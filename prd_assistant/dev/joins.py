"""Which routes a screen calls: frontend call sites (slice 2 linker) in the screen's files or in files they import."""
from .. import ui_text

EXTRA_HOPS = 2      # imports followed beyond the screen's slice 3 evidence files (page -> hook -> api layer)
MAX_FILES = 300     # per screen


def _closure(repo_root, start, cache):
    def aliases_for(directory):
        if directory not in cache:
            cache[directory] = ui_text.load_aliases(repo_root, directory)
        return cache[directory]

    seen = list(dict.fromkeys(start))
    frontier = list(seen)
    for _ in range(EXTRA_HOPS):
        nxt = []
        for rel in frontier:
            text = ui_text._read_ui_file(repo_root, rel)
            if text is None:
                continue
            for target in ui_text._depth1_imports(repo_root, rel, text, aliases_for):
                if target not in seen and len(seen) < MAX_FILES:
                    seen.append(target)
                    nxt.append(target)
        frontier = nxt
        if not frontier:
            break
    return seen


def screen_endpoints(ui, links_result, repo_root=None):
    by_file = {}
    for route_id, entry in links_result["routes"].items():
        for call in entry["frontend"]:
            by_file.setdefault(call["file"], set()).add(route_id)
    cache, out = {}, {}
    for sid, screen in ui["screens"].items():
        files = _closure(repo_root, screen["files"], cache) if repo_root is not None else screen["files"]
        out[sid] = sorted({rid for f in files for rid in by_file.get(f, ())})
    return out
