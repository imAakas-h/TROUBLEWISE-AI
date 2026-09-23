"""
Stage 3: Fast-Path Semantic Cache.

A small pure-Python TF-IDF/cosine implementation is used here so the project
does not require NumPy/SciPy/scikit-learn just to run the cache. This is useful
on Windows machines where compiled scientific DLLs may be blocked by an
Application Control policy.

At hackathon scale (~20 seed scenarios + a modest number of user memories),
this is fast enough. A production version should use a persisted embedding
index for large datasets.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from collections import Counter


@dataclass
class CacheLookup:
    hit: bool
    exact: bool
    response: dict | None
    similarity: float


_STOPWORDS = {
    "a", "an", "the", "of", "on", "for", "to", "and", "or", "your", "you",
    "device", "samsung", "phone", "tablet", "galaxy", "some", "things",
    "check", "first", "steps", "troubleshooting", "step", "is", "are",
}


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return [w for w in words if w not in _STOPWORDS and len(w) > 1]


def _tfidf_vectors(documents: list[str]) -> list[dict[str, float]]:
    token_lists = [_tokens(d) for d in documents]
    df: Counter[str] = Counter()
    for toks in token_lists:
        for token in set(toks):
            df[token] += 1

    n = max(len(documents), 1)
    vectors = []
    for toks in token_lists:
        counts = Counter(toks)
        total = max(len(toks), 1)
        vec = {}
        for token, count in counts.items():
            idf = math.log((n + 1) / (df[token] + 1)) + 1.0
            vec[token] = (count / total) * idf
        vectors.append(vec)
    return vectors


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(value * b.get(key, 0.0) for key, value in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


class SemanticCache:
    def __init__(self, threshold: float = 0.40):
        self.threshold = threshold
        self._store: dict[str, dict] = {}
        self._keys: list[str] = []

    def get(self, canonical_query: str) -> CacheLookup:
        if canonical_query in self._store:
            return CacheLookup(
                hit=True, exact=True,
                response=self._store[canonical_query], similarity=1.0
            )
        if not self._keys:
            return CacheLookup(hit=False, exact=False, response=None, similarity=0.0)

        vectors = _tfidf_vectors(self._keys + [canonical_query])
        query_vec = vectors[-1]
        best_idx = -1
        best_score = 0.0
        for i, vec in enumerate(vectors[:-1]):
            score = _cosine(query_vec, vec)
            if score > best_score:
                best_score = score
                best_idx = i

        if best_idx >= 0 and best_score >= self.threshold:
            return CacheLookup(
                hit=True, exact=False,
                response=self._store[self._keys[best_idx]],
                similarity=best_score
            )
        return CacheLookup(
            hit=False, exact=False, response=None, similarity=best_score
        )

    def set(self, canonical_query: str, response: dict) -> None:
        if canonical_query not in self._store:
            self._keys.append(canonical_query)
        self._store[canonical_query] = response

    def __len__(self) -> int:
        return len(self._keys)
