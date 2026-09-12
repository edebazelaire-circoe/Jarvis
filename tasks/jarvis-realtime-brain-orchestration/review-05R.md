# Slice 05R — commande mute et ponctuation de transcription

Date : 2026-09-12. Correction attribuée après validation des slices 08R et 02R.

## Défaut et reproduction avant correction

Dans `RealtimeConversationBridge._handle_transcript`, seule la virgule était
retirée avant comparaison avec `jarvis mute`. Un point final suffisait donc à
transformer la commande vocale en demande au cerveau ; Voice restait ACTIVE.

Reproduction sans fournisseur réel ni matériel, sur le vrai bridge et les doubles
existants :

| Transcript | Mute | Envoi cerveau |
| --- | --- | --- |
| `Jarvis mute` | oui | aucun |
| `Jarvis mute.` | non | texte complet |
| `Jarvis, mute !` | non | texte complet |

Régressions ajoutées avant modification de production :

```powershell
./.venv/Scripts/python.exe -m pytest -q tests/unit/test_v2_continuous_live.py -k mute -W error
```

Résultat : **6 failed, 7 passed, 17 deselected**. Les six variantes ponctuées
dépassaient le délai d'attente du retour au mot d'éveil. La commande historique
et les six phrases qui ne doivent pas déclencher mute passaient déjà.

## Correction

- `jarvis/runtime/realtime_audio.py` : comparaison locale des mots de commande
  après remplacement des seuls caractères de ponctuation Unicode par des espaces.
  La liste complète doit rester exactement `jarvis`, `mute`. Les autres lettres,
  nombres et symboles restent significatifs. Le texte utilisateur transmis au
  cerveau et la normalisation des confirmations ne sont pas modifiés.
- `tests/unit/test_v2_continuous_live.py` : le test de cycle de vie mute existant
  couvre maintenant sept variantes, dont point, interrogation, exclamation,
  virgule, nouvelles lignes, espaces et guillemets. Six contre-exemples conservent
  Voice ACTIVE et transmettent le texte original au cerveau : négations, demande
  d'explication, mention de la commande et négation non latine.

Pourquoi ne pas réutiliser `turn_filters.words()` : sa normalisation ne conserve
que l'alphabet ASCII et effacerait le mot `нет` dans `Jarvis mute нет`. Une
normalisation destinée aux filtres d'audition ne doit pas supprimer un mot de la
commande exacte.

Les contrôles d'identité/adressage et les filtres d'audition précèdent toujours
la reconnaissance de commande. Aucun changement dans leur ordre ou leurs règles.

## Contrat d'observabilité et de test

Support officiel : `RuntimeJournal`, selon la Décision 27 du handoff.
Pas de nouveau canal ni sonde temporaire.

- Commande exacte : événement existant `voice.background` puis `audio.stop` ;
  aucun `voice.brain_turn_submitted`. Le travail Core, la conversation et le
  dépôt Core restent vivants ; aucun appel d'annulation.
- Phrase mentionnant la commande : `voice.brain_turn_submitted` avec le
  `correlation_id`/`conversation_id` existant ; aucun `voice.background`.
- Une ponctuation normale ne constitue pas un échec : aucun nouveau code
  d'erreur ou warning. Les erreurs de transport suivent leurs chemins existants.
- Vérification : assertions directes sur `RecordingJournal`, sur les tours reçus
  par le double Core et sur le cycle de vie du runtime. Aucune session acoustique
  réelle prétendue.

## Validation après correction

```powershell
./.venv/Scripts/python.exe -m pytest -q tests/unit/test_v2_continuous_live.py tests/unit/test_v2_voice_toggle.py tests/unit/test_surface_reflex_policy.py tests/unit/test_v2_speech_scheduler.py tests/integration/test_v2_async_conversation.py -W error
```

**133 passed**, sans warning, après ajout des assertions d'observabilité.
Ce gate couvre le cycle continu, le cycle legacy, la politique réflexe,
l'ordonnanceur et les conversations asynchrones intégrées.

`git diff --check` : aucun défaut d'espacement ; avertissements habituels
de conversion LF/CRLF seulement.

## Limites et prochain pas

La ponctuation est testée sur des transcripts injectés, pas sur la qualité d'un
modèle de transcription réel. Les reformulations de la commande restent hors
périmètre : seul le contenu lexical exact `Jarvis mute` est reconnu.

Prochain pas : revue de cette tranche par l'orchestrateur puis gate 09. Le test
SQLite barge-in réservé à cette autre tranche n'a pas été modifié.

Fichiers modifiés uniquement dans le périmètre attribué ; aucun commit Git.
