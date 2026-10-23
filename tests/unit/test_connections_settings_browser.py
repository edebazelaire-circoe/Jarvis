"""Connexions › Fournisseurs dans un vrai Chrome sans tête (Slice 07 de jarvis-settings-ui-reorganization).

Contrat : `docs/settings/connections.md`. Un VRAI Control Center isolé (fixture `served` de
`test_wake_word_settings_browser.py` : runtime temporaire, port libre) sert la page ; son magasin de clés est le fichier
de réglages de ce runtime temporaire. Seules des clés factices (`sk-test-FAKE-…`) sont saisies. Ce que ce fichier prouve :

- plus d'onglet « API Keys » : `connections` montre la section Fournisseurs, une carte par fournisseur servi ; l'ancien
  ID `keys` y mène ; le lien d'Agent principal pose le focus sur la carte du fournisseur, celui de la Mémoire ouvre la
  section ;
- ajout, remplacement, choix de la clé active, suppression (après confirmation) : chaque requête part avec sa charge
  figée clé par clé, le fichier du runtime suit, aucune valeur n'est dans le DOM ni dans les champs ni dans les
  réponses de lecture ; statut et erreur dans leurs régions vivantes ;
- la retombée sur une variable d'environnement se dit (nom seul, jamais la valeur) ;
- une réponse arrivée après le départ de la section ne redessine rien, l'état reçu est gardé ; une attente sans réponse
  se dit et rend la main ; une vue détruite arrête son minuteur ;
- tout se fait au clavier ;
- aucune largeur ne déborde à 1920×1080, 1366×768, 100 % et 125 %.

Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import json

import pytest

from jarvis.runtime import credentials as creds
from tests.unit.test_wake_word_settings_browser import click, drive, eval_, got, key, served, type_in, wait, open_settings  # noqa: F401

SECRET = "sk-test-FAKE-perso-1111"
SECRET_2 = "sk-test-FAKE-travail-2222"
SECRET_3 = "sk-test-FAKE-remplace-3333"
ENV_SECRET = "sk-ant-FAKE-env-4444"

OPEN = [
    wait("!!document.getElementById('openSettings')"),
    click("#dockMore"), *open_settings(),
    wait("!!document.getElementById('voiceSection_conversation')"),
    click("#settingsCategories [data-category=connections]"),
    wait("!!document.querySelector('#connection_openai')"),
]
#: Tout ce qui pourrait porter un secret dans la page : le HTML et la valeur de chaque champ.
LEAK = """(()=>{const s=%s,html=document.documentElement.outerHTML,
  fields=[...document.querySelectorAll('input,textarea')].map(e=>e.value).join('\\n');
  return s.filter(x=>html.includes(x)||fields.includes(x))})()"""


def leak(*secrets: str) -> str:
    return LEAK % json.dumps(list(secrets))


#: Chaque appel à `console.log/info/warn/error/debug` de la page, arguments sérialisés (S07 N4, mutation E : une valeur de
#: clé passée à un journal). Posé avant toute saisie ; `CONSOLE_LEAK` dit quelles valeurs y sont passées.
CONSOLE = """(()=>{window.__consoleCalls=[];for(const level of ['log','info','warn','error','debug']){const real=console[level].bind(console);
  console[level]=(...args)=>{let text;try{text=JSON.stringify(args)}catch(_e){text=args.map(String).join(' ')}
    window.__consoleCalls.push(level+' '+text);return real(...args)}}return true})()"""
CONSOLE_LEAK = """(()=>{const s=%s,calls=window.__consoleCalls||[];
  return {calls:calls.length,written:calls.filter(c=>c.includes('connections_credential_written')).length,
    leaked:s.filter(x=>calls.some(c=>c.includes(x)))}})()"""


@pytest.fixture
def clean_env(monkeypatch):
    for spec in creds.PROVIDERS:
        for name in spec.env:
            monkeypatch.delenv(name, raising=False)
    return monkeypatch


TOUR = """(async()=>{const pause=ms=>new Promise(r=>setTimeout(r,ms)),q=s=>document.querySelector(s);
  const all=[];for(const c of window.JarvisSettingsRegistry.CATEGORY_IDS){q(`#settingsCategories [data-category=${c}]`).click();await pause(150);
    all.push(...[...document.querySelectorAll('#modalTabs [role=tab]')].map(b=>b.textContent))}
  selectTab('providers');await pause(250);
  const out={labels:[...document.querySelectorAll('#modalTabs [role=tab]')].map(b=>b.textContent),all,
    at:[SET.category,SET.section],footer:!document.querySelector('.set-foot').hidden,
    cards:[...document.querySelectorAll('#modalContent .conn-card')].map(c=>c.dataset.connProvider),
    served:(await (await fetch('/api/credentials')).json()).providers.map(p=>p.id),
    anthropic:q('#connection_anthropic').textContent.replace(/\\s+/g,' '),tabs:typeof TABS};
  selectTab('voice_audio');await pause(200);selectTab('keys');await pause(250);
  out.alias=[SET.category,SET.section,window.JarvisSettingsRegistry.page.resolve('keys')];
  return out})()"""


async def test_category_cards_alias_environment_fallback_and_links(served, clean_env):
    clean_env.setenv("ANTHROPIC_API_KEY", ENV_SECRET)
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN, eval_(TOUR, "tour"), eval_(leak(ENV_SECRET), "leak"),
        # Runtime & CLI › « Plugins & MCP › anthropic » : la carte du fournisseur des modèles du CLI, focalisée (lien
        # porté par Agent principal jusqu'à la Slice 07 de jarvis-architecture-agents-settings-editor).
        eval_("selectTab('runtime_cli')"),
        wait("!!document.querySelector('#modalContent [data-settings-focus]')", 8000),
        click("#modalContent [data-settings-focus]"),
        wait("SET.section==='providers'&&document.activeElement&&document.activeElement.id==='connection_anthropic_title'"),
        eval_("[SET.category,SET.section,document.activeElement.id]", "agent_link"),
        # Mémoire › Sources de connaissances : « Connexions » ouvre la section.
        eval_("selectTab('knowledge_sources')"),
        wait("!!document.querySelector('#modalContent [data-mem-open]')", 8000),
        click("#modalContent [data-mem-open]"),
        wait("SET.section==='providers'"),
        eval_("[SET.category,SET.section,document.activeElement&&document.activeElement.tagName]", "memory_link"),
    ]}])
    step = out["steps"][0]
    tour = got(step, "tour")
    # Hub du 2026-10-23 : Plugins MCP précède Fournisseurs dans la catégorie (test resté en retard, corrigé à la Slice 07
    # de jarvis-architecture-agents-settings-editor).
    assert tour["labels"] == ["Plugins MCP", "Fournisseurs"] and "API Keys" not in tour["all"]
    assert tour["tabs"] == "undefined"  # Slice 09 : plus de système d'onglets
    assert tour["at"] == ["connections", "providers"] and tour["footer"] is False
    assert tour["cards"] == tour["served"] == [p.id for p in creds.PROVIDERS]
    assert "Variable d’environnement" in tour["anthropic"] and "ANTHROPIC_API_KEY" in tour["anthropic"]
    # Slice 09 : `keys` n'est plus un alias (aucun appelant) ; la section s'ouvre par son ID `providers`.
    assert tour["alias"] == ["voice_audio", "conversation", None]
    assert got(step, "leak") == []
    assert got(step, "agent_link") == ["connections", "providers", "connection_anthropic_title"]
    assert got(step, "memory_link")[:2] == ["connections", "providers"]
    assert got(step, "memory_link")[2] != "BODY"
    assert out["console"] == [], out["console"]


STATE = "(()=>({status:document.getElementById('connectionsStatus').textContent,error:document.getElementById('connectionsError').textContent," \
        "focus:document.activeElement&&(document.activeElement.id||document.activeElement.dataset.bindId||document.activeElement.tagName)}))()"


async def test_add_bind_replace_delete_post_frozen_payloads_and_never_show_a_value(served, clean_env):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN, eval_(CONSOLE),
        # Ajout d'une première clé OpenAI, au clavier : divulgation, nom, valeur, Entrée.
        eval_("document.querySelector('#connection_openai .conn-add>summary').focus()"),
        key("Enter"), key("Tab"),
        type_in("#conn_openai_name", "Perso"), key("Tab"),
        type_in("#conn_openai_value", SECRET), key("Enter"),
        wait("/ajoutée pour OpenAI/.test(document.getElementById('connectionsStatus').textContent)"),
        eval_(STATE, "added"), eval_(leak(SECRET), "leak_added"),
        eval_("""(async()=>{const a=await (await fetch('/api/credentials')).text(),b=await (await fetch('/api/settings')).text();
          return [a.includes(%s),b.includes(%s)]})()""" % (json.dumps(SECRET), json.dumps(SECRET)), "leak_reads"),
        # Doublon refusé : message du serveur dans la région d'erreur, nom gardé, valeur effacée.
        click("#connection_openai .conn-add>summary"),
        type_in("#conn_openai_name", "Perso"), type_in("#conn_openai_value", SECRET_2),
        click("#connection_openai form[data-conn-add] button[type=submit]"),
        wait("/déjà/.test(document.getElementById('connectionsError').textContent)"),
        eval_("[document.getElementById('conn_openai_name').value,document.getElementById('conn_openai_value').value]", "kept"),
        eval_(leak(SECRET_2), "leak_refused"),
        # Seconde clé, puis elle devient l'active.
        type_in("#conn_openai_name", "Travail"), type_in("#conn_openai_value", SECRET_2),
        click("#connection_openai form[data-conn-add] button[type=submit]"),
        wait("document.querySelectorAll('#connection_openai [data-bind-id]').length===2"),
        eval_("[...document.querySelectorAll('#connection_openai [data-bind-id]')].map(r=>[r.closest('li').querySelector('.conn-key-name').textContent,r.checked])", "two"),
        click("#connection_openai li:last-child input[type=radio]"),
        wait("/maintenant la clé OpenAI/.test(document.getElementById('connectionsStatus').textContent)"),
        eval_("[...document.querySelectorAll('#connection_openai [data-bind-id]')].map(r=>r.checked)", "bound"),
        # Remplacement de la valeur de « Perso ». Valeur vide d'abord : refusé sur place, rien n'est envoyé (S07 N4, F).
        click("#connection_openai li:first-child .conn-replace>summary"),
        click("#connection_openai li:first-child form[data-conn-replace] button[type=submit]"),
        wait("/Collez la nouvelle valeur/.test(document.getElementById('connectionsError').textContent)"),
        eval_(STATE, "empty_replace"),
        type_in("#connection_openai li:first-child input[name=value]", SECRET_3),
        click("#connection_openai li:first-child form[data-conn-replace] button[type=submit]"),
        wait("/remplacée/.test(document.getElementById('connectionsStatus').textContent)"),
        eval_(leak(SECRET, SECRET_2, SECRET_3), "leak_all"),
        # Suppression : Annuler n'envoie rien, Supprimer après confirmation.
        click("#connection_openai li:first-child [data-conn-delete]"),
        wait("!!document.querySelector('[data-conn-delete-confirm]')"),
        eval_("document.activeElement.hasAttribute('data-conn-delete-confirm')", "confirm_focus"),
        click("[data-conn-delete-cancel]"),
        wait("!document.querySelector('[data-conn-delete-confirm]')"),
        click("#connection_openai li:first-child [data-conn-delete]"),
        wait("!!document.querySelector('[data-conn-delete-confirm]')"),
        click("[data-conn-delete-confirm]"),
        wait("document.querySelectorAll('#connection_openai [data-bind-id]').length===1"),
        eval_(STATE, "deleted"),
        eval_(CONSOLE_LEAK % json.dumps([SECRET, SECRET_2, SECRET_3]), "console_leak"),
    ]}])
    step = out["steps"][0]
    posts = [(r["path"], json.loads(r["body"])) for r in out["requests"] if r["method"] == "POST"]
    stored = served.stored()
    perso = next(c for c in stored.get("credentials", []) if c["name"] == "Travail")
    assert posts[0] == ("/api/credentials", {"provider": "openai", "name": "Perso", "value": SECRET})
    assert list(posts[0][1]) == ["provider", "name", "value"]
    assert posts[1] == ("/api/credentials", {"provider": "openai", "name": "Perso", "value": SECRET_2})
    assert posts[2] == ("/api/credentials", {"provider": "openai", "name": "Travail", "value": SECRET_2})
    assert posts[3][0] == "/api/credentials/bind" and list(posts[3][1]) == ["provider", "id"]
    assert posts[3][1] == {"provider": "openai", "id": perso["id"]}
    assert posts[4][0] == "/api/credentials" and list(posts[4][1]) == ["id", "provider", "name", "value"]
    assert posts[4][1]["name"] == "Perso" and posts[4][1]["value"] == SECRET_3
    assert posts[5][0] == "/api/credentials/delete" and posts[5][1] == {"id": posts[4][1]["id"]}
    assert len(posts) == 6  # « Annuler » et le remplacement à valeur vide n'ont rien envoyé
    empty = got(step, "empty_replace")
    assert "remplacée" not in empty["status"] and empty["error"] == "Collez la nouvelle valeur avant de remplacer."
    console = got(step, "console_leak")
    assert console["written"] == 5 and console["leaked"] == [], console  # journaux vus, sans aucune valeur
    added = got(step, "added")
    assert added["status"] == "Clé « Perso » ajoutée pour OpenAI." and added["error"] == ""
    assert added["focus"].startswith("conn_bind_cred_")  # le bouton radio de la nouvelle clé
    assert got(step, "leak_added") == [] and got(step, "leak_reads") == [False, False]
    assert got(step, "kept") == ["Perso", ""] and got(step, "leak_refused") == []
    assert got(step, "two") == [["Perso", True], ["Travail", False]]
    assert got(step, "bound") == [False, True]
    assert got(step, "leak_all") == []
    assert got(step, "confirm_focus") is True
    deleted = got(step, "deleted")
    assert deleted["status"] == "Clé « Perso » supprimée." and deleted["focus"] == "connection_openai_title"
    assert [(c["name"], c["value"]) for c in stored["credentials"]] == [("Travail", SECRET_2)]
    assert stored["credential_bindings"] == {"openai": perso["id"]}
    assert out["console"] == [], out["console"]


#: Les POST du magasin retenus par la page jusqu'à `__release()` : la réponse arrive quand on le décide.
HOLD = """(()=>{window.__held=[];const real=window.fetch;
  window.fetch=(u,o)=>String(u).startsWith('/api/credentials')&&o&&o.method==='POST'
    ?new Promise(r=>window.__held.push(()=>real(u,o).then(r))):real(u,o);
  window.__release=()=>{window.__held.splice(0).forEach(go=>go())};return true})()"""


@pytest.mark.parametrize("leave", ["section", "close"])
async def test_a_late_response_redraws_nothing_once_the_section_is_left(served, clean_env, leave):
    away = "selectTab('shortcuts')" if leave == "section" else "closeSettings()"
    gone = "!document.getElementById('connection_google')" if leave == "section" else "SET.open===false"
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN, eval_(HOLD),
        click("#connection_google .conn-add>summary"),
        type_in("#conn_google_name", "Perso"), type_in("#conn_google_value", "AIza-FAKE-5555"),
        click("#connection_google form[data-conn-add] button[type=submit]"),
        wait("window.__held.length===1"),
        eval_("[document.getElementById('conn_google_value').value,document.getElementById('connectionsStatus').textContent]", "pending"),
        eval_(away),
        wait(gone),
        eval_("window.__marker=document.getElementById('modalContent').innerHTML;window.__release();true"),
        wait("SET.data.credentials.credentials.length===1", 6000),
        eval_("""new Promise(r=>setTimeout(()=>r({same:document.getElementById('modalContent').innerHTML===window.__marker,
          cards:document.querySelectorAll('.conn-card').length,open:SET.open,section:SET.section,
          stored:SET.data.credentials.credentials.map(c=>[c.provider,c.name,c.bound])}),400))""", "after"),
    ]}])
    step = out["steps"][0]
    assert got(step, "pending") == ["", "Enregistrement de la clé Google (Gemini)…"]
    after = got(step, "after")
    assert after["same"] is True  # rien n'est redessiné
    assert after["stored"] == [["google", "Perso", True]]  # l'état reçu est gardé (vrai côté serveur)
    if leave == "section":
        assert after["open"] is True and after["section"] == "shortcuts" and after["cards"] == 0
    else:
        assert after["open"] is False
    assert [c["name"] for c in served.stored()["credentials"]] == ["Perso"]
    assert out["console"] == [], out["console"]


#: Le module seul, monté dans un hôte de la page avec une requête qui ne répond jamais et un délai court : l'attente se
#: dit et rend la main ; une vue détruite pendant l'attente n'écrit plus rien et ne journalise rien.
TIMER = """(async()=>{const M=window.JarvisConnectionsSettings,pause=ms=>new Promise(r=>setTimeout(r,ms));
  const state=await (await fetch('/api/credentials')).json(),logs=[];
  const log={info:(c)=>logs.push(['info',c]),warn:(c)=>logs.push(['warn',c]),error:(c)=>logs.push(['error',c])};
  const make=()=>{const host=document.createElement('div');document.body.appendChild(host);
    const view=M.create(host,{request:()=>new Promise(()=>{}),state,waitMs:250,log});view.load();return {host,view}};
  const submit=host=>{host.querySelector('#conn_openai_name').value='X';host.querySelector('#conn_openai_value').value='sk-test-FAKE-6666';
    host.querySelector('form[data-conn-add]').requestSubmit()};
  const a=make();submit(a.host);await pause(50);
  const busy=a.host.querySelector('#conn_openai_name').disabled;
  await pause(400);
  const slow={busy,error:a.host.querySelector('#connectionsError').textContent,released:!a.host.querySelector('#conn_openai_name').disabled};
  const b=make();submit(b.host);await pause(50);const before=b.host.innerHTML;b.view.destroy();await pause(400);
  const dead={same:b.host.innerHTML===before,destroyed:b.view.destroyed};
  a.host.remove();b.host.remove();
  return {slow,dead,logs}})()"""


async def test_waiting_has_a_deadline_and_a_destroyed_view_stops_its_timer(served, clean_env):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [*OPEN, eval_(TIMER, "timer")]}])
    result = got(out["steps"][0], "timer")
    assert result["slow"]["busy"] is True and result["slow"]["released"] is True
    assert result["slow"]["error"].startswith("Pas de réponse du Control Center après 0 s")
    assert result["dead"] == {"same": True, "destroyed": True}
    assert result["logs"] == [["warn", "connections_credential_slow"]]  # une fois : la vue détruite s'est tue
    assert out["console"] == [], out["console"]


#: S07 N1 et N2 : le module seul, avec des requêtes dont la page décide la réponse et une échéance courte.
#: N1 : un succès arrivé après l'échéance dit le succès et efface l'erreur d'attente.
#: N2 : la réponse d'un ajout dépassé, arrivée pendant un second envoi, est ignorée : elle ne remet pas l'ancien nom
#: dans le champ, ne déplace pas le focus et ne dit rien ; le second envoi conclut normalement.
LATE = """(async()=>{const M=window.JarvisConnectionsSettings,pause=ms=>new Promise(r=>setTimeout(r,ms));
  const state=await (await fetch('/api/credentials')).json(),log={info(){},warn(){},error(){}};
  const reply=name=>({...state,credentials:[{id:'cred_'+name,provider:'openai',name,hint:'…FAKE',bound:false}]});
  const make=()=>{const held=[],host=document.createElement('div');document.body.appendChild(host);
    const view=M.create(host,{request:()=>new Promise(r=>held.push(r)),state,waitMs:400,log});view.load();return {host,view,held}};
  const submit=(host,name)=>{host.querySelector('#conn_openai_name').value=name;host.querySelector('#conn_openai_value').value='sk-test-FAKE-7777';
    host.querySelector('form[data-conn-add]').requestSubmit()};
  const read=host=>({status:host.querySelector('#connectionsStatus').textContent,error:host.querySelector('#connectionsError').textContent});
  const a=make();submit(a.host,'Tard');await pause(600);
  const timedOut=read(a.host);
  a.held[0](reply('Tard'));await pause(100);
  const n1={timedOut,after:read(a.host)};
  const b=make();submit(b.host,'Premier');await pause(600);
  b.host.querySelector('#connection_openai .conn-add').open=true;submit(b.host,'Second');await pause(30);
  const field=()=>b.host.querySelector('#conn_openai_name');
  const marker=document.activeElement;
  b.held[0](reply('Premier'));await pause(60);
  const during={name:field().value,focusMoved:document.activeElement!==marker,error:read(b.host).error,status:read(b.host).status,
    busy:field().disabled};
  b.held[1](reply('Second'));await pause(100);
  const n2={during,after:read(b.host)};
  a.view.destroy();b.view.destroy();a.host.remove();b.host.remove();
  return {n1,n2}})()"""


async def test_a_late_success_clears_the_deadline_error_and_an_ignored_reply_touches_nothing(served, clean_env):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [*OPEN, eval_(LATE, "late")]}])
    result = got(out["steps"][0], "late")
    n1, n2 = result["n1"], result["n2"]
    assert n1["timedOut"]["error"].startswith("Pas de réponse du Control Center")
    assert n1["after"] == {"status": "Clé « Tard » ajoutée pour OpenAI.", "error": ""}
    during = n2["during"]
    assert during["name"] != "Premier" and during["focusMoved"] is False and during["busy"] is True, during
    assert during["error"] == "" and during["status"] == "Enregistrement de la clé OpenAI…", during
    assert n2["after"] == {"status": "Clé « Second » ajoutée pour OpenAI.", "error": ""}
    assert out["console"] == [], out["console"]


LAYOUT = """(async()=>{const pause=ms=>new Promise(r=>setTimeout(r,ms));selectTab('providers');await pause(300);
  document.querySelectorAll('#modalContent details').forEach(d=>{d.open=true});await pause(200);
  const body=document.getElementById('modalContent'),main=document.getElementById('settingsMain');
  const wide=[...body.querySelectorAll('*')].filter(e=>e.getBoundingClientRect().right>body.getBoundingClientRect().right+1)
    .slice(0,3).map(e=>e.tagName+'.'+e.className);
  return {page:document.documentElement.scrollWidth-innerWidth,content:body.scrollWidth-body.clientWidth,
    main:main.scrollWidth-main.clientWidth,wide}})()"""


@pytest.mark.parametrize(("width", "height"), [(1920, 1080), (1366, 768), (1536, 864), (1093, 614)])
async def test_no_connection_card_overflows(served, clean_env, width, height):
    """1536×864 et 1093×614 : la largeur CSS de 1920×1080 et 1366×768 à 125 % de zoom. Deux clés OpenAI, divulgations
    ouvertes : la carte la plus chargée."""
    settings = {}
    creds.upsert_credential(settings, provider="openai", name="Une clé au nom assez long pour tester le retour", value=SECRET)
    creds.upsert_credential(settings, provider="openai", name="Travail", value=SECRET_2)
    served.control._write_settings(settings)
    out = await drive(served.url, [{"width": width, "height": height, "actions": [*OPEN, eval_(LAYOUT, "layout")]}])
    row = got(out["steps"][0], "layout")
    assert row["page"] <= 0 and row["content"] <= 1 and row["main"] <= 0 and row["wide"] == [], row
