import re
import unittest

from prd_assistant import guide

SLICE1 = {"verdict": "PASS", "checks": []}


def item(kind, text, file, line):
    return {"kind": kind, "text": text, "file": file, "line": line}


def ui_data():
    return {
        "schema": 1, "i18n": {"detected": False, "evidence": []},
        "shared_files": [{"file": "web/Layout.tsx", "used_by": 3}],
        "shared_items": [item("button", "Home menu", "web/Layout.tsx", 3)],
        "screens": {
            "s1": {"path": "/login", "status": "resolved", "component_file": "web/Login.tsx", "candidates": [],
                   "files": ["web/Login.tsx"], "truncated": False,
                   "items": [item("heading", "Sign in", "web/Login.tsx", 5),
                             item("button", "Sign in now", "web/Login.tsx", 9),
                             item("message", "Wrong password", "web/Login.tsx", 12)]},
            "s2": {"path": "/teams", "status": "conditional", "component_file": "web/Teams.tsx",
                   "candidates": [{"name": "TeamsPage", "file": "web/Teams.tsx"}, {"name": "ViewerPage", "file": "web/Viewer.tsx"}],
                   "files": ["web/Teams.tsx"], "truncated": True,
                   "items": [item("heading", "Teams", "web/Teams.tsx", 4), item("label", "Team name", "web/Teams.tsx", 8)]},
            "s3": {"path": "/ghost", "status": "unresolved", "component_file": None,
                   "candidates": [{"name": "Ghost", "file": None}], "files": [], "truncated": False, "items": []},
            "s4": {"path": "/bare", "status": "resolved", "component_file": "web/Bare.tsx", "candidates": [],
                   "files": ["web/Bare.tsx"], "truncated": False, "items": []},
        },
        "skipped_candidates": {"count": 2, "sample": [{"file": "web/Login.tsx", "line": 20, "text": "A hidden sentence"}]},
    }


def jr_data():
    return {"schema": 1,
            "edges": [{"from_screen": "s1", "to_screen": "s2", "via": "web/Login.tsx:9", "label": "Sign in now"}],
            "shared": [{"to_screen": "s1", "via": "web/Layout.tsx:3", "from_file": "web/Layout.tsx", "label": "Home menu"}],
            "screens": {"s1": {"reached_from": [], "leads_to": ["s2"], "shared_nav": True},
                        "s2": {"reached_from": ["s1"], "leads_to": [], "shared_nav": False},
                        "s3": {"reached_from": [], "leads_to": [], "shared_nav": False},
                        "s4": {"reached_from": [], "leads_to": [], "shared_nav": False}}}


def facts():
    return {"screens": [{"id": "s1", "path": "/login"}, {"id": "s2", "path": "/teams"},
                        {"id": "s3", "path": "/ghost"}, {"id": "s4", "path": "/bare"}],
            "meta": {"repo": "/r"}}


def build(ui=None, jr=None):
    ui, jr = ui or ui_data(), jr or jr_data()
    gate = guide.guide_gate(ui, jr)
    return guide.build(facts(), SLICE1, ui, jr, gate, "myrepo", "2026-10-14") + (gate,)


class GateTests(unittest.TestCase):
    def check(self, gate, name):
        return next(c for c in gate["checks"] if c["name"] == name)

    def test_fixture_gate(self):
        gate = guide.guide_gate(ui_data(), jr_data())
        self.assertEqual(self.check(gate, "component_resolution")["status"], "WARN")   # 3 of 4
        self.assertEqual(self.check(gate, "component_resolution")["detail"]["ratio"], 0.75)
        self.assertEqual(self.check(gate, "text_coverage")["status"], "WARN")          # 2 of 3 resolved have text
        self.assertEqual(self.check(gate, "i18n")["status"], "PASS")
        self.assertEqual(self.check(gate, "truncation")["detail"]["screens"], ["s2"])
        self.assertEqual(gate["verdict"], "WARN")

    def test_thresholds(self):
        ui = ui_data()
        for sid in ("s1", "s2", "s4"):
            ui["screens"][sid]["status"] = "unresolved"
        self.assertEqual(guide.guide_gate(ui, jr_data())["verdict"], "FAIL")     # 0 of 4 resolved
        ui = ui_data()
        ui["screens"]["s3"]["status"] = "resolved"
        ui["screens"]["s3"]["component_file"] = "web/Ghost.tsx"
        self.assertEqual(self.check(guide.guide_gate(ui, jr_data()), "component_resolution")["status"], "PASS")

    def test_i18n_and_unsupported_tech_warn(self):
        ui = ui_data()
        ui["i18n"] = {"detected": True, "evidence": ["package.json lists vue-i18n"]}
        ui["screens"]["s1"]["component_file"] = "web/Login.ts"
        gate = guide.guide_gate(ui, jr_data())
        self.assertEqual(self.check(gate, "i18n")["status"], "WARN")
        self.assertEqual(self.check(gate, "unsupported_tech")["status"], "WARN")

    def test_a_repo_with_screens_but_nothing_resolved_fails(self):
        ui = ui_data()
        ui["screens"] = {k: dict(v, status="unresolved", component_file=None, items=[]) for k, v in ui["screens"].items()}
        self.assertEqual(guide.guide_gate(ui, jr_data())["verdict"], "FAIL")


class ScreenIdTests(unittest.TestCase):
    def test_ids_sorted_by_path_and_widened(self):
        screens = [{"id": "a", "path": "/b"}, {"id": "b", "path": "/a"}]
        self.assertEqual(guide.screen_ids(screens), {"b": "S01", "a": "S02"})
        many = [{"id": f"x{i}", "path": f"/p{i:03d}"} for i in range(120)]
        ids = guide.screen_ids(many)
        self.assertEqual((ids["x0"], ids["x119"]), ("S001", "S120"))


class ScaffoldTests(unittest.TestCase):
    def test_placeholders_match_template_keys(self):
        text, template, _ = build()
        placeholders = re.findall(r"\{\{slot:([^}]+)\}\}", text)
        self.assertEqual(sorted(placeholders), sorted(s["key"] for s in template["slots"]))
        # ids by sorted path: bare S01, ghost S02, login S03, teams S04; bare has no text and ghost is unresolved
        self.assertEqual(sorted(placeholders), ["overview", "screen.S03", "screen.S04"])

    def test_verbatim_tables_with_sources(self):
        text, _, _ = build()
        self.assertIn("| heading | Sign in | `web/Login.tsx:5` |", text)
        self.assertIn("| button | Sign in now | `web/Login.tsx:9` |", text)
        self.assertIn("| Wrong password | `web/Login.tsx:12` |", text)

    def test_conditional_truncated_and_shared_notes(self):
        text, _, _ = build()
        self.assertIn("TeamsPage", text)
        self.assertIn("ViewerPage", text)
        self.assertIn("evidence was capped", text)
        self.assertIn("| button | Home menu | `web/Layout.tsx:3` |", text)

    def test_journeys_and_gaps(self):
        text, _, _ = build()
        self.assertIn("S04 `/teams`", text)
        self.assertIn("shared menu", text)
        self.assertIn("`/ghost`", text)
        self.assertIn("component not found", text)
        self.assertIn("no text of its own", text)
        self.assertIn("Who may use each screen: NEEDS HUMAN INPUT", text)
        self.assertIn("translation files", text)

    def test_if_something_goes_wrong_lists_messages_with_their_screen(self):
        text, _, _ = build()
        section = text.split("## 5. If something goes wrong")[1].split("## 6.")[0]
        self.assertIn("Wrong password", section)
        self.assertIn("`/login`", section)

    def test_slot_template_shape(self):
        _, template, _ = build()
        slots = {s["key"]: s for s in template["slots"]}
        login = slots["screen.S03"]
        self.assertEqual((login["max_words"], login["audience"]), (60, "client"))
        self.assertIn("api", login["banned_terms"])
        self.assertIn("apis", login["banned_terms"])
        self.assertIn({"file": "web/Login.tsx", "from_line": 9, "to_line": 9}, login["allowed_evidence"])
        self.assertIn("button: Sign in now", [e["text"] for e in login["evidence_text"]])
        self.assertNotIn("message: Wrong password", [e["text"] for e in login["evidence_text"]])  # messages are not slot evidence
        self.assertEqual(slots["overview"]["max_words"], 80)

    def test_hostile_ui_text_cannot_inject(self):
        ui = ui_data()
        ui["screens"]["s1"]["items"].append(item("label", "x {{slot:overview}} | `y`\n## Injected", "web/Login.tsx", 14))
        ui["screens"]["s1"]["items"].append(item("message", "boom {{slot:evil}}", "web/Login.tsx", 15))
        text, template, _ = build(ui=ui)
        placeholders = re.findall(r"\{\{slot:([^}]+)\}\}", text)
        self.assertEqual(sorted(placeholders), sorted(s["key"] for s in template["slots"]))
        self.assertNotIn("\n## Injected", text)

    def test_repo_with_no_resolved_text_still_builds(self):
        ui = ui_data()
        for v in ui["screens"].values():
            v["items"] = []
        text, template, _ = build(ui=ui)
        self.assertEqual(template["slots"], [])
        self.assertNotIn("{{slot:", text)


class GateMarkdownTests(unittest.TestCase):
    def test_render(self):
        md = guide.render_gate_md(guide.guide_gate(ui_data(), jr_data()))
        self.assertTrue(md.startswith("# Guide gate: WARN"))
        self.assertIn("component_resolution", md)


if __name__ == "__main__":
    unittest.main()
