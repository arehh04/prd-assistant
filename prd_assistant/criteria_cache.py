"""The criteria cache: where the facts live, when they are stale, and how they are rebuilt without half-writes."""
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
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


MAX_HASH_BYTES = 5_000_000


def _git(repo, *args):
    """Read-only git (never takes optional locks). None when git is missing or the command fails."""
    try:
        run = subprocess.run(["git", "--no-optional-locks", "-C", str(repo), *args], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return run.stdout.decode("utf-8", "surrogateescape") if run.returncode == 0 else None


def _stamp(full):
    """What identifies the current state of one changed path: its content (hashed), or for a nested repository
    its HEAD and status. Size and mtime alone are not enough: a restore or rsync keeps the mtime."""
    try:
        if full.is_dir():
            head = _git(full, "rev-parse", "HEAD") or ""
            status = _git(full, "status", "--porcelain=v1", "-z", "-uall") or ""
            return b"dir:" + hashlib.sha256((head + "\0" + status).encode("utf-8", "surrogateescape")).digest()
        st = full.stat()
        if st.st_size <= MAX_HASH_BYTES:
            return b"file:" + hashlib.sha256(full.read_bytes()).digest()
        return f"big:{st.st_size}:{st.st_mtime_ns}".encode()
    except OSError:
        return b"missing"


def fingerprint(repo):
    repo = Path(repo).resolve()
    top = _git(repo, "rev-parse", "--show-toplevel")
    head = _git(repo, "rev-parse", "HEAD")
    status = _git(repo, "status", "--porcelain=v1", "-z", "-uall")
    if top is None or head is None or status is None:
        return {"git": False, "head": None, "dirty": None, "changed": None}
    base = Path(top.strip()).resolve()     # git reports paths relative to the repository root, not to `repo`
    try:
        rel = repo.relative_to(base).as_posix()
    except ValueError:
        rel = "."
    ignored = tuple(prefix if rel == "." else f"{rel}/{prefix}" for prefix in IGNORED_PREFIXES)
    digest, changed, entries, i = hashlib.sha256(), 0, status.split("\0"), 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, path = entry[:2], entry[3:]
        if xy[0] in "RC":
            i += 1    # in -z output a rename or copy is followed by its source path
        if path.startswith(ignored):
            continue
        changed += 1
        digest.update(f"{xy}\0{path}\0".encode("utf-8", "surrogateescape"))
        digest.update(_stamp(base / path))
    return {"git": True, "head": head.strip(), "dirty": digest.hexdigest(), "changed": changed}


def is_fresh(meta, fp):
    return bool(fp["git"] and meta and meta.get("tool_version") == criteria.TOOL_VERSION
                and meta.get("schema_version") == 1 and meta.get("head") == fp["head"]
                and meta.get("dirty") == fp["dirty"])


def _read_meta(cache):
    try:
        data = json.loads((Path(cache) / "meta.json").read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_bank(cache):
    return json.loads((Path(cache) / "criteria.json").read_text())


def _bank_ok(cache):
    try:
        bank = load_bank(cache)
    except (OSError, ValueError):
        return False
    return (isinstance(bank, dict) and isinstance(bank.get("candidates"), list)
            and isinstance(bank.get("counts"), dict) and isinstance(bank.get("groups"), list))


def _swap(work, final):
    for _ in range(3):
        old = final.with_name(f"{final.name}.old-{os.getpid()}")
        shutil.rmtree(old, ignore_errors=True)    # a leftover of a crashed run with the same pid
        moved = False
        try:
            os.rename(final, old)
            moved = True
        except FileNotFoundError:
            pass                                   # another run moved it first, or there was no cache yet
        try:
            os.rename(work, final)
        except OSError:
            if moved:
                try:
                    os.rename(old, final)          # put the previous cache back, then try again
                except OSError:
                    pass
            continue
        if moved:
            shutil.rmtree(old, ignore_errors=True)
        return
    raise OSError("could not put the rebuilt cache in place")


def _sweep(root, max_age=3600):
    """Remove build and replaced-cache directories that a crashed run left behind (never recent ones)."""
    now = time.time()
    for p in root.iterdir():
        if (p.name.startswith(".build-") or ".old-" in p.name) and p.is_dir():
            try:
                if now - p.stat().st_mtime > max_age:
                    shutil.rmtree(p, ignore_errors=True)
            except OSError:
                pass


def build(repo, root, fp):
    repo = Path(repo).resolve()
    if not repo.is_dir():
        raise EnvError(f"{repo} is not a directory")
    if not (repo / ".codegraph" / "codegraph.db").is_file():
        raise EnvError(f"{repo} has no CodeGraph index (.codegraph/codegraph.db); run `codegraph init` there first. "
                       "Nothing was built.")
    try:
        root.mkdir(parents=True, exist_ok=True)
        _sweep(root)
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
    here, there = repo.resolve(), root.resolve()
    if there == here or here in there.parents:
        raise EnvError(f"the state directory {root} must be outside the repo {repo}")
    final = root / repo_dir_name(repo)
    fp = fingerprint(repo)
    meta = _read_meta(final)
    if not force and is_fresh(meta, fp) and _bank_ok(final):
        return final, meta, False
    final, meta = build(repo, root, fp)
    return final, meta, True


def _read_json(path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def ensure_bank(repo, state_dir=None, force=False):
    """(cache, meta, rebuilt, bank). Retries once if a concurrent rebuild swapped the cache away."""
    for attempt in (1, 2):
        try:
            cache, meta, rebuilt = ensure(repo, state_dir, force=force)
            bank = load_bank(cache)
            break
        except FileNotFoundError:
            if attempt == 2:
                raise
    if not isinstance(bank, dict) or not all(k in bank for k in ("candidates", "counts", "groups")):
        raise ValueError(f"the cached criteria.json in {cache} is malformed; run `build` to recreate it")
    return cache, meta, rebuilt, bank


def status(repo, state_dir=None):
    """What a lookup would find, without building anything and without creating any directory."""
    repo = Path(repo)
    if not repo.is_dir():
        raise EnvError(f"{repo} is not a directory")
    root = state_root(state_dir)
    here, there = repo.resolve(), root.resolve()
    if there == here or here in there.parents:
        raise EnvError(f"the state directory {root} must be outside the repo {repo}")
    final = root / repo_dir_name(repo)
    fp = fingerprint(repo)
    meta = _read_meta(final)
    index = (here / ".codegraph" / "codegraph.db").is_file()
    reasons = []
    if not final.exists():
        cache = "missing"
    elif meta is None:
        cache, reasons = "stale", ["the cache is malformed (meta.json is unreadable)"]
    else:
        if meta.get("tool_version") != criteria.TOOL_VERSION or meta.get("schema_version") != 1:
            reasons.append("the tool version differs")
        if not fp["git"]:
            reasons.append("not a git repository or it has no commits (rebuilt on every run)")
        else:
            if meta.get("head") != fp["head"]:
                reasons.append("the commit differs")
            if meta.get("dirty") != fp["dirty"]:
                reasons.append(f"the working tree differs ({fp['changed']} changed files)")
        if not _bank_ok(final):
            reasons.append("the cache is malformed (criteria.json is missing or unreadable)")
        cache = "fresh" if not reasons else "stale"
    gate, dev_gate = _read_json(final / "gate.json"), _read_json(final / "dev" / "dev_gate.json")
    counts = None
    if meta and isinstance(meta.get("counts"), dict):
        counts = {"routes": meta.get("routes"), "screens": meta.get("screens"), "candidates": meta["counts"]}
    if not index:
        next_step = f"There is no CodeGraph index: run `codegraph init` in {here.name} first."
    elif cache == "missing":
        next_step = "There is no cache yet: the next lookup builds it (seconds to a few minutes)."
    elif cache == "stale":
        next_step = "The facts are stale; the next lookup rebuilds them."
    else:
        next_step = "The facts are fresh."
    return {"repo": str(here), "index_present": index, "git": fp["git"], "cache": cache, "reasons": reasons,
            "head": meta.get("head") if meta else None, "built_at": meta.get("built_at") if meta else None,
            "codegraph_commit": meta.get("codegraph_commit") if meta else None,
            "cache_path": str(final) if final.exists() else None,
            "gates": {"slice1": (gate or {}).get("verdict"), "dev": (dev_gate or {}).get("verdict")},
            "counts": counts, "coverage": _read_json(final / "dev" / "dev_summary.json"), "next_step": next_step}
