from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from collectors.price_sources import fetch_close_http
from config import MARKET_INDICES, WATCHLIST

FDR_LOOKBACK_DAYS = 14
FDR_TREND_LOOKBACK_DAYS = 120
FDR_REQUEST_DELAY = 0.4
FDR_DATA_SOURCES = (None, "Naver", "Yahoo")
YFINANCE_RETRY_DELAYS = (5, 12, 20)
YFINANCE_ONLY_TICKERS = {"^VIX", "GC=F", "^TNX"}
HTTP_REQUEST_DELAY = 0.2

_close_series_cache: dict[tuple[str, int], pd.Series | None] = {}
_http_close_cache: dict[str, tuple[pd.Series, str]] = {}
_http_prefetched = False


def _is_ci() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def _all_instruments() -> list[dict]:
    return list(MARKET_INDICES) + list(WATCHLIST)


def _prefetch_all_http() -> None:
    global _http_prefetched

    if _http_prefetched:
        return

    instruments = _all_instruments()
    print(f"HTTP 시세 prefetch 시작: {len(instruments)}개 (Yahoo 미사용)")

    for item in instruments:
        ticker = str(item["yf"])
        close, source = fetch_close_http(
            item["name"], item.get("fdr"), ticker, FDR_TREND_LOOKBACK_DAYS
        )
        if close is not None and not close.empty:
            _http_close_cache[ticker] = (close, source)
            _close_series_cache[(f"http:{ticker}", FDR_TREND_LOOKBACK_DAYS)] = close
            print(f"시세 수집 성공 ({item['name']}): {source}")
        else:
            print(f"HTTP 시세 실패: {item['name']}")
        time.sleep(HTTP_REQUEST_DELAY)

    print(f"HTTP 시세 prefetch 완료: {len(_http_close_cache)}/{len(instruments)}")
    _http_prefetched = True


def ensure_market_data_prefetched() -> None:
    _prefetch_all_http()


def _close_from_http(ticker: str) -> tuple[pd.Series | None, str]:
    cached = _http_close_cache.get(ticker)
    if cached:
        return cached
    return None, ""

def _import_fdr():
    import FinanceDataReader as fdr

    return fdr


def _import_yfinance():
    import yfinance as yf

    return yf


@dataclass
class WatchlistTrend:
    name: str
    stock_code: str
    price: float | None
    change_1d: float | None
    change_5d: float | None
    change_20d: float | None
    change_60d: float | None
    low_20d: float | None
    high_20d: float | None
    low_60d: float | None
    high_60d: float | None

    def format_block(self) -> str:
        lines = [f"- {self.name} ({self.stock_code})"]
        if self.price is None:
            lines.append("  시세/추세 데이터 없음")
            return "\n".join(lines)

        lines.append(f"  현재가: {self._fmt(self.price)}")
        lines.append(
            "  수익률: "
            f"1일 {self._fmt_pct(self.change_1d)} / "
            f"5일 {self._fmt_pct(self.change_5d)} / "
            f"20일 {self._fmt_pct(self.change_20d)} / "
            f"60일 {self._fmt_pct(self.change_60d)}"
        )
        if self.low_20d is not None and self.high_20d is not None:
            lines.append(
                f"  20일 구간: {self._fmt(self.low_20d)} ~ {self._fmt(self.high_20d)}"
            )
        if self.low_60d is not None and self.high_60d is not None:
            lines.append(
                f"  60일 구간: {self._fmt(self.low_60d)} ~ {self._fmt(self.high_60d)}"
            )
        return "\n".join(lines)

    @staticmethod
    def _fmt(value: float) -> str:
        return f"{value:,.0f}"

    @staticmethod
    def _fmt_pct(value: float | None) -> str:
        if value is None:
            return "N/A"
        sign = "+" if value >= 0 else ""
        return f"{sign}{value:.2f}%"


@dataclass
class Quote:
    name: str
    ticker: str
    price: float | None
    change_pct: float | None
    group: str = ""
    source: str = ""

    def format_line(self) -> str:
        if self.price is None:
            return f"- {self.name}: 데이터 없음"

        if self.change_pct is None:
            return f"- {self.name}: {self._format_price(self.price)}"

        sign = "+" if self.change_pct >= 0 else ""
        return (
            f"- {self.name}: {self._format_price(self.price)} "
            f"({sign}{self.change_pct:.2f}%)"
        )

    @staticmethod
    def _format_price(price: float) -> str:
        if price >= 1000:
            return f"{price:,.2f}"
        return f"{price:.2f}"


def _get_instruments() -> list[dict[str, str | None]]:
    instruments = [
        {
            "name": item["name"],
            "fdr": item["fdr"],
            "yf": item["yf"],
            "group": item["group"],
        }
        for item in MARKET_INDICES
    ]
    instruments.extend(
        {
            "name": item["name"],
            "fdr": item["fdr"],
            "yf": item["yf"],
            "group": "워치리스트",
        }
        for item in WATCHLIST
    )
    return instruments


def _price_change_from_close(close: pd.Series) -> tuple[float | None, float | None]:
    if close.empty:
        return None, None

    current = float(close.iloc[-1])
    change_pct = None
    if len(close) >= 2:
        previous = float(close.iloc[-2])
        if previous != 0:
            change_pct = ((current - previous) / previous) * 100

    return current, change_pct


def _fetch_close_series_fdr(symbol: str, lookback_days: int) -> pd.Series | None:
    cache_key = (symbol, lookback_days)
    if cache_key in _close_series_cache:
        return _close_series_cache[cache_key]

    end = datetime.now()
    start = end - timedelta(days=lookback_days)

    sources = (None, "Naver") if _is_ci() else FDR_DATA_SOURCES
    for source in sources:
        try:
            fdr = _import_fdr()
            if source:
                data = fdr.DataReader(symbol, start, end, data_source=source)
            else:
                data = fdr.DataReader(symbol, start, end)

            if data is None or data.empty:
                continue

            if "Close" in data.columns:
                close = data["Close"].dropna()
            else:
                close = data.iloc[:, -1].dropna()

            if not close.empty:
                _close_series_cache[cache_key] = close
                return close
        except Exception as exc:
            source_label = source or "default"
            print(f"FDR 조회 실패 ({symbol}, {source_label}): {exc}")

        time.sleep(FDR_REQUEST_DELAY)

    _close_series_cache[cache_key] = None
    return None


def _fetch_close_series_yfinance(ticker: str, lookback_days: int) -> pd.Series | None:
    cache_key = (f"yf:{ticker}", lookback_days)
    if cache_key in _close_series_cache:
        return _close_series_cache[cache_key]

    try:
        yf = _import_yfinance()
        period = "6mo" if lookback_days >= 90 else "3mo"
        data = yf.download(
            ticker,
            period=period,
            auto_adjust=True,
            threads=False,
            progress=False,
        )
        if data is None or data.empty:
            _close_series_cache[cache_key] = None
            return None

        if "Close" in data.columns:
            close = data["Close"].dropna()
        else:
            close = data.iloc[:, -1].dropna()

        if close.empty:
            _close_series_cache[cache_key] = None
            return None

        _close_series_cache[cache_key] = close
        return close
    except Exception as exc:
        print(f"yfinance 추세 조회 실패 ({ticker}): {exc}")
        _close_series_cache[cache_key] = None
        return None


def _build_watchlist_trend(item: dict, close: pd.Series) -> WatchlistTrend:
    price = float(close.iloc[-1])
    low_20d, high_20d = _range_window(close, 20)
    low_60d, high_60d = _range_window(close, 60)
    return WatchlistTrend(
        name=item["name"],
        stock_code=item["fdr"],
        price=price,
        change_1d=_period_return(close, 1),
        change_5d=_period_return(close, 5),
        change_20d=_period_return(close, 20),
        change_60d=_period_return(close, 60),
        low_20d=low_20d,
        high_20d=high_20d,
        low_60d=low_60d,
        high_60d=high_60d,
    )


def _empty_watchlist_trend(item: dict) -> WatchlistTrend:
    return WatchlistTrend(
        name=item["name"],
        stock_code=item["fdr"],
        price=None,
        change_1d=None,
        change_5d=None,
        change_20d=None,
        change_60d=None,
        low_20d=None,
        high_20d=None,
        low_60d=None,
        high_60d=None,
    )


def _period_return(close: pd.Series, days: int) -> float | None:
    if len(close) <= days:
        return None
    previous = float(close.iloc[-(days + 1)])
    current = float(close.iloc[-1])
    if previous == 0:
        return None
    return ((current - previous) / previous) * 100


def _range_window(close: pd.Series, days: int) -> tuple[float | None, float | None]:
    window = close.tail(days)
    if window.empty:
        return None, None
    return float(window.min()), float(window.max())


def fetch_watchlist_trends() -> list[WatchlistTrend]:
    _prefetch_all_http()

    trends: list[WatchlistTrend] = []
    yfinance_fallback: list[tuple[int, str]] = []

    for index, item in enumerate(WATCHLIST):
        close, _source = _close_from_http(item["yf"])
        if close is not None and not close.empty:
            trends.append(_build_watchlist_trend(item, close))
            continue

        close = _fetch_close_series_fdr(item["fdr"], FDR_TREND_LOOKBACK_DAYS)
        if close is None or close.empty:
            yfinance_fallback.append((index, item["yf"]))
            trends.append(_empty_watchlist_trend(item))
            continue

        trends.append(_build_watchlist_trend(item, close))
        time.sleep(FDR_REQUEST_DELAY)

    if yfinance_fallback and _is_ci():
        for trend_index, _ticker in yfinance_fallback:
            print(f"워치리스트 시세 없음: {WATCHLIST[trend_index]['name']}")
        success_count = sum(1 for trend in trends if trend.price is not None)
        print(f"워치리스트 추세 수집 성공: {success_count}/{len(trends)}")
        return trends

    if yfinance_fallback:
        fallback_tickers = [ticker for _, ticker in yfinance_fallback]
        print(f"워치리스트 yfinance 보조 조회: {len(fallback_tickers)}개")
        time.sleep(2)

        try:
            yf = _import_yfinance()
            batch_data = yf.download(
                fallback_tickers,
                period="6mo",
                group_by="ticker",
                auto_adjust=True,
                threads=False,
                progress=False,
            )
        except Exception as exc:
            print(f"워치리스트 yfinance 배치 실패: {exc}")
            batch_data = pd.DataFrame()

        for trend_index, ticker in yfinance_fallback:
            close = _get_close_series(batch_data, ticker, fallback_tickers)
            if close is None or close.empty:
                close = _fetch_close_series_yfinance(ticker, FDR_TREND_LOOKBACK_DAYS)
            if close is not None and not close.empty:
                trends[trend_index] = _build_watchlist_trend(
                    WATCHLIST[trend_index], close
                )
            else:
                print(f"워치리스트 시세 없음: {WATCHLIST[trend_index]['name']}")

    success_count = sum(1 for trend in trends if trend.price is not None)
    print(f"워치리스트 추세 수집 성공: {success_count}/{len(trends)}")
    return trends


def format_watchlist_trends(trends: list[WatchlistTrend]) -> str:
    lines = ["📈 워치리스트 추세·가격 구간 (시세 데이터 기반)"]
    lines.extend(trend.format_block() for trend in trends)
    return "\n".join(lines)


def _fetch_via_fdr(symbol: str) -> tuple[float | None, float | None]:
    close = _fetch_close_series_fdr(symbol, FDR_LOOKBACK_DAYS)
    if close is None:
        return None, None
    return _price_change_from_close(close)


def _download_yfinance_history_batch(
    tickers: list[str], period: str = "5d"
) -> pd.DataFrame:
    last_error: Exception | None = None

    for attempt, delay in enumerate(YFINANCE_RETRY_DELAYS, start=1):
        try:
            yf = _import_yfinance()
            data = yf.download(
                tickers,
                period=period,
                group_by="ticker",
                auto_adjust=True,
                threads=False,
                progress=False,
            )
            if not data.empty:
                return data
        except Exception as exc:
            last_error = exc
            print(
                f"yfinance 배치 실패 (시도 {attempt}/{len(YFINANCE_RETRY_DELAYS)}, "
                f"{period}): {exc}"
            )

        time.sleep(delay)

    if last_error:
        print(f"yfinance 배치 최종 실패 ({period}): {last_error}")

    return pd.DataFrame()


def _download_yfinance_batch(tickers: list[str]) -> pd.DataFrame:
    return _download_yfinance_history_batch(tickers, period="5d")

def _get_close_series(
    data: pd.DataFrame, ticker: str, batch: list[str]
) -> pd.Series | None:
    if data.empty:
        return None

    if len(batch) == 1 and "Close" in data.columns:
        series = data["Close"].dropna()
        return series if not series.empty else None

    if isinstance(data.columns, pd.MultiIndex):
        tickers_in_data = data.columns.get_level_values(0).unique()
        if ticker in tickers_in_data:
            series = data[ticker]["Close"].dropna()
            return series if not series.empty else None

    return None


def _fetch_via_yfinance(ticker: str, data: pd.DataFrame, batch: list[str]) -> tuple[float | None, float | None]:
    close = _get_close_series(data, ticker, batch)
    if close is None:
        return None, None
    return _price_change_from_close(close)


def fetch_market_quotes() -> list[Quote]:
    _prefetch_all_http()

    instruments = _get_instruments()
    quotes: list[Quote] = []
    yfinance_fallback: list[tuple[int, str]] = []

    yfinance_first = [
        (index, str(instrument["yf"]))
        for index, instrument in enumerate(instruments)
        if instrument["yf"] in YFINANCE_ONLY_TICKERS and not _is_ci()
    ]
    yfinance_first_indices = {index for index, _ in yfinance_first}
    yfinance_prefetch: pd.DataFrame = pd.DataFrame()
    prefetch_tickers: list[str] = []

    if yfinance_first:
        prefetch_tickers = [ticker for _, ticker in yfinance_first]
        print(f"yfinance 우선 조회: {len(prefetch_tickers)}개")
        time.sleep(3)
        yfinance_prefetch = _download_yfinance_batch(prefetch_tickers)

    for index, instrument in enumerate(instruments):
        name = str(instrument["name"])
        group = str(instrument["group"])
        fdr_symbol = instrument["fdr"]
        yf_ticker = str(instrument["yf"])

        price, change_pct = None, None
        source = ""

        close, http_source = _close_from_http(yf_ticker)
        if close is not None and not close.empty:
            price, change_pct = _price_change_from_close(close)
            source = http_source

        if price is None and index in yfinance_first_indices and not yfinance_prefetch.empty:
            price, change_pct = _fetch_via_yfinance(
                yf_ticker, yfinance_prefetch, prefetch_tickers
            )
            if price is not None:
                source = "yfinance"

        if price is None and fdr_symbol:
            price, change_pct = _fetch_via_fdr(str(fdr_symbol))
            if price is not None:
                source = "FDR"
            time.sleep(FDR_REQUEST_DELAY)

        if price is None and yf_ticker and index not in yfinance_first_indices and not _is_ci():
            yfinance_fallback.append((index, yf_ticker))

        quotes.append(
            Quote(
                name=name,
                ticker=yf_ticker,
                price=price,
                change_pct=change_pct,
                group=group,
                source=source,
            )
        )

    if yfinance_fallback:
        fallback_tickers = [ticker for _, ticker in yfinance_fallback]
        print(f"yfinance 보조 조회 시작: {len(fallback_tickers)}개")
        time.sleep(5)
        yf_data = _download_yfinance_batch(fallback_tickers)

        for quote_index, ticker in yfinance_fallback:
            price, change_pct = _fetch_via_yfinance(ticker, yf_data, fallback_tickers)
            if price is not None:
                quotes[quote_index].price = price
                quotes[quote_index].change_pct = change_pct
                quotes[quote_index].source = "yfinance"
            else:
                print(f"시세 데이터 없음 ({quotes[quote_index].name}, {ticker})")

    success_count = sum(1 for quote in quotes if quote.price is not None)
    print(f"시세 수집 성공: {success_count}/{len(quotes)}")

    return quotes


def format_market_snapshot(quotes: list[Quote]) -> str:
    lines = ["📊 시장 스냅샷"]

    grouped: dict[str, list[Quote]] = {}
    for quote in quotes:
        grouped.setdefault(quote.group or "기타", []).append(quote)

    for group_name, group_quotes in grouped.items():
        lines.append(f"\n[{group_name}]")
        lines.extend(quote.format_line() for quote in group_quotes)

    return "\n".join(lines)
