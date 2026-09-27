"""Match actions to catalog metadata; emit only exact, non-placeholder URIs."""
from __future__ import annotations

import re
import math
from collections import Counter
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

TOKEN_RE = re.compile(r"[a-z0-9]+")

# Generic phone/UI vocabulary that appears across huge swaths of the catalog
# and in almost every troubleshooting sentence -- excluded from tokenization
# so it can't manufacture false-positive overlap.
GENERIC_STOPWORDS = {
    "a", "an", "the", "of", "on", "for", "to", "and", "or", "your", "you",
    "device", "phone", "tablet", "samsung", "galaxy", "screen", "button",
    "settings", "setting", "please", "will", "it", "is", "are", "this",
    "that", "with", "in", "at", "if", "then", "try", "check", "open",
    "tap", "select", "go", "step", "steps", "let", "lets", "app", "apps",
    "up", "down", "off", "again", "here", "there", "be", "can", "may",
    "need", "want", "make", "get", "hold", "press", "use", "using", "not",
    # generic troubleshooting narrative filler -- shows up regardless of the
    # specific feature/screen involved, so a shared hit on one of these
    # alone must never be treated as evidence of a real topical match
    # (empirically caused "clear cache" to false-match a "temporary mute"
    # deeplink purely via the word "temporary")
    "temporary", "temporarily", "glitch", "glitches", "resolve", "issue",
    "issues", "problem", "problems", "fix", "fixed", "clear", "clearing",
    "data", "quick", "easy", "simple", "help", "helps", "might", "should",
    "could", "would", "also", "some", "many", "most", "often", "sometimes",
    "usually", "typically", "one", "two", "first", "second", "third",
    "next", "before", "after", "new", "old", "way", "ways",
}


def _tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower())
            if len(t) > 1 and t not in GENERIC_STOPWORDS]


@dataclass
class MatchResult:
    entry: dict | None
    score: float
    used_fallback: bool


class DeeplinkMatcher:
    def __init__(self, deeplinks: list[dict], accept_threshold: float = 0.30,
                 fallback_threshold: float = 0.10, min_shared_tokens: int = 1):
        # The source kit contains a deliberately named dummy placeholder.
        # It is not an actionable Settings target and must never be returned.
        self.entries = [entry for entry in deeplinks
                        if entry.get("deeplink") != "bixby://dummy_positive"
                        and entry.get("originalType") != "placeholder"]
        self.accept_threshold = accept_threshold
        self.fallback_threshold = fallback_threshold
        self.min_shared_tokens = min_shared_tokens

        self._corpus_text = [self._entry_text(e) for e in deeplinks]
        self._corpus_tokens = [set(_tokenize(t)) for t in self._corpus_text]
        self._bm25 = BM25Okapi([_tokenize(t) for t in self._corpus_text])
        tokenized = [_tokenize(t) for t in self._corpus_text]
        df = Counter(token for row in tokenized for token in set(row))
        n_docs = max(len(tokenized), 1)
        self._idf = {token: math.log((n_docs + 1) / (count + 1)) + 1 for token, count in df.items()}
        self._tfidf_matrix = [self._vector(row) for row in tokenized]

    def _vector(self, words: list[str]) -> dict[str, float]:
        counts = Counter(words)
        total = max(len(words), 1)
        return {word: (count / total) * self._idf.get(word, 1.0) for word, count in counts.items()}

    @staticmethod
    def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
        if not left or not right:
            return 0.0
        dot = sum(value * right.get(key, 0.0) for key, value in left.items())
        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))
        return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0

    @staticmethod
    def _entry_text(entry: dict) -> str:
        return " ".join(filter(None, [
            entry.get("description", ""),
            entry.get("message", ""),
            entry.get("qna_description", ""),
        ]))

    def match(self, query_text: str) -> MatchResult:
        query_tokens = set(_tokenize(query_text))
        if not query_tokens:
            return MatchResult(entry=None, score=0.0, used_fallback=False)

        bm25_scores = self._bm25.get_scores(list(query_tokens)).tolist()
        bm25_max = max(max(bm25_scores, default=0.0), 1e-9)

        q_vec = self._vector(_tokenize(query_text))
        cos_scores = [self._cosine(q_vec, doc) for doc in self._tfidf_matrix]

        # Cosine (TF-IDF) naturally down-weights common terms via IDF, which
        # empirically tracks true topical relevance better than raw BM25 on
        # this catalog's short metadata strings -- BM25 alone let three
        # generic-ish shared words ("menu", "security", "biometrics") outrank
        # one highly specific one ("fingerprint"). Cosine is weighted higher
        # accordingly; BM25 is kept as a secondary signal for exact rare-term
        # overlap it sometimes catches that TF-IDF misses.
        combined = [0.35 * (score / bm25_max) + 0.65 * cosine
                    for score, cosine in zip(bm25_scores, cos_scores)]

        # Rank candidates best-first, but skip any that fail the lexical
        # overlap gate -- a good combined score built entirely on generic
        # words is not a real match.
        order = sorted(range(len(combined)), key=lambda idx: combined[idx], reverse=True)
        for idx in order[:10]:
            score = float(combined[idx])
            if score < self.fallback_threshold:
                break
            shared = query_tokens & self._corpus_tokens[idx]
            if len(shared) < self.min_shared_tokens:
                continue
            if score >= self.accept_threshold:
                return MatchResult(entry=self.entries[idx], score=score, used_fallback=False)
            return MatchResult(entry=None, score=score, used_fallback=True)

        return MatchResult(entry=None, score=0.0, used_fallback=False)
