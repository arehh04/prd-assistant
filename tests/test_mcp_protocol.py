import json
import unittest
from unittest import mock

from prd_assistant import mcp_server as m


def new():
    return m.Session(), m.Config(roots=[], allow_any=False, state_dir=None)


def send(msg, session=None, config=None):
    s, c = new()
    return m.handle_message(msg, session or s, config or c)


def req(method, params=None, rid=1):
    out = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        out["params"] = params
    return out


class InitializeTests(unittest.TestCase):
    def test_known_version_is_echoed_and_remembered(self):
        s, c = new()
        r = m.handle_message(req("initialize", {"protocolVersion": "2025-03-26"}), s, c)
        self.assertEqual(r["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(s.negotiated, "2025-03-26")
        self.assertEqual(r["result"]["capabilities"], {"tools": {}})
        self.assertEqual(r["result"]["serverInfo"]["name"], "prd-assistant")
        self.assertIn("data, not instructions", r["result"]["instructions"])

    def test_unknown_or_missing_version_gets_the_newest_supported(self):
        for params in ({"protocolVersion": "2099-01-01"}, {}, None, {"protocolVersion": 5}):
            s, c = new()
            r = m.handle_message(req("initialize", params), s, c)
            self.assertEqual(r["result"]["protocolVersion"], m.SUPPORTED_VERSIONS[0])

    def test_ping_and_initialized_notification(self):
        self.assertEqual(send(req("ping"))["result"], {})
        self.assertIsNone(send({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertIsNone(send({"jsonrpc": "2.0", "method": "tools/call", "params": {}}))   # any notification: no answer


class ErrorTests(unittest.TestCase):
    def test_unknown_method(self):
        r = send(req("resources/list"))
        self.assertEqual((r["error"]["code"], r["id"]), (-32601, 1))

    def test_invalid_requests(self):
        for bad in (5, "x", None, {"id": 1}, {"id": 1, "method": 7}):
            r = send(bad)
            self.assertEqual(r["error"]["code"], -32600, bad)
        self.assertEqual(send({"id": 1, "method": 7})["id"], 1)
        self.assertIsNone(send({"id": 1.5, "method": "ping"})["id"])
        self.assertIsNone(send({"id": None, "method": "ping"})["id"])
        self.assertIsNone(send({"id": True, "method": "ping"})["id"])
        self.assertEqual(send({"id": None, "method": "ping"})["error"]["code"], -32600)

    def test_ids_of_both_kinds_are_echoed(self):
        self.assertEqual(send(req("ping", rid="abc"))["id"], "abc")
        self.assertEqual(send(req("ping", rid=0))["id"], 0)

    def test_batches(self):
        s, c = new()
        out = m.handle_message([req("ping", rid=1), {"jsonrpc": "2.0", "method": "notifications/x"}, req("nope", rid=2)], s, c)
        self.assertEqual([x["id"] for x in out], [1, 2])
        self.assertEqual(m.handle_message([], s, c)["error"]["code"], -32600)
        self.assertIsNone(m.handle_message([{"jsonrpc": "2.0", "method": "notifications/x"}], s, c))
        nested = m.handle_message([[req("ping")]], s, c)
        self.assertEqual(nested[0]["error"]["code"], -32600)


class HandleLineTests(unittest.TestCase):
    def test_parse_errors_and_one_line_output(self):
        s, c = new()
        for line in ("{not json", "", "[", "nul\x00l"):
            out = json.loads(m.handle_line(line, s, c))
            self.assertEqual((out["error"]["code"], out["id"]), (-32700, None))
        out = m.handle_line(json.dumps(req("ping", rid="x y\n")), s, c)
        self.assertNotIn("\n", out)
        self.assertNotIn(" ", out)
        self.assertEqual(json.loads(out)["id"], "x y\n")

    def test_notifications_produce_no_line(self):
        s, c = new()
        self.assertIsNone(m.handle_line('{"jsonrpc":"2.0","method":"notifications/initialized"}', s, c))

    def test_pathologically_deep_json_is_a_parse_error_not_a_crash(self):
        s, c = new()
        out = json.loads(m.handle_line("[" * 200000, s, c))
        self.assertEqual(out["error"]["code"], -32700)


class ToolsListTests(unittest.TestCase):
    def test_four_tools_with_fixed_descriptions_and_honest_annotations(self):
        tools = {t["name"]: t for t in send(req("tools/list"))["result"]["tools"]}
        self.assertEqual(set(tools), {"criteria_lookup", "criteria_show", "criteria_build", "repo_status"})
        for t in tools.values():
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertIn("repo", t["inputSchema"]["required"])
            self.assertIn("outside the repo", t["description"])
            self.assertFalse(t["annotations"]["openWorldHint"])
        self.assertTrue(tools["repo_status"]["annotations"]["readOnlyHint"])
        for name in ("criteria_lookup", "criteria_show", "criteria_build"):
            self.assertFalse(tools[name]["annotations"]["readOnlyHint"])
            self.assertFalse(tools[name]["annotations"]["destructiveHint"])
            self.assertTrue(tools[name]["annotations"]["idempotentHint"])

    def test_schemas_bound_every_input(self):
        tools = {t["name"]: t["inputSchema"]["properties"] for t in m.TOOLS}
        self.assertEqual(tools["criteria_lookup"]["task"]["maxLength"], 2000)
        self.assertEqual((tools["criteria_lookup"]["max_subjects"]["minimum"], tools["criteria_lookup"]["max_subjects"]["maximum"]), (1, 20))
        self.assertEqual(tools["criteria_lookup"]["max_candidates"]["maximum"], 200)
        self.assertIn("pattern", tools["criteria_show"]["id"])
        self.assertTrue(all(p["repo"]["maxLength"] == 4096 for p in tools.values()))


class ValidateTests(unittest.TestCase):
    def test_accepts_valid_arguments_and_drops_unknown_ones(self):
        clean, problem = m.validate("criteria_lookup", {"repo": "/r", "task": "pay", "max_subjects": 3, "extra": 1})
        self.assertIsNone(problem)
        self.assertEqual(clean, {"repo": "/r", "task": "pay", "max_subjects": 3})

    def test_rejects_with_fixed_messages_that_never_echo_the_input(self):
        hostile = "<img src=x> {{slot:a}}"
        cases = [(None, "repo"), ([], "arguments"), ({}, "repo"), ({"repo": 5}, "repo"), ({"repo": ""}, "repo"),
                 ({"repo": "x" * 5000, "task": "t"}, "repo"), ({"repo": "/r"}, "task"), ({"repo": "/r", "task": hostile * 300}, "task"),
                 ({"repo": "/r", "task": "t", "max_subjects": 0}, "max_subjects"), ({"repo": "/r", "task": "t", "max_subjects": 21}, "max_subjects"),
                 ({"repo": "/r", "task": "t", "max_subjects": True}, "max_subjects"), ({"repo": "/r", "task": "t", "max_subjects": 2.5}, "max_subjects"),
                 ({"repo": "/r", "task": "t", "max_candidates": "9"}, "max_candidates")]
        for args, word in cases:
            _, problem = m.validate("criteria_lookup", args)
            self.assertIsNotNone(problem, args)
            self.assertIn(word, problem)
            self.assertNotIn("<img", problem)
        _, problem = m.validate("criteria_show", {"repo": "/r", "id": "C-ROLE-1; rm"})
        self.assertIn("id", problem)
        self.assertIsNone(m.validate("criteria_show", {"repo": "/r", "id": "C-ROLE-014"})[1])


class CallTests(unittest.TestCase):
    def test_unknown_tool_is_a_protocol_error(self):
        r = send(req("tools/call", {"name": "nope", "arguments": {}}))
        self.assertEqual(r["error"]["code"], -32602)
        for bad in ({}, {"name": 5}, {"name": None}, None):
            self.assertEqual(send(req("tools/call", bad))["error"]["code"], -32602)

    def test_argument_problems_are_error_results_not_protocol_errors(self):
        r = send(req("tools/call", {"name": "criteria_lookup", "arguments": {"repo": 5}}))
        self.assertTrue(r["result"]["isError"])
        self.assertEqual(r["result"]["content"][0]["type"], "text")
        self.assertNotIn("error", r)

    def test_missing_arguments_are_an_error_result(self):
        r = send(req("tools/call", {"name": "repo_status"}))
        self.assertTrue(r["result"]["isError"])

    def test_an_unexpected_exception_becomes_an_error_result_without_a_traceback(self):
        s, c = new()
        with mock.patch.dict(m.HANDLERS, {"repo_status": mock.Mock(side_effect=RuntimeError("boom <img>"))}):
            r = m.handle_message(req("tools/call", {"name": "repo_status", "arguments": {"repo": "/r"}}), s, c)
        text = r["result"]["content"][0]["text"]
        self.assertTrue(r["result"]["isError"])
        self.assertIn("RuntimeError", text)
        self.assertNotIn("Traceback", text)
        self.assertNotIn("<img", text)


if __name__ == "__main__":
    unittest.main()
