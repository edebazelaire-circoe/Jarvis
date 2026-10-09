# Guide de style des prefabs soignés (langage CX)

Complète [prefabs.md](prefabs.md) (contrat) : ce guide dit **comment ça doit
avoir l'air**. Le langage vit dans `jarvis/prefabs/runtime/shell.css` (bloc
« CX »), les modèles dans `jarvis/prefabs/circoe/`. Rendu de référence :
`docs/results/prefab-cx/`.

## Principe

Une page produit sobre, pas un tableau de bord de boîtes. De l'espace, une
typographie à fort contraste d'échelle et de graisse, **une** surface de verre
par idée (jamais des boîtes bordées imbriquées), la lumière portée par l'accent.
Sombre seulement : c'est l'interface de JARVIS.

## Choisir un modèle

| Information à montrer | Modèle |
| --- | --- |
| Une liste d'actions classées (Urgent, Aujourd'hui…), avec échéances et gestes Fait / Rappeler / Reporter / Ouvrir | `circoe.dashboard` |
| Un message, un bilan, une annonce portés par UN chiffre clé et quelques points | `circoe.hero` |
| Des rendez-vous, un planning, des échéances dans le temps | `circoe.timeline` |
| Plusieurs chiffres, des séries, des tendances, des objectifs | `circoe.metrics` |
| Un tableau brut / un long texte / une case à cocher simple | `jarvis.table` / `jarvis.document` / `jarvis.checklist` |
| Rien ne convient | variante par `prefab_get include_source` + `prefab_validate` + `prefab_save` (nouvel id `circoe.*`, jamais `jarvis.*`) |

Règle du cerveau : pour afficher de l'information, un modèle `circoe.*` d'abord
(`BRAIN_PREFAB_PROMPT`). Aucun HTML écrit à la main pour un besoin couvert.

## Structure d'une page

```html
<div class="cx monmodele">
  <div class="cx-ambient" aria-hidden="true"></div>   <!-- lueurs + grain : donne au verre quelque chose à flouter -->
  <main class="cx-page">…</main>                       <!-- typographie fluide : tout en em -->
</div>
```

`.cx` est un conteneur (`container-type: inline-size`) : la taille de base de
`.cx-page` va de 11,5 px (cadre étroit) à 17 px (cadre large), multipliée par
`--jv-scale`. Tout se dimensionne en `em` ; une mise en page se rééquilibre
avec `@container (max-width: 30em)`. Tester à 520 px et à 980 px.

## Échelle typographique

Pile : SF Pro / Segoe UI Variable / Inter / système (aucune police distante).
Chiffres tabulaires pour tout nombre qui change. Interlignage serré en grand,
aéré en petit ; crénage négatif en grand (`letter-spacing`).

| Classe | Taille | Graisse | Usage |
| --- | --- | --- | --- |
| `.cx-display` | 5,6 em | 200 | LE chiffre clé, dégradé blanc → accent |
| `.cx-big` | 3 em | 250 | chiffre de carte |
| `.cx-h1` | 2,35 em | 650 | grand titre (`<em>` = mot en dégradé) |
| `.cx-h2` | 1,32 em | 620 | titre de section |
| `.cx-h3` | 1,04 em | 560 | titre d'élément |
| `.cx-lead` | 1,2 em | 380 | phrase d'explication |
| `.cx-body` | 1 em | 400 | texte |
| `.cx-cap` | 0,8 em | 400 | légende, valeur secondaire |
| `.cx-eyebrow` | 0,74 em, capitales, 0,16 em d'espacement | 600 | surtitre |

Contraste d'échelle d'abord : un seul très grand élément par vue, le reste
nettement plus petit.

## Palette

Fond `#04080d` → `#070d14` + lueurs d'accent (30 %, 20 %, 16 %) + grain 7 %.
Encre : `--cx-ink` `#f6f9fc` (titres), `--cx-ink-2` 76 % (texte), `--cx-ink-3`
60 % (légendes) : tous ≥ 4,5:1 sur le verre. Accent : `--cx-acc` (prop `accent`,
cyan `#6ee7ff` par défaut). Tons de sens : `--cx-urgent` `#ff8c7a`,
`--cx-warm` `#ffcf72`, `--cx-ok` `#63e8a9`, `--cx-violet` `#aea4ff`. Une teinte
sert une signification (urgent, avertissement, réussite), pas la décoration.
Une pastille ou un bouton colorés éclaircissent leur texte (`color-mix(… #fff)`)
pour rester AA.

## Surfaces, espacements, formes

- Verre : `.cx-glass` (dégradé de lumière, filet intérieur de 1 px, flou 28 px,
  trois ombres en couches). Au plus quelques surfaces par vue ; les lignes
  d'une liste ne sont **pas** des boîtes : un filet fin (`.cx-rule`) ou rien.
- Coins continus : `corner-shape: squircle` quand le navigateur le connaît,
  sinon arrondi simple (rayon 1,35 em).
- Espacement en `em` : 2 em entre blocs d'une page, 0,5–1 em dans un bloc,
  marges de page 2,1–2,6 em. Les titres de section ont de l'air autour.
- Lueur douce : ombre colorée à 55–70 %, jamais un contour dur.

## Animations

- Apparition : `.cx-rise` + `style="--i:n"` (retard échelonné de 70 ms) ;
  0,8 s, courbe `--cx-ease`.
- Survol : léger soulèvement (`translateY(-2px)`), projecteur de lumière qui suit
  le pointeur sur le verre (`--mx`, `--my` posés par l'assistant commun).
- Repli : ligne de grille `0fr → 1fr` (hauteur naturelle animée), ouverture
  0,55 s ; contenu replié `inert`.
- Compteurs : `cxCount(node, valeur)` (rAF, 0,9 s, sortie en quartique).
- Tracés (courbes, anneaux) : `stroke-dashoffset` ; barres : `scaleX`.
- `prefers-reduced-motion: reduce` coupe toute transition et animation (règle
  finale de `shell.css`) et `CX_REDUCED` met les compteurs d'emblée à leur valeur.
  Pas de mouvement qui porte seul une information.

## Accessibilité

- Contraste ≥ 4,5:1 pour le texte, ≥ 3:1 pour les contrôles et les icônes.
- Focus clavier : anneau net de 2 px + halo (`.cx :focus-visible`), jamais
  supprimé. Tout geste est un `<button>` atteignable au clavier.
- Sémantique : `main`, `h1/h2`, `ul/li`, `aria-expanded` + `aria-controls` pour
  un repli, `aria-pressed` pour une bascule, libellés `aria-label` contenant le
  nom de l'élément (« Fait : Répondre à Marion »), `role="status"` pour l'annonce
  d'une action, `aria-hidden` sur ce qui est décoratif, résumé textuel pour tout
  graphe (`role="img"` + `aria-label`).
- Information jamais portée par la couleur seule (icône, texte, position).
- `forced-colors` : filets et bordures de repli prévus dans `shell.css`.

## Écrire un modèle

1. Dossier `jarvis/prefabs/circoe/<id>/` : `manifest.json`, `template.html`,
   `style.css`, `behavior.body.js`. Bornes : template ≤ 32 Kio, style ≤ 32 Kio,
   behavior ≤ 64 Kio, données ≤ 16 Kio.
2. `python scripts/circoe_assemble.py` (colle le bloc commun `_common/cx.js`
   devant le corps), `python scripts/circoe_check.py <dossier>` (validation du
   domaine, comme `prefab_validate`).
3. Texte uniquement par `textContent`, SVG par `createElementNS` ; aucun réseau,
   aucune police ou image distante ; `url(` seulement `url(data:…)` (un dégradé
   SVG se référence par attribut `stroke="url(#id)"`).
4. Garder les nœuds d'une mise à jour à l'autre (les transitions et le focus en
   dépendent) ; une écriture d'état est un événement, Core écrit, la mise à jour
   revient.
5. Rendu réel : `python scripts/prefab_preview.py scenario.json sortie.png`
   (Chrome headless, vrai `buildSrcdoc`, iframe isolé, CSP), regarder la capture.
6. Publier par le chemin officiel : `prefab_validate`, puis `prefab_save`
   (nouvel id `circoe.*` ou nouvelle version), jamais `jarvis.*`.

## Limites connues

Un cadre isolé ne voit pas le bureau : le verre floute le fond ambiant du cadre,
pas les étoiles de la scène. `corner-shape` demande un Chrome récent. 24 cadres
vivants au plus, 10 événements par seconde, pas de réseau. La capture de scène
ne montre pas le contenu d'un prefab (voir `prefab_preview.py`).
