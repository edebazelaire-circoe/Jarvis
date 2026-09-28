# Validation humaine — calibration adaptative et Tester (HV-BH-ADAPT-02 … 10)

Liste unique, **dans l'ordre**, pour une séance réelle : webcam + voix. Elle
regroupe les contrôles humains des Slices 02 à 10. Elle ne remplace aucune QA
machine (toutes passées, voir `LOG.md`) : elle vérifie ce qu'aucun test
synthétique ne peut dire — la main réelle, la caméra réelle, la voix réelle, le
ressenti.

**Règle d'enregistrement.** Pour chaque point, noter **séparément** :

- **Mesuré** — ce que l'écran, le rapport, `runtime/trace.jsonl` ou la console
  de la page (`[barehands] …`) affichent : nombres, codes, états. Recopier tel
  quel.
- **Ressenti** — ce que vous avez éprouvé (« le clic part trop tôt », « l'anneau
  se voit mal »), en vos mots.
- **Verdict** — OK / KO / À revoir, et la cause précise d'un KO (capture d'écran
  ou ligne de journal).

Un ressenti positif ne vaut pas un mesuré négatif, et inversement : les deux
colonnes restent distinctes.

Durée estimée : 60 à 90 minutes.

---

## 0. Préconditions (une fois)

1. Branche `task/jarvis-bare-hands-adaptive-calibration-benchmark` à jour, Core
   et Control Center lancés normalement (ports habituels), page du Control
   Center ouverte dans Chrome, **au premier plan**, fenêtre ≥ **1440 × 900**
   (noter la taille réelle).
2. Webcam réelle branchée, éclairage de face, fond non encombré. Noter le
   modèle de caméra et sa cadence (30 ou 60 images/s si connue).
3. Voix : architecture `continuous_brain`, micro et haut-parleurs du portable,
   en français. Vérifier qu'une phrase simple (« quelle heure est-il ? ») reçoit
   une réponse.
4. Bare Hands **allumé** (bouton à icône de main en haut à gauche → Veille ou
   Actif) **avant** le démarrage du cerveau, pour que les outils
   `jarvis-barehands` soient montés (sinon : redémarrer le cerveau).
5. Onglet Expérimental → section Calibration : **noter l'état du profil
   enregistré avant toute chose** (ce qui est listé sous « Calibré », « mesuré
   aussi, sans effet sur le moteur », réglages acceptés). Profil connu à ce
   jour : seuil secondaire de la main droite **0,468** (usine 0,28).
6. Ouvrir la console de la page (F12) filtrée sur `[barehands]`, et garder
   `runtime/trace.jsonl` sous la main.
7. **Fermer les panneaux latéraux** de la page (Agents, Trace, Erreurs…) :
   la calibration et le test couvrent la page, mais un panneau resté ouvert
   brouille les captures et la lecture de ce qui est derrière.

---

## 1. Migration et profil existant (HV-BH-ADAPT-10, HV-BH-ADAPT-04)

1. Recharger la page. **Observer** : le profil d'avant est intact (mêmes
   valeurs qu'en 0.5), aucune notice « Profil illisible ».
2. Sous « Calibré », seules des clés qui changent le moteur (seuils, tolérance
   clic/glissement) ; tremblement, portée, qualité apparaissent à part, entre
   parenthèses, « sans effet sur le moteur ».
3. **Seuils par main actifs** : faire 10 clics droits (pouce + majeur) main
   droite, puis 10 main gauche, sur un bouton quelconque.
   - Mesuré : nombre de clics droits reconnus / 10 par main.
   - Ressenti : la main droite clique-t-elle plus facilement (seuil 0,468) ?
     Trop facilement (faux clics droits en fermant la main) ?

## 2. Réveil, intention de pointer, anneau (HV-BH-ADAPT-03)

1. Bare Hands en **Veille**. Main détendue, doigts à plat, puis main qui bouge
   naturellement devant la caméra pendant 10 s.
   - Attendu : **aucun** anneau, aucun jeton, pas de réveil.
2. Former le **C** (pouce et index en C, autres doigts repliés), **de face**,
   tenir. Attendu : l'anneau apparaît dès que le maintien progresse, réveil en
   ~1,5 s. Noter le temps ressenti et si le réveil a eu lieu.
3. Même chose **de profil** (main tournée de ~45°). Noter : réveil oui/non,
   nombre d'essais.
4. En Actif : main détendue qui passe devant l'écran → aucun jeton. Index
   tendu, autres doigts repliés → le jeton apparaît (fondu).
   - Mesuré : apparitions de jeton non voulues sur 30 s de mouvement ordinaire.
   - Ressenti : la posture exigée est-elle naturelle ?

## 3. Pincements, latences (HV-BH-ADAPT-02)

1. 10 clics **vifs** (pincer-relâcher le plus vite possible) sur un bouton,
   puis 10 clics **appuyés** (tenir ~0,5 s).
   - Mesuré : clics reconnus / 10 dans chaque série ; faux glissements.
   - Ressenti : délai perçu à l'appui, au relâchement.
2. Glisser une fenêtre de la scène sur ~300 px et la lâcher.
   - Mesuré : la fenêtre se pose-t-elle là où la main l'a lâchée (écart
     estimé en px) ? Un clic parasite au lâcher ?

## 4. Présélection et assistance (HV-BH-ADAPT-05)

1. Viser une **étoile** de la scène sans pincer : l'anneau de présélection
   doit l'entourer, nom dessous ; le jeton n'est jamais déplacé vers elle.
   - Ressenti : l'anneau se voit-il bien sur la scène ? (contraste, taille)
2. Pincer : c'est **l'étoile de l'anneau** qui est prise (présélection =
   prise). Répéter 10 fois sur des étoiles proches. Mesuré : prises correctes / 10.
3. Deux étoiles **voisines** : tenir la main au milieu, trembler légèrement.
   Mesuré : l'anneau clignote-t-il d'une étoile à l'autre (nombre de bascules
   en 10 s) ?
4. **Pincement dans la bande ambiguë** (exactement entre deux voisines très
   proches) : attendu **rien** (pas de prise, pas de clic). Noter ce qui se
   passe.

## 5. Menu contextuel et pincement dans le vide (HV-BH-ADAPT-10, décision 70)

1. Ouvrir un menu contextuel à la main (clic droit pouce + majeur sur une carte
   d'agent ou un objet de la scène).
2. Pincer (pouce + index) **dans le vide**, loin de tout contrôle.
   - Attendu : le menu se ferme, rien d'autre ne se passe.
3. Rouvrir le menu, pincer sur son **en-tête** (le titre, pas une entrée) :
   attendu, il reste ouvert.
4. Rouvrir, pincer **entre deux entrées** du menu en visant mal : noter s'il
   se ferme (attendu : non si le point est ambigu entre les deux entrées ;
   l'entrée la plus proche est prise si elle est nettement plus proche).
5. Sans menu ouvert, pincer dans le vide : attendu, aucun effet.
   - Mesuré : fermetures correctes / essais ; fermetures non voulues.

## 6. Calibration complète à la main (HV-BH-ADAPT-07, HV-BH-ADAPT-02, -03)

Lancer : clic droit sur le bouton à icône de main → **Calibrer…**.

1. Pour **chaque** exercice : jouer, lire la **revue** (elle n'avance jamais
   seule — attendre 10 s pour le vérifier), puis Valider l'étape.
   - Mesuré : les valeurs de la revue (recopier : tremblement, latences,
     taux, etc.).
   - Ressenti : consignes claires ? durée ?
2. **Pincement primaire** et **secondaire** : noter si « Pincez plus
   franchement » apparaît, et le nombre d'épisodes mesurés.
3. **Tenir puis relâcher** : tenir chaque pincement ~1 s. Noter
   `premature_drop_count`, `missed_release_rate`, latence de relâchement.
4. **Viser et cliquer** (étoiles petites, voisines, mobile) : noter erreurs de
   cible et ratés.
5. **Fenêtre 6A / 6B / 6C** : déplacer, redimensionner à deux mains, **déposer
   (6C)** dans la destination. Noter réussite, erreur de placement.
6. **Bouger sans cliquer** (7A mouvement libre, 7B visée sans pincer) : noter
   les faux événements comptés (appuis, clics droits, réveils, curseurs).
7. **Double-clic** sur « Valider l'étape » : l'écran suivant ne doit rien
   valider ni passer ; le focus va au titre.
8. **Échap** une fois : message « Appuyez encore sur Échap… » ; ne pas
   confirmer.
8 bis. **Mains retirées plus de 30 s** pendant un écran de lecture ou une
   revue : retirer les deux mains du champ de la caméra, attendre 40 s
   (chronomètre), les remettre. Attendu : Bare Hands **reste éveillé** (pas de
   retour en veille, le bouton de main reste « Actif »), le parcours reprend là
   où il était. (Report des Slices 03 et 07.)
   - Mesuré : état du bouton de main à 35 s ; ligne `idle_sleep` absente de la
     console.
9. **Rapport** à 1440 × 900 : « Sera enregistré » et les boutons Enregistrer /
   Quitter sans enregistrer sont **visibles sans défiler** ; la liste des
   exercices défile seule (liseré en bas si elle déborde) ; **rien de la page
   ne transparaît** derrière le rapport (panneaux, pastilles, barres).
   - Mesuré : ce qui est listé sous « Sera enregistré » (avant → après) et
     « Conservé ».
10. Enregistrer. Vérifier dans l'onglet que seules les valeurs listées ont
    changé (comparer à 0.5).

## 7. Agent de calibration à la voix (HV-BH-ADAPT-06, HV-BH-ADAPT-07)

Relancer **Calibrer…**, aller au pincement primaire, jouer l'exercice.

1. Dire à JARVIS un ressenti : « le relâchement colle un peu ».
   - Attendu : réponse de **deux phrases au plus**, nombres seulement tirés
     des mesures de la séance ; il propose un essai.
   - Mesuré (trace) : `barehands.tool` → `calibration_status`,
     `calibration_record_feedback`, `calibration_propose_hypothesis`,
     `calibration_apply_trial` dans cet ordre (ou proche) ; **aucun**
     `settings_set`, aucun sous-agent.
2. Pendant que l'essai attend sa mesure : appuyer sur **Valider l'étape** puis
   **Passer…** — attendu : refus à l'écran « Un réglage d'essai attend d'être
   jugé sur cet exercice… ». Dire « passe à la suite » : même refus à la voix.
3. « Refais l'exercice » → rejouer → JARVIS juge l'essai (amélioré / inchangé
   / pire) avec les nombres du reçu.
4. **Accord** : dire « si tu veux, garde-le » → attendu : **refusé** (pas
   d'accord net). Puis « oui, garde ce réglage » → attendu : gardé
   (`calibration_accept_trial` réussi, réglage listé « acceptés » dans
   l'onglet après la séance).
5. Dire « mets les mains en veille » **pendant la calibration** — attendu :
   la calibration se ferme, notice « Bare Hands en veille — Mise en veille
   demandée : la calibration est arrêtée… », rien d'enregistré de la séance
   (l'essai déjà gardé en 7.4 reste gardé), Bare Hands en Veille et qui ne se
   réveille pas tout seul. La notice ne dit « l'essai en cours est défait » que
   si un essai était en cours : pour le vérifier, refaire une fois avec un
   essai appliqué et **non** gardé (dire un ressenti, laisser JARVIS appliquer
   un essai, puis « mets les mains en veille »).
   - Mesuré : état du bouton de main 10 s après ; console
     `barehands.sleep_ends_flow`.
6. Ressenti global : l'agent comprend-il vos mots ? le ton ? la longueur ?

## 8. Tester, dimension faible, recalibrer, comparer (HV-BH-ADAPT-08, HV-BH-ADAPT-09)

1. Dire « teste mes mains ». Attendu : l'écran d'accueil du **Tester**
   s'ouvre (aucun run ne démarre). JARVIS dit que c'est ouvert, pas « testé ».
   Redire « teste mes mains » : JARVIS dit qu'il était déjà ouvert.
2. Noter la **classe de fenêtre** affichée (vp100 ≥ 1280 × 700, vp90, vp80).
   Lancer le run, jouer les six exercices (~2 min).
   - Mesuré : les 8 scores de dimension, le global, la date.
   - Ressenti : le score décrit-il Bare Hands ou vous (fatigue, apprentissage) ?
3. S'il y a une dimension **sous 60** : suivre « Calibrer « exercice »… ». La
   calibration s'ouvre directement sur l'exercice (les précédents « plus
   tard »). Calibrer cet exercice, Enregistrer. Vérifier « Conservé » dans le
   rapport (les autres valeurs gardées).
   **Aucune dimension sous 60** : le lien n'est pas proposé. Prendre la
   dimension **la plus basse**, noter son nom et son score, ouvrir la
   calibration (clic droit → Calibrer…) et passer « plus tard » jusqu'à
   l'exercice qui lui répond (la table du Tester : acquisition et précision de
   sélection → Viser et cliquer ; résistance aux faux positifs → Bouger sans
   cliquer (mouvement libre) ; fiabilité du relâchement → Tenir puis
   relâcher ; glisser-déposer → 6C Déposer ; stabilité du pointeur → Bouger
   sans cliquer (visée) ; réactivité → Pincement pouce-index ; transitions →
   6A Déplacer), le calibrer, Enregistrer. Si rien n'est à
   calibrer (toutes les dimensions ≥ 80), sauter 8.3–8.4 en le notant
   (« pas de dimension faible, scores : … »).
4. Relancer le Tester, refaire le run, ouvrir **Voir l'avant / après**.
   - Mesuré : verdict par dimension (Amélioré / Dégradé / Inchangé / Pas de
     conclusion) et la dimension visée.
5. Pendant un run : **Échap** (pause), reprendre ; puis dire « mets les mains
   en veille » — attendu : run arrêté, rien de rangé, notice ; puis éteindre /
   rallumer Bare Hands pendant un autre run — attendu : run arrêté,
   « Bare Hands a été éteint pendant le test ».
6. **Classes de fenêtre** : réduire la fenêtre sous 1024 × 560 → l'accueil
   refuse avec sa phrase ; à 1152 × 630 (vp90) → le run part ; redimensionner
   pendant un run → arrêt « la fenêtre a changé ». Noter la classe affichée
   à chaque taille.
7. Bare Hands **éteint**, dire « teste mes mains » → JARVIS dit que Bare Hands
   est éteint et ne le rallume pas sans votre accord. Mesuré (trace) : le
   refus vient du **Control Center**, `barehands_disabled` (409), avant que la
   page soit consultée. Les codes de la page (`barehands_benchmark_lifecycle_off`)
   ne s'obtiennent qu'aux boutons — vérifier aussi : Bare Hands éteint, le
   bouton « Tester… » de l'onglet est grisé avec sa raison.

## 9. Confidentialité et nettoyage (tous)

1. Après la séance : `runtime/barehands-benchmarks.json` ne contient que des
   résumés chiffrés (pas d'image, pas de liste de points de main). Noter sa
   taille et le nombre de résultats (≤ 20).
2. Le profil (`barehands_calibration_profile` dans les réglages) ne contient
   que des nombres par main, des états d'étape et `tuning`.
3. Onglet fermé pendant une calibration → rouvrir : aucune séance fantôme
   (`GET /api/barehands/calibration-session` → `active: false` après ≤ 30 s).
4. Après avoir quitté chaque parcours : plus de jeton figé, plus d'anneau, la
   veille automatique revient après 30 s sans main.

---

## Ce qu'il faut rendre

Pour chaque section : Mesuré / Ressenti / Verdict, plus la liste des KO avec
capture ou ligne de journal. Un KO sur les points 5, 6.7, 6.9, 7.2, 7.5, 8.1 ou
9 est bloquant pour la clôture ; les autres se rangent en réglages à affiner.
