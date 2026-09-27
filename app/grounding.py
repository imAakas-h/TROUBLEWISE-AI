"""Programmatic checks that plans and deeplinks stay within trusted sources."""
from __future__ import annotations

from app.schema import ContextDeeplinkResponse


class GroundingError(ValueError):
    pass


def validate_grounding(response: dict, source_text: str, catalog: list[dict]) -> None:
    parsed = ContextDeeplinkResponse.model_validate(response)
    source = source_text.casefold()
    catalog_by_uri = {item.get("deeplink"): item for item in catalog}
    for goal in parsed.contexts:
        for action in goal.actions:
            for group in action.stepGroups:
                for step in group.steps:
                    # Extraction is intentionally verbatim; URLs are removed
                    # before output so their remaining source text is checked.
                    if step.casefold() not in source:
                        raise GroundingError(f"Step is not a source excerpt: {step[:90]!r}")
                actionable = group.actionableDeeplink
                if actionable:
                    match = catalog_by_uri.get(actionable.deeplink)
                    if match is None:
                        raise GroundingError(f"Actionable deeplink is not in catalog: {actionable.deeplink}")
                    if match.get("deeplink") != actionable.deeplink:
                        raise GroundingError("Actionable deeplink URI changed")
                validation = group.validationDeeplink
                if validation:
                    parent = next((x for x in catalog if (x.get("validation") or {}).get("deeplink") == validation.deeplink), None)
                    if parent is None:
                        raise GroundingError(f"Validation deeplink is not in catalog: {validation.deeplink}")
                    metadata = parent["validation"]
                    for field in ("key", "resultType", "condition", "value"):
                        expected = metadata.get(field)
                        actual = getattr(validation, field)
                        if expected is not None and actual != expected:
                            raise GroundingError(f"Validation metadata mismatch for {field}")
