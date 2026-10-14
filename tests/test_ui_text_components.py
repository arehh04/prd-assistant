import os
import tempfile
import unittest
from pathlib import Path

from prd_assistant import ui_text

JSX_ROUTER = '''import { lazy, Suspense } from "react";
import ViewerHomePage from "./pages/ViewerHomePage";
const NewSearchPage = lazy(() => import("./pages/NewSearchPage"));

export const A = () => (
  <Routes>
    <Route
      path="/searches"
      element={
        isViewer ? (
          <ViewerHomePage />
        ) : (
          <Suspense fallback={<PageLoader />}>
            <NewSearchPage isAdmin={isAdmin} />
          </Suspense>
        )
      }
    />
    <Route path="/ghost" element={<Missing />} />
  </Routes>
);
'''

OBJECT_ROUTER = '''import { MyShiftPage } from "../features/staff/pages/MyShiftPage";
export const routes = [
  { path: "/me", element: <MyShiftPage /> },
  { path: "/lazy", Component: MyShiftPage },
];
'''

VUE_ROUTER = '''const routes = [
  {
    path: 'branches',
    name: 'admin-branches',
    component: () => import('@/views/admin/branches/BranchesView.vue'),
    // Branch admins see their own branches read-only.
    meta: { title: 'Branches', roles: ADMIN_ROLES },
  },
]
'''


def write(root, rel, text=""):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def line_of(text, needle):
    for number, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return number
    raise AssertionError(needle)


class ComponentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        for rel in ("src/pages/ViewerHomePage.tsx", "src/pages/NewSearchPage.tsx",
                    "src/features/staff/pages/MyShiftPage.tsx", "web/src/views/admin/branches/BranchesView.vue"):
            write(self.root, rel, "x")

    def screen(self, text, needle, path, file, **extra):
        return dict({"id": "s", "path": path, "file": file, "line": line_of(text, needle)}, **extra)

    def test_jsx_ternary_with_wrappers_gives_conditional_candidates(self):
        # a JSX route is recorded on the line of its "<Route" tag, one line above its path attribute
        s = {"id": "s", "path": "/searches", "file": "src/router.tsx",
             "line": line_of(JSX_ROUTER, 'path="/searches"') - 1}
        r = ui_text.resolve_component(s, ui_text.Source(JSX_ROUTER), [], self.root)
        self.assertEqual(r["status"], "conditional")
        self.assertEqual([c["name"] for c in r["candidates"]], ["ViewerHomePage", "NewSearchPage"])
        self.assertEqual([c["file"] for c in r["candidates"]],
                         ["src/pages/ViewerHomePage.tsx", "src/pages/NewSearchPage.tsx"])
        self.assertEqual(r["component_file"], "src/pages/ViewerHomePage.tsx")  # fallback loader is not a candidate

    def test_unknown_component_is_unresolved_not_an_error(self):
        s = self.screen(JSX_ROUTER, 'path="/ghost"', "/ghost", "src/router.tsx")
        r = ui_text.resolve_component(s, ui_text.Source(JSX_ROUTER), [], self.root)
        self.assertEqual(r["status"], "unresolved")
        self.assertEqual(r["candidates"], [{"name": "Missing", "file": None}])
        self.assertIsNone(r["component_file"])

    def test_object_routes_with_element_and_Component_keys(self):
        src = ui_text.Source(OBJECT_ROUTER)
        me = ui_text.resolve_component(self.screen(OBJECT_ROUTER, 'path: "/me"', "/me", "src/app/router.tsx"),
                                       src, [], self.root)
        self.assertEqual((me["status"], me["component_file"]), ("resolved", "src/features/staff/pages/MyShiftPage.tsx"))
        lazy = ui_text.resolve_component(self.screen(OBJECT_ROUTER, 'path: "/lazy"', "/lazy", "src/app/router.tsx"),
                                         src, [], self.root)
        self.assertEqual(lazy["component_file"], "src/features/staff/pages/MyShiftPage.tsx")

    def test_vue_import_with_alias_and_router_title(self):
        aliases = [("@", Path(os.path.abspath(self.root)) / "web" / "src")]
        s = self.screen(VUE_ROUTER, "path: 'branches'", "/admin/branches", "web/src/router/index.ts")
        r = ui_text.resolve_component(s, ui_text.Source(VUE_ROUTER), aliases, self.root)
        self.assertEqual((r["status"], r["component_file"]), ("resolved", "web/src/views/admin/branches/BranchesView.vue"))
        self.assertEqual(r["title"], {"text": "Branches", "line": line_of(VUE_ROUTER, "meta:")})

    def test_codegraph_link_wins(self):
        s = self.screen(OBJECT_ROUTER, 'path: "/me"', "/me", "src/app/router.tsx",
                        component={"name": "Other", "file": "src/pages/NewSearchPage.tsx", "line": 3})
        r = ui_text.resolve_component(s, ui_text.Source(OBJECT_ROUTER), [], self.root)
        self.assertEqual((r["status"], r["component_file"]), ("resolved", "src/pages/NewSearchPage.tsx"))

    def test_a_line_outside_the_file_is_unresolved_not_a_crash(self):
        s = {"id": "s", "path": "/x", "file": "src/router.tsx", "line": 9999}
        r = ui_text.resolve_component(s, ui_text.Source(OBJECT_ROUTER), [], self.root)
        self.assertEqual(r["status"], "unresolved")


if __name__ == "__main__":
    unittest.main()
