# Retour utilisateur : transcriptions absentes de l'onglet

Dit (voix) : "Je ne vois pas les retranscriptions de ce que je suis en train de te raconter dans l'onglet des retranscriptions." Puis : "Là c'est revenu, mais tout à l'heure ça marchait pas."

Constat : aucune capture audio n'est active (derniere : 02/10, 20 segments), donc l'onglet ne pouvait rien montrer de la capture. Le panneau "Transcription" de la chronologie du Control Center (conversation vocale) lisait un instantane une seule fois par conversation et ne le relisait jamais : il montrait l'etat du premier affichage, "revenait" a la reouverture/changement de mode.
Correctif : branche task/transcription-tab-live-refresh (worktree C:\Projects\jarvis\btr), commit ca4aa92a, non fusionne. Relecture a chaque ouverture et toutes les 4 s, sans effacer le texte. Necessite un rechargement du Control Center (a faire par l'utilisateur apres fusion).
Doute : cause non prouvee sur la panne exacte du moment (pas de trace de ce moment relue), seulement le defaut de code.
