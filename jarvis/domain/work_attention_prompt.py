"""Consigne du tour de réveil ouvert par un changement de travail de fond.

Ce texte n'est pas une parole : il n'est jamais prononcé. C'est la consigne
interne du tour que Core ouvre de lui-même quand un travail d'arrière-plan
change d'état sans que l'utilisateur ait rien demandé — un sous-agent qui
échoue, un hôte qui disparaît, un travail qui attend une réponse.

La règle de Core reste entière (Décision 14) : il ne fabrique aucune phrase
publique. Il ouvre un tour et laisse le cerveau choisir ses mots, ou se taire
par la réponse convenue. Le détail du changement, lui, ne passe pas par ici :
il arrive dans le contexte de travail du tour (`BrainWorkContext.attention`),
que `build_brain_work_context` borne déjà.

Il vit dans `jarvis/domain` parce que Core l'utilise et n'importe jamais
`jarvis/runtime` ; il est déclaré au catalogue de prompts
(`jarvis/runtime/prompt_catalog.py`) comme tout matériel visible du modèle.
"""

from __future__ import annotations

from jarvis.domain.v2 import BRAIN_NOT_ADDRESSED_ANSWER

WORK_ATTENTION_WAKE_PROMPT = f"""\
Un ou plusieurs travaux d'arrière-plan viennent de changer d'état sans que \
l'utilisateur l'ait demandé : échec, interruption, ou attente d'une réponse de \
sa part. Le détail est dans ton contexte de travail, section « attention ». \
Personne ne t'a parlé : c'est toi qui prends la parole.

Dis à l'utilisateur, en une ou deux phrases orales, ce qui s'est passé et ce \
que tu proposes — relancer, corriger, ou attendre sa décision. Si le travail \
attendait une réponse, pose-lui la question. Ne relance rien de toi-même dans \
ce tour : annonce d'abord.

Si ce changement ne mérite aucune annonce, réponds exactement \
{BRAIN_NOT_ADDRESSED_ANSWER} et rien d'autre : rien ne sera dit.\
"""
