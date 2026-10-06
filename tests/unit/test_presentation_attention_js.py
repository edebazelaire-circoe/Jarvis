"""La logique pure de l'avertissement de vérification, exécutée sous node (Slice 09).

Ce fichier ne lit **jamais** la source du module : il la charge et l'exécute.
La Slice 03 a livré trois tests qui affirmaient sur du texte et ont manqué les
trois défauts qu'ils existaient pour attraper ; le LOG du handoff en a fait une
règle pour cette Slice.

Le partage avec `test_presentation_attention_browser.py` est délibéré :

- **ici** : les fonctions pures, exhaustivement et pour trois francs — la porte
  du son entre onglets, le modèle de vue et sa tolérance aux charges utiles
  malformées ;
- **là-bas** : tout ce qui n'est vrai que dans un navigateur — géométrie, style
  calculé, `localStorage` réellement partagé entre deux onglets, requêtes
  réseau réelles, oscillateurs WebAudio réellement créés.

Ce qui est ici est ce qu'on veut pouvoir casser en une seconde.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import PRESENTATION_ATTENTION_SCRIPT_FILE

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / PRESENTATION_ATTENTION_SCRIPT_FILE

#: Le prélude. Le module s'installe seul quand `window` et `document` existent ;
#: sous node ils n'existent pas, donc il ne fait qu'exporter son API — ce qui
#: est exactement le chemin qu'on veut éprouver ici.
WORLD = """
const M=require(MODULE_PATH);
const out=v=>process.stdout.write(JSON.stringify(v));

/* Un `localStorage` en mémoire, avec des interrupteurs de panne : c'est la
   seule façon d'atteindre les branches « stockage refusé », qui sont
   exactement celles qu'un navigateur en navigation privée emprunte. */
function makeStorage(options){
  const opts=options||{};
  const values=Object.create(null);
  return {
    values:values,
    reads:0,writes:0,
    getItem(key){this.reads+=1;if(opts.readThrows)throw new Error('lecture refusee');
      return Object.prototype.hasOwnProperty.call(values,key)?values[key]:null},
    setItem(key,value){this.writes+=1;if(opts.writeThrows)throw new Error('ecriture refusee');
      values[key]=String(value)},
    removeItem(key){delete values[key]},
  };
}

function entry(over){
  const o=over||{};
  return {
    seq:o.seq===undefined?7:o.seq,
    ts:'2026-09-24T10:00:00+00:00',
    label:o.label===undefined?'Une affirmation est contredite par une source verifiee':o.label,
    detail:o.detail===undefined?'2 sources \\u00b7 confiance elevee':o.detail,
    attention:o.attention===undefined?{
      attention_id:o.id===undefined?'att-1':o.id,
      category:o.category===undefined?'contradiction':o.category,
      severity:'warning',
      band:o.band===undefined?'high':o.band,
      claim_id:'claim-1',topic_id:'topic-1',source_count:2,
      evidence:o.evidence===undefined?[
        {source_id:'src-1',locator:'https://exemple.test/1',title:'Rapport',resource_id:'res-1'},
        {source_id:'src-2',locator:'doc:interne/bilan',title:'Bilan',resource_id:''},
      ]:o.evidence,
      resource_ids:['res-1'],
    }:o.attention,
  };
}

function background(items,seq){
  return {seq:seq===undefined?7:seq,unread:items.length,
    counts:items.length?{attention:items.length}:{},attention:items};
}
"""


def run_node(tmp_path: Path, source: str, name: str = "pa") -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"presentation-attention-{name}.cjs"
    script.write_text(
        f"const MODULE_PATH={json.dumps(str(MODULE))};\n{WORLD}\n"
        f"(async()=>{{\n{source}\n}})().catch(e=>{{"
        "console.error(e&&e.stack||String(e));process.exit(1)});\n",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ==========================================================================
# 1. La porte du son entre onglets
# ==========================================================================


def test_le_premier_onglet_prend_le_bail_et_sonne(tmp_path):
    """Le cas nominal : personne ne mène, cet onglet prend la main et sonne."""

    seen = run_node(tmp_path, """
      const storage=makeStorage();
      const first=M.claimCue(7,{storage,now:1000,tabId:'A'});
      out({first,leader:JSON.parse(storage.values[M.CUE.leaderKey]),
           mark:Number(storage.values[M.CUE.markKey])});
    """, "lease")
    assert seen["first"] is True
    assert seen["leader"]["id"] == "A"
    assert seen["mark"] == 7


def test_un_second_onglet_ne_sonne_pas_pendant_le_bail(tmp_path):
    """Le trou que cette Slice bouche, dans sa forme la plus simple.

    Deux onglets voient la même hausse à quelques centaines de millisecondes
    d'écart. Un seul doit sonner — et le second doit quand même pouvoir
    **montrer** l'avertissement, ce qui est vérifié à part.
    """

    seen = run_node(tmp_path, """
      const storage=makeStorage();
      const a=M.claimCue(7,{storage,now:1000,tabId:'A'});
      const b=M.claimCue(7,{storage,now:1200,tabId:'B'});
      out({a,b,writes:storage.writes});
    """, "twotabs")
    assert seen["a"] is True
    assert seen["b"] is False


def test_le_bail_seul_retient_un_onglet_que_la_borne_ne_retient_pas(tmp_path):
    """Le bail porte quelque chose que la borne haute ne porte pas.

    Survivant de mutation M33 : neutraliser la condition de bail ne cassait
    rien, parce que le test des deux onglets portait sur le **meme** numero de
    sequence, que la borne haute bloque de toute facon. Le bail n'etait donc
    teste que la ou il etait redondant.

    Ici la sequence monte entre les deux lectures — le cas reel de deux
    contradictions coup sur coup — et la borne ne peut plus rien : seul le bail
    empeche le second onglet de sonner par-dessus le premier.
    """

    seen = run_node(tmp_path, """
      const storage=makeStorage();
      const a=M.claimCue(7,{storage,now:1000,tabId:'A'});
      // B voit une sequence PLUS HAUTE : la borne haute ne l'arrete pas.
      const b=M.claimCue(8,{storage,now:1150,tabId:'B'});
      // A, lui, mene toujours et peut signaler la nouvelle.
      const again=M.claimCue(8,{storage,now:1300,tabId:'A'});
      out({a,b,again,mark:Number(storage.values[M.CUE.markKey])});
    """, "leaseonly")
    assert seen["a"] is True
    assert seen["b"] is False, "un onglet qui ne mene pas ne sonne pas, meme sur du neuf"
    assert seen["again"] is True
    assert seen["mark"] == 8


def test_un_onglet_meneur_qui_disparait_laisse_la_main(tmp_path):
    """Un bail périmé n'immobilise pas le son : sinon fermer un onglet rendrait muet."""

    seen = run_node(tmp_path, """
      const storage=makeStorage();
      M.claimCue(7,{storage,now:1000,tabId:'A'});
      // Le meneur s'est tu : plus de 3 s se sont ecoulees.
      const b=M.claimCue(8,{storage,now:1000+M.CUE.leaseMs+1,tabId:'B'});
      out({b,leader:JSON.parse(storage.values[M.CUE.leaderKey]).id});
    """, "expired")
    assert seen["b"] is True
    assert seen["leader"] == "B"


def test_la_borne_haute_tient_meme_quand_le_bail_a_change_de_main(tmp_path):
    """La seconde ceinture, et la seule qui survit au rechargement.

    Si le bail expire et qu'un autre onglet le prend, il ne doit pas re-sonner
    pour un numéro déjà joué. Sans cette borne, fermer l'onglet meneur ferait
    rejouer le dernier signal.
    """

    seen = run_node(tmp_path, """
      const storage=makeStorage();
      M.claimCue(7,{storage,now:1000,tabId:'A'});
      const again=M.claimCue(7,{storage,now:1000+M.CUE.leaseMs+1,tabId:'B'});
      // **Et A, lui, peut-il encore sonner ?** La version precedente de ce test
      // n'interrogeait que B, donc elle atteignait l'etat ou B est refuse par la
      // borne apres avoir pris le bail — exactement le defaut B1 — sans jamais
      // demander ce qu'il en coutait a l'autre onglet.
      const aStillCan=M.claimCue(8,{storage,now:1000+M.CUE.leaseMs+2,tabId:'A'});
      const older=M.claimCue(5,{storage,now:1000+2*M.CUE.leaseMs,tabId:'B'});
      const newer=M.claimCue(9,{storage,now:1000+3*M.CUE.leaseMs,tabId:'B'});
      out({again,aStillCan,older,newer});
    """, "mark")
    assert seen["again"] is False
    assert seen["aStillCan"] is True, "un onglet refuse par la borne ne bloque personne"
    assert seen["older"] is False
    assert seen["newer"] is True


def test_un_onglet_refuse_par_la_borne_ne_garde_pas_le_bail(tmp_path):
    """**B1.** Un onglet qui n'emet rien ne doit pas faire taire les autres.

    Le defaut : le bail etait pris AVANT que la borne haute ne soit consultee,
    et jamais rendu quand elle refusait. Un onglet reveille en retard — ce que
    Chrome fait de tout onglet cache — prenait donc le bail pour trois secondes
    en n'emettant rien, et le seul onglet capable de signaler la contradiction
    suivante se taisait.

    C'est l'inverse exact de la preference que l'en-tete de ce module declare :
    « un silence la ou D11 demande un signal est le defaut que ce module existe
    pour eviter ». Le bail est une serialisation, pas un droit de veto.

    Le test suit la trace exacte relevee par QA dans un vrai navigateur : A
    signale 100, B se reveille apres l'expiration et est refuse par la borne,
    puis un evenement **genuinement nouveau** arrive.
    """

    seen = run_node(tmp_path, """
      const storage=makeStorage();
      const a=M.claimCue(100,{storage,now:1000,tabId:'A'});
      // B se reveille apres l'expiration du bail et retrouve la meme sequence :
      // il n'a rien a annoncer.
      const b=M.claimCue(100,{storage,now:1000+M.CUE.leaseMs+200,tabId:'B'});
      const leaderAfter=storage.values[M.CUE.leaderKey]||null;
      // Une contradiction genuinement nouvelle, vue par A.
      const a2=M.claimCue(101,{storage,now:1000+M.CUE.leaseMs+300,tabId:'A'});
      out({a,b,a2,leaderAfter:leaderAfter?JSON.parse(leaderAfter).id:null});
    """, "b1lease")

    assert seen["a"] is True
    assert seen["b"] is False, "B n'a rien a annoncer"
    # Le coeur du defaut : B ne doit pas etre devenu meneur en refusant.
    assert seen["leaderAfter"] != "B", seen
    # Et la consequence, qui est ce qui comptait vraiment.
    assert seen["a2"] is True, "un evenement neuf doit encore pouvoir sonner"


def test_un_bail_pris_a_rebours_d_horloge_ne_fait_taire_personne(tmp_path):
    """Point 10 : une correction d'horloge vers l'arriere rendait le delta negatif.

    Un delta negatif etait lu comme « bail tenu », donc tout onglet non meneur
    se taisait pendant toute la duree du saut — qui n'est borne par rien.
    """

    seen = run_node(tmp_path, """
      const storage=makeStorage();
      M.claimCue(100,{storage,now:60000,tabId:'A'});
      // L'horloge recule d'une minute : le bail de A est date du futur.
      const b=M.claimCue(101,{storage,now:1000,tabId:'B'});
      out({b,leader:JSON.parse(storage.values[M.CUE.leaderKey]).id});
    """, "b1clock")
    assert seen["b"] is True, "un bail date du futur n'est pas un bail tenu"
    assert seen["leader"] == "B"


def test_le_meme_onglet_ne_sonne_pas_deux_fois_pour_le_meme_numero(tmp_path):
    """La porte **consomme** le numéro : la rappeler n'ouvre pas une seconde fois."""

    seen = run_node(tmp_path, """
      const storage=makeStorage();
      out([M.claimCue(7,{storage,now:1000,tabId:'A'}),
           M.claimCue(7,{storage,now:1100,tabId:'A'}),
           M.claimCue(7,{storage,now:1200,tabId:'A'})]);
    """, "idempotent")
    assert seen == [True, False, False]


@pytest.mark.parametrize("failure", ["none", "readThrows", "writeThrows", "absent"])
def test_sans_stockage_utilisable_la_porte_s_ouvre(tmp_path, failure):
    """Un son de trop est un défaut mineur ; un silence est celui qu'on refuse.

    Trois formes de panne réelles — navigation privée, quota, origine opaque —
    plus l'absence pure. La branche saine est dans la même table pour que le
    test ne passe pas simplement parce qu'il ouvre toujours.
    """

    seen = run_node(tmp_path, f"""
      const mode={json.dumps(failure)};
      const storage=mode==='absent'?null:makeStorage(
        mode==='none'?{{}}:{{[mode]:true}});
      out(M.claimCue(7,{{storage,now:1000,tabId:'A'}}));
    """, f"storage-{failure}")
    assert seen is True


def test_un_numero_de_sequence_absurde_n_ecrit_rien(tmp_path):
    seen = run_node(tmp_path, """
      const storage=makeStorage();
      const answers=[M.claimCue(0,{storage,now:1,tabId:'A'}),
                     M.claimCue(-4,{storage,now:1,tabId:'A'}),
                     M.claimCue('rien',{storage,now:1,tabId:'A'}),
                     M.claimCue(null,{storage,now:1,tabId:'A'})];
      out({answers,writes:storage.writes});
    """, "absurd")
    assert seen["answers"] == [True, True, True, True]
    assert seen["writes"] == 0, "une sequence absurde ne doit pas salir la borne"


# ==========================================================================
# 2. Le modèle de vue
# ==========================================================================


def test_un_point_d_attention_donne_exactement_une_carte(tmp_path):
    seen = run_node(tmp_path, """
      out(M.viewOf(background([entry()]),[]));
    """, "one")
    assert len(seen) == 1
    card = seen[0]
    assert card["id"] == "att-1"
    assert card["title"] == "Contradiction"
    assert card["tone"] == "warn"
    assert card["bandWord"] == "confiance élevée"
    assert [s["openable"] for s in card["sources"]] == [True, False]


def test_deux_lignes_pour_le_meme_point_ne_donnent_qu_une_carte(tmp_path):
    """La ceinture d'identité côté page.

    Le magasin coalesce déjà côté Core sur `(catégorie, affirmation, sujet)` ;
    si malgré cela deux lignes portaient la même identité, la page n'en
    montrerait — et n'en signalerait — qu'une.
    """

    seen = run_node(tmp_path, """
      out(M.viewOf(background([entry({seq:7}),entry({seq:8})]),[]));
    """, "dup")
    assert len(seen) == 1


def test_un_point_ecarte_ne_revient_pas(tmp_path):
    seen = run_node(tmp_path, """
      out({kept:M.viewOf(background([entry(),entry({id:'att-2'})]),['att-1'])
             .map(c=>c.id)});
    """, "dismissed")
    assert seen["kept"] == ["att-2"]


@pytest.mark.parametrize("block", [
    "null", "undefined", "'texte'", "42", "{}", "{attention:null}",
    "{attention:'pas une liste'}", "{attention:[null,1,'x']}",
    "{attention:[{}]}", "{attention:[{attention:{}}]}",
    "{attention:[{attention:{attention_id:''}}]}",
])
def test_un_bloc_de_statut_malforme_ne_leve_jamais(tmp_path, block):
    """`refreshStatus` est la seule boucle de cette page : rien n'a le droit d'y lever.

    Un serveur plus ancien ne connaît pas `attention` ; un serveur cassé peut
    envoyer n'importe quoi. Les deux doivent donner zéro carte, jamais une
    exception qui emporterait le statut, la scène et la chronologie.
    """

    seen = run_node(tmp_path, f"out(M.viewOf({block},[]));", "hostile")
    assert seen == []


def test_une_categorie_inconnue_reste_neutre(tmp_path):
    """Un serveur plus récent peut nommer une catégorie que cette page ignore.

    La peindre en avertissement serait une affirmation que personne ne peut
    soutenir — même règle que le ton `other` du contrôle de mode.
    """

    seen = run_node(tmp_path, """
      out(M.viewOf(background([entry({category:'quelque_chose_de_neuf'})]),[])[0]);
    """, "unknown-cat")
    assert seen["tone"] == "info"
    assert seen["title"] == "À vérifier"


def test_une_bande_inconnue_retombe_sur_la_plus_prudente(tmp_path):
    seen = run_node(tmp_path, """
      out([M.bandWord('high'),M.bandWord('moderate'),M.bandWord('extreme'),
           M.bandWord(null),M.bandWord('constructor')]);
    """, "band")
    assert seen == ["confiance élevée", "confiance moyenne", "confiance moyenne",
                    "confiance moyenne", "confiance moyenne"]


def test_une_piece_sans_locator_n_est_pas_montree(tmp_path):
    """Une source sans référence n'est pas une preuve : elle ne s'affiche pas."""

    seen = run_node(tmp_path, """
      out(M.sourcesOf([
        {source_id:'a',locator:'',title:'vide'},
        {source_id:'b',title:'absent'},
        null,'x',
        {source_id:'c',locator:'https://ok.test/1'},
      ]));
    """, "locators")
    assert [s["locator"] for s in seen] == ["https://ok.test/1"]
    # Sans titre, c'est le locator qui sert d'étiquette : jamais une case vide.
    assert seen[0]["title"] == "https://ok.test/1"


@pytest.mark.parametrize("locator,expected", [
    ("https://exemple.test/a", True),
    ("http://exemple.test/a", True),
    ("file:///C:/rapports/bilan.pdf", True),
    ("doc:interne/bilan", False),
    ("chart:ventes", False),
    ("scene:obj-1", False),
    ("dataset:ventes", False),
    ("note:memo", False),
    ("javascript:alert(1)", False),
    ("data:text/html,<script>", False),
    ("", False),
])
def test_seuls_les_schemas_qu_un_navigateur_ouvre_deviennent_des_liens(tmp_path, locator, expected):
    """Les références internes de la Slice 04 ne sont pas des liens morts.

    `ALLOWED_LOCATOR_SCHEMES` en admet huit ; trois seulement s'ouvrent dans un
    navigateur. Les autres se montrent en clair. Et `javascript:` n'y est pas,
    ce qui est la raison la plus importante pour que cette table soit une liste
    blanche et non une liste d'exclusion.
    """

    seen = run_node(tmp_path, f"out(M.openable({json.dumps(locator)}));", "scheme")
    assert seen is expected


def test_la_memoire_des_ecartes_est_bornee_et_tolerante(tmp_path):
    seen = run_node(tmp_path, """
      const storage=makeStorage();
      storage.values[M.CUE.dismissKey]=JSON.stringify(
        Array.from({length:100},(_,i)=>'att-'+i).concat(['att-0',null,'']));
      const kept=M.dismissedFrom(storage);
      const broken=makeStorage();broken.values[M.CUE.dismissKey]='{pas du json';
      out({count:kept.length,unique:new Set(kept).size,
           first:kept[0],broken:M.dismissedFrom(broken),none:M.dismissedFrom(null)});
    """, "dismissmem")
    assert seen["count"] == seen["unique"] == 32
    assert seen["first"] == "att-0"
    assert seen["broken"] == []
    assert seen["none"] == []


# ==========================================================================
# 4. Le ton du signal (Slice 10) — le vrai code de la page, exécuté
# ==========================================================================
#
# `bgCue` et `renderBackgroundPills` vivent dans `control_center.html`, pas
# dans le module. Ils sont **extraits** de la page par leur déclaration et
# exécutés tels quels sous node, avec un `AudioContext` de mesure : on compte
# les oscillateurs créés, leurs fréquences et le gain atteint. Rien n'est
# affirmé sur le texte de la source, sauf la garde statique de l'émetteur unique.

PAGE = ROOT / "jarvis" / "runtime" / "control_center.html"

#: Ce que l'extraction prend de la page, dans l'ordre où la page le déclare.
CUE_DECLARATIONS = ("BG", "bgActiveId", "bgBoards", "BG_TONES", "bgCue", "bgCueTone", "bgCueAllowed",
                    "BG_CATS", "bgCat", "bgCount", "renderBackgroundPills")

CUE_WORLD = """
const AUDIO={contexts:0,freqs:[],peaks:[],tones:[]};
class FakeParam{setValueAtTime(){} linearRampToValueAtTime(v){AUDIO.peaks.push(v)} exponentialRampToValueAtTime(){}}
class FakeContext{
  constructor(){AUDIO.contexts+=1;this.state='running';this.currentTime=0;this.destination={}}
  createOscillator(){const o={type:'',frequency:{value:0},connect:g=>g,start(){AUDIO.freqs.push(o.frequency.value)},stop(){}};return o}
  createGain(){return {gain:new FakeParam(),connect:d=>d}}
  resume(){return Promise.resolve()}
}
const window={AudioContext:FakeContext};
const box={innerHTML:'',hidden:true,querySelector(){return null}};
const $=selector=>selector==='#bgPills'?box:null;
const document={querySelector(){return null}};
const esc=value=>String(value);
function toast(){}
function closeBackgroundPop(){}
function placeBackgroundPop(){}
"""


def _balanced_end(text: str, start: int, *, statement: bool) -> int:
    """Fin d'une déclaration de premier niveau : corps de fonction, ou `;` d'un `const`.

    Petit lecteur à pile : chaînes, gabarits (et leurs `${…}` imbriqués) et
    commentaires sont sautés, de sorte qu'une accolade dans un texte ne
    compte pas.
    """

    depth, i, opened = 0, start, False
    while i < len(text):
        ch = text[i]
        if text.startswith("/*", i):
            i = text.index("*/", i) + 2
            continue
        if text.startswith("//", i):
            i = text.index("\n", i)
            continue
        if ch in "'\"":
            i += 1
            while text[i] != ch:
                i += 2 if text[i] == "\\" else 1
        elif ch == "`":
            i = _template_end(text, i)
        elif ch in "([{":
            depth, opened = depth + 1, True
        elif ch in ")]}":
            depth -= 1
            if depth == 0 and opened and not statement and ch == "}":
                return i + 1
        elif ch == ";" and depth == 0 and statement:
            return i + 1
        i += 1
    raise AssertionError("déclaration non terminée")


def _template_end(text: str, start: int) -> int:
    i = start + 1
    while text[i] != "`":
        if text[i] == "\\":
            i += 2
            continue
        if text.startswith("${", i):
            i = _balanced_end(text, i + 1, statement=False) - 1
        i += 1
    return i


def _page_declarations(names: tuple[str, ...]) -> str:
    html = PAGE.read_text(encoding="utf-8")
    chunks = []
    for name in names:
        found = re.search(rf"^(function {name}\(|const {name}=)", html, re.M)
        assert found, f"{name} absent de la page"
        statement = found.group(1).startswith("const")
        chunks.append(html[found.start():_balanced_end(html, found.start(), statement=statement)])
    return "\n".join(chunks)


def run_page_cue(tmp_path: Path, source: str, name: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"page-cue-{name}.cjs"
    script.write_text(
        CUE_WORLD + _page_declarations(CUE_DECLARATIONS)
        + "\nconst pageCue=bgCue;bgCue=function(tone){AUDIO.tones.push(tone);return pageCue(tone)};\n"
        + "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        + "const render=(seq,counts)=>renderBackgroundPills("
        + "{seq,unread:Object.values(counts).reduce((a,b)=>a+b,0),counts},null);\n"
        + source,
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_attention_only_rise_plays_attention_tone(tmp_path):
    """Une hausse faite seulement d'un point à vérifier : le ton `attention`, plus doux que `bad`."""

    seen = run_page_cue(tmp_path, """
      render(3,{done:1});                       // premier sondage : arme, ne sonne pas
      render(4,{done:1,attention:1});           // seul « à vérifier » monte
      const attention={tones:[...AUDIO.tones],freqs:[...AUDIO.freqs],peaks:[...AUDIO.peaks]};
      AUDIO.tones.length=0;AUDIO.freqs.length=0;AUDIO.peaks.length=0;
      bgCue('bad');
      out({attention,bad:{freqs:AUDIO.freqs,peaks:AUDIO.peaks},contexts:AUDIO.contexts,
           tones:Object.keys(BG_TONES)});
    """, "attention")
    attention, bad = seen["attention"], seen["bad"]
    assert attention["tones"] == ["attention"]
    assert len(attention["freqs"]) == 2, "deux notes, comme les autres tons"
    assert set(attention["freqs"]).isdisjoint(bad["freqs"]), "un intervalle distinct de l'échec"
    assert max(attention["peaks"]) < max(bad["peaks"]), "plus doux que l'échec"
    assert seen["contexts"] == 1, "un seul contexte audio pour tous les tons"
    assert set(seen["tones"]) == {"ok", "bad", "attention"}


def test_failure_wins_over_attention(tmp_path):
    """Un échec et un point à vérifier montent ensemble : c'est l'échec qu'on entend."""

    seen = run_page_cue(tmp_path, """
      render(5,{attention:1});
      render(6,{attention:2,failed:1});
      const both=[...AUDIO.tones];
      render(7,{attention:2,failed:2});         // l'échec monte seul : toujours grave
      render(8,{attention:3,failed:2});         // « à vérifier » seul : doux, même avec un échec en attente
      render(9,{attention:3,failed:2,done:1});  // une tâche finie : la règle d'avant
      render(10,{attention:4,failed:3,done:2}); // l'échec monte avec les autres : il gagne
      out({both,all:AUDIO.tones,freqs:AUDIO.freqs.slice(0,2)});
    """, "failure")
    assert seen["both"] == ["bad"]
    assert seen["all"] == ["bad", "bad", "attention", "bad", "bad"]
    assert seen["freqs"] == [392, 294]


def test_attention_rising_with_a_finished_task_plays_attention_tone(tmp_path):
    """Un point à vérifier et une tâche finie montent ensemble, sans échec qui monte : `attention` (p13)."""

    seen = run_page_cue(tmp_path, """
      render(3,{});                             // premier sondage : arme
      render(4,{attention:1,done:1});           // les deux montent, aucun échec
      render(5,{attention:2,done:2,failed:1});  // un échec monte aussi : il gagne
      render(6,{attention:3,done:3,failed:1});  // échec en attente, pas en hausse : doux
      out({all:AUDIO.tones});
    """, "mixed")
    assert seen["all"] == ["attention", "bad", "attention"]


#: Sites audio connus hors Presentation, dans des modules injectés par la page :
#: le retour sonore de Bare Hands et le micro du panneau de travail. Ils ne
#: jouent pas le signal d'arrière-plan. Toute autre apparition est un second
#: émetteur.
AUDIO_ALLOWLIST = frozenset({"control_center_barehands.js", "control_center_work.js"})
AUDIO_SITE = re.compile(r"AudioContext|createOscillator\(")


async def test_single_audio_emitter(tmp_path):
    """Un seul site construit le contexte audio du signal d'arrière-plan : `bgCue`.

    Garde sur la page **servie** (`ControlCenter.index`), modules injectés
    compris : chaque apparition d'`AudioContext` ou de `createOscillator(` est
    soit dans `bgCue`, soit dans un module de la liste blanche. Le module
    d'attention arbitre *si* l'onglet sonne, jamais *comment*.
    """

    from jarvis.runtime.control_center import ControlCenter

    served = (await ControlCenter(runtime_root=tmp_path, project_root=tmp_path).index(None)).text
    runtime = PAGE.parent
    injected: dict[str, tuple[int, int]] = {}
    for path in sorted(runtime.glob("control_center*.js")):
        text = path.read_text(encoding="utf-8")
        at = served.find(text)
        if at >= 0:
            injected[path.name] = (at, at + len(text))
    assert MODULE.name in injected, "le module d'attention est servi"
    assert AUDIO_ALLOWLIST <= set(injected), "la liste blanche ne nomme que des modules servis"

    cue = re.search(r"^function bgCue\(", served, re.M)
    cue_end = _balanced_end(served, cue.start(), statement=False)
    owners: dict[str, int] = {}
    for match in AUDIO_SITE.finditer(served):
        owner = next((name for name, (lo, hi) in injected.items() if lo <= match.start() < hi), None)
        if owner is None:
            assert cue.start() < match.start() < cue_end, f"site audio hors bgCue : {served[match.start() - 80:match.end()]}"
            owner = "bgCue"
        owners[owner] = owners.get(owner, 0) + 1
    assert set(owners) == {"bgCue", *AUDIO_ALLOWLIST}, owners
    constructions = re.findall(r"\bnew\s+(?:window\.)?(?:webkit)?(?:AudioContext|C)\s*\(", served[cue.start():cue_end])
    assert len(constructions) == 1, "bgCue construit son contexte une seule fois"
