import unittest

from prd_assistant import groups


def route(rid, path):
    return {"id": rid, "path": path, "method": "GET"}


class PrefixTests(unittest.TestCase):
    def test_majority_prefix(self):
        paths = ["/api/v1/a/x", "/api/v1/a/y", "/api/v1/b", "/health", "/docs"]
        self.assertEqual(groups.global_prefix(paths), ["api", "v1"])

    def test_no_majority_means_empty_prefix(self):
        self.assertEqual(groups.global_prefix(["/a/x", "/b/x", "/c/x"]), [])

    def test_empty_input(self):
        self.assertEqual(groups.global_prefix([]), [])

    def test_a_route_equal_to_the_prefix_is_allowed(self):
        self.assertEqual(groups.global_prefix(["/api", "/api/x", "/api/y"]), ["api"])

    def test_query_strings_and_slashes_are_ignored(self):
        self.assertEqual(groups.split_path("/a//b/?x=1"), ["a", "b"])


class GroupTests(unittest.TestCase):
    def test_routes_group_by_segment_after_prefix_with_root_group(self):
        routes = [route("r1", "/api/v1/teams"), route("r2", "/api/v1/teams/{id}"),
                  route("r3", "/api/v1/users"), route("r4", "/health"), route("r5", "/api/v1")]
        result = groups.group_routes(routes)
        self.assertEqual(
            [(g["id"], g["key"], [r["id"] for r in g["routes"]]) for g in result],
            [("G01", "(root)", ["r4", "r5"]), ("G02", "teams", ["r1", "r2"]), ("G03", "users", ["r3"])],
        )

    def test_ids_widen_for_many_groups(self):
        routes = [route(f"r{i}", f"/svc/k{i:03d}") for i in range(120)]
        result = groups.group_routes(routes)
        self.assertEqual(result[0]["id"], "G001")
        self.assertEqual(result[-1]["id"], "G120")

    def test_no_routes_means_no_groups(self):
        self.assertEqual(groups.group_routes([]), [])

    def test_screens_group_by_first_segment(self):
        screens = [{"id": "s1", "path": "/admin/users"}, {"id": "s2", "path": "/admin"},
                   {"id": "s3", "path": "/login"}, {"id": "s4", "path": "/"}]
        result = groups.group_screens(screens)
        self.assertEqual(
            [(g["id"], g["key"], [s["id"] for s in g["screens"]]) for g in result],
            [("S01", "(root)", ["s4"]), ("S02", "admin", ["s1", "s2"]), ("S03", "login", ["s3"])],
        )


if __name__ == "__main__":
    unittest.main()
