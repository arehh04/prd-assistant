import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from prd_assistant import criteria, criteria_cache
from tests.test_criteria_bank import ERRORS, FACTS, ROLES2, RULES

FACTS_FULL = {**FACTS, "meta": {"indexed_at_commit": "cafe123"}}
OK_RESULT = {"verdict": "PASS", "checks": []}


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
                   check=True, capture_output=True)


def make_repo(tmp, name="demo", with_index=True):
    repo = Path(tmp) / name
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "a.py").write_text("x = 1\n")
    if with_index:
        (repo / ".codegraph").mkdir()
        (repo / ".codegraph" / "codegraph.db").write_text("db")
    git(repo, "add", "a.py")
    git(repo, "commit", "-q", "-m", "first")
    return repo


def fake_write_outputs(out, facts, result):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "facts.json").write_text(json.dumps(facts))
    (out / "gate.json").write_text(json.dumps(result))


def fake_dev_prepare(repo, out, today=None):
    dev = Path(out) / "dev"
    dev.mkdir(exist_ok=True)
    for name, data in (("roles.json", ROLES2), ("form_rules.json", RULES), ("error_messages.json", ERRORS)):
        (dev / name).write_text(json.dumps(data))
    return {}


class PatchedPipeline:
    """Replaces the heavy slice 1 and 3b steps with the synthetic facts used by the other tests."""

    def __enter__(self):
        self.patches = [mock.patch("prd_assistant.criteria_cache.pipeline.run", return_value=(FACTS_FULL, OK_RESULT)),
                        mock.patch("prd_assistant.criteria_cache.pipeline.write_outputs", side_effect=fake_write_outputs),
                        mock.patch("prd_assistant.criteria_cache.draft.dev_prepare", side_effect=fake_dev_prepare)]
        self.run = self.patches[0].start()
        for p in self.patches[1:]:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()


class NamingTests(unittest.TestCase):
    def test_state_root_precedence(self):
        with mock.patch.dict(os.environ, {"PRD_ASSISTANT_STATE": "/env/state"}):
            self.assertEqual(criteria_cache.state_root("/given"), Path("/given"))
            self.assertEqual(criteria_cache.state_root(), Path("/env/state"))
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(criteria_cache.state_root(), Path.home() / ".claude" / "state" / "prd-assistant")

    def test_hostile_directory_names_cannot_escape_or_collide(self):
        with tempfile.TemporaryDirectory() as tmp:
            names = {}
            for raw in ("a b$c;rm -rf", "...", "ünï", "x" * 200):
                d = Path(tmp) / raw
                d.mkdir()
                name = criteria_cache.repo_dir_name(d)
                names[raw] = name
                self.assertRegex(name, r"^[A-Za-z0-9._-]{1,40}-[0-9a-f]{8}$")
                self.assertNotIn("/", name)
                self.assertFalse(name.startswith("."))
            self.assertEqual(len(set(names.values())), 4)


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(self.tmp.name)

    def test_clean_repo(self):
        fp = criteria_cache.fingerprint(self.repo)
        self.assertEqual((fp["git"], fp["changed"]), (True, 0))
        self.assertRegex(fp["head"], r"^[0-9a-f]{40}$")

    def test_codegraph_churn_is_ignored(self):
        before = criteria_cache.fingerprint(self.repo)
        (self.repo / ".codegraph" / "codegraph.db").write_text("a much longer database")
        (self.repo / ".codegraph" / "daemon.log").write_text("new")
        self.assertEqual(criteria_cache.fingerprint(self.repo), before)

    def test_new_commit_untracked_file_and_double_edit_all_change_it(self):
        base = criteria_cache.fingerprint(self.repo)
        (self.repo / "new.py").write_text("y = 2\n")
        untracked = criteria_cache.fingerprint(self.repo)
        self.assertNotEqual(untracked["dirty"], base["dirty"])
        self.assertEqual(untracked["changed"], 1)
        (self.repo / "a.py").write_text("x = 22\n")
        once = criteria_cache.fingerprint(self.repo)
        (self.repo / "a.py").write_text("x = 3333\n")   # same ' M a.py' status line, different content
        twice = criteria_cache.fingerprint(self.repo)
        self.assertNotEqual(once["dirty"], twice["dirty"])
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "second")
        after = criteria_cache.fingerprint(self.repo)
        self.assertNotEqual(after["head"], base["head"])
        self.assertEqual(after["changed"], 0)

    def test_a_directory_that_is_not_a_git_repository(self):
        plain = Path(self.tmp.name) / "plain"
        plain.mkdir()
        fp = criteria_cache.fingerprint(plain)
        self.assertEqual((fp["git"], fp["head"], fp["dirty"]), (False, None, None))
        self.assertFalse(criteria_cache.is_fresh({"tool_version": criteria.TOOL_VERSION, "schema_version": 1,
                                                  "head": None, "dirty": None}, fp))


class FreshnessTests(unittest.TestCase):
    def test_is_fresh_matrix(self):
        fp = {"git": True, "head": "h", "dirty": "d", "changed": 0}
        good = {"tool_version": criteria.TOOL_VERSION, "schema_version": 1, "head": "h", "dirty": "d"}
        self.assertTrue(criteria_cache.is_fresh(good, fp))
        for change in ({"tool_version": "0"}, {"schema_version": 2}, {"head": "x"}, {"dirty": "x"}):
            self.assertFalse(criteria_cache.is_fresh({**good, **change}, fp), change)
        self.assertFalse(criteria_cache.is_fresh(None, fp))


class EnsureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(self.tmp.name)
        self.state = Path(self.tmp.name) / "state"

    def test_first_call_builds_second_reuses_new_commit_rebuilds(self):
        with PatchedPipeline() as p:
            cache, meta, rebuilt = criteria_cache.ensure(self.repo, self.state)
            self.assertTrue(rebuilt)
            for name in ("criteria.json", "meta.json", "facts.json", "dev/roles.json"):
                self.assertTrue((cache / name).is_file(), name)
            self.assertEqual(meta["codegraph_commit"], "cafe123")
            self.assertEqual(criteria_cache.load_bank(cache)["tool_version"], criteria.TOOL_VERSION)
            self.assertEqual([x.name for x in self.state.iterdir() if x.name.startswith(".build-")], [])
            _, _, again = criteria_cache.ensure(self.repo, self.state)
            self.assertFalse(again)
            self.assertEqual(p.run.call_count, 1)
            (self.repo / "b.py").write_text("z = 1\n")
            _, _, third = criteria_cache.ensure(self.repo, self.state)
            self.assertTrue(third)
            self.assertEqual(p.run.call_count, 2)

    def test_force_rebuilds(self):
        with PatchedPipeline() as p:
            criteria_cache.ensure(self.repo, self.state)
            criteria_cache.ensure(self.repo, self.state, force=True)
            self.assertEqual(p.run.call_count, 2)

    def test_a_non_git_directory_is_rebuilt_every_time(self):
        plain = Path(self.tmp.name) / "plain"
        (plain / ".codegraph").mkdir(parents=True)
        (plain / ".codegraph" / "codegraph.db").write_text("db")
        with PatchedPipeline() as p:
            _, meta, _ = criteria_cache.ensure(plain, self.state)
            criteria_cache.ensure(plain, self.state)
            self.assertEqual(p.run.call_count, 2)
            self.assertFalse(meta["git"])

    def test_no_codegraph_index_writes_nothing(self):
        bare = make_repo(self.tmp.name, "bare", with_index=False)
        with PatchedPipeline():
            with self.assertRaises(criteria_cache.EnvError) as ctx:
                criteria_cache.ensure(bare, self.state)
        self.assertIn("CodeGraph", str(ctx.exception))
        self.assertFalse(self.state.exists())

    def test_not_a_directory(self):
        with self.assertRaises(criteria_cache.EnvError):
            criteria_cache.ensure(Path(self.tmp.name) / "nope", self.state)

    def test_failed_rebuild_keeps_the_previous_cache(self):
        with PatchedPipeline():
            cache, meta, _ = criteria_cache.ensure(self.repo, self.state)
        before = (cache / "criteria.json").read_text()
        with mock.patch("prd_assistant.criteria_cache.pipeline.run", side_effect=OSError("disk went away")):
            with self.assertRaises(criteria_cache.EnvError):
                criteria_cache.ensure(self.repo, self.state, force=True)
        self.assertEqual((cache / "criteria.json").read_text(), before)
        self.assertEqual([x.name for x in self.state.iterdir() if x.name.startswith(".build-")], [])

    def test_gate_failure_is_facts_unavailable(self):
        with PatchedPipeline() as p:
            p.run.return_value = (FACTS_FULL, {"verdict": "FAIL", "checks": []})
            with self.assertRaises(criteria_cache.FactsUnavailable):
                criteria_cache.ensure(self.repo, self.state)
        self.assertEqual([x.name for x in self.state.iterdir()], [])

    def test_dev_gate_failure_and_no_routes(self):
        from prd_assistant import draft
        with PatchedPipeline():
            with mock.patch("prd_assistant.criteria_cache.draft.dev_prepare", side_effect=draft.GateFailed("dev gate is FAIL")):
                with self.assertRaises(criteria_cache.FactsUnavailable):
                    criteria_cache.ensure(self.repo, self.state)
            with mock.patch("prd_assistant.criteria_cache.draft.dev_prepare", side_effect=ValueError("no routes were extracted")):
                with self.assertRaises(criteria_cache.EnvError):
                    criteria_cache.ensure(self.repo, self.state)

    def test_unwritable_state_directory(self):
        blocker = Path(self.tmp.name) / "blocker"
        blocker.write_text("a file, not a directory")
        with PatchedPipeline():
            with self.assertRaises(criteria_cache.EnvError):
                criteria_cache.ensure(self.repo, blocker / "state")

    def test_nothing_is_written_into_the_repo(self):
        before = sorted(str(p.relative_to(self.repo)) for p in self.repo.rglob("*") if ".git" not in p.parts)
        with PatchedPipeline():
            criteria_cache.ensure(self.repo, self.state)
        after = sorted(str(p.relative_to(self.repo)) for p in self.repo.rglob("*") if ".git" not in p.parts)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
