# 2025GAMJA - Multi-LLM RRF (Reciprocal Rank Fusion)

다중 LLM(Large Language Model)의 응답을 RRF(Reciprocal Rank Fusion) 알고리즘으로 결합하여 최적의 답변을 제공하는 시스템입니다.

## 🎯 주요 기능

- **다중 LLM 통합**: OpenAI GPT-4와 Anthropic Claude를 동시에 활용
- **RRF 융합 알고리즘**: 여러 랭킹 전략을 결합하여 최적의 답변 선택
  - Confidence 기반 랭킹
  - 키워드 오버랩 기반 랭킹
  - 간결성 기반 랭킹
- **견고한 에러 처리**: 하나의 LLM이 실패해도 다른 LLM 결과 활용
- **실시간 웹 인터페이스**: 간단하고 직관적인 UI

## 🏗️ 프로젝트 구조

```
2025GAMJA/
├── README.md
└── multi-llm-rrf/
    ├── backend/
    │   ├── app.py              # FastAPI 백엔드 서버
    │   ├── requirements.txt    # Python 의존성
    │   ├── .env.example        # 환경변수 템플릿
    │   └── .env               # 실제 API 키 (git에서 제외됨)
    └── frontend/
        └── index.html          # 웹 인터페이스
```

## 📋 사전 요구사항

- Python 3.10 이상
- OpenAI API 키 ([발급받기](https://platform.openai.com/api-keys))
- Anthropic API 키 ([발급받기](https://console.anthropic.com/settings/keys))

## 🚀 설치 및 실행 방법

### 1. 환경 설정

```bash
# 프로젝트 클론
git clone https://github.com/hyunsang1021/2025GAMJA.git
cd 2025GAMJA/multi-llm-rrf/backend

# Python 가상환경 생성 (권장)
python -m venv venv

# 가상환경 활성화
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt
```

### 2. API 키 설정

```bash
# .env.example을 .env로 복사
cp .env.example .env

# .env 파일을 편집하여 실제 API 키 입력
# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
```

### 3. 백엔드 서버 실행

```bash
# multi-llm-rrf/backend 디렉토리에서
fastapi dev app.py
```

서버가 `http://127.0.0.1:8000`에서 실행됩니다.

### 4. 프론트엔드 실행

새 터미널 창을 열고:

```bash
# multi-llm-rrf/frontend 디렉토리에서
# Live Server 사용 (VSCode 확장 프로그램)
# 또는 Python 간단한 HTTP 서버:
python -m http.server 5500
```

브라우저에서 `http://127.0.0.1:5500`를 열어 접속합니다.

## 💡 사용 방법

1. 웹 인터페이스에 질문을 입력
2. "질의" 버튼 클릭
3. 각 LLM의 응답과 RRF 알고리즘이 선택한 최적의 답변 확인

## 🔧 API 엔드포인트

### POST /ask
질문을 받아 여러 LLM의 응답을 RRF로 결합하여 반환합니다.

**요청:**
```json
{
  "query": "질문 내용"
}
```

**응답:**
```json
{
  "query": "질문 내용",
  "winner": {
    "provider": "openai",
    "answer": "답변 내용",
    "confidence": 85,
    "notes": "raw"
  },
  "fused": [
    {"id": "openai", "score": 0.0327},
    {"id": "anthropic", "score": 0.0163}
  ],
  "all": [
    {...},
    {...}
  ]
}
```

## 🎨 RRF 알고리즘 설명

RRF(Reciprocal Rank Fusion)는 여러 랭킹 전략의 결과를 결합하는 알고리즘입니다:

1. **Confidence Ranking**: LLM이 제공한 신뢰도 점수 기반
2. **Keyword Overlap**: 질문과 답변의 키워드 유사도 (Jaccard) 기반
3. **Brevity**: 답변의 간결성 기반

각 랭킹의 점수를 다음 공식으로 결합:
```
score = Σ(1 / (k + rank))
```
여기서 k는 상수(기본값 60), rank는 각 전략에서의 순위입니다.

## 🛡️ 보안 고려사항

- `.env` 파일은 절대 Git에 커밋하지 마세요
- 프로덕션 환경에서는 CORS 설정을 특정 도메인으로 제한하세요
- API 키는 안전하게 관리하세요

## 🐛 트러블슈팅

### CORS 에러 발생 시
백엔드의 `app.py`에서 CORS 설정을 확인하세요. 현재는 모든 origin 허용(`allow_origins=["*"]`)으로 설정되어 있습니다.

### API 키 에러
- `.env` 파일이 올바른 위치(`multi-llm-rrf/backend/.env`)에 있는지 확인
- API 키가 유효한지 확인 (공백, 잘못된 문자 등)

### 포트 충돌
- 백엔드: 기본 포트 8000이 사용 중이면 `fastapi dev app.py --port 8001`로 변경
- 프론트엔드: 다른 포트 번호 사용

## 📝 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다.

## 👥 기여

이슈 제보와 풀 리퀘스트를 환영합니다!

## 📧 문의

문제나 질문이 있으시면 GitHub Issues를 통해 문의해 주세요.
