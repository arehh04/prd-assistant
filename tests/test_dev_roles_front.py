import tempfile
import unittest
from pathlib import Path

from prd_assistant.dev import joins, roles_front, source

NAV = '''const MANAGEMENT: readonly UserRole[] = ["MANAGER", "ADMIN"];
const EVERYONE: readonly UserRole[] = ["WORKER", "MANAGER", "ADMIN"];
const NAV_ITEMS = [
  { label: "My Shift", to: "/me", icon: "badge", roles: EVERYONE },
  { label: "Inbound", to: "/inbound", roles: MANAGEMENT, description: "Suppliers { and } orders" },
  { roles: MANAGEMENT, to: "/payroll", label: "Payroll" },
  { label: "Odd", to: "/odd", roles: SOMETHING_ELSE },
];
'''
VUE_ROUTER = '''const ADMIN_ROLES = ['super_admin', 'branch_admin']
const routes = [
  {
    path: 'branches',
    component: () => import('@/views/BranchesView.vue'),
    meta: { title: 'Branches', roles: ADMIN_ROLES },
  },
  { path: 'open', component: () => import('@/views/Open.vue'), meta: { title: 'Open' } },
]
'''


def write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class FrontRolesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        write(self.root, "web/src/lib/navigation.ts", NAV)
        write(self.root, "web/src/router/index.ts", VUE_ROUTER)
        self.index = source.ConstIndex(self.root)
        self.entries = roles_front.nav_tables(self.root, self.index)

    def screen(self, path, file="web/src/app/router.tsx", line=1):
        return {"id": "s", "path": path, "file": file, "line": line}

    def test_nav_table_reads_both_key_orders_and_ignores_braces_in_text(self):
        by_path = {e["path"]: e["roles"] for e in self.entries}
        self.assertEqual(by_path["/me"], ["WORKER", "MANAGER", "ADMIN"])
        self.assertEqual(by_path["/inbound"], ["MANAGER", "ADMIN"])
        self.assertEqual(by_path["/payroll"], ["MANAGER", "ADMIN"])
        self.assertIsNone(by_path["/odd"])

    def test_longest_prefix_wins_and_unmatched_is_not_read(self):
        r = roles_front.screen_roles(self.screen("/inbound/orders/:id"), self.entries, self.root, self.index)
        self.assertEqual((r["status"], r["roles"]), ("read", ["MANAGER", "ADMIN"]))
        self.assertTrue(r["source"].startswith("web/src/lib/navigation.ts:"))
        none = roles_front.screen_roles(self.screen("/elsewhere"), self.entries, self.root, self.index)
        self.assertEqual(none["status"], "not_read")

    def test_unresolved_table_roles_are_not_read(self):
        r = roles_front.screen_roles(self.screen("/odd"), self.entries, self.root, self.index)
        self.assertEqual((r["status"], r["roles"]), ("not_read", None))

    def test_root_path_only_matches_itself(self):
        entries = [{"path": "/", "roles": ["ADMIN"], "via": [], "file": "n.ts", "line": 1}]
        self.assertEqual(roles_front.screen_roles(self.screen("/"), entries, self.root, self.index)["roles"], ["ADMIN"])
        self.assertEqual(roles_front.screen_roles(self.screen("/x"), entries, self.root, self.index)["status"], "not_read")

    def test_vue_meta_roles_from_the_route_object(self):
        line = next(i for i, l in enumerate(VUE_ROUTER.splitlines(), 1) if "path: 'branches'" in l)
        r = roles_front.screen_roles(self.screen("/admin/branches", "web/src/router/index.ts", line),
                                     [], self.root, self.index)
        self.assertEqual((r["status"], r["roles"]), ("read", ["super_admin", "branch_admin"]))
        open_line = next(i for i, l in enumerate(VUE_ROUTER.splitlines(), 1) if "path: 'open'" in l)
        o = roles_front.screen_roles(self.screen("/admin/open", "web/src/router/index.ts", open_line),
                                     [], self.root, self.index)
        self.assertEqual(o["status"], "not_read")


class JoinTests(unittest.TestCase):
    def test_screen_joins_routes_called_from_its_evidence_files(self):
        ui = {"screens": {"s1": {"files": ["web/a.tsx", "web/api.ts"]}, "s2": {"files": ["web/b.tsx"]}}}
        links_result = {"routes": {"r1": {"frontend": [{"file": "web/api.ts", "line": 3}]},
                                   "r2": {"frontend": []}}}
        self.assertEqual(joins.screen_endpoints(ui, links_result), {"s1": ["r1"], "s2": []})


    def test_calls_made_two_imports_away_still_join_the_screen(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "web/Page.tsx", 'import { usePay } from "./usePay";\nexport const Page = () => null;\n')
            write(tmp, "web/usePay.ts", 'import { fetchPay } from "./pay.api";\nexport const usePay = () => fetchPay();\n')
            write(tmp, "web/pay.api.ts", 'import { deep } from "./deep";\nexport const fetchPay = () => fetch("/pay");\n')
            write(tmp, "web/deep.ts", 'import { far } from "./far";\nexport const deep = 1;\n')
            write(tmp, "web/far.ts", 'export const far = 1;\n')
            ui = {"screens": {"s1": {"files": ["web/Page.tsx", "web/usePay.ts"]}}}
            near = {"routes": {"r1": {"frontend": [{"file": "web/pay.api.ts", "line": 2}]}}}
            too_far = {"routes": {"r1": {"frontend": [{"file": "web/far.ts", "line": 1}]}}}
            self.assertEqual(joins.screen_endpoints(ui, near), {"s1": []})   # without a repo root only evidence files count
            self.assertEqual(joins.screen_endpoints(ui, near, tmp), {"s1": ["r1"]})
            self.assertEqual(joins.screen_endpoints(ui, too_far, tmp), {"s1": []})   # more than two extra hops is out of reach


if __name__ == "__main__":
    unittest.main()
