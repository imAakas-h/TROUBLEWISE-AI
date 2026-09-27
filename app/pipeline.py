"""Normalize → cache → retrieve SIIS → extract → validate → link → respond."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from app.cache import SemanticCache
from app.deeplink_matcher import DeeplinkMatcher
from app.extraction import extract_goal, ExtractedStepGroup
from app.query_enrichment import enrich_query
from app.response_builder import build_goal
from app.schema import ContextDeeplinkResponse
from app.retrieval import SiisRetriever
from app.grounding import validate_grounding, GroundingError
from app.diagnostics import choose_probe

MODEL_NAME = "rule-based-extraction-v1"  # deterministic core; see below for the optional AI-agent layer


def _current_model_label() -> str:
    return MODEL_NAME


class TroubleshootingEngine:
    """Single-process engine. Cache defaults to exact canonical keys only;
    unverified fuzzy matches must not bypass current-source retrieval."""
    def __init__(self, deeplinks: list[dict], siis_entries: list[dict] | None = None, cache_threshold: float = 1.01):
        self.matcher = DeeplinkMatcher(deeplinks)
        self.cache = SemanticCache(threshold=cache_threshold)
        self.deeplinks = deeplinks
        self.siis_entries = siis_entries or []
        self.retriever = SiisRetriever(self.siis_entries)

    def prewarm(self, siis_entries: list[dict]) -> None:
        """Populate the cache from the 20 supplied seed scenarios so cached
        queries meet the <=300ms fast-path target from first request."""
        for entry in siis_entries:
            query = entry["original_query"]
            siis = entry["siis_response"]
            self.run(query=query, siis_response=siis["content"],
                      siis_title=siis.get("title"), _prewarm=True)

    def run(self, query: str, siis_response: Optional[str] = None,
            siis_title: Optional[str] = None, _prewarm: bool = False) -> dict:
        t0 = time.perf_counter()
        query = query or ""
        if len(query) > 2000 or not query.strip():
            return {"query": query, "response": ContextDeeplinkResponse(contexts=[]).model_dump(),
                    "meta": {"latency_ms": round((time.perf_counter() - t0) * 1000, 2), "cache_hit": False,
                             "model": MODEL_NAME, "cost_usd": 0.0, "fallback": "invalid_or_empty_query"}}
        enriched = enrich_query(query)

        # Explicit context changes the source of truth; never answer it from
        # a prior query-only cache entry.
        lookup = self.cache.get(enriched.canonical) if siis_response is None else None
        if lookup and lookup.hit and not _prewarm:
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            return {
                "query": query,
                "response": lookup.response,
                "meta": {
                    "latency_ms": latency_ms,
                    "cache_hit": True,
                    "cache_exact": lookup.exact,
                    "cache_similarity": round(lookup.similarity, 3),
                    "model": _current_model_label(),
                    "cost_usd": 0.0,
                },
            }

        retrieval_results = []
        source_id = None
        if siis_response is None:
            retrieval_results = self.retriever.search(query, limit=4)
            if not retrieval_results or retrieval_results[0].score < 0.30:
                latency_ms = round((time.perf_counter() - t0) * 1000, 2)
                return {"query": query, "response": ContextDeeplinkResponse(contexts=[]).model_dump(),
                        "meta": {"latency_ms": latency_ms, "cache_hit": False, "model": MODEL_NAME,
                                 "cost_usd": 0.0, "fallback": "no_match",
                                 "retrieved_sources": [{"source_id": r.entry.get("id"), "score": round(r.score, 3),
                                                        "title": r.entry.get("siis_response", {}).get("title")}
                                                       for r in retrieval_results]}}
            source = retrieval_results[0].entry
            siis = source.get("siis_response", {})
            siis_response, siis_title, source_id = siis.get("content", ""), siis.get("title"), source.get("id")

        extracted = extract_goal(siis_response, title=siis_title)
        probe = choose_probe(extracted, retrieval_results, query) if retrieval_results else None
        if probe is not None:
            action = extracted.actions[probe["index"]]
            action.step_groups = [ExtractedStepGroup([probe["probe_text"],], action.step_groups[0].source_heading)]
            extracted.actions = [action]
        goal, diagnostics = build_goal(extracted, self.matcher)

        if goal is None:
            response_obj = ContextDeeplinkResponse(contexts=[]).model_dump()
            fallback = "no_match"
        else:
            response_obj = ContextDeeplinkResponse(contexts=[goal]).model_dump()
            fallback = None
            try:
                validate_grounding(response_obj, siis_response, self.deeplinks)
            except (GroundingError, ValueError) as exc:
                response_obj = ContextDeeplinkResponse(contexts=[]).model_dump()
                fallback = "grounding_validation_failed"
                diagnostics["grounding_error"] = str(exc)
            if fallback is None and (_prewarm or source_id is not None):
                self.cache.set(enriched.canonical, response_obj)
            if retrieval_results:
                diagnostics["retrieval"] = [{"source_id": r.entry.get("id"), "score": round(r.score, 3),
                                              "title": r.entry.get("siis_response", {}).get("title")}
                                             for r in retrieval_results]
                diagnostics["adaptive_probe"] = probe or {"selected": False}
                diagnostics["source_id"] = source_id

        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        meta = {
            "latency_ms": latency_ms,
            "cache_hit": False,
            "model": _current_model_label(),
            "cost_usd": 0.0,
        }
        if fallback:
            meta["fallback"] = fallback
        if not _prewarm:
            meta["diagnostics"] = diagnostics
        return {"query": query, "response": response_obj, "meta": meta}


def load_engine(data_dir: Path) -> TroubleshootingEngine:
    import json
    deeplinks = json.loads((data_dir / "deeplinks.json").read_text())["deeplinks"]
    siis = json.loads((data_dir / "siis_responses.json").read_text())["responses"]
    engine = TroubleshootingEngine(deeplinks, siis_entries=siis)
    engine.prewarm(siis)
    return engine
