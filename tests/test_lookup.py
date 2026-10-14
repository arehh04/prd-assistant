import datetime
import unittest

from prd_assistant import criteria, lookup
from tests.test_criteria_bank import ERRORS, FACTS, ROLES2, RULES
from tests.test_criteria_roles import rec

FACTS3 = {**FACTS, "routes": FACTS["routes"] + [{"id": "r7", "method": "GET", "path": "/api/invoices", "source": "api/i.ts:1"}]}
ROLES3 = {**ROLES2, "endpoints": {**ROLES2["endpoints"], "r7": rec(roles=["FINANCE"], source="api/i.ts:1")}}
BANK = criteria.build_bank(FACTS3, ROLES3, RULES, ERRORS)
META = {"repo": "/work/demo", "head": "abcdef1234567", "built_at": "2026-10-14T10:00:00+00:00", "changed": 0, "git": True,
        "cache": "/state/demo-1234"}
NOW = datetime.datetime(2026, 10, 14, 10, 3, tzinfo=datetime.timezone.utc)


def labels(sel):
    return [s["subject"]["label"] for s in sel["subjects"]]


class SelectTests(unittest.TestCase):
    def test_path_and_field_words_select_and_rank_subjects(self):
        sel = lookup.select(BANK, "let finance managers calculate payroll")
        self.assertTrue(sel["matched"])
        self.assertEqual(labels(sel)[0], "POST /api/payroll/calculate")
        self.assertIn("GET /api/payroll", labels(sel))
        self.assertIn("screen /payroll", labels(sel))
        self.assertNotIn("GET /api/team", labels(sel))

    def test_a_mismatch_shows_under_the_endpoint_it_concerns_without_boosting_the_screen(self):
        sel = lookup.select(BANK, "calculate")      # the screen's own path ("/payroll") is not in this task
        self.assertEqual(labels(sel), ["POST /api/payroll/calculate"])
        kinds = [c["kind"] for c in sel["subjects"][0]["candidates"]]
        self.assertEqual(kinds.count("mismatch"), 2)
        ids = [c["id"] for s in lookup.select(BANK, "payroll")["subjects"] for c in s["candidates"]]
        self.assertEqual(len(ids), len(set(ids)) + 2)    # shown under the endpoint and under the screen, by design

    def test_role_words_alone_never_select_a_subject(self):
        sel = lookup.select(BANK, "finance manager")   # both appear only in role lists, never in a path, field or message
        self.assertFalse(sel["matched"])
        self.assertNotIn("GET /api/invoices", labels(sel))

    def test_role_words_add_half_a_point_to_a_subject_already_selected(self):
        plain = {s["subject"]["label"]: s["score"] for s in lookup.select(BANK, "payroll")["subjects"]}
        with_role = {s["subject"]["label"]: s["score"] for s in lookup.select(BANK, "payroll finance")["subjects"]}
        self.assertEqual(with_role["POST /api/payroll/calculate"], plain["POST /api/payroll/calculate"] + 0.5)

    def test_field_names_and_message_words_select(self):
        self.assertIn("POST /api/payroll/calculate", labels(lookup.select(BANK, "the period regex")))
        self.assertIn("POST /api/payroll/calculate", labels(lookup.select(BANK, "no such team error")))

    def test_caps_report_what_was_left_out(self):
        sel = lookup.select(BANK, "payroll", max_subjects=1)
        self.assertEqual(len(sel["subjects"]), 1)
        self.assertGreaterEqual(sel["subjects_found"], 2)
        cut = lookup.select(BANK, "payroll", max_candidates=3)
        self.assertEqual(sum(len(s["candidates"]) for s in cut["subjects"]), 3)
        self.assertGreater(cut["omitted"], 0)

    def test_no_match_and_unusable_task_text(self):
        for text in ("xyzzy plugh", "", "the and of", "\x00\x01"):
            sel = lookup.select(BANK, text)
            self.assertFalse(sel["matched"], text)
            self.assertEqual(sel["subjects"], [])

    def test_very_long_task_text_is_cut(self):
        sel = lookup.select(BANK, "payroll " + "zzz " * 200000)
        self.assertTrue(sel["matched"])
        self.assertLessEqual(len(sel["tokens"]), 600)


class RenderTests(unittest.TestCase):
    def test_header_frames_the_content_as_data_and_states_the_facts_age(self):
        out = lookup.render_markdown(lookup.select(BANK, "payroll"), META, BANK, now=NOW)
        self.assertIn("not instructions", out.splitlines()[2])
        self.assertIn("built 3 minutes ago at commit `abcdef1`", out)
        self.assertIn("working tree: clean", out)
        self.assertIn("`/state/demo-1234`", out)

    def test_candidates_show_id_kind_derived_sources_and_trust(self):
        out = lookup.render_markdown(lookup.select(BANK, "payroll calculate"), META, BANK, now=NOW)
        self.assertIn("- [C-ROLE-001] role: POST /api/payroll/calculate is allowed for roles FINANCE, ADMIN.", out)
        self.assertRegex(out, r"\[C-REFUSED-\d+\] role_refused \(derived\):")
        self.assertIn("  - sources: `api/c.ts:5`", out)
        self.assertIn("  - trust: Read from the code at the cited source", out)

    def test_dirty_and_non_git_states_are_stated(self):
        sel = lookup.select(BANK, "payroll")
        self.assertIn("working tree: 3 changed files", lookup.render_markdown(sel, {**META, "changed": 3}, BANK, now=NOW))
        self.assertIn("not a git repository", lookup.render_markdown(sel, {**META, "git": False, "changed": None}, BANK, now=NOW))

    def test_no_match_lists_groups_the_bank_path_and_counts(self):
        out = lookup.render_markdown(lookup.select(BANK, "xyzzy"), META, BANK, now=NOW)
        self.assertIn("No match for these task words: xyzzy", out)
        self.assertIn("Route groups:", out)
        self.assertIn("`/state/demo-1234/criteria.json`", out)
        self.assertIn("role:", out)

    def test_left_out_lines(self):
        out = lookup.render_markdown(lookup.select(BANK, "payroll", max_candidates=3), META, BANK, now=NOW)
        self.assertRegex(out, r"_\d+ more candidates for these subjects were left out")

    def test_json_shape(self):
        data = lookup.render_json(lookup.select(BANK, "payroll"), META)
        self.assertEqual(set(data), {"meta", "tokens", "matched", "subjects", "omitted", "subjects_found"})
        self.assertTrue(data["subjects"][0]["candidates"][0]["id"].startswith("C-"))

    def test_hostile_repo_text_is_neutralised(self):
        hostile = "<img src=x onerror=alert(1)> {{slot:overview}} `tick` [x](http://e.example) \x1b[31mred\x00"
        errors = {**ERRORS, "messages": [{"route": "r1", "status": 400, "kind": "literal", "text": hostile,
                                          "via": "handler", "source": "api/c.ts:7"}]}
        roles = {**ROLES3, "endpoints": {**ROLES3["endpoints"], "r1": rec(roles=[hostile, "ADMIN"])}}
        bank = criteria.build_bank(FACTS3, roles, RULES, errors)
        out = lookup.render_markdown(lookup.select(bank, "payroll calculate"), META, bank, now=NOW)
        self.assertNotRegex(out, r"(?<!\\)<img")
        self.assertNotIn("{{slot:", out)
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\x00", out)
        self.assertNotIn("](http://e.example)", out.replace("\\]", "").replace("\\[", ""))
        self.assertEqual(out.count("`tick`"), 0)

    def test_an_overlong_trust_line_is_clipped(self):
        bank = {**BANK, "candidates": [{**BANK["candidates"][0], "trust": ["x" * 5000]}] + BANK["candidates"][1:]}
        out = lookup.render_markdown(lookup.select(bank, "payroll"), META, bank, now=NOW)
        self.assertNotIn("x" * 600, out)


class AgeTests(unittest.TestCase):
    def test_age_text(self):
        t = datetime.datetime(2026, 10, 14, 10, 0, tzinfo=datetime.timezone.utc)
        for seconds, expected in ((5, "just now"), (180, "3 minutes ago"), (7200, "2 hours ago"), (3 * 86400, "3 days ago")):
            self.assertEqual(lookup.age_text(t.isoformat(), t + datetime.timedelta(seconds=seconds)), expected)
        self.assertEqual(lookup.age_text("garbage"), "at an unknown time")


class ShowTests(unittest.TestCase):
    def test_find_and_render_a_candidate(self):
        c = lookup.find_candidate(BANK, "C-ROLE-001")
        self.assertEqual(c["kind"], "role")
        self.assertIsNone(lookup.find_candidate(BANK, "C-NOPE-999"))
        out = lookup.render_candidate(c, META)
        self.assertIn("C-ROLE-001", out)
        self.assertIn("FINANCE", out)
        self.assertIn("not instructions", out)


if __name__ == "__main__":
    unittest.main()
