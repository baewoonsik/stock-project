from __future__ import annotations

import ast
import json
import time
from datetime import datetime, timedelta, timezone
from io import StringIO

import pandas as pd
import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

NAVER_INDEX_SYMBOLS = {
    "KS11": "KOSPI",
    "KQ11": "KOSDAQ",
}

# 브라우저에서 확인된 네이버 해외지수 JSON 심볼
NAVER_WORLD_JSON = {
    "^GSPC": "SPI@SPX",
    "^IXIC": "NAS@IXIC",
    "^DJI": "DJI@DJI",
    "^N225": "NII@NI225",
    "^HSI": "HSI@HSI",
}

NAVER_MARKETINDEX_HTML = {
    "GC=F": (
        "https://finance.naver.com/marketindex/worldDailyQuote.naver"
        "?marketindexCd=CMDT_GC&fdtc=2&page={page}"
    ),
    "CL=F": (
        "https://finance.naver.com/marketindex/worldDailyQuote.naver"
        "?marketindexCd=OIL_CL&fdtc=2&page={page}"
    ),
}

FX_PAIRS = {
    "USDKRW=X": ("USD", "KRW"),
    "EURKRW=X": ("EUR", "KRW"),
    "JPYKRW=X": ("JPY", "KRW"),
}

_session: requests.Session | None = None


def _http() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
    return _session


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("%", "").strip()
    if not text or text in {"-", "N/A", "null", "."}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date(value: object) -> datetime:
    text = re_sub_date(str(value).strip())
    for size, fmt in ((10, "%Y-%m-%d"), (8, "%Y%m%d")):
        try:
            return datetime.strptime(text[:size], fmt)
        except ValueError:
            continue
    raise ValueError(f"지원하지 않는 날짜: {value}")


def re_sub_date(text: str) -> str:
    text = text.replace("/", "-").replace(".", "-")
    if "T" in text:
        text = text.split("T", 1)[0]
    return text.split(" ")[0]


def _series_from_rows(rows: list[tuple[datetime, float]]) -> pd.Series | None:
    if not rows:
        return None
    frame = pd.DataFrame(rows, columns=["date", "close"]).dropna()
    if frame.empty:
        return None
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date").drop_duplicates("date")
    series = frame.set_index("date")["close"].astype(float)
    return series if not series.empty else None


def fetch_close_http(
    name: str, fdr: str | None, yf: str | None, lookback_days: int
) -> tuple[pd.Series | None, str]:
    if fdr and str(fdr).isdigit() and len(str(fdr)) == 6:
        close = _fetch_naver_stock(str(fdr), lookback_days)
        if close is not None:
            return close, "Naver"

    if fdr in NAVER_INDEX_SYMBOLS:
        close = _fetch_naver_index(NAVER_INDEX_SYMBOLS[fdr], lookback_days)
        if close is not None:
            return close, "Naver"

    if yf in NAVER_WORLD_JSON:
        close = _fetch_naver_world_day_json(NAVER_WORLD_JSON[yf], lookback_days)
        if close is not None:
            return close, "NaverWorld"

    if yf == "^VIX":
        close = _fetch_cboe_vix(lookback_days)
        if close is not None:
            return close, "CBOE"
        close = _fetch_daum_days(".VIX", lookback_days)
        if close is not None:
            return close, "Daum"

    if yf in NAVER_MARKETINDEX_HTML:
        close = _fetch_naver_html_pages(NAVER_MARKETINDEX_HTML[yf], lookback_days)
        if close is not None:
            return close, "NaverMarket"

    if yf == "^TNX":
        close = _fetch_fred_dgs10(lookback_days)
        if close is not None:
            return close, "FRED"
        close = _fetch_treasury_10y(lookback_days)
        if close is not None:
            return close, "Treasury"

    if yf in FX_PAIRS:
        close = _fetch_frankfurter(*FX_PAIRS[yf], lookback_days)
        if close is not None:
            return close, "Frankfurter"

    if yf == "BTC-USD":
        close = _fetch_coingecko_btc(lookback_days)
        if close is not None:
            return close, "CoinGecko"

    return None, ""


def _fetch_naver_stock(code: str, lookback_days: int) -> pd.Series | None:
    close = _fetch_naver_fchart(code, lookback_days)
    if close is not None:
        return close
    return _fetch_json_price_list(
        f"https://m.stock.naver.com/api/stock/{code}/price",
        {"pageSize": max(lookback_days, 90), "page": 1},
    )


def _fetch_naver_index(symbol: str, lookback_days: int) -> pd.Series | None:
    close = _fetch_naver_fchart(symbol, lookback_days)
    if close is not None:
        return close
    return _fetch_json_price_list(
        f"https://m.stock.naver.com/api/index/{symbol}/price",
        {"pageSize": max(lookback_days, 90), "page": 1},
    )


def _fetch_naver_fchart(symbol: str, lookback_days: int) -> pd.Series | None:
    end = datetime.now()
    start = end - timedelta(days=lookback_days)
    for url in (
        "https://api.finance.naver.com/siseJson.naver",
        "https://fchart.stock.naver.com/siseJson.nhn",
    ):
        try:
            response = _http().get(
                url,
                params={
                    "symbol": symbol,
                    "requestType": "1",
                    "startTime": start.strftime("%Y%m%d"),
                    "endTime": end.strftime("%Y%m%d"),
                    "timeframe": "day",
                },
                timeout=30,
                headers={**HEADERS, "Referer": "https://finance.naver.com/"},
            )
            if response.status_code != 200:
                continue
            series = _parse_naver_fchart(response.text)
            if series is not None:
                return series
        except Exception as exc:
            print(f"Naver fchart 실패 ({symbol}): {exc}")
    return None


def _parse_naver_fchart(text: str) -> pd.Series | None:
    payload = text.strip()
    if not payload or payload[0] not in "[{":
        return None
    try:
        rows = json.loads(payload)
    except json.JSONDecodeError:
        try:
            rows = ast.literal_eval(payload)
        except (SyntaxError, ValueError):
            return None
    if not isinstance(rows, list) or len(rows) < 2:
        return None

    parsed: list[tuple[datetime, float]] = []
    for row in rows[1:]:
        if not row:
            continue
        close = _to_float(row[4] if len(row) > 4 else None)
        if close is None:
            continue
        try:
            parsed.append((_parse_date(row[0]), close))
        except ValueError:
            continue
    return _series_from_rows(parsed)


def _fetch_json_price_list(url: str, params: dict) -> pd.Series | None:
    try:
        response = _http().get(
            url,
            params=params,
            timeout=30,
            headers={**HEADERS, "Referer": "https://m.stock.naver.com/"},
        )
        if response.status_code != 200:
            return None
        payload = response.json()
    except Exception:
        return None

    items = payload if isinstance(payload, list) else []
    if isinstance(payload, dict):
        for key in ("priceInfos", "prices", "candleDataList", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                items = value
                break

    parsed: list[tuple[datetime, float]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        date_raw = (
            item.get("localTradedAt")
            or item.get("localDateTime")
            or item.get("date")
            or item.get("bizdate")
        )
        close = _to_float(
            item.get("closePrice")
            or item.get("close")
            or item.get("tradePrice")
            or item.get("lastPrice")
        )
        if not date_raw or close is None:
            continue
        try:
            parsed.append((_parse_date(date_raw), close))
        except ValueError:
            continue
    return _series_from_rows(parsed)


def _fetch_naver_world_day_json(symbol: str, lookback_days: int) -> pd.Series | None:
    """네이버 해외지수 일별 JSON. 페이지당 약 10개."""
    max_pages = min(15, max(3, lookback_days // 8 + 1))
    parsed: list[tuple[datetime, float]] = []

    for page in range(1, max_pages + 1):
        url = "https://finance.naver.com/world/worldDayListJson.naver"
        try:
            response = _http().get(
                url,
                params={"symbol": symbol, "fdtc": "0", "page": page},
                timeout=30,
                headers={**HEADERS, "Referer": f"https://finance.naver.com/world/sise.naver?symbol={symbol}"},
            )
            if response.status_code != 200:
                print(f"NaverWorld HTTP {response.status_code} ({symbol} p{page})")
                break
            rows = response.json()
            if not isinstance(rows, list) or not rows:
                break
            for item in rows:
                close = _to_float(item.get("clos"))
                date_raw = item.get("xymd")
                if close is None or not date_raw:
                    continue
                parsed.append((_parse_date(date_raw), close))
            if len(rows) < 10:
                break
            time.sleep(0.1)
        except Exception as exc:
            print(f"NaverWorld 실패 ({symbol} p{page}): {exc}")
            break

    return _series_from_rows(parsed)


def _fetch_naver_html_pages(url_template: str, lookback_days: int) -> pd.Series | None:
    max_pages = min(10, max(2, lookback_days // 20 + 1))
    parsed: list[tuple[datetime, float]] = []

    for page in range(1, max_pages + 1):
        url = url_template.format(page=page)
        try:
            response = _http().get(
                url,
                timeout=30,
                headers={**HEADERS, "Referer": "https://finance.naver.com/marketindex/"},
            )
            if response.status_code != 200 or "<table" not in response.text:
                break
            tables = pd.read_html(StringIO(response.text))
        except Exception as exc:
            print(f"NaverMarket HTML 실패 (p{page}): {exc}")
            break

        page_rows: list[tuple[datetime, float]] = []
        for table in tables:
            if table.shape[1] < 2:
                continue
            for _, item in table.iterrows():
                close = _to_float(item.iloc[1])
                if close is None:
                    continue
                try:
                    page_rows.append((_parse_date(item.iloc[0]), close))
                except ValueError:
                    continue
            if page_rows:
                break
        if not page_rows:
            break
        parsed.extend(page_rows)
        time.sleep(0.1)

    return _series_from_rows(parsed)


def _fetch_daum_days(symbol: str, lookback_days: int) -> pd.Series | None:
    try:
        response = _http().get(
            f"https://finance.daum.net/api/charts/{symbol}/days",
            params={"limit": max(lookback_days, 120), "adjusted": "true"},
            timeout=30,
            headers={
                **HEADERS,
                "Referer": f"https://finance.daum.net/global/quotes/{symbol}",
            },
        )
        if response.status_code != 200:
            return None
        items = response.json().get("data")
        if not isinstance(items, list):
            return None
        parsed = []
        for item in items:
            close = _to_float(item.get("tradePrice") or item.get("closePrice"))
            date_raw = item.get("date") or item.get("candleTime")
            if close is None or not date_raw:
                continue
            parsed.append((_parse_date(date_raw), close))
        return _series_from_rows(parsed)
    except Exception as exc:
        print(f"Daum 실패 ({symbol}): {exc}")
        return None


def _fetch_cboe_vix(lookback_days: int) -> pd.Series | None:
    urls = (
        "https://cdn.cboe.com/api/global/delayed_quotes/charts/historical/VIX.json",
        "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX.json",
    )
    for url in urls:
        try:
            response = _http().get(url, timeout=30)
            if response.status_code != 200:
                continue
            payload = response.json()
            items = payload.get("data") or payload.get("price") or payload
            if isinstance(items, dict):
                items = items.get("data") or items.get("prices") or []
            if not isinstance(items, list):
                continue
            parsed = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                close = _to_float(
                    item.get("close")
                    or item.get("price")
                    or item.get("last")
                    or item.get("value")
                )
                date_raw = (
                    item.get("date")
                    or item.get("timestamp")
                    or item.get("price_date")
                )
                if close is None or not date_raw:
                    continue
                try:
                    parsed.append((_parse_date(date_raw), close))
                except ValueError:
                    continue
            series = _series_from_rows(parsed)
            if series is not None:
                cutoff = datetime.now() - timedelta(days=lookback_days + 20)
                series = series[series.index >= cutoff]
                if not series.empty:
                    return series
        except Exception as exc:
            print(f"CBOE VIX 실패: {exc}")

    # 최신 호가만이라도 확보
    try:
        response = _http().get(
            "https://cdn.cboe.com/api/global/delayed_quotes/quotes/VIX.json",
            timeout=30,
        )
        if response.status_code == 200:
            data = response.json().get("data") or {}
            price = _to_float(
                data.get("current_price") or data.get("price") or data.get("last_price")
            )
            if price is not None:
                today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                return pd.Series([price], index=[today])
    except Exception as exc:
        print(f"CBOE VIX quote 실패: {exc}")
    return None


def _fetch_fred_dgs10(lookback_days: int) -> pd.Series | None:
    for attempt, delay in enumerate((1, 3, 6), start=1):
        try:
            response = _http().get(
                "https://fred.stlouisfed.org/graph/fredgraph.csv",
                params={"id": "DGS10"},
                timeout=60,
            )
            response.raise_for_status()
            frame = pd.read_csv(StringIO(response.text))
            if frame.empty or len(frame.columns) < 2:
                return None
            date_col, value_col = frame.columns[:2]
            frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
            frame[value_col] = frame[value_col].map(_to_float)
            frame = frame.dropna(subset=[date_col, value_col]).sort_values(date_col)
            cutoff = datetime.now() - timedelta(days=lookback_days + 20)
            frame = frame[frame[date_col] >= cutoff]
            series = frame.set_index(date_col)[value_col].astype(float)
            if not series.empty:
                return series
        except Exception as exc:
            print(f"FRED 실패 (시도 {attempt}/3): {exc}")
            time.sleep(delay)
    return None


def _fetch_treasury_10y(lookback_days: int) -> pd.Series | None:
    """US Treasury Fiscal Data API - 일별 10년물."""
    try:
        response = _http().get(
            "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/"
            "v2/accounting/od/avg_interest_rates",
            params={
                "filter": "security_desc:eq:Treasury Notes,security_type_desc:eq:Marketable",
                "sort": "-record_date",
                "page[size]": 100,
            },
            timeout=45,
        )
        # avg_interest_rates may not be daily 10Y; try yield curve endpoint style dump
        if response.status_code != 200:
            return None
    except Exception:
        pass

    year = datetime.now().year
    urls = (
        f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        f"daily-treasury-rates.csv/{year}/all"
        f"?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv",
        f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        f"daily-treasury-rates.csv/all/{year}"
        f"?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv",
    )
    for url in urls:
        try:
            response = _http().get(url, timeout=45)
            if response.status_code != 200 or "Date" not in response.text[:200]:
                continue
            frame = pd.read_csv(StringIO(response.text))
            cols = {str(c).strip(): c for c in frame.columns}
            date_col = cols.get("Date")
            ten_col = None
            for key, original in cols.items():
                if key.startswith("10") and "Yr" in key.replace(" ", ""):
                    ten_col = original
                    break
                if key in {"10 Yr", "10 Yr.", "10-Year"}:
                    ten_col = original
                    break
            if date_col is None or ten_col is None:
                # common layout: Date, 1 Mo, ... 10 Yr ...
                for c in frame.columns:
                    if "10" in str(c) and "Yr" in str(c):
                        ten_col = c
                        break
                if "Date" in frame.columns:
                    date_col = "Date"
            if date_col is None or ten_col is None:
                continue
            frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
            frame[ten_col] = frame[ten_col].map(_to_float)
            frame = frame.dropna(subset=[date_col, ten_col]).sort_values(date_col)
            cutoff = datetime.now() - timedelta(days=lookback_days + 20)
            frame = frame[frame[date_col] >= cutoff]
            series = frame.set_index(date_col)[ten_col].astype(float)
            if not series.empty:
                return series
        except Exception as exc:
            print(f"Treasury 실패: {exc}")
    return None


def _fetch_frankfurter(base: str, quote: str, lookback_days: int) -> pd.Series | None:
    end = datetime.now()
    start = end - timedelta(days=lookback_days)
    url = (
        f"https://api.frankfurter.app/{start:%Y-%m-%d}..{end:%Y-%m-%d}"
        f"?from={base}&to={quote}"
    )
    try:
        response = _http().get(url, timeout=30)
        response.raise_for_status()
        rates = response.json().get("rates", {})
        parsed = [
            (datetime.strptime(day, "%Y-%m-%d"), _to_float(values.get(quote)))
            for day, values in rates.items()
            if isinstance(values, dict)
        ]
        parsed = [(day, price) for day, price in parsed if price is not None]
        return _series_from_rows(parsed)
    except Exception as exc:
        print(f"Frankfurter 실패 ({base}/{quote}): {exc}")
        return None


def _fetch_coingecko_btc(lookback_days: int) -> pd.Series | None:
    try:
        response = _http().get(
            "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
            params={"vs_currency": "usd", "days": min(lookback_days, 180)},
            timeout=30,
        )
        response.raise_for_status()
        points = response.json().get("prices", [])
        parsed = [
            (
                datetime.fromtimestamp(ts / 1000, tz=timezone.utc).replace(tzinfo=None),
                _to_float(price),
            )
            for ts, price in points
        ]
        parsed = [(day, price) for day, price in parsed if price is not None]
        return _series_from_rows(parsed)
    except Exception as exc:
        print(f"CoinGecko 실패 (BTC): {exc}")
        return None
