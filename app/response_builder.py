"""
Turns an `ExtractedGoal` (extraction.py) + deeplink matches (deeplink_matcher.py)
into schema-valid `schema.Goal` / `schema.Action` objects, enforcing every
formatting rule from section 4.1 of the spec programmatically -- word counts
and prefixes are NOT left to the LLM/heuristic to get right on its own; they
are checked and corrected here (spec section 7, "Prompt-Only Constraints").
"""
from __future__ import annotations

import re

from app.schema import (
    Action, Deeplink, Goal, StepGroup, ValidationDeepLink, actionCategory,
)
from app.extraction import ExtractedGoal
from app.deeplink_matcher import DeeplinkMatcher, MatchResult

URL_RE = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)
FILLERS = ["for you", "safely", "quickly", "right now", "on your device"]


def _scrub_urls(text: str) -> str:
    return URL_RE.sub("[link removed]", text).strip()


def _sentence_case_topic(words: list[str]) -> str:
    words = words[:3] or ["device", "issue"]
    return " ".join([words[0].capitalize()] + [w.lower() for w in words[1:]])


def _title_case_topic(words: list[str]) -> str:
    words = words[:3] or ["Device", "Issue"]
    return " ".join(w.capitalize() for w in words)


def build_description(action_name: str) -> str:
    """Exactly 5-7 words, starting with 'It will'.

    Tries the optional Groq-based polish first (see llm_enhancer.py) for
    more natural phrasing; ALWAYS validated against the same 5-7-word /
    'It will' rule before use, and falls back to the deterministic template
    below if Groq is unavailable or returns something non-compliant. The
    schema constraint is enforced here regardless of which path produced
    the text -- an LLM is never trusted to have followed the instruction
    correctly on its own.
    """
    from app import llm_enhancer
    if llm_enhancer.is_available():
        polished = llm_enhancer.polish_description(action_name, category="auto")
        if polished:
            words = polished.split()
            if 5 <= len(words) <= 7 and polished.lower().startswith("it will"):
                return polished

    tail = re.sub(r"[^a-zA-Z\s]", "", action_name).lower().split()
    combined = ["It", "will", "help", "fix"] + tail
    if len(combined) > 7:
        combined = combined[:7]
    i = 0
    fillers_flat = " ".join(FILLERS).split()
    while len(combined) < 5 and i < len(fillers_flat):
        combined.append(fillers_flat[i])
        i += 1
    return " ".join(combined)


CATEGORY_MAP = {
    "auto": actionCategory.auto,
    "manual": actionCategory.manual,
    "critical": actionCategory.critical,
}


def build_goal(extracted: ExtractedGoal, matcher: DeeplinkMatcher) -> tuple[Goal, dict]:
    """Returns (validated Goal, diagnostics dict for logging/metrics)."""
    topic_words = extracted.topic.split()
    title = _sentence_case_topic(topic_words)
    goal_topic_title_case = _title_case_topic(topic_words)
    goal_str = f"Follow these steps to perform this {goal_topic_title_case} Troubleshooting"

    actions: list[Action] = []
    diagnostics = {"actions": []}

    for ea in extracted.actions:
        clean_steps = [_scrub_urls(s) for s in ea.step_groups[0].steps]
        clean_steps = [s for s in clean_steps if s]
        if not clean_steps:
            continue

        category = CATEGORY_MAP.get(ea.category, actionCategory.manual)
        # Use the action name + full step text for matching. We previously
        # limited this to just the first step to avoid noisy long-paragraph
        # false positives, but that lost specific keywords that only appear
        # in a later step (e.g. "rotate"/"landscape" appearing in step 3 of
        # a "Screen Orientation" action while step 1 is just "open Quick
        # settings"). Now that hardware/physical actions are routed to
        # "manual" by keyword classification (see extraction.py) before we
        # ever attempt a deeplink match, the original noise source (button-
        # press paragraphs) no longer reaches the matcher, so the fuller
        # context is safe and more accurate for genuine "auto" actions.
        query_text = ea.action_name + " " + " ".join(clean_steps)

        actionable = None
        validation = None
        match_diag = {"score": 0.0, "used_fallback": False, "matched_id": None}

        if category != actionCategory.manual:
            result: MatchResult = matcher.match(query_text)
            match_diag["score"] = round(result.score, 3)
            match_diag["used_fallback"] = result.used_fallback
            if result.entry is not None:
                entry = result.entry
                match_diag["matched_id"] = entry.get("id")
                actionable = Deeplink(
                    deeplink=entry["deeplink"],
                    description=entry.get("description", ""),
                    message=entry.get("message", ""),
                    originalType=entry.get("originalType"),
                )
                val = entry.get("validation")
                if val and val.get("deeplink") and val.get("key"):
                    validation = ValidationDeepLink(
                        deeplink=val["deeplink"], key=val["key"],
                    )
            elif result.used_fallback:
                screen_name = ea.action_name
                actionable = Deeplink(
                    deeplink="bixby://dummy_positive",
                    description=f"Opens the {screen_name.lower()} settings screen on the device.",
                    message=f"Open {screen_name} Settings",
                    originalType="placeholder",
                )

        stepgroup = StepGroup(
            steps=clean_steps,
            actionableDeeplink=actionable,
            validationDeeplink=validation,
        )
        action_name_clean = ea.action_name[:60]
        actions.append(Action(
            actionName=action_name_clean,
            description=build_description(action_name_clean),
            stepGroups=[stepgroup],
            category=category,
        ))
        diagnostics["actions"].append(match_diag)

    if not actions:
        return None, diagnostics  # caller treats as no_match

    # score: heuristic confidence -- higher when more actions resolved a real
    # (non-fallback, non-empty) deeplink match.
    resolved = sum(1 for d in diagnostics["actions"] if d["matched_id"])
    total = max(len(diagnostics["actions"]), 1)
    score = round(min(0.6 + 0.35 * (resolved / total), 0.98), 2)

    goal = Goal(goal=goal_str, title=title, actions=actions, score=score)
    return goal, diagnostics
