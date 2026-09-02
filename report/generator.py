from __future__ import annotations

import os

import google.generativeai as genai

from config import (
    GEMINI_MODEL,
    GEMINI_MODEL_FALLBACKS,
    MESSAGE_BREAK,
    STAGE1_PROMPT,
    STAGE2_PROMPT,
)


def _get_models_to_try() -> list[str]:
    return [GEMINI_MODEL] + [
        model for model in GEMINI_MODEL_FALLBACKS if model != GEMINI_MODEL
    ]


def _generate_with_fallback(prompt: str, step_name: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY가 설정되지 않았습니다.")

    genai.configure(api_key=api_key)
    errors: list[str] = []

    for model_name in _get_models_to_try():
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)

            if response.text:
                print(f"{step_name} 사용 모델: {model_name}")
                return response.text

            errors.append(f"{model_name}: 빈 응답")
        except Exception as exc:
            print(f"{step_name} 모델 {model_name} 실패: {exc}")
            errors.append(f"{model_name}: {exc}")

    raise RuntimeError(
        f"{step_name} 모든 Gemini 모델 호출에 실패했습니다.\n" + "\n".join(errors)
    )


def extract_facts(
    market_data: str,
    financial_data: str,
    watchlist_data: str,
    news_data: str,
) -> str:
    prompt = STAGE1_PROMPT.format(
        market_data=market_data,
        financial_data=financial_data,
        watchlist_data=watchlist_data,
        news_data=news_data,
    )
    return _generate_with_fallback(prompt, "1단계 사실 추출")


def generate_report_parts(
    facts: str,
    market_data: str,
    financial_data: str,
    watchlist_data: str,
) -> list[str]:
    prompt = STAGE2_PROMPT.format(
        facts=facts,
        market_data=market_data,
        financial_data=financial_data,
        watchlist_data=watchlist_data,
        message_break=MESSAGE_BREAK,
    )
    report_text = _generate_with_fallback(prompt, "2단계 리포트 생성")

    parts = [part.strip() for part in report_text.split(MESSAGE_BREAK) if part.strip()]
    if len(parts) >= 2:
        return parts

    return _split_long_text(report_text)


def _split_long_text(text: str, max_length: int = 3800) -> list[str]:
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    current = ""

    for paragraph in text.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_length:
            current = candidate
            continue

        if current:
            chunks.append(current)
        current = paragraph

    if current:
        chunks.append(current)

    return chunks or [text[:max_length]]
