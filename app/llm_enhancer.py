"""
Groq-powered AI enhancement layer for the troubleshooting engine.

This module:
1. Generates query paraphrases.
2. Polishes troubleshooting action descriptions.
3. Generates grounded AI guidance.
4. Uses previous user experiences when available.

The core troubleshooting engine still works if Groq is unavailable.
"""

from __future__ import annotations

import json
import os
import re

from dotenv import load_dotenv

load_dotenv()

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_TIMEOUT_SECONDS = 15.0


def is_available() -> bool:
    return bool(os.environ.get("GROQ_API_KEY")) and requests is not None


def _chat(system: str, user: str, max_tokens: int = 300) -> str | None:
    """Send one request to Groq and return the generated text."""

    api_key = os.environ.get("GROQ_API_KEY")

    if not api_key or requests is None:
        return None

    try:
        response = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": system,
                    },
                    {
                        "role": "user",
                        "content": user,
                    },
                ],
                "max_completion_tokens": max_tokens,
                "temperature": 0.4,
                "include_reasoning": False,
            },
            timeout=GROQ_TIMEOUT_SECONDS,
        )

        response.raise_for_status()

        data = response.json()

        content = data["choices"][0]["message"].get("content")

        if not content:
            return None

        return content.strip()

    except requests.HTTPError:
        print(
            f"[Groq] HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )
        return None

    except Exception as exc:
        print(f"[Groq] {type(exc).__name__}: {exc}")
        return None


def generate_paraphrases(
    canonical_query: str,
    n: int = 8,
) -> list[str]:
    """Generate alternative versions of a troubleshooting query."""

    text = _chat(
        system=(
            "You paraphrase short technical support queries. "
            f"Return exactly {n} different paraphrases. "
            "Return one paraphrase per line. "
            "No numbering, no bullets, no explanations, no markdown."
        ),
        user=canonical_query,
        max_tokens=250,
    )

    if not text:
        return []

    lines = [
        re.sub(r"^[\d\.\)\-\s]+", "", line).strip()
        for line in text.splitlines()
    ]

    return [line for line in lines if line][:n]


def polish_description(
    action_name: str,
    category: str,
) -> str | None:
    """Generate a short description for a troubleshooting action."""

    text = _chat(
        system=(
            "Write one short troubleshooting action description. "
            "It MUST start with exactly 'It will'. "
            "Use between 5 and 10 words. "
            "Return ONLY the description. "
            "Do not use quotes, bullets, numbering, markdown, "
            "or explanations."
        ),
        user=(
            f"Action: {action_name}\n"
            f"Category: {category}"
        ),
        max_tokens=80,
    )

    if not text:
        return None

    candidate = text.strip()

    # Remove accidental quotes
    candidate = candidate.strip('"').strip("'").strip()

    # Remove accidental bullets/numbering
    candidate = re.sub(
        r"^[\-\*\d\.\)\s]+",
        "",
        candidate,
    ).strip()

    # Remove trailing punctuation
    candidate = candidate.rstrip(".!?")

    words = candidate.split()

    if (
        5 <= len(words) <= 10
        and candidate.lower().startswith("it will")
    ):
        return candidate

    return None


def generate_guidance(
    query: str,
    grounded_response: dict,
    experiences: list[dict],
) -> dict | None:
    """
    Generate grounded AI guidance using Groq.

    The LLM can explain the verified troubleshooting result,
    but it must not invent new troubleshooting actions.
    """

    # ---------------------------------------------------------
    # Previous user experience
    # ---------------------------------------------------------

    experience_text = "No previous user experiences are available."

    if experiences:
        experience_lines = []

        for item in experiences:
            outcome = item.get("outcome", "unknown")
            action = item.get("action_name", "")
            note = item.get("note", "")

            line = f"- Outcome: {outcome}"

            if action:
                line += f"; Action: {action}"

            if note:
                line += f"; Note: {note}"

            experience_lines.append(line)

        experience_text = "\n".join(experience_lines)

    # ---------------------------------------------------------
    # System prompt
    # ---------------------------------------------------------

    system = """
You are an AI troubleshooting assistant.

Your job is to explain the troubleshooting result supplied
to you and help the user understand what to do next.

IMPORTANT RULES:

1. Use ONLY the verified troubleshooting information supplied.
2. Do NOT invent troubleshooting steps.
3. Do NOT invent settings, buttons, menus, URLs, or device behavior.
4. Do NOT diagnose unsupported problems.
5. You may explain why an existing verified step is relevant.
6. You may use previous user experiences as supporting context.
7. Keep the response short, practical, and easy to understand.
8. Return ONLY valid JSON.
9. Do not use markdown.
10. Do not put the JSON inside ```json fences.

Return exactly this structure:

{
  "message": "short helpful guidance",
  "experience_insight": "short insight from previous experiences or empty string",
  "next_question": "one useful question for the user"
}
"""

    # ---------------------------------------------------------
    # User prompt
    # ---------------------------------------------------------

    user = f"""
USER PROBLEM:
{query}

VERIFIED TROUBLESHOOTING RESULT:
{json.dumps(grounded_response, ensure_ascii=False, indent=2)}

PREVIOUS USER EXPERIENCES:
{experience_text}

Generate grounded guidance for the user.
"""

    # ---------------------------------------------------------
    # Call Groq
    # ---------------------------------------------------------

    text = _chat(
        system=system,
        user=user,
        max_tokens=400,
    )

    if not text:
        return None

    # ---------------------------------------------------------
    # Parse JSON
    # ---------------------------------------------------------

    try:
        cleaned = text.strip()

        # Remove accidental markdown code fences
        if cleaned.startswith("```"):
            cleaned = re.sub(
                r"^```(?:json)?\s*",
                "",
                cleaned,
                flags=re.IGNORECASE,
            )

            cleaned = re.sub(
                r"\s*```$",
                "",
                cleaned,
            )

            cleaned = cleaned.strip()

        data = json.loads(cleaned)

        if not isinstance(data, dict):
            return None

        required = [
            "message",
            "experience_insight",
            "next_question",
        ]

        if not all(key in data for key in required):
            return None

        return {
            "message": str(data["message"]),
            "experience_insight": str(
                data["experience_insight"]
            ),
            "next_question": str(
                data["next_question"]
            ),
        }

    except Exception as exc:
        print(f"[Groq] Invalid guidance JSON: {exc}")
        print(f"[Groq] Raw response: {text[:1000]}")
        return None


# -------------------------------------------------------------
# Local self-test
# -------------------------------------------------------------

if __name__ == "__main__":

    if not is_available():
        print(
            "GROQ_API_KEY not set "
            "(or requests is missing)."
        )

    else:

        print("Testing generate_paraphrases()...")

        paraphrases = generate_paraphrases(
            "phone screen is black and unresponsive"
        )

        print(paraphrases)

        print()
        print("Testing polish_description()...")

        description = polish_description(
            "Configure Navigation Bar Settings",
            "auto",
        )

        print(description)

        print()
        print("Testing generate_guidance()...")

        test_response = {
            "status": "success",
            "steps": [
                {
                    "name": "Configure Navigation Bar Settings",
                    "description": "It will configure navigation settings",
                }
            ],
        }

        guidance = generate_guidance(
            query="My phone screen is black",
            grounded_response=test_response,
            experiences=[],
        )

        print(json.dumps(
            guidance,
            indent=2,
            ensure_ascii=False,
        ))