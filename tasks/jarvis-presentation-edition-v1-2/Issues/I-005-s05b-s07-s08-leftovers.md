# I-005 — Restes des Slices 05b, 07 et 08 (2026-10-27)

## 05b — mot de réveil des builds internes
- Acceptés : m1 (`channel_problems` ne regarde que les dossiers connus ; injection artificielle avec manifestes réécrits non détectée), m3 (`release_info.py` nomme un build interne `-internal-` mais ne refuse pas de le publier : aucune étape de publication n'existe, la CI construit le canal production), m4 (`onnxruntime_directml-*.dist-info` seul non détecté).
- Question juridique pour le Human : clause NonCommercial des modèles openWakeWord pour des tests internes d'une société (HD-V12-01, HV-PACKAGE-07).
- Non vérifié : installeur et `package_smoke` du build interne, reproductibilité du build interne, réveil vocal réel (HV-V12-VOICE-02).

## 07 — Signaler un problème
- Acceptés (hors portée raisonnable d'un masquage par règles) : liste YAML sous un nom sensible, URL encodée (`%3D`), base64 d'un JSON de secrets, secret sans forme reconnaissable sous un nom ordinaire absent du `.env` et du coffre.
- À faire (petit) : exclure par leur nom les fichiers de clé sans extension (`id_rsa`, `id_ed25519`, `id_ecdsa`, `id_dsa`) ; leur contenu est déjà masqué.
- 1 cellule de la base réelle masquée à tort par le masquage MCP commun (identifiants d'outil pointés pris pour un JWT).
- Non vérifié : MAPI réel (HV-SUPPORT-01, « nouvel Outlook » inconnu), DPAPI réel du produit installé.

## 08 — macOS
- Écart déclaré au critère d'acceptation : aucun paquet macOS construit. Prérequis : job CI `macos` exécuté (push du Human) et sonde de boucle locale lue ; décision sur l'adresse `127.77.0.1`/`127.77.0.2` (macOS ne répond qu'à `127.0.0.1` sans alias) ; scellement par le Trousseau.
- m5 (suite de découverte bruyante sous POSIX), m6 (capture d'écran : ffmpeg sans session propre sur Mac) consignés.
- Groupe de processus POSIX plus faible qu'un Job Windows (documenté).
