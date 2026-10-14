"""Frontend form rules: HTML validation attributes on inputs and zod schemas passed to zodResolver."""
import re

from ..mask import line_of, mask
from .source import read_source

FORM_TAGS = {"input", "textarea", "select", "Input", "Textarea", "Select", "InputText", "InputNumber", "el-input"}
TAG_RE = re.compile(r"<([A-Za-z][\w.\-]*)")
ATTR_RE = re.compile(r"""([:@\w.\-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|\{([^{}]*)\}))?""")
REGISTER_RE = re.compile(r"register\(\s*['\"](\w+)['\"]")
RESOLVER_RE = re.compile(r"zodResolver\(\s*(\w+)\s*\)")
MAX_TAG = 2000


def _tag_text(text, start):
    depth, quote, i = 0, None, start
    limit = min(len(text), start + MAX_TAG)
    while i < limit:
        c = text[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == ">" and depth <= 0:
            return text[start:i]
        i += 1
    return None


def _value(raw):
    raw = raw.strip().strip("'\"")
    return int(raw) if re.fullmatch(r"-?\d+", raw) else raw


def _clean(text, rel):
    if rel.endswith(".vue"):
        return re.sub(r"<!--.*?-->", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    return mask(text, blank_strings=False, apostrophe_in_words=True)


def read_forms(repo_root, files, schemas):
    fields, schema_names, unnamed = [], [], 0
    for rel in files:
        text = read_source(repo_root, rel)
        if text is None:
            continue
        clean = _clean(text, rel)
        for m in RESOLVER_RE.finditer(clean):
            schema = schemas.get(m.group(1))
            if schema is not None and m.group(1) not in schema_names:
                schema_names.append(m.group(1))
                for f in schema["fields"]:
                    fields.append({"field": f["name"], "required": f["required"],
                                   "minlength": f["min"] if f["type"] == "string" else None,
                                   "maxlength": f["max"] if f["type"] == "string" else None,
                                   "min": f["min"] if f["type"] == "number" else None,
                                   "max": f["max"] if f["type"] == "number" else None,
                                   "pattern": f["pattern"], "type": f["type"], "from_schema": m.group(1),
                                   "source": f["source"]})
        skip_until = 0
        for m in TAG_RE.finditer(clean):
            if m.group(1) not in FORM_TAGS or m.start() < skip_until:
                continue
            attrs_text = _tag_text(clean, m.end())
            if attrs_text is None:
                skip_until = m.end() + MAX_TAG  # an unterminated tag: do not rescan the same text for every `<input`
                continue
            attrs = {}
            for a in ATTR_RE.finditer(attrs_text):
                value = a.group(2) if a.group(2) is not None else a.group(3) if a.group(3) is not None else a.group(4)
                attrs[a.group(1).lower()] = True if value is None else _value(value)
            reg = REGISTER_RE.search(attrs_text)
            name = attrs.get("name") or (reg.group(1) if reg else None)
            if not name and isinstance(attrs.get("v-model"), str):
                name = attrs["v-model"].split(".")[-1]
            name = name or attrs.get("id")
            if not isinstance(name, str) or not name:
                unnamed += 1
                continue
            fields.append({"field": name, "required": bool(attrs.get("required")),
                           "minlength": attrs.get("minlength"), "maxlength": attrs.get("maxlength"),
                           "min": attrs.get("min"), "max": attrs.get("max"), "pattern": attrs.get("pattern"),
                           "type": attrs.get("type"), "source": f"{rel}:{line_of(clean, m.start())}"})
    return {"fields": fields, "schemas": schema_names, "unnamed": unnamed}
