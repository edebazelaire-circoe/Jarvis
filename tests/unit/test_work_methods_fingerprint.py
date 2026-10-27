"""Garde d'empreinte des Work Methods livrées (V1.2 Slice 03).

Lacune relevée à l'audit de la Slice 00 : modifier le texte d'une méthode intégrée sans changer sa version
change en silence le contenu derrière `id@version` (les faits `work_method`, l'historique des missions et
l'apprentissage des candidats citent la clé, pas le texte). Seules les versions promues (table v11, en ajout
seul) étaient protégées. Ce test fige l'empreinte de chaque version livrée.

Règle (`docs/work-methods.md` › *Versions livrées*) :
- changer quoi que ce soit d'une méthode livrée (nom, résumé, principes, critères, relations, rôles) = publier la
  version suivante (`@2`), jamais réécrire `@1` ;
- ajouter ici l'empreinte de la nouvelle version, et **garder** celle de l'ancienne (historique) ;
- la nouvelle version livrée doit dépasser toute version déjà promue de la même méthode : sinon
  `promotion_refusal` écarte la promue (`work_method_version_not_after_builtin`) et deux contenus porteraient la
  même clé.
"""

from __future__ import annotations

import hashlib
import json

from jarvis.domain.work_methods import BUILTIN_METHODS, WorkMethod, render_method

#: `<id>@<version>` -> sha256 du contrat (`to_payload`, clés triées) et du texte apposé (`render_method`).
#: Une ligne ne se modifie jamais ; une nouvelle version ajoute la sienne.
SHIPPED_FINGERPRINTS = {
    "quick-research@1": "5eeaefa0f18e9bc8cf7bdd719eacbbad8fafbb66970b6d9d6b3a6fc9741ced51",
    "deep-research@1": "f9187fc3de5a229cc5e254c58f4ff5b48c7a013e41a920326c81404f9d33e57c",
    "comparative-research@1": "e4bcaec4e4b17c9bcf7442db2ed3286ea602a9c22c7b67e7f02f12bc207ee02e",
    "bug-investigation@1": "3706652c4e0685b14cdac36aca5a6da9a6812e29cb26a66e1893ba18bade1fe9",
    "result-review@1": "67366a5968f2c25c15c07e65b922c98dfcd4fa98843a77331604bad97588a547",
}


def fingerprint(method: WorkMethod) -> str:
    payload = json.dumps(method.to_payload(), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(f"{payload}\n{render_method(method)}".encode("utf-8")).hexdigest()


def test_every_shipped_method_version_keeps_its_fingerprint():
    for method in BUILTIN_METHODS:
        assert method.key in SHIPPED_FINGERPRINTS, (
            f"{method.key} : nouvelle version livrée, ajoutez son empreinte {fingerprint(method)} "
            "à SHIPPED_FINGERPRINTS (et gardez celle de la version précédente)")
        assert fingerprint(method) == SHIPPED_FINGERPRINTS[method.key], (
            f"{method.key} a changé de contenu sans changer de version : publiez la version "
            f"{method.version + 1} (docs/work-methods.md › Versions livrées), ne réécrivez jamais une version publiée")


def test_a_shipped_version_is_never_withdrawn_from_the_history_and_only_moves_forward():
    shipped = {}
    for key in SHIPPED_FINGERPRINTS:
        method_id, _, version = key.partition("@")
        shipped.setdefault(method_id, set()).add(int(version))
    for method in BUILTIN_METHODS:
        # La version livrée est la plus récente de l'historique : jamais un retour à une clé déjà publiée ailleurs.
        assert method.version == max(shipped[method.method_id])
    assert set(shipped) == {method.method_id for method in BUILTIN_METHODS}


def test_the_guard_catches_a_silent_text_change():
    """Mutation : un principe reformulé sous la même clé change l'empreinte, donc le test ci-dessus échoue."""

    from dataclasses import replace

    method = BUILTIN_METHODS[0]
    edited = replace(method, principles=(method.principles[0] + " ",) + method.principles[1:])
    assert edited.key == method.key and fingerprint(edited) != SHIPPED_FINGERPRINTS[method.key]
