"""
Ties every stage together: enrichment -> cache -> (extraction + deeplink
matching on cache miss) -> schema-validated response + operational metadata.
This is what both the API layer and the offline benchmark harness call, so
the two never drift.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from app.cache import SemanticCache
from app.deeplink_matcher import DeeplinkMatcher
from app.extraction import extract_goal
from app.query_enrichment import enrich_query, canonicalize
from app.response_builder import build_goal
from app.schema import ContextDeeplinkResponse
from app import llm_enhancer

MODEL_NAME = "rule-based-extraction-v1"  # deterministic core; see below for the optional AI-agent layer


def _current_model_label() -> str:
    return "rule-based-extraction-v1+groq" if llm_enhancer.is_available() else MODEL_NAME


class TroubleshootingEngine:
    def __init__(self, deeplinks: list[dict], cache_threshold: float = 0.40):
        self.matcher = DeeplinkMatcher(deeplinks)
        self.cache = SemanticCache(threshold=cache_threshold)

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
        enriched = enrich_query(query)

        lookup = self.cache.get(enriched.canonical)
        if lookup.hit and not _prewarm:
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

        if siis_response is None:
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            empty = ContextDeeplinkResponse(contexts=[]).model_dump()
            return {
                "query": query,
                "response": empty,
                "meta": {
                    "latency_ms": latency_ms,
                    "cache_hit": False,
                    "model": _current_model_label(),
                    "cost_usd": 0.0,
                    "fallback": "no_siis_context",
                },
            }

        extracted = extract_goal(siis_response, title=siis_title)
        goal, diagnostics = build_goal(extracted, self.matcher)

        if goal is None:
            response_obj = ContextDeeplinkResponse(contexts=[]).model_dump()
            fallback = "no_match"
        else:
            response_obj = ContextDeeplinkResponse(contexts=[goal]).model_dump()
            fallback = None
            self.cache.set(enriched.canonical, response_obj)
            # Also cache every paraphrase variation as its own exact-match
            # key pointing at the same response -- but ONLY when the
            # variations came from Groq (see query_enrichment.py). This is
            # empirically important, not a style choice: pre-caching the
            # deterministic *template* variations (synonym swaps / truncated
            # forms of the same seed query) was tested and made the measured
            # cross-phrasing cache-hit rate WORSE (11% -> 0%), because those
            # near-duplicate keys dilute the TF-IDF corpus used for the
            # semantic-similarity fallback without adding any genuinely new
            # phrasing. Real LLM-generated paraphrases don't have that
            # problem (they're independently worded, closer to how a
            # different user would actually phrase the same complaint), but
            # that path could not be verified in this build (no Groq network
            # access) -- see llm_enhancer.py and evaluator-analysis.md.
            if llm_enhancer.is_available():
                for variation in enriched.variations:
                    var_canonical = canonicalize(variation)
                    if var_canonical and var_canonical != enriched.canonical:
                        self.cache.set(var_canonical, response_obj)

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
    engine = TroubleshootingEngine(deeplinks)
    siis = json.loads((data_dir / "siis_responses.json").read_text())["responses"]
    engine.prewarm(siis)
    return engine
