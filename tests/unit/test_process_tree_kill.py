"""`process_tree.kill_tree` : l'arbre est suivi par identité, jamais par `taskkill /T`.

Windows ne rafraîchit pas le PID parent d'un orphelin : un processus étranger dont le PPID périmé égale le PID d'un
processus vivant passerait pour son enfant. Seuls les descendants nés après leur parent sont suivis, et un pid dont
l'heure de création a changé n'est jamais tué.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import time

import pytest

from jarvis.adapters import process_tree

ROOT = Path(__file__).resolve().parents[2]


def test_only_children_born_after_their_parent_are_followed():
    born = {10: "100", 11: "150", 12: "90", 13: "160", 14: "155", 15: None}
    table = [(10, 1), (11, 10), (12, 10), (13, 11), (14, 12), (15, 11), (10, 10)]
    found = process_tree.verified_descendants(10, "100", table, born.get)
    assert found == [(11, "150"), (13, "160")], "12 (born before 10) is a stale-PPID orphan, 14 hangs under it, 15 is gone"


def test_a_cycle_or_an_unreadable_time_never_loops_nor_guesses():
    born = {1: "10", 2: "20", 3: "x"}
    table = [(2, 1), (1, 2), (3, 2)]
    assert process_tree.verified_descendants(1, "10", table, born.get) == [(2, "20")]


def test_the_product_code_never_asks_taskkill_to_follow_the_tree():
    source = (ROOT / "jarvis" / "adapters" / "process_tree.py").read_text(encoding="utf-8")
    assert '"/T"' not in source and "'/T'" not in source


@pytest.mark.skipif(sys.platform != "win32", reason="arbre de processus Windows")
def test_the_tree_stops_by_identity_and_a_changed_identity_is_never_followed():
    spawn_child = ("import subprocess,sys,time;c=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
                   "print(c.pid,flush=True);time.sleep(60)")
    stranger = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"])
    procs = [stranger]
    try:
        parent = subprocess.Popen([sys.executable, "-c", spawn_child], stdout=subprocess.PIPE, text=True)
        procs.append(parent)
        child = int(parent.stdout.readline())
        ref = process_tree.make_process_ref(parent.pid)
        pid, started = process_tree.parse_process_ref(ref)
        assert process_tree.kill_tree(pid, started=started) is True
        parent.wait(timeout=20)
        for _ in range(40):
            if not process_tree.pid_exists(child):
                break
            time.sleep(0.25)
        assert not process_tree.pid_exists(child), "the launched tree is stopped"

        other = subprocess.Popen([sys.executable, "-c", spawn_child], stdout=subprocess.PIPE, text=True)
        procs.append(other)
        grandchild = int(other.stdout.readline())
        assert process_tree.kill_tree(other.pid, started="1") is True, "another identity: our tree is gone"
        assert other.poll() is None and process_tree.pid_exists(grandchild), "a pid under another identity is never touched"
        subprocess.run(["taskkill", "/PID", str(grandchild), "/F"], capture_output=True, check=False)
        assert stranger.poll() is None, "a process outside the tree is never touched"
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)
