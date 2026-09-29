"""Alertes attribuées et « Aller au Board », exécutés par node (handoff board-session, Slice 07).

Même monde que `test_boards_hud_js.py` (DOM, minuteries et réseau doublés ; le
module est le fichier que la page insère). Ce que ce fichier épingle :

- l'étiquette du Board d'une alerte : discrète pour le Board actif, mise en
  avant (et assortie d'une action) pour un autre ; rien quand la trace ne
  nommait aucun Board ;
- les pastilles comptent ce qui vient d'**ailleurs**, et seulement quand le
  Board actif est connu ;
- « Aller au Board » est **la bascule normale** : `POST /api/boards/switch`
  avec le seul `board_id` (aucun contexte transporté), attente visible sur le
  bouton avec compteur, refus dit sur place, pas de double envoi, et rien
  n'est envoyé si une autre action Boards est en vol.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

from jarvis.runtime.control_center import ControlCenter
from tests.unit.test_boards_hud_js import PAGE_HTML, run_node

JUMP = r"""
const jump=(m,over)=>{
  const button=makeNode('button');button.textContent='Aller au Board →';
  const note=makeNode('p');note.hidden=true;
  const journal=[];
  const run=B.goToBoardFromAlert(Object.assign({control:m.control,button,note,boardId:'board_b',title:'Projet B',
    now:()=>clock,setInterval:setIntervalD,clearInterval:clearD,setTimeout:setTimeoutD,clearTimeout:clearD,
    log:(level,event,data)=>journal.push({level,event,data})},over||{}));
  return {button,note,journal,run};
};
"""


def test_an_alert_names_its_board_quietly_here_and_loudly_elsewhere(tmp_path):
    result = run_node(tmp_path, r"""
      out({
        here:B.alertBoardOf({board_id:'default',board_title:'Jarvis'},'default'),
        away:B.alertBoardOf({board_id:'board_b',board_title:'Projet B'},'default'),
        untitled:B.alertBoardOf({board_id:'board_c',board_title:null},'default'),
        unknownActive:B.alertBoardOf({board_id:'board_b',board_title:'Projet B'},null),
        none:B.alertBoardOf({board_id:null},'default'),
      });
    """)
    assert result["here"] == {"board_id": "default", "title": "Jarvis", "here": True,
                              "label": "Ce Board · Jarvis", "action": ""}
    assert result["away"] == {"board_id": "board_b", "title": "Projet B", "here": False,
                              "label": "Board « Projet B »", "action": "Aller au Board « Projet B »"}
    assert result["untitled"]["label"] == "Board « board_c »", "the id when the title is not known yet"
    assert result["unknownActive"]["here"] is False
    assert result["none"] is None


def test_pills_count_what_comes_from_another_board_only_when_the_active_one_is_known(tmp_path):
    result = run_node(tmp_path, r"""
      const sources=[{board_id:'default',title:'Jarvis',counts:{failed:1}},
        {board_id:'board_b',title:'Projet B',counts:{failed:2,done:1}},{board_id:'',counts:{done:4}},'junk'];
      const away=B.elsewhereOf(sources,'default');
      out({away,unknown:B.elsewhereOf(sources,null),none:B.elsewhereOf(undefined,'default'),
        label:B.pillLabelOf('Arrière-plan · 3 échecs',away.failed),plain:B.pillLabelOf('Arrière-plan · 1 échec',[])});
    """)
    assert result["away"] == {"failed": [{"board_id": "board_b", "title": "Projet B", "count": 2}],
                              "done": [{"board_id": "board_b", "title": "Projet B", "count": 1}]}
    assert result["unknown"] == {} and result["none"] == {}
    assert result["label"] == "Arrière-plan · 3 échecs · dont 2 sur « Projet B »"
    assert result["plain"] == "Arrière-plan · 1 échec"


def test_go_to_board_is_the_normal_switch_with_its_wait_on_the_clicked_button(tmp_path):
    result = run_node(tmp_path, JUMP + r"""
      const m=mount();
      m.server.plan['POST /api/boards/switch']=[{delay:3000}];
      const j=jump(m);
      await settle();advance(2000);await settle();
      const during={text:j.button.textContent,busy:j.button.getAttribute('aria-busy'),
        disabled:j.button.getAttribute('aria-disabled'),hud:m.tone(),hudSub:m.sub()};
      const again=await B.goToBoardFromAlert({control:m.control,button:j.button,note:j.note,boardId:'board_b'});
      advance(1500);await settle();
      const ok=await j.run;await settle();
      out({during,again,ok,after:{text:j.button.textContent,busy:j.button.getAttribute('aria-busy'),
        note:j.note.hidden},posts:m.server.calls.filter(c=>c.method==='POST'),title:m.title(),
        toast:m.toasts[m.toasts.length-1],journal:j.journal.map(x=>x.event)});
    """)
    during = result["during"]
    assert during["text"] == "Bascule… 2 s", "a live counter on the button the user clicked"
    assert during["busy"] == "true" and during["disabled"] == "true"
    assert during["hud"] == "pending" and during["hudSub"] == "Bascule · 2 s", "the same transaction as the panel"
    assert result["again"] is False, "a second click sends nothing"
    assert result["ok"] is True
    assert result["posts"] == [{"path": "/api/boards/switch", "method": "POST", "body": {"board_id": "board_b"}}], \
        "only the Board travels: no alert, no context"
    assert result["after"] == {"text": "Aller au Board →", "busy": None, "note": True}
    assert result["title"] == "Projet B"
    assert result["toast"]["title"] == "Board « Projet B » actif.", "the alert's title names the target"
    assert result["journal"] == ["boards.alert_jump_requested", "boards.alert_jump_done"]


def test_a_refused_jump_says_why_next_to_the_button_and_keeps_the_board(tmp_path):
    result = run_node(tmp_path, JUMP + r"""
      const m=mount();
      m.server.plan['POST /api/boards/switch']=[{status:502,code:'board_activation_failed',message:'host said no'}];
      const j=jump(m);
      const ok=await j.run;await settle();
      out({ok,note:j.note.textContent,hidden:j.note.hidden,text:j.button.textContent,
        busy:j.button.getAttribute('aria-busy'),title:m.title(),journal:j.journal.map(x=>[x.level,x.event])});
    """)
    assert result["ok"] is False and result["hidden"] is False
    assert result["note"].startswith("L’agent du Board n’a pas pu démarrer. Rien n’a changé")
    assert "board_activation_failed · host said no" in result["note"], "the real cause stays readable"
    assert result["text"] == "Aller au Board →" and result["busy"] is None
    assert result["title"] == "Jarvis"
    assert ["warn", "boards.alert_jump_refused"] in result["journal"]


def test_a_jump_that_never_answers_gives_the_hand_back_at_the_switch_deadline(tmp_path):
    result = run_node(tmp_path, JUMP + r"""
      const m=mount();
      m.server.plan['POST /api/boards/switch']=[{hang:true}];
      const j=jump(m);
      await settle();advance(B.DEADLINE_MS.switch+500);await settle();
      const ok=await j.run;
      out({ok,note:j.note.textContent,text:j.button.textContent,busy:j.button.getAttribute('aria-busy'),
        journal:j.journal.map(x=>x.event)});
    """)
    assert result["ok"] is False
    assert "boards.alert_jump_expired" in result["journal"]
    assert result["note"].startswith("Pas de réponse au bout de 75 s")
    assert result["text"] == "Aller au Board →" and result["busy"] is None


def test_nothing_is_sent_while_another_boards_action_is_in_flight_or_without_the_control(tmp_path):
    result = run_node(tmp_path, JUMP + r"""
      const m=mount();
      m.trigger.fire('click');await settle();
      m.server.plan['POST /api/sessions/new']=[{hang:true}];
      m.newSession().fire('click');await settle();
      const j=jump(m);const busy=await j.run;
      const missing=jump(m,{control:null});const none=await missing.run;
      out({busy,busyNote:j.note.textContent,none,noneNote:missing.note.textContent,
        switches:m.server.calls.filter(c=>c.path==='/api/boards/switch').length,
        missingLog:missing.journal.map(x=>[x.level,x.event,x.data.code])});
    """)
    assert result["busy"] is False and result["busyNote"].startswith("Une autre action Boards est en cours")
    assert result["none"] is False and "pas installé" in result["noneNote"]
    assert result["switches"] == 0
    assert result["missingLog"] == [["error", "boards.alert_jump_failed", "boards_control_missing"]]


@pytest.mark.asyncio
async def test_the_served_page_wires_the_alerts_to_the_boards_switch(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    html = (await control.index(None)).text
    assert "renderBackgroundPills(s.background,s.boards)" in html
    assert "goToBoardFromAlert" in html and "control:window.JarvisBoardsControl" in html
    assert "switchTo:control.switchTo" in html, "the installed control exposes the normal switch"
    source = PAGE_HTML.read_text(encoding="utf-8")
    assert re.search(r"\.bgpill\.elsewhere::before\{", source)
    await control.board_brains.aclose()
