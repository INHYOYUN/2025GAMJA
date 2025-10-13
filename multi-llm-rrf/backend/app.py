# app.py
# Python 3.10+, pip install "fastapi[standard]" httpx python-dotenv
import os
import re
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import asyncio
import json
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

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
    return [t for t in re.sub(r"[^a-z0-9가-힣\s]", " ", (s or "").lower()).split() if t]

def jaccard(a: List[str], b: List[str]) -> float:
    A, B = set(a), set(b)
    inter = len(A & B)
    uni = len(A | B) or 1
    return inter / uni

async def call_openai(query: str) -> Dict[str, Any]:
    prompt = f"""질문에 정확히 답하고 JSON으로만 응답하세요.
필드: answer(string), confidence(0-100 number), notes(string).
질문: {query}"""
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        parsed = {"answer": text, "confidence": 50, "notes": "raw"}
        try:
            if text:
                parsed = {**parsed, **json.loads(text)}
        except Exception:
            pass
        return {"provider": "openai", **parsed}
    except Exception as e:
        return {"provider": "openai", "answer": f"Error: {str(e)}", "confidence": 0, "notes": "error"}

async def call_anthropic(query: str) -> Dict[str, Any]:
    prompt = f"""질문에 정확히 답하고 JSON으로만 응답하세요.
필드: answer(string), confidence(0-100 number), notes(string).
질문: {query}"""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
        text = ((data.get("content") or [{}])[0].get("text") or "").strip()
        parsed = {"answer": text, "confidence": 50, "notes": "raw"}
        try:
            if text:
                parsed = {**parsed, **json.loads(text)}
        except Exception:
            pass
        return {"provider": "anthropic", **parsed}
    except Exception as e:
        return {"provider": "anthropic", "answer": f"Error: {str(e)}", "confidence": 0, "notes": "error"}

def rank_by_confidence(items: List[Dict[str, Any]]):
    sorted_items = sorted(items, key=lambda x: (x.get("confidence") or 0), reverse=True)
    return [{"id": x["provider"], "rank": i + 1} for i, x in enumerate(sorted_items)]

def rank_by_keyword_overlap(items: List[Dict[str, Any]], query: str):
    qtok = tokenize(query)
    scored = [{"id": x["provider"], "score": jaccard(qtok, tokenize(x.get("answer") or ""))} for x in items]
    sorted_items = sorted(scored, key=lambda x: x["score"], reverse=True)
    return [{"id": x["id"], "rank": i + 1} for i, x in enumerate(sorted_items)]

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
    if not body.query:
        raise HTTPException(status_code=400, detail="query is required")
    
    # 각 LLM 호출 (에러가 발생해도 계속 진행)
    results = await asyncio.gather(
        call_openai(body.query),
        call_anthropic(body.query),
        return_exceptions=True
    )
    
    # 에러 처리: 모든 호출이 실패한 경우
    valid_results = [r for r in results if isinstance(r, dict) and not isinstance(r, Exception)]
    if not valid_results:
        raise HTTPException(status_code=500, detail="All LLM providers failed")
    
    # RRF 랭킹
    ranks1 = rank_by_confidence(valid_results)
    ranks2 = rank_by_keyword_overlap(valid_results, body.query)
    ranks3 = rank_by_brevity(valid_results)
    fused = rrf_fuse([ranks1, ranks2, ranks3], k=60)
    
    winner_id = fused[0]["id"]
    winner = next(x for x in valid_results if x["provider"] == winner_id)
    
    return {"query": body.query, "winner": winner, "fused": fused, "all": valid_results}
