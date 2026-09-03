from __future__ import annotations

import ast
import json
import re
import os
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
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Referer": "https://finance.naver.com/",
}

NAVER_INDEX_SYMBOLS = {
    "KS11": "KOSPI",
    "KQ11": "KOSDAQ",
}

NAVER_WORLD_INDEX = {
    "^GSPC": (".INX", ".GSPC"),
    "^IXIC": (".IXIC",),
    "^DJI": (".DJI",),
    "^N225": (".N225",),
    "^HSI": (".HSI",),
    "^VIX": (".VIX", ".VXN"),
}

NAVER_COMMODITY = {
    "GC=F": "CMDT_GC",
    "CL=F": "OIL_CL",
}

STOOQ_SYMBOLS = {
    "^GSPC": "^spx",
    "^IXIC": "^ndq",
    "^DJI": "^dji",
    "^N225": "^nkx",
    "^HSI": "^hsi",
    "^VIX": "^vix",
    "USDKRW=X": "usdkrw",
    "EURKRW=X": "eurkrw",
    "JPYKRW=X": "jpykrw",
    "GC=F": "gc.f",
    "CL=F": "cl.f",
    "BTC-USD": "btcusd",
    "^TNX": "10usy.b",
    "^KS11": "^kospi",
    "^KQ11": "^kosdaq",
}

FX_PAIRS = {
    "USDKRW=X": ("USD", "KRW"),
    "EURKRW=X": ("EUR", "KRW"),
    "JPYKRW=X": ("JPY", "KRW"),
}

FRED_SERIES = {
    "^TNX": "DGS10",
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

    if yf in NAVER_WORLD_INDEX:
        for code in NAVER_WORLD_INDEX[yf]:
            close = _fetch_naver_world_index(code, lookback_days)
            if close is not None:
                return close, "Naver"

    if yf in NAVER_COMMODITY:
        close = _fetch_naver_commodity(NAVER_COMMODITY[yf], lookback_days)
        if close is not None:
            return close, "Naver"

    if yf in FRED_SERIES:
        close = _fetch_fred(FRED_SERIES[yf], lookback_days)
        if close is not None:
            return close, "FRED"

    if yf in STOOQ_SYMBOLS:
        close = _fetch_stooq(STOOQ_SYMBOLS[yf], lookback_days)
        if close is not None:
            return close, "Stooq"

    if yf in FX_PAIRS:
        close = _fetch_frankfurter(*FX_PAIRS[yf], lookback_days)
        if close is not None:
            return close, "Frankfurter"

    if yf == "BTC-USD":
        close = _fetch_coingecko_btc(lookback_days)
        if close is not None:
            return close, "CoinGecko"

    if yf in {"GC=F", "CL=F"}:
        close = _fetch_stooq("xauusd" if yf == "GC=F" else "cl.f", lookback_days)
        if close is not None:
            return close, "Stooq"

    if yf and os.environ.get("GITHUB_ACTIONS") != "true":
        close = _fetch_yahoo_chart(yf, lookback_days)
        if close is not None:
            return close, "YahooChart"

    return None, ""


def _fetch_naver_stock(code: str, lookback_days: int) -> pd.Series | None:
    close = _fetch_naver_fchart(code, lookback_days)
    if close is not None:
        return close
    return _fetch_naver_mobile_prices(
        f"https://m.stock.naver.com/api/stock/{code}/price", lookback_days
    )


def _fetch_naver_index(symbol: str, lookback_days: int) -> pd.Series | None:
    close = _fetch_naver_fchart(symbol, lookback_days)
    if close is not None:
        return close
    return _fetch_naver_mobile_prices(
        f"https://m.stock.naver.com/api/index/{symbol}/price", lookback_days
    )


def _fetch_naver_world_index(code: str, lookback_days: int) -> pd.Series | None:
    candle_count = max(lookback_days, 90)
    endpoints = (
        (
            f"https://api.stock.naver.com/chart/foreign/index/{code}",
            {"periodType": "day", "candleCount": candle_count},
        ),
        (
            f"https://m.stock.naver.com/front-api/product/chart/foreign/index/{code}",
            {"periodType": "day", "maxCount": candle_count},
        ),
        (
            f"https://api.stock.naver.com/index/{code}/price",
            {"page": 1, "pageSize": candle_count},
        ),
        (
            f"https://m.stock.naver.com/api/index/{code}/price",
            {"page": 1, "pageSize": candle_count},
        ),
    )

    for url, params in endpoints:
        close = _fetch_naver_json_series(url, params)
        if close is not None:
            return close
    return None


def _fetch_naver_commodity(code: str, lookback_days: int) -> pd.Series | None:
    page_size = max(lookback_days, 90)
    endpoints = (
        (
            f"https://api.stock.naver.com/marketindex/oilgold/{code}/price",
            {"page": 1, "pageSize": page_size},
        ),
        (
            f"https://m.stock.naver.com/front-api/marketIndex/prices/{code}",
            {"page": 1, "pageSize": page_size},
        ),
        (
            f"https://api.stock.naver.com/marketindex/{code}/price",
            {"page": 1, "pageSize": page_size},
        ),
    )

    for url, params in endpoints:
        close = _fetch_naver_json_series(url, params)
        if close is not None:
            return close
    return None


def _fetch_naver_json_series(url: str, params: dict) -> pd.Series | None:
    try:
        response = _http().get(url, params=params, timeout=20)
        if response.status_code != 200:
            return None
        payload = response.json()
    except Exception as exc:
        print(f"Naver JSON 실패 ({url}): {exc}")
        return None

    items = _extract_price_items(payload)
    parsed: list[tuple[datetime, float]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        date_raw = (
            item.get("localTradedAt")
            or item.get("localDateTime")
            or item.get("localDate")
            or item.get("bizdate")
            or item.get("date")
            or item.get("trdDd")
        )
        close = _to_float(
            item.get("closePrice")
            or item.get("close")
            or item.get("closeVal")
            or item.get("lastPrice")
            or item.get("nv")
            or item.get("value")
        )
        if not date_raw or close is None:
            continue
        try:
            parsed.append((_parse_date(date_raw), close))
        except ValueError:
            continue

    return _series_from_rows(parsed)


def _extract_price_items(payload: object) -> list:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []

    for key in (
        "priceInfos",
        "prices",
        "candleDataList",
        "chartDataList",
        "data",
        "result",
    ):
        value = payload.get(key)
        if isinstance(value, list) and value:
            return value
        if isinstance(value, dict):
            nested = _extract_price_items(value)
            if nested:
                return nested
    return []


def _fetch_naver_fchart(symbol: str, lookback_days: int) -> pd.Series | None:
    end = datetime.now()
    start = end - timedelta(days=lookback_days)
    urls = (
        "https://api.finance.naver.com/siseJson.naver",
        "https://fchart.stock.naver.com/siseJson.nhn",
    )
    params = {
        "symbol": symbol,
        "requestType": "1",
        "startTime": start.strftime("%Y%m%d"),
        "endTime": end.strftime("%Y%m%d"),
        "timeframe": "day",
    }

    for url in urls:
        try:
            response = _http().get(url, params=params, timeout=20)
            response.raise_for_status()
            rows = _parse_naver_fchart(response.text)
            if rows is not None:
                return rows
        except Exception as exc:
            print(f"Naver fchart 실패 ({symbol}, {url}): {exc}")

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
        date_raw = str(row[0])
        close = _to_float(row[4] if len(row) > 4 else None)
        if close is None:
            continue
        try:
            parsed.append((_parse_date(date_raw), close))
        except ValueError:
            continue

    return _series_from_rows(parsed)


def _parse_date(value: object) -> datetime:
    text = re.sub(r"[./]", "-", str(value).strip())
    if "T" in text:
        text = text.split("T", 1)[0]
    for size, fmt in ((10, "%Y-%m-%d"), (8, "%Y%m%d")):
        try:
            return datetime.strptime(text[:size], fmt)
        except ValueError:
            continue
    raise ValueError(f"지원하지 않는 날짜: {value}")


def _fetch_naver_mobile_prices(url: str, lookback_days: int) -> pd.Series | None:
    return _fetch_naver_json_series(
        url, {"pageSize": max(lookback_days, 90), "page": 1}
    )


def _fetch_stooq(symbol: str, lookback_days: int) -> pd.Series | None:
    end = datetime.now()
    start = end - timedelta(days=lookback_days + 20)
    hosts = (
        "https://stooq.com/q/d/l/",
        "https://stooq.pl/q/d/l/",
    )
    params = {
        "s": symbol,
        "i": "d",
        "d1": start.strftime("%Y%m%d"),
        "d2": end.strftime("%Y%m%d"),
    }

    for url in hosts:
        try:
            response = _http().get(url, params=params, timeout=20)
            text = response.text.strip()
            if response.status_code != 200 or not text:
                continue
            first_line = text.splitlines()[0]
            if "Date" not in first_line:
                print(f"Stooq 비정상 응답 ({symbol}): {first_line[:80]}")
                continue

            frame = pd.read_csv(StringIO(text))
            if frame.empty or "Close" not in frame.columns:
                continue

            frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
            close = frame.dropna(subset=["Date", "Close"]).set_index("Date")["Close"]
            close = close[close > 0].astype(float).sort_index()
            if not close.empty:
                return close
        except Exception as exc:
            print(f"Stooq 실패 ({symbol}, {url}): {exc}")

    return None


def _fetch_fred(series_id: str, lookback_days: int) -> pd.Series | None:
    try:
        response = _http().get(
            "https://fred.stlouisfed.org/graph/fredgraph.csv",
            params={"id": series_id},
            timeout=20,
        )
        response.raise_for_status()
        frame = pd.read_csv(StringIO(response.text))
        if frame.empty or len(frame.columns) < 2:
            return None

        date_col, value_col = frame.columns[:2]
        frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
        frame[value_col] = frame[value_col].map(_to_float)
        frame = frame.dropna(subset=[date_col, value_col]).sort_values(date_col)
        if lookback_days:
            cutoff = datetime.now() - timedelta(days=lookback_days + 20)
            frame = frame[frame[date_col] >= cutoff]
        series = frame.set_index(date_col)[value_col].astype(float)
        return series if not series.empty else None
    except Exception as exc:
        print(f"FRED 실패 ({series_id}): {exc}")
        return None


def _fetch_yahoo_chart(ticker: str, lookback_days: int) -> pd.Series | None:
    range_map = "6mo" if lookback_days >= 90 else "3mo"
    hosts = (
        "https://query1.finance.yahoo.com/v8/finance/chart/",
        "https://query2.finance.yahoo.com/v8/finance/chart/",
    )

    for host in hosts:
        try:
            response = _http().get(
                f"{host}{ticker}",
                params={"interval": "1d", "range": range_map},
                timeout=20,
            )
            if response.status_code != 200:
                continue
            payload = response.json()
            result = (payload.get("chart") or {}).get("result") or []
            if not result:
                continue
            item = result[0]
            timestamps = item.get("timestamp") or []
            closes = (
                ((item.get("indicators") or {}).get("quote") or [{}])[0].get("close")
                or []
            )
            parsed = []
            for ts, close in zip(timestamps, closes):
                price = _to_float(close)
                if price is None:
                    continue
                parsed.append(
                    (
                        datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None),
                        price,
                    )
                )
            series = _series_from_rows(parsed)
            if series is not None:
                return series
        except Exception as exc:
            print(f"YahooChart 실패 ({ticker}): {exc}")

    return None


def _fetch_frankfurter(base: str, quote: str, lookback_days: int) -> pd.Series | None:
    end = datetime.now()
    start = end - timedelta(days=lookback_days)
    url = (
        f"https://api.frankfurter.app/{start:%Y-%m-%d}..{end:%Y-%m-%d}"
        f"?from={base}&to={quote}"
    )
    try:
        response = _http().get(url, timeout=20)
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
            params={
                "vs_currency": "usd",
                "days": min(lookback_days, 180),
            },
            timeout=20,
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
