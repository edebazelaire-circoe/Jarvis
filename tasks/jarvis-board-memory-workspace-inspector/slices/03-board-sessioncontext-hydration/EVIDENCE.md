# Slice 03 — preuves (hydratation Board + Context)

## Run QA en direct

Montage isolé : Core sur le port 18973, Control Center sur 18974, racines
`data` et `runtime` dans un dossier de scratch (Boards de test « Projet Atlas »
et « Projet Borée », aucune donnée réelle). Les tours passent par Core
`POST /v1/conversations/{id}/brain-turns` avec `addressing=addressed` : la
route CC `/api/agent/ask` contourne l'hydratation Core et ne prouve donc rien
ici.

| Tour | Board | Résultat | Coût |
|---|---|---|---|
| a | Atlas | Client, budget et ZÉPHYR-731 répondus depuis le condensé du brief, sans outil. Brief de 2 081 o. | 0,112 $ |
| b | Atlas | Consigne d'une décision : déléguée à un sous-agent de fond, qui a ajouté à `decisions.md` et `summary.md` dans la mémoire d'Atlas. Rien sous `sessions/`. | 0,145 $ (+ tour de réveil 0,259 $) |
| c | Borée | Le brief dit la mémoire vide, sans aucun contenu d'Atlas ; pas d'outil. | 0,075 $ |
| d | Atlas | Le brief montre le condensé mis à jour, ligne OVHcloud comprise. | 0,093 $ |

- L'id du Context reste le même à chaque bascule de Board.
- Le CLI a reçu `--add-dir …/boards`. Aucun avertissement mémoire.
- Coût total ≈ 0,68 $.

Les briefs effectivement reçus par le CLI sont dans `evidence/` :
[`qa_s03_brief_a.txt`](evidence/qa_s03_brief_a.txt),
[`qa_s03_brief_c.txt`](evidence/qa_s03_brief_c.txt),
[`qa_s03_brief_d.txt`](evidence/qa_s03_brief_d.txt). Ils précèdent la reprise
S3 : la règle du Context y dit encore « C'est ton seul espace de travail
implicite ».

## Coût de l'hydratation

| Mémoire | Durée |
|---|---|
| minuscule | 1,4 ms |
| `summary.md` de 1 Mio | 2,5 ms |
| 1 Mio + 2 000 fichiers | 9,9 ms |

## Mutations

7 sur 8 détectées. M7 (budget de lecture du condensé doublé) survit sans
conséquence : `bounded()` recoupe le condensé à sa borne.

## Piste d'optimisation

L'ajout de deux lignes (tour b) est passé par un sous-agent puis un tour de
réveil, environ 0,26 $ de plus qu'une écriture directe.

## Reprise S3

- `neutralize_lines` coupe désormais sur toutes les fins de ligne de
  `str.splitlines()` (`\r`, `\r\n`, `\v`, `\f`, U+001C–U+001E, U+0085, U+2028,
  U+2029) : un condensé de Context ou de Board ne peut plus ouvrir de fausse
  section ni fermer son bloc avec ces séparateurs.
- La règle du Context ne contredit plus MÉMOIRE DE BOARD : le dossier du
  Context est l'espace implicite du travail de la conversation, le savoir
  durable du Board actif va dans sa mémoire de Board.
