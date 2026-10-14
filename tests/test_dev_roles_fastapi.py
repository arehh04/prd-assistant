import tempfile
import unittest
from pathlib import Path

from prd_assistant.dev import pyast, roles_fastapi

DEPS = '''from fastapi import Depends, HTTPException
ADMIN_LIKE = (UserType.admin, UserType.developer)


async def require_user(authorization=Header(default=None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    return {}


async def require_admin(auth_data=Depends(require_user)):
    if auth_data["type"] not in ADMIN_LIKE:
        raise HTTPException(status_code=403, detail="Admin access required")
    return auth_data


async def require_developer(auth_data=Depends(require_user)):
    if auth_data["type"] != UserType.developer:
        raise HTTPException(status_code=403, detail="Access denied")
    return auth_data


async def mystery(x=Depends(other_thing)):
    return x
'''
ROUTES = '''from fastapi import APIRouter, Depends
router = APIRouter()


@router.get("/open")
async def open_page():
    return 1


@router.get("/me")
async def me(user=Depends(require_user)):
    return user


@router.delete("/users/{id}")
async def delete_user(id: str, who=Depends(require_admin)):
    return id


@router.post("/dev", dependencies=[Depends(require_developer)])
async def dev_only():
    return 1


@router.get("/odd")
async def odd(x=Depends(mystery)):
    return x


@router.get("/both")
async def both(a=Depends(require_admin), b=Depends(require_developer)):
    return 1
'''


def line_of(text, needle):
    return next(i for i, l in enumerate(text.splitlines(), 1) if needle in l)


class FastApiRolesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "api").mkdir()
        (root / "api" / "dependencies.py").write_text(DEPS)
        (root / "api" / "users.py").write_text(ROUTES)
        self.idx = pyast.PyIndex(root)
        self.addCleanup(self.tmp.cleanup)

    def rec(self, needle):
        tree = self.idx.trees["api/users.py"]
        return roles_fastapi.read_roles("api/users.py", tree, ROUTES, line_of(ROUTES, needle), self.idx)

    def test_no_dependency_is_undeclared_and_open(self):
        r = self.rec("async def open_page")
        self.assertEqual((r["status"], r["undeclared_means"]), ("undeclared", "open"))

    def test_sign_in_only(self):
        r = self.rec("async def me")
        self.assertEqual((r["status"], r["roles"], r["authenticated"]), ("read", None, True))
        self.assertTrue(r["guards"][0].startswith("api/dependencies.py:"))

    def test_role_check_in_the_dependency_body_with_a_module_constant(self):
        r = self.rec("async def delete_user")
        self.assertEqual((r["status"], r["roles"]), ("read", ["admin", "developer"]))
        self.assertIn("require_admin", r["via"][0])
        self.assertIn("require_user", r["via"][0])

    def test_dependency_listed_on_the_decorator(self):
        self.assertEqual(self.rec("async def dev_only")["roles"], ["developer"])

    def test_unrecognised_dependency_is_not_read(self):
        r = self.rec("async def odd")
        self.assertEqual(r["status"], "not_read")
        self.assertIn("mystery", r["reason"])

    def test_two_role_dependencies_intersect(self):
        self.assertEqual(self.rec("async def both")["roles"], ["developer"])

    def test_router_level_dependencies_are_noted(self):
        text = ROUTES.replace("router = APIRouter()", "router = APIRouter(dependencies=[Depends(require_user)])")
        tree = pyast.py_tree(text)
        r = roles_fastapi.read_roles("api/users.py", tree, text, line_of(text, "async def open_page"), self.idx)
        self.assertEqual(r["status"], "undeclared")
        self.assertTrue(any("router-level" in n for n in r["notes"]))

    def test_handler_not_found_is_not_read(self):
        tree = self.idx.trees["api/users.py"]
        r = roles_fastapi.read_roles("api/users.py", tree, ROUTES, 9999, self.idx)
        self.assertEqual(r["status"], "not_read")


if __name__ == "__main__":
    unittest.main()
