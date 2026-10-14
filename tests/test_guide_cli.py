import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CLI = Path(__file__).resolve().parent.parent / "bin" / "prd_draft.py"

ROUTER = '''import { LoginPage } from "../pages/LoginPage";
import { TeamsPage } from "../pages/TeamsPage";

export const routes = [
  { path: "/login", element: <LoginPage /> },
  { path: "/teams", element: <TeamsPage /> },
];
'''
LOGIN = '''export function LoginPage() {
  return (
    <div>
      <h1>Sign in</h1>
      <button type="submit">Sign in now</button>
      <p role="alert">Wrong password</p>
    </div>
  );
}
'''
TEAMS = '''import { useNavigate } from "react-router-dom";

export function TeamsPage() {
  const go = useNavigate();
  return (
    <div>
      <h1>Teams</h1>
      <label>Team name</label>
      <button onClick={() => go("/login")}>Back to sign in</button>
    </div>
  );
}
'''


def run_cli(*args):
    return subprocess.run([sys.executable, "-I", str(CLI), *args], capture_output=True, text=True)


def line_of(text, needle):
    for number, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return number
    raise AssertionError(needle)


def make_workspace(tmp, router=ROUTER, gate="PASS", screens=True):
    repo, out = Path(tmp) / "repo", Path(tmp) / "out"
    for rel, text in (("web/package.json", '{"dependencies": {"react-router-dom": "7"}}'),
                      ("web/src/app/router.tsx", router), ("web/src/pages/LoginPage.tsx", LOGIN),
                      ("web/src/pages/TeamsPage.tsx", TEAMS)):
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    out.mkdir()
    shown = [{"id": f"s{i}", "kind": "screen", "path": p, "file": "web/src/app/router.tsx",
              "line": line_of(router, f'path: "{p}"'), "source": "x", "origin": "codegraph", "component": None}
             for i, p in enumerate(["/login", "/teams"], start=1)] if screens else []
    facts = {"schema": 1, "meta": {"repo": str(repo.resolve()), "codegraph_version": "1.6.2",
                                   "extraction_version": "27", "indexed_at_commit": "abc"},
             "routes": [], "screens": shown, "excluded": [],
             "navigation": [{"id": "n1", "from_symbol": "TeamsPage", "from_file": "web/src/pages/TeamsPage.tsx",
                             "to_path": "/login", "to_id": "s1", "line": line_of(TEAMS, 'go("/login")'),
                             "source": "web/src/pages/TeamsPage.tsx:9", "href": "/login", "reattached": False}]}
    (out / "facts.json").write_text(json.dumps(facts))
    (out / "gate.json").write_text(json.dumps({"verdict": gate, "checks": []}))
    return repo, out


def good_slots(out):
    template = json.loads((out / "guide" / "slots.template.json").read_text())
    slots = {}
    for s in template["slots"]:
        ev = s["allowed_evidence"][0]
        slots[s["key"]] = f"Lets you carry on. [{ev['file']}:{ev['from_line']}]"
    return slots


class GuideCliTests(unittest.TestCase):
    def test_prepare_verify_assemble_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, out = make_workspace(tmp)
            done = run_cli("guide-prepare", str(repo), "--out", str(out))
            self.assertEqual(done.returncode, 0, done.stderr)
            guide_dir = out / "guide"
            for name in ("ui_text.json", "journeys.json", "guide_gate.json", "guide_gate.md", "scaffold.md",
                         "slots.template.json", "manifest.json", "guide_summary.json"):
                self.assertTrue((guide_dir / name).is_file(), name)
            summary = json.loads((guide_dir / "guide_summary.json").read_text())
            self.assertEqual((summary["screens"], summary["resolved"], summary["with_text"]), (2, 2, 2))
            self.assertEqual(summary["edges"], 1)
            self.assertEqual(json.loads((guide_dir / "manifest.json").read_text())["kind"], "guide")
            (guide_dir / "slots.json").write_text(json.dumps(good_slots(out)))
            self.assertEqual(run_cli("verify", "--out", str(guide_dir)).returncode, 0)
            done = run_cli("assemble", "--out", str(guide_dir))
            self.assertEqual(done.returncode, 0, done.stderr)
            guide = (guide_dir / "client-guide.md").read_text()
            self.assertIn("Back to sign in", guide)
            self.assertIn("Wrong password", guide)
            self.assertNotIn("{{slot:", guide)
            self.assertFalse((guide_dir / "prd.md").exists())

    def test_jargon_in_a_slot_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, out = make_workspace(tmp)
            run_cli("guide-prepare", str(repo), "--out", str(out))
            slots = good_slots(out)
            key = next(k for k in slots if k.startswith("screen."))
            ev = json.loads((out / "guide" / "slots.template.json").read_text())["slots"][1]["allowed_evidence"][0]
            slots[key] = f"Calls the API for you. [{ev['file']}:{ev['from_line']}]"
            (out / "guide" / "slots.json").write_text(json.dumps(slots))
            done = run_cli("verify", "--out", str(out / "guide"))
            self.assertEqual(done.returncode, 1)
            self.assertIn("jargon", done.stdout)

    def test_slice1_gate_fail_stops_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, out = make_workspace(tmp, gate="FAIL")
            done = run_cli("guide-prepare", str(repo), "--out", str(out))
            self.assertEqual(done.returncode, 2)
            self.assertFalse((out / "guide").exists())

    def test_no_screens_exits_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, out = make_workspace(tmp, screens=False)
            done = run_cli("guide-prepare", str(repo), "--out", str(out))
            self.assertEqual(done.returncode, 3)
            self.assertIn("no screens", done.stderr)
            self.assertFalse((out / "guide" / "scaffold.md").exists())

    def test_guide_gate_fail_writes_diagnostics_but_no_scaffold(self):
        with tempfile.TemporaryDirectory() as tmp:
            router = ROUTER.replace("<LoginPage />", "<Gone />").replace("<TeamsPage />", "<AlsoGone />")
            repo, out = make_workspace(tmp, router=router)
            done = run_cli("guide-prepare", str(repo), "--out", str(out))
            self.assertEqual(done.returncode, 2, done.stderr)
            guide_dir = out / "guide"
            self.assertTrue((guide_dir / "guide_gate.json").is_file())
            self.assertTrue((guide_dir / "ui_text.json").is_file())
            for name in ("scaffold.md", "slots.template.json", "manifest.json"):
                self.assertFalse((guide_dir / name).exists(), name)

    def test_the_prd_pipeline_still_names_its_output_prd_md(self):
        # a manifest without a kind (written by slice 2) means "prd"
        from prd_assistant import draft
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "scaffold.md").write_text("# T\n\n{{slot:a}}\n")
            template = {"slots": [{"key": "a", "max_words": 10, "may_be_needs_human_input": True,
                                   "allowed_evidence": [{"file": "f.py", "from_line": 1, "to_line": 1}],
                                   "evidence_text": [{"file": "f.py", "from_line": 1, "to_line": 1, "text": "x"}],
                                   "allowed_numbers": []}]}
            (out / "slots.template.json").write_text(json.dumps(template))
            (out / "slots.json").write_text(json.dumps({"a": "Fine. [f.py:1]"}))
            draft._write_json(out / "manifest.json", {"scaffold_sha256": draft._sha(out / "scaffold.md"),
                                                      "template_sha256": draft._sha(out / "slots.template.json")})
            self.assertEqual(draft.run_assemble(out).name, "prd.md")


if __name__ == "__main__":
    unittest.main()
