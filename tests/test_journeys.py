import unittest

from prd_assistant import journeys

UI = {
    "shared_files": [{"file": "web/Layout.tsx", "used_by": 4}],
    "shared_items": [{"kind": "button", "text": "Home menu", "file": "web/Layout.tsx", "line": 3}],
    "screens": {
        "s1": {"path": "/login", "files": ["web/pages/LoginPage.tsx"],
               "items": [{"kind": "button", "text": "Sign in", "file": "web/pages/LoginPage.tsx", "line": 12}]},
        "s2": {"path": "/teams", "files": ["web/pages/TeamsPage.tsx", "web/Card.tsx"], "items": []},
        "s3": {"path": "/home", "files": ["web/pages/HomePage.tsx", "web/Card.tsx"], "items": []},
        "s4": {"path": "/orphan", "files": [], "items": []},
    },
}


def nav(i, from_file, to_id, line):
    return {"id": f"n{i}", "from_file": from_file, "to_id": to_id, "line": line,
            "source": f"{from_file}:{line}", "from_symbol": "x"}


class JourneyTests(unittest.TestCase):
    def test_edges_shared_navigation_and_labels(self):
        facts = {"navigation": [
            nav(1, "web/pages/LoginPage.tsx", "s2", 12),   # login -> teams, label from the same line
            nav(2, "web/Layout.tsx", "s3", 3),             # shared menu -> home
            nav(3, "web/Card.tsx", "s1", 5),               # Card is used by two screens: both get the edge
            nav(4, "web/unknown.tsx", "s2", 8),            # belongs to no screen: shared navigation
            nav(5, "web/pages/TeamsPage.tsx", "s2", 9),    # self navigation is ignored
        ]}
        result = journeys.build(facts, UI)
        edges = {(e["from_screen"], e["to_screen"]): e for e in result["edges"]}
        self.assertEqual(set(edges), {("s1", "s2"), ("s2", "s1"), ("s3", "s1")})
        self.assertEqual(edges[("s1", "s2")]["label"], "Sign in")
        self.assertEqual(edges[("s1", "s2")]["via"], "web/pages/LoginPage.tsx:12")
        self.assertEqual({(s["to_screen"], s["from_file"]) for s in result["shared"]},
                         {("s3", "web/Layout.tsx"), ("s2", "web/unknown.tsx")})
        self.assertEqual([s for s in result["shared"] if s["to_screen"] == "s3"][0]["label"], "Home menu")

    def test_per_screen_summary(self):
        facts = {"navigation": [nav(1, "web/pages/LoginPage.tsx", "s2", 12), nav(2, "web/Layout.tsx", "s3", 3)]}
        screens = journeys.build(facts, UI)["screens"]
        self.assertEqual(screens["s1"]["leads_to"], ["s2"])
        self.assertEqual(screens["s2"]["reached_from"], ["s1"])
        self.assertTrue(screens["s3"]["shared_nav"])
        self.assertEqual(screens["s4"], {"reached_from": [], "leads_to": [], "shared_nav": False})

    def test_no_navigation_is_fine(self):
        result = journeys.build({"navigation": []}, UI)
        self.assertEqual((result["edges"], result["shared"]), ([], []))


if __name__ == "__main__":
    unittest.main()
