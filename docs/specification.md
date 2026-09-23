# Official Specification — What Was Actually Asked For

## The deliverable

A REST API, not a mobile app, not a chatbot UI. Per the official brief and
your own scope slide: **"Deliverable is a REST API returning structured
JSON."** Two endpoints:

- `POST /v1/troubleshoot` — `{"query": str, "siis_response": Optional[str]}` in,
  a `schema.ContextDeeplinkResponse` out.
- `GET /health` — readiness probe (caching layer, model connections, vector
  indexes fully initialized).

## The pipeline the spec describes

```
Raw Complaint (+ optional SIIS text)
  -> [0] Query Enrichment       (canonicalize, generate 8-10 paraphrases)
  -> [1] Structure Extraction    (SIIS text -> Goal/Action/StepGroup, no invention)
  -> [2] Deeplink Mapping        (match steps to catalog screens, order least-disruptive-first)
  -> [3] Fast-Path Semantic Cache (<=300ms on hit, full pipeline on miss)
  -> [4] REST API                (expose latency/cache_hit/cost metadata)
```

## Non-negotiable field rules (section 4.1 of the spec)

| Field | Rule |
|---|---|
| `goal` | Exact syntax: "Follow these steps to perform this `<Topic>` Troubleshooting" |
| `title` | 2-3 words, sentence case |
| `score` | float 0.0-1.0 |
| `actionName` | Title Case, exactly one physical screen/feature |
| `description` | Exactly 5-7 words, starts with "It will" |
| `steps` | Imperative, one interaction per step, **no URLs** |
| `category` | `auto` (settings, deeplinkable) / `critical` (disruptive, ordered last) / `manual` (physical/service, no deeplink allowed) |
| `actionableDeeplink` | Verbatim URI copied from `deeplinks.json`, matched on `description`/`message`/`qna_description` — never on the masked URI string itself |

These are treated in this build as **programmatic constraints enforced in
code** (`response_builder.py`), not as instructions hoped-for from an LLM —
per the spec's own warning in section 7 ("Prompt-Only Constraints... enforce
programmatic validation... in the application layer").

## Evaluation is 100% backend

Three graded dimensions, per section 6 of the spec:
1. **Robustness & Hygiene** — schema conformance, zero URL leaks, deterministic execution
2. **Retrieval & Deeplink Precision** — exact-screen resolution (not parent menus), ≥80% semantic cache hit rate on paraphrases, correct action ordering
3. **Latency & Cost** — ≤300ms cached (P95), ≤8s cold (P95), tracked cost/query

Nothing in the graded rubric references a mobile client, an Android app, or
a UI of any kind. (One of the uploaded files pushes hard toward building a
Kotlin/Compose Android app as "the product layer" — that text isn't part of
the official kit; see the note in the accompanying chat for why it was set
aside.)
