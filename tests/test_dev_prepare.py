import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from prd_assistant import draft

ROOT = Path(__file__).resolve().parent.parent
CONTROLLER = '''@Controller('payroll')
export class PayrollController {
  @Get()
  @Authenticated()
  async list() {}

  @Post('calculate')
  @AdminOnly()
  async calculate(@Body(new ZodValidationPipe(TeamSchema)) body: X) {
    throw new NotFoundException("No such team");
  }
}
'''
FILES = {
    "api/payroll.controller.ts": CONTROLLER,
    "api/roles.decorator.ts": "export const Authenticated = () => Roles(...ALL_ROLES);\nexport const AdminOnly = () => Roles(...ADMIN_ONLY);\n",
    "packages/types/roles.ts": 'export const ALL_ROLES = ["WORKER", "ADMIN"];\nexport const ADMIN_ONLY = ["ADMIN"];\n',
    "packages/schemas/team.schema.ts": 'export const TeamSchema = z.object({ title: z.string().max(60) });\n',
}


def line_of(text, needle):
    return next(i for i, l in enumerate(text.splitlines(), 1) if needle in l)


def make_repo(tmp, with_routes=True, gate="PASS"):
    repo, out = Path(tmp) / "repo", Path(tmp) / "out"
    for rel, text in FILES.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    out.mkdir()
    routes = []
    if with_routes:
        for rid, method, path, needle in (("r-list", "GET", "/payroll", "async list()"),
                                          ("r-calc", "POST", "/payroll/calculate", "async calculate(")):
            line = line_of(CONTROLLER, needle)
            routes.append({"id": rid, "method": method, "path": path, "file": "api/payroll.controller.ts",
                           "line": line - 1, "source": f"api/payroll.controller.ts:{line - 1}",
                           "handler": {"id": rid + "-h", "source": f"api/payroll.controller.ts:{line}"}})
    (out / "facts.json").write_text(json.dumps({"meta": {"repo": str(repo.resolve())}, "routes": routes,
                                                "screens": [], "navigation": []}))
    (out / "gate.json").write_text(json.dumps({"verdict": gate}))
    return repo, out


class DevPrepareTests(unittest.TestCase):
    def test_writes_every_output_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, out = make_repo(tmp)
            summary = draft.dev_prepare(repo, out, today="2026-01-01")
            for name in ("roles.json", "form_rules.json", "error_messages.json", "dev_gate.json", "dev_gate.md",
                         "scaffold.md", "slots.template.json", "manifest.json", "dev_summary.json"):
                self.assertTrue((out / "dev" / name).is_file(), name)
            self.assertEqual(json.loads((out / "dev" / "manifest.json").read_text())["kind"], "dev")
            self.assertEqual(summary["roles"], {"read": 2, "public": 0, "undeclared": 0, "not_read": 0})
            roles = json.loads((out / "dev" / "roles.json").read_text())
            self.assertEqual(roles["endpoints"]["r-calc"]["roles"], ["ADMIN"])
            msgs = json.loads((out / "dev" / "error_messages.json").read_text())["messages"]
            self.assertEqual([(m["status"], m["text"]) for m in msgs], [(404, "No such team")])

    def test_full_loop_assembles_developer_guide(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, out = make_repo(tmp)
            draft.dev_prepare(repo, out, today="2026-01-01")
            template = json.loads((out / "dev" / "slots.template.json").read_text())
            (out / "dev" / "slots.json").write_text(json.dumps({s["key"]: "NEEDS HUMAN INPUT" for s in template["slots"]}))
            self.assertEqual(draft.run_verify(out / "dev"), [])
            target = draft.run_assemble(out / "dev")
            self.assertEqual(target.name, "developer-guide.md")
            self.assertIn("Developer guide", target.read_text())

    def test_no_routes_is_an_input_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, out = make_repo(tmp, with_routes=False)
            with self.assertRaises(ValueError):
                draft.dev_prepare(repo, out)

    def test_slice1_fail_stops_and_a_failed_rerun_leaves_no_stale_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, out = make_repo(tmp)
            draft.dev_prepare(repo, out, today="2026-01-01")
            (out / "gate.json").write_text(json.dumps({"verdict": "FAIL"}))
            with self.assertRaises(draft.GateFailed):
                draft.dev_prepare(repo, out)
            (out / "gate.json").write_text(json.dumps({"verdict": "PASS"}))
            facts = json.loads((out / "facts.json").read_text())
            for r in facts["routes"]:
                r["handler"]["source"] = "api/missing.ts:1"
            (out / "facts.json").write_text(json.dumps(facts))
            with self.assertRaises(draft.GateFailed):
                draft.dev_prepare(repo, out)
            for name in ("scaffold.md", "slots.template.json", "manifest.json", "dev_summary.json", "developer-guide.md"):
                self.assertFalse((out / "dev" / name).exists(), name)

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, out = make_repo(tmp, with_routes=False)
            run = subprocess.run([sys.executable, "-I", str(ROOT / "bin" / "prd_draft.py"), "dev-prepare", str(repo),
                                  "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 3)
            repo, out = make_repo(tmp + "/ok")
            run = subprocess.run([sys.executable, "-I", str(ROOT / "bin" / "prd_draft.py"), "dev-prepare", str(repo),
                                  "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("dev/scaffold.md", run.stdout)


if __name__ == "__main__":
    unittest.main()
