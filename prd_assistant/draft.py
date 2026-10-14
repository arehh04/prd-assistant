"""Drivers for the three CLI steps. Files live in the slice 1 output directory."""
import datetime
import json
from pathlib import Path

from . import assemble, docs_index, groups, links, scaffold, verify


class GateFailed(RuntimeError):
    pass


def _read_json(path):
    return json.loads(Path(path).read_text())


def _write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True))


def prepare(repo, out_dir, today=None):
    out = Path(out_dir)
    facts_path, gate_path = out / "facts.json", out / "gate.json"
    if not facts_path.is_file() or not gate_path.is_file():
        raise FileNotFoundError(f"{out} has no facts.json/gate.json; run bin/prd_facts.py first")
    facts, gate = _read_json(facts_path), _read_json(gate_path)
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
    return verify.verify(slots, template)


def run_assemble(out_dir):
    out = Path(out_dir)
    slots, template = _load_slots_and_template(out)
    scaffold_path = out / "scaffold.md"
    if not scaffold_path.is_file():
        raise FileNotFoundError(f"missing {scaffold_path}")
    prd = assemble.assemble(scaffold_path.read_text(), slots, template)
    target = out / "prd.md"
    target.write_text(prd)
    return target
