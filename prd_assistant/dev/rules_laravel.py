"""Laravel FormRequest::rules(), messages() and authorize(), followed one level into rule-helper classes."""
import re

from ..mask import match_brace, mask
from .roles_laravel import CHECK_RE
from .source import line_start, paren_args, read_source, split_args

USE_RE = re.compile(r"^use\s+([\w\\]+?)(?:\s+as\s+(\w+))?\s*;", re.M)
NS_RE = re.compile(r"^namespace\s+([\w\\]+)\s*;", re.M)
PARAM_RE = re.compile(r"\b([A-Z]\w*Request)\s+\$\w+")
ENTRY_RE = re.compile(r"""^\s*(?:'([^']+)'|"([^"]+)")\s*=>\s*(.*)$""", re.S)
SPREAD_RE = re.compile(r"^\s*\.\.\.\s*([\w\\]+)::(\w+)\(\s*\)\s*$")
STR_RE = re.compile(r"""^\s*(?:'((?:\\.|[^'\\])*)'|"((?:\\.|[^"\\])*)")\s*$""", re.S)
CONCAT_RE = re.compile(r"""^\s*'([^']*)'\s*\.\s*(?:self|static|([\w\\]+))::(\w+)\s*$""")
SIMPLE_TYPES = {"string", "integer", "numeric", "boolean", "array", "date", "file", "image"}
SIMPLE_FORMATS = {"email", "url", "uuid", "ip", "ulid", "json"}


def _num(text):
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*", text)
    if not m:
        return None
    return float(m.group(1)) if "." in m.group(1) else int(m.group(1))


def _namespace(text):
    m = NS_RE.search(text)
    return m.group(1) if m else ""


def _class_path(short, text, rel):
    fqcn = None
    for m in USE_RE.finditer(text):
        if (m.group(2) or m.group(1).split("\\")[-1]) == short:
            fqcn = m.group(1)
    if fqcn is None:
        ns = _namespace(text)
        fqcn = f"{ns}\\{short}" if ns else None
    if fqcn is None or not fqcn.startswith("App\\") or "app/" not in rel:
        return None
    root = rel[:rel.index("app/")]
    return root + "app/" + fqcn[len("App\\"):].replace("\\", "/") + ".php"


def _method_body(text, masked, name):
    m = re.search(rf"function\s+{name}\s*\(", masked)
    if not m:
        return None
    brace = masked.find("{", m.end())
    if brace == -1:
        return None
    return brace, match_brace(masked, brace)


def _return_array(text, masked, name):
    span = _method_body(text, masked, name)
    if span is None:
        return None
    r = masked.find("return", span[0], span[1])
    if r == -1:
        return None
    start = masked.find("[", r, span[1])
    if start == -1:
        return None
    depth = 0
    for i in range(start, span[1]):
        if masked[i] == "[":
            depth += 1
        elif masked[i] == "]":
            depth -= 1
            if depth == 0:
                return start + 1, i
    return None


def _split_top(masked, text, a, b):
    parts, depth, last = [], 0, a
    for i in range(a, b):
        c = masked[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(text[last:i])
            last = i + 1
    parts.append(text[last:b])
    return [p for p in parts if p.strip()]


def _const(name, owner_text, other_text):
    for body in (owner_text, other_text):
        if body:
            m = re.search(rf"const\s+{name}\s*=\s*(\d+)\s*;", body)
            if m:
                return m.group(1)
    return None


def _tokens(value, class_text, repo_root, rel):
    """Rule tokens (strings) and raw items for one entry value."""
    value = value.strip()
    items = split_args(value[1:-1]) if value.startswith("[") and value.endswith("]") else None
    tokens, raw = [], []
    if items is None:
        m = STR_RE.match(value)
        if m:
            tokens = (m.group(1) if m.group(1) is not None else m.group(2)).split("|")
        else:
            raw.append(value)
        return tokens, raw
    for item in items:
        s = STR_RE.match(item)
        c = CONCAT_RE.match(item)
        if s:
            tokens.append(s.group(1) if s.group(1) is not None else s.group(2))
        elif c:
            other = None
            if c.group(2):
                path = _class_path(c.group(2).split("\\")[-1], class_text, rel)
                other = read_source(repo_root, path) if path else None
            digits = _const(c.group(3), class_text, other)
            if digits is None:
                raw.append(item.strip())
            else:
                tokens.append(c.group(1) + digits)
        else:
            raw.append(item.strip())
    return tokens, raw


def _field(name, tokens, raw, messages, source):
    f = {"name": name, "location": "body", "required": False, "type": None, "min": None, "max": None,
         "pattern": None, "format": None, "one_of": None, "messages": messages, "raw": tokens + raw,
         "source": source}
    for token in tokens:
        key, _, arg = token.partition(":")
        if key == "required":
            f["required"] = True
        elif key in SIMPLE_TYPES:
            f["type"] = key
        elif key in SIMPLE_FORMATS:
            f["format"] = key
        elif key == "min":
            f["min"] = _num(arg)
        elif key == "max":
            f["max"] = _num(arg)
        elif key == "size":
            f["min"] = f["max"] = _num(arg)
        elif key == "between" and "," in arg:
            a, b = arg.split(",", 1)
            f["min"], f["max"] = _num(a), _num(b)
        elif key == "in":
            f["one_of"] = arg.split(",")
        elif key == "regex":
            f["pattern"] = arg
    if "sometimes" in tokens:
        f["required"] = False
    return f


def _line(text, part, start):
    idx = text.find(part.strip(), start)
    return text.count("\n", 0, idx if idx != -1 else start) + 1


def _entries(text, masked, span, rel, repo_root, class_text, depth, not_read, messages_by_field):
    fields = []
    for part in _split_top(masked, text, span[0], span[1]):
        spread = SPREAD_RE.match(part)
        entry = ENTRY_RE.match(part)
        if spread and depth > 0:
            path = _class_path(spread.group(1).split("\\")[-1], class_text, rel)
            helper = read_source(repo_root, path) if path else None
            if helper is None:
                not_read.append(f"rule helper {spread.group(1)}::{spread.group(2)}() could not be read")
                continue
            h_masked = mask(helper, hash_comments=True)
            h_span = _return_array(helper, h_masked, spread.group(2))
            if h_span is None:
                not_read.append(f"rule helper {spread.group(1)}::{spread.group(2)}() has no plain return array")
                continue
            fields += _entries(helper, h_masked, h_span, path, repo_root, helper, depth - 1, not_read,
                               messages_by_field)
        elif entry:
            name = entry.group(1) or entry.group(2)
            tokens, raw = _tokens(entry.group(3), class_text, repo_root, rel)
            fields.append(_field(name, tokens, raw, messages_by_field.get(name, []),
                                 f"{rel}:{_line(text, part, span[0])}"))
        else:
            not_read.append("rule entry not followed: " + " ".join(part.split())[:80])
    return fields


def read_request(rel, text, line, repo_root):
    masked_c = mask(text, hash_comments=True)
    open_idx = masked_c.find("(", line_start(text, line))
    params = paren_args(masked_c, open_idx) if open_idx != -1 else None
    source = f"{rel}:{line}"
    base = {"source": source, "fields": [], "not_read": [], "authorize_checks": [], "request_class": None,
            "stack": "laravel"}
    m = PARAM_RE.search(params or "")
    if not m:
        return base
    short = m.group(1)
    base["request_class"] = short
    path = _class_path(short, text, rel)
    req_text = read_source(repo_root, path) if path else None
    if req_text is None:
        base["not_read"].append(f"request class {short} could not be found or read")
        return base
    clean = mask(req_text, hash_comments=True, blank_strings=False)
    masked = mask(req_text, hash_comments=True)
    messages_by_field = {}
    msg_span = _return_array(clean, masked, "messages")
    if msg_span:
        for part in _split_top(masked, clean, *msg_span):
            e = ENTRY_RE.match(part)
            s = STR_RE.match(e.group(3)) if e else None
            if e and s:
                key = (e.group(1) or e.group(2)).split(".")[0]
                messages_by_field.setdefault(key, []).append(s.group(1) if s.group(1) is not None else s.group(2))
    auth = _method_body(clean, masked, "authorize")
    if auth:
        base["authorize_checks"] = sorted(set(CHECK_RE.findall(clean[auth[0]:auth[1] + 1])))
    span = _return_array(clean, masked, "rules")
    if span is None:
        base["not_read"].append(f"{short}::rules() has no plain return array")
        return base
    base["fields"] = _entries(clean, masked, span, path, repo_root, clean, 1, base["not_read"], messages_by_field)
    return base
