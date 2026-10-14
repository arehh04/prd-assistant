"""What a screen shows: component resolution and user-facing text. Pattern-based and read-only."""
import bisect
import os
import re
from pathlib import Path

from . import count, links, paths
from .mask import mask, match_brace

UI_SUFFIXES = (".tsx", ".jsx", ".vue", ".ts", ".js")
GUESS_SUFFIXES = (".tsx", ".ts", ".jsx", ".js", ".vue", ".mjs")
MAX_FILE_BYTES = 2_000_000
STRING_RE = re.compile(r"""(['"`])((?:\\.|(?!\1).)*)\1""", re.S)
VITE_ALIAS_RE = re.compile(r"""['"]([@~][\w-]*)['"]\s*:\s*([^\n]+)""")
TS_PATH_RE = re.compile(r'"([^"*]+)/\*"\s*:\s*\[\s*"([^"]+?)/?\*?"')
IMPORT_RE = re.compile(r"""^\s*import\s+(?:(?P<clause>[^'"]+?)\s+from\s+)?(['"])(?P<spec>[^'"]+)\2""", re.M)
LAZY_RE = re.compile(
    r"""\b(?:const|let|var)\s+([A-Z]\w*)\s*=\s*(?:React\.)?lazy\(\s*\(\)\s*=>\s*import\(\s*(['"`])(.*?)\2""", re.S)


def _abs(path):
    return Path(os.path.abspath(path))


def _alias_target(config_dir, rhs):
    for m in STRING_RE.finditer(rhs):
        value = m.group(2)
        if "://" in value or not re.fullmatch(r"[\w./@-]+", value):
            continue
        return _abs(Path(config_dir) / value.lstrip("/"))
    return None


def load_aliases(repo_root, start_dir):
    repo_root = _abs(repo_root)
    directory = _abs(repo_root / start_dir)
    directories = [directory]
    while directory != repo_root and repo_root in directory.parents:
        directory = directory.parent
        directories.append(directory)
    aliases = []
    for d in directories:
        for pattern in ("vite.config.*", "tsconfig*.json", "jsconfig.json"):
            for cfg in sorted(d.glob(pattern)):
                text = count.read_text(cfg)
                if cfg.name.startswith("vite"):
                    for m in VITE_ALIAS_RE.finditer(text):
                        target = _alias_target(d, m.group(2))
                        if target:
                            aliases.append((m.group(1), target))
                else:
                    for m in TS_PATH_RE.finditer(text):
                        aliases.append((m.group(1), _abs(d / m.group(2))))
    return list(dict.fromkeys(aliases))


def resolve_module(spec, base_dir, aliases, repo_root):
    """Repo-relative posix path of the file a module specifier points to, or None."""
    repo_root = _abs(repo_root)
    if spec.startswith("."):
        base = _abs(repo_root / base_dir / spec)
    else:
        base = None
        for prefix, target in aliases:
            if spec == prefix or spec.startswith(prefix + "/"):
                base = _abs(target / spec[len(prefix):].lstrip("/"))
                break
        if base is None:
            return None
    candidates = [base] + [Path(str(base) + s) for s in GUESS_SUFFIXES] + [base / ("index" + s) for s in GUESS_SUFFIXES]
    for cand in candidates:
        if cand.is_file() and not cand.is_symlink() and repo_root in cand.parents:
            return cand.relative_to(repo_root).as_posix()
    return None


def parse_imports(text):
    names, specs = {}, []
    for m in IMPORT_RE.finditer(text):
        spec = m.group("spec")
        specs.append(spec)
        clause = (m.group("clause") or "").strip()
        default = re.match(r"([A-Za-z_$][\w$]*)\s*(?:,|$)", clause)
        if default and not clause.startswith(("{", "*")):
            names[default.group(1)] = spec
        for named in re.findall(r"\{([^}]*)\}", clause):
            for part in named.split(","):
                part = part.strip()
                if part:
                    names[re.split(r"\s+as\s+", part)[-1].strip()] = spec
    for m in LAZY_RE.finditer(text):
        names[m.group(1)] = m.group(3)
        specs.append(m.group(3))
    return names, specs


TAG_START_RE = re.compile(r"(?<![\w$)\]])<([A-Za-z][\w.\-]*)")
WRAPPERS = {"Suspense", "Navigate", "Fragment", "Outlet", "ErrorBoundary", "Route", "Routes",
            "React.Fragment", "React.Suspense"}


class Source:
    """A file prepared for pattern scanning: comments blanked, offsets preserved."""

    def __init__(self, text):
        self.text = text
        self.code = mask(text, blank_strings=False, apostrophe_in_words=True)
        self.blanked = mask(text, apostrophe_in_words=True)
        self.starts = [0] + [m.end() for m in re.finditer("\n", text)]

    def line_at(self, pos):
        return bisect.bisect_right(self.starts, pos)


def tag_end(blanked, i):
    """Index of the '>' that closes the opening tag whose name ends at i, or -1."""
    depth, n = 0, len(blanked)
    while i < n:
        ch = blanked[i]
        if ch in "{(":
            depth += 1
        elif ch in "})":
            depth -= 1
        elif ch == ">" and depth <= 0 and blanked[i - 1] != "=":
            return i
        i += 1
    return -1


def close_paren(blanked, open_idx):
    depth = 0
    for i in range(open_idx, len(blanked)):
        if blanked[i] == "(":
            depth += 1
        elif blanked[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return len(blanked) - 1


def _enclosing_object(blanked, pos):
    depth = 0
    for i in range(pos - 1, -1, -1):
        ch = blanked[i]
        if ch == "}":
            depth += 1
        elif ch == "{":
            if depth == 0:
                return i
            depth -= 1
    return None


def _top_level_value(blanked, start, limit):
    depth, i = 0, start
    while i < limit:
        ch = blanked[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif ch == "," and depth == 0:
            break
        i += 1
    return i


def _component_tags(code, blanked, start, end):
    names, zones = [], []
    for m in TAG_START_RE.finditer(code, start, end):
        if any(a <= m.start() < b for a, b in zones):
            continue
        name = m.group(1)
        if name in WRAPPERS:
            zones.append((m.start(), max(tag_end(blanked, m.end()), m.start())))
            continue
        if name[:1].isupper() and name not in names:
            names.append(name)
    return names


def _object_components(src, obj, obj_end):
    names, direct = [], []
    segment = src.code[obj:obj_end + 1]
    for m in re.finditer(r"\b(element|Component|component)\s*:\s*", segment):
        start = obj + m.end()
        end = _top_level_value(src.blanked, start, obj_end)
        expr = src.code[start:end]
        if m.group(1) == "element" or expr.lstrip().startswith("<"):
            names += _component_tags(src.code, src.blanked, start, end)
            continue
        imp = re.search(r"import\(\s*(['\"`])(.*?)\1", expr, re.S)
        if imp:
            direct.append(imp.group(2))
            continue
        ident = re.match(r"\s*([A-Z][\w$]*)", expr)
        if ident:
            names.append(ident.group(1))
    return names, direct


def resolve_component(screen, src, aliases, repo_root):
    base_dir = Path(screen["file"]).parent.as_posix()
    result = {"status": "unresolved", "component_file": None, "candidates": [], "title": None}
    line = screen["line"]
    if not 1 <= line <= len(src.starts):
        return result
    line_start = src.starts[line - 1]
    line_end = src.starts[line] if line < len(src.starts) else len(src.code)
    names, direct = [], []
    tag = src.code.find("<Route", line_start, line_end)
    if tag != -1:
        end = tag_end(src.blanked, tag + len("<Route"))
        if end != -1:
            m = re.search(r"\b(?:element|Component)\s*=\s*\{", src.code[tag:end])
            if m:
                open_i = tag + m.end() - 1
                names = _component_tags(src.code, src.blanked, open_i + 1, match_brace(src.blanked, open_i))
    else:
        key = re.compile(r"\bpath\s*:").search(src.code, line_start, line_end)
        obj = _enclosing_object(src.blanked, key.start()) if key else None
        if obj is not None:
            obj_end = match_brace(src.blanked, obj)
            names, direct = _object_components(src, obj, obj_end)
            title = re.search(r"\btitle\s*:\s*(['\"`])(.*?)\1", src.code[obj:obj_end + 1])
            if title:
                result["title"] = {"text": " ".join(title.group(2).split()),
                                   "line": src.line_at(obj + title.start(2))}
    imports, _ = parse_imports(src.text)
    cands = []
    for name in dict.fromkeys(names):
        spec = imports.get(name)
        cands.append({"name": name, "file": resolve_module(spec, base_dir, aliases, repo_root) if spec else None})
    for spec in direct:
        cands.append({"name": Path(spec).stem, "file": resolve_module(spec, base_dir, aliases, repo_root)})
    hint = screen.get("component")
    if hint and hint.get("file"):
        cands = [{"name": hint["name"], "file": hint["file"]}]
    result["candidates"] = cands
    files = [c for c in cands if c["file"]]
    if files:
        result["component_file"] = files[0]["file"]
        result["status"] = "conditional" if len(cands) > 1 else "resolved"
    return result


ATTR_RE = re.compile(r"""([A-Za-z_:][\w:\-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|\{\s*(["'`])(.*?)\4\s*\})""", re.S)
TEXT_ATTRS = {"placeholder": "placeholder", "label": "label", "title": "title", "aria-label": "title", "alt": "title"}
ERROR_CLASS_RE = re.compile(r"destructive|error", re.I)
CALL_RE = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(")
MESSAGE_NAME_RE = re.compile(r"toast|error|alert|notify|snack|warning|success", re.I)
CODEISH_RE = re.compile(r"[a-z0-9_./:@#\-]+")
MAX_ITEMS = 300


def _norm(text):
    return " ".join(text.split())


def _has_letter(text):
    return any(c.isalpha() for c in text)


def _tag_kind(name):
    low = name.lower().split(".")[-1]
    if re.fullmatch(r"h[1-6]", low) or "title" in low or "heading" in low:
        return "heading"
    if low == "a" or "button" in low or "link" in low:
        return "button"
    if low == "label" or low.endswith("label"):
        return "label"
    return "text"


def _finish(items):
    seen, out = set(), []
    for item in sorted(items, key=lambda i: i["line"]):
        key = (item["kind"], item["text"])
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _content_pieces(blanked, code, start):
    """Text pieces outside braces from `start` up to the next '<' at brace depth 0."""
    pieces, depth, piece_start, open_i = [], 0, start, start
    for i in range(start, len(blanked)):
        ch = blanked[i]
        if ch == "{":
            if depth == 0:
                if i > piece_start:
                    pieces.append((piece_start, code[piece_start:i]))
                open_i = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                literal = re.fullmatch(r"(['\"`])(.*)\1", code[open_i + 1:i].strip(), re.S)
                if literal:
                    pieces.append((open_i + 1, literal.group(2)))
                piece_start = i + 1
        elif ch == "<" and depth == 0:
            if i > piece_start:
                pieces.append((piece_start, code[piece_start:i]))
            return pieces
    return pieces


def message_items(code, blanked, line_at, rel, base=0):
    items = []
    for m in CALL_RE.finditer(code):
        name = m.group(1)
        last = name.split(".")[-1]
        if not MESSAGE_NAME_RE.search(name):
            continue
        if re.match(r"(console|logger|log|Sentry)\.", name) or (last[:1].isupper() and re.search(r"(Error|Exception)$", last)):
            continue
        close = close_paren(blanked, m.end() - 1)
        args = code[m.end():close]
        for s in STRING_RE.finditer(args):
            value = _norm(s.group(2))
            if _has_letter(value) and not CODEISH_RE.fullmatch(value):
                items.append({"kind": "message", "text": value, "file": rel,
                              "line": line_at(base + m.end() + s.start())})
    return items


def _jsx_items(src, rel):
    code, blanked, items = src.code, src.blanked, []
    for m in TAG_START_RE.finditer(code):
        name = m.group(1)
        end = tag_end(blanked, m.end())
        if end < 0:
            continue
        attrs = code[m.end():end]
        error_ctx = False
        for a in ATTR_RE.finditer(attrs):
            attr, value = a.group(1), a.group(2) or a.group(3) or a.group(5) or ""
            if attr in ("className", "class") and ERROR_CLASS_RE.search(value):
                error_ctx = True
            elif attr == "role" and value == "alert":
                error_ctx = True
            elif attr in TEXT_ATTRS and _has_letter(value):
                items.append({"kind": TEXT_ATTRS[attr], "text": _norm(value), "file": rel,
                              "line": src.line_at(m.end() + a.start())})
        if blanked[end - 1] == "/":
            continue
        kind = "message" if error_ctx else _tag_kind(name)
        for pos, raw in _content_pieces(blanked, code, end + 1):
            text = _norm(raw)
            if _has_letter(text):
                items.append({"kind": kind, "text": text, "file": rel,
                              "line": src.line_at(pos + len(raw) - len(raw.lstrip()))})
    items += message_items(code, blanked, src.line_at, rel)
    return items


def extract_items(text, rel):
    if Path(rel).suffix.lower() == ".vue":
        return _vue_items(text, rel)
    return _finish(_jsx_items(Source(text), rel))


HTML_ATTR_RE = re.compile(r"""([:@\w.\-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
VUE_INTERP_RE = re.compile(r"\{\{.*?\}\}", re.S)


def _blank_comments(segment):
    return HTML_COMMENT_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group()), segment)


def _vue_blocks(text):
    template = None
    m = re.search(r"<template\b[^>]*>", text)
    if m:
        depth = 1
        for t in re.finditer(r"<(/?)template\b[^>]*>", text[m.end():]):
            depth += -1 if t.group(1) else 1
            if depth == 0:
                template = (m.end(), m.end() + t.start())
                break
    scripts = []
    for s in re.finditer(r"<script\b[^>]*>", text):
        e = re.search(r"</script>", text[s.end():])
        if e:
            scripts.append((s.end(), s.end() + e.start()))
    return template, scripts


def _vue_items(text, rel):
    starts = [0] + [m.end() for m in re.finditer("\n", text)]

    def line_at(pos):
        return bisect.bisect_right(starts, pos)

    items = []
    template, scripts = _vue_blocks(text)
    if template:
        t0, t1 = template
        seg = _blank_comments(text[t0:t1])
        for m in re.finditer(r"<([A-Za-z][\w\-.]*)", seg):
            i, quote = m.end(), None
            while i < len(seg):
                ch = seg[i]
                if quote:
                    if ch == quote:
                        quote = None
                elif ch in "\"'":
                    quote = ch
                elif ch == ">":
                    break
                i += 1
            if i >= len(seg):
                continue
            attrs, error_ctx = seg[m.end():i], False
            for a in HTML_ATTR_RE.finditer(attrs):
                attr, value = a.group(1), a.group(2) if a.group(2) is not None else a.group(3)
                if attr in ("class",) and ERROR_CLASS_RE.search(value):
                    error_ctx = True
                elif attr == "role" and value == "alert":
                    error_ctx = True
                elif attr in TEXT_ATTRS and _has_letter(value):
                    items.append({"kind": TEXT_ATTRS[attr], "text": _norm(value), "file": rel,
                                  "line": line_at(t0 + m.end() + a.start())})
            if seg[i - 1] == "/":
                continue
            nxt = seg.find("<", i + 1)
            end = len(seg) if nxt == -1 else nxt
            kind = "message" if error_ctx else _tag_kind(m.group(1))
            pos = i + 1
            for interp in list(VUE_INTERP_RE.finditer(seg, i + 1, end)) + [None]:
                stop = interp.start() if interp else end
                raw = seg[pos:stop]
                piece = _norm(raw)
                if _has_letter(piece):
                    items.append({"kind": kind, "text": piece, "file": rel,
                                  "line": line_at(t0 + pos + len(raw) - len(raw.lstrip()))})
                if interp:
                    pos = interp.end()
    for s0, s1 in scripts:
        script = Source(text[s0:s1])
        items += message_items(script.code, script.blanked, lambda p, base=s0: line_at(base + p), rel)
    return _finish(items)


MAX_FILES = 40
I18N_PACKAGES = ("react-i18next", "i18next", "vue-i18n", "@lingui/core")
I18N_CALL_RE = re.compile(r"""(?<![\w$.])\$?t\(\s*['"][\w.:\-]+['"]""")
LOOSE_STRING_RE = re.compile(r"""(['"`])([A-Za-z][^'"`\n]*\s[^'"`\n]*)\1""")
NOT_TEXT_CONTEXT_RE = re.compile(r"(className|class|import|from|require|style|href|src|alias)[^\n]{0,25}$")


def _read_ui_file(repo_root, rel):
    full = Path(repo_root) / rel
    if full.is_symlink() or not full.is_file() or paths.exclusion_reason(rel):
        return None
    if full.stat().st_size > MAX_FILE_BYTES:
        count.mark_unreadable(full)
        return None
    return count.read_text(full)


def _depth1_imports(repo_root, rel, text, aliases_for):
    base_dir = Path(rel).parent.as_posix()
    _, specs = parse_imports(text)
    found = []
    for spec in specs:
        target = resolve_module(spec, base_dir, aliases_for(base_dir), repo_root)
        if target and target != rel and target.endswith(UI_SUFFIXES) and not paths.exclusion_reason(target):
            found.append(target)
    return list(dict.fromkeys(found))


def _skipped(text, rel, taken):
    out = []
    for m in LOOSE_STRING_RE.finditer(text):
        value = _norm(m.group(2))
        if value in taken or not _has_letter(value):
            continue
        before = text[max(0, m.start() - 40):m.start()].split("\n")[-1]
        if NOT_TEXT_CONTEXT_RE.search(before):
            continue
        out.append({"file": rel, "line": text.count("\n", 0, m.start()) + 1, "text": value[:120]})
    return out


def build(repo_root, facts):
    repo_root = Path(repo_root)
    alias_cache, router_cache = {}, {}

    def aliases_for(directory):
        if directory not in alias_cache:
            alias_cache[directory] = load_aliases(repo_root, directory)
        return alias_cache[directory]

    resolved = {}
    for screen in facts["screens"]:
        router = screen["file"]
        if router not in router_cache:
            router_cache[router] = Source(count.read_text(repo_root / router))
        info = resolve_component(screen, router_cache[router], aliases_for(Path(router).parent.as_posix()), repo_root)
        resolved[screen["id"]] = (screen, info)

    texts, imports = {}, {}
    for sid, (screen, info) in resolved.items():
        if info["status"] == "unresolved":
            continue
        for cand in info["candidates"]:
            rel = cand["file"]
            if rel and rel not in texts:
                texts[rel] = _read_ui_file(repo_root, rel)
            if rel and texts.get(rel) is not None:
                imports.setdefault(rel, _depth1_imports(repo_root, rel, texts[rel], aliases_for))

    live = [sid for sid, (_, info) in resolved.items() if info["status"] != "unresolved"]
    own_files, used_by = {}, {}
    for sid in live:
        info = resolved[sid][1]
        component_files = [c["file"] for c in info["candidates"] if c["file"]]
        extra = []
        for rel in component_files:
            extra += [f for f in imports.get(rel, []) if f not in component_files]
        own_files[sid] = (component_files, list(dict.fromkeys(extra)))
        for f in set(own_files[sid][1]):
            used_by[f] = used_by.get(f, 0) + 1
    shared = sorted(f for f, n in used_by.items() if n >= 3 and n > len(live) / 3)

    def items_for(rel):
        if rel not in texts:
            texts[rel] = _read_ui_file(repo_root, rel)
        return extract_items(texts[rel], rel) if texts[rel] is not None else []

    screens_out, all_taken = {}, {}
    for sid, (screen, info) in resolved.items():
        files, truncated, items = [], False, []
        if sid in own_files:
            component_files, extra = own_files[sid]
            files = component_files + [f for f in extra if f not in shared]
            if len(files) > MAX_FILES:
                files, truncated = files[:MAX_FILES], True
            for rel in files:
                items += items_for(rel)
            if info["title"]:
                items.append({"kind": "title", "text": info["title"]["text"], "file": screen["file"],
                              "line": info["title"]["line"]})
            if len(items) > MAX_ITEMS:
                items, truncated = items[:MAX_ITEMS], True
        screens_out[sid] = {"path": screen["path"], "status": info["status"], "component_file": info["component_file"],
                            "candidates": info["candidates"], "files": files, "truncated": truncated, "items": items}
        for rel in files:
            all_taken.setdefault(rel, set()).update(i["text"] for i in items if i["file"] == rel)

    shared_items = []
    for rel in shared:
        shared_items += items_for(rel)
        all_taken.setdefault(rel, set()).update(i["text"] for i in shared_items if i["file"] == rel)

    skipped = []
    for rel in sorted(all_taken):
        if texts.get(rel) is not None:
            skipped += _skipped(texts[rel], rel, all_taken[rel])

    evidence = []
    for pkg_dir in links.frontend_roots(repo_root):
        pkg = repo_root / pkg_dir / "package.json"
        if pkg.is_file():
            body = count.read_text(pkg)
            evidence += [f"{(pkg_dir + '/' if pkg_dir else '')}package.json lists {name}"
                         for name in I18N_PACKAGES if f'"{name}"' in body]
    for rel in sorted(all_taken):
        if texts.get(rel) and I18N_CALL_RE.search(texts[rel]):
            evidence.append(f"{rel} calls t('...')")
    return {"schema": 1, "i18n": {"detected": bool(evidence), "evidence": evidence[:10]},
            "shared_files": [{"file": f, "used_by": used_by[f]} for f in shared],
            "screens": screens_out, "shared_items": _finish(shared_items),
            "skipped_candidates": {"count": len(skipped), "sample": skipped[:20]}}
