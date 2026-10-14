import unittest

from prd_assistant import links


def routes(*specs):
    return [{"id": rid, "method": m, "segs": links.segments(p)} for rid, m, p in specs]


class SegmentTests(unittest.TestCase):
    def test_interpolations_and_params_become_wildcards(self):
        self.assertEqual(links.segments("/api/v1/houses/${id}/rooms?x=1"), ("api", "v1", "houses", "{}", "rooms"))
        self.assertEqual(links.segments("/houses/{$house->id}/rooms"), ("houses", "{}", "rooms"))
        self.assertEqual(links.segments("/a/:id/"), ("a", "{}"))
        self.assertEqual(links.segments("/file-{x}.pdf"), ("{}",))
        self.assertEqual(links.segments("/a//b"), ("a", "b"))
        self.assertEqual(links.segments("/users/{id}"), ("users", "{}"))
        self.assertEqual(links.segments("api/v1/x"), ("api", "v1", "x"))


class MatchTests(unittest.TestCase):
    R = routes(("me", "GET", "/users/me"), ("one", "GET", "/users/{id}"),
               ("mk", "POST", "/users"), ("out", "POST", "/auth/logout"))

    def match(self, path, method, prefix=()):
        return links.match_call(links.segments(path), method, self.R, prefix)

    def test_static_beats_parameter(self):
        self.assertEqual(self.match("/users/me", "GET"), ("matched", ["me"], False))

    def test_a_concrete_value_matches_the_parameter_route(self):
        self.assertEqual(self.match("/users/7", "GET"), ("matched", ["one"], False))

    def test_an_interpolated_value_prefers_the_parameter_route(self):
        self.assertEqual(self.match("/users/${uid}", "GET"), ("matched", ["one"], False))

    def test_method_must_match(self):
        self.assertEqual(self.match("/users/7", "DELETE")[0], "unmatched")

    def test_unknown_method_matches_any(self):
        self.assertEqual(self.match("/users", None)[:2], ("matched", ["mk"]))

    def test_prefix_retry(self):
        self.assertEqual(self.match("/logout", "POST", prefix=("auth",)), ("matched", ["out"], True))

    def test_unmatched(self):
        self.assertEqual(self.match("/nothing", "GET"), ("unmatched", [], False))

    def test_duplicate_routes_are_ambiguous(self):
        dup = routes(("a", "GET", "/api/dup"), ("b", "GET", "/api/dup"))
        result = links.match_call(links.segments("/api/dup"), "GET", dup, ())
        self.assertEqual(result, ("ambiguous", ["a", "b"], False))

    def test_all_method_routes_match_any_verb(self):
        any_route = routes(("x", "ALL", "/hook"))
        self.assertEqual(links.match_call(links.segments("/hook"), "POST", any_route, ())[0], "matched")


if __name__ == "__main__":
    unittest.main()
