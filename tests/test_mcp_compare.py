import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

from prd_assistant import mcp_server as m

ROOT = Path(__file__).resolve().parent.parent
CALIBRATION = ROOT / "calibration" / "calibration.json"


def without_volatile_lines(text):
    return "\n".join(line for line in text.splitlines() if not line.startswith("- Facts built") and not line.startswith("- Cache:"))


class CompareWithCliTests(unittest.TestCase):
    def test_server_text_equals_cli_text_for_a_calibration_repo(self):
        spec = json.loads(CALIBRATION.read_text())["repos"]["rms"]
        if not Path(spec["path"]).is_dir():
            self.skipTest("calibration repo not present")
        cli_spec = importlib.util.spec_from_file_location("prd_criteria", ROOT / "bin" / "prd_criteria.py")
        cli = importlib.util.module_from_spec(cli_spec)
        cli_spec.loader.exec_module(cli)
        task = "let branch admins deactivate a house"
        with tempfile.TemporaryDirectory() as state:
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                cli.main(["lookup", spec["path"], task, "--state-dir", state])
            session, config = m.Session(), m.Config(roots=[Path(spec["path"]).resolve()], state_dir=state)
            reply = m.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": "criteria_lookup", "arguments": {"repo": spec["path"], "task": task}}}, session, config)
        self.assertFalse(reply["result"]["isError"])
        self.assertEqual(without_volatile_lines(reply["result"]["content"][0]["text"]), without_volatile_lines(out.getvalue()))


if __name__ == "__main__":
    unittest.main()
