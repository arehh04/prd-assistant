import os
import tempfile
import unittest
from pathlib import Path

from prd_assistant import ui_text


def write(root, rel, text=""):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


VITE = """import { fileURLToPath, URL } from 'node:url'
export default defineConfig({
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
})
"""
TSCONFIG = """{
  // comments are allowed in tsconfig
  "compilerOptions": { "paths": { "@/*": ["./src/*"], "~lib/*": ["./lib/*"] } }
}
"""


class AliasTests(unittest.TestCase):
    def test_vite_and_tsconfig_aliases_are_read_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "web/vite.config.ts", VITE)
            write(tmp, "web/tsconfig.app.json", TSCONFIG)
            aliases = ui_text.load_aliases(tmp, "web/src")
            root = Path(os.path.abspath(tmp))
            self.assertIn(("@", root / "web" / "src"), aliases)
            self.assertIn(("~lib", root / "web" / "lib"), aliases)
            self.assertEqual(len([a for a in aliases if a[0] == "@"]), 1)

    def test_no_config_means_no_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "web/src/a.ts")
            self.assertEqual(ui_text.load_aliases(tmp, "web/src"), [])


class ResolveModuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        write(self.root, "web/src/views/A.vue")
        write(self.root, "web/src/components/index.ts")
        write(self.root, "web/src/pages/Home.tsx")
        write(self.root, "outside.tsx")
        self.aliases = [("@", Path(os.path.abspath(self.root)) / "web" / "src")]

    def resolve(self, spec, base="web/src/views"):
        return ui_text.resolve_module(spec, base, self.aliases, self.root)

    def test_relative_alias_and_extension_guessing(self):
        self.assertEqual(self.resolve("../components"), "web/src/components/index.ts")
        self.assertEqual(self.resolve("@/views/A.vue"), "web/src/views/A.vue")
        self.assertEqual(self.resolve("../pages/Home"), "web/src/pages/Home.tsx")

    def test_packages_missing_files_and_escapes_are_none(self):
        self.assertIsNone(self.resolve("react"))
        self.assertIsNone(self.resolve("@/views/Nope.vue"))
        self.assertIsNone(self.resolve("../../../../outside"))

    def test_symlinks_are_not_followed(self):
        os.symlink(Path(self.root) / "outside.tsx", Path(self.root) / "web/src/views/Link.tsx")
        self.assertIsNone(self.resolve("./Link"))


class ParseImportsTests(unittest.TestCase):
    SRC = """import Home from './pages/Home'
import { A, B as C } from "@/x"
import type { Props } from './types'
import Def, { Named } from './def'
import * as ns from './ns'
import './side-effect.css'
const Lazy = lazy(() => import('./pages/Lazy'))
const Other = React.lazy(() => import("./pages/Other"))
"""

    def test_names_and_specs(self):
        names, specs = ui_text.parse_imports(self.SRC)
        self.assertEqual(names["Home"], "./pages/Home")
        self.assertEqual((names["A"], names["C"]), ("@/x", "@/x"))
        self.assertEqual(names["Def"], "./def")
        self.assertEqual(names["Named"], "./def")
        self.assertEqual(names["Lazy"], "./pages/Lazy")
        self.assertEqual(names["Other"], "./pages/Other")
        self.assertNotIn("ns", names)
        for spec in ("./pages/Home", "./types", "./side-effect.css", "./pages/Lazy", "./ns"):
            self.assertIn(spec, specs)


if __name__ == "__main__":
    unittest.main()
