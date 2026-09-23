"""
Offline benchmark harness -- mirrors the graded dimensions in the spec's
metrics.md template as closely as we can measure without the real evaluator:

  1. Schema & rule compliance  (Pydantic validation, word-count rules, zero URL leaks)
  2. Deeplink catalog integrity (every returned deeplink is a verbatim catalog URI)
  3. Latency (P50/P95 for cache hits vs cold path)
  4. Cache behavior (exact hits on the 20 seed queries, semantic hits on paraphrases)
  5. Unseen-scenario handling (a SIIS-style payload not in the 20 seed scenarios)

Run: python -m tests.run_benchmark
"""
from __future__ import annotations

import json
import re
import statistics
import time
from pathlib import Path

from app.pipeline import TroubleshootingEngine
from app.schema import ContextDeeplinkResponse

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
URL_RE = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)


def load_data():
    deeplinks = json.loads((DATA_DIR / "deeplinks.json").read_text())["deeplinks"]
    siis = json.loads((DATA_DIR / "siis_responses.json").read_text())["responses"]
    return deeplinks, siis


def check_response(resp: dict, valid_uris: set[str]) -> list[str]:
    """Returns a list of rule violations (empty = fully compliant)."""
    violations = []
    try:
        parsed = ContextDeeplinkResponse.model_validate(resp)
    except Exception as e:
        return [f"SCHEMA_INVALID: {e}"]

    for goal in parsed.contexts:
        if not goal.goal.startswith("Follow these steps to perform this"):
            violations.append(f"GOAL_SYNTAX: {goal.goal!r}")
        title_words = goal.title.split()
        if not (2 <= len(title_words) <= 3):
            violations.append(f"TITLE_LENGTH({len(title_words)}): {goal.title!r}")
        if not (0.0 <= goal.score <= 1.0):
            violations.append(f"SCORE_RANGE: {goal.score}")

        for action in goal.actions:
            desc_words = action.description.split()
            if not (5 <= len(desc_words) <= 7):
                violations.append(f"DESC_LENGTH({len(desc_words)}): {action.description!r}")
            if not action.description.startswith("It will"):
                violations.append(f"DESC_PREFIX: {action.description!r}")
            if action.category.value == "manual":
                for sg in action.stepGroups:
                    if sg.actionableDeeplink is not None:
                        violations.append(f"MANUAL_HAS_DEEPLINK: {action.actionName}")
            for sg in action.stepGroups:
                for s in sg.steps:
                    if URL_RE.search(s):
                        violations.append(f"URL_LEAK: {s[:60]}")
                if sg.actionableDeeplink is not None:
                    uri = sg.actionableDeeplink.deeplink
                    if uri != "bixby://dummy_positive" and uri not in valid_uris:
                        violations.append(f"UNKNOWN_URI: {uri}")
    return violations


def main():
    deeplinks, siis = load_data()
    valid_uris = {d["deeplink"] for d in deeplinks} | {"bixby://dummy_positive"}

    engine = TroubleshootingEngine(deeplinks)
    engine.prewarm(siis)

    print(f"Prewarmed cache with {len(engine.cache)} seed scenarios.\n")

    all_violations = 0
    total_actions_auto = 0
    total_actions_auto_with_dl = 0
    latencies_cache_hit = []
    latencies_cold = []

    print("=== 1) Seed scenarios: exact cache hit, schema compliance ===")
    for entry in siis:
        query = entry["original_query"]
        result = engine.run(query=query)
        latencies_cache_hit.append(result["meta"]["latency_ms"])
        violations = check_response(result["response"], valid_uris)
        all_violations += len(violations)
        for ctx in result["response"]["contexts"]:
            for a in ctx["actions"]:
                if a["category"] == "auto":
                    total_actions_auto += 1
                    if a["stepGroups"][0]["actionableDeeplink"]:
                        total_actions_auto_with_dl += 1
        status = "OK" if not violations else f"{len(violations)} VIOLATIONS: {violations[:3]}"
        cache_hit = result["meta"]["cache_hit"]
        print(f"  {entry['id']:8s} cache_hit={cache_hit!s:5s} "
              f"latency={result['meta']['latency_ms']:6.2f}ms  {status}")

    print(f"\nTotal violations across 20 seed scenarios: {all_violations}")
    if total_actions_auto:
        pct = 100 * total_actions_auto_with_dl / total_actions_auto
        print(f"'auto' actions carrying a resolved deeplink: "
              f"{total_actions_auto_with_dl}/{total_actions_auto} ({pct:.0f}%)")

    print("\n=== 2) Paraphrase robustness (semantic cache hit expected) ===")
    paraphrase_tests = [
        ("row_17", "why is my samsung display totally dark and unresponsive"),
        ("row_19", "screen cracked at the fold on my flip phone"),
    ]
    sem_hits = 0
    by_id = {s["id"]: s for s in siis}
    for entry_id, paraphrase in paraphrase_tests:
        match = by_id[entry_id]
        engine.run(query=match["original_query"], siis_response=match["siis_response"]["content"],
                   siis_title=match["siis_response"]["title"])
        result = engine.run(query=paraphrase)
        hit = result["meta"]["cache_hit"]
        sem_hits += hit
        print(f"  paraphrase hit={hit}  sim={result['meta'].get('cache_similarity')}  "
              f"-> {paraphrase[:60]!r}")

    print("\n=== 3) Unseen scenario (not among the 20 seed SIIS entries) ===")
    unseen_query = "My Galaxy speaker sounds muffled and distorted during phone calls"
    unseen_siis = (
        "Muffled or distorted speaker sound on Samsung phone (Smartphone): "
        "## Troubleshooting Steps for Speaker Sound Quality\n"
        "### Step 1: Remove Case and Screen Protector Debris\n"
        "Please remove your phone case and check the speaker grille for dust, "
        "lint, or debris that may be blocking sound output. Clean gently with a "
        "soft dry brush.\n"
        "### Step 2: Adjust Media Volume and Sound Settings\n"
        "Navigate to and open Settings. Tap on Sounds and vibration. Tap on "
        "Volume and drag the media volume slider to a mid-range level, then "
        "test call audio again.\n"
        "### Step 3: Disable Bixby Voice Wake-Up Interference\n"
        "Navigate to and open Settings. Tap on Advanced features, then tap "
        "Bixby Key or Voice wake-up, and turn off Voice wake-up temporarily "
        "to rule out interference.\n"
        "### Step 4: Escalate to Service\n"
        "If distortion continues after these checks, please contact Samsung "
        "Support or visit an authorized Samsung Service Center, as the speaker "
        "hardware may need inspection."
    )
    result = engine.run(query=unseen_query, siis_response=unseen_siis)
    violations = check_response(result["response"], valid_uris)
    print(f"  cache_hit={result['meta']['cache_hit']} (must be False -- never seen before)")
    print(f"  violations: {violations or 'none'}")
    print(f"  actions extracted: {[a['actionName'] for a in result['response']['contexts'][0]['actions']]}")

    print("\n=== 4) No-context fallback (no siis_response, no cache hit) ===")
    result = engine.run(query="my phone smells like burning plastic")
    print(f"  contexts={result['response']['contexts']}  fallback={result['meta'].get('fallback')}")

    print("\n=== 5) Latency summary ===")
    if latencies_cache_hit:
        print(f"  cache-hit P50={statistics.median(latencies_cache_hit):.2f}ms  "
              f"P95={sorted(latencies_cache_hit)[int(0.95*len(latencies_cache_hit))-1]:.2f}ms  "
              f"max={max(latencies_cache_hit):.2f}ms")

    # cold path timing (force cache misses with fresh engine, no prewarm)
    cold_engine = TroubleshootingEngine(deeplinks)
    cold_times = []
    for entry in siis[:8]:
        t0 = time.perf_counter()
        cold_engine.run(query=entry["original_query"],
                         siis_response=entry["siis_response"]["content"],
                         siis_title=entry["siis_response"]["title"])
        cold_times.append((time.perf_counter() - t0) * 1000)
    print(f"  cold-path (no cache) P50={statistics.median(cold_times):.2f}ms  "
          f"max={max(cold_times):.2f}ms  (n={len(cold_times)})")


if __name__ == "__main__":
    main()
