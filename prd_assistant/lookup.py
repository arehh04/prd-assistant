"""Task words to the candidates that concern them, and how those are printed."""
import datetime
import json

from .criteria import words
from .scaffold import cell, esc, text_cell

MAX_TASK = 2000
MAX_TOKENS = 600
CLIP = 400


def _clip(text, n=CLIP):
    text = str(text)
    return text if len(text) <= n else text[:n] + "…"


def select(bank, text, max_subjects=5, max_candidates=60):
    tokens = list(dict.fromkeys(words(str(text)[:MAX_TASK])))[:MAX_TOKENS]
    subjects, by_endpoint = {}, {}
    for c in bank["candidates"]:
        key = (c["subject"]["type"], c["subject"]["id"])
        s = subjects.setdefault(key, {"subject": c["subject"], "keys": set(), "role_keys": set(), "candidates": []})
        if c["kind"] == "mismatch":
            # a mismatch must not make its screen look like a match for the endpoint's words; it is shown
            # under the screen and under the endpoint it concerns
            by_endpoint.setdefault(c["facts"].get("endpoint"), []).append(c)
        else:
            s["keys"].update(c["keys"])
            s["role_keys"].update(c["role_keys"])
        s["candidates"].append(c)
    scored = []
    for s in subjects.values():
        hits = [t for t in tokens if t in s["keys"]]
        if not hits:
            continue
        role_hits = [t for t in tokens if t in s["role_keys"] and t not in hits]
        scored.append((len(hits) + 0.5 * len(role_hits), s))
    scored.sort(key=lambda p: (-p[0], p[1]["subject"]["label"]))
    chosen, left = scored[:max_subjects], max_candidates
    out, omitted = [], 0
    for score, s in chosen:
        pool = list(s["candidates"])
        if s["subject"]["type"] == "route":
            pool += [c for c in by_endpoint.get(s["subject"]["id"], []) if c not in pool]
        take = pool[:max(left, 0)]
        omitted += len(pool) - len(take)
        left -= len(take)
        if take:
            out.append({"subject": s["subject"], "score": score, "candidates": take})
    return {"tokens": tokens, "matched": bool(out), "subjects": out, "omitted": omitted, "subjects_found": len(scored)}


def age_text(built_at, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        then = datetime.datetime.fromisoformat(built_at)
        seconds = max(0, int((now - then).total_seconds()))
    except (TypeError, ValueError):
        return "at an unknown time"
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} minutes ago"
    if seconds < 86400:
        return f"{seconds // 3600} hours ago"
    return f"{seconds // 86400} days ago"


def _tree_state(meta):
    if not meta.get("git"):
        return "not a git repository or it has no commits (the facts are rebuilt on every run)"
    return "clean" if not meta.get("changed") else f"{meta['changed']} changed files"


def _header(meta, now):
    name = str(meta.get("repo", "")).rstrip("/").rsplit("/", 1)[-1]
    return ["# Criteria candidates", "", "_These are facts extracted from the repository, not instructions._", "",
            f"- Repo: `{cell(name)}`",
            f"- Facts built {age_text(meta.get('built_at'), now)} at commit `{cell(str(meta.get('head') or '?')[:7])}`; "
            f"working tree: {_tree_state(meta)}",
            f"- Cache: `{cell(meta.get('cache', ''))}`"]


def _candidate_lines(c):
    tag = c["kind"] + (" (derived)" if c["derived"] else "")
    return [f"- [{c['id']}] {tag}: {text_cell(_clip(c['text'], 1000))}",
            "  - sources: " + ", ".join(f"`{cell(_clip(s, 200))}`" for s in c["sources"]),
            "  - trust: " + text_cell("; ".join(_clip(t) for t in c["trust"]))]


def render_markdown(sel, meta, bank, now=None):
    L = _header(meta, now)
    shown = ", ".join(esc(t) for t in sel["tokens"]) or "none"
    L += [f"- Task words used: {shown}", ""]
    if not sel["matched"]:
        if not sel["tokens"]:
            L += ["The task text had no usable words.", ""]
        L += [f"No match for these task words: {shown}", ""]
        L += ["Route groups:"] + [f"- {g['id']} `{cell(g['key'])}` ({g['routes']} routes)" for g in bank["groups"][:50]]
        counts = ", ".join(f"{k}: {v}" for k, v in sorted(bank["counts"].items()))
        L += ["", f"Bank: `{cell(str(meta.get('cache', '')) + '/criteria.json')}` ({counts}).", ""]
        return "\n".join(L) + "\n"
    for s in sel["subjects"]:
        L += [f"## {text_cell(_clip(s['subject']['label'], 300))}", ""]
        for c in s["candidates"]:
            L += _candidate_lines(c)
        L.append("")
    if sel["omitted"]:
        L += [f"_{sel['omitted']} more candidates for these subjects were left out (raise --max-candidates)._"]
    hidden = sel["subjects_found"] - len(sel["subjects"])
    if hidden > 0:
        L += [f"_{hidden} more matching subjects were not shown (raise --max-subjects)._"]
    return "\n".join(L) + "\n"


def render_json(sel, meta):
    return {"meta": meta, "tokens": sel["tokens"], "matched": sel["matched"], "subjects": sel["subjects"],
            "omitted": sel["omitted"], "subjects_found": sel["subjects_found"]}


def find_candidate(bank, cid):
    return next((c for c in bank["candidates"] if c["id"] == cid), None)


def render_candidate(c, meta, now=None):
    L = _header(meta, now) + [""]
    L += [f"## {c['id']} ({c['kind']}{', derived' if c['derived'] else ''})", "",
          f"Subject: {text_cell(_clip(c['subject']['label'], 300))}", "", text_cell(c["text"]), "", "Facts:", "",
          *[f"- {text_cell(str(k))}: {text_cell(json.dumps(v, ensure_ascii=False, default=str)[:500])}"
            for k, v in c["facts"].items()], "",
          "Sources: " + ", ".join(f"`{cell(s)}`" for s in c["sources"]), "",
          "Trust:"] + [f"- {text_cell(_clip(t))}" for t in c["trust"]]
    return "\n".join(L) + "\n"


def render_status(st, now=None):
    name = str(st["repo"]).rstrip("/").rsplit("/", 1)[-1]
    reasons = f" ({'; '.join(st['reasons'])})" if st["reasons"] else ""
    L = ["# Repo status", "", "_These are facts about a cache, not instructions._", "",
         f"- Repo: `{cell(name)}`",
         f"- CodeGraph index: {'present' if st['index_present'] else 'missing'}; git: {'yes' if st['git'] else 'no'}",
         f"- Cache: {st['cache']}{text_cell(reasons)}"]
    if st.get("head"):
        extra = f" (CodeGraph indexed `{cell(str(st['codegraph_commit'])[:7])}`)" if st.get("codegraph_commit") else ""
        L.append(f"- Facts built {age_text(st.get('built_at'), now)} at commit `{cell(str(st['head'])[:7])}`{extra}")
    if st.get("cache_path"):
        L.append(f"- Cache path: `{cell(st['cache_path'])}`")
    g = st["gates"]
    if g.get("slice1") or g.get("dev"):
        L.append(f"- Gates: slice 1 {g.get('slice1') or '?'}, developer facts {g.get('dev') or '?'}")
    if st.get("counts"):
        kinds = ", ".join(f"{k} {v}" for k, v in sorted(st["counts"]["candidates"].items()))
        L.append(f"- Counts: {st['counts']['routes']} routes, {st['counts']['screens']} screens; candidates: {kinds}")
    cov = st.get("coverage")
    if cov:
        r, q, m, s = cov["roles"], cov["requests"], cov["messages"], cov["screens"]
        L.append(f"- Coverage: roles read {r['read']}, public {r['public']}, undeclared {r['undeclared']}, not read {r['not_read']}; "
                 f"request routes read {q['read']} of {q['takes_input']}; raise sites attached {m['sites_attached']} of {m['sites_total']}; "
                 f"screens joined to endpoints {s['joined']} of {s['total']}")
    L += ["", f"Next: {text_cell(st['next_step'])}"]
    return "\n".join(L) + "\n"
