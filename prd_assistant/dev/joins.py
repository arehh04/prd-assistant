"""Which routes a screen calls: frontend call sites (slice 2 linker) that sit in the screen's evidence files."""


def screen_endpoints(ui, links_result):
    by_file = {}
    for route_id, entry in links_result["routes"].items():
        for call in entry["frontend"]:
            by_file.setdefault(call["file"], set()).add(route_id)
    return {sid: sorted({rid for f in screen["files"] for rid in by_file.get(f, ())})
            for sid, screen in ui["screens"].items()}
