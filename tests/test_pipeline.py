import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from prd_assistant import pipeline
from tests.helpers import make_index, node, sha256_file

SRC = "router = APIRouter()\n\n@router.get('/a')\ndef a(): ...\n\n@router.post('/b')\ndef b(): ...\n"


def build_repo(root, index_lines=(3, 6)):
    root = Path(root)
    (root / "app").mkdir(parents=True)
    (root / "requirements.txt").write_text("fastapi\n")
    api = root / "app/api.py"
    api.write_text(SRC)
    nodes, edges = [], []
    for line, method, fn in ((3, "GET", "a"), (6, "POST", "b")):
        if line in index_lines:
            rid = f"route:app/api.py:{line}:{method}:"
            nodes += [node(rid, "route", f"{method} /{fn}", "app/api.py", line),
                      node(f"fn:{fn}", "function", fn, "app/api.py", line + 1)]
            edges.append((rid, f"fn:{fn}", "references", line, None))
    make_index(root, nodes=nodes, edges=edges, files=[("app/api.py", sha256_file(api), 0)])


class PipelineTests(unittest.TestCase):
    def test_end_to_end_pass_and_outputs_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "my repo"  # a space in the path on purpose
            repo.mkdir()
            build_repo(repo)
            facts, result = pipeline.run(repo)
            self.assertEqual(result["verdict"], "PASS")
            self.assertEqual(len(facts["routes"]), 2)
            self.assertEqual(facts["meta"]["frameworks"], ["fastapi"])
            out = Path(tmp) / "out"
            pipeline.write_outputs(out, facts, result)
            self.assertEqual(json.loads((out / "summary.json").read_text())["verdict"], "PASS")
            self.assertTrue((out / "gate.md").read_text().startswith("# Gate: PASS"))
            self.assertEqual(json.loads((out / "facts.json").read_text())["schema"], 1)

    def test_missing_route_in_index_fails_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_repo(tmp, index_lines=(3,))
            _, result = pipeline.run(tmp)
            self.assertEqual(result["verdict"], "FAIL")

    def test_laravel_adapter_is_used_and_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "composer.json").write_text('{"require": {"laravel/framework": "^11"}}')
            (root / "routes").mkdir()
            routes = root / "routes/api.php"
            routes.write_text("<?php\nRoute::get('/ping', [P::class, 'i']);\n")
            make_index(root, files=[("routes/api.php", sha256_file(routes), 0)])
            _, with_adapter = pipeline.run(root, use_adapters=True)
            _, without = pipeline.run(root, use_adapters=False)
        self.assertEqual(with_adapter["verdict"], "PASS")
        self.assertEqual(without["verdict"], "FAIL")  # the negative test from the spec

    def test_repo_without_index_is_indexed_on_a_secret_free_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "app").mkdir()
            (repo / "app/api.py").write_text(SRC)
            (repo / ".env").write_text("SECRET=1\n")
            (repo / "node_modules").mkdir()
            (repo / "node_modules/junk.js").write_text("x")

            def fake_codegraph(cmd, **kwargs):
                make_index(Path(cmd[2]))
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with mock.patch("prd_assistant.pipeline.subprocess.run", side_effect=fake_codegraph) as run:
                index_root, cleanup = pipeline.ensure_index(repo)
            try:
                self.assertEqual(run.call_args.args[0][:2], ["codegraph", "init"])
                self.assertNotEqual(index_root, repo)
                self.assertTrue((index_root / "app/api.py").is_file())
                self.assertFalse((index_root / ".env").exists())
                self.assertFalse((index_root / "node_modules").exists())
                self.assertFalse((repo / ".codegraph").exists())  # original untouched
            finally:
                pipeline.shutil.rmtree(cleanup)

    def test_repo_with_index_is_used_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_repo(tmp)
            index_root, cleanup = pipeline.ensure_index(Path(tmp))
            self.assertEqual(index_root, Path(tmp))
            self.assertIsNone(cleanup)


if __name__ == "__main__":
    unittest.main()
