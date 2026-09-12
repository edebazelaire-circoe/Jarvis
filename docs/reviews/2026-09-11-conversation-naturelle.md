# Audit de la conversation vocale du 11 septembre 2026

Statut : diagnostic et proposition de conception, sans modification du runtime.
Référence du code audité : `e292784`. Le transcript fourni porte le 11/09/2026.

## Conclusion

Les difficultés observées viennent de responsabilités mal séparées : un agent CLI exécute les actions et traite la conversation dans la même file ; un second modèle transforme son texte en audio sous une consigne de lecture littérale. La liste des sous-agents observe les délégations du CLI sans les imposer. Le contexte du brain ne reflète pas complètement les paroles et incidents vécus par l'utilisateur.

La cible demandée est différente : le brain comprend, orchestre, suit et répond ; toute action sur les fichiers, applications ou services est confiée à un exécutant visible. Les salutations et clarifications restent dans la conversation, sans créer artificiellement un agent d'exécution.

## Preuves et limites

Analyse du code, du transcript fourni et de 247 événements récupérés par l'API locale officielle `GET /api/trace?limit=10000`, filtrés sur 15:10–15:17, Europe/Paris. Le dépôt utilise `RuntimeJournal` et son API, pas le LogBroker de Symphonia. Les traces sont en UTC ; les heures ci-dessous sont locales.

Aucun appel à un service de génération ni essai microphone effectué. Aucune observation visuelle de la liste des agents : l'analyse porte sur son code et sur les événements qui l'alimentent. Les horodatages `voice.assistant` et `speech.completed` ne sont pas des débuts de parole ; la transcription de sortie ne prouve pas non plus que tout l'audio a été joué.

### 1. L'annonce de lecture est ajoutée par la surface vocale

À 15:12:56.496, `agent.ask` contient seulement « Ça va bien, merci. Et toi ? On travaille sur quoi aujourd'hui ? ». À 15:13:05.480, `voice.assistant` contient en plus « Okay, je lis le texte demandé, mot pour mot. », avec le même `speech_id` que la vraie réponse. Pour cet incident, le brain n'a donc pas écrit la phrase parasite.

`jarvis/adapters/openai_realtime.py`, `VERBATIM_SPEECH_INSTRUCTION` et `speak()`, demandent à un modèle conversationnel de lire un texte. Une interdiction d'ajouter une introduction existe déjà dans le code audité : la renforcer seule ne fournit pas une garantie d'absence de fuite. Le transcript ne permet pas d'affirmer que toutes les instructions métier sont lues ; il démontre précisément cette annonce parasite.

### 2. Les réflexes produisent une seconde conversation

`REFLEX_INSTRUCTION` impose une phrase de trois à dix mots montrant ce que la voix a compris « qu'il faut faire ». Appliqué à une salutation, ce cadrage favorise « Je note votre salutation ». Appliqué à une question sur une explication, il favorise « Je cherche la console de debug ».

Les règles de session prescrivent un vocabulaire fermé ; la consigne spécifique du réflexe demande au contraire une phrase contextuelle libre. `JARVIS_PERSONA` impose le vouvoiement à la surface, tandis que le brain tutoie dans cette session. Le brief du brain n'injecte pas cette même persona.

À 15:12:54.906, le réflexe est lancé environ 1,2 seconde après le transcript ; la réponse utile est prête à 15:12:56.496. Le système a déjà engagé une prise de parole supplémentaire.

### 3. L'absence de délégation est réelle dans la séquence

Sur la fenêtre observée : 16 appels d'outils, dont `Grep`, `Read`, `PowerShell`, `Bash`, `Write` et `Edit`. Tous ont `parent_tool_use_id=null`. Aucun appel `Agent`/`Task`, aucun événement de sous-tâche. Les créations de fichiers à 15:15:39.949 et 15:15:49.761 sont effectuées directement par le brain.

`ClaudeLocalAgent.start()` ouvre un CLI généraliste. `build_agent_brief()` ajoute l'adressage et l'état public, sans contrat imposant la délégation ni séparation des capacités. `AgentTaskTracker.observe_claude()` reconstitue les tâches à partir du flux ; il n'en crée pas pour exécuter une demande. Le panneau interroge `/api/agent/tasks` et affiche cette projection.

L'absence de carte est donc cohérente avec l'absence de délégation dans cette session Claude. Cela n'exclut pas d'autres défauts d'affichage. Limite supplémentaire : l'adaptateur Codex expose explicitement le brain seul et ne possède pas de lecteur d'événements de sous-agents équivalent.

### 4. Le brain est indisponible pendant le travail

`ClaudeLocalAgent.ask()` garde `_ask_lock` pendant l'attente de la réponse complète. Le Core accepte plusieurs tours, mais ce verrou sérialise leur traitement réel dans le CLI.

La correction reconnue à 15:14:55.314 ne devient `agent.input` qu'à 15:16:13.171, soit 77,9 secondes plus tard. Le « Oui » reconnu à 15:15:11.948 est transmis à 15:16:19.008, soit 67,1 secondes plus tard. Les deux sont aussi marqués `uncertain` dans leur brief. Leur traitement différé et leur contexte doivent être distingués d'une mauvaise reconnaissance des mots.

Le backend `ControlCenterBrainBackend` attend un résultat HTTP complet et le convertit en parole ; ce chemin ne transmet pas un flux de décisions et de résultats d'exécutants au brain pendant la conversation.

### 5. Le brain ne voit pas toute l'expérience utilisateur

`SpeechScheduler._persist()` conserve le texte demandé par le brain en supposant une restitution fidèle. Le brief de 15:13:12 ne contient pas l'annonce de lecture réellement ajoutée par la voix. Le brief de 15:13:55 ne contient pas non plus le message d'interruption par la console dans « Déjà dit à l'utilisateur ».

Le problème n'est pas de transmettre davantage de raisonnement interne : il faut transmettre les paroles publiques réellement générées, leur livraison et les événements utiles à la conversation. Aujourd'hui, le brain peut devoir enquêter dans le dépôt sur une phrase que l'utilisateur vient simplement d'entendre.

### 6. La console de debug modifie ce qu'elle observe

`ClaudeLocalAgent.open_console()` arrête le processus vocal et interrompt son appel en cours. `start()` ouvre une nouvelle session si la console conserve l'ancienne. Les événements `agent.console_interrupt` à 15:13:40 et `agent.session_forked` à 15:13:55 confirment ce fonctionnement.

L'inspection devrait être passive par défaut. La reprise interactive est un changement de propriétaire de session, à distinguer clairement de l'affichage des traces.

### 7. L'interruption comporte plusieurs latences distinctes

Une nouvelle demande est transcrite à 15:14:25.648 ; l'ancienne réponse n'est marquée interrompue qu'à 15:14:35.932. Après détection confirmée de l'interruption, l'arrêt audio local est mesuré à 70,8 ms. Cette bonne dernière mesure ne suffit donc pas à qualifier l'ensemble de l'expérience.

Un avertissement `response_cancel_not_active` suit : la génération fournisseur peut être terminée alors que le son local continue. Il faut distinguer génération, tampon audio, lecture et révision d'intention. La cause exacte du retard de détection demande une recette acoustique ; les traces seules ne permettent pas de l'attribuer au micro ou à l'écho.

## Architecture proposée

```text
Micro → perception → brain conversationnel
                         ├─ réponse / clarification → sortie vocale
                         └─ délégation → registre Core → exécutant
                                              ↑             │
                                              └─ événements ┘
                                                     │
                                            brain + panneau Agents
```

Un seul propriétaire de l'intention. Le brain dispose d'outils d'orchestration et de consultation de l'état public ; les exécutants disposent des outils d'action. Un exécutant rend des faits et des artefacts, jamais une consigne à prononcer. Le brain formule ensuite une réponse orale courte.

Créer l'enregistrement de tâche avant son lancement, avec identifiant stable, objectif, parent, statut, révision de demande et résultat. Une demande peut nécessiter un ou plusieurs exécutants, mais une reformulation doit mettre à jour le travail concerné plutôt que le dupliquer. Prévoir déduplication, annulation explicite, résultat périmé, échec de lancement et reprise après redémarrage.

Le lancement rend immédiatement un identifiant ; le travail se poursuit indépendamment de l'appel conversationnel. Déclarer un sous-agent puis attendre son résultat sous le même verrou ne résoudrait pas l'indisponibilité du brain. Les nouvelles paroles et les résultats reviennent comme événements à un brain disponible pour arbitrer.

Le panneau affiche le même registre que celui utilisé pour exécuter, avec les états « en attente », « en cours », « terminé », « annulé », « échec ». Les événements CLI enrichissent les traces et les métriques ; ils ne constituent plus l'unique preuve d'existence d'une tâche.

## Ordre de réalisation recommandé

1. **Séparer le contrat oral du résultat technique.** Introduire des champs explicites pour la parole, l'affichage, les résultats et les erreurs publiques. Partager le choix de tutoiement/vouvoiement. Réponse brève par défaut, détail dans le document ou le panneau. Aucun contexte interne ni rapport brut envoyé à la synthèse vocale.
2. **Rendre la conversation disponible pendant l'exécution.** Contrat d'orchestration, capacités d'action réservées aux exécutants, registre de tâches commun à l'exécution et à l'interface, retour asynchrone. Réviser la décision historique « pas d'ordonnancement multi-agents » avant de considérer cette cible comme l'architecture en vigueur.
3. **Unifier l'historique public.** Conserver séparément texte prévu, transcription de sortie, état de lecture et interruption. Renvoyer au brain les incidents publics pertinents. Ne jamais traiter l'intégralité d'un audio généré mais interrompu comme entendue.
4. **Retirer les réflexes systématiques.** Salutation : réponse sociale directe. Action longue : un acquittement éventuel, cohérent avec une délégation effectivement acceptée. Pas d'annonce d'activité sur simple supposition de la surface, ni de phrase de remplissage pendant que l'utilisateur reformule.
5. **Traiter les corrections en priorité.** Arrêter la sortie devenue inadaptée sans annuler automatiquement le travail. Le brain décide s'il faut poursuivre, amender, annuler ou remplacer la tâche, avec son identifiant. Les résultats d'une intention remplacée ne doivent pas revenir comme une nouvelle réponse pertinente.
6. **Rendre le debug passif et mesurer la voix sur poste.** L'ouverture des traces doit conserver session et tâches. Évaluer la détection d'interruption séparément de l'arrêt du lecteur, puis ajuster VAD et garde d'écho sur des essais représentatifs.

### Choix de la sortie vocale

Deux voies méritent une comparaison mesurée, sans changer de fournisseur à l'aveugle :

- Une chaîne explicite où le brain rédige une phrase orale et une synthèse vocale reçoit uniquement ce texte. L'API Speech permet la lecture en streaming avant la fin de génération. Cette voie retire l'étape conversationnelle « lis mes instructions » ; elle ne dispense pas de vérifier omissions et ajouts audibles. Source : [Text to speech](https://developers.openai.com/api/docs/guides/text-to-speech).
- Une interface vocale native capable de continuer la conversation pendant le travail d'un backend séparé. La documentation actuelle décrit notamment cette séparation pour GPT-Live, ainsi que les compromis des architectures Realtime et des chaînes transcription–agent–synthèse. Piste à prototyper sur la même recette ; disponibilité, migration et qualité française restent à vérifier pour ce projet. Source : [Voice agents](https://developers.openai.com/api/docs/guides/voice-agents).

Ma recommandation pour JARVIS : stabiliser d'abord les contrats brain/exécutants/historique, puis comparer ces sorties sur les mêmes scénarios. La liberté de formulation de la voix doit porter sur des faits publics établis ; elle ne doit pas lui donner un second pouvoir de décision métier.

La troncature Realtime ne fournit pas à elle seule une transcription précisément alignée sur le son entendu. Le suivi local de lecture et les marques d'interruption restent nécessaires. Source : [Realtime conversations](https://developers.openai.com/api/docs/guides/realtime-conversations).

## Recette et observabilité à ajouter lors de l'implémentation

| Scénario | Résultat attendu |
| --- | --- |
| « Salut, ça va ? » | Une réponse sociale courte, pas de réflexe administratif, pas d'outil d'action |
| « Fais le transcript et ouvre-le » | Exécutant visible dès l'acceptation, fichiers vérifiés, annonce de succès après résultat |
| « Attends, seulement le transcript » pendant le travail | Correction traitée sans attendre la fin du travail, même tâche amendée ou remplacement explicite, aucune écriture doublée |
| « Pourquoi as-tu dit cela ? » | Le brain dispose de la parole publique en cause et répare l'échange avant une éventuelle investigation déléguée |
| Ouverture des traces | Aucune interruption, aucun changement de session |
| Échec de création / annulation / résultat tardif | État visible exact et explication courte, aucun faux succès |
| « Oui » | Rattaché à une question en attente ; pas de nouvelle opération sans référent |
| Résultat obtenu pendant une autre prise de parole | Pas de collision ni de lecture obsolète ; présentation au moment approprié |

Corrélations proposées : conversation → tour → révision d'intention → tâche → sortie vocale. Journaliser acceptation, début effectif, mise à jour, annulation et résultat comme événements normaux ; identifier distinctement échec de lancement, exécution échouée, livraison échouée et divergence de parole. Réutiliser `DiagnosticSink`/`RuntimeJournal` et leur API ; aucun nouveau canal n'est créé par cet audit.

Mesurer fin de parole → réponse utile, correction reconnue → traitement par le brain, interruption détectée → arrêt local, et acceptation de tâche → apparition dans le panneau. Suivre médiane et p95 sur des essais répétés. Objectifs initiaux à valider sur poste : réponse sociale utile en moins de 2 s, arrêt local après détection en moins de 200 ms, visibilité de tâche en moins de 1 s. Ce sont des objectifs, pas des performances démontrées.

Exiger zéro consigne interne prononcée et zéro annonce de succès sans résultat dans la recette ; mesurer séparément leur fréquence sur des essais plus larges. Rejouer le transcript avec variations de pauses, reformulations et interruptions. Les tests de structure des prompts ne remplacent pas les essais audio réels.

## Validation de l'audit

Tests existants exécutés :

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/unit/test_agent_tasks.py tests/unit/test_surface_reflex_policy.py tests/unit/test_realtime_output_control.py tests/unit/test_claude_debug_console.py tests/integration/test_v2_brain_protocol.py
```

Résultat : **123 tests réussis en 5,81 s**. Ils valident des contrats techniques existants ; plusieurs comportements problématiques sont précisément autorisés ou attendus par ces contrats. Aucune correction fonctionnelle ni validation acoustique n'est revendiquée ici.
