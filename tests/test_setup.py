"""Tests for the wizard's write path and its secret handling.

setup.save() is reachable from the browser, so what it will and will not write is
a security boundary, not a detail. Two properties are pinned here: a step can only
write its own fields, and a blank secret never overwrites a stored one.
"""

import json
import unittest

import frappe_stub

frappe = frappe_stub.install()

from deskpilot import config, setup


class _SaveDoc(frappe_stub.Doc):
    """Records what the wizard set, so the test can assert on it."""

    def __init__(self, values=None, passwords=None):
        super().__init__(values, passwords)
        self.saved = False

    def set(self, key, value):
        self[key] = value

    def save(self, ignore_permissions=False):
        self.saved = True


class SetupTestCase(unittest.TestCase):
    def setUp(self):
        frappe_stub.reset(frappe)
        self.doc = _SaveDoc({}, {"api_key": "stored-secret"})
        frappe._doc = self.doc
        config.invalidate()


class TestStepAllowList(SetupTestCase):
    def test_writes_its_own_fields(self):
        setup.save("access", json.dumps({"required_role": "Sales User"}))
        self.assertEqual(self.doc["required_role"], "Sales User")
        self.assertTrue(self.doc.saved)

    def test_will_not_write_another_steps_field(self):
        setup.save("access", json.dumps({"required_role": "R", "api_base": "http://evil/v1"}))
        self.assertEqual(self.doc["required_role"], "R")
        self.assertNotIn("api_base", self.doc)

    def test_will_not_write_an_unknown_field(self):
        setup.save("personalize", json.dumps({"helper_name": "Ada", "setup_complete": 1}))
        self.assertEqual(self.doc["helper_name"], "Ada")
        self.assertNotIn("setup_complete", self.doc)

    def test_unknown_step_is_rejected(self):
        with self.assertRaises(Exception):
            setup.save("nonesuch", json.dumps({"x": 1}))

    def test_accepts_a_dict_as_well_as_a_json_string(self):
        setup.save("personalize", {"helper_name": "Ada"})
        self.assertEqual(self.doc["helper_name"], "Ada")

    def test_every_step_field_is_a_real_settings_field(self):
        """A typo here would silently write a field the form never shows."""
        import json as _json
        import os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "deskpilot", "deskpilot", "doctype",
                               "deskpilot_settings", "deskpilot_settings.json")) as fh:
            schema = _json.load(fh)
        real = {f["fieldname"] for f in schema["fields"]}
        for step, fields in setup.STEP_FIELDS.items():
            for f in fields:
                self.assertIn(f, real, "%s step writes unknown field %s" % (step, f))


class TestSecrets(SetupTestCase):
    def test_blank_secret_does_not_wipe_a_stored_one(self):
        setup.save("model", json.dumps({"api_key": "", "model": "m"}))
        self.assertNotIn("api_key", self.doc)
        self.assertEqual(self.doc["model"], "m")

    def test_a_supplied_secret_is_written(self):
        setup.save("model", json.dumps({"api_key": "new-key"}))
        self.assertEqual(self.doc["api_key"], "new-key")

    def test_state_reports_presence_not_value(self):
        st = setup.state()
        self.assertTrue(st["api_key_set"])
        self.assertNotIn("api_key", st)
        self.assertNotIn("stored-secret", json.dumps(st))

    def test_state_carries_no_secret_field_at_all(self):
        st = setup.state()
        for secret in ("api_key", "embed_key", "kb_mcp_token", "drive_refresh_token"):
            self.assertNotIn(secret, st)


if __name__ == "__main__":
    unittest.main()
