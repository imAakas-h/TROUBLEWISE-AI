"""
Stage 2: Galaxy Deeplink Retrieval.

Matches an extracted action to an entry in the masked deeplink catalog,
using ONLY the catalog's descriptive metadata fields (`description`,
`message`, `qna_description`) -- never the opaque masked URI itself.

Retrieval is hybrid:
  1. BM25 lexical scoring over the same metadata corpus.
  2. TF-IDF cosine similarity as a softer semantic-ish signal (no
     internet-hosted embedding model is reachable from this sandbox --
     huggingface.co is not on the network allowlist -- so this is the
     stand-in; swap in a real sentence-embedding model in production without
     changing the `DeeplinkMatcher.match` interface).
  3. Scores are combined and reranked.
  4. A hard lexical-overlap gate rejects a "match" that only scored well
     because of generic phone vocabulary ("device", "button", "settings")
     shared with dozens of unrelated catalog entries -- the query and the
     winning entry must share at least one *specific* (non-generic) token.
  5. Below the fallback threshold, no deeplink is returned at all rather
     than guessing.

The query text passed in should be the action's short name plus (at most)
its first step -- NOT the full paragraph of steps. Long text pulls in noisy
shared vocabulary and produces false positives (verified empirically: this
caused "Force a restart" to match a "Pen button" toggle in early testing).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

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
        self.entries = deeplinks
        self.accept_threshold = accept_threshold
        self.fallback_threshold = fallback_threshold
        self.min_shared_tokens = min_shared_tokens

        self._corpus_text = [self._entry_text(e) for e in deeplinks]
        self._corpus_tokens = [set(_tokenize(t)) for t in self._corpus_text]
        self._bm25 = BM25Okapi([_tokenize(t) for t in self._corpus_text])
        self._tfidf = TfidfVectorizer(stop_words=list(GENERIC_STOPWORDS))
        self._tfidf_matrix = self._tfidf.fit_transform(self._corpus_text)

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

        bm25_scores = self._bm25.get_scores(list(query_tokens))
        bm25_max = max(bm25_scores.max(), 1e-9)
        bm25_norm = bm25_scores / bm25_max

        q_vec = self._tfidf.transform([query_text])
        cos_scores = cosine_similarity(q_vec, self._tfidf_matrix).flatten()

        # Cosine (TF-IDF) naturally down-weights common terms via IDF, which
        # empirically tracks true topical relevance better than raw BM25 on
        # this catalog's short metadata strings -- BM25 alone let three
        # generic-ish shared words ("menu", "security", "biometrics") outrank
        # one highly specific one ("fingerprint"). Cosine is weighted higher
        # accordingly; BM25 is kept as a secondary signal for exact rare-term
        # overlap it sometimes catches that TF-IDF misses.
        combined = 0.35 * bm25_norm + 0.65 * cos_scores

        # Rank candidates best-first, but skip any that fail the lexical
        # overlap gate -- a good combined score built entirely on generic
        # words is not a real match.
        order = combined.argsort()[::-1]
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
