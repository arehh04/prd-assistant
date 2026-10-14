"""Which files are test, mock or generated code (excluded from route and screen lists)."""
import fnmatch
from pathlib import PurePosixPath

TEST_DIR_PARTS = {"tests", "test", "__tests__", "__mocks__", "e2e", "fixtures", "spec", "mocks"}
TEST_NAME_GLOBS = (
    "test_*.py", "*_test.py",
    "*.spec.ts", "*.spec.tsx", "*.spec.js", "*.test.ts", "*.test.tsx", "*.test.js", "*.test.mjs",
    "*Test.php", "*Tests.php",
)


def exclusion_reason(path, generated=False):
    """Return "generated", "test", or None for a repo-relative posix path."""
    if generated:
        return "generated"
    p = PurePosixPath(path)
    if TEST_DIR_PARTS & {part.lower() for part in p.parts[:-1]}:
        return "test"
    if any(fnmatch.fnmatchcase(p.name, glob) for glob in TEST_NAME_GLOBS):
        return "test"
    return None
