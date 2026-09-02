from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd
import yfinance as yf

from config import MARKET_INDICES, WATCHLIST

FDR_LOOKBACK_DAYS = 14
FDR_REQUEST_DELAY = 0.4
YFINANCE_RETRY_DELAYS = (3, 8, 15)


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


def _fetch_via_fdr(symbol: str) -> tuple[float | None, float | None]:
    end = datetime.now()
    start = end - timedelta(days=FDR_LOOKBACK_DAYS)

    try:
        data = fdr.DataReader(symbol, start, end)
        if data is None or data.empty:
            return None, None

        if "Close" in data.columns:
            close = data["Close"].dropna()
        else:
            close = data.iloc[:, -1].dropna()

        return _price_change_from_close(close)
    except Exception as exc:
        print(f"FDR 조회 실패 ({symbol}): {exc}")
        return None, None


def _download_yfinance_batch(tickers: list[str]) -> pd.DataFrame:
    last_error: Exception | None = None

    for attempt, delay in enumerate(YFINANCE_RETRY_DELAYS, start=1):
        try:
            data = yf.download(
                tickers,
                period="5d",
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
                f"yfinance 배치 실패 (시도 {attempt}/{len(YFINANCE_RETRY_DELAYS)}): {exc}"
            )

        time.sleep(delay)

    if last_error:
        print(f"yfinance 배치 최종 실패: {last_error}")

    return pd.DataFrame()


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
    instruments = _get_instruments()
    quotes: list[Quote] = []
    yfinance_fallback: list[tuple[int, str]] = []

    for index, instrument in enumerate(instruments):
        name = str(instrument["name"])
        group = str(instrument["group"])
        fdr_symbol = instrument["fdr"]
        yf_ticker = str(instrument["yf"])

        price, change_pct = None, None
        source = ""

        if fdr_symbol:
            price, change_pct = _fetch_via_fdr(str(fdr_symbol))
            if price is not None:
                source = "FDR"
            time.sleep(FDR_REQUEST_DELAY)

        if price is None and yf_ticker:
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
        time.sleep(2)
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
