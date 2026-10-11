# Slice 02 : inventaire de l'écran, à valider par vous (HV-RFX-02-01)

Cette page montre, sans rien à cliquer, ce que deviendra l'écran des présentations. Elle résume le contrat écrit dans `docs/presentation-studio.md`, section *Presentation experience contract (Level 2, 2026-10)*. Si un point ne vous convient pas, on corrige d'abord le contrat, puis le code.

## 1. Deux noms, deux endroits

| Vous voyez | Ce que c'est | On ne dira plus |
| --- | --- | --- |
| **Remotion Studio** | l'éditeur de Remotion. Il s'ouvre dans un onglet à part, sur une seule scène, après une confirmation (« cette scène tourne hors du bac à sable ») | « Studio » tout court |
| **Variantes** | l'écran de Jarvis où l'on voit l'historique des versions, où l'on regarde la vidéo (c'est le seul endroit où elle se lit) et où l'on crée, active, compare, renomme ou archive une version | « Studio », « explorateur de variantes » |

Le menu de la colonne des présentations (à gauche) change seulement de mots. Sa mise en page attend votre croquis.

| Entrée | Ce qu'elle fait |
| --- | --- |
| « Ouvrir les variantes » | ouvre l'écran Variantes sur la version active |
| « Remotion Studio… » | ouvre l'écran Variantes, puis Remotion Studio sur la scène choisie |
| « Éditer » | ouvre l'écran Variantes et le panneau de réglages |
| « Présenter » | lance une présentation, dans l'écran Variantes |
| « Acquitter le problème » | efface la pastille orange (inchangé) |
| « Masquer / Afficher », « Renommer… », « Supprimer… » | inchangés |

## 2. L'écran Variantes (dans la fenêtre)

```
+-- Variantes -- <titre> · 3 variantes ------------------- [Fenêtré] [Plein écran] [Fermer] --+
| ÉVOLUTION            1/64 |  +------------------------------------------------------------+ |
| #1 Diaporama ...   ACTIF  |  |                                                            | |
|   `- #2 Variante ...      |  |                    LA VIDÉO                                | |
|   `- #3 Variante ...      |  |       (rien par-dessus : pas de barre dans l'image)        | |
|                           |  +------------------------------------------------------------+ |
|                           |  [|<] [ > Lire ] [>|]  ===o===|====|====|====|===  0:12 / 1:30  [Son] [...]  |
|                           |  Scène 6 sur 9 · Mode Présentation ...   [Remotion Studio] [Présenter v]    |
|                           |  [01][02][03][04][05][*06*][07][08][09]   (un clic = début de cette scène)  |
| > Archivées (0)           |  #1 Titre · Créée hier par Jarvis · 9 scènes                                |
|                           |  (Variante active) (Partition liée) (couleurs)   note                       |
|                           |  [Activer] [Brancher d'ici…] [Renommer…] [Archiver…]   [Comparer]          |
+-----------------------------------------------------------------------------------------------+
  [...]          = Lire seulement cette scène · Revenir au début · Raccourcis clavier
  [Présenter v]  = Vous présentez · Jarvis présente · Répétition
  À la fin       : la dernière image reste affichée, et [ > Lire ] devient [ Rejouer ].
```

Les traits `|` de la barre `===o===|====|` marquent le début de chaque scène. On peut faire glisser le rond pour aller n'importe où dans la vidéo : l'image, le numéro de scène et l'heure suivent ensemble.

Pendant une présentation (dans la fenêtre), une ligne d'information apparaît sous la vidéo, à la place du titre de la scène :

```
  Vous présentez · En cours   Scène 3/9 · élément 5/16   Ensuite : « ... »   Suivi vocal indisponible (...)
  Élément 0:10 (prévu 0:15, temps de la partition)              [Sortir de la séquence (S)] [Arrêter]
```

En plein écran, on ne voit que la vidéo. Les boutons de lecture apparaissent quand on bouge la souris et disparaissent ensuite. L'historique, les informations et les boutons de version restent hors du plein écran. Le plein écran ne s'ouvre que par le bouton « Plein écran » (ou la touche `F`), jamais tout seul.

## 3. Chaque bouton une seule fois

| Bouton | Touche | Ce qu'il fait |
| --- | --- | --- |
| Lire / Pause / Rejouer | `Espace` | lit toute la présentation d'un trait, chaque scène pendant sa vraie durée, puis s'arrête sur la dernière image |
| Scène précédente / suivante | `←` `→` (ou les touches d'une télécommande) | va au tout début de la scène |
| La barre de position | flèches quand elle est sélectionnée | va à n'importe quel moment |
| Le temps `0:12 / 1:30` | | le temps de toute la présentation, et rien d'autre |
| Son | `M` | le son est coupé à l'ouverture |
| Plein écran (en haut) | `F` | le seul plein écran ; il faut votre clic (la voix ne fait que le préparer) |
| Fermer | `Échap` | ferme d'abord un menu ou une fenêtre ouverte, puis le plein écran, puis l'écran |
| Présenter | | lance une présentation dans cet écran, jamais dans une fenêtre flottante |
| Remotion Studio | | ouvre la scène affichée dans l'éditeur Remotion |
| ... | `?` | Lire seulement cette scène · Revenir au début · Raccourcis |
| les vignettes de scènes | flèches | un clic = début de la scène |
| historique, Activer, Brancher, Renommer, Archiver, Restaurer, Comparer | `A` `N` `F2` `Suppr` `R` `Maj+C`, `[` `]` | inchangés |

**Ce qui disparaît :**
- la fenêtre flottante « STUDIO_STAGE » et le bandeau du bas (capture 1) ;
- la petite barre dans l'image (« Lecture », sa réglette, `x s / 30 s`) ;
- les flèches ‹ › séparées au-dessus des vignettes ;
- les boutons « Jouer cette slide » et « Tout jouer » ;
- la rangée de pastilles de versions (l'historique fait la même chose) ;
- la petite fenêtre que la colonne de gauche ouvrait.

**Ce qui est interdit :**
- « 8 s par slide », ou tout réglage de temps par diapositive pour une vidéo ;
- une deuxième rangée de boutons de lecture ;
- la lecture en boucle ;
- un deuxième bouton de plein écran ;
- un bouton qui ferme l'écran pour lire.

## 4. Choix faits pour vous (vous pouvez les changer)

1. **Le plein écran montre seulement la vidéo**, pas tout l'écran Variantes (aujourd'hui, tout l'écran passe en plein écran).
2. **Pas de plein écran automatique quand une présentation commence** : vous cliquez sur « Plein écran » quand vous le voulez.
3. **« Jouer cette slide » ne reste que dans le menu « ... »**, sous le nom « Lire seulement cette scène ».
4. **`Échap` ne met plus en pause** une présentation ; c'est `Espace`. `Échap` sort du plein écran, puis ferme.
5. **La rangée de pastilles de versions disparaît** ; on choisit une version dans l'historique.
6. **Écran externe** : déplacer la fenêtre sur le projecteur, puis « Plein écran ». Pas d'écran séparé avec vos notes sur l'ordinateur, dans cette tâche.
7. **Une nouvelle scène commence toujours à son début**, même si la partition prévoit d'y montrer tout de suite un élément plus loin.
8. **La rangée du bas de la capture 2** (« 8 s par slide », boucle, `2 s / 8 s`) n'existe pas dans le code partagé. Elle vient d'un travail resté sur une autre machine. Conseil : l'abandonner.
9. **Les apartés** (une scène montrée en passant pendant une présentation) s'affichent **dans** l'écran Variantes. Quand un agent travaille, la colonne de gauche montre seulement une pastille ; rien ne s'ouvre tout seul.
