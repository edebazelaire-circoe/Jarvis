"""Migration réelle v7 -> v8 par de vrais processus `python -m jarvis core` (bbm), puis refus et retour arrière (b7e)."""
import json, os, shutil, sqlite3, subprocess, sys, time, urllib.request
from pathlib import Path
S = Path(__file__).parent
PY = r"C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe"
PORT = 18981
out = {}

def start(code_dir, root, rt):
    env = {**os.environ, "PYTHONPATH": code_dir, "JARVIS_DATA_ROOT": str(root), "JARVIS_RUNTIME_DIR": str(rt),
           "JARVIS_CORE_PORT": str(PORT), "JARVIS_CORE_HOST": "127.0.0.1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    rt.mkdir(parents=True, exist_ok=True)
    log = open(rt / "core.out", "w", encoding="utf-8")
    p = subprocess.Popen([PY, "-m", "jarvis", "core"], cwd=code_dir, env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(300):
        time.sleep(0.2)
        text = (rt / "core.out").read_text(encoding="utf-8", errors="replace")
        if "ready on" in text:
            return p, (rt / "core.token").read_text().strip()
        if p.poll() is not None:
            return p, None
    stop(p); raise SystemExit("core did not start")

def stop(p):
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
    p.wait(10)

def req(token, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=data, method=method,
                               headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")

def sql(db, q):
    c = sqlite3.connect(db); 
    try: return c.execute(q).fetchall()
    finally: c.close()

BBM, B7E = r"C:/Projects/jarvis/bbm", r"C:/Projects/jarvis/b7e"
mig = S / "mig"; shutil.rmtree(mig, ignore_errors=True); shutil.copytree(S / "v7root", mig)
db = mig / "state" / "jarvis.sqlite3"
before = {t: sql(db, f'select count(*) from "{t}"')[0][0] for (t,) in sql(db, "select name from sqlite_master where type='table'")}
open_session = sql(db, "select jarvis_session_id, active_board_id from jarvis_sessions where status='open'")[0]
out["v7"] = {"version": sql(db, "select version from schema_version"), "counts": before, "open_session": open_session}

# 1. premier démarrage du code v8
p, tok = start(BBM, mig, S / "migrt1")
st, cur = req(tok, "GET", "/v1/sessions/current")
board = open_session[1]
st2, w = req(tok, "POST", f"/v1/workspace/boards/{board}/memory/write", {"path": "summary.md", "content": "# Atlas\nmigré\n"})
st3, insp = req(tok, "GET", f"/v1/workspace/boards/{board}")
stop(p)
after = {t: sql(db, f'select count(*) from "{t}"')[0][0] for (t,) in sql(db, "select name from sqlite_master where type='table'")}
out["v8_first_start"] = {"version": sql(db, "select version from schema_version"),
    "bak": sorted(x.name for x in db.parent.glob("*.bak")),
    "bak_version": sql(db.parent / "jarvis.sqlite3.v7.bak", "select version from schema_version"),
    "same_session": cur["session"]["jarvis_session_id"] == open_session[0], "current_status": st,
    "write": [st2, w.get("created"), w.get("path")], "inspect": [st3, insp.get("board", {}).get("board_kind"), insp.get("memory", {}).get("files")],
    "lost_rows": {t: (before[t], after.get(t)) for t in before if after.get(t, 0) < before[t]},
    "new_tables": sorted(set(after) - set(before)),
    "links": sql(db, "select count(*) from board_artifact_links")}
# 2. redémarrage : reprise, mémoire relue, une seule sauvegarde
p, tok = start(BBM, mig, S / "migrt2")
st, cur2 = req(tok, "GET", "/v1/sessions/current")
st4, page = req(tok, "GET", f"/v1/workspace/boards/{board}/memory/read?path=summary.md")
stop(p)
out["v8_restart"] = {"same_session": cur2["session"]["jarvis_session_id"] == open_session[0], "read": [st4, page.get("text")],
    "bak": sorted(x.name for x in db.parent.glob("*.bak"))}
# 3. le code v7 refuse la base v8 (sur une copie)
ref = S / "refuse"; shutil.rmtree(ref, ignore_errors=True); shutil.copytree(mig, ref)
p, tok = start(B7E, ref, S / "refusert")
text = (S / "refusert" / "core.out").read_text(encoding="utf-8", errors="replace")
if tok: stop(p)
out["v7_on_v8"] = {"started": tok is not None, "exit": p.poll(), "tail": text.strip().splitlines()[-1:],
                   "version_after": sql(ref / "state" / "jarvis.sqlite3", "select version from schema_version")}
# 4. retour arrière : mettre la base v8 de côté, restaurer .v7.bak, v7 redémarre
rb = S / "rollback"; shutil.rmtree(rb, ignore_errors=True); shutil.copytree(mig, rb)
st_dir = rb / "state"; aside = rb / "aside"; aside.mkdir()
for name in ("jarvis.sqlite3", "jarvis.sqlite3-wal", "jarvis.sqlite3-shm"):
    if (st_dir / name).exists(): shutil.move(st_dir / name, aside / name)
shutil.copy2(st_dir / "jarvis.sqlite3.v7.bak", st_dir / "jarvis.sqlite3")
p, tok = start(B7E, rb, S / "rollbackrt")
st5, cur3 = req(tok, "GET", "/v1/sessions/current") if tok else (None, {})
if tok: stop(p)
out["rollback"] = {"started": tok is not None, "version": sql(st_dir / "jarvis.sqlite3", "select version from schema_version"),
                   "same_session": (cur3.get("session") or {}).get("jarvis_session_id") == open_session[0]}
(S / "migrate.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=1))
