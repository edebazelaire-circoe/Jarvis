# Retour utilisateur : la voix « perd la connexion du brain », pas de transcript, pas de lien vers le brain

Dit (voix, 14/10 15:35) : « t'as pas du tout les infos du brain... des fois tu perds la connexion du brain... je ne vois pas le transcript, je vois pas de lien vers le brain ».

## Constaté (runtime/trace.jsonl, Core lancé à 14:33 heure locale, lecture seule)
- Liaison voix-brain intacte depuis ce démarrage : 22 tours brain sur 22 « completed », agent Claude en marche (pid 712), aucun « Claude CLI not found » aujourd'hui.
- « Claude CLI not found » : dernière occurrence le 12/10 09:30 locale. Le Control Center de ce jour-là a été lancé sans `C:\Users\Clarice\.local\bin` dans son PATH (claude.exe y est) ; il n'a pas retrouvé le CLI, le cerveau du Board n'a pas démarré. Un démarrage ultérieur l'a retrouvé. Cause du PATH de ce lancement-là : non établie (les anciens lancements ne sont pas journalisés).
- Une seule coupure brève aujourd'hui : 14:45:03, le Control Center n'a pas pu lire l'état de Core (timeout) et l'a retrouvé en 0,15 s.
- Voix : la session GPT-Live a été arrêtée depuis le Control Center puis relancée à la touche F9 sept fois aujourd'hui (la dernière à 15:34, 56 s avant le signalement). Une session neuve repart avec les 8 derniers tours seulement, pas les tâches, la scène ni la mémoire du Board : ils n'arrivent qu'à chaque tour confié au brain.
- 15:33, « archive-le » : le brain a bien archivé l'objet (scene_archive appliqué) mais n'a rien dit (règle « pas de confirmation orale d'une tâche simple »). L'utilisateur a pu l'entendre comme une perte du brain. Hypothèse, non prouvée.
- Transcript : Core le sert complet et à jour (conversation c4dae6fc, tours Utilisateur/Brain/Jarvis jusqu'à 15:36). Le panneau, lui, restait figé : correctif task/transcription-tab-live-refresh (ca4aa92a) fusionné dans main à 15:36 ; la page servie par le Control Center le contient déjà.
- Lien vers le brain : aucun indicateur permanent n'existe dans le Control Center (l'état du brain n'apparaît que dans les réglages de la scène). Ce n'est pas une régression, c'est un manque.

## À faire (utilisateur)
- Recharger la page du Control Center (F5) : le panneau Transcription se relit alors toutes les 4 s.
- Si « Claude CLI not found » revient : relancer JARVIS depuis un terminal dont le PATH contient `C:\Users\Clarice\.local\bin` (vérifier avec `where claude`).

## Doute
Cause de la sensation « la voix n'a pas les infos du brain » non établie par la trace : aucun tour brain perdu. Pistes non traitées faute de preuve : contexte initial d'une session neuve trop pauvre, absence d'indicateur de liaison brain. Aucun code modifié.
