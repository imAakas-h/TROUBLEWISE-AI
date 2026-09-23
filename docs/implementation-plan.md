# Implementation Plan & Status

## G. What should NOT be built

- An Android/Kotlin mobile app (not in the graded rubric — see specification.md)
- A real-time chat/conversational UI layered on top of the API
- Any infrastructure (queues, DBs, k8s) beyond a single FastAPI process —
  not asked for and not justified at this data scale

## H. Implementation order (as actually executed, in this session)

1. **Read every supplied file first** — `schema.py`, `sample_output.json`,
   the official PDF spec, `deeplinks.json`/`siis_responses.json` structure,
   `input.txt` — before writing any code.
2. **Query enrichment** (`query_enrichment.py`) — canonicalization +
   template paraphrase generation.
3. **Structure extraction** (`extraction.py`) — heading-based segmentation
   of SIIS text into Goal/Action/StepGroup, with keyword-based category
   classification.
4. **Deeplink matcher** (`deeplink_matcher.py`) — hybrid BM25 + TF-IDF.
   *This stage needed three real bug fixes found through testing, not
   assumption:*
   - A substring-match bug where the keyword `"wipe"` matched inside the
     unrelated word `"Swipe"`, silently reclassifying a "swipe to open
     Quick settings" step as a destructive `critical` action. Fixed by
     switching every keyword check to word-boundary regex.
   - False-positive deeplink matches driven by generic shared vocabulary
     ("device", "button", "settings") outranking genuinely specific shared
     terms. Fixed with a domain stopword list, a hard lexical-overlap gate,
     and reweighting the BM25/cosine blend toward cosine (which naturally
     IDF-downweights common terms).
   - Hardware/physical actions (button-holds, charging, SIM tray) being
     treated as reachable via a Settings deeplink. Fixed by routing them to
     `manual` before matching is even attempted.
5. **Response builder** (`response_builder.py`) — schema assembly with
   every word-count/prefix/category rule enforced in code.
6. **Semantic cache** (`cache.py`) + **pipeline orchestration**
   (`pipeline.py`) — found and fixed a bug where `prewarm()` computed
   responses but never wrote them to the cache.
7. **FastAPI app** (`main.py`) — thin wrapper exposing the two official
   endpoints; verified against curl locally (`/health`, both the
   cache-hit and no-context-fallback paths of `/v1/troubleshoot`).
8. **Benchmark harness** (`tests/run_benchmark.py`) — schema validation,
   URL-leak check, catalog-integrity check, latency, unseen-scenario test,
   and the cross-phrasing cache-hit measurement. This is what produced
   every number in evaluator-analysis.md — nothing there is estimated.

## Current status vs. the spec's own success checklist

| Criterion | Status |
|---|---|
| Official API works (`/v1/troubleshoot`, `/health`) | ✅ verified |
| Official schema respected | ✅ 0 violations / 20 |
| SIIS is the source of truth, no hallucinated steps | ✅ by construction (no LLM in the loop) |
| No invented Samsung URIs | ✅ 0 unknown URIs |
| Auto actions carry required deeplinks | ✅ 26/26 (100%) |
| Zero URL leaks | ✅ 0 across all tests |
| Exact/near-duplicate cache works | ✅ 20/20, <1ms |
| Semantic cache on genuine paraphrases | ⚠️ 11% measured, target 80% — documented, root-caused, fix identified |
| Unseen scenarios generalize | ✅ tested with a topic outside the 20 seed scenarios |
| Latency targets | ✅ cached ~0.1ms (target 300ms), cold ~4-30ms (target 8000ms) |
| Cost | ✅ $0.00 — no LLM calls in this build |

## Recommended next steps, in priority order

1. **Close the semantic-cache gap** — swap `cache.py`'s TF-IDF vectorizer
   for a real sentence-embedding model. Highest-leverage single change
   against the graded rubric.
2. **Expand keyword lists from a larger sample** — the category classifier
   was tuned against the 20 supplied scenarios; running it against more
   SIIS-style text before the final submission would surface any remaining
   phrasing gaps.
3. **Add a small LLM-assisted rewrite pass on `action.description`** (still
   validated/corrected programmatically afterward) to make the "It will..."
   descriptions read a bit more naturally than the current template.
4. **Only after 1-3**, consider a thin demo-facing HTML page (not a mobile
   app) if a live demo needs something more visual than curl/Postman.
