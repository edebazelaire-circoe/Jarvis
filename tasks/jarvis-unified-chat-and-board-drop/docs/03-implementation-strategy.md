# 03 — Déploiement et dépendances

## Chemin critique P0

1. **00 audit/orchestration** : état réel de `main`, tâches parallèles, contrats, Task Types. 
2. **01 contrat produit/technique** : figer projection, admission, état de canal, pièces jointes et protections ; documenter les éventuels gaps L2 avant implementation.
3. **02 projection** : tests unitaires des deux seuls types affichables et de la séparation Board/Session.
4. **03 ingress texte** : route end-to-end Core indépendante de Voice et réutilisant binding Brain actif ; mode chat => disposition textuelle, aucune TTS.
5. **04 canal Voice/Chat** : source d'état et transition explicite sans annulation Brain ; garde serveur contre la course d'envoi.
6. **05 flux lecture** : projection API + réhydratation/poll du journal existant, sans doublons ni fuite diagnostique.
7. **06 UI** : bouton bas droite, panneau, transcript, composer lock et bascule ; premier trajet complet clavier. **Jalon utilisable sans pièce jointe.**
8. **07 pièces jointes chat** : sécurité, ingestion, références vers Brain, UI drop + sélection et erreurs ; test documentaire réel. **Jalon P0 complet.**
9. **08 extra Board** : import/dépose ressources URL/fichiers/images ; voie indépendante, sans régression du chat.
10. **09 tests intégrés** : isoler un Core/Control Center, scoping, mode switch, reconnexions, sécurité et traces réelles.
11. **10 release/Human acceptance** : readiness de sortie, docs L3, validation utilisateur sur instance autorisée.

Le PM peut découper plus finement une Slice s'il découvre que UI et backend de l'extra demandent des contrats distincts. Aucun travail du PM ne change le produit. Les tâches de chat ne dépendent pas du chantier Remotion.

## Migration

- Ancien historique : lecture canonique de `ConversationEventStore`, sans copie. Les sessions antérieures à l'instrumentation peuvent ne pas avoir de backfill exhaustif : afficher un état honnête, ne jamais inventer des messages à partir de traces.
- Si API/schéma change : append-only events, rétrocompatibilité client, migration SQLite versionnée avec snapshot (`CLAUDE.md`). Ne pas modifier migrations publiées, base locale ou fichiers historiques.
- Feature gate utile pour introduire Chat sans altérer Voice ; déploiement par étapes avec tests de non-régression. Privilégier réutilisation des routes existantes, sinon nouvelles routes mince adaptatrices.
- Protéger P0 des chantiers actifs qui touchent `control_center.html`, Brain, Boards. Séquencer ou rebase à chaque Slice, éviter les conflits de branche.

## Contrat de handoff

Chaque Work Agent commence par vérifier les dépendances, relire les sources canoniques indiquées, confirmer les fichiers propriétaires et tests, exécuter `/caveman` + `/coding-guideline` pour code (et `/impeccable` + agent Claude quand frontend pris en charge). Il n'exécute pas Jarvis en production. Il retourne preuves, changements de docs, et points de Human validation identifiés ; PM lance les QA obligatoires.
