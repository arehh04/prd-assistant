import tempfile
import unittest
from pathlib import Path

from prd_assistant.adapters import laravel

API = """<?php
use App\\Http\\Controllers\\Api\\V1\\AuthController;
use App\\Http\\Controllers\\Api\\V1\\HealthController as Health;
use Illuminate\\Support\\Facades\\Route;

// Route::get('/commented', [AuthController::class, 'nope']);
/* Route::post('/blocked', X::class); */
Route::get('/health', Health::class)->name('health');
Route::post('/auth/login', [AuthController::class, 'login'])->middleware('throttle:login');
Route::prefix('admin')->group(function (): void {
    Route::get('/users/{user}', [AuthController::class, 'me']);
    Route::get('/closure', function () { return 'x // not a comment'; });
});
Route::middleware(['auth'])->group(function (): void {
    Route::delete('/session', [AuthController::class, 'logout']);
});
Route::resource('photos', PhotoController::class);
Route::middleware('auth')->get('/chained', [AuthController::class, 'me']);
"""


def find_line(content, needle):
    for number, line in enumerate(content.splitlines(), start=1):
        if needle in line:
            return number
    raise AssertionError(needle)


class ParseFileTests(unittest.TestCase):
    def setUp(self):
        self.routes, self.unsupported = laravel.parse_file(API, "backend/routes/api.php", "api/v1")
        self.by_path = {r["path"]: r for r in self.routes}

    def test_plain_routes_with_prefix_and_comments_ignored(self):
        self.assertEqual(
            sorted(self.by_path),
            ["/api/v1/admin/closure", "/api/v1/admin/users/{user}", "/api/v1/auth/login",
             "/api/v1/health", "/api/v1/session"],
        )

    def test_methods_lines_and_ids(self):
        login = self.by_path["/api/v1/auth/login"]
        self.assertEqual(login["method"], "POST")
        self.assertEqual(login["line"], find_line(API, "'/auth/login'"))
        self.assertEqual(login["source"], f"backend/routes/api.php:{login['line']}")
        self.assertEqual(login["id"], f"route:backend/routes/api.php:{login['line']}:POST:/api/v1/auth/login")
        self.assertEqual(login["origin"], "adapter:laravel")
        self.assertEqual(self.by_path["/api/v1/session"]["method"], "DELETE")

    def test_handler_resolution_via_imports(self):
        self.assertEqual(self.by_path["/api/v1/auth/login"]["handler_qualified_name"],
                         "App\\Http\\Controllers\\Api\\V1::AuthController::login")
        self.assertEqual(self.by_path["/api/v1/health"]["handler_qualified_name"],
                         "App\\Http\\Controllers\\Api\\V1::HealthController::__invoke")
        self.assertIsNone(self.by_path["/api/v1/admin/closure"]["handler_qualified_name"])

    def test_unsupported_constructs_are_reported_not_guessed(self):
        found = {(u["line"]) for u in self.unsupported}
        self.assertEqual(found, {find_line(API, "Route::resource"), find_line(API, "->get('/chained'")})
        self.assertNotIn("/api/v1/chained", self.by_path)

    def test_empty_api_prefix_and_root_path(self):
        routes, _ = laravel.parse_file("<?php\nRoute::get('/', [A::class, 'i']);\n", "r.php", "")
        self.assertEqual(routes[0]["path"], "/")


class LoadTests(unittest.TestCase):
    def test_load_reads_prefix_from_bootstrap_and_skips_web_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "backend/routes").mkdir(parents=True)
            (root / "backend/bootstrap").mkdir(parents=True)
            (root / "backend/bootstrap/app.php").write_text(
                "<?php\nreturn Application::configure()->withRouting(\n    api: __DIR__.'/../routes/api.php',\n"
                "    apiPrefix: 'api/v1',\n);\n")
            (root / "backend/routes/api.php").write_text("<?php\nRoute::get('/ping', [P::class, 'i']);\n")
            (root / "backend/routes/web.php").write_text("<?php\nRoute::get('/welcome', [W::class, 'i']);\n")
            routes, unsupported = laravel.load(root)
        self.assertEqual(sorted((r["file"], r["path"]) for r in routes),
                         [("backend/routes/api.php", "/api/v1/ping"),
                          ("backend/routes/web.php", "/welcome")])
        self.assertEqual(unsupported, [])

    def test_default_api_prefix_is_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "routes").mkdir()
            (root / "routes/api.php").write_text("<?php\nRoute::get('/ping', [P::class, 'i']);\n")
            routes, _ = laravel.load(root)
        self.assertEqual(routes[0]["path"], "/api/ping")


if __name__ == "__main__":
    unittest.main()
