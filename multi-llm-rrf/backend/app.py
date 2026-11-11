# app.py
# Python 3.10+, pip install -r requirements.txt
import os
import re
import asyncio
import json
from ipaddress import ip_address
from pathlib import Path
from threading import Lock
from typing import List, Dict, Any, Literal
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
import httpx
import openai
import anthropic
from dotenv import dotenv_values, set_key

ENV_FILE = Path(__file__).with_name(".env")
PROVIDER_ENV = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
LOCAL_ORIGINS = [
    "http://127.0.0.1:5500", "http://localhost:5500",
    "http://127.0.0.1:8000", "http://localhost:8000",
]
# ponytail: one process; use a shared lock/store before supporting multiple workers.
KEY_LOCK = Lock()
MODEL_LIST_DEADLINE = 20.0


def read_env():
    try:
        # Treat API keys literally, including a possible ${...} sequence.
        return dotenv_values(ENV_FILE, interpolate=False)
    except (OSError, UnicodeError):
        raise HTTPException(status_code=500, detail="API 키 설정을 읽을 수 없습니다. backend/.env 파일을 확인해 주세요.") from None


file_config = read_env()
API_KEYS = {
    provider: os.getenv(name, "").strip() or (file_config.get(name) or "").strip()
    for provider, name in PROVIDER_ENV.items()
}
ANTHROPIC_MODEL = (os.getenv("ANTHROPIC_MODEL") or file_config.get("ANTHROPIC_MODEL") or "").strip() or "claude-sonnet-5-5"
del file_config

PROMPT = """질문에 정확히 답하고 JSON으로만 응답하세요.
필드: answer(string), notes(string).
질문: """

app = FastAPI(title="Multi-LLM RRF")

# 루트 경로에 안내 메시지 반환
@app.get("/")
def root():
    return {"message": "Multi-LLM RRF API. Use /ask endpoint for queries."}

app.add_middleware(
    CORSMiddleware,
    allow_origins=LOCAL_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def settings_no_store(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in {"/settings/keys", "/settings/models"}:
        response.headers["Cache-Control"] = "no-store"
    return response


class ListModelsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["openai", "anthropic"]


class RegisterKeyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["openai", "anthropic"]
    api_key: SecretStr = Field(min_length=1, max_length=512)

    @field_validator("api_key")
    @classmethod
    def validate_key_characters(cls, value):
        # Printable ASCII fits provider headers; no backslashes avoids older dotenv escaping bugs.
        if any(ord(c) < 33 or ord(c) > 126 or c == "\\" for c in value.get_secret_value()):
            raise ValueError("API 키에 사용할 수 없는 문자가 있습니다")
        return value


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    if request.url.path in {"/settings/keys", "/settings/models"}:
        # FastAPI's default validation response includes the raw input.
        return JSONResponse(status_code=422, content={
            "detail": "OpenAI 또는 Anthropic만 선택해 주세요." if request.url.path == "/settings/models" else
                      "OpenAI 또는 Anthropic을 선택하고 공백·제어 문자·역슬래시가 없는 1~512자의 영문·숫자·기호 API 키를 입력해 주세요."
        })
    return await request_validation_exception_handler(request, exc)


def require_local_settings(request: Request):
    try:
        local_client = request.client is not None and ip_address(request.client.host).is_loopback
    except ValueError:
        local_client = False
    if request.url.hostname not in {"localhost", "127.0.0.1"} or not local_client:
        raise HTTPException(status_code=403, detail="API 키 설정은 이 컴퓨터의 localhost에서만 사용할 수 있습니다.")
    if request.method == "POST":
        origins = request.headers.getlist("origin")
        if len(origins) != 1 or origins[0] not in LOCAL_ORIGINS:
            raise HTTPException(status_code=403, detail="로컬 앱 화면에서 API 키 설정을 열어 주세요.")


def key_status():
    # Caller holds KEY_LOCK. Keep active keys; adopt only newly configured keys.
    if not all(API_KEYS.values()):
        values = read_env()
        for provider, name in PROVIDER_ENV.items():
            if not API_KEYS[provider]:
                API_KEYS[provider] = (values.get(name) or "").strip()
    return {"providers": {provider: bool(key) for provider, key in API_KEYS.items()}}


@app.get("/settings/keys", dependencies=[Depends(require_local_settings)])
def get_keys(response: Response):
    response.headers["Cache-Control"] = "no-store"
    with KEY_LOCK:
        return key_status()


async def list_verified_models(provider: str, api_key: str):
    """Verify only model-list access; keep SDK clients and catalogs request-scoped."""
    sdk = openai if provider == "openai" else anthropic
    client_type = openai.AsyncOpenAI if provider == "openai" else anthropic.AsyncAnthropic
    base_url = "https://api.openai.com/v1" if provider == "openai" else "https://api.anthropic.com"

    async def bind_candidate_key(request):
        # SDK custom-header environment variables must not substitute another credential/host.
        request.headers["Authorization"] = f"Bearer {api_key}"
        request.headers["Host"] = f"api.{provider}.com"
        request.headers.pop("x-api-key", None)

    async def collect_models():
        models = {}
        async with sdk.DefaultAsyncHttpxClient(
            follow_redirects=False, event_hooks={"request": [bind_candidate_key]}
        ) as http_client:
            async with client_type(api_key=api_key, base_url=base_url, timeout=10.0,
                                   max_retries=0, http_client=http_client) as client:
                page = await client.models.list()
                # Use the SDK's cursor handling; OpenAI currently returns a single page.
                async for page in page.iter_pages():
                    if not isinstance(getattr(page, "data", None), list):
                        raise ValueError("Invalid model list")
                    if provider == "anthropic":
                        if page.has_more is not None and not isinstance(page.has_more, bool):
                            raise ValueError("Invalid model pagination")
                        if page.has_more is True and (
                            not page.data or not isinstance(page.last_id, str) or not page.last_id.strip()
                        ):
                            raise ValueError("Incomplete model list")
                    for model in page.data:
                        model_id = getattr(model, "id", None)
                        if not isinstance(model_id, str) or not model_id.strip():
                            raise ValueError("Invalid model identifier")
                        name = getattr(model, "display_name", None) if provider == "anthropic" else None
                        if name is not None and not isinstance(name, str):
                            raise ValueError("Invalid model name")
                        if api_key in model_id or (name and api_key in name):
                            raise ValueError("Credential echoed in model list")
                        models[model_id] = {"id": model_id, "display_name": name or model_id}
        return [models[model_id] for model_id in sorted(models)]

    try:
        return await asyncio.wait_for(collect_models(), timeout=MODEL_LIST_DEADLINE)
    except (openai.APITimeoutError, anthropic.APITimeoutError, asyncio.TimeoutError):
        raise HTTPException(status_code=504, detail="모델 목록 확인 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.") from None
    except (openai.APIStatusError, anthropic.APIStatusError) as exc:
        errors = {
            401: "API 키 인증에 실패했습니다. 키를 확인해 주세요.",
            403: "이 API 키에는 모델 목록을 조회할 권한이 없습니다. 제공업체의 권한 설정을 확인해 주세요.",
            429: "제공업체의 요청 한도에 도달했습니다. 잠시 후 다시 시도해 주세요.",
        }
        status = exc.status_code if exc.status_code in errors else 502
        raise HTTPException(status_code=status, detail=errors.get(status,
            "제공업체의 모델 목록을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.")) from None
    except (openai.APIError, anthropic.APIError, ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=502, detail="제공업체의 모델 목록을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.") from None


@app.post("/settings/models", dependencies=[Depends(require_local_settings)])
async def list_models(body: ListModelsBody):
    with KEY_LOCK:
        if not key_status()["providers"][body.provider]:
            raise HTTPException(status_code=409, detail="먼저 이 제공업체의 API 키를 등록해 주세요.")
        api_key = API_KEYS[body.provider]
    models = await list_verified_models(body.provider, api_key)
    return {"provider": body.provider, "verified": True, "models": models}


@app.post("/settings/keys", status_code=201, dependencies=[Depends(require_local_settings)])
async def register_key(body: RegisterKeyBody):
    with KEY_LOCK:
        if key_status()["providers"][body.provider]:
            raise HTTPException(status_code=409, detail="이 제공업체의 API 키가 이미 등록되어 있습니다.")
    api_key = body.api_key.get_secret_value()
    models = await list_verified_models(body.provider, api_key)
    with KEY_LOCK:
        # Another registration or an external .env edit may have won during the network wait.
        if key_status()["providers"][body.provider]:
            raise HTTPException(status_code=409, detail="이 제공업체의 API 키가 이미 등록되어 있습니다.")
        try:
            if ENV_FILE.is_symlink():
                raise OSError("The settings file must not be a symlink")
            if os.name == "posix" and ENV_FILE.exists():
                # Set permissions before the atomic write so a failed chmod cannot save a key.
                ENV_FILE.chmod(0o600)
            if not set_key(ENV_FILE, PROVIDER_ENV[body.provider], api_key)[0]:
                raise OSError("The settings file was not saved")
        except (OSError, UnicodeError):
            raise HTTPException(status_code=500, detail="API 키를 저장하지 못했습니다. backend/.env 파일 권한을 확인한 뒤 다시 시도해 주세요.") from None
        API_KEYS[body.provider] = api_key
        return {"providers": {provider: bool(key) for provider, key in API_KEYS.items()},
                "provider": body.provider, "verified": True, "models": models}


class AskBody(BaseModel):
    query: str

def tokenize(s: str) -> List[str]:
    return re.sub(r"[^a-z0-9가-힣\s]", " ", (s or "").lower()).split()

def jaccard(a: List[str], b: List[str]) -> float:
    A, B = set(a), set(b)
    inter = len(A & B)
    uni = len(A | B) or 1
    return inter / uni

def parse_answer(text: str, provider: str) -> Dict[str, Any]:
    text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = {"answer": text, "notes": "raw"}
    if not isinstance(parsed, dict):
        raise ValueError("Expected an answer object")
    answer = parsed.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("Expected a non-empty answer string")
    notes = parsed.get("notes", "raw")
    return {"provider": provider, "answer": answer,
            "notes": notes if isinstance(notes, str) else "raw"}


async def call_openai(query: str) -> Dict[str, Any]:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEYS['openai']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": PROMPT + query}],
        "temperature": 0.7,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
    choice = data["choices"][0]
    if choice.get("finish_reason") in {"length", "content_filter"}:
        raise ValueError("OpenAI did not complete an answer")
    return parse_answer(choice["message"]["content"], "openai")

async def call_anthropic(query: str) -> Dict[str, Any]:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": API_KEYS["anthropic"],
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": PROMPT + query}],
    }
    if ANTHROPIC_MODEL == "claude-sonnet-5-5":
        # No tools: preserve direct answering within the existing output-token cap.
        payload["thinking"] = {"type": "between_tools"}
        payload["output_config"] = {"effort": "medium"}
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
    if data.get("stop_reason") in {"max_tokens", "refusal", "model_context_window_exceeded"}:
        raise ValueError("Claude did not complete an answer")
    text = "".join(block["text"] for block in data["content"] if block.get("type") == "text")
    return parse_answer(text, "anthropic")

def rank_by_keyword_overlap(items: List[Dict[str, Any]], query: str):
    qtok = tokenize(query)
    sorted_items = sorted(items, key=lambda x: jaccard(qtok, tokenize(x.get("answer") or "")), reverse=True)
    return [{"id": x["provider"], "rank": i + 1} for i, x in enumerate(sorted_items)]

def rank_by_brevity(items: List[Dict[str, Any]]):
    sorted_items = sorted(items, key=lambda x: len(x.get("answer") or ""))
    return [{"id": x["provider"], "rank": i + 1} for i, x in enumerate(sorted_items)]

def rrf_fuse(rank_lists, k: int = 60):
    scores = {}
    for ranks in rank_lists:
        for entry in ranks:
            rid, rnk = entry["id"], entry["rank"]
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rnk)
    return [{"id": k_, "score": v} for k_, v in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)]

@app.post("/ask")
async def ask(body: AskBody):
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="query is required")
    with KEY_LOCK:
        if not all(key_status()["providers"].values()):
            raise HTTPException(status_code=409, detail="질문하기 전에 API 키 설정에서 OpenAI와 Anthropic 키를 모두 등록해 주세요.")
    
    # 각 LLM 호출 (에러가 발생해도 계속 진행)
    results = await asyncio.gather(
        call_openai(body.query),
        call_anthropic(body.query),
        return_exceptions=True
    )
    
    # 에러 처리: 모든 호출이 실패한 경우
    valid_results = [r for r in results if isinstance(r, dict)]
    if not valid_results:
        raise HTTPException(status_code=500, detail="All LLM providers failed")
    
    # RRF 랭킹
    ranks1 = rank_by_keyword_overlap(valid_results, body.query)
    ranks2 = rank_by_brevity(valid_results)
    fused = rrf_fuse([ranks1, ranks2], k=60)
    
    winner_id = fused[0]["id"]
    winner = next(x for x in valid_results if x["provider"] == winner_id)
    
    return {"query": body.query, "winner": winner, "fused": fused, "all": valid_results}
