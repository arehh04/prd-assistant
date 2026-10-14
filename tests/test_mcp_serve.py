import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from prd_assistant import mcp_server as m
from tests.test_criteria_cache import make_repo

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "prd_mcp.py"


def lines(*msgs):
    return b"".join(x if isinstance(x, bytes) else (x if isinstance(x, str) else json.dumps(x)).encode() + b"\n" for x in msgs)


def run_serve(data, config=None, stderr=None):
    out = io.BytesIO()
    with contextlib.redirect_stderr(stderr or io.StringIO()):
        code = m.serve(io.BytesIO(data), out, config or m.Config(roots=[]))
    return code, [json.loads(line) for line in out.getvalue().splitlines()]


def req(method, params=None, rid=1):
    return {"jsonrpc": "2.0", "id": rid, "method": method, **({"params": params} if params is not None else {})}


class ServeTests(unittest.TestCase):
    def test_a_conversation(self):
        data = lines(req("initialize", {"protocolVersion": "2025-06-18"}, 1),
                     {"jsonrpc": "2.0", "method": "notifications/initialized"}, req("tools/list", None, 2), "", req("ping", None, 3))
        code, out = run_serve(data)
        self.assertEqual(code, 0)
        self.assertEqual([o["id"] for o in out], [1, 2, 3])
        self.assertEqual(len(out[1]["result"]["tools"]), 4)

    def test_blank_lines_bad_lines_and_invalid_utf8_do_not_stop_the_stream(self):
        data = lines("not json", b"\xff\xfe broken \xc3\n", req("ping", None, 7))
        code, out = run_serve(data)
        self.assertEqual(code, 0)
        self.assertEqual([o.get("id") for o in out], [None, None, 7])
        self.assertEqual(out[0]["error"]["code"], -32700)

    def test_an_oversize_line_is_one_parse_error_and_the_next_message_still_works(self):
        data = b"x" * (m.MAX_LINE + 500) + b"\n" + lines(req("ping", None, 9))
        code, out = run_serve(data)
        self.assertEqual(code, 0)
        self.assertEqual(out[0]["error"]["code"], -32700)
        self.assertIn("long", out[0]["error"]["message"])
        self.assertEqual(out[1]["id"], 9)

    def test_a_line_without_a_final_newline_is_still_answered(self):
        code, out = run_serve(json.dumps(req("ping", None, 4)).encode())
        self.assertEqual(out[0]["id"], 4)

    def test_a_closed_stdout_ends_the_loop_quietly(self):
        class Broken:
            def write(self, b):
                raise BrokenPipeError

            def flush(self):
                raise BrokenPipeError
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(m.serve(io.BytesIO(lines(req("ping"))), Broken(), m.Config(roots=[])), 0)

    def test_a_print_inside_a_tool_goes_to_stderr_not_into_the_protocol(self):
        def noisy(args, session, config):
            print("stray output that would corrupt the stream")
            return m.ok_result("fine", None, session)
        err = io.StringIO()
        with mock.patch.dict(m.HANDLERS, {"repo_status": noisy}):
            code, out = run_serve(lines(req("tools/call", {"name": "repo_status", "arguments": {"repo": "/r"}}, 5)), stderr=err)
        self.assertEqual(out[0]["result"]["content"][0]["text"], "fine")
        self.assertIn("stray output", err.getvalue())

    def test_output_lines_never_contain_raw_newlines_or_non_ascii(self):
        out = io.BytesIO()
        with contextlib.redirect_stderr(io.StringIO()):
            m.serve(io.BytesIO(lines(req("ping", None, "id- -\n-‮"))), out, m.Config(roots=[]))
        raw = out.getvalue()
        self.assertEqual(raw.count(b"\n"), 1)
        raw.decode("ascii")


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.repo = make_repo(str(self.base), with_index=False)

    def run_script(self, data, *args):
        run = subprocess.run([sys.executable, "-I", str(SCRIPT), *args], input=data, capture_output=True, timeout=60)
        return run, [json.loads(line) for line in run.stdout.splitlines()]

    def test_end_to_end_over_pipes(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        data = lines(req("initialize", {"protocolVersion": "2025-06-18"}, 1), {"jsonrpc": "2.0", "method": "notifications/initialized"},
                     req("tools/list", None, 2),
                     req("tools/call", {"name": "repo_status", "arguments": {"repo": str(self.repo)}}, 3),
                     req("tools/call", {"name": "repo_status", "arguments": {"repo": str(outside)}}, 4),
                     "garbage line", req("ping", None, 5))
        run, out = self.run_script(data, "--root", str(self.base), "--state-dir", str(self.base / "state"))
        self.assertEqual(run.returncode, 0, run.stderr.decode())
        by_id = {o.get("id"): o for o in out}
        self.assertEqual(len(by_id[2]["result"]["tools"]), 4)
        self.assertFalse(by_id[3]["result"]["isError"])
        self.assertIn("codegraph init", by_id[3]["result"]["content"][0]["text"])
        self.assertTrue(by_id[4]["result"]["isError"])
        self.assertEqual(by_id[None]["error"]["code"], -32700)
        self.assertEqual(by_id[5]["result"], {})
        self.assertFalse((self.base / "state").exists())

    def test_roots_from_the_environment_and_the_working_directory(self):
        data = lines(req("tools/call", {"name": "repo_status", "arguments": {"repo": str(self.repo)}}, 1))
        state = str(self.base / "s")
        env_run = subprocess.run([sys.executable, "-I", str(SCRIPT), "--state-dir", state], input=data, capture_output=True,
                                 timeout=60, env={"PRD_MCP_ROOTS": str(self.base), "PATH": "/usr/bin:/bin"}, cwd="/")
        self.assertFalse(json.loads(env_run.stdout)["result"]["isError"])
        cwd_run = subprocess.run([sys.executable, "-I", str(SCRIPT), "--state-dir", state], input=data, capture_output=True,
                                 timeout=60, env={"PATH": "/usr/bin:/bin"}, cwd=str(self.base))
        self.assertFalse(json.loads(cwd_run.stdout)["result"]["isError"])
        nowhere = subprocess.run([sys.executable, "-I", str(SCRIPT)], input=data, capture_output=True, timeout=60,
                                 env={"PATH": "/usr/bin:/bin"}, cwd="/")
        self.assertTrue(json.loads(nowhere.stdout)["result"]["isError"])

    def test_allow_any_repo_and_warnings_on_stderr(self):
        data = lines(req("tools/call", {"name": "repo_status", "arguments": {"repo": str(self.repo)}}, 1))
        run, out = self.run_script(data, "--root", str(self.base / "missing"), "--allow-any-repo", "--state-dir", str(self.base / "s"))
        self.assertFalse(out[0]["result"]["isError"])
        self.assertIn("does not exist", run.stderr.decode())
        self.assertNotIn("does not exist", run.stdout.decode())

    def test_help(self):
        run = subprocess.run([sys.executable, "-I", str(SCRIPT), "--help"], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0)
        self.assertIn("--root", run.stdout)


if __name__ == "__main__":
    unittest.main()
