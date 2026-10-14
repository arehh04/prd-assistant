"""zod object schemas to request fields, and the NestJS reader that links them through ZodValidationPipe."""
import re

from .. import count
from ..mask import line_of, match_brace, mask
from .source import MAX_INDEX_FILES, line_start, paren_args, read_source, split_args

OBJ_RE = re.compile(r"\b(?:export\s+)?const\s+(\w+)\s*=\s*z\s*\.\s*object\s*\(\s*\{")
FIELD_RE = re.compile(r"^\s*(\w+|'[^']*'|\"[^\"]*\")\s*:\s*(.*)$", re.S)
STR_RE = re.compile(r"""(['"`])((?:\\.|(?!\1)[^\\])*)\1""", re.S)
MOD_RE = re.compile(r"\s*\.\s*(\w+)\s*\(")
FORMATS = {"email", "url", "uuid", "cuid", "cuid2", "ulid", "datetime", "ip", "date", "time"}
PIPE_RE = re.compile(r"@(Body|Query|Param)\(\s*(?:(['\"])(\w+)\2\s*,\s*)?new\s+ZodValidationPipe\(\s*(\w+)\s*\)\s*\)")
NAMED_RE = re.compile(r"@(Body|Query|Param)\(\s*(['\"])(\w+)\2")
LOCATION = {"Body": "body", "Query": "query", "Param": "path"}
DTO_RE = re.compile(r"@(Body|Query)\(\s*\)\s*\w+\s*:\s*(\w+)")


def _num(arg):
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*", arg)
    if not m:
        return None
    return float(m.group(1)) if "." in m.group(1) else int(m.group(1))


def _msg(arg):
    m = STR_RE.fullmatch(arg.strip())
    return m.group(2) if m else None


def _apply(f, name, args):
    first = args[0] if args else ""
    second = args[1] if len(args) > 1 else ""
    msg = None
    if name in ("min", "gte", "gt"):
        f["min"], msg = _num(first), _msg(second)
    elif name in ("max", "lte", "lt"):
        f["max"], msg = _num(first), _msg(second)
    elif name == "length":
        f["min"] = f["max"] = _num(first)
        msg = _msg(second)
    elif name == "nonempty":
        f["min"], msg = 1, _msg(first)
    elif name == "regex":
        f["pattern"], msg = first.strip(), _msg(second)
    elif name in FORMATS:
        f["format"], msg = name, _msg(first)
    elif name in ("optional", "nullish", "default"):
        f["required"] = False
    elif name == "nullable":
        f["nullable"] = True
    else:
        f.setdefault("other", []).append(name)
    if msg:
        f["messages"].append(msg)


def _field(name, chain, rel, line):
    f = {"name": name, "required": True, "type": None, "min": None, "max": None, "pattern": None, "format": None,
         "one_of": None, "messages": [], "raw": " ".join(chain.split())[:200], "source": f"{rel}:{line}"}
    m = re.match(r"\s*z\s*\.\s*(\w+)\s*\(", chain)
    if m:
        f["type"] = m.group(1)
        args = paren_args(chain, m.end() - 1)
        if args is None:
            return f
        if f["type"] == "enum":
            f["one_of"] = [s[1] for s in STR_RE.findall(args)]
        pos = m.end() + len(args) + 1
    else:
        ref = re.match(r"\s*([A-Za-z_]\w*)", chain)
        f["type"] = f"ref:{ref.group(1)}" if ref else None
        pos = ref.end() if ref else 0
    while True:
        mm = MOD_RE.match(chain, pos)
        if not mm:
            break
        args = paren_args(chain, mm.end() - 1)
        if args is None:
            break
        _apply(f, mm.group(1), split_args(args))
        pos = mm.end() + len(args) + 1
    return f


def _object_fields(clean, masked, open_idx, rel):
    close = match_brace(masked, open_idx)
    spans, depth, last = [], 0, open_idx + 1
    for i in range(open_idx + 1, close):
        c = masked[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            spans.append((last, i))
            last = i + 1
    spans.append((last, close))
    out = []
    for a, b in spans:
        raw = clean[a:b]
        m = FIELD_RE.match(raw)
        if m:
            lead = len(raw) - len(raw.lstrip())
            out.append(_field(m.group(1).strip("'\""), m.group(2).strip(), rel, line_of(clean, a + lead)))
    return out


def parse_schemas(text, rel):
    clean = mask(text, blank_strings=False)
    masked = mask(text)
    out = {}
    for m in OBJ_RE.finditer(masked):
        out.setdefault(m.group(1), {"file": rel, "line": line_of(clean, m.start()),
                                    "fields": _object_fields(clean, masked, m.end() - 1, rel)})
    return out


class SchemaIndex:
    def __init__(self, repo_root):
        self.schemas, self.ambiguous = {}, set()
        for n, (rel, _full) in enumerate(count.iter_files(repo_root, (".ts", ".tsx", ".js"))):
            if n >= MAX_INDEX_FILES:
                break
            text = read_source(repo_root, rel)
            if text is None or "z.object" not in text:
                continue
            for name, schema in parse_schemas(text, rel).items():
                if name in self.schemas:
                    self.ambiguous.add(name)
                else:
                    self.schemas[name] = schema
        for name in self.ambiguous:
            self.schemas.pop(name, None)


def read_request(rel, text, line, schemas):
    clean = mask(text, blank_strings=False)
    open_idx = clean.find("(", line_start(text, line))
    params = paren_args(clean, open_idx) if open_idx != -1 else None
    source = f"{rel}:{line}"
    if params is None:
        return {"source": source, "fields": [], "stack": "nestjs",
                "not_read": ["the handler signature could not be read"]}
    fields, not_read, covered = [], [], []
    for m in PIPE_RE.finditer(params):
        covered.append(m.span())
        schema = schemas.get(m.group(4))
        if schema is None:
            not_read.append(f"schema {m.group(4)} was not found or is defined more than once")
            continue
        location = LOCATION[m.group(1)]
        fields += [{**f, "location": location} for f in schema["fields"]]
    for m in NAMED_RE.finditer(params):
        if any(a <= m.start() < b for a, b in covered):
            continue
        fields.append({"name": m.group(3), "location": LOCATION[m.group(1)], "required": None, "type": None,
                       "min": None, "max": None, "pattern": None, "format": None, "one_of": None,
                       "messages": [], "raw": m.group(0) + ")", "source": source})
    for m in DTO_RE.finditer(params):
        not_read.append(f"request class {m.group(2)} (class-validator) is not read")
    return {"source": source, "fields": fields, "not_read": not_read, "stack": "nestjs"}
