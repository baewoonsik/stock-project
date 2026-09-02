import os
import sys
from datetime import datetime

import feedparser
import google.generativeai as genai
import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_MODEL_FALLBACKS = ("gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.1-flash-lite")

RSS_URLS = [
    "https://news.google.com/news/rss/headlines/section/topic/BUSINESS?hl=ko&gl=KR&ceid=KR:ko",
    "https://news.google.com/rss/search?q=엔비디아&hl=ko&gl=KR&ceid=KR:ko",
]

PROMPT_TEMPLATE = """당신은 전문 주식 애널리스트입니다. 다음은 오늘 수집된 주요 경제 및 종목 뉴스 헤드라인입니다.
{news_data}

이 뉴스들을 분석하여 슬랙(Slack) 메신저에서 보기 좋은 마크다운 형식으로 오늘의 증시 시황 리포트를 작성해 주세요.
반드시 다음 구조를 지켜주세요:
1. 📈 *오늘의 시장 한 줄 평*
2. 🌐 *거시 경제 주요 이슈* (2~3개 불릿 포인트)
3. 🎯 *주요 종목 동향* (2~3개 불릿 포인트)
4. 💡 *투자 인사이트 및 시그널* (긍정/부정적 요인 요약)
"""


def validate_env() -> None:
    if not GEMINI_API_KEY or not SLACK_WEBHOOK_URL:
        print("API 키 또는 웹훅 URL이 설정되지 않았습니다.")
        sys.exit(1)


def fetch_news_headlines() -> str:
    news_texts: list[str] = []

    for url in RSS_URLS:
        feed = feedparser.parse(url)
        if feed.bozo:
            print(f"RSS 파싱 경고: {url} - {feed.bozo_exception}")

        for entry in feed.entries[:5]:
            news_texts.append(f"- {entry.title}")

    if not news_texts:
        return "수집된 뉴스가 없습니다."

    return "\n".join(news_texts)


def generate_report(news_data: str) -> str:
    genai.configure(api_key=GEMINI_API_KEY)
    prompt = PROMPT_TEMPLATE.format(news_data=news_data)

    models_to_try = [GEMINI_MODEL] + [
        model for model in GEMINI_MODEL_FALLBACKS if model != GEMINI_MODEL
    ]
    errors: list[str] = []

    for model_name in models_to_try:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)

            if response.text:
                print(f"사용 모델: {model_name}")
                return response.text

            errors.append(f"{model_name}: 빈 응답")
        except Exception as exc:
            print(f"모델 {model_name} 실패: {exc}")
            errors.append(f"{model_name}: {exc}")

    raise RuntimeError(
        "모든 Gemini 모델 호출에 실패했습니다.\n" + "\n".join(errors)
    )


def send_to_slack(report_content: str) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    final_message = f"🔔 *{today} 주식 현황 상세 리포트*\n\n{report_content}"

    if len(final_message) > 4000:
        final_message = final_message[:3997] + "..."

    slack_response = requests.post(
        SLACK_WEBHOOK_URL,
        json={"text": final_message},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    slack_response.raise_for_status()


def main() -> None:
    validate_env()

    print("뉴스 헤드라인 수집 중...")
    news_data = fetch_news_headlines()
    print(f"수집된 헤드라인 수: {news_data.count(chr(10)) + 1}")

    print("Gemini API로 리포트 생성 중...")
    report_content = generate_report(news_data)

    print("슬랙으로 리포트 전송 중...")
    send_to_slack(report_content)
    print("슬랙 리포트 전송 완료")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"오류: {exc}")
        sys.exit(1)
