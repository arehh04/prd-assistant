import tempfile
import unittest
from pathlib import Path
from unittest import mock

from prd_assistant import ui_text

ROUTER = '''import { LoginPage } from "../pages/LoginPage";
import { TeamsPage } from "../pages/TeamsPage";
import { HomePage } from "../pages/HomePage";
import { AboutPage } from "../pages/AboutPage";

export const routes = [
  { path: "/login", element: <LoginPage /> },
  { path: "/teams", element: <TeamsPage /> },
  { path: "/home", element: <HomePage /> },
  { path: "/about", element: <AboutPage /> },
  { path: "/ghost", element: <Ghost /> },
];
'''


def page(name, title, card=False):
    card_import = 'import { Card } from "../components/Card";\n' if card else ""
    card_use = "<Card />\n      {toast.error(\"Could not load teams\")}" if card else ""
    return (f'import {{ Layout }} from "../components/Layout";\n{card_import}\n'
            f'export function {name}() {{\n  return (\n    <Layout>\n      <h1>{title}</h1>\n      {card_use}\n    </Layout>\n  );\n}}\n')


LAYOUT = 'export function Layout({ children }) {\n  return (<div><nav><a href="/home">Home menu</a></nav>{children}</div>);\n}\n'
CARD = 'export function Card() {\n  return <p>Card text</p>;\n}\n'


def write(root, rel, text):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def line_of(text, needle):
    for number, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return number
    raise AssertionError(needle)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        write(self.root, "web/package.json", '{"dependencies": {"react-router-dom": "7"}}')
        write(self.root, "web/src/app/router.tsx", ROUTER)
        for name, title, card in (("LoginPage", "Sign in", False), ("TeamsPage", "Teams", True),
                                  ("HomePage", "Home", False), ("AboutPage", "About", False)):
            write(self.root, f"web/src/pages/{name}.tsx", page(name, title, card))
        write(self.root, "web/src/components/Layout.tsx", LAYOUT)
        write(self.root, "web/src/components/Card.tsx", CARD)
        self.facts = {"screens": [
            {"id": f"s{i}", "path": p, "file": "web/src/app/router.tsx", "line": line_of(ROUTER, f'path: "{p}"')}
            for i, p in enumerate(["/login", "/teams", "/home", "/about", "/ghost"], start=1)]}
        self.ui = ui_text.build(self.root, self.facts)

    def test_statuses_and_unresolved_screen(self):
        statuses = {sid: s["status"] for sid, s in self.ui["screens"].items()}
        self.assertEqual(statuses, {"s1": "resolved", "s2": "resolved", "s3": "resolved", "s4": "resolved",
                                    "s5": "unresolved"})
        self.assertEqual(self.ui["screens"]["s5"]["items"], [])
        self.assertEqual(self.ui["screens"]["s5"]["candidates"], [{"name": "Ghost", "file": None}])

    def test_evidence_files_are_component_plus_direct_imports_minus_shared(self):
        self.assertEqual(self.ui["screens"]["s1"]["files"], ["web/src/pages/LoginPage.tsx"])
        self.assertEqual(self.ui["screens"]["s2"]["files"], ["web/src/pages/TeamsPage.tsx", "web/src/components/Card.tsx"])

    def test_shared_layout_is_listed_once_and_not_repeated(self):
        self.assertEqual(self.ui["shared_files"], [{"file": "web/src/components/Layout.tsx", "used_by": 4}])
        self.assertIn(("button", "Home menu"), {(i["kind"], i["text"]) for i in self.ui["shared_items"]})
        for sid in ("s1", "s2", "s3", "s4"):
            self.assertNotIn("Home menu", [i["text"] for i in self.ui["screens"][sid]["items"]])

    def test_items_for_a_screen(self):
        pairs = {(i["kind"], i["text"]) for i in self.ui["screens"]["s2"]["items"]}
        self.assertLessEqual({("heading", "Teams"), ("text", "Card text"), ("message", "Could not load teams")}, pairs)

    def test_i18n_not_detected_here_and_detected_when_a_library_is_listed(self):
        self.assertFalse(self.ui["i18n"]["detected"])
        write(self.root, "web/package.json", '{"dependencies": {"react-router-dom": "7", "react-i18next": "14"}}')
        self.assertTrue(ui_text.build(self.root, self.facts)["i18n"]["detected"])

    def test_truncation_is_recorded(self):
        with mock.patch("prd_assistant.ui_text.MAX_ITEMS", 1):
            ui = ui_text.build(self.root, self.facts)
        self.assertTrue(ui["screens"]["s2"]["truncated"])
        self.assertEqual(len(ui["screens"]["s2"]["items"]), 1)

    def test_two_screens_never_produce_shared_files(self):
        facts = {"screens": self.facts["screens"][:2]}
        ui = ui_text.build(self.root, facts)
        self.assertEqual(ui["shared_files"], [])
        self.assertIn("Home menu", [i["text"] for i in ui["screens"]["s1"]["items"]])

    def test_skipped_candidates_are_counted_and_sampled(self):
        write(self.root, "web/src/pages/LoginPage.tsx",
              page("LoginPage", "Sign in") + 'const hint = "A sentence the extractor does not take";\n')
        ui = ui_text.build(self.root, self.facts)
        self.assertGreaterEqual(ui["skipped_candidates"]["count"], 1)
        self.assertTrue(any("A sentence" in s["text"] for s in ui["skipped_candidates"]["sample"]))

    def test_missing_router_file_is_unresolved_not_a_crash(self):
        facts = {"screens": [{"id": "s9", "path": "/x", "file": "web/src/app/gone.tsx", "line": 3}]}
        ui = ui_text.build(self.root, facts)
        self.assertEqual(ui["screens"]["s9"]["status"], "unresolved")


class LocalComponentTests(unittest.TestCase):
    APP = '''function OnePage() {
  return <h1>One</h1>;
}
function TwoPage() {
  return <h1>Two</h1>;
}
export const routes = [
  { path: "/one", element: <OnePage /> },
  { path: "/two", element: <TwoPage /> },
];
'''

    def test_a_component_declared_in_the_router_only_contributes_its_own_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "web/package.json", '{"dependencies": {"react-router-dom": "7"}}')
            write(tmp, "web/src/App.tsx", self.APP)
            facts = {"screens": [{"id": "s1", "path": "/one", "file": "web/src/App.tsx", "line": line_of(self.APP, 'path: "/one"')},
                                 {"id": "s2", "path": "/two", "file": "web/src/App.tsx", "line": line_of(self.APP, 'path: "/two"')}]}
            ui = ui_text.build(tmp, facts)
        self.assertEqual([i["text"] for i in ui["screens"]["s1"]["items"]], ["One"])
        self.assertEqual([i["text"] for i in ui["screens"]["s2"]["items"]], ["Two"])
        self.assertEqual(ui["screens"]["s1"]["files"], ["web/src/App.tsx"])


if __name__ == "__main__":
    unittest.main()
