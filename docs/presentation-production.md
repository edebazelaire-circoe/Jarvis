# Production d'une présentation ou d'une vidéo : le brain orchestre, un auteur construit en code natif

Contrat de `jarvis/runtime/presentation_playbooks.py` et de `claude_local.PRESENTATION_PRODUCTION_RULE`. Les tests sont dans
`tests/unit/test_presentation_playbooks.py`. Le chemin de création et ses portes : [presentation-studio.md](presentation-studio.md)
> *Native Remotion authoring*. Les mesures qui ont fixé ce défaut (Slice 13 de native-studio-playback-fix) :
`tasks/jarvis-remotion-native-studio-playback-fix/slices/13-claude-native-generation-parity/BENCHMARK.md`.

## Pourquoi

Un sous-agent ne voit ni le prompt système du brain ni le guide du planificateur (`PLANNER_PROMPT`). Il n'a que la
consigne que le brain a rédigée, et le prompt du brain demande des consignes de « quelques lignes de faits ». Une
vidéo demandée ainsi sort sans contexte et sans méthode : la méthode est apposée d'office (voir plus bas).

Avant la Slice 13, le chemin enchaînait toujours dossier, auteur, relecture, puis un second auteur : sur le même brief,
mesuré, quatre sous-agents, 76 appels d'outils, 15 refus (dont 13 brouillons refusés), environ 21 minutes et 3,9 USD, pour un deck que
personne n'avait regardé ; Claude seul dans un projet Remotion : un agent, 12 à 19 appels, 2,5 à 7,5 minutes, 0,34 à 0,47 USD,
et il regardait ses propres images.

## Le chemin

Un sous-agent ne lance pas de sous-agent : le brain enchaîne les rôles, tous en arrière-plan.

| Étape | Marqueur de la description de l'Agent | Quand | Rôle |
| --- | --- | --- | --- |
| défaut | `[code] [presentation-author]` | toujours | lit les sources, écrit le storyboard, code les scènes en Remotion natif, les rend en images (`presentation_source preview`), les regarde, corrige (`presentation_source write`) |
| avant | `[general] [research]` | la matière manque | recherches, en parallèle |
| avant | `[general] [presentation-brief]` | la matière est éparpillée dans le Board | écrit `presentation/production_brief.md` dans la mémoire du Board ; rend ses questions ouvertes (le brain les relaie, une à la fois) |
| après | `[general] [presentation-review]` | l'utilisateur demande une relecture, ou livrable important | critique images à l'appui, sans rien modifier ; écrit `presentation/review.md` ; s'il y a des écarts, le brain relance l'auteur |

## Comment la méthode arrive à l'agent

Le hook de routage (`routing_hook.charter_input`) appose le playbook du rôle sur la consigne de l'appel `Agent`, comme
la charte du chantier : à toute profondeur, quoi que le brain ait rédigé, et jamais en double (`PLAYBOOK_MARK`). Le
brain n'a donc qu'à écrire le marqueur et une consigne courte (les mots exacts de l'utilisateur, les chemins nommés, le
chemin du dossier s'il existe). Preuve réelle (Slice 13) : la consigne du brain recopie les mots de l'utilisateur et le
chemin de la source ; le premier geste de l'auteur est `draft_guide` `kind: native`, comme le dit le playbook.

Le playbook de l'auteur ne contient plus `PLANNER_PROMPT` (9 000 caractères de règles du modèle guidé) : il porte la
boucle native (`NATIVE_LOOP`) et la barre de qualité, en moins de 7 000 caractères (testé). Le mode guidé (contrôles
réglables à la voix, thème de variante, partition parlée par Jarvis) reste disponible quand la consigne le demande : la
porte de qualité complète s'applique alors, et `draft_guide` sans `kind` en donne la forme.

**Une seule vidéo par construction (master-project Slice 07, [remotion-master-project.md](remotion-master-project.md) § 12).** « Natif »
veut dire : du code Remotion normal par scène, stocké scène par scène (une version immuable par écriture), que JARVIS assemble à la demande
en UN projet Remotion (le projet maître, dérivé, jamais canonique) pour Remotion Studio et l'export de la vidéo entière. Pour que
l'assemblage soit possible, le playbook et `draft_guide` `kind: native` portent `MASTER_HINT` : même `width`, `height`, `fps` pour toutes
les scènes (deck neuf 1920x1080 à 30, que Core pose aussi pour ce qu'un bundle natif omet ; scène ajoutée ou recodée : ceux de la
variante), fichiers `public/` nommés d'après leur scène (chemin et `staticFile()`), jamais `getInputProps`. Ce sont des faits techniques
de compatibilité, pas une règle de contenu ou de style : le natif reste permissif. Le résultat de `presentation_draft_assemble` et de
`presentation_source` porte le bloc `master` (prête, ou la raison dite à l'utilisateur) ; l'auteur corrige ce qu'il nomme.

## Limites connues

- La revue visuelle est celle de l'auteur (images fixes, pas de vidéo jouée) ; la qualité finale reste un jugement humain
  (HV-RFX-13-01, decks aveugles côte à côte).
- La règle du brain est lue au premier tour d'une conversation ; une conversation déjà ouverte la voit après un
  redémarrage de JARVIS. Le hook, lui, s'applique dès l'appel suivant.
- Un aperçu coûte 30 à 40 s par scène sur un poste chargé (empaquetage et navigateur à chaque appel).
