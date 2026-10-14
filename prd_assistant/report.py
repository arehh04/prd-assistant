"""Render the gate result as Markdown."""


def _fmt_pairs(pairs, limit=20):
    shown = [f"{f}:{n}" for f, n in pairs[:limit]]
    more = len(pairs) - limit
    return ", ".join(shown) + (f" (+{more} more)" if more > 0 else "") if shown else "none"


def render_gate_md(result, facts):
    lines = [f"# Gate: {result['verdict']}", "",
             f"Repo: `{facts['meta']['repo']}`  ",
             f"CodeGraph {facts['meta']['codegraph_version']} (extraction {facts['meta']['extraction_version']}), "
             f"indexed at commit `{facts['meta']['indexed_at_commit']}`", "",
             "| Check | Status |", "|---|---|"]
    lines += [f"| {c['name']} | {c['status']} |" for c in result["checks"]]
    for c in result["checks"]:
        d = c["detail"]
        lines += ["", f"## {c['name']}: {c['status']}"]
        if "note" in d:
            lines.append(d["note"])
        if "missing_in_codegraph" in d:
            lines += [f"- independent count: {d['independent']}, extracted: {d['extracted']}, "
                      f"disagreement: {d['disagreement']}",
                      f"- missing in CodeGraph: {_fmt_pairs(d['missing_in_codegraph'])}",
                      f"- extra in CodeGraph: {_fmt_pairs(d['extra_in_codegraph'])}"]
        elif c["name"] == "index_staleness":
            lines += [f"- indexed commit: {d['indexed_at_commit']}, git HEAD: {d['git_head']}",
                      f"- changed files since index: {d['changed_files']}",
                      f"- changed or new route/router/controller files: {d['relevant_changed'] or 'none'}"]
        elif c["name"] == "language_coverage":
            lines += [f"- source files on disk: {d['source_files_on_disk']}, indexed: {d['indexed']}, "
                      f"ratio: {d['ratio']}", f"- not indexed (sample): {d['not_indexed_sample'] or 'none'}"]
        elif c["name"] == "adapter_unsupported":
            lines.append(f"- unsupported constructs: {d['count']}")
            lines += [f"  - {u['file']}:{u['line']} `{u['text']}`" for u in d["items"]]
        elif c["name"] == "unreadable_files":
            lines.append(f"- files that could not be read: {d['count']}")
            lines += [f"  - `{item}`" for item in d["items"]]
        elif c["name"] == "orphans":
            lines += [f"- routes without a handler: {len(d['routes_without_handler'])}",
                      f"- screens nothing navigates to: {len(d['screens_not_navigated_to'])}"]
        elif c["name"] == "exclusions":
            lines.append(f"- excluded: {d['total']} {d['by_reason']}")
    return "\n".join(lines) + "\n"
