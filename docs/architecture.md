# Architecture

## Pipeline

```
Raw complaint
     |
     v
[0] Query Enrichment (query_enrichment.py)
     - strip device model mentions, expand contractions
     - normalize synonyms (dark/blank -> black, etc.)
     - produce canonical string = semantic-cache key
     |
     v
[Cache lookup] (cache.py) -- exact dict hit, then pure-Python TF-IDF cosine over cached keys
     |                          |
     | miss                     | hit -> return cached response, <1ms
     v
[1] Structure Extraction (extraction.py)
     - segment SIIS text on ## / ### headings
     - each heading -> one candidate Action (one physical screen/feature)
     - sentence-split the body -> StepGroup.steps
     - classify category by keyword cue:
         service-center / hardware-button phrases -> manual
         factory reset / software update / restart -> critical
         explicit Settings/menu navigation language -> auto
         nothing matched -> manual (safe default; never guess a deeplink
         for text with no software/settings cue)
     - sort actions: auto -> critical -> manual
     |
     v
[2] Deeplink Matching (deeplink_matcher.py)
     - hybrid BM25 (lexical) + pure-Python TF-IDF cosine (semantic-ish), domain
       stopword filtering to stop generic words ("device", "button",
       "settings") manufacturing false matches
     - hard lexical-overlap gate: winning candidate must share at least
       one *specific* token with the query, not just a generic one
     - accept / fallback-to-dummy_positive / no-deeplink-at-all, by
       confidence tier
     |
     v
[response_builder.py]
     - builds schema.Goal/Action/StepGroup objects
     - programmatically enforces every word-count/prefix/enum rule
       (never left to hope-the-model-follows-instructions)
     - validates via pydantic before returning
     |
     v
[3] Cache write (successful, non-empty results only)
     |
     v
JSON response + {latency_ms, cache_hit, model, cost_usd, diagnostics}
```

## Why this shape

**Deterministic core, LLM-shaped seams.** Every stage is currently
rule-based (regex, keyword lists, BM25/TF-IDF) because no model credentials
or embedding-API network access exist in this build sandbox. But each stage
is a single function with a narrow interface
(`enrich_query`, `extract_goal`, `DeeplinkMatcher.match`), specifically so
that swapping in a real LLM or embedding model later is a one-file change,
not a rewrite. This also means the *current* system is 100% deterministic
end-to-end (a genuine plus for the "Deterministic Execution" grading gate),
and has zero per-query inference cost.

**No hallucination by construction, not by prompting.** The extraction
stage only ever emits text that appears in the supplied SIIS content — it
segments and lightly reformats, it never generates new sentences. The
deeplink matcher can only return a verbatim catalog URI or the reserved
placeholder. There's no LLM in the loop to hallucinate a step or a URL in
the first place, which sidesteps the entire class of "did the LLM follow
the no-invention instruction" risk. This is a genuine tradeoff against
fluency (see the extraction rewording quality, which is closer to
"repackaged source text" than "polished prose") and against the semantic
cache hit rate (11% measured — see evaluator-analysis.md) — an LLM /
embedding model in either the extraction or cache stage would likely
recover fluency and hit-rate, at the cost of introducing hallucination risk
that would then need active guarding.

## Known gaps (stated plainly, not glossed over)

1. **Semantic cache hit rate on cross-phrasing (11% measured, target 80%).**
   Root cause and fix are in evaluator-analysis.md section E. This is the
   single highest-leverage improvement available for a v2.
2. **Cache doesn't scale past ~hundreds of entries as built.** `cache.py`
   refits a TF-IDF matrix on every semantic lookup — fine at demo scale (20
   seed scenarios + paraphrases), not for the stated 10k+ scenario
   production target. A production version needs a persisted embedding
   index (e.g. an approximate-nearest-neighbor store) rather than a refit-
   per-query in-memory matrix.
3. **Heuristic classification is keyword-based**, so it can misfire on
   phrasing outside the keyword lists (documented and partially mitigated
   with a "no cue found -> default to manual" safety net, so the failure
   mode is under-linking, not fabricating a wrong deeplink).
4. **Title/topic condensation** (`extraction._condense_topic`) is a simple
   stopword-strip heuristic; on messy source text (SIIS entries with
   embedded category-tag prefixes and no clean title) it can produce an
   awkward but schema-valid short title rather than a polished one.

## What was NOT built, on purpose

- No mobile/Android client. Out of scope for the graded deliverable (see
  specification.md). If you want a demo-facing client later, a thin HTML
  page hitting `/v1/troubleshoot` is a lower-risk way to show it off than a
  full native app, and doesn't touch the evaluator-critical backend.
- No queue/worker infrastructure, no database — not needed at this scale
  and not requested by the spec.

## Addendum: frontend/ and the optional Groq layer

Since this doc was written, a `frontend/` (mobile-first static HTML/CSS/JS,
no build step) and an optional Groq-based AI-agent layer
(`app/llm_enhancer.py`) were added for demo purposes — see the root
`README.md` for full detail. Neither changes anything above: the frontend
is a thin `fetch()` client with zero business logic, and the Groq layer only
ever supplies text that's re-validated against the schema before use, with
every call wrapped to fail silently back to the deterministic path described
in this document. The pipeline diagram, the known gaps, and the "what was
not built" list all still hold for the core engine.
