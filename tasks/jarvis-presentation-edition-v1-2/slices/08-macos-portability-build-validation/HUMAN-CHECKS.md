# Checks Human — Slice 08 (portabilité macOS)

**Une CI macOS verte ne veut pas dire « macOS supporté ».** macOS reste non supporté tant que `HV-V12-MAC-01` n'est
pas passé (décision HD-V12-03). Contexte et inventaire : `docs/macos-portability.md`.

## Avant de commencer (prérequis, aucun n'est fait à ce jour)

1. Pousser la branche pour exécuter le job CI `macos` ; lire ses rapports (`macos-portability-arm64`, `-x64`) :
   porte dure verte, et ce que disent les étapes de découverte (sonde `127.77.0.1`, suite voisine, smoke Core).
2. Décider de l'adresse de Core et du bac à sable Remotion sur Mac (`docs/macos-portability.md` › *Boucle locale*).
3. Écrire et éprouver le scellement des secrets par le Trousseau (aujourd'hui : refus explicite, aucune clé enregistrable).
4. Écrire le packager macOS (`packaging/macos/` n'est qu'un plan), générer les verrous `requirements-macos-*.lock`.
5. Identifiants Apple Developer (Developer ID, notarisation) ; paquet signé, notarisé, agrafé.

## HV-V12-MAC-01 — acceptation sur un vrai Mac

Sur le Mac d'un collègue, avec un compte utilisateur sans droits d'administrateur si possible. Noter le modèle, la
puce (Apple Silicon ou Intel), la version de macOS. Pour chaque point : OK / KO + capture ou journal.

| # | Vérification | Attendu |
|---|---|---|
| 1 | Télécharger le `.dmg`, glisser `Jarvis.app` dans Applications, premier lancement | Gatekeeper ouvre sans avertissement (signature + notarisation) ; aucune demande de Python, Node ni Homebrew |
| 2 | Maison du produit | `~/Library/Application Support/CIRCOE/Jarvis` créé (`data`, `runtime`, `config`) ; rien écrit dans le bundle ni dans Documents |
| 3 | Permission micro | invite macOS avec le texte de Jarvis ; après « Autoriser », la voix entend ; après « Refuser », Jarvis le dit clairement |
| 4 | Raccourci F9 (Accessibilité / Surveillance de l'entrée) | invite ou consigne claire ; F9 réveille Jarvis une fois autorisé |
| 5 | Voix et réveil | Sleep → Active par F9 (et « Hey Jarvis » sur un build interne) ; orbe conforme ; pas de boucle d'écho sur les haut-parleurs du Mac |
| 6 | Clé de fournisseur et connexion Claude | la clé s'enregistre scellée (Trousseau), jamais en clair ; la CLI Claude est trouvée et la connexion s'ouvre dans une fenêtre visible |
| 7 | Chat | une question écrite, puis parlée, reçoit une réponse |
| 8 | Recherche | une recherche web aboutit avec ses sources |
| 9 | Board | reprise d'un projet après relance |
| 10 | Presentation | création, aperçu, rendu (Chrome ou Edge du Mac), export dans `~/Documents/Jarvis` |
| 11 | Arrêt | « Quitter » arrête Core, Control Center, voix et leurs enfants (Moniteur d'activité : aucun `python3`, `node` ni Chrome de Jarvis restant) |
| 12 | Deuxième lancement | un second clic rouvre la page au lieu d'un second Jarvis (verrou d'instance) |
| 13 | Mise à jour / réparation | remplacer l'app par une version plus récente garde profil, réglages et présentations ; une app altérée est détectée |
| 14 | Paquet de diagnostic | le rapport de bug se crée sans chemin personnel ni secret |

Verdict : macOS peut être annoncé supporté seulement si 1 à 14 sont OK sur au moins un Mac Apple Silicon (et sur un Mac
Intel si l'x64 est distribué).
