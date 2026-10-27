# Décisions Human — V1.2 (reçues le 2026-10-27)

Réponses du Human aux points ouverts de `READINESS.md`.

- **HD-V12-01 Mot de réveil** : la V1.2 reste en test interne. On garde la technologie actuelle (openWakeWord, modèles CC-BY-NC-SA) pour les builds de test interne ; elle sera remplacée par une autre technologie avant une vraie mise en production. Conséquence : la Slice 05 peut armer le mot de réveil vocal en Sleep dans les builds internes (en plus de F9), et l'exclusion du paquet (`packaging/windows/requirements.in`, `third_party_policy.json`) est levée pour les builds internes seulement. Le remplacement devient un bloquant de mise en production, consigné dans la doc de release.
- **HD-V12-02 Destination des rapports de support** : `e.debazelaire@circoe.com`. Fournie par le Human, donc pas devinée ; elle vit dans la configuration du produit (valeur par défaut modifiable), pas comme littéral dispersé dans le code. L'envoi exige toujours la confirmation explicite de l'utilisateur ; l'enregistrement manuel reste le repli.
- **HD-V12-03 macOS** : ajouter la CI macOS dans la Slice 08. Le Human fera l'acceptation sur le Mac d'un collègue avant toute sortie macOS. Aucune affirmation de support macOS d'ici là.
- **IGuard** : hors périmètre de cette tâche ; le Human le branchera lui-même par une connexion MCP. La recherche doit simplement fonctionner sans lui.
