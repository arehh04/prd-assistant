import unittest
from pathlib import Path

from prd_assistant import mcp_server

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "mcp-setup.md"


class SetupDocTests(unittest.TestCase):
    def test_names_the_real_script_every_tool_every_client_and_the_settings(self):
        text = DOC.read_text()
        self.assertTrue((ROOT / "bin" / "prd_mcp.py").is_file())
        for needle in ("/home/arep/research/prd-assistant/bin/prd_mcp.py", "--root", "PRD_MCP_ROOTS", "--allow-any-repo",
                       "Claude Code", "Codex", "Cline", "Kiro", "mcpServers", "mcp_servers", "one request at a time"):
            self.assertIn(needle, text)
        for tool in mcp_server.TOOLS:
            self.assertIn(tool["name"], text)

    def test_every_snippet_says_whether_it_was_checked(self):
        text = DOC.read_text()
        for client in ("Claude Code", "Codex", "Cline", "Kiro"):
            section = text.split(f"## {client}", 1)[1].split("\n## ", 1)[0]
            self.assertTrue("Status: checked against" in section or "Status: unverified" in section, client)


if __name__ == "__main__":
    unittest.main()
