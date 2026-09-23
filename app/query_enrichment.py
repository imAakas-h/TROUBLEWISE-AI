"""
Stage 0: Query Enrichment.

Normalizes a raw, colloquial complaint into a canonical technical query used as
the semantic-cache key, and produces a handful of paraphrase variations so the
cache can be exercised/tested for paraphrase robustness.

No LLM call is made here (no model credentials are available in this
environment) -- normalization is done with deterministic text rules. This is
the one stage of the pipeline where swapping in an LLM call would most
directly improve quality (better canonicalization, richer paraphrases); the
hook is isolated in `enrich_query` so that swap is a single-function change.
See implementation-plan.md, "Where an LLM is actually useful".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Device-model tokens we normalize away from the canonical key so that
# "Galaxy S22" and "Galaxy S24 Ultra" complaints about the same symptom land
# in the same semantic-cache bucket. The raw device mention is preserved
# separately (device_context) for any downstream logic that wants it.
DEVICE_PATTERN = re.compile(
    r"\b(galaxy\s+)?(z\s*fold\s*\d+|z\s*flip\s*\d+|note\s*\d+|"
    r"[sazm]\d{2,3}[a-z]{0,3}(\s*(ultra|plus|fe))?|tab\s*[sa]\d*)\b",
    re.IGNORECASE,
)

FILLER_PATTERN = re.compile(
    r"\b(my|the|i|i'm|im|so|and|please|just|also|really|very|kinda|literally)\b",
    re.IGNORECASE,
)

WHITESPACE = re.compile(r"\s+")


@dataclass
class EnrichedQuery:
    raw: str
    canonical: str
    device_context: str | None
    variations: list[str] = field(default_factory=list)


def _strip_device(text: str) -> tuple[str, str | None]:
    match = DEVICE_PATTERN.search(text)
    device = match.group(0).strip() if match else None
    cleaned = DEVICE_PATTERN.sub("the device", text)
    return cleaned, device


_CONTRACTIONS = [
    (r"\bwon't\b", "will not"),
    (r"\bcan't\b", "cannot"),
    (r"\bdoesn't\b", "does not"),
    (r"\bdon't\b", "do not"),
    (r"\bisn't\b", "is not"),
    (r"\bwasn't\b", "was not"),
    (r"\bi'm\b", "i am"),
]

# Canonical-form synonym normalization -- applied to BOTH stored cache keys
# and incoming lookups so that "dark screen" and "blank screen" land in the
# same semantic-cache bucket even though a pure TF-IDF cosine over such
# short strings gives them fairly low similarity on their own (measured:
# ~0.2-0.3, well under a safe acceptance threshold). This is a partial,
# honest workaround for not having a real embedding model available in this
# sandbox -- see cache.py docstring for the production upgrade path.
_CANONICAL_SYNONYMS = [
    (r"\bdark\b", "black"),
    (r"\bblank\b", "black"),
    (r"\bunresponsive\b", "not responding"),
    (r"\bnot responsive\b", "not responding"),
    (r"\btotally\b", "completely"),
    (r"\bcompletely dark\b", "completely black"),
    (r"\bwont turn on\b", "not turning on"),
    (r"\bdoes not turn on\b", "not turning on"),
    (r"\bwill not turn on\b", "not turning on"),
    (r"\bfroze\b", "frozen"),
    (r"\bfreezing\b", "frozen"),
    (r"\bstuck\b", "frozen"),
]


def canonicalize(text: str) -> str:
    """Collapse a raw complaint to a short, symptom-centric technical query."""
    text = text.strip()
    # Drop leading list markers like "1." or "2)" that appear in input.txt
    text = re.sub(r"^\s*\d+[\.\)]\s*", "", text)
    text = text.replace('"', "").strip()
    cleaned, _device = _strip_device(text)
    cleaned = cleaned.lower()
    for pat, repl in _CONTRACTIONS:
        cleaned = re.sub(pat, repl, cleaned)
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
    cleaned = FILLER_PATTERN.sub(" ", cleaned)
    cleaned = WHITESPACE.sub(" ", cleaned).strip()
    for pat, repl in _CANONICAL_SYNONYMS:
        cleaned = re.sub(pat, repl, cleaned)
    cleaned = WHITESPACE.sub(" ", cleaned).strip()
    return cleaned


_SYNONYM_SWAPS = [
    (r"\bscreen\b", "display"),
    (r"\bblank\b", "black"),
    (r"\bwon't\b", "will not"),
    (r"\bturn on\b", "power on"),
    (r"\bstopped working\b", "is not working"),
    (r"\bkeeps\b", "continues to"),
]


def _template_variations(canonical: str, n: int = 6) -> list[str]:
    """Cheap, deterministic paraphrase generator (word-order / synonym swaps).

    This is a stand-in for an LLM-generated paraphrase set. It won't match the
    fluency of an LLM, but it exercises the same code path (semantic cache
    must hit on all of these) and is fully reproducible for grading/demo.
    """
    variations = set()
    words = canonical.split()

    # 1) synonym substitution
    v = canonical
    for pat, repl in _SYNONYM_SWAPS:
        v = re.sub(pat, repl, v)
    if v != canonical:
        variations.add(v)

    # 2) "issue with X" / "having trouble with X" framings
    variations.add(f"issue with {canonical}")
    variations.add(f"having trouble with {canonical}")
    variations.add(f"problem {canonical}")

    # 3) question form
    variations.add(f"why does {canonical}")

    # 4) keyword-only (drop short function words)
    keywords = [w for w in words if len(w) > 3]
    if keywords:
        variations.add(" ".join(keywords))

    # 5) truncated / typo-ish (drop last word) -- crude but deterministic
    if len(words) > 3:
        variations.add(" ".join(words[:-1]))

    variations.discard(canonical)
    return list(variations)[:n]


def enrich_query(raw_text: str) -> EnrichedQuery:
    canonical = canonicalize(raw_text)
    _, device = _strip_device(raw_text)

    # Optional AI-agent upgrade: if GROQ_API_KEY is set, ask Groq for richer
    # paraphrases than the template swaps below can produce. Falls back to
    # the deterministic template on any failure (see llm_enhancer.py) --
    # this call can never break query enrichment, only enrich it further.
    from app import llm_enhancer
    if llm_enhancer.is_available():
        llm_variations = llm_enhancer.generate_paraphrases(canonical)
        if llm_variations:
            return EnrichedQuery(
                raw=raw_text, canonical=canonical, device_context=device,
                variations=llm_variations,
            )

    variations = _template_variations(canonical)
    return EnrichedQuery(
        raw=raw_text, canonical=canonical, device_context=device, variations=variations
    )
