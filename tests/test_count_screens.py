import tempfile
import unittest
from pathlib import Path

from prd_assistant import count

VUE = """import { createRouter } from 'vue-router'
const routes = [
  {
    path: '/',
    component: Layout,
    children: [
      { path: '', name: 'root', component: { render: () => null } },
      { path: 'login', component: Login },
    ],
  },
  { path: '/:pathMatch(.*)*', component: NotFound },
]
export default createRouter({ routes })
"""

JSX = """export const A = () => (
  <Routes>
    <Route element={<Shell />}>
      <Route path="/searches" element={<Searches />} />
      <Route
        path="/teams"
        element={<Teams onGo={() => go('/x')} />}
      />
      <Route path="/admin" element={<Admin />}>
        <Route path="users" element={<Users />} />
      </Route>
    </Route>
  </Routes>
)
"""


def write(root, rel, text):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def find_line(content, needle):
    for number, line in enumerate(content.splitlines(), start=1):
        if needle in line:
            return number
    raise AssertionError(needle)


class ScreenCounterTests(unittest.TestCase):
    def test_vue_object_routes_count_leaves_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "src/router/index.ts", VUE)
            hits = count.independent_screens(tmp, {"vue-router"})
        expected = {("src/router/index.ts", find_line(VUE, "name: 'root'")),
                    ("src/router/index.ts", find_line(VUE, "path: 'login'")),
                    ("src/router/index.ts", find_line(VUE, "pathMatch"))}
        self.assertEqual(hits, expected)

    def test_jsx_routes_count_self_closing_routes_with_a_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "src/App.tsx", JSX)
            hits = count.independent_screens(tmp, {"react-router"})
        expected = {("src/App.tsx", find_line(JSX, 'path="/searches"')),
                    ("src/App.tsx", find_line(JSX, 'path="/teams"') - 1),
                    ("src/App.tsx", find_line(JSX, 'path="users"'))}
        self.assertEqual(hits, expected)

    def test_no_router_framework_means_no_screens(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "src/router/index.ts", VUE)
            self.assertEqual(count.independent_screens(tmp, {"fastapi"}), set())

    def test_test_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "src/__tests__/mount.ts", VUE)
            self.assertEqual(count.independent_screens(tmp, {"vue-router"}), set())

    def test_plain_files_without_router_markers_are_not_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "src/types.ts", "const x = { path: '/not-a-route' }\n")
            self.assertEqual(count.independent_screens(tmp, {"vue-router"}), set())


if __name__ == "__main__":
    unittest.main()
