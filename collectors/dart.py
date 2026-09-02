from __future__ import annotations

import io
import os
import time
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass

import requests

from config import WATCHLIST

DART_BASE_URL = "https://opendart.fss.or.kr/api"
DART_REQUEST_DELAY = 0.25
REPORT_CODE_ORDER = ("11014", "11013", "11012", "11011")
REPORT_CODE_LABELS = {
    "11011": "사업보고서",
    "11012": "반기보고서",
    "11013": "1분기보고서",
    "11014": "3분기보고서",
}
INDICATOR_CLASS_CODES = ("M210000", "M220000", "M230000", "M240000")

CORP_CODE_FALLBACK = {
    "005930": "00126380",
    "000660": "00164779",
    "005380": "00164742",
    "035420": "00266961",
    "042700": "00356370",
    "036930": "00261285",
    "058470": "00358040",
    "403870": "01596425",
    "357780": "01467451",
}


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _calc_ratio(price: float | None, base: float | None) -> str | None:
    if price is None or base is None or base <= 0:
        return None
    return f"{price / base:.2f}"


@dataclass
class FinancialHighlight:
    name: str
    stock_code: str
    period: str
    revenue: str | None = None
    operating_profit: str | None = None
    net_income: str | None = None
    roe: str | None = None
    per: str | None = None
    pbr: str | None = None
    eps: str | None = None
    debt_ratio: str | None = None

    def format_block(self) -> str:
        lines = [f"- {self.name} ({self.stock_code}, {self.period})"]
        metrics = [
            ("매출액", self.revenue),
            ("영업이익", self.operating_profit),
            ("당기순이익", self.net_income),
            ("ROE", self.roe),
            ("PER", self.per),
            ("PBR", self.pbr),
            ("EPS", self.eps),
            ("부채비율", self.debt_ratio),
        ]
        metric_text = " / ".join(
            f"{label} {value}" for label, value in metrics if value is not None
        )
        if metric_text:
            lines.append(f"  {metric_text}")
        else:
            lines.append("  재무 지표 데이터 없음")
        return "\n".join(lines)


def _get_api_key() -> str:
    return os.environ.get("DART_API_KEY", "")


def _dart_get(endpoint: str, params: dict) -> dict:
    response = requests.get(f"{DART_BASE_URL}/{endpoint}", params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    status = payload.get("status")
    if status == "000":
        return payload
    if status in {"013", "014"}:
        return {"list": []}
    message = payload.get("message", "알 수 없는 오류")
    raise RuntimeError(message)


def _fetch_corp_code_map(stock_codes: list[str]) -> dict[str, str]:
    api_key = _get_api_key()
    if not api_key:
        return {}

    try:
        response = requests.get(
            f"{DART_BASE_URL}/corpCode.xml",
            params={"crtfc_key": api_key},
            timeout=60,
        )
        response.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            xml_name = archive.namelist()[0]
            with archive.open(xml_name) as xml_file:
                root = ET.parse(xml_file).getroot()

        mapping: dict[str, str] = {}
        for item in root.findall("list"):
            stock_code = (item.findtext("stock_code") or "").strip()
            corp_code = (item.findtext("corp_code") or "").strip()
            if stock_code in stock_codes and corp_code:
                mapping[stock_code] = corp_code
        return mapping
    except Exception as exc:
        print(f"DART corp_code 목록 조회 실패: {exc}")
        return {}


def _resolve_corp_code(stock_code: str, corp_code_map: dict[str, str]) -> str | None:
    return corp_code_map.get(stock_code) or CORP_CODE_FALLBACK.get(stock_code)


def _format_amount(value: str) -> str:
    try:
        amount = int(float(value.replace(",", "")))
    except (TypeError, ValueError):
        return value

    if abs(amount) >= 100_000_000:
        return f"{amount / 100_000_000:,.0f}억원"
    if abs(amount) >= 10_000:
        return f"{amount / 10_000:,.0f}만원"
    return f"{amount:,}원"


def _format_ratio(value: str | float | None, suffix: str = "") -> str | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        return text or None

    if suffix == "%":
        return f"{number:.2f}%"
    return f"{number:.2f}{suffix}"


def _pick_indicator(indicators: dict[str, str], keywords: tuple[str, ...]) -> str | None:
    for name, value in indicators.items():
        if any(keyword in name for keyword in keywords):
            if value not in ("", "-", "N/A"):
                return _format_ratio(value, "%") if "비율" in name or "ROE" in name or "ROA" in name else value
    return None


def _pick_account(accounts: dict[str, str], keywords: tuple[str, ...]) -> str | None:
    for name, value in accounts.items():
        if any(keyword in name for keyword in keywords):
            return value
    return None


def _fetch_indicators(corp_code: str, year: int, reprt_code: str) -> dict[str, str]:
    indicators: dict[str, str] = {}

    for idx_cl_code in INDICATOR_CLASS_CODES:
        try:
            payload = _dart_get(
                "fnlttCmpnyIndx.json",
                {
                    "crtfc_key": _get_api_key(),
                    "corp_code": corp_code,
                    "bsns_year": str(year),
                    "reprt_code": reprt_code,
                    "idx_cl_code": idx_cl_code,
                },
            )
            for item in payload.get("list", []):
                name = item.get("idx_nm", "").strip()
                value = str(item.get("idx_val", "")).strip()
                if name and value:
                    indicators[name] = value
        except Exception as exc:
            print(
                f"DART 지표 조회 실패 ({corp_code}, {year}, {reprt_code}, "
                f"{idx_cl_code}): {exc}"
            )
        time.sleep(DART_REQUEST_DELAY)

    return indicators


def _fetch_accounts(corp_code: str, year: int, reprt_code: str) -> dict[str, str]:
    for fs_div in ("CFS", "OFS"):
        try:
            payload = _dart_get(
                "fnlttSinglAcnt.json",
                {
                    "crtfc_key": _get_api_key(),
                    "corp_code": corp_code,
                    "bsns_year": str(year),
                    "reprt_code": reprt_code,
                    "fs_div": fs_div,
                },
            )
            accounts: dict[str, str] = {}
            for item in payload.get("list", []):
                name = item.get("account_nm", "").replace(" ", "")
                if name in accounts:
                    continue
                amount = str(item.get("thstrm_amount", "")).strip()
                if amount:
                    accounts[name] = amount
            if accounts:
                return accounts
        except Exception as exc:
            print(f"DART 계정 조회 실패 ({corp_code}, {year}, {reprt_code}, {fs_div}): {exc}")
        time.sleep(DART_REQUEST_DELAY)

    return {}


def _fetch_market_ratios(
    stock_code: str,
    price: float | None,
    eps_raw: str | None,
    bps_raw: str | None,
    indicators: dict[str, str],
) -> tuple[str | None, str | None]:
    eps_value = _to_float(eps_raw) or _to_float(
        _pick_indicator(indicators, ("EPS", "주당순이익"))
    )
    bps_value = _to_float(bps_raw) or _to_float(
        _pick_indicator(indicators, ("BPS", "주당순자산", "주당순자산가치"))
    )

    per = _calc_ratio(price, eps_value)
    pbr = _calc_ratio(price, bps_value)
    return per, pbr


def _fetch_highlight_for_stock(
    name: str,
    stock_code: str,
    corp_code: str,
    current_price: float | None = None,
) -> FinancialHighlight | None:
    current_year = time.localtime().tm_year

    for year in (current_year, current_year - 1):
        for reprt_code in REPORT_CODE_ORDER:
            accounts = _fetch_accounts(corp_code, year, reprt_code)
            indicators = _fetch_indicators(corp_code, year, reprt_code)

            if not indicators and not accounts:
                continue

            period = f"{year} {REPORT_CODE_LABELS[reprt_code]}"
            revenue_raw = _pick_account(accounts, ("매출액", "영업수익"))
            op_raw = _pick_account(accounts, ("영업이익",))
            net_raw = _pick_account(accounts, ("당기순이익", "분기순이익", "연결당기순이익"))

            eps_raw = _pick_indicator(indicators, ("EPS", "주당순이익"))
            bps_raw = _pick_indicator(indicators, ("BPS", "주당순자산", "주당순자산가치"))
            per, pbr = _fetch_market_ratios(
                stock_code,
                current_price,
                eps_raw,
                bps_raw,
                indicators,
            )

            return FinancialHighlight(
                name=name,
                stock_code=stock_code,
                period=period,
                revenue=_format_amount(revenue_raw) if revenue_raw else None,
                operating_profit=_format_amount(op_raw) if op_raw else None,
                net_income=_format_amount(net_raw) if net_raw else None,
                roe=_pick_indicator(indicators, ("ROE", "자기자본이익률")),
                per=per,
                pbr=pbr,
                eps=eps_raw,
                debt_ratio=_pick_indicator(indicators, ("부채비율",)),
            )

    return None


def fetch_financial_highlights(
    prices_by_stock: dict[str, float] | None = None,
) -> list[FinancialHighlight]:
    api_key = _get_api_key()
    if not api_key:
        print("경고: DART_API_KEY 없음 - 재무 데이터를 생략합니다.")
        return []

    prices_by_stock = prices_by_stock or {}

    stock_codes = [item["fdr"] for item in WATCHLIST]
    corp_code_map = _fetch_corp_code_map(stock_codes)
    highlights: list[FinancialHighlight] = []

    for item in WATCHLIST:
        stock_code = item["fdr"]
        corp_code = _resolve_corp_code(stock_code, corp_code_map)
        if not corp_code:
            print(f"DART corp_code 없음: {item['name']} ({stock_code})")
            continue

        highlight = _fetch_highlight_for_stock(
            item["name"],
            stock_code,
            corp_code,
            prices_by_stock.get(stock_code),
        )
        if highlight:
            highlights.append(highlight)
            print(f"DART 재무 수집 완료: {item['name']}")
        else:
            print(f"DART 재무 데이터 없음: {item['name']}")

        time.sleep(DART_REQUEST_DELAY)

    print(f"DART 재무 수집 성공: {len(highlights)}/{len(WATCHLIST)}")
    return highlights


def format_financial_data(highlights: list[FinancialHighlight]) -> str:
    if not highlights:
        return "재무 데이터 없음 (DART API 미설정 또는 수집 실패)"

    lines = ["📋 재무 하이라이트 (DART Open API, 최근 공시 기준)"]
    lines.extend(highlight.format_block() for highlight in highlights)
    return "\n".join(lines)
