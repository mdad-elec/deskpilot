"""Hermetic tests for deskpilot.extract and the Drive folder-id parser.

extract.py has no frappe dependency at all, which is why it can be tested
directly. The rules worth pinning are the boring ones: an unsupported type must
report a reason rather than raise, a missing optional parser must degrade to a
skip, and the size limit must be enforced before anything tries to parse.
"""

import unittest

import frappe_stub

frappe_stub.install()

from deskpilot import extract


class TestDispatch(unittest.TestCase):
    def test_plain_text(self):
        text, why = extract.extract_bytes("notes.md", "text/markdown", b"# Title\nbody")
        self.assertIsNone(why)
        self.assertIn("# Title", text)

    def test_encoding_is_recovered_not_fatal(self):
        text, why = extract.extract_bytes("a.txt", None, "café".encode("latin-1"))
        self.assertIsNone(why)
        self.assertTrue(text)

    def test_unsupported_type_reports_a_reason(self):
        text, why = extract.extract_bytes("thing.exe", "application/octet-stream", b"MZ")
        self.assertIsNone(text)
        self.assertIn("unsupported", why)

    def test_none_content(self):
        text, why = extract.extract_bytes("a.txt", None, None)
        self.assertIsNone(text)
        self.assertEqual(why, "no content")

    def test_size_limit_is_checked_before_parsing(self):
        """An oversized PDF must be skipped by size, not handed to the parser."""
        oversized = b"x" * (extract.MAX_BYTES + 1)
        text, why = extract.extract_bytes("huge.pdf", "application/pdf", oversized)
        self.assertIsNone(text)
        self.assertIn("exceeds", why)

    def test_extension_wins_when_mime_is_absent(self):
        text, why = extract.extract_bytes("data.csv", None, b"a,b\n1,2")
        self.assertIsNone(why)
        self.assertIn("a,b", text)

    def test_pdf_mime_without_pdf_extension_is_still_a_pdf(self):
        text, why = extract.extract_bytes("scan", "application/pdf", b"not really a pdf")
        self.assertIsNone(text)
        # Either "no parser" or "parse failed" — the point is it did not raise.
        self.assertTrue(why)

    def test_every_extractable_extension_is_routed_somewhere(self):
        for ext in extract.EXTRACTABLE_EXT:
            text, why = extract.extract_bytes("f" + ext, None, b"stub")
            self.assertFalse(text is None and why is None,
                             "%s returned (None, None)" % ext)
            if why:
                self.assertNotIn("unsupported", why, "%s should be routed" % ext)


class TestParseFolderId(unittest.TestCase):
    """Users paste the browser URL far more often than the bare id."""

    def setUp(self):
        from deskpilot import kb_drive
        self.parse = kb_drive.parse_folder_id

    def test_bare_id_passes_through(self):
        self.assertEqual(self.parse("1AbCdEfGhIjKlMnOp"), "1AbCdEfGhIjKlMnOp")

    def test_folder_url(self):
        self.assertEqual(
            self.parse("https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp"),
            "1AbCdEfGhIjKlMnOp")

    def test_folder_url_with_query(self):
        self.assertEqual(
            self.parse("https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp?usp=sharing"),
            "1AbCdEfGhIjKlMnOp")

    def test_open_id_url(self):
        self.assertEqual(self.parse("https://drive.google.com/open?id=1AbCdEfGhIjKlMnOp"),
                         "1AbCdEfGhIjKlMnOp")

    def test_whitespace_is_trimmed(self):
        self.assertEqual(self.parse("  1AbCdEfGhIjKlMnOp \n"), "1AbCdEfGhIjKlMnOp")

    def test_empty(self):
        self.assertEqual(self.parse(""), "")
        self.assertEqual(self.parse(None), "")


if __name__ == "__main__":
    unittest.main()
