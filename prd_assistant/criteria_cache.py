"""The criteria cache: where the facts live, when they are stale, and how they are rebuilt without half-writes."""
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import cgdb, criteria, draft, pipeline

IGNORED_PREFIXES = (".codegraph/",)   # CodeGraph's own index changes whenever its watcher syncs


class EnvError(RuntimeError):
    """The environment or input is unusable (exit 3)."""


class FactsUnavailable(RuntimeError):
    """The facts cannot be trusted or produced (exit 2)."""


def state_root(override=None):
    if override:
        return Path(override)
    env = os.environ.get("PRD_ASSISTANT_STATE")
    return Path(env) if env else Path.home() / ".claude" / "state" / "prd-assistant"


def repo_dir_name(repo):
    path = Path(repo).resolve()
    name = re.sub(r"[^A-Za-z0-9._-]", "_", path.name).strip("._") or "repo"
    return f"{name[:40]}-{hashlib.sha256(str(path).encode()).hexdigest()[:8]}"


def _git(repo, *args):
    """Read-only git (never takes optional locks). None when git is missing or the command fails."""
    try:
        run = subprocess.run(["git", "--no-optional-locks", "-C", str(repo), *args],
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return run.stdout if run.returncode == 0 else None


def fingerprint(repo):
    repo = Path(repo).resolve()
    head = _git(repo, "rev-parse", "HEAD")
    status = _git(repo, "status", "--porcelain=v1", "-uall")
    if head is None or status is None:
        return {"git": False, "head": None, "dirty": None, "changed": None}
    digest, changed = hashlib.sha256(), 0
    for line in status.splitlines():
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip('"')
        if path.startswith(IGNORED_PREFIXES):
            continue
        changed += 1
        try:
            st = (repo / path).stat()
            stamp = f"{st.st_size}:{st.st_mtime_ns}"
        except OSError:
            stamp = "missing"
        digest.update(f"{line}\0{stamp}\0".encode())
    return {"git": True, "head": head.strip(), "dirty": digest.hexdigest(), "changed": changed}


def is_fresh(meta, fp):
    return bool(fp["git"] and meta and meta.get("tool_version") == criteria.TOOL_VERSION
                and meta.get("schema_version") == 1 and meta.get("head") == fp["head"]
                and meta.get("dirty") == fp["dirty"])


def _read_meta(cache):
    try:
        return json.loads((Path(cache) / "meta.json").read_text())
    except (OSError, ValueError):
        return None


def load_bank(cache):
    return json.loads((Path(cache) / "criteria.json").read_text())


def _swap(work, final):
    old = None
    if final.exists():
        old = final.with_name(f"{final.name}.old-{os.getpid()}")
        os.rename(final, old)
    try:
        os.rename(work, final)
    except OSError:
        if old is not None:
            os.rename(old, final)   # put the previous cache back
        raise
    if old is not None:
        shutil.rmtree(old, ignore_errors=True)


def build(repo, root, fp):
    repo = Path(repo).resolve()
    if not repo.is_dir():
        raise EnvError(f"{repo} is not a directory")
    if not (repo / ".codegraph" / "codegraph.db").is_file():
        raise EnvError(f"{repo} has no CodeGraph index (.codegraph/codegraph.db); run `codegraph init` there first. "
                       "Nothing was built.")
    try:
        root.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=".build-", dir=root))
    except OSError as exc:
        raise EnvError(f"cannot create the state directory {root}: {exc}") from exc
    final = root / repo_dir_name(repo)
    try:
        facts, result = pipeline.run(repo)
        pipeline.write_outputs(work, facts, result)
        if result["verdict"] == "FAIL":
            raise FactsUnavailable("the slice 1 gate is FAIL, so the facts cannot be trusted; "
                                   "run bin/prd_facts.py on the repo to see why")
        draft.dev_prepare(repo, work)
        dev = work / "dev"
        roles, rules, errors = (json.loads((dev / n).read_text())
                                for n in ("roles.json", "form_rules.json", "error_messages.json"))
        bank = criteria.build_bank(facts, roles, rules, errors)
        meta = {"schema_version": 1, "tool_version": criteria.TOOL_VERSION, "repo": str(repo), "head": fp["head"],
                "dirty": fp["dirty"], "changed": fp["changed"], "git": fp["git"],
                "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "codegraph_commit": facts.get("meta", {}).get("indexed_at_commit"), "counts": bank["counts"],
                "routes": len(facts["routes"]), "screens": len(facts["screens"])}
        (work / "criteria.json").write_text(json.dumps(bank, indent=1, ensure_ascii=False))
        (work / "meta.json").write_text(json.dumps(meta, indent=1))
        _swap(work, final)
    except draft.GateFailed as exc:
        raise FactsUnavailable(str(exc)) from exc
    except ValueError as exc:
        raise EnvError(str(exc)) from exc
    except (cgdb.VersionError, FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
        raise EnvError(str(exc)) from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)   # a no-op after a successful swap
    return final, meta


def ensure(repo, state_dir=None, force=False):
    repo = Path(repo)
    if not repo.is_dir():
        raise EnvError(f"{repo} is not a directory")
    root = state_root(state_dir)
    final = root / repo_dir_name(repo)
    fp = fingerprint(repo)
    meta = _read_meta(final)
    if not force and is_fresh(meta, fp):
        return final, meta, False
    final, meta = build(repo, root, fp)
    return final, meta, True
