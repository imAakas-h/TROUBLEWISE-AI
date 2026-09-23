# Evaluator Analysis — Measured Against This Build

Numbers below are from `tests/run_benchmark.py`, re-run at any time; nothing
here is estimated or aspirational.

## A. What the evaluator actually measures

Per spec section 6: schema conformance, zero fabricated URLs/URIs,
deterministic output, deeplink screen-resolution accuracy, semantic
paraphrase cache-hit rate, action ordering, and P50/P95 latency at two
tiers (cached vs cold).

## B. What can cause score loss

- **Schema violations** — wrong word counts, wrong `goal`/`description`
  prefixes, category enum mismatches. *Measured: 0/20 seed scenarios
  violate any rule* (see benchmark output below).
- **Fabricated or altered deeplinks** — any URI not a verbatim catalog
  copy. *Measured: 0 unknown URIs across all runs* — the matcher can only
  return `entry["deeplink"]` unmodified or the reserved
  `bixby://dummy_positive` placeholder, never a constructed string.
- **Manual actions carrying a deeplink** — explicitly forbidden.
  *Measured: 0 occurrences* (`response_builder.py` never attaches a
  deeplink to a `manual`-category action).
- **Weak paraphrase generalization** — this is the real risk in this
  build. See below.

## C. What should be deterministic

Everything except paraphrase-matching confidence: identical input always
produces an identical, byte-for-byte response (same `Goal`/`Action`
objects), because extraction is pure regex/keyword logic and matching is a
fixed TF-IDF/BM25 index built once at startup — no sampling, no
temperature, no LLM call in the hot path.

## D. Where an LLM is (and isn't) actually useful

**Not used in this build** — no model credentials or embedding-API network
access are available in this sandbox (huggingface.co and llm endpoints
aren't on the environment's network allowlist). Every stage that an LLM
would improve is isolated behind one function so it's a contained swap:

| Stage | Current approach | LLM/embedding upgrade |
|---|---|---|
| Query enrichment | regex canonicalization + template paraphrases | LLM-generated canonical form + fluent paraphrases |
| Structure extraction | heading/keyword segmentation | LLM-assisted extraction with the same anti-hallucination constraint (must cite source spans) |
| Deeplink matching | BM25 + TF-IDF hybrid | real sentence-embedding model (this is the one that matters most — see below) |

## E. Measured results

```
Schema & rule compliance:      0 violations / 20 seed scenarios
'auto' actions w/ resolved dl:  26/26 (100%)
Fabricated/unknown URIs:       0
Manual actions w/ a deeplink:  0 (forbidden case never triggered)

Cache-hit latency:   P50 0.12ms | P95 0.15ms | max 0.16ms   (target: <=300ms — met by ~2000x)
Cold-path latency:   P50 3.6ms  | max 29.5ms  (n=8)          (target: <=8000ms — met comfortably)

Exact/near-duplicate cache hit rate:        20/20 (100%) on the seed set itself
Cross-phrasing semantic cache hit rate:     1/9 = 11%  <-- below the 80% target
```

The cross-phrasing number is the honest headline finding: seeded with one
worded version of each of the kit's SIIS topics, then tested against every
*other* differently-worded real user complaint mapped to that same topic
(these are real complaints from `input.txt`/`siis_responses.json`, not
synthetic ones), only 1 of 9 cross-phrasings hit the cache.

**Why:** TF-IDF cosine similarity over short canonicalized strings is a
lexical-overlap proxy, not a semantic one. Two genuinely different users
describing the same "black screen" symptom often share only 1-2 words after
stopword removal — nowhere near enough lexical overlap for cosine
similarity to clear a safe acceptance threshold. Lowering the threshold to
chase the 80% target was tested and rejected: it started returning
wrong-topic matches (verified concretely — a threshold of 0.40 pulled in a
security/fingerprint-related cached response for what should have been a
display-hardware query at 0.32 similarity). **A wrong cache hit is worse
than a cache miss** — a miss just costs latency by falling through to the
(still well under budget) cold path; a wrong hit returns the wrong
troubleshooting plan entirely, which directly damages the "Deeplink
Relevance" and "Step accuracy" scoring dimensions. Given that tradeoff, this
build keeps the threshold conservative and reports the real number rather
than gaming the metric.

**Path to the 80% target:** replace the TF-IDF vectorizer in `cache.py` with
a real sentence-embedding model (e.g. a small local model, or an API-based
one if network access is available in the production environment) — the
`SemanticCache` interface doesn't need to change, only the vectorization
call inside `get`/`set`.

## F. Unseen-scenario handling

Tested with a speaker-distortion complaint that has no corresponding entry
anywhere in the 20 supplied SIIS scenarios. Result: 0 schema violations,
sensible 4-action extraction (2 auto with real catalog deeplinks, 2 manual
with none), correctly ordered auto-before-manual. Confirms the pipeline
doesn't rely on hardcoded scenario matching.
