"""Turn CodeGraph route/navigation rows into a facts dict. Nothing is dropped silently."""
import json
import re

from . import cgdb, paths

ROUTE_NAME = re.compile(r"^(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD|ALL)\s+(\S+)$")


def _tested_by(conn, handler_id):
    rows = conn.execute(
        "select distinct s.file_path from edges e join nodes s on s.id = e.source "
        "where e.target = ? and e.kind in ('calls', 'references')",
        (handler_id,),
    )
    return sorted(p for (p,) in rows if paths.exclusion_reason(p) == "test")


def _handler_dict(row):
    return {"id": row["id"], "name": row["name"], "qualified_name": row["qualified_name"],
            "source": f"{row['file_path']}:{row['start_line']}"}


def _handler(conn, route_id):
    row = conn.execute(
        "select t.id, t.name, t.qualified_name, t.file_path, t.start_line "
        "from edges e join nodes t on t.id = e.target "
        "where e.source = ? and e.kind = 'references' and t.kind in ('function', 'method') limit 1",
        (route_id,),
    ).fetchone()
    return None if row is None else _handler_dict(row)


def extract_facts(conn, repo_root):
    generated = {r["path"]: bool(r["generated"]) for r in conn.execute("select path, generated from files")}
    routes, screens, excluded = [], [], []
    for r in conn.execute("select id, name, file_path, start_line from nodes where kind = 'route' "
                          "order by file_path, start_line, id"):
        match = ROUTE_NAME.match(r["name"])
        source = f"{r['file_path']}:{r['start_line']}"
        reason = paths.exclusion_reason(r["file_path"], generated.get(r["file_path"], False))
        if reason:
            excluded.append({"id": r["id"], "kind": "route" if match else "screen",
                             "name": r["name"], "source": source, "reason": reason})
            continue
        fact = {"id": r["id"], "file": r["file_path"], "line": r["start_line"],
                "source": source, "origin": "codegraph"}
        if match:
            handler = _handler(conn, r["id"])
            fact.update(kind="route", method=match.group(1), path=match.group(2), handler=handler,
                        tested_by=_tested_by(conn, handler["id"]) if handler else [])
            routes.append(fact)
        else:
            fact.update(kind="screen", path=r["name"])
            screens.append(fact)

    screen_ids = {s["id"] for s in screens}
    navigation = []
    for e in conn.execute(
        "select e.id as edge_id, e.line, e.metadata, s.name as from_name, s.file_path as from_file, "
        "t.id as to_id, t.name as to_path from edges e "
        "join nodes s on s.id = e.source join nodes t on t.id = e.target "
        "where e.kind = 'navigates' order by s.file_path, e.line, e.id"
    ):
        source = f"{e['from_file']}:{e['line']}"
        reason = paths.exclusion_reason(e["from_file"], generated.get(e["from_file"], False))
        if reason is None and e["to_id"] not in screen_ids:
            reason = "target-excluded"
        if reason:
            excluded.append({"id": f"nav:{e['edge_id']}", "kind": "navigation",
                             "name": f"{e['from_name']} -> {e['to_path']}", "source": source, "reason": reason})
            continue
        try:
            href = (json.loads(e["metadata"]) if e["metadata"] else {}).get("href")
        except ValueError:
            href = None
        navigation.append({"id": f"nav:{e['edge_id']}", "from_symbol": e["from_name"],
                           "from_file": e["from_file"], "to_path": e["to_path"], "to_id": e["to_id"],
                           "line": e["line"], "source": source, "href": href})

    return {
        "schema": 1,
        "meta": {
            "repo": str(repo_root),
            "codegraph_version": cgdb.get_meta(conn, "indexed_with_version"),
            "extraction_version": cgdb.get_meta(conn, "indexed_with_extraction_version"),
            "indexed_at_commit": cgdb.get_meta(conn, "indexed_at_commit"),
        },
        "routes": routes, "screens": screens, "navigation": navigation, "excluded": excluded,
    }


def merge_adapter_routes(conn, facts, adapter_routes, unsupported, name):
    """Add routes that CodeGraph does not extract itself; CodeGraph wins on the same (file, line)."""
    have = {(r["file"], r["line"]) for r in facts["routes"]}
    added = 0
    for route in adapter_routes:
        if (route["file"], route["line"]) in have:
            continue
        qualified = route.pop("handler_qualified_name", None)
        row = None
        if qualified:
            row = conn.execute(
                "select id, name, qualified_name, file_path, start_line from nodes "
                "where kind = 'method' and qualified_name = ?", (qualified,)).fetchone()
        route["handler"] = None if row is None else _handler_dict(row)
        route["tested_by"] = _tested_by(conn, row["id"]) if row else []
        facts["routes"].append(route)
        have.add((route["file"], route["line"]))
        added += 1
    facts["routes"].sort(key=lambda r: (r["file"], r["line"]))
    facts.setdefault("adapters", {})[name] = {"routes_added": added, "unsupported": unsupported}
