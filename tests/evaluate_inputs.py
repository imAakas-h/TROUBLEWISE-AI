"""Run every supplied complaint through a fresh retrieval-backed engine."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.grounding import validate_grounding
from app.pipeline import TroubleshootingEngine
from app.schema import ContextDeeplinkResponse

def main():
    data = ROOT / "data"
    deeplinks = json.loads((data / "deeplinks.json").read_text(encoding="utf-8"))["deeplinks"]
    siis = json.loads((data / "siis_responses.json").read_text(encoding="utf-8"))["responses"]
    queries = [line.strip().lstrip("0123456789. )").strip().strip('"') for line in (data / "input.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
    engine = TroubleshootingEngine(deeplinks, siis)
    rows = []
    for query in queries:
        result = engine.run(query)
        response = result["response"]
        sources = result["meta"].get("diagnostics", {}).get("retrieval", result["meta"].get("retrieved_sources", []))
        source_id = result["meta"].get("diagnostics", {}).get("source_id")
        source = next((item for item in siis if item.get("id") == source_id), None)
        try:
            parsed = ContextDeeplinkResponse.model_validate(response)
            if source:
                validate_grounding(response, source["siis_response"]["content"], deeplinks)
            actions = [action for goal in parsed.contexts for action in goal.actions]
            matches = [g.actionableDeeplink.deeplink for a in actions for g in a.stepGroups if g.actionableDeeplink]
            valid = all(uri in {x["deeplink"] for x in deeplinks} for uri in matches)
            passed = valid and (source is not None or not parsed.contexts)
            goal_text = parsed.contexts[0].goal if parsed.contexts else "(no_match)"
            action_text = "; ".join(a.actionName for a in actions) or "(none)"
            validation = "schema valid; source excerpts verified" if source else "schema valid; no-match fallback"
            reason = "grounded retrieved source" if source else result["meta"].get("fallback", "no reliable source")
            rows.append({"query": query, "source": source_id or "none", "title": source["siis_response"]["title"] if source else "none",
                         "goal": goal_text, "actions": action_text, "deeplinks": matches or ["(none)"],
                         "validation": validation, "status": "PASS" if passed else "FAIL", "reason": reason,
                         "latency": result["meta"]["latency_ms"], "candidate_sources": sources})
        except Exception as exc:
            rows.append({"query": query, "source": source_id or "none", "title": "unknown", "goal": "(rejected)",
                         "actions": "(none)", "deeplinks": [], "validation": f"FAILED: {exc}",
                         "status": "FAIL", "reason": "schema/grounding validation failed", "latency": result["meta"]["latency_ms"],
                         "candidate_sources": sources})
    lines = ["# Supplied Input Evaluation", "", f"Queries: {len(rows)} | Passed: {sum(x['status']=='PASS' for x in rows)} | Failed: {sum(x['status']=='FAIL' for x in rows)}", "",
             "Each record shows the top retrieved source, generated result, deeplink URIs, grounding/schema validation, and cold-path latency. A no-match is a passing safe fallback.", ""]
    for i, row in enumerate(rows, 1):
        candidates = ", ".join(f"{c['source_id']} ({c['score']:.3f})" for c in row["candidate_sources"]) or "none"
        lines.extend([f"## {i}. {row['query']}", "", f"- Retrieved source: {row['source']} — {row['title']} (candidates: {candidates})",
                      f"- Goal: {row['goal']}", f"- Actions: {row['actions']}", f"- Deeplinks: {', '.join(row['deeplinks'])}",
                      f"- Validation: {row['validation']}", f"- Result: **{row['status']}** — {row['reason']}",
                      f"- Cold-path latency: {row['latency']:.2f} ms", ""])
    (ROOT / "docs/input-evaluation.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"queries={len(rows)} pass={sum(x['status']=='PASS' for x in rows)} fail={sum(x['status']=='FAIL' for x in rows)}")
    for i, row in enumerate(rows, 1):
        print(f"{i:02d} {row['status']} {row['source']} {row['title']} | {row['actions']} | {row['reason']}")


if __name__ == "__main__":
    main()
