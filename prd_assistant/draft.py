"""Drivers for the three CLI steps. Files live in the slice 1 output directory."""
import datetime
import hashlib
import json
import shutil
from pathlib import Path

from . import assemble, cgdb, devguide, docs_index, groups, guide, journeys, links, scaffold, ui_text, verify
from . import count as count_module
from .dev import errors as dev_errors, roles as dev_roles, rules as dev_rules


class GateFailed(RuntimeError):
    pass


class TamperError(RuntimeError):
    pass


def _read_json(path):
    return json.loads(Path(path).read_text())


def _write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_manifest(out, kind="prd"):
    _write_json(out / "manifest.json", {"scaffold_sha256": _sha(out / "scaffold.md"),
                                       "template_sha256": _sha(out / "slots.template.json"), "kind": kind})


def _check_manifest(out):
    manifest = out / "manifest.json"
    if not manifest.is_file():
        raise TamperError("manifest.json is missing; run `prd_draft.py prepare` first")
    recorded = _read_json(manifest)
    for name, key in (("scaffold.md", "scaffold_sha256"), ("slots.template.json", "template_sha256")):
        if not (out / name).is_file() or _sha(out / name) != recorded.get(key):
            raise TamperError(f"{name} changed since prepare; run `prd_draft.py prepare` again")


def prepare(repo, out_dir, today=None):
    out = Path(out_dir)
    facts_path, gate_path = out / "facts.json", out / "gate.json"
    if not facts_path.is_file() or not gate_path.is_file():
        raise FileNotFoundError(f"{out} has no facts.json/gate.json; run bin/prd_facts.py first")
    facts, gate = _read_json(facts_path), _read_json(gate_path)
    repo = Path(repo)
    if not repo.is_dir():
        raise FileNotFoundError(f"{repo} is not a directory")
    built_for = facts.get("meta", {}).get("repo")
    if built_for and Path(built_for).resolve() != repo.resolve():
        raise ValueError(f"facts were built for {built_for}, not {repo.resolve()}; run prd_facts.py on this repo")
    if gate["verdict"] == "FAIL":
        raise GateFailed(f"gate verdict is FAIL; see {out / 'gate.md'}")
    repo = Path(repo).resolve()
    docs = docs_index.index_docs(repo)
    link_data = links.link(repo, facts)
    text, template = scaffold.build(facts, gate, link_data, docs, repo.name,
                                    today or datetime.date.today().isoformat())
    _write_json(out / "docs_index.json", docs)
    _write_json(out / "links.json", link_data)
    _write_json(out / "slots.template.json", template)
    (out / "scaffold.md").write_text(text)
    _write_manifest(out, "prd")
    summary = {
        "prefix": groups.global_prefix([r["path"] for r in facts["routes"]]),
        "route_groups": len(groups.group_routes(facts["routes"])),
        "screen_groups": len(groups.group_screens(facts["screens"])),
        "tests": link_data["tests"]["totals"], "frontend": link_data["frontend"]["totals"],
    }
    _write_json(out / "draft_summary.json", summary)
    return summary


def _load_slots_and_template(out):
    slots_path, template_path = out / "slots.json", out / "slots.template.json"
    for p in (slots_path, template_path):
        if not p.is_file():
            raise FileNotFoundError(f"missing {p}")
    return _read_json(slots_path), _read_json(template_path)


def run_verify(out_dir):
    slots, template = _load_slots_and_template(Path(out_dir))
    _check_manifest(Path(out_dir))
    return verify.verify(slots, template)


def run_assemble(out_dir):
    out = Path(out_dir)
    slots, template = _load_slots_and_template(out)
    scaffold_path = out / "scaffold.md"
    if not scaffold_path.is_file():
        raise FileNotFoundError(f"missing {scaffold_path}")
    _check_manifest(out)
    prd = assemble.assemble(scaffold_path.read_text(), slots, template)
    kind = _read_json(out / "manifest.json").get("kind", "prd")
    target = out / {"prd": "prd.md", "guide": "client-guide.md", "dev": "developer-guide.md"}.get(kind, "prd.md")
    target.write_text(prd)
    return target


GUIDE_STALE = ("scaffold.md", "slots.template.json", "manifest.json", "guide_summary.json", "client-guide.md")
DEV_STALE = ("scaffold.md", "slots.template.json", "manifest.json", "dev_summary.json", "developer-guide.md",
             "roles.json", "form_rules.json", "error_messages.json", "dev_gate.json", "dev_gate.md")


def _remove_stale(directory, names):
    for name in names:
        (Path(directory) / name).unlink(missing_ok=True)   # a failed run must not leave an older guide to assemble


def guide_prepare(repo, out_dir, today=None):
    out = Path(out_dir)
    _remove_stale(out / "guide", GUIDE_STALE)
    facts_path, gate_path = out / "facts.json", out / "gate.json"
    if not facts_path.is_file() or not gate_path.is_file():
        raise FileNotFoundError(f"{out} has no facts.json/gate.json; run bin/prd_facts.py first")
    facts, slice1 = _read_json(facts_path), _read_json(gate_path)
    repo = Path(repo)
    if not repo.is_dir():
        raise FileNotFoundError(f"{repo} is not a directory")
    built_for = facts.get("meta", {}).get("repo")
    if built_for and Path(built_for).resolve() != repo.resolve():
        raise ValueError(f"facts were built for {built_for}, not {repo.resolve()}; run prd_facts.py on this repo")
    if slice1["verdict"] == "FAIL":
        raise GateFailed(f"gate verdict is FAIL; see {out / 'gate.md'}")
    if not facts["screens"]:
        raise ValueError("no screens were extracted; the client guide needs a frontend")
    repo = repo.resolve()
    gdir = out / "guide"
    count_module.reset_unreadable()
    ui = ui_text.build(repo, facts)
    jr = journeys.build(facts, ui)
    gate = guide.guide_gate(ui, jr)
    gdir = out / "guide"
    gdir.mkdir(exist_ok=True)
    _write_json(gdir / "ui_text.json", ui)
    _write_json(gdir / "journeys.json", jr)
    _write_json(gdir / "guide_gate.json", gate)
    (gdir / "guide_gate.md").write_text(guide.render_gate_md(gate))
    if gate["verdict"] == "FAIL":
        raise GateFailed(f"guide gate is FAIL; see {gdir / 'guide_gate.md'}")
    text, template = guide.build(facts, slice1, ui, jr, gate, repo.name, today or datetime.date.today().isoformat())
    (gdir / "scaffold.md").write_text(text)
    _write_json(gdir / "slots.template.json", template)
    _write_manifest(gdir, "guide")
    statuses = [s["status"] for s in ui["screens"].values()]
    kinds = {}
    for s in ui["screens"].values():
        for i in s["items"]:
            kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
    summary = {"screens": len(statuses), "resolved": statuses.count("resolved"),
               "conditional": statuses.count("conditional"), "unresolved": statuses.count("unresolved"),
               "with_text": sum(1 for s in ui["screens"].values() if s["items"]),
               "items_by_kind": dict(sorted(kinds.items())), "shared_files": len(ui["shared_files"]),
               "edges": len(jr["edges"]), "shared_nav": len(jr["shared"]), "verdict": gate["verdict"]}
    _write_json(gdir / "guide_summary.json", summary)
    return summary


def dev_prepare(repo, out_dir, today=None):
    out = Path(out_dir)
    _remove_stale(out / "dev", DEV_STALE)
    facts_path, gate_path = out / "facts.json", out / "gate.json"
    if not facts_path.is_file() or not gate_path.is_file():
        raise FileNotFoundError(f"{out} has no facts.json/gate.json; run bin/prd_facts.py first")
    facts, slice1 = _read_json(facts_path), _read_json(gate_path)
    repo = Path(repo)
    if not repo.is_dir():
        raise FileNotFoundError(f"{repo} is not a directory")
    built_for = facts.get("meta", {}).get("repo")
    if built_for and Path(built_for).resolve() != repo.resolve():
        raise ValueError(f"facts were built for {built_for}, not {repo.resolve()}; run prd_facts.py on this repo")
    if slice1["verdict"] == "FAIL":
        raise GateFailed(f"gate verdict is FAIL; see {out / 'gate.md'}")
    if not facts["routes"]:
        raise ValueError("no routes were extracted; the developer guide needs a backend")
    repo = repo.resolve()
    ddir = out / "dev"
    count_module.reset_unreadable()
    ui = ui_text.build(repo, facts) if facts["screens"] else {"screens": {}}
    links_result = links.link(repo, facts)
    roles = dev_roles.build(repo, facts, ui, links_result)
    rules = dev_rules.build(repo, facts, ui, links_result)
    conn, tmp = None, None
    try:
        conn, tmp = cgdb.open_index(repo)
    except FileNotFoundError:
        pass
    try:
        errors = dev_errors.build(repo, facts, roles, conn)
    finally:
        if conn is not None:
            conn.close()
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
    gate = devguide.dev_gate(roles, rules, errors)
    ddir.mkdir(exist_ok=True)
    _write_json(ddir / "roles.json", roles)
    _write_json(ddir / "form_rules.json", rules)
    _write_json(ddir / "error_messages.json", errors)
    _write_json(ddir / "dev_gate.json", gate)
    (ddir / "dev_gate.md").write_text(devguide.render_gate_md(gate))
    if gate["verdict"] == "FAIL":
        raise GateFailed(f"dev gate is FAIL; see {ddir / 'dev_gate.md'}")
    text, template = devguide.build(facts, slice1, roles, rules, errors, gate, repo.name,
                                    today or datetime.date.today().isoformat())
    (ddir / "scaffold.md").write_text(text)
    _write_json(ddir / "slots.template.json", template)
    _write_manifest(ddir, "dev")
    summary = {"routes": roles["counts"]["routes"],
               "roles": {k: roles["counts"][k] for k in ("read", "public", "undeclared", "not_read")},
               "requests": {k: rules["counts"][k] for k in ("takes_input", "read", "not_read")},
               "messages": {"count": errors["counts"]["messages"], "sites_total": errors["sites"]["total"],
                            "sites_attached": errors["sites"]["attached"]},
               "mismatches": {"roles": len(roles["mismatches"]), "rules": len(rules["mismatches"])},
               "screens": {"total": len(roles["joined"]), "joined": sum(1 for v in roles["joined"].values() if v)},
               "verdict": gate["verdict"]}
    _write_json(ddir / "dev_summary.json", summary)
    return summary
