import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

MEMORY_FILE = Path(__file__).resolve().parent.parent / "data" / "experience_memory.json"
MAX_RECORDS = 500


def _load():
    if not MEMORY_FILE.exists():
        return []

    try:
        with MEMORY_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save(records):
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    with MEMORY_FILE.open("w", encoding="utf-8") as f:
        json.dump(records[-MAX_RECORDS:], f, indent=2, ensure_ascii=False)


def _tokens(text):
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _similarity(a, b):
    tokens_a = _tokens(a)
    tokens_b = _tokens(b)

    if not tokens_a or not tokens_b:
        return 0.0

    jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
    sequence = SequenceMatcher(
        None,
        (a or "").lower(),
        (b or "").lower()
    ).ratio()

    return (jaccard * 0.7) + (sequence * 0.3)


def record_experience(query, outcome, action_name="", note=""):
    records = _load()

    records.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "outcome": outcome,
        "action_name": action_name,
        "note": note,
    })

    _save(records)


def find_relevant_experiences(query, limit=3):
    records = _load()

    scored = []

    for record in records:
        score = _similarity(query, record.get("query", ""))

        if score > 0.15:
            item = dict(record)
            item["similarity"] = round(score, 3)
            scored.append(item)

    scored.sort(
        key=lambda item: item.get("similarity", 0),
        reverse=True
    )

    return scored[:limit]


def count():
    return len(_load())