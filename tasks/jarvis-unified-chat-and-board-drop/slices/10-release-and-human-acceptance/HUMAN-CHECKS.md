# Contrôles humains — Chat unifié et dépôt sur le Board

Statut de chaque contrôle : **en attente**. Rien ci-dessous n'a été fait à votre place ; les essais machine sont dans
`../09-integration-and-security-gates/evidence/RESULTS.md` et `evidence/RESULTS.md` de cette Slice.
Prévoyez environ 30 minutes. Vous pouvez regrouper tous les contrôles dans une même séance.

## 0. Avant de commencer : redémarrez JARVIS vous-même

Les changements touchent Core, le Control Center et Voice : votre JARVIS doit être relancé sur la branche de la
tâche pour les prendre. Aucun agent ne l'a fait et aucun ne le fera.

1. Placez votre dépôt principal sur la branche de la tâche, `task/jarvis-unified-chat-and-board-drop`, une fois la
   Slice 10 fusionnée (ou attendez la fusion dans `main`).
2. Lancez la commande que vous utilisez d'habitude : `project jarvis restart`.
3. Ouvrez le Control Center (`http://127.0.0.1:17654/`). Vous devez voir l'onglet **CHAT** en bas à droite.

Aucune migration : vos bases ne changent pas de version, rien à sauvegarder au-delà de votre sauvegarde habituelle.
Pour revenir en arrière : replacez votre dépôt sur le commit de `main` d'avant la fusion, `57f28a74`
(`git switch --detach 57f28a74`), et relancez de la même façon ; les pièces jointes déjà déposées restent dans
`artifacts/` comme des Artifacts ordinaires.

## HV-JCHAT-04-01 — « Passer au chat » coupe la voix, pas le travail

1. Activez la voix (F9) et demandez à JARVIS une tâche longue qui lance un sous-agent (par exemple : « compte les
   fichiers .md du dossier docs et dis-moi combien il y en a »).
2. Dès qu'il a accusé réception, ouvrez l'onglet **CHAT**. Attendu : l'historique est lisible, la zone d'écriture est
   grisée avec « Désactivez le vocal pour écrire » et un bouton **Passer au chat**.
3. Cliquez **Passer au chat**. Attendu : « Arrêt du vocal… », puis la zone d'écriture se libère en quelques secondes ;
   la voix est passée en veille.
4. Attendu : le sous-agent continue (il apparaît toujours dans le dock AGT) et son résultat finit par arriver dans le
   Chat sous forme de bulle.

Verdict : ☐ conforme ☐ non conforme — remarque :

## HV-JCHAT-06-01 — Ergonomie du panneau sur votre écran habituel

1. Ouvrez et fermez le panneau par l'onglet **CHAT**, puis par Échap. Attendu : le focus revient à l'onglet.
2. Écrivez un message : Entrée envoie, Maj+Entrée passe à la ligne. Attendu : « Message transmis… » puis
   « Jarvis traite votre message… » avec un compteur, puis la bulle de réponse.
3. Vérifiez qu'aucune notification ne masque l'onglet CHAT, le dock, le bouton du mode d'interaction ni le bas du
   panneau, y compris dans une fenêtre étroite (environ 500 px de large).
4. Ouvrez le panneau des Boards ou l'inspecteur du Studio : attendu, un seul panneau latéral à la fois.
5. Menus, Chat ouvert : ouvrez le menu du mode d'interaction et les menus du dock. Attendu : chacun s'affiche entier
   et reste cliquable, sans passer sous le panneau. Le bouton Boards de la barre du haut est couvert par le panneau
   ouvert (limite connue, comme pour les autres panneaux) : fermez le Chat pour l'atteindre.
6. Cliquez « Voir la chronologie complète ». Attendu : la chronologie détaillée s'ouvre sur la même conversation.

Verdict : ☐ conforme ☐ non conforme — remarque :

## HV-JCHAT-07-01 — Deux pièces jointes de types différents

1. Dans le Chat, cliquez **Joindre** et choisissez un PDF ; puis glissez une image (PNG ou JPEG) sur le panneau.
   Attendu : deux lignes, chacune « Envoi N % », puis « Vérification par Jarvis Core… », puis « Prête ».
2. Écrivez « Que contiennent ces deux fichiers ? » et envoyez. Attendu : la bulle porte « 2 pièces jointes ».
3. Attendu : la réponse de JARVIS décrit le contenu réel des deux fichiers (pas une supposition).
4. Facultatif : joignez un fichier `.zip`. Attendu : « Prête · jointe, mais le Brain ne pourra pas la lire » avant
   l'envoi, et une réponse qui dit ne pas pouvoir le lire.

Verdict : ☐ conforme ☐ non conforme — remarque :

## HV-JCHAT-08-01 — Fichier, image et URL déposés sur un Board

1. Sur le Board affiché, glissez sur la scène (hors du panneau Chat) un fichier, une image, puis un lien depuis la
   barre d'adresse du navigateur. Attendu : un calque « Déposer sur « <Board> » » pendant le survol, puis, pour chacun,
   « Ajouté au Board « … » ».
2. Cliquez « Voir dans l'inspecteur ». Attendu : les trois ressources sont listées (« Fichier déposé », « Lien »).
3. Passez sur un autre Board, puis revenez. Attendu : les trois ressources sont toujours là sur le premier Board et
   absentes du second.
4. Ressource réutilisable après le changement de Board : de retour sur le premier Board, sélectionnez chacune des trois
   ressources dans l'inspecteur. Attendu : ses détails s'affichent (nom, taille et type pour le fichier et l'image ;
   l'URL en texte pour le lien), comme avant le changement. Facultatif : après un redémarrage de JARVIS fait par vous,
   elles sont toujours là.
5. Attendu : aucun message n'est parti vers JARVIS et le lien n'a pas été ouvert ni prévisualisé.

Verdict : ☐ conforme ☐ non conforme — remarque :

## HV-JCHAT-10-01 — Parcours voix, puis Chat, puis voix

1. Parlez à JARVIS à la voix (une question simple). Attendu : réponse dite, et visible dans le Chat.
2. **Passer au chat**, puis écrivez une question. Attendu : réponse **écrite seulement**, jamais dite à voix haute.
3. Réactivez la voix (F9). Attendu : le Chat se verrouille de nouveau ; la conversation et le Board sont les mêmes.
4. Pendant tout le parcours, un sous-agent lancé plus tôt reste vivant.

Verdict : ☐ conforme ☐ non conforme — remarque :

## HV-JCHAT-10-02 — Lisibilité finale, dépôts et documentation

1. Relisez le Chat après les contrôles ci-dessus : bulles, états, messages d'erreur compréhensibles.
2. Confirmez que la différence entre pièce jointe du Chat (envoyée à JARVIS) et dépôt sur le Board (rangé, jamais
   envoyé) est claire à l'usage.
3. Parcourez `docs/chat.md` (contrat) et `docs/OPERATIONS.md` › *Chat et dépôt sur le Board* (réglages,
   diagnostics).

Verdict : ☐ conforme ☐ non conforme — remarque :

## Dernier cas, à trancher par vous : sous-agent lancé à la voix, puis « Passer au chat »

Constat n° 2 de la Slice 09 : après « Passer au chat » et **avant** tout message écrit, la fin d'un sous-agent lancé
à la voix est **dite** à voix haute. Le code ne retient la parole que pour un tour écrit ; retenir toute parole quand
la voix est en veille couperait aussi les annonces normales de veille.

1. À la voix, lancez une tâche longue avec sous-agent.
2. Cliquez tout de suite **Passer au chat**, sans rien écrire.
3. Notez si la fin du sous-agent est dite à voix haute, et si elle apparaît en bulle dans le Chat.

Votre choix : ☐ la dire reste correct (comportement actuel) ☐ elle doit rester silencieuse (correctif à prévoir)
— remarque :

## Votre verdict global

☐ Accepté ☐ Accepté avec réserves ☐ Refusé

Réserves ou commentaires :

Date :
