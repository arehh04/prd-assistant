import tempfile
import unittest
from pathlib import Path

from prd_assistant import count


def write(root, rel, text, binary=False):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if binary:
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8", newline="")
    return path


class DetectTests(unittest.TestCase):
    def test_detects_each_framework_and_ignores_node_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "backend/composer.json", '{"require": {"laravel/framework": "^11"}}')
            write(tmp, "apps/api/package.json", '{"dependencies": {"@nestjs/core": "1", "express": "4"}}')
            write(tmp, "web/package.json", '{"dependencies": {"vue-router": "4", "react-router-dom": "7"}}')
            write(tmp, "requirements.txt", "FastAPI==0.1\nuvicorn\n")
            write(tmp, "node_modules/x/package.json", '{"dependencies": {"@nestjs/core": "1"}}')
            self.assertEqual(
                count.detect_frameworks(tmp),
                {"laravel", "nestjs", "express", "vue-router", "react-router", "fastapi"},
            )

    def test_no_framework_detected_in_an_empty_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "README.md", "hello")
            self.assertEqual(count.detect_frameworks(tmp), set())


class RouteCounterTests(unittest.TestCase):
    def test_fastapi_decorators_with_crlf_and_bom(self):
        content = ("﻿router = APIRouter()\r\n\r\n@router.get('/a')\r\ndef a(): ...\r\n\r\n"
                   "@app.post(\"/b\")\r\ndef b(): ...\r\n").encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "app/api.py", content, binary=True)
            write(tmp, "tests/test_api.py", "@router.get('/t')\ndef t(): ...\n")
            hits = count.independent_routes(tmp, {"fastapi"})
        self.assertEqual(hits, {("app/api.py", 3), ("app/api.py", 6)})

    def test_non_utf8_bytes_do_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "app/api.py", b"# caf\xe9\n@router.get('/a')\ndef a(): ...\n", binary=True)
            self.assertEqual(count.independent_routes(tmp, {"fastapi"}), {("app/api.py", 2)})

    def test_nest_decorators(self):
        src = "@Controller('x')\nexport class C {\n  @Get()\n  a() {}\n\n  @Post('y')\n  b() {}\n  // @Delete('z')\n}\n"
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "apps/api/src/c.controller.ts", src)
            self.assertEqual(count.independent_routes(tmp, {"nestjs"}),
                             {("apps/api/src/c.controller.ts", 3), ("apps/api/src/c.controller.ts", 6)})

    def test_express_needs_a_literal_path_and_a_router_like_receiver(self):
        src = "app.get('/a', h)\nrouter.post(\"/b\", h)\ncache.get('key')\nmap.get(key)\nusersRouter.delete('/c', h)\n// app.get('/d', h)\n"
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "server.js", src)
            self.assertEqual(count.independent_routes(tmp, {"express"}),
                             {("server.js", 1), ("server.js", 2), ("server.js", 5)})

    def test_laravel_route_calls_ignore_comments_and_non_route_dirs(self):
        src = ("<?php\n// Route::get('/commented', X);\n/* Route::post('/block', X); */\n"
               "Route::get('/a', [A::class, 'i']);\nRoute::post('/b', B::class);\n")
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "backend/routes/api.php", src)
            write(tmp, "backend/app/Other.php", "<?php\nRoute::get('/not-a-routes-file', X);\n")
            self.assertEqual(count.independent_routes(tmp, {"laravel"}),
                             {("backend/routes/api.php", 4), ("backend/routes/api.php", 5)})

    def test_frameworks_not_requested_are_not_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "app/api.py", "@router.get('/a')\ndef a(): ...\n")
            self.assertEqual(count.independent_routes(tmp, set()), set())


if __name__ == "__main__":
    unittest.main()
