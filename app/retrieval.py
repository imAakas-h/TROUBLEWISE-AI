"""Lightweight hybrid retrieval over the supplied SIIS responses."""
from __future__ import annotations

import re
import math
from difflib import get_close_matches
from dataclasses import dataclass
from collections import Counter

from rank_bm25 import BM25Okapi

from app.query_enrichment import canonicalize

TOKEN_RE = re.compile(r"[a-z0-9]+")
SYNONYMS = {
    "display": "screen", "screens": "screen", "flashing": "flicker",
    "flashes": "flicker", "flickering": "flicker", "dark": "black",
    "blank": "black", "white": "black", "unresponsive": "notresponding", "laggy": "slow",
    "lagging": "slow", "freezes": "frozen", "cracked": "crack", "cracking": "crack",
    "charger": "charge", "charging": "charge",
}
STOP = {"the", "a", "an", "my", "is", "are", "it", "and", "or", "in", "on", "to", "of", "for", "with", "this", "that", "phone", "tablet", "samsung", "galaxy", "device", "use", "using", "app", "apps", "other", "when", "whenever", "too", "completely", "turns", "turned", "happens", "happen", "appears", "text", "no"}
NAMED_APPS = ("gmail", "camera", "smart switch", "smart tutor", "whatsapp", "youtube", "bixby")


def tokens(text: str) -> list[str]:
    return [SYNONYMS.get(t, t) for t in TOKEN_RE.findall(canonicalize(text)) if t not in STOP and len(t) > 1]


@dataclass(frozen=True)
class RetrievalResult:
    entry: dict
    score: float
    lexical_overlap: float


class SiisRetriever:
    """BM25 with normalized-token overlap and device/product entity overlap."""

    def __init__(self, entries: list[dict]):
        self.entries = entries
        self.texts = []
        self.topic_texts = []
        self.corpus_tokens = []
        self.topic_tokens = []
        for entry in entries:
            siis = entry.get("siis_response", {})
            content = siis.get("content", "")
            headings = " ".join(re.findall(r"^#{1,4}\s*(.+)$", content, re.M))
            # Explicitly weight user phrasing, KB title, and procedural
            # headings. Long article bodies are retained for extraction but
            # excluded here so generic boilerplate cannot swamp the intent.
            topic = " ".join((siis.get("title", ""), siis.get("title", ""), headings))
            self.topic_texts.append(topic.casefold())
            text = " ".join((entry.get("original_query", ""), topic))
            self.texts.append(text)
            self.corpus_tokens.append(set(tokens(text)))
            self.topic_tokens.append(set(tokens(topic)))
        corpus = [list(topic) or ["_empty_"] for topic in self.topic_tokens]
        self.bm25 = BM25Okapi(corpus) if corpus else None
        df = Counter(token for row in self.topic_tokens for token in row)
        self.idf = {token: math.log((len(entries) + 1) / (count + 1)) + 1.0 for token, count in df.items()}
        self.vocabulary = set(self.idf)

    def search(self, query: str, limit: int = 4, min_score: float = 0.10) -> list[RetrievalResult]:
        query_tokens = set(tokens(query))
        if not query_tokens or self.bm25 is None:
            return []
        query_tokens = {token if token in self.vocabulary else
                        (get_close_matches(token, self.vocabulary, n=1, cutoff=0.86) or [token])[0]
                        if len(token) >= 4 else token for token in query_tokens}
        raw = self.bm25.get_scores(list(query_tokens))
        max_bm25 = max(max(raw, default=0.0), 1e-9)
        scored = []
        for i, entry in enumerate(self.entries):
            shared = query_tokens & self.corpus_tokens[i]
            topic_shared = query_tokens & self.topic_tokens[i]
            covered_query = query_tokens & self.vocabulary
            query_weight = sum(self.idf.get(t, 1.0) for t in covered_query)
            overlap = sum(self.idf.get(t, 1.0) for t in topic_shared) / max(query_weight, 1e-9)
            doc_weight = sum(self.idf.get(t, 1.0) for t in self.topic_tokens[i])
            jaccard = sum(self.idf.get(t, 1.0) for t in topic_shared) / max(query_weight + doc_weight - sum(self.idf.get(t, 1.0) for t in topic_shared), 1e-9)
            bm25 = max(0.0, float(raw[i])) / max_bm25
            # Use canonical user examples only as a small bridge signal; a
            # contradictory article title must not win on query wording alone.
            bridge = len(shared) / max(len(covered_query), 1)
            score = 0.55 * overlap + 0.25 * jaccard + 0.12 * bm25 + 0.08 * bridge
            query_text = query.lower()
            topic_text = self.topic_texts[i]
            app_is_trigger = re.search(r"\b(when(?:ever)?|only|only when|while)\b.{0,120}\b(" + "|".join(re.escape(a) for a in NAMED_APPS) + r")\b", query_text)
            display_symptoms = {"black", "flicker", "damage", "crack", "distorted", "white", "blank"}
            query_symptoms = query_tokens & display_symptoms
            if query_symptoms:
                symptom_coverage = len(query_symptoms & self.topic_tokens[i]) / len(query_symptoms)
                score = (0.35 * score + 0.65 * symptom_coverage) if symptom_coverage else 0.20 * score
            broad_app_scope = re.search(
                r"\b(other apps?|all apps?|multiple apps?|across apps?|apps? too)\b",
                query_text,
            )
            if app_is_trigger and not broad_app_scope and app_is_trigger.group(2) not in topic_text:
                score *= 0.20
            if re.search(r"\b(activation|activated|deactivated|carrier)\b", query_text) and not re.search(r"\b(activation|activated|deactivated|carrier)\b", topic_text):
                score = 0.0
            if re.search(r"\b(fold|foldable|flip|fold 7|fold 6)\b", query_text) and "camera" in topic_text:
                score *= 0.55
            if re.search(r"\b(inner|outer|cover) screen\b", query_text) and not re.search(r"\b(inner|outer|cover|fold|flip)\b", topic_text):
                score *= 0.25
            if re.search(r"\b(floating|hovering|floating circle|accessibility menu)\b", query_text) and not re.search(r"\b(accessibility|floating|assistant menu)\b", topic_text):
                score *= 0.20
            if re.search(r"\b(small|full size|fill the whole|expand to full)\b", query_text) and not re.search(r"\b(screen size|display size|zoom|full size)\b", topic_text):
                score *= 0.25
            if query_symptoms & {"crack", "damage"} and not (query_symptoms & self.topic_tokens[i] or "crack" in self.topic_tokens[i]):
                score *= 0.20
            if re.search(r"\b(charger|charging|plug in|plugging in)\b", query_text) and not re.search(r"\b(charge|charger|charging|power)\b", topic_text):
                score *= 0.25
            if re.search(r"\b(tiny text|boot screen|startup screen|bootloader|recovery screen)\b", query_text) and not re.search(r"\b(tiny text|boot|startup|bootloader|recovery)\b", topic_text):
                score = 0.0
            transfer_with_display_failure = (re.search(r"\b(transfer|smart switch|backup|back up)\b", query_text)
                and re.search(r"\b(cannot|can't|unable|can't see|no image|stopped working|black|blank|dark)\b", query_text))
            access_data_topic = ("access" in self.topic_tokens[i] and "data" in self.topic_tokens[i]
                                 and "screen" in self.topic_tokens[i])
            if transfer_with_display_failure and access_data_topic:
                score *= 1.8
            minimum_topic_terms = 2 if len(covered_query) >= 3 else 1
            if score >= min_score and len(topic_shared) >= minimum_topic_terms:
                scored.append(RetrievalResult(entry, float(score), float(overlap)))
        # Several SIIS rows can be alternate customer phrasings for the same
        # article. They are one source, not competing diagnostic branches.
        # Deduplicate on the actual knowledge text so replicas do not trigger
        # adaptive probing or crowd distinct evidence out of the result set.
        ranked = sorted(scored, key=lambda r: r.score, reverse=True)
        unique = []
        seen = set()
        for result in ranked:
            siis = result.entry.get("siis_response", {})
            fingerprint = (
                re.sub(r"\s+", " ", siis.get("title", "")).strip().casefold(),
                re.sub(r"\s+", " ", siis.get("content", "")).strip().casefold(),
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            unique.append(result)
            if len(unique) >= limit:
                break
        return unique
