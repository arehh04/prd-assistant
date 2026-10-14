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

    def test_the_routers_own_expression_beats_a_wrong_codegraph_link(self):
        # CodeGraph links a nested Vue route to its parent layout; the route object itself names the real view
        aliases = [("@", Path(os.path.abspath(self.root)) / "web" / "src")]
        s = self.screen(VUE_ROUTER, "path: 'branches'", "/admin/branches", "web/src/router/index.ts",
                        component={"name": "AdminLayout", "file": "web/src/layouts/AdminLayout.vue", "line": 1})
        r = ui_text.resolve_component(s, ui_text.Source(VUE_ROUTER), aliases, self.root)
        self.assertEqual(r["component_file"], "web/src/views/admin/branches/BranchesView.vue")

    def test_codegraph_link_is_the_fallback_when_the_expression_gives_nothing(self):
        text = 'export const routes = [\n  { path: "/dyn", element: renderPage() },\n];\n'
        s = {"id": "s", "path": "/dyn", "file": "src/router.tsx", "line": 2,
             "component": {"name": "Other", "file": "src/pages/NewSearchPage.tsx", "line": 3}}
        r = ui_text.resolve_component(s, ui_text.Source(text), [], self.root)
        self.assertEqual((r["status"], r["component_file"]), ("resolved", "src/pages/NewSearchPage.tsx"))

    LOCAL_ROUTER = '''export function ViewerHomePage() {
  return <div>Hello viewer</div>;
}

const AdminPage = () => {
  return <div>Admin</div>;
};

export const App = () => (
  <Routes>
    <Route path="/viewer" element={<ViewerHomePage />} />
    <Route path="/admin" element={<AdminPage />} />
    <Route path="/nope" element={<NotDeclared />} />
  </Routes>
);
'''

    def test_components_declared_in_the_router_file_resolve_to_it_with_a_span(self):
        src = ui_text.Source(self.LOCAL_ROUTER)

        def resolve(path):
            s = {"id": "s", "path": path, "file": "src/App.tsx", "line": line_of(self.LOCAL_ROUTER, f'path="{path}"')}
            return ui_text.resolve_component(s, src, [], self.root)

        viewer, admin, nope = resolve("/viewer"), resolve("/admin"), resolve("/nope")
        self.assertEqual((viewer["status"], viewer["component_file"]), ("resolved", "src/App.tsx"))
        self.assertEqual(viewer["candidates"][0]["span"], [1, 3])
        self.assertEqual(admin["candidates"][0]["span"], [5, 7])
        self.assertEqual(nope["status"], "unresolved")

    def test_a_line_outside_the_file_is_unresolved_not_a_crash(self):
        s = {"id": "s", "path": "/x", "file": "src/router.tsx", "line": 9999}
        r = ui_text.resolve_component(s, ui_text.Source(OBJECT_ROUTER), [], self.root)
        self.assertEqual(r["status"], "unresolved")


if __name__ == "__main__":
    unittest.main()
