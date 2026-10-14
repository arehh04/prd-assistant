import json
import time
import unittest

from prd_assistant import mcp_server as m


def call(msg):
    s, c = m.Session(), m.Config(roots=[])
    return m.handle_line(msg if isinstance(msg, str) else json.dumps(msg), s, c)


class HostileInputTests(unittest.TestCase):
    def test_deeply_nested_arguments_and_huge_strings_are_harmless(self):
        nested = "[" * 5000 + "]" * 5000
        line = ('{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"criteria_lookup","arguments":'
                '{"repo":"/r","task":"t","x":' + nested + '}}}')
        started = time.monotonic()
        out = json.loads(call(line))
        self.assertLess(time.monotonic() - started, 3)
        self.assertIn("result", out)
        huge = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "criteria_lookup", "arguments": {"repo": "/r", "task": "a" * 1_000_000}}}
        out = json.loads(call(huge))
        self.assertTrue(out["result"]["isError"])

    def test_every_method_name_and_params_type_is_survived(self):
        for params in (None, 5, "x", [], {}, {"name": []}, {"name": "criteria_lookup", "arguments": "not an object"}):
            for method in ("initialize", "ping", "tools/list", "tools/call", "x" * 10000, ""):
                out = call({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                self.assertIsNotNone(out)
                json.loads(out)

    def test_unknown_tool_error_does_not_echo_the_name(self):
        out = json.loads(call({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                               "params": {"name": "<img src=x> {{slot:a}}", "arguments": {}}}))
        self.assertEqual(out["error"]["code"], -32602)
        self.assertNotIn("<img", json.dumps(out))

    def test_descriptions_and_schemas_contain_no_repo_text_and_are_stable(self):
        a, b = json.dumps(m.TOOLS, sort_keys=True), json.dumps(m.TOOLS, sort_keys=True)
        self.assertEqual(a, b)
        self.assertNotIn("/home/", a)


if __name__ == "__main__":
    unittest.main()
