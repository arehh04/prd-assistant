import unittest

from prd_assistant import links


def find_line(content, needle):
    for number, line in enumerate(content.splitlines(), start=1):
        if needle in line:
            return number
    raise AssertionError(needle)


def summarize(calls):
    return [(c["method"], c["raw"], c["dynamic"]) for c in calls]


PY = '''def test_x(client):
    r = client.get("/api/v1/teams")
    client.post(f"/api/v1/teams/{tid}/members", json={})
    client.get("/api/v1/users/" + uid)
    # client.get("/commented")
    d.get("key")
'''

PHP = """<?php
$this->getJson('/api/v1/houses');
$this->actingAs($u)->postJson("/api/v1/houses/{$house->id}/rooms", []);
$this->getJson($url);
$this->json('PATCH', '/api/v1/rooms/1');
$this->get(route('x'));
$this->get('/api/v1/health');
// $this->getJson('/commented');
"""

JS_TEST = """await request(app.getHttpServer()).get('/api/v1/health').expect(200)
request(server).post(`/api/v1/items/${id}`)
"""

JS_FRONT = """export const a = () => http.post('/auth/logout')
export const b = () => fetch('/api/v1/teams', { method: 'POST' })
export const c = () => fetch(TEAMS_URL)
export const d = () => fetch('https://example.com/x')
const e = cache.get('key')
"""


class ParseCallsTests(unittest.TestCase):
    def test_python_calls(self):
        calls, ignored = links.parse_calls(PY, "tests/test_api.py", "tests", "py")
        self.assertEqual(summarize(calls), [
            ("GET", "/api/v1/teams", False),
            ("POST", "/api/v1/teams/{tid}/members", False),
            ("GET", "/api/v1/users/", True),
        ])
        self.assertEqual([c["line"] for c in calls],
                         [find_line(PY, '"/api/v1/teams")'), find_line(PY, "members"), find_line(PY, '+ uid')])
        self.assertEqual([i["line"] for i in ignored], [find_line(PY, 'd.get("key")')])

    def test_php_calls(self):
        calls, ignored = links.parse_calls(PHP, "tests/Feature/HouseTest.php", "tests", "php")
        self.assertEqual(summarize(calls), [
            ("GET", "/api/v1/houses", False),
            ("POST", "/api/v1/houses/{$house->id}/rooms", False),
            ("GET", None, True),
            ("PATCH", "/api/v1/rooms/1", False),
            ("GET", "/api/v1/health", False),
        ])
        self.assertEqual([i["line"] for i in ignored], [find_line(PHP, "route('x')")])

    def test_javascript_test_calls(self):
        calls, _ = links.parse_calls(JS_TEST, "e2e/app.e2e-spec.ts", "tests", "js")
        self.assertEqual(summarize(calls), [("GET", "/api/v1/health", False),
                                            ("POST", "/api/v1/items/${id}", False)])

    def test_frontend_calls(self):
        calls, ignored = links.parse_calls(JS_FRONT, "web/src/api.ts", "frontend", "js")
        self.assertEqual(summarize(calls), [
            ("POST", "/auth/logout", False),
            ("POST", "/api/v1/teams", False),   # method read from the fetch options
            (None, None, True),                 # fetch(TEAMS_URL) is dynamic
        ])
        self.assertEqual([i["line"] for i in ignored], [find_line(JS_FRONT, "cache.get")])

    def test_fetch_is_not_a_call_on_the_test_side(self):
        calls, _ = links.parse_calls("fetch('/api/v1/x')\n", "e2e/a.ts", "tests", "js")
        self.assertEqual(calls, [])

    def test_language_of(self):
        self.assertEqual(links.language_of("a/b.py"), "py")
        self.assertEqual(links.language_of("a/B.php"), "php")
        for name in ("a.ts", "a.tsx", "a.js", "a.jsx", "a.mjs", "a.cjs", "a.vue"):
            self.assertEqual(links.language_of(name), "js", name)
        self.assertIsNone(links.language_of("a.rb"))


if __name__ == "__main__":
    unittest.main()
