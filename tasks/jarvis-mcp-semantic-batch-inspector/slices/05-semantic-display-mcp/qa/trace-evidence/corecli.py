"""Petit client Core isolé (garde : refuse 17653/17654)."""
import json, os, sys, urllib.request
from datetime import datetime, timezone
PORT = os.environ.get("JARVIS_CORE_PORT", "")
HOST = os.environ.get("JARVIS_CORE_HOST", "127.77.0.1")
if not PORT or PORT in ("17653", "17654"):
    sys.exit("REFUSE: bad core port %r" % PORT)
TOKEN = open(os.path.join(os.environ["JARVIS_RUNTIME_DIR"], "core.token"), encoding="utf-8").read().strip()
from jarvis.domain.v2 import PROTOCOL_VERSION  # noqa

def req(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(f"http://{HOST}:{PORT}{path}", data=data, method=method, headers={
        "Authorization": f"Bearer {TOKEN}", "X-Jarvis-Protocol": str(PROTOCOL_VERSION), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")

def cmd(payload, actor="user"):
    st, b = req("POST", "/v1/scene/commands", {"schema_version": 1, "actor": actor, **payload})
    return st, b

def observe(*items):
    now = datetime.now(timezone.utc).isoformat()
    return req("POST", "/v1/work/observations", {"source": "claude", "producer_id": "qa-seed", "observations": [
        {"source": "claude", "observed_at": now, **i} for i in items]})

def snap():
    return req("GET", "/v1/scene/snapshot")[1]
