import unittest

from prd_assistant import paths


class PathsTests(unittest.TestCase):
    def test_test_directories_and_names_are_excluded(self):
        for p in ("tests/test_x.py", "frontend/src/__tests__/mount.ts", "e2e/login.ts",
                  "apps/api/src/a.controller.spec.ts", "backend/tests/Feature/AuthTest.php",
                  "web/src/Button.test.tsx", "svc/test_users.py", "svc/users_test.py"):
            self.assertEqual(paths.exclusion_reason(p), "test", p)

    def test_normal_source_is_kept(self):
        for p in ("backend/app/Http/Controllers/Api/V1/BranchController.php",
                  "src/Testimonials.tsx", "app/Contest.php", "apps/api/src/app.controller.ts"):
            self.assertIsNone(paths.exclusion_reason(p), p)

    def test_generated_flag_wins(self):
        self.assertEqual(paths.exclusion_reason("src/api/client.ts", generated=True), "generated")


if __name__ == "__main__":
    unittest.main()
