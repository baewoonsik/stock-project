import os

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_MODEL_FALLBACKS = ("gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.1-flash-lite")

NEWS_PER_FEED = 8
NEWS_MAX_AGE_HOURS = 48
SLACK_MESSAGE_MAX_LENGTH = 3800
MIN_MARKET_DATA_SUCCESS_RATIO = 0.4
MIN_WATCHLIST_SUCCESS_RATIO = 0.7

WATCHLIST = [
    {"name": "삼성전자", "fdr": "005930", "yf": "005930.KS"},
    {"name": "SK하이닉스", "fdr": "000660", "yf": "000660.KS"},
    {"name": "현대차", "fdr": "005380", "yf": "005380.KS"},
    {"name": "네이버", "fdr": "035420", "yf": "035420.KS"},
    {"name": "한미반도체", "fdr": "042700", "yf": "042700.KS"},
    {"name": "주성엔지니어링", "fdr": "036930", "yf": "036930.KQ"},
    {"name": "리노공업", "fdr": "058470", "yf": "058470.KQ"},
    {"name": "HPSP", "fdr": "403870", "yf": "403870.KQ"},
    {"name": "솔브레인", "fdr": "357780", "yf": "357780.KQ"},
]

MARKET_INDICES = [
    {"name": "코스피", "fdr": "KS11", "yf": "^KS11", "group": "국내"},
    {"name": "코스닥", "fdr": "KQ11", "yf": "^KQ11", "group": "국내"},
    {"name": "S&P 500", "fdr": "US500", "yf": "^GSPC", "group": "해외"},
    {"name": "나스닥", "fdr": "IXIC", "yf": "^IXIC", "group": "해외"},
    {"name": "다우존스", "fdr": "DJI", "yf": "^DJI", "group": "해외"},
    {"name": "닛케이225", "fdr": "N225", "yf": "^N225", "group": "해외"},
    {"name": "항셍", "fdr": "HSI", "yf": "^HSI", "group": "해외"},
    {"name": "VIX", "fdr": None, "yf": "^VIX", "group": "해외"},
    {"name": "원/달러", "fdr": "USD/KRW", "yf": "USDKRW=X", "group": "환율·원자재"},
    {"name": "유로/원", "fdr": "EUR/KRW", "yf": "EURKRW=X", "group": "환율·원자재"},
    {"name": "엔/원", "fdr": "JPY/KRW", "yf": "JPYKRW=X", "group": "환율·원자재"},
    {"name": "금", "fdr": None, "yf": "GC=F", "group": "환율·원자재"},
    {"name": "WTI 유가", "fdr": "CL", "yf": "CL=F", "group": "환율·원자재"},
    {"name": "비트코인", "fdr": "BTC/USD", "yf": "BTC-USD", "group": "환율·원자재"},
    {"name": "美 10년물 금리", "fdr": None, "yf": "^TNX", "group": "환율·원자재"},
]

RSS_TOPIC_FEEDS = [
    {
        "topic": "경제 일반",
        "url": "https://news.google.com/news/rss/headlines/section/topic/BUSINESS?hl=ko&gl=KR&ceid=KR:ko",
    },
    {
        "topic": "국내 증시",
        "url": "https://news.google.com/rss/search?q=코스피+OR+코스닥&hl=ko&gl=KR&ceid=KR:ko",
    },
    {
        "topic": "반도체·AI",
        "url": "https://news.google.com/rss/search?q=반도체+OR+AI+주가&hl=ko&gl=KR&ceid=KR:ko",
    },
    {
        "topic": "금리·연준",
        "url": "https://news.google.com/rss/search?q=연준+OR+금리&hl=ko&gl=KR&ceid=KR:ko",
    },
    {
        "topic": "2차전지·배터리",
        "url": "https://news.google.com/rss/search?q=2차전지+OR+배터리+OR+전기차+배터리&hl=ko&gl=KR&ceid=KR:ko",
    },
    {
        "topic": "부동산",
        "url": "https://news.google.com/rss/search?q=부동산+OR+아파트+OR+전세&hl=ko&gl=KR&ceid=KR:ko",
    },
    {
        "topic": "바이오",
        "url": "https://news.google.com/rss/search?q=바이오+OR+제약+OR+신약&hl=ko&gl=KR&ceid=KR:ko",
    },
]

MESSAGE_BREAK = "===MESSAGE_BREAK==="

STAGE1_PROMPT = """당신은 금융 데이터 분석가입니다. 아래 데이터만을 근거로 사실을 추출하세요.

[시장 데이터]
{market_data}

[재무 데이터]
{financial_data}

[워치리스트 추세·가격 구간]
{watchlist_data}

[뉴스 헤드라인]
{news_data}

다음 형식으로 사실만 정리하세요. 추측·해석·없는 수치는 쓰지 마세요.
1. 시장 수치 요약 (제공된 숫자만 인용)
2. 재무 지표 요약 (DART 데이터만 인용, 기간 명시)
3. 워치리스트 추세 요약 (수익률·20일/60일 구간만 인용)
4. 거시경제 관련 사실 (헤드라인 근거, 키워드 표기)
5. 섹터별 사실 (반도체/소부장, 2차전지, 자동차, 부동산, 바이오)
6. 워치리스트 종목 관련 사실 (종목명별, 헤드라인에 언급된 것만)
7. 확인되지 않은 정보 (데이터 부족 시 명시)
"""

STAGE2_PROMPT = """당신은 전문 주식 애널리스트입니다. 아래 1단계 사실 추출 결과와 원본 데이터만을 근거로 상세 분석 리포트를 작성하세요.

[1단계 사실 추출 결과]
{facts}

[시장 데이터 원본]
{market_data}

[재무 데이터 원본]
{financial_data}

[워치리스트 추세·가격 구간 원본]
{watchlist_data}

규칙:
- 제공된 데이터에 없는 수치·사실을 만들지 말 것
- 불확실하면 "뉴스 헤드라인 기준" 또는 "데이터 미확인"이라고 명시
- 사실(Fact)과 해석(Interpretation)을 구분할 것
- 매수/매도/목표가 권유 금지. 대신 20일·60일 가격 구간과 PER/PBR 등 밸류 위치만 참고용으로 언급
- Slack mrkdwn 형식 (*굵게*, 불릿 -) 사용

반드시 아래 3개 파트로 나누고, 파트 사이에 정확히 `{message_break}` 한 줄만 넣으세요.

파트 1:
- 📊 시장 스냅샷 (시장 데이터 원본 수치를 그대로 표기)
- 📋 재무 하이라이트 요약 (DART 데이터 기반, 종목별 1~2줄)
- 📈 오늘의 시장 한 줄 평
- 🌐 거시경제·글로벌 이슈 (3~5개 불릿, 근거 키워드 괄호 표기)

파트 2:
- 🏭 섹터별 동향 (반도체/소부장, 2차전지·배터리, 자동차, 부동산, 바이오 각 2~3개 불릿)
- 각 불릿에 사실/해석 구분

파트 3:
- 🎯 워치리스트 종목별 상세 브리핑 (9종목: 삼성전자, SK하이닉스, 현대차, 네이버, 한미반도체, 주성엔지니어링, 리노공업, HPSP, 솔브레인)
  각 종목마다 아래 항목 포함:
  • 현재가 및 5일/20일/60일 수익률 (제공 수치만)
  • 20일·60일 가격 구간 (지지·저항 참고용, 계산된 구간만)
  • 재무 위치 (PER/PBR/ROE 등 DART 데이터가 있을 때만)
  • 단기(1~4주) / 중기(1~3개월) / 장기(6개월+) 관점 (사실·해석 구분)
  • 리스크 요인
- 💡 종합 투자 인사이트 (긍정/부정 요인, 사실과 해석 구분)
- ⚠️ 주의: 본 리포트는 정보 제공 목적이며 투자 권유가 아닙니다. 최종 판단은 본인 책임입니다.
"""
