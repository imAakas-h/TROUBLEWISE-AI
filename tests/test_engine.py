"""Contract, grounding, cache, retrieval, and safety regression tests."""
import json
import unittest
from pathlib import Path

from app.extraction import extract_goal, ExtractedGoal, ExtractedAction, ExtractedStepGroup
from app.grounding import GroundingError, validate_grounding
from app.pipeline import TroubleshootingEngine
from app.query_enrichment import enrich_query
from app.retrieval import SiisRetriever
from app.deeplink_matcher import MatchResult
from app.response_builder import build_goal
from app.schema import ContextDeeplinkResponse

ROOT = Path(__file__).resolve().parent.parent


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.deeplinks = json.loads((ROOT / "data/deeplinks.json").read_text(encoding="utf-8"))["deeplinks"]
        cls.siis = json.loads((ROOT / "data/siis_responses.json").read_text(encoding="utf-8"))["responses"]
        cls.engine = TroubleshootingEngine(cls.deeplinks, cls.siis)

    def test_schema_sample_output(self):
        sample = json.loads((ROOT / "data/sample_output.json").read_text(encoding="utf-8"))["response"]
        ContextDeeplinkResponse.model_validate(sample)

    def test_empty_and_unrelated_queries_fall_back(self):
        for query in ("", "x", "the weather in Paris", "a" * 2001):
            result = self.engine.run(query)
            self.assertEqual(result["response"]["contexts"], [])
            ContextDeeplinkResponse.model_validate(result["response"])

    def test_grounding_rejects_fabricated_step(self):
        response = {"contexts": [{"goal": "Follow these steps to perform this Test Troubleshooting",
                    "title": "Test Plan", "score": 0.5, "actions": [{"actionName": "Test",
                    "description": "It will guide you through Test", "category": "manual",
                    "stepGroups": [{"steps": ["Invent a new Settings menu"]}]}]}]}
        with self.assertRaises(GroundingError):
            validate_grounding(response, "Source text without that step", self.deeplinks)

    def test_only_catalog_actionable_uris_are_returned(self):
        uri_set = {x["deeplink"] for x in self.deeplinks}
        entry = self.siis[0]
        result = self.engine.run(entry["original_query"], entry["siis_response"]["content"], entry["siis_response"]["title"])
        parsed = ContextDeeplinkResponse.model_validate(result["response"])
        for goal in parsed.contexts:
            for action in goal.actions:
                for group in action.stepGroups:
                    if group.actionableDeeplink:
                        self.assertIn(group.actionableDeeplink.deeplink, uri_set)
                        self.assertNotEqual(group.actionableDeeplink.deeplink, "bixby://dummy_positive")

    def test_cache_exact_hit_and_context_bypass(self):
        entry = self.siis[0]
        query = entry["original_query"]
        self.engine.prewarm([entry])
        self.assertTrue(self.engine.run(query)["meta"]["cache_hit"])
        overridden = self.engine.run(query, "", "different context")
        self.assertFalse(overridden["meta"]["cache_hit"])

    def test_retrieval_finds_black_display_kb(self):
        results = SiisRetriever(self.siis).search("phone display suddenly turns black")
        self.assertTrue(results)
        self.assertIn("display", results[0].entry["siis_response"]["title"].lower())

    def test_broad_app_symptoms_match_but_small_screen_does_not_match_gesture_article(self):
        engine = TroubleshootingEngine(self.deeplinks, self.siis)
        broad = engine.run("screen is blank in Smart Tutor and it happens with other apps too")
        self.assertTrue(broad["response"]["contexts"])
        small = engine.run("my main screen is small and does not fill the whole display")
        self.assertEqual(small["response"]["contexts"], [])

    def test_typo_heavy_query_is_normalized_conservatively(self):
        result = self.engine.run("scren going blak")
        ContextDeeplinkResponse.model_validate(result["response"])
        self.assertTrue(result["response"]["contexts"])

    def test_cache_reuses_safe_canonical_intent(self):
        engine = TroubleshootingEngine(self.deeplinks, self.siis)
        first = engine.run("my screen keeps going black")
        second = engine.run("phone display suddenly turns black")
        self.assertFalse(first["meta"]["cache_hit"])
        self.assertTrue(second["meta"]["cache_hit"])

    def test_entity_extraction_keeps_useful_context(self):
        enriched = enrich_query("Galaxy Z Flip 6: screen blanks when charging in Gmail after restart")
        self.assertTrue(enriched.device_context)
        self.assertIn("application", enriched.entities)
        self.assertIn("trigger", enriched.entities)
        self.assertIn("gmail", enriched.canonical)

    def test_canonical_cache_key_normalizes_wording_but_keeps_triggers(self):
        from app.query_enrichment import canonicalize
        a = canonicalize("my screen keeps going black")
        b = canonicalize("screen goes black on my phone")
        c = canonicalize("phone display suddenly turns black")
        self.assertEqual(a, b)
        self.assertEqual(b, c)
        self.assertNotEqual(a, canonicalize("screen goes black while charging"))

    def test_heading_extraction_preserves_source_order(self):
        sample = "## Troubleshooting Steps\n### Step 1: Check display\nCheck the display.\n### Step 2: Contact service\nContact Samsung Support."
        result = extract_goal(sample, "Display troubleshooting")
        self.assertEqual([a.action_name for a in result.actions], ["Check Display", "Contact Service"])

    def test_destructive_action_is_not_first(self):
        sample = ("## Troubleshooting Steps\n### Step 1: Factory data reset\n"
                  "Navigate to Settings and perform a factory data reset.\n"
                  "### Step 2: Check display settings\nOpen Settings and check display settings.")
        result = extract_goal(sample, "Display troubleshooting")
        self.assertEqual(result.actions[0].action_name, "Check Display Settings")
        self.assertEqual(result.actions[1].category, "critical")

    def test_validation_metadata_is_preserved(self):
        entry = next(x for x in self.deeplinks if (x.get("validation") or {}).get("resultType"))
        source_step = "Navigate to Settings and open the setting."
        extracted = ExtractedGoal("test issue", "Follow these steps to perform this Test Issue Troubleshooting",
            "Test issue", [ExtractedAction("Test Setting", [ExtractedStepGroup([source_step], "Test Setting")], "auto")])
        matcher = self.engine.matcher
        original_match = matcher.match
        matcher.match = lambda _: MatchResult(entry=entry, score=1.0, used_fallback=False)
        try:
            goal, _ = build_goal(extracted, matcher)
        finally:
            matcher.match = original_match
        val = goal.actions[0].stepGroups[0].validationDeeplink
        expected = entry["validation"]
        self.assertEqual(val.key, expected["key"])
        self.assertEqual(val.resultType.value, expected["resultType"])
        self.assertEqual(val.condition.value, expected["condition"])
        self.assertEqual(val.value, expected["value"])

    def test_dummy_catalog_placeholder_is_not_matchable(self):
        self.assertFalse(any(x.get("deeplink") == "bixby://dummy_positive" for x in self.engine.matcher.entries))

    def test_ambiguous_screen_query_selects_grounded_probe(self):
        result = self.engine.run("my screen keeps going black")
        meta = result["meta"]["diagnostics"]["adaptive_probe"]
        self.assertEqual(len(result["meta"]["diagnostics"]["retrieval"]), 1)
        self.assertTrue(meta["selected"])
        self.assertTrue(meta)
        self.assertTrue(meta["probe_text"])
        self.assertTrue(meta["hypotheses"])
        self.assertEqual(len(result["response"]["contexts"][0]["actions"]), 1)
        self.assertIn(meta["probe_text"], self.siis[1]["siis_response"]["content"])


if __name__ == "__main__":
    unittest.main()
