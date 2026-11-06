# 2025GAMJA - Multi-LLM RRF (Reciprocal Rank Fusion)

**같은 질문에 대한 두 AI 모델의 답변을 비교하고, 여러 평가 기준의 순위를 합쳐 답변 하나를 선택하는 웹 프로젝트입니다.**

OpenAI GPT-4와 Anthropic Claude를 병렬 호출하고, 신뢰도·키워드 일치·간결성을 기준으로 RRF 점수를 계산합니다. 모델별 답변과 최종 선택 결과를 한 화면에서 확인할 수 있습니다.

## 🎯 프로젝트 목적

같은 질문에도 모델마다 답변과 표현 방식이 달라집니다. 이 프로젝트는 외부 LLM API를 연동하고, 서로 다른 기준의 순위를 하나의 점수로 합쳐 답변을 선택하는 과정을 구현한 학습용 프로젝트입니다.

API 요청부터 응답 검증, 순위 계산, 화면 표시까지 연결하는 데 초점을 두었습니다. RRF 점수는 이 프로젝트의 선택 기준이며, 답변의 사실성이나 정답 확률을 뜻하지는 않습니다.

## ✨ 주요 기능

- **다중 LLM 병렬 호출**: 하나의 질문을 OpenAI와 Anthropic에 동시에 전달
- **RRF 기반 답변 선택**: 세 가지 평가 기준의 순위를 합산해 최종 답변 결정
- **모델별 결과 비교**: 각 모델의 답변·자체 신뢰도와 최종 답변의 RRF 점수 표시
- **실패 응답 분리**: 한 모델이 실패해도 정상 답변으로 결과 제공, 모두 실패하면 오류 안내
- **응답 검증**: 잘못된 답변 형식·신뢰도 값을 처리하고 공급자 정보 덮어쓰기 방지
- **텍스트 렌더링**: 답변에 HTML이 들어 있어도 실행하지 않고 문자 그대로 표시

## 🛠️ 사용 기술

| 구분 | 기술 | 역할 |
| --- | --- | --- |
| 백엔드 | Python, FastAPI, Pydantic | API 서버와 요청 형식 검증 |
| 외부 API 통신 | httpx, asyncio | 비동기 HTTP 요청과 병렬 실행 |
| 모델 | OpenAI GPT-4, Anthropic Claude Sonnet 5.5 | 답변 생성 |
| 환경 설정 | python-dotenv | 로컬 API 키와 Claude 모델 설정 |
| 프런트엔드 | HTML, CSS, JavaScript | 질문 입력과 결과 표시 |
| 테스트 | unittest, Playwright | 백엔드 회귀 테스트와 실제 브라우저 검증 |

## ⚙️ 동작 흐름

1. 사용자가 웹 화면에서 질문을 입력합니다.
2. FastAPI의 `/ask`가 두 모델을 병렬 호출합니다.
3. 응답을 공통 형식으로 정리하고 실패한 후보를 제외합니다.
4. 정상 후보를 세 가지 기준으로 정렬한 뒤 RRF 점수를 합산합니다.
5. 점수가 가장 높은 답변과 모델별 결과를 화면에 표시합니다.

두 호출의 결과를 모아 처리하는 방식이며, 답변을 토큰 단위로 스트리밍하지 않습니다.

## 🏗️ 프로젝트 구조

```text
2025GAMJA/
├── .gitignore
├── README.md
└── multi-llm-rrf/
    ├── backend/
    │   ├── app.py              # 모델 호출, 응답 검증, RRF 계산
    │   ├── requirements.txt    # Python 의존성
    │   ├── .env.example        # 환경변수 설정 예시
    │   └── test_app.py         # 백엔드 회귀 테스트
    └── frontend/
        ├── index.html          # 질문 입력 및 결과 화면
        └── test-ui.cjs         # 브라우저 회귀 테스트
```

실행 시 `backend/.env`를 직접 생성합니다. API 키 파일, Python 캐시, 가상환경은 Git 추적 대상에서 제외됩니다.

## 📋 사전 요구사항

- Python 3.10 이상
- OpenAI API 키와 `gpt-4` 사용 권한: [API 키 발급](https://platform.openai.com/api-keys)
- Anthropic API 키와 설정한 Claude 모델 사용 권한: [API 키 발급](https://console.anthropic.com/settings/keys)
- 브라우저 테스트를 실행할 경우 Node.js와 Playwright

앱을 시작하려면 **두 공급자의 API 키가 모두 설정되어 있어야 합니다.** 실제 질문을 보내면 외부 API가 호출되며, 공급자의 요금 정책에 따라 비용이 발생합니다.

## 🚀 설치 및 실행 방법

아래 명령은 별도 안내가 없는 한 **저장소 루트**에서 실행합니다.

### 1. 프로젝트와 가상환경 준비

```bash
git clone https://github.com/hyunsang1021/2025GAMJA.git
cd 2025GAMJA
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
source .venv/bin/activate
```

의존성 설치:

```bash
python -m pip install -r multi-llm-rrf/backend/requirements.txt
```

### 2. API 키 설정

Windows PowerShell:

```powershell
Copy-Item multi-llm-rrf/backend/.env.example multi-llm-rrf/backend/.env
```

macOS / Linux:

```bash
cp multi-llm-rrf/backend/.env.example multi-llm-rrf/backend/.env
```

생성한 `.env`의 예시 값을 실제 API 키로 교체합니다.

```dotenv
OPENAI_API_KEY=YOUR_OPENAI_API_KEY
ANTHROPIC_API_KEY=YOUR_ANTHROPIC_API_KEY
ANTHROPIC_MODEL=claude-sonnet-5-5
```

| 설정 | 기본값 / 필요 여부 |
| --- | --- |
| `OPENAI_API_KEY` | 필수 |
| `ANTHROPIC_API_KEY` | 필수 |
| `ANTHROPIC_MODEL` | 생략하거나 비워 두면 `claude-sonnet-5-5` |

OpenAI 모델은 현재 코드의 `gpt-4`로 고정되어 있습니다. 환경 설정을 바꾼 뒤에는 서버를 재시작하세요. 이미 설정된 운영체제 환경변수가 있다면 `.env`보다 우선합니다.

### 3. 백엔드 실행

가상환경을 활성화한 터미널에서 실행합니다.

```bash
python -m uvicorn app:app --app-dir multi-llm-rrf/backend --host 127.0.0.1 --port 8000 --reload
```

- API 서버: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- API 문서: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### 4. 프런트엔드 실행

새 터미널을 열고 저장소 루트에서 실행합니다.

```bash
python -m http.server 5500 --bind 127.0.0.1 --directory multi-llm-rrf/frontend
```

[http://127.0.0.1:5500](http://127.0.0.1:5500)에 접속해 질문을 입력하고 **질의** 버튼을 누르면 됩니다. 두 터미널은 사용하는 동안 실행 상태로 유지합니다.

## 🎨 RRF 알고리즘 설명

RRF는 각 기준에서 얻은 **순위**를 점수로 바꾸어 합산합니다.

| 평가 기준 | 계산 방식 | 높은 순위를 받는 답변 |
| --- | --- | --- |
| Confidence | 모델이 응답에 포함한 자체 신뢰도 | 값이 큰 답변 |
| Keyword Overlap | 질문·답변 토큰 집합의 Jaccard 유사도 | 공통 키워드 비율이 높은 답변 |
| Brevity | 답변 문자열의 길이 | 더 짧은 답변 |

```text
RRF score = Σ 1 / (k + rank)
k = 60, rank는 1부터 시작
```

세 기준에서 모두 1위인 후보의 점수는 약 `0.04918`입니다. 기준별 가중치는 같고, 개별 평가 기준에서 값이 같으면 기존 입력 순서에 따라 OpenAI가 앞섭니다.

### 응답 처리 기준

- 숫자 문자열로 받은 `confidence`는 숫자로 변환합니다. 유한한 0–100 범위의 숫자로 해석할 수 없거나 불리언이면 기본값 `50`을 사용합니다.
- JSON 파싱에 실패한 비어 있지 않은 텍스트는 `confidence=50`, `notes=raw`로 사용합니다. JSON 객체의 `answer`가 비어 있거나 문자열이 아니면 후보에서 제외합니다.
- OpenAI의 `length`·`content_filter` 종료 응답, Claude의 `max_tokens`·`refusal`·`model_context_window_exceeded` 종료 응답은 후보에서 제외합니다.
- `provider`는 서버가 지정하며, 모델 응답에 같은 필드가 있어도 덮어쓰지 않습니다.

### Claude 모델 설정

기존 Claude 3.5 Sonnet에서 `claude-sonnet-5-5`로 기본값을 갱신했습니다. Sonnet 5.5에는 `thinking.type=between_tools`와 `output_config.effort=medium`을 보내, 도구를 쓰지 않는 이 질문 흐름에서 사전 추론을 끕니다. 출력 토큰 한도는 `1024`이며 응답의 `text` 블록만 합쳐 사용합니다.

다른 모델명을 설정하면 Sonnet 5.5 전용 옵션은 보내지 않습니다. 모델마다 지원 옵션과 비용이 다르므로 변경 후에는 연동을 확인해야 합니다.

- [Anthropic 모델 지원 상태](https://platform.claude.com/docs/en/about-claude/model-deprecations)
- [Claude Sonnet 5.5 마이그레이션 안내](https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide)
- [OpenAI 응답 종료 사유 정의](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/list)

## 🔧 API 엔드포인트

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `GET` | `/` | API 안내 메시지 |
| `POST` | `/ask` | 질문 처리와 답변 선택 |

### 요청 예시

```json
{
  "query": "수도"
}
```

### 응답 구조 예시

아래는 형식을 설명하기 위한 예시이며 실제 모델 응답을 기록한 결과가 아닙니다.

```json
{
  "query": "수도",
  "winner": {
    "provider": "openai",
    "answer": "수도",
    "confidence": 90,
    "notes": "예시"
  },
  "fused": [
    {"id": "openai", "score": 0.04918032786885246},
    {"id": "anthropic", "score": 0.04838709677419355}
  ],
  "all": [
    {"provider": "openai", "answer": "수도", "confidence": 90, "notes": "예시"},
    {"provider": "anthropic", "answer": "다른 긴 응답입니다", "confidence": 80, "notes": "예시"}
  ]
}
```

`winner`는 선택된 답변, `fused`는 RRF 점수순 목록, `all`은 성공한 모델의 답변 목록입니다. 한 모델만 성공했다면 해당 답변만 들어갑니다.

| 상태 | 응답 |
| --- | --- |
| 정상 후보가 하나 이상 있음 | `200` + 결과 |
| 질문이 비어 있거나 공백뿐임 | `400` + `query is required` |
| 요청 필드 누락 또는 형식 오류 | `422` + 검증 오류 |
| 정상 후보가 없음 | `500` + `All LLM providers failed` |

## 🧪 테스트

### 백엔드

Python 의존성을 설치하고 가상환경을 활성화한 뒤, 저장소 루트에서 실행합니다.

```bash
python -m unittest discover -s multi-llm-rrf/backend -v
```

**13개 테스트**에서 정상 응답의 순위·점수 유지, 한쪽·양쪽 호출 실패, 잘못된 신뢰도·답변 형식, 공급자 정보 덮어쓰기, 모델 설정, 여러 Claude 응답 블록, 불완전한 응답과 공백 질문을 확인합니다.

### 브라우저

개발용 Playwright와 Chromium을 준비한 뒤 실행합니다. 이 도구들은 앱 실행에는 필요하지 않습니다.

```bash
npm install --no-save --package-lock=false playwright
npx playwright install chromium
node --test multi-llm-rrf/frontend/test-ui.cjs
```

**5개 시나리오**에서 정상 결과와 HTML 문자열 표시, 연결 실패, 비JSON 응답, 상세 메시지가 있는 HTTP 400, 상세 메시지가 없는 HTTP 503을 확인합니다. Node 테스트 출력에는 상위 그룹을 포함해 6개로 집계됩니다.

이미 설치된 Chrome을 사용하려면 `CHROME_PATH` 환경변수에 실행 파일 경로를 지정할 수 있습니다.

두 테스트 모두 외부 요청을 모의 응답으로 대체합니다. 실제 API 키, 실행 중인 서버, 유료 API 호출 없이 검증할 수 있습니다.

## 🛡️ 설정 및 운영 시 주의사항

- 실제 API 키를 담은 `.env`는 커밋하지 않습니다. 설정 예시는 `.env.example`로 공유합니다.
- 현재 CORS는 로컬 개발을 위해 모든 origin을 허용합니다. 공개 배포 시에는 접근 범위를 제한해야 합니다.
- 로그인, 요청 횟수 제한, 사용량·비용 관리 기능은 구현되어 있지 않습니다.
- 화면에는 모델 응답을 HTML이나 Markdown으로 해석하지 않고 텍스트로 표시합니다.

## 🐛 트러블슈팅

| 증상 | 확인할 내용 |
| --- | --- |
| 서버 시작 시 API 키 오류 | `backend/.env` 위치와 두 키 설정 여부 확인 |
| 화면에 연결 오류 표시 | 백엔드 실행 여부와 `index.html`의 API 주소 확인 |
| 모든 모델 호출 실패 | API 키·잔액·모델 접근 권한·네트워크 확인. 잘못되거나 불완전한 응답만 받은 경우에도 발생 |
| 한 모델의 답변만 표시 | 다른 모델의 요청 또는 응답 검증이 실패하면 정상 후보만 표시됨 |
| 포트 8000 사용 중 | 실행 명령의 `--port`와 `index.html`의 요청 URL을 같은 포트로 변경 |
| 포트 5500 사용 중 | 프런트엔드 서버 포트를 바꾸고 해당 주소로 접속 |
| Playwright가 브라우저를 찾지 못함 | `npx playwright install chromium` 실행 또는 `CHROME_PATH` 지정 |

## 📌 현재 한계

- 모델의 자체 신뢰도, 키워드 일치, 짧은 길이는 사실성을 직접 검증하지 않습니다.
- 두 답변의 내용을 합쳐 새 답변을 생성하는 기능은 없습니다.
- 동점 처리에 OpenAI 우선 편향이 있으며, 기준별 가중치 조정이나 별도 평가 모델은 적용하지 않았습니다.
- 오프라인 회귀 테스트는 통과했지만, OpenAI·Anthropic의 실제 API 연동·계정별 접근 권한은 이번 검증 범위에 포함되지 않았습니다.
- 정확도·응답 시간·비용 개선은 측정하지 않았습니다. 현재 변경의 검증 범위는 코드 정리와 오류 처리입니다.

## 📝 변경 기록

### V2.1

- 공통 프롬프트·응답 파싱 정리 및 불필요한 중간 목록 제거
- 응답 형식·신뢰도 검증과 실패·불완전 응답 제외 처리 보완
- Claude 모델 기본값 갱신 및 환경변수 설정 추가
- 화면 텍스트 렌더링과 요청 오류 안내 보완
- 백엔드·브라우저 회귀 테스트 추가
- 캐시·빈 환경설정 파일 정리 및 `.gitignore` 추가
- README의 실행 방법·처리 흐름·검증 범위 정리

### V2.0

- 다중 LLM 호출, 세 가지 순위 기준의 RRF 계산, 웹 결과 화면을 갖춘 기존 구현

## 📄 라이선스

기존 README의 라이선스 표기는 MIT입니다. 라이선스 전문을 담은 별도 `LICENSE` 파일은 아직 포함되어 있지 않습니다.

## 👥 기여 및 문의

오류 제보나 개선 의견은 [GitHub Issues](https://github.com/hyunsang1021/2025GAMJA/issues)에 남겨 주세요. 변경 제안은 Pull Request로 공유할 수 있습니다.
