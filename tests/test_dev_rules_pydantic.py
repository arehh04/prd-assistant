import tempfile
import unittest
from pathlib import Path

from prd_assistant.dev import pyast, rules_pydantic

MODELS = '''from pydantic import BaseModel, Field
from typing import Optional, Literal, Annotated


class Base(BaseModel):
    created_by: str


class CreateTeam(Base):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    kind: Literal["open", "closed"] = "open"
    size: Annotated[int, Field(ge=1, le=50)]

    @field_validator("name")
    def check(cls, v):
        return v
'''
ROUTES = '''from fastapi import APIRouter, Depends, Query, Request
router = APIRouter()


@router.post("/teams/{team_id}")
async def create(team_id: str, body: CreateTeam, request: Request, limit: int = Query(10, ge=1, le=100), who=Depends(dep)):
    return 1


@router.get("/plain")
async def plain():
    return 1


@router.post("/upload")
async def upload(file: UploadFile = File(...), kind: str = Form(...), note: str = Form("x")):
    return 1
'''


def line_of(text, needle):
    return next(i for i, l in enumerate(text.splitlines(), 1) if needle in l)


class PydanticRulesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "api").mkdir()
        (root / "api" / "models.py").write_text(MODELS)
        (root / "api" / "teams.py").write_text(ROUTES)
        self.idx = pyast.PyIndex(root)
        self.addCleanup(self.tmp.cleanup)

    def rec(self, needle, path):
        return rules_pydantic.read_request("api/teams.py", self.idx.trees["api/teams.py"],
                                           line_of(ROUTES, needle), path, self.idx)

    def test_path_query_and_body_model_fields(self):
        r = self.rec("async def create", "/teams/{team_id}")
        by = {(f["name"], f["location"]): f for f in r["fields"]}
        self.assertEqual(by[("team_id", "path")]["required"], True)
        limit = by[("limit", "query")]
        self.assertEqual((limit["required"], limit["min"], limit["max"]), (False, 1, 100))
        name = by[("name", "body")]
        self.assertEqual((name["required"], name["min"], name["max"]), (True, 1, 100))
        self.assertFalse(by[("description", "body")]["required"])
        self.assertTrue(by[("description", "body")]["nullable"])
        self.assertEqual(by[("kind", "body")]["one_of"], ["open", "closed"])
        size = by[("size", "body")]
        self.assertEqual((size["required"], size["min"], size["max"]), (True, 1, 50))
        self.assertTrue(by[("created_by", "body")]["required"])   # inherited field

    def test_dependencies_requests_and_unrelated_params_are_not_fields(self):
        r = self.rec("async def create", "/teams/{team_id}")
        self.assertEqual({f["name"] for f in r["fields"]} & {"request", "who"}, set())

    def test_validators_are_noted(self):
        r = self.rec("async def create", "/teams/{team_id}")
        self.assertTrue(any("validators" in n for n in r["notes"]))

    def test_handler_without_params(self):
        r = self.rec("async def plain", "/plain")
        self.assertEqual((r["fields"], r["not_read"]), ([], []))

    def test_upload_and_form_parameters_are_body_fields(self):
        r = self.rec("async def upload", "/upload")
        by = {f["name"]: f for f in r["fields"]}
        self.assertEqual(r["not_read"], [])
        self.assertEqual((by["file"]["location"], by["file"]["required"]), ("body", True))
        self.assertEqual((by["kind"]["location"], by["kind"]["required"]), ("body", True))
        self.assertFalse(by["note"]["required"])

    def test_unknown_model_is_not_read(self):
        text = ROUTES.replace("body: CreateTeam", "body: NoSuchModel")
        tree = pyast.py_tree(text)
        r = rules_pydantic.read_request("api/teams.py", tree, line_of(text, "async def create"),
                                        "/teams/{team_id}", self.idx)
        self.assertTrue(any("NoSuchModel" in n for n in r["not_read"]))


if __name__ == "__main__":
    unittest.main()
