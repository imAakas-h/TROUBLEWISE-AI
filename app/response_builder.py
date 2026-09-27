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


def _scrub_urls(text: str) -> str:
    return URL_RE.sub("[link removed]", text).strip()


def _sentence_case_topic(words: list[str]) -> str:
    words = words[:3] or ["device", "issue"]
    return " ".join([words[0].capitalize()] + [w.lower() for w in words[1:]])


def _title_case_topic(words: list[str]) -> str:
    words = words[:3] or ["Device", "Issue"]
    return " ".join(w.capitalize() for w in words)


def build_description(action_name: str) -> str:
    """Schema-compatible neutral copy; the SIIS instruction stays in steps."""
    return "It will guide you through this step"


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
                    classes=entry.get("classes"),
                    originalType=entry.get("originalType"),
                )
                val = entry.get("validation")
                if val and val.get("deeplink") and val.get("key"):
                    metadata = {key: val.get(key) for key in ("key", "resultType", "condition", "value")}
                    validation = ValidationDeepLink(deeplink=val["deeplink"], **metadata)

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
