"""
Stage 1: Structure Extraction.

Turns raw SIIS reference text into a `schema.Goal` object: a goal string, a
short title, and an ordered list of actions/steps. This is 100% derived from
the supplied text -- no step, screen name, or feature is invented. That's the
"No Hallucinated Steps" / "Catalog Integrity" requirement from the spec.

Approach: the SIIS text is markdown with `##`/`###` headings. We segment on
headings; each heading (after the first, usually generic "Troubleshooting
Steps for X" intro heading) becomes one candidate action. Sentences under a
heading become that action's steps. Category (auto/manual/critical) is
inferred from keyword cues that map directly onto the spec's own examples
(factory reset/restart -> critical; visiting a service center / replacing
hardware -> manual; everything else -> auto, i.e. a normal Settings toggle).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADING_RE = re.compile(r"^(#{2,4})\s*(.+)$", re.MULTILINE)
URL_RE = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)

CRITICAL_KEYWORDS = [
    "factory reset", "factory data reset", "restart", "reboot",
    "firmware update", "software update", "update software",
    "update device software", "system update", "safe mode",
    "reset network settings", "erase all data", "wipe",
]
MANUAL_KEYWORDS = [
    # escalation / physical service
    "service center", "samsung support", "contact samsung", "visit an authorized",
    "replace the battery", "replace the screen", "clean the port", "clean the charging port",
    "physically inspect", "physical damage", "repair", "authorized service",
    # hardware / button-press / physical-inspection actions -- not reachable
    # via any Settings deeplink, so schema-wise these are "manual" even
    # though they aren't an escalation to a human
    "press and hold", "power button", "side button", "volume down button",
    "remove the battery", "reinsert", "ejector tool", "sim/microsd", "microsd tray",
    "flashlight", "usb cable", "usb connection", "plug in", "charger",
    "charge the device", "charge for", "liquid damage indicator", "corrosion",
    "bent pins", "restart on your device",
]
# Explicit software/UI cues -- required for a step to be eligible for "auto"
# (i.e. for us to even attempt a deeplink match). Without one of these, an
# action defaults to "manual": we'd rather under-link than hand out a wrong
# or fabricated deeplink for what might be a purely physical action.
SETTINGS_CUES = [
    "settings", "tap on", "navigate to", "toggle", "turn on", "turn off",
    "enable", "disable", "menu", "select your preferred", "swipe down",
    "notification panel", "quick panel", "go to display", "open the",
]

STOPWORDS = {
    "a", "an", "the", "of", "on", "for", "to", "and", "or", "your", "you",
    "device", "samsung", "phone", "tablet", "galaxy", "some", "things",
    "check", "first", "steps", "troubleshooting", "step", "is", "are",
    # SIIS category-tag noise that precedes the real title in raw text
    "smartphone", "wearable", "accessories", "mobile", "others", "tv",
}

TAG_PREFIX_RE = re.compile(r"^\(?[\w\s,]{0,80}?\)?\s*([A-Z][^():]{5,90}?)\s*\([^)]*\):", re.MULTILINE)


@dataclass
class ExtractedStepGroup:
    steps: list[str]
    source_heading: str


@dataclass
class ExtractedAction:
    action_name: str
    step_groups: list[ExtractedStepGroup]
    category: str  # auto | manual | critical
    raw_text: str = ""


@dataclass
class ExtractedGoal:
    topic: str          # short 2-4 word topic, used to build goal + title
    goal: str            # "Follow these steps to perform this <Topic> Troubleshooting"
    title: str            # 2-3 word sentence-case title
    actions: list[ExtractedAction] = field(default_factory=list)


def _condense_topic(title: str) -> str:
    """Collapse a long SIIS title into a short 2-4 word topic phrase."""
    t = title.lower()
    t = re.sub(r"\bon (a |an )?(samsung|galaxy).*$", "", t)
    t = re.sub(r"\bfor (a |an )?(samsung|galaxy).*$", "", t)
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    words = [w for w in t.split() if w not in STOPWORDS]
    if not words:
        words = [w for w in title.lower().split() if w.isalpha()][:3]
    words = words[:4]
    return " ".join(words) if words else "device issue"


def _clean_sentence(s: str) -> str:
    s = URL_RE.sub("", s).strip()
    s = WHITESPACE.sub(" ", s) if (WHITESPACE := re.compile(r"\s+")) else s
    return s.strip(" -*\t")


def _split_steps(block_text: str) -> list[str]:
    """Split a heading's body text into discrete, imperative-ish UI steps."""
    block_text = URL_RE.sub("", block_text)
    # Split on sentence terminators, keep reasonably substantial sentences.
    raw_sentences = re.split(r"(?<=[.!?])\s+", block_text)
    steps = []
    for s in raw_sentences:
        s = s.strip()
        if len(s) < 8:
            continue
        # Skip pure narrative/empathy filler sentences (no actionable verb cue)
        if re.match(r"^(i understand|let'?s go through|here'?s how|remember that|"
                     r"it'?s important to note|you should see)", s, re.IGNORECASE):
            continue
        steps.append(s)
    return steps or [block_text.strip()][:1]


_WORD_BOUNDARY_CACHE: dict[str, re.Pattern] = {}


def _contains_keyword(text: str, keywords: list[str]) -> bool:
    """Word-boundary keyword match -- a naive substring `in` check would
    (and empirically did) match 'wipe' inside 'Swipe', misclassifying an
    ordinary 'swipe up to open Apps' step as a destructive operation."""
    for kw in keywords:
        pattern = _WORD_BOUNDARY_CACHE.get(kw)
        if pattern is None:
            pattern = re.compile(r"\b" + re.escape(kw) + r"\b")
            _WORD_BOUNDARY_CACHE[kw] = pattern
        if pattern.search(text):
            return True
    return False


def _classify(text: str) -> str:
    low = text.lower()
    if _contains_keyword(low, MANUAL_KEYWORDS):
        return "manual"
    if _contains_keyword(low, CRITICAL_KEYWORDS):
        return "critical"
    if _contains_keyword(low, SETTINGS_CUES):
        return "auto"
    # No explicit software/settings cue found -- default to manual rather
    # than risk attempting (and possibly fabricating relevance for) a
    # deeplink match for what may be a purely physical action.
    return "manual"


def _action_name_from_heading(heading: str) -> str:
    h = re.sub(r"^step\s*\d+\s*:\s*", "", heading, flags=re.IGNORECASE).strip()
    h = re.sub(r"[^a-zA-Z0-9\s]", " ", h)
    words = h.split()
    # Title Case, capped to keep it a "screen/feature" name rather than a sentence
    return " ".join(w.capitalize() for w in words[:6]) if words else "Troubleshooting Step"


def derive_title(content: str) -> str:
    """Best-effort title guess when the caller supplies raw siis_response text
    with no separate title field (the live /v1/troubleshoot contract only
    guarantees a `siis_response` string, per the official API spec)."""
    m = TAG_PREFIX_RE.search(content[:300])
    if m:
        return m.group(1).strip()
    first_heading = HEADING_RE.search(content)
    if first_heading:
        return first_heading.group(2).strip()
    return " ".join(content.split()[:6])


def extract_goal(content: str, title: str | None = None) -> ExtractedGoal:
    if not title:
        title = derive_title(content)
    topic = _condense_topic(title)
    goal_str = f"Follow these steps to perform this {topic.title()} Troubleshooting"
    schema_title = topic  # sentence case, 2-3(ish) words

    headings = list(HEADING_RE.finditer(content))
    actions: list[ExtractedAction] = []

    if not headings:
        # No headings at all -- treat the whole body as a single action.
        steps = _split_steps(content)
        actions.append(ExtractedAction(
            action_name=_action_name_from_heading(topic),
            step_groups=[ExtractedStepGroup(steps=steps, source_heading=topic)],
            category=_classify(content),
            raw_text=content,
        ))
        return ExtractedGoal(topic=topic, goal=goal_str, title=schema_title, actions=actions)

    # Skip a generic first heading like "Troubleshooting Steps for X" only if
    # there's more than one heading (otherwise it's the only content we have).
    start_idx = 0
    if len(headings) > 1 and re.search(
        r"troubleshoot|some things to check first", headings[0].group(2), re.IGNORECASE
    ):
        start_idx = 1

    for i in range(start_idx, len(headings)):
        h = headings[i]
        heading_text = h.group(2).strip()
        body_start = h.end()
        body_end = headings[i + 1].start() if i + 1 < len(headings) else len(content)
        body = content[body_start:body_end].strip()
        if not body:
            continue
        steps = _split_steps(body)
        if not steps:
            continue
        category = _classify(heading_text + " " + body)
        actions.append(ExtractedAction(
            action_name=_action_name_from_heading(heading_text),
            step_groups=[ExtractedStepGroup(steps=steps, source_heading=heading_text)],
            category=category,
            raw_text=body,
        ))

    if not actions:
        # Fallback: every heading was filtered out (e.g. all "intro" style) --
        # use whatever body text follows the last heading, or the raw content.
        steps = _split_steps(content)
        actions.append(ExtractedAction(
            action_name=_action_name_from_heading(topic),
            step_groups=[ExtractedStepGroup(steps=steps, source_heading=topic)],
            category=_classify(content),
            raw_text=content,
        ))

    # Order: auto first, critical next, manual (service-center escalation) last.
    rank = {"auto": 0, "critical": 1, "manual": 2}
    actions.sort(key=lambda a: rank.get(a.category, 0))

    return ExtractedGoal(topic=topic, goal=goal_str, title=schema_title, actions=actions)
