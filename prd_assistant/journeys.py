"""Screen-to-screen journeys from navigation facts and each screen's own files."""


def build(facts, ui):
    shared_files = {x["file"] for x in ui["shared_files"]}
    owners = {}
    for sid, info in ui["screens"].items():
        for f in info["files"]:
            owners.setdefault(f, set()).add(sid)
    labels = {}
    for info in ui["screens"].values():
        for i in info["items"]:
            labels.setdefault((i["file"], i["line"]), i["text"])
    for i in ui["shared_items"]:
        labels.setdefault((i["file"], i["line"]), i["text"])

    edges, shared = [], []
    for n in facts["navigation"]:
        label = labels.get((n["from_file"], n["line"]))
        sources = owners.get(n["from_file"], set()) if n["from_file"] not in shared_files else set()
        if not sources:
            shared.append({"to_screen": n["to_id"], "via": n["source"], "from_file": n["from_file"], "label": label})
            continue
        for sid in sorted(sources):
            if sid != n["to_id"]:
                edges.append({"from_screen": sid, "to_screen": n["to_id"], "via": n["source"], "label": label})

    screens = {sid: {"reached_from": [], "leads_to": [], "shared_nav": False} for sid in ui["screens"]}
    for e in edges:
        if e["to_screen"] in screens:
            screens[e["to_screen"]]["reached_from"] = sorted(set(screens[e["to_screen"]]["reached_from"]) | {e["from_screen"]})
        screens[e["from_screen"]]["leads_to"] = sorted(set(screens[e["from_screen"]]["leads_to"]) | {e["to_screen"]})
    for s in shared:
        if s["to_screen"] in screens:
            screens[s["to_screen"]]["shared_nav"] = True
    return {"schema": 1, "edges": edges, "shared": shared, "screens": screens}
