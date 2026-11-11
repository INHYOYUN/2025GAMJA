# app.py
# Python 3.10+, pip install "fastapi[standard]" httpx python-dotenv
import os
import re
import asyncio
import json
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "").strip() or "claude-sonnet-5-5"

PROMPT = """질문에 정확히 답하고 JSON으로만 응답하세요.
필드: answer(string), notes(string).
질문: """

if not OPENAI_API_KEY or not ANTHROPIC_API_KEY:
    raise RuntimeError("Set OPENAI_API_KEY and ANTHROPIC_API_KEY environment variables")


app = FastAPI(title="Multi-LLM RRF")

# 루트 경로에 안내 메시지 반환
@app.get("/")
def root():
    return {"message": "Multi-LLM RRF API. Use /ask endpoint for queries."}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 개발 환경용 - 프로덕션에서는 특정 도메인으로 제한
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
        raise ValueError("Expected- an answer object")
    answer = parsed.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("Expected a non-empty answer string")
    notes = parsed.get("notes", "raw")
    return {"provider": provider, "answer": answer,
            "notes": notes if isinstance(notes, str) else "raw"}


async def call_openai(query: str) -> Dict[str, Any]:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
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
        "x-api-key": ANTHROPIC_API_KEY,
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
