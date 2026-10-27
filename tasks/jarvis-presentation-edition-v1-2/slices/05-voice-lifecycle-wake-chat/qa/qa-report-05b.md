# QA — Slice 05b (mot de réveil openWakeWord dans les builds internes, HD-V12-01)

Diff relu : `76ed387e..de19e3d7` (`40fd44d2`, `9b90236e`, `de19e3d7`), worktree `pev12d`, branche `wt/v12-s05b`.
Agent QA, 2026-10-27. Preuves : `C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\448345f0-a514-4023-9dde-33aed523cf61\scratchpad\v12s05bqa\`.

## Verdict : PASS avec réserves

Canal par défaut `production`, refus de `verify` sur les composants internes, verrou interne, épinglage des
modèles, avis de licence et défaut du mot de réveil sont conformes à HD-V12-01 et prouvés par deux vrais builds
reconstruits depuis un clone propre de `de19e3d7`. Aucun bloquant. Un majeur (doc contredite par le comportement
quand un modèle manque), des mineurs.

## Findings

### Majeur

**MA1 — Modèle manquant dans un build interne : retour silencieux à F9, contraire à la doc.**
`docs/voice-lifecycle.md:128-130` dit : « If the engine files disappear after install, the default stays armed but
the status line says why it does not listen (`wake_model_missing`, « Moteur absent ») ». C'est vrai seulement dans
le processus déjà lancé (`installed_engine_ready` est en cache). Dès le redémarrage suivant,
`jarvis/runtime/wake_word_install.py:106` rend faux, `baseline()` rend les défauts sûrs, et l'utilisateur lit
« Aucun mot de réveil vocal n'est activé : F9 réveille JARVIS » (`code: null`). Le mot de réveil n'est alors plus
armé, et rien ne dit que c'est à cause d'une panne.
Scénario : paquet interne réel, `hey_jarvis_v0.1.onnx` retiré, nouveau processus : `load({}).enabled == False`,
`voice_lifecycle.wake_engine({})` → `configured: false, code: null` (`detector-and-default-runs.txt`, `det2.py`).
Le test `test_an_installed_engine_whose_models_went_missing_is_said_not_silent` ne couvre que le cas en processus.
Deux corrections possibles : (a) la condition d'armement devient « produit installé + manifeste avec un bloc `models` » et
l'état du moteur dit la panne ; (b) la doc dit le vrai comportement. `verify` ou la réparation détectent
de toute façon le paquet altéré : l'impact se limite aux builds internes.

### Mineur

- **m1 — Le contrôle sur le disque de `channel_problems` est étroit** (`jarvis/private_runtime.py:427-429`) : il ne voit que
  `site-packages/openwakeword|onnxruntime` (+ `<module>-*.dist-info`) et `models/`. Avec des manifestes réécrits
  de façon cohérente (arbres et `package_sha256` recalculés), `verify` accepte un paquet de production qui contient
  onnxruntime renommé (`ort_renamed/`) ou `hey_jarvis` renommé en `app/jarvis/assets_hj.bin`
  (`inject-results.json`, cas B et G). Sans réécriture des manifestes, les deux sont refusés par l'empreinte des
  arbres (cas A et F). Ce n'est pas exploitable par accident : le build exige une entrée de politique par roue
  et `.gitignore` exclut `*.onnx`. Une recherche de `*.onnx` / `*.tflite` hors `onnxruntime/datasets` renforcerait le
  contrôle à peu de frais.
- **m2 — Trous de test (mutations survivantes)** : (M4) le défaut `--channel` de la sous-commande `build`
  (`packaging/windows/build_package.py:951`) n'est testé par aucun appel à `main` : `default=PR.CHANNEL_INTERNAL`
  passe les 124 tests. (M7) Si on retire la vérification du marqueur produit dans `installed_engine_ready`
  (`wake_word_install.py:97-98`), les tests passent encore. La raison : le venv n'a pas l'extra `wakeword`, donc
  `test_the_development_checkout_is_never_an_installed_engine` passe pour une autre raison que celle qu'il veut
  prouver. J'ai vérifié le comportement à la main : un checkout avec l'extra et des modèles vérifiés simulés donne
  `ready=False`, profil vierge désactivé. C'est donc correct aujourd'hui, mais rien ne le garde.
- **m3 — `release_info.py` ne refuse pas de publier un build interne** (`scripts/release_info.py:217-228`). Il
  l'identifie seulement : nom `jarvis-<v>-internal-…`, `production_blockers`, `channel_warning`. Le dépôt n'a pas
  d'étape de publication, et la CI construit le canal par défaut (`.github/workflows/ci.yml:137`, donc production).
  C'est acceptable, mais une future étape de publication devra lire `product.channel`. Un manifeste qui se dit
  `internal` sur un paquet de production passe `verify` (cas J) : l'erreur va dans le sens prudent.
- **m4 — Variante `onnxruntime_directml-*.dist-info` seule** (cas D) : le motif `onnxruntime-*.dist-info` ne
  l'attrape pas. Sans effet réel : ces roues installent le dossier `onnxruntime/`, qui est attrapé.

### Signalé (hors défaut de la Slice)

- La licence CC BY-NC-SA « NonCommercial » appliquée aux tests internes d'une société qui prépare un produit
  commercial : c'est une question juridique qui relève de HD-V12-01 et HV-PACKAGE-07, pas de la Slice.
- `onnxruntime` livre trois `.onnx` de démonstration (`onnxruntime/datasets/*.onnx`, MIT) dans le build interne. C'est
  normal, mais une future recherche de `*.onnx` devra les exclure.

## Vérifié OK

- **Canal** : `production` par défaut (`DEFAULT_CHANNEL`, argparse) ; `internal` seulement par `--channel internal` ;
  un canal inconnu ou mal casé (`Production`) est refusé ; un manifeste sans canal vaut production (cas K).
- **Vrai build de production** (clone propre `de19e3d7`, cache partagé à empreintes vérifiées) : sonde OK, réveil
  `default_enabled: false` ; `verify` vert (`1a76c23f…`, canal production) ; ni `models/`, ni `.onnx`, ni
  openwakeword/onnxruntime/scipy/sklearn. **Injections** (`inject.py`) : onnxruntime sous son vrai nom, ou
  `OpenWakeWord` avec une casse différente, manifestes réécrits → refus nommé « réservé au build interne » ; `models/`
  avec bloc `models` réécrit → refus ; ajouts sans réécriture → refus par l'empreinte. Paquet de nouveau intact à la fin.
- **Vrai build interne** : avertissement au build et à `verify` ; `verify` vert (`02b00338…`) ; 3 modèles sous
  `models/wake-word` ; sonde : `OpenWakeWordEngine`, silence `[-1]*5`. Mon essai avec le Python du paquet (PATH
  Windows, LOCALAPPDATA du bac, aucun périphérique ouvert) : `ready: true`, profil vierge armé `openwakeword`, bloc
  illisible → désactivé, `enabled:false` écrit → désactivé ; 20 trames de silence et 20 de bruit aléatoire → aucune
  détection. Le paquet de production dans les mêmes conditions donne `ready: false`, F9 seul.
- **Licences** : NOTICE des modèles (attribution, URI, non commercial, « à remplacer avant production ») ;
  `LICENSE` et `ThirdPartyNotices.txt` d'onnxruntime livrés. **Astuce flatbuffers : acceptable et exacte.** La
  métadonnée de la roue dit `License: Apache 2.0` et le classifieur Apache. Le texte copié est le texte Apache-2.0
  standard, identique octet pour octet au `LICENSE` de requests 2.34.2, sans copyright propre à requests. Le
  `NOTICE` de requests n'est pas copié (filtre `LICEN*`). Le `NOTICE.txt` dit d'où vient le texte, et le build
  refuse une source dont la licence déclarée diffère.
- **Verrou interne** : 12 roues en plus, SHA-256, aucune en double avec la production (`read_locks`,
  `internal_lock_findings`) ; `scripts/verify_release.py` → « Release verification passed ».
- **Défaut du réveil** : blanc + moteur installé → armé ; bloc illisible → sûr ; patch partiel → appliqué
  sur `load()` (donc sur le défaut armé) ; checkout de développement → inchangé.
- **Docs** : release.md (P1, canaux), windows-packaging.md, voice-lifecycle.md (sauf MA1), third_party/README.md,
  SECURITY.md, OPERATIONS.md cohérents avec le code.

## Tests rejoués

- `test_wake_word_installed_default.py`, `test_release_tooling.py`, `test_windows_packaging.py` : 124 passés.
- 18 fichiers voisins (openwakeword engine, wake word settings/api/ui/docs/install/catalog/disabled/parity/wiring,
  v2 backends, voice_lifecycle, private_runtime, product_setup, windows_installer, release_update_profile,
  wakeword_dependency_declaration) : 703 passés, 2 ignorés (essais live sans modèle ni clip). Aucun échec, connu ou nouveau.
- Mutations : 9 tentées, 6 tuées, 3 survivent (M1 quasi équivalente, M4 et M7 → m2).

## Non vérifié

- Le vrai micro (« Hey Jarvis » réellement prononcé) → HV-V12-VOICE-02.
- L'installeur et `package_smoke.py` sur le build interne ; la reproductibilité du build interne.
- `test_wake_word_settings_browser.py` (Chrome, plus de 10 min) : pas rejoué.
- Voice en cours d'exécution en Sleep avec le défaut armé : couvert seulement par les tests et la sonde.

Nettoyage : clone, deux paquets (448 Mo + 689 Mo) et bac `%TEMP%\v12s05bqa` supprimés ; aucun processus laissé ;
le cache partagé `jarvis-build-cache` est réutilisé tel quel (déjà peuplé par l'implémenteur).
