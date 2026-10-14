"""Deterministic checks on extracted facts. Every check prints its raw numbers."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

from . import cgdb, count

SOURCE_SUFFIXES = (".py", ".php", ".ts", ".tsx", ".js", ".jsx", ".vue", ".mjs", ".cjs")
ROUTEISH_RE = re.compile(r"(?i)(controller|router|route)")
ORDER = {"PASS": 0, "WARN": 1, "FAIL": 2}


def load_config(path=None):
    path = Path(path) if path else Path(__file__).with_name("gate_config.json")
    return json.loads(path.read_text())


def compare(extracted, independent):
    extracted, independent = set(extracted), set(independent)
    missing = sorted(independent - extracted)
    extra = sorted(extracted - independent)
    if independent:
        ratio = (len(missing) + len(extra)) / len(independent)
    else:
        ratio = 0.0 if not extracted else 1.0
    return {"independent": len(independent), "extracted": len(extracted),
            "missing_in_codegraph": missing, "extra_in_codegraph": extra,
            "disagreement": round(ratio, 4)}


def grade(ratio, thresholds):
    if ratio <= thresholds["pass"]:
        return "PASS"
    if ratio <= thresholds["warn"]:
        return "WARN"
    return "FAIL"


def git_head(repo_root):
    try:
        done = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def _agreement(name, extracted, independent, applicable, thresholds, empty_ok_note):
    if not applicable:
        extracted_n = len(extracted)
        if extracted_n == 0:
            return {"name": name, "status": "PASS", "detail": {"note": empty_ok_note}}
        return {"name": name, "status": "WARN",
                "detail": {"note": "no independent counter applies to the detected frameworks; "
                                   "extracted facts could not be cross-checked", "extracted": extracted_n}}
    detail = compare(extracted, independent)
    return {"name": name, "status": grade(detail["disagreement"], thresholds), "detail": detail}


def disk_sources(repo_root):
    return {rel for rel, _ in count.iter_files(repo_root, SOURCE_SUFFIXES, include_tests=True)}


def staleness(conn, repo_root, route_files, head, disk):
    repo_root = Path(repo_root)
    touched, indexed_paths = [], set()
    for row in conn.execute("select path, content_hash from files"):
        indexed_paths.add(row["path"])
        full = repo_root / row["path"]
        try:
            changed = hashlib.sha256(full.read_bytes()).hexdigest() != row["content_hash"]
        except OSError:  # deleted, or unreadable now: either way the index no longer matches disk
            changed = True
        if changed:
            touched.append(row["path"])
    relevant = [p for p in touched if p in route_files or ROUTEISH_RE.search(p)]
    # A route/router/controller file that appeared after indexing is invisible to CodeGraph.
    new_routeish = sorted(p for p in disk - indexed_paths if ROUTEISH_RE.search(p))
    relevant += new_routeish
    indexed = cgdb.get_meta(conn, "indexed_at_commit")
    status = "FAIL" if relevant else ("WARN" if touched else "PASS")
    return {"name": "index_staleness", "status": status, "detail": {
        "indexed_at_commit": indexed, "git_head": head,
        "commit_matches": None if not (indexed and head) else indexed == head,
        "changed_files": len(touched), "relevant_changed": relevant, "new_unindexed_route_files": new_routeish,
        "sample_changed": touched[:20]}}


def coverage(conn, disk, thresholds):
    indexed = {r["path"] for r in conn.execute("select path from files")}
    ratio = len(disk & indexed) / len(disk) if disk else 1.0
    status = "FAIL" if ratio < thresholds["fail"] else ("WARN" if ratio < thresholds["warn"] else "PASS")
    return {"name": "language_coverage", "status": status, "detail": {
        "source_files_on_disk": len(disk), "indexed": len(disk & indexed), "ratio": round(ratio, 4),
        "not_indexed_sample": sorted(disk - indexed)[:20]}}


def run(conn, repo_root, facts, frameworks, cfg=None, head="auto"):
    cfg = cfg or load_config()
    head = git_head(repo_root) if head == "auto" else head
    frameworks = set(frameworks)
    routes_x = {(r["file"], r["line"]) for r in facts["routes"]}
    screens_x = {(s["file"], s["line"]) for s in facts["screens"]}
    checks = [
        _agreement("route_agreement", routes_x, count.independent_routes(repo_root, frameworks),
                   bool(frameworks & count.BACKEND_FRAMEWORKS), cfg["route_agreement"],
                   "no backend framework detected and no routes extracted"),
        _agreement("screen_agreement", screens_x, count.independent_screens(repo_root, frameworks),
                   bool(frameworks & count.SCREEN_FRAMEWORKS), cfg["screen_agreement"],
                   "no router framework detected and no screens extracted"),
    ]
    # No framework at all: we cannot vouch for anything, so say so instead of passing.
    if not frameworks:
        checks[0] = {"name": "route_agreement", "status": "WARN",
                     "detail": {"note": "no framework detected, so no independent counter ran; "
                                        "this repo's facts are unverified", "extracted": len(routes_x)}}
    route_files = {r["file"] for r in facts["routes"]} | {s["file"] for s in facts["screens"]}
    disk = disk_sources(repo_root)
    checks.append(staleness(conn, repo_root, route_files, head, disk))
    checks.append(coverage(conn, disk, cfg["language_coverage"]))
    unsupported = [u for a in facts.get("adapters", {}).values() for u in a.get("unsupported", [])]
    checks.append({"name": "adapter_unsupported", "status": "WARN" if unsupported else "PASS",
                   "detail": {"count": len(unsupported), "items": unsupported[:20]}})
    unreadable = count.unreadable_paths()
    checks.append({"name": "unreadable_files", "status": "WARN" if unreadable else "PASS",
                   "detail": {"count": len(unreadable), "items": unreadable[:20]}})
    reached = {n["to_id"] for n in facts["navigation"]}
    checks.append({"name": "orphans", "status": "INFO", "detail": {
        "routes_without_handler": [r["id"] for r in facts["routes"] if not r.get("handler")],
        "screens_not_navigated_to": [s["id"] for s in facts["screens"] if s["id"] not in reached]}})
    by_reason = {}
    for e in facts["excluded"]:
        by_reason[e["reason"]] = by_reason.get(e["reason"], 0) + 1
    checks.append({"name": "exclusions", "status": "INFO", "detail": {
        "total": len(facts["excluded"]), "by_reason": by_reason}})
    graded = [c["status"] for c in checks if c["status"] in ORDER]
    verdict = max(graded, key=ORDER.get)
    return {"verdict": verdict, "checks": checks, "thresholds": cfg}


def summary(result):
    by_name = {c["name"]: c for c in result["checks"]}
    route = by_name["route_agreement"]["detail"]
    screen = by_name["screen_agreement"]["detail"]
    return {"verdict": result["verdict"],
            "routes_extracted": route.get("extracted", 0), "routes_independent": route.get("independent", 0),
            "screens_extracted": screen.get("extracted", 0), "screens_independent": screen.get("independent", 0)}
