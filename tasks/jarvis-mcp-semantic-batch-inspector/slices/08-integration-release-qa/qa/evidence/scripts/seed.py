import json, sys, time
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
from corecli import cmd, observe, snap
def art(oid, title, x, y, w=44, h=24, cat="note"):
    return {"op": "upsert_object", "object_id": oid, "fields": {"kind": "artifact", "category": cat, "representation": "capsule",
            "payload": {"title": title, "summary": "", "items": []}, "geometry": {"x": x, "y": y, "w": w, "h": h}}}
out = []
# Constellation « Projet Orion » près du bord gauche : racine + 4 membres (1 masqué, 1 épinglé)
for p in [art("orion", "Projet Orion", -130, -20, cat="research"), art("orion-budget", "Budget Orion", -140, 20),
          art("orion-equipe", "Équipe Orion", -80, -50), art("orion-risques", "Risques Orion", -80, 10),
          art("orion-planning", "Planning Orion", -100, 40), art("courses", "Liste de courses", 60, -40),
          art("idees", "Idées vacances", 70, 20)]:
    out.append(("upsert " + p["object_id"], cmd(p)))
for i, (a, b) in enumerate([("orion", "orion-budget"), ("orion", "orion-equipe"), ("orion-equipe", "orion-risques"), ("orion", "orion-planning")]):
    out.append((f"link {a}->{b}", cmd({"op": "link", "relation": {"relation_id": f"user-rel-{i}", "kind": "groups", "from_id": a, "to_id": b}})))
out.append(("hide orion-risques", cmd({"op": "set_visibility", "object_id": "orion-risques", "visibility": "hidden"})))
out.append(("pin orion-budget", cmd({"op": "pin", "object_id": "orion-budget"})))
out.append(("pin courses", cmd({"op": "pin", "object_id": "courses"})))
# Étoiles : 3 terminées, 1 en cours
out.append(("observe", observe(*[{"external_id": f"qa-{n}", "status": "running", "kind": "agent", "label": l} for n, l in
    [("a", "Recherche billets"), ("b", "Résumé réunion"), ("c", "Analyse logs"), ("d", "Veille techno")]])))
time.sleep(1)
out.append(("finish", observe(*[{"external_id": f"qa-{n}", "status": "completed", "kind": "agent"} for n in "abc"])))
for name, (st, b) in out:
    print(st, name, b.get("outcome"), b.get("reason"), b.get("revision"))
time.sleep(1.5)
s = snap()
print("revision", s["revision"])
for o in s["snapshot"]["objects"]:
    print(o["object_id"], o["kind"], o.get("exec_state"), o.get("visibility"), o.get("pinned_by_user") or o.get("pinned"), o.get("geometry"))
print(len(s["snapshot"]["relations"]), "relations")
