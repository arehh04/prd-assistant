"""Feature groups: the shared API prefix and the next path segment after it."""
from collections import Counter

ROOT = "(root)"


def split_path(path):
    path = path.split("?", 1)[0]
    return [s for s in path.strip("/").split("/") if s]


def global_prefix(paths):
    """Longest leading segment run shared by more than half of all routes, extended one segment at a time."""
    segs = [split_path(p) for p in paths]
    total = len(segs)
    prefix, candidates = [], segs
    while True:
        depth = len(prefix)
        counter = Counter(s[depth] for s in candidates if len(s) > depth)
        if not counter:
            break
        seg, n = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        if n * 2 <= total:
            break
        prefix.append(seg)
        candidates = [s for s in candidates if len(s) > depth and s[depth] == seg]
    return prefix


def _assign(items, key_of, letter, field):
    buckets = {}
    for item in items:
        buckets.setdefault(key_of(item), []).append(item)
    keys = sorted(buckets)
    width = max(2, len(str(len(keys))))
    return [{"id": f"{letter}{i:0{width}d}", "key": key, field: buckets[key]}
            for i, key in enumerate(keys, start=1)]


def group_routes(routes):
    prefix = global_prefix([r["path"] for r in routes])

    def key_of(route):
        segs = split_path(route["path"])
        if segs[:len(prefix)] != prefix or len(segs) == len(prefix):
            return ROOT
        return segs[len(prefix)]

    return _assign(routes, key_of, "G", "routes")


def group_screens(screens):
    def key_of(screen):
        segs = split_path(screen["path"])
        return segs[0] if segs else ROOT

    return _assign(screens, key_of, "S", "screens")
