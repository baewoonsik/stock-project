import os
import sys
from datetime import datetime

import requests

from config import (
    MIN_MARKET_DATA_SUCCESS_RATIO,
    MIN_WATCHLIST_SUCCESS_RATIO,
    SLACK_MESSAGE_MAX_LENGTH,
    WATCHLIST,
)


def validate_env() -> None:
    missing = []
    if not os.environ.get("GEMINI_API_KEY"):
        missing.append("GEMINI_API_KEY")
    if not os.environ.get("SLACK_WEBHOOK_URL"):
        missing.append("SLACK_WEBHOOK_URL")

    if missing:
        print(f"환경변수 누락: {', '.join(missing)}")
        print("GitHub Secrets 또는 export 설정을 확인하세요.")
        sys.exit(1)


def send_to_slack(messages: list[str]) -> None:
    webhook_url = os.environ["SLACK_WEBHOOK_URL"]
    today = datetime.now().strftime("%Y-%m-%d")
    total = len(messages)

    for index, message in enumerate(messages, start=1):
        header = f"🔔 *{today} 주식 현황 상세 리포트 ({index}/{total})*\n\n"
        final_message = header + message

        if len(final_message) > SLACK_MESSAGE_MAX_LENGTH:
            final_message = final_message[: SLACK_MESSAGE_MAX_LENGTH - 3] + "..."

        response = requests.post(
            webhook_url,
            json={"text": final_message},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        print(f"슬랙 메시지 {index}/{total} 전송 완료")


def main() -> None:
    validate_env()

    try:
        from collectors.dart import fetch_financial_highlights, format_financial_data
        from collectors.market import (
            ensure_market_data_prefetched,
            fetch_market_quotes,
            fetch_watchlist_trends,
            format_market_snapshot,
            format_watchlist_trends,
        )
        from collectors.news import fetch_news_items, format_news_data
        from report.generator import extract_facts, generate_report_parts
    except Exception as exc:
        print(f"모듈 import 실패: {exc}")
        raise

    print("워치리스트 추세 데이터 수집 중...")
    ensure_market_data_prefetched()
    watchlist_trends = fetch_watchlist_trends()
    watchlist_data = format_watchlist_trends(watchlist_trends)

    watchlist_success = sum(1 for trend in watchlist_trends if trend.price is not None)
    watchlist_ratio = watchlist_success / len(WATCHLIST)
    print(
        f"워치리스트 추세 수집: {watchlist_success}/{len(WATCHLIST)} "
        f"({watchlist_ratio:.0%})"
    )

    if watchlist_ratio < MIN_WATCHLIST_SUCCESS_RATIO:
        print(
            "경고: 워치리스트 시세 일부 누락. 가능한 데이터로 리포트를 계속 생성합니다."
        )

    print("시장 데이터 수집 중...")
    quotes = fetch_market_quotes()
    market_data = format_market_snapshot(quotes)

    success_count = sum(1 for quote in quotes if quote.price is not None)
    success_ratio = success_count / len(quotes)
    print(f"시장 데이터 수집 완료: {success_count}/{len(quotes)} ({success_ratio:.0%})")

    if success_ratio < MIN_MARKET_DATA_SUCCESS_RATIO:
        print(
            "경고: 시장 지수 일부 누락. 워치리스트 데이터로 리포트를 계속 생성합니다."
        )

    prices_by_stock = {
        trend.stock_code: trend.price
        for trend in watchlist_trends
        if trend.price is not None
    }

    print("DART 재무 데이터 수집 중...")
    financial_highlights = fetch_financial_highlights(prices_by_stock)
    financial_data = format_financial_data(financial_highlights)

    print("뉴스 헤드라인 수집 중...")
    news_items = fetch_news_items()
    news_data = format_news_data(news_items)
    print(f"뉴스 수집 완료: {len(news_items)}개")

    print("1단계: 사실 추출 중...")
    facts = extract_facts(market_data, financial_data, watchlist_data, news_data)

    print("2단계: 상세 리포트 생성 중...")
    report_parts = generate_report_parts(
        facts, market_data, financial_data, watchlist_data
    )
    print(f"리포트 파트 수: {len(report_parts)}")

    print("슬랙으로 리포트 전송 중...")
    send_to_slack(report_parts)
    print("슬랙 리포트 전송 완료")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"오류: {exc}")
        sys.exit(1)
