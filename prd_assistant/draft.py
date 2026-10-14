"""Drivers for the three CLI steps. Files live in the slice 1 output directory."""
import datetime
import hashlib
import json
from pathlib import Path

from . import assemble, docs_index, groups, links, scaffold, verify


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


def _write_manifest(out):
    _write_json(out / "manifest.json", {"scaffold_sha256": _sha(out / "scaffold.md"),
                                       "template_sha256": _sha(out / "slots.template.json")})


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
    _write_manifest(out)
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
    target = out / "prd.md"
    target.write_text(prd)
    return target
