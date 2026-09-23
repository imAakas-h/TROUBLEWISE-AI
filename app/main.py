"""
Layer 1 — the official competition engine.

    POST /v1/troubleshoot   {"query": str, "siis_response": Optional[str]}
    GET  /health             -> {"status": "ok"}

Pure JSON in, pure JSON out -- no markdown fences, no conversational preamble.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Literal

from dotenv import load_dotenv
load_dotenv()  # picks up GROQ_API_KEY from a local .env if present; no-op otherwise

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.pipeline import load_engine
from app import llm_enhancer
from app.experience_memory import record_experience, find_relevant_experiences, count as experience_count

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

app = FastAPI(title="Smart Guided Troubleshooting Engine", version="0.1.0")

# Wide open for local/demo use (the frontend/ folder is a static page served
# from a different origin/port). Tighten this to your actual frontend origin
# before deploying anywhere public.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_engine = None


class TroubleshootRequest(BaseModel):
    query: str
    siis_response: Optional[str] = None


class GuidanceRequest(BaseModel):
    query: str
    response: dict


class FeedbackRequest(BaseModel):
    query: str
    outcome: Literal["solved", "not_solved"]
    action_name: Optional[str] = None
    note: Optional[str] = None


@app.on_event("startup")
def _startup() -> None:
    global _engine
    _engine = load_engine(DATA_DIR)


@app.get("/health")
def health() -> dict:
    ready = _engine is not None
    return {"status": "ok" if ready else "initializing"}


@app.post("/v1/troubleshoot")
def troubleshoot(req: TroubleshootRequest) -> JSONResponse:
    result = _engine.run(query=req.query, siis_response=req.siis_response)
    return JSONResponse(content=result)


@app.post("/v1/guidance")
def guidance(req: GuidanceRequest) -> JSONResponse:
    """AI explanation layer over the already-grounded troubleshooting result."""
    experiences = find_relevant_experiences(req.query, limit=3)
    ai = llm_enhancer.generate_guidance(
        query=req.query,
        grounded_response=req.response,
        experiences=experiences,
    )
    if ai is None:
        ai = {
            "message": "Follow the grounded steps in order. If a step does not help, record what happened so the assistant can use that experience on similar future problems.",
            "experience_insight": "",
            "next_question": "What happened after you tried the latest step?",
        }
        model = "deterministic-guidance-fallback"
    else:
        model = GROQ_MODEL if "GROQ_MODEL" in globals() else llm_enhancer.GROQ_MODEL

    return JSONResponse(content={
        "guidance": ai,
        "model": model,
        "experience_matches": len(experiences),
        "experience_memory_size": experience_count(),
    })


@app.post("/v1/feedback")
def feedback(req: FeedbackRequest) -> JSONResponse:
    """Store a user's troubleshooting outcome for future retrieval."""
    item = record_experience(
        query=req.query,
        outcome=req.outcome,
        action_name=req.action_name,
        note=req.note,
    )
    return JSONResponse(content={
        "status": "stored",
        "outcome": item["outcome"],
        "experience_memory_size": experience_count(),
    })
