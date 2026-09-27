"""Explainable selection of a safe, source-backed first diagnostic action."""
from __future__ import annotations

import re

SAFE_CUES = re.compile(r"\b(check|verify|confirm|inspect|try|test|see if|determine|observe)\b", re.I)
RISK_CUES = re.compile(r"\b(factory reset|erase|delete|remove account|clear data|reset all|repair|replace)\b", re.I)


def choose_probe(extracted, retrieval_results, query: str = ""):
    """Select a verbatim low-risk observation when sources indicate ambiguity.

    No probe question or instruction is generated. Candidates must already
    exist as extracted SIIS steps. Return None when evidence is not ambiguous.
    """
    if not retrieval_results:
        return None
    # A short, underspecified complaint can be ambiguous even when only one
    # article clears retrieval. In that case lead with its safest observation.
    vague_single_source = len(retrieval_results) == 1 and len(re.findall(r"[a-z0-9]+", query.lower())) <= 7
    if len(retrieval_results) > 1 and retrieval_results[0].score - retrieval_results[1].score > 0.14:
        return None
    if len(retrieval_results) == 1 and not vague_single_source:
        return None
    candidates = []
    for i, action in enumerate(extracted.actions):
        steps = [step for group in action.step_groups for step in group.steps]
        probe_step = next((step for step in sorted(steps, key=len) if SAFE_CUES.search(step) and not RISK_CUES.search(step)), None)
        text = probe_step or ""
        if text and action.category != "critical":
            specificity = len(set(re.findall(r"[a-z]{4,}", text.lower())))
            signal_terms = set(re.findall(r"[a-z]{4,}", (action.action_name + " " + text).lower()))
            source_hits = 0
            for result in retrieval_results:
                source_text = " ".join((result.entry.get("original_query", ""),
                                        result.entry.get("siis_response", {}).get("title", ""),
                                        result.entry.get("siis_response", {}).get("content", "")[:1000])).lower()
                source_hits += bool(signal_terms & set(re.findall(r"[a-z]{4,}", source_text)))
            prevalence = source_hits / len(retrieval_results)
            # An observation has at least two possible outcomes (present or
            # absent); branch balance across sources adds to that simple
            # explainable score. This is a ranking heuristic, not a diagnosis.
            information_gain = (0.5 if len(retrieval_results) == 1 else
                                max(0.5, 1.0 - abs(0.5 - prevalence) * 2.0))
            candidates.append((information_gain, -len(text), specificity, -i, i, action, prevalence, text))
    if not candidates:
        return None
    gain, _, _, _, index, action, prevalence, text = max(candidates)
    # Hypotheses are retrieved SIIS scenarios, not invented diagnoses.
    hypotheses = [{"hypothesis": r.entry.get("siis_response", {}).get("title", r.entry.get("id")),
                   "supporting_signals": sorted(set(re.findall(r"[a-z]{4,}",
                       (r.entry.get("original_query", "") + " " + r.entry.get("siis_response", {}).get("title", "")).lower())) &
                       set(re.findall(r"[a-z]{4,}", text.lower()))),
                   "missing_signal": "outcome of this source-backed check",
                   "candidate_probe": action.action_name,
                   "expected_information_gain": round(gain, 3)} for r in retrieval_results]
    return {"selected": True, "index": index, "action": action.action_name, "probe_text": text,
            "expected_information_gain": round(gain, 3), "source_support": round(prevalence, 3),
            "hypotheses": hypotheses}
