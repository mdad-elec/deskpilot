"""Packaging metadata that a marketplace install depends on.

None of this is exercised by importing the app, which is exactly why it goes
missing: the declared Frappe compatibility was absent until Frappe Cloud rejected
the submission for it, and nothing in the repo had an opinion.

The useful property here is not "the key exists" but "the key agrees with what CI
installs against". A claim of support that no job tests is the thing worth
failing on.
"""

import os
import re
import unittest

import tomllib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPROJECT = os.path.join(REPO, "pyproject.toml")
WORKFLOW = os.path.join(REPO, ".github", "workflows", "ci.yml")


def pyproject():
    with open(PYPROJECT, "rb") as fh:
        return tomllib.load(fh)


def ci_frappe_branches():
    """The version-N branches the install job actually builds against."""
    with open(WORKFLOW) as fh:
        return {int(m) for m in re.findall(r"frappe-branch:\s*version-(\d+)", fh.read())}


class TestFrappeDependencies(unittest.TestCase):
    def setUp(self):
        self.deps = pyproject().get("tool", {}).get("bench", {}).get("frappe-dependencies", {})

    def test_declared_at_all(self):
        """Frappe Cloud refuses the app without this; bench warns on get-app."""
        self.assertIn("frappe", self.deps,
                      "[tool.bench.frappe-dependencies] must declare frappe")

    def test_is_a_bounded_range(self):
        spec = self.deps["frappe"]
        self.assertRegex(spec, r">=\d+\.\d+\.\d+", "needs a lower bound")
        self.assertRegex(spec, r"<\d+\.\d+\.\d+", "needs an upper bound")

    def test_range_covers_every_branch_ci_installs(self):
        lower = int(re.search(r">=(\d+)\.", self.deps["frappe"]).group(1))
        upper = int(re.search(r"<(\d+)\.", self.deps["frappe"]).group(1))
        branches = ci_frappe_branches()
        self.assertTrue(branches, "no version-N branches found in the CI matrix")
        for major in branches:
            self.assertGreaterEqual(major, lower,
                                    "CI installs v%d, below the declared floor" % major)
            self.assertLess(major, upper,
                            "CI installs v%d, at or above the declared ceiling" % major)

    def test_does_not_claim_more_than_ci_tests(self):
        """Widening the range without adding a CI job is the failure mode."""
        lower = int(re.search(r">=(\d+)\.", self.deps["frappe"]).group(1))
        upper = int(re.search(r"<(\d+)\.", self.deps["frappe"]).group(1))
        branches = ci_frappe_branches()
        self.assertEqual(
            set(range(lower, upper)), branches,
            "declared support is %s but CI installs %s — test what you claim"
            % (sorted(range(lower, upper)), sorted(branches)))

    def test_erpnext_is_not_claimed_as_required(self):
        """CI installs onto a plain Frappe bench; naming erpnext would be false."""
        self.assertNotIn("erpnext", self.deps)


class TestProjectMetadata(unittest.TestCase):
    def setUp(self):
        self.project = pyproject()["project"]

    def test_name_matches_the_app_module(self):
        self.assertEqual(self.project["name"], "deskpilot")
        self.assertTrue(os.path.isdir(os.path.join(REPO, "deskpilot")))

    def test_python_floor_suits_the_oldest_supported_line(self):
        """Frappe v16 pins 3.14; copying that here would break every v15 site."""
        self.assertEqual(self.project["requires-python"], ">=3.10")

    def test_version_is_released_not_scaffold(self):
        with open(os.path.join(REPO, "deskpilot", "__init__.py")) as fh:
            version = re.search(r'__version__\s*=\s*"([^"]+)"', fh.read()).group(1)
        self.assertNotEqual(version, "0.0.1", "still the scaffold version")
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
