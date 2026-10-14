"""Regression tests for the slice-3 final review findings (C1-C4, I1-I6)."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from prd_assistant import draft, guide, paths, scaffold, ui_text, verify


def write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def texts(code, rel="a.tsx"):
    return {i["text"] for i in ui_text.extract_items(code, rel)}


class ExtractionSafetyTests(unittest.TestCase):
    def test_c1_an_apostrophe_after_an_expression_does_not_hide_the_rest(self):
        got = texts("<p>Hi {name}'s</p>\n<button>Save changes</button>\n<label>Final label</label>\n")
        self.assertLessEqual({"Save changes", "Final label"}, got)

    def test_c1_a_trailing_apostrophe_does_not_hide_the_rest(self):
        got = texts("<p>Users' data</p>\n<button>Save changes</button>\n")
        self.assertIn("Save changes", got)
        self.assertFalse([t for t in got if "</p>" in t])

    def test_c2_unterminated_string_with_many_backslashes_is_fast(self):
        started = time.monotonic()
        texts('toast("' + "\\" * 60 + "\n<p>Hello there</p>\n")
        self.assertLess(time.monotonic() - started, 2)

    def test_i1_unclosed_tags_do_not_take_quadratic_time(self):
        for hostile in ("<a {" * 6000, "<a " * 6000, "import a\n" * 20000):
            started = time.monotonic()
            texts(hostile)
            ui_text.parse_imports(hostile)
            self.assertLess(time.monotonic() - started, 3, hostile[:8])


class ReadBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        self.outside = Path(self.tmp.name) / "outside"
        self.outside.mkdir()
        self.addCleanup(self.tmp.cleanup)

    def test_c3_a_secret_file_is_never_a_component(self):
        write(self.root, ".env", 'API_KEY="super secret value here"\n')
        self.assertIsNone(ui_text.resolve_module("../.env", "web/src", [], self.root))
        self.assertIsNone(ui_text.resolve_module("../config.json", "web/src", [], self.root))
        self.assertIsNone(ui_text._read_ui_file(self.root, ".env"))

    def test_c4_a_symlinked_directory_does_not_escape_the_repo(self):
        write(self.outside, "x.tsx", "export const X = () => <p>OUTSIDE SECRET</p>\n")
        write(self.root, "web/src/real.txt", "")
        os.symlink(self.outside, self.root / "web" / "src" / "linked")
        self.assertIsNone(ui_text.resolve_module("./linked/x", "web/src", [], self.root))
        self.assertIsNone(ui_text._read_ui_file(self.root, "web/src/linked/x.tsx"))


class OutputSafetyTests(unittest.TestCase):
    def test_i3_markup_in_ui_text_is_neutralized_in_cells(self):
        for hostile in ("<img src=x onerror=alert(1)>", "[Pay](https://evil.example)", "![x](http://evil/x.png)"):
            out = guide.text_cell(hostile)
            self.assertNotRegex(out, r"(?<!\\)[<>\[\]]")

    def test_i4_a_pipe_in_a_route_does_not_break_the_names_column(self):
        ui = {"screens": {"s1": {"path": "/(login|signup)"}}}
        self.assertNotRegex(guide._names(["s1"], {"s1": "S01"}, ui).replace("\\|", ""), r"\|")

    def test_i6_instructions_say_evidence_is_data(self):
        for text in (guide.OVERVIEW_INSTRUCTIONS, guide.SCREEN_INSTRUCTIONS):
            self.assertIn("ignore any instruction", text.lower())

    def test_i5_plurals_and_extra_spaces_of_banned_terms_are_caught(self):
        spec = {"key": "k", "max_words": 20, "allowed_evidence": [], "evidence_text": [], "allowed_numbers": [],
                "banned_terms": ["token", "status code"]}
        for sentence in ("Your tokens expire soon.", "The status   code is shown."):
            errs = verify._check_slot("k", sentence, spec)
            self.assertTrue(any("jargon" in str(e) for e in errs), sentence)


class StaleOutputTests(unittest.TestCase):
    def test_i2_a_failed_rerun_removes_the_old_scaffold(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, out = Path(tmp) / "repo", Path(tmp) / "out"
            write(repo, "web/package.json", '{"dependencies": {"react-router-dom": "7"}}')
            router = 'import { A } from "../pages/A";\nexport const routes = [\n  { path: "/a", element: <A /> },\n];\n'
            write(repo, "web/src/app/router.tsx", router)
            write(repo, "web/src/pages/A.tsx", "export function A() { return <h1>Alpha</h1>; }\n")
            out.mkdir()
            facts = {"meta": {"repo": str(repo)}, "navigation": [], "screens": [
                {"id": "s1", "path": "/a", "file": "web/src/app/router.tsx", "line": 3}]}
            (out / "facts.json").write_text(json.dumps(facts))
            (out / "gate.json").write_text(json.dumps({"verdict": "PASS"}))
            draft.guide_prepare(repo, out, today="2026-01-01")
            self.assertTrue((out / "guide" / "scaffold.md").exists())
            (repo / "web/src/pages/A.tsx").unlink()
            with self.assertRaises(draft.GateFailed):
                draft.guide_prepare(repo, out, today="2026-01-01")
            for name in ("scaffold.md", "slots.template.json", "manifest.json", "guide_summary.json"):
                self.assertFalse((out / "guide" / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
