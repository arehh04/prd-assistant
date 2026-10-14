"""Index README and docs headings so the model can cite them by file:line."""
import re
from pathlib import Path

from . import count

AGENT_FILES = {"agents.md", "claude.md", "gemini.md"}
MAX_BYTES = 2_000_000
EXCERPT_LINES = 12
EXCERPT_CHARS = 1200
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _doc_files(root):
    for rel, full in count.iter_files(root, (".md",), include_tests=True):
        parts = rel.split("/")
        if len(parts) > 1 and parts[0] != "docs":
            continue
        if Path(rel).name.lower() in AGENT_FILES:
            continue
        if full.stat().st_size > MAX_BYTES:
            continue
        yield rel, full


def _sections(lines):
    sections, current, fenced = [], None, False
    for number, line in enumerate(lines, start=1):
        if FENCE_RE.match(line):
            fenced = not fenced
        match = None if fenced else HEADING_RE.match(line)
        if match:
            if current:
                sections.append(current)
            current = {"heading": match.group(2), "level": len(match.group(1)), "line": number, "body": []}
            continue
        if current is None:
            if not line.strip():
                continue
            current = {"heading": "(top)", "level": 0, "line": number, "body": []}
        current["body"].append(line)
    if current:
        sections.append(current)
    return sections


def index_docs(repo_root):
    entries = []
    for rel, full in sorted(_doc_files(repo_root)):
        lines = count.read_text(full).split("\n")
        if lines and lines[-1] == "":
            lines.pop()  # a trailing newline is not an extra line
        sections = _sections(lines)
        for i, s in enumerate(sections):
            end = sections[i + 1]["line"] - 1 if i + 1 < len(sections) else len(lines)
            body = [ln for ln in s["body"] if ln.strip()][:EXCERPT_LINES]
            entries.append({
                "id": f"D{len(entries) + 1:03d}", "file": rel, "heading": s["heading"],
                "level": s["level"], "line": s["line"], "end_line": end,
                "excerpt": "\n".join(body)[:EXCERPT_CHARS],
            })
    return {"schema": 1, "entries": entries}
