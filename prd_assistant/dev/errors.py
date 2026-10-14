"""error_messages.json: the messages an endpoint can return, with status, kind and source."""
import ast
import re

from .. import count, paths
from ..mask import line_of, match_brace, mask
from .pyast import PyIndex, http_exception, py_tree
from .roles_fastapi import _find_handler
from .source import line_start, paren_args, read_source, split_args, split_source

COMPUTED = "message is computed or not a plain string"
MAX_THROWS = 500
TS_STATUS = {
    "BadRequestException": 400, "UnauthorizedException": 401, "PaymentRequiredException": 402,
    "ForbiddenException": 403, "NotFoundException": 404, "MethodNotAllowedException": 405,
    "NotAcceptableException": 406, "RequestTimeoutException": 408, "ConflictException": 409,
    "GoneException": 410, "PayloadTooLargeException": 413, "UnsupportedMediaTypeException": 415,
    "UnprocessableEntityException": 422, "TooManyRequestsException": 429, "InternalServerErrorException": 500,
    "NotImplementedException": 501, "BadGatewayException": 502, "ServiceUnavailableException": 503,
    "GatewayTimeoutException": 504}
HTTP_STATUS = {"BAD_REQUEST": 400, "UNAUTHORIZED": 401, "FORBIDDEN": 403, "NOT_FOUND": 404, "CONFLICT": 409,
               "UNPROCESSABLE_ENTITY": 422, "TOO_MANY_REQUESTS": 429, "INTERNAL_SERVER_ERROR": 500}
THROW_TS_RE = re.compile(r"\bthrow\s+new\s+(\w+)\s*\(")
THROW_PHP_RE = re.compile(r"\bthrow\s+new\s+([\w\\]+)\s*\(")
ABORT_RE = re.compile(r"\babort\s*\(")
ABORT_IF_RE = re.compile(r"\babort_(?:if|unless)\s*\(")
SITE_RES = {".py": re.compile(r"\braise\s+HTTPException\b"),
            ".ts": re.compile(r"\bthrow\s+new\s+\w*(?:Exception|Error)\b"),
            ".js": re.compile(r"\bthrow\s+new\s+\w*(?:Exception|Error)\b"),
            ".php": re.compile(r"\babort(?:_if|_unless)?\s*\(|\bthrow\s+new\s+[\w\\]*Exception\b")}


def find_function(tree, line):
    return _find_handler(tree, line) if tree is not None else None


def _py_text(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return "literal", node.value
    if isinstance(node, ast.JoinedStr):
        parts = [str(v.value) if isinstance(v, ast.Constant) else "{…}" for v in node.values]
        return "template", "".join(parts)
    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value == "message":
                return _py_text(value)
    return None, None


def _message(rel, line, status, kind, text, via, helper):
    out = {"status": status, "kind": kind, "text": text, "via": via, "source": f"{rel}:{line}"}
    if helper:
        out["helper"] = helper
    return out


def py_messages(rel, fn, via, helper=None):
    messages, not_read = [], []
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Raise) and node.exc is not None):
            continue
        got = http_exception(node.exc)
        if not got:
            continue
        status, detail = got
        kind, text = _py_text(detail)
        if text is None:
            not_read.append(COMPUTED)
        else:
            messages.append(_message(rel, node.lineno, status, kind, text, via, helper))
    return messages, not_read


def _body(clean, masked, start_line, text):
    open_idx = masked.find("(", line_start(text, start_line))
    if open_idx == -1:
        return None
    args = paren_args(clean, open_idx)
    if args is None:
        return None
    brace = masked.find("{", open_idx + len(args) + 2)
    if brace == -1:
        return None
    return brace, match_brace(masked, brace)


def _ts_text(arg):
    arg = arg.strip()
    m = re.fullmatch(r"(['\"])((?:\\.|(?!\1)[^\\])*)\1", arg, re.S)
    if m:
        return "literal", m.group(2)
    m = re.fullmatch(r"`((?:\\.|[^`\\])*)`", arg, re.S)
    if m:
        t = re.sub(r"\$\{[^}]*\}", "{…}", m.group(1))
        return ("template" if "{…}" in t else "literal"), t
    m = re.fullmatch(r"\{(.*)\}", arg, re.S)
    if m:
        inner = re.search(r"\bmessage\s*:\s*('[^']*'|\"[^\"]*\"|`[^`]*`)", m.group(1))
        if inner:
            return _ts_text(inner.group(1))
    return None, None


def _status_arg(arg):
    arg = arg.strip()
    if re.fullmatch(r"\d{3}", arg):
        return int(arg)
    m = re.fullmatch(r"HttpStatus\.(\w+)", arg)
    return HTTP_STATUS.get(m.group(1)) if m else None


def ts_messages(rel, text, start_line, via, helper=None):
    clean = mask(text, blank_strings=False)
    masked = mask(text)
    span = _body(clean, masked, start_line, text)
    messages, not_read = [], []
    if span is None:
        return messages, ["the function body could not be located"]
    body = clean[span[0]:span[1] + 1]
    for n, m in enumerate(THROW_TS_RE.finditer(body)):
        if n >= MAX_THROWS:
            not_read.append(f"more than {MAX_THROWS} throw sites in one function")
            break
        name = m.group(1)
        parts = split_args(paren_args(body, m.end() - 1) or "")
        line = line_of(clean, span[0] + m.start())
        if name in TS_STATUS:
            status, first = TS_STATUS[name], (parts[0] if parts else "")
        elif name == "HttpException":
            status, first = (_status_arg(parts[1]) if len(parts) > 1 else None), (parts[0] if parts else "")
        elif name.endswith(("Exception", "Error")):
            not_read.append(f"{name} has no HTTP status that can be read")
            continue
        else:
            continue
        kind, msg = _ts_text(first)
        if msg is None:
            not_read.append(COMPUTED)
        else:
            messages.append(_message(rel, line, status, kind, msg, via, helper))
    return messages, not_read


def _php_text(arg):
    a = arg.strip()
    m = re.fullmatch(r"'((?:\\.|[^'\\])*)'", a, re.S)
    if m:
        return "literal", m.group(1)
    m = re.fullmatch(r'"((?:\\.|[^"\\])*)"', a, re.S)
    if m:
        t = re.sub(r"\{\$[^}]*\}|\$\w+(?:->\w+|\[[^\]]*\])*", "{…}", m.group(1))
        return ("template" if "{…}" in t else "literal"), t
    return None, None


def php_messages(rel, text, start_line, via, helper=None):
    clean = mask(text, hash_comments=True, blank_strings=False)
    masked = mask(text, hash_comments=True)
    span = _body(clean, masked, start_line, text)
    messages, not_read = [], []
    if span is None:
        return messages, ["the function body could not be located"]
    body = clean[span[0]:span[1] + 1]

    def add(pos, status, msg_arg):
        kind, msg = _php_text(msg_arg) if msg_arg is not None else (None, None)
        if msg is None:
            not_read.append(COMPUTED)
        else:
            messages.append(_message(rel, line_of(clean, span[0] + pos), status, kind, msg, via, helper))

    for m in list(ABORT_RE.finditer(body))[:MAX_THROWS]:
        parts = split_args(paren_args(body, m.end() - 1) or "")
        add(m.start(), _status_arg(parts[0]) if parts else None, parts[1] if len(parts) > 1 else None)
    for m in list(ABORT_IF_RE.finditer(body))[:MAX_THROWS]:
        parts = split_args(paren_args(body, m.end() - 1) or "")
        add(m.start(), _status_arg(parts[1]) if len(parts) > 1 else None, parts[2] if len(parts) > 2 else None)
    for m in list(THROW_PHP_RE.finditer(body))[:MAX_THROWS]:
        if not m.group(1).endswith("Exception"):
            continue
        parts = split_args(paren_args(body, m.end() - 1) or "")
        add(m.start(), _status_arg(parts[1]) if len(parts) > 1 else None, parts[0] if parts else None)
    messages.sort(key=lambda x: int(x["source"].rsplit(":", 1)[1]))
    return messages, not_read


def callees(conn, handler_id):
    rows = conn.execute(
        "select distinct t.id, t.name, t.file_path, t.start_line from edges e join nodes t on t.id = e.target "
        "where e.source = ? and e.kind = 'calls' and t.kind in ('function', 'method') and t.id != ?",
        (handler_id, handler_id)).fetchall()
    return [r for r in rows if not paths.exclusion_reason(r["file_path"])][:25]


def _extract(repo_root, rel, line, via, helper, pyidx):
    text = read_source(repo_root, rel)
    if text is None:
        return [], ["the file could not be read"]
    if rel.endswith(".py"):
        fn = find_function(pyidx.trees.get(rel) or py_tree(text), line)
        return ([], ["the function was not found in its file"]) if fn is None else py_messages(rel, fn, via, helper)
    if rel.endswith((".ts", ".js")):
        return ts_messages(rel, text, line, via, helper)
    if rel.endswith(".php"):
        return php_messages(rel, text, line, via, helper)
    return [], ["no reader for this file type"]


def _count_sites(repo_root):
    total = 0
    for rel, _full in count.iter_files(repo_root, tuple(SITE_RES)):
        text = read_source(repo_root, rel)
        if text is None:
            continue
        suffix = rel[rel.rfind("."):]
        total += len(SITE_RES[suffix].findall(mask(text, hash_comments=rel.endswith((".php", ".py")))))
    return total


def build(repo_root, facts, roles, conn):
    pyidx = PyIndex(repo_root)
    messages, not_read = [], {}

    def note(reasons):
        for reason in reasons:
            not_read[reason] = not_read.get(reason, 0) + 1

    for route in facts["routes"]:
        handler = route.get("handler")
        if not handler:
            continue
        rid = route["id"]
        rel, line = split_source(handler["source"])
        jobs = [(rel, line, "handler", None)]
        for guard in (roles["endpoints"].get(rid, {}).get("guards") or []):
            g_rel, g_line = split_source(guard)
            jobs.append((g_rel, g_line, "guard", None))
        if conn is not None and handler.get("id"):
            for c in callees(conn, handler["id"]):
                jobs.append((c["file_path"], c["start_line"], "helper", c["name"]))
        elif handler.get("id"):
            note(["no CodeGraph index: helper messages were not read"])
        for j_rel, j_line, via, helper in jobs:
            try:
                found, unread = _extract(repo_root, j_rel, j_line, via, helper, pyidx)
            except Exception as exc:  # a hostile file must not stop the run
                found, unread = [], [f"reader error: {type(exc).__name__}"]
            messages += [{"route": rid, **m} for m in found]
            note(unread)
    attached = len({m["source"] for m in messages})
    total = max(_count_sites(repo_root), attached)
    return {"schema_version": 1, "messages": messages, "sites": {"total": total, "attached": attached},
            "unattached": total - attached, "not_read": dict(sorted(not_read.items())),
            "counts": {"messages": len(messages)}}
