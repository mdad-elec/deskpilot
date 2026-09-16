"""Hermetic tests for deskpilot.config — the settings resolver.

No bench, no site, no database: `frappe` is stubbed. This is deliberate. The
resolver decides what every other module reads, its rules are subtle (three
tiers, two of which treat "empty" differently), and the alternative is finding
out on a live site. These run anywhere python does, which is why CI can gate on
them.

    python3 -m unittest discover -s tests -v
"""

import sys
import types
import unittest

import frappe_stub

frappe = frappe_stub.install()
_Doc = frappe_stub.Doc

from deskpilot import config  # must be imported after the stub is installed


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        frappe_stub.reset(frappe)
        config.invalidate()

    def settings(self, values=None, passwords=None):
        frappe._doc = _Doc(values, passwords)
        config.invalidate()


class TestResolutionOrder(ConfigTestCase):
    def test_default_when_nothing_is_set(self):
        self.assertEqual(config.get("embed_model"), "nomic-embed-text")

    def test_site_config_beats_default(self):
        frappe.conf = {"deskpilot_embed_model": "bge-m3"}
        self.assertEqual(config.get("embed_model"), "bge-m3")

    def test_settings_beats_site_config(self):
        frappe.conf = {"deskpilot_embed_model": "bge-m3"}
        self.settings({"embed_model": "from-settings"})
        self.assertEqual(config.get("embed_model"), "from-settings")

    def test_blank_settings_field_falls_through_to_site_config(self):
        """The whole reason defaults are not in the DocType JSON."""
        frappe.conf = {"deskpilot_embed_model": "bge-m3"}
        self.settings({"embed_model": ""})
        self.assertEqual(config.get("embed_model"), "bge-m3")

    def test_unknown_key_returns_the_given_default(self):
        self.assertIsNone(config.get("nonesuch", None))
        self.assertEqual(config.get("nonesuch", "fallback"), "fallback")

    def test_unknown_key_with_no_default_is_none(self):
        self.assertIsNone(config.get("nonesuch"))


class TestChecks(ConfigTestCase):
    """A flag turned on in site_config must be switchable off from the UI."""

    def test_unticked_setting_overrides_site_config(self):
        frappe.conf = {"deskpilot_vision_disabled": 1}
        self.settings({"vision_disabled": 0})
        self.assertFalse(config.get_bool("vision_disabled"))

    def test_ticked_setting_is_true(self):
        self.settings({"vision_disabled": 1})
        self.assertTrue(config.get_bool("vision_disabled"))

    def test_site_config_applies_when_there_is_no_settings_row(self):
        frappe.conf = {"deskpilot_vision_disabled": 1}
        self.assertTrue(config.get_bool("vision_disabled"))


class TestInts(ConfigTestCase):
    def test_zero_means_use_the_default(self):
        self.settings({"max_job_seconds": 0})
        self.assertEqual(config.get_int("max_job_seconds", 150), 150)

    def test_real_value_is_used(self):
        self.settings({"max_job_seconds": 42})
        self.assertEqual(config.get_int("max_job_seconds", 150), 42)

    def test_garbage_falls_back_rather_than_raising(self):
        self.settings({"max_job_seconds": "not a number"})
        self.assertEqual(config.get_int("max_job_seconds", 150), 150)


class TestLines(ConfigTestCase):
    def test_splits_and_strips(self):
        self.settings({"blocked_topics": "  alpha \n\n beta \n"})
        self.assertEqual(config.get_lines("blocked_topics"), ["alpha", "beta"])

    def test_commas_also_split(self):
        self.settings({"issue_assignees": "a@x.com, b@x.com"})
        self.assertEqual(config.get_lines("issue_assignees"), ["a@x.com", "b@x.com"])

    def test_empty_is_empty_list(self):
        self.assertEqual(config.get_lines("blocked_topics"), [])


class TestPasswords(ConfigTestCase):
    def test_reads_from_settings(self):
        self.settings({}, {"api_key": "sekrit"})
        self.assertEqual(config.get_password("api_key"), "sekrit")

    def test_falls_back_to_site_config(self):
        frappe.conf = {"deskpilot_api_key": "from-conf"}
        self.assertEqual(config.get_password("api_key"), "from-conf")

    def test_undecryptable_value_does_not_raise(self):
        class Exploding(_Doc):
            def get_password(self, key, raise_exception=True):
                raise RuntimeError("cannot decrypt")

        frappe._doc = Exploding({})
        config.invalidate()
        self.assertIsNone(config.get_password("api_key"))


class TestSurvivesAMissingDocType(ConfigTestCase):
    """Code deployed, `bench migrate` not run yet: must degrade, never raise."""

    def test_missing_doctype_falls_back(self):
        frappe._doctype_exists = False
        frappe.conf = {"deskpilot_embed_model": "bge-m3"}
        self.assertEqual(config.get("embed_model"), "bge-m3")

    def test_no_database_at_all_falls_back(self):
        frappe.local = types.SimpleNamespace(db=None)
        config.invalidate()
        self.assertEqual(config.get("embed_model"), "nomic-embed-text")

    def test_exploding_get_cached_doc_falls_back(self):
        def boom(_):
            raise RuntimeError("table doesn't exist")

        frappe.get_cached_doc = boom
        config.invalidate()
        self.assertEqual(config.get("embed_model"), "nomic-embed-text")


class TestLLMResolution(ConfigTestCase):
    def test_nothing_configured_is_provider_none(self):
        sys.modules["deskpilot.api"] = types.SimpleNamespace(_raven_llm=lambda: None)
        self.assertEqual(config.get_llm(), (None, None, None, "none"))

    def test_settings_key_with_openai_provider_uses_preset_base_and_model(self):
        self.settings({"provider": "OpenAI"}, {"api_key": "k"})
        key, base, model, tag = config.get_llm()
        self.assertEqual((key, base, model, tag),
                         ("k", "https://api.openai.com/v1", "gpt-4o-mini", "configured"))

    def test_explicit_base_and_model_win_over_preset(self):
        self.settings({"provider": "OpenAI", "api_base": "http://local/v1", "model": "m"},
                      {"api_key": "k"})
        self.assertEqual(config.get_llm(), ("k", "http://local/v1", "m", "configured"))

    def test_key_without_endpoint_does_not_claim_to_be_configured(self):
        """An OpenAI-compatible provider has no preset, so a bare key is not usable."""
        sys.modules["deskpilot.api"] = types.SimpleNamespace(_raven_llm=lambda: None)
        self.settings({"provider": "OpenAI-compatible"}, {"api_key": "k"})
        self.assertEqual(config.get_llm()[3], "none")

    def test_legacy_openai_api_key_still_works(self):
        sys.modules["deskpilot.api"] = types.SimpleNamespace(_raven_llm=lambda: None)
        frappe.conf = {"openai_api_key": "legacy"}
        key, _base, _model, tag = config.get_llm()
        self.assertEqual((key, tag), ("legacy", "openai"))

    def test_raven_provider_delegates(self):
        sentinel = ("k", "b", "m", "raven-local")
        sys.modules["deskpilot.api"] = types.SimpleNamespace(_raven_llm=lambda: sentinel)
        self.settings({"provider": "Raven Settings"})
        self.assertEqual(config.get_llm(), sentinel)


class TestPublicAppearance(ConfigTestCase):
    def test_defaults(self):
        a = config.public_appearance()
        self.assertEqual(a["helper_name"], "Deskpilot")
        self.assertEqual(a["avatar_url"], "/assets/deskpilot/img/deskpilot_mark.svg")

    def test_overrides(self):
        self.settings({"helper_name": "Ada", "greeting": "Hi", "avatar": "/files/a.png"})
        self.assertEqual(config.public_appearance(),
                         {"helper_name": "Ada", "greeting": "Hi", "avatar_url": "/files/a.png"})

    def test_carries_no_secrets(self):
        self.settings({"helper_name": "Ada"}, {"api_key": "sekrit"})
        self.assertNotIn("sekrit", str(config.public_appearance()))


if __name__ == "__main__":
    unittest.main()
