"""Consigne du CLI cerveau : rendu par l'arbre donné (main ad1e7f4d ou la branche S08), mêmes entrées que le
lancement réel du bac à sable (programme, modèle, contexte global du bac à sable). Usage :
  python -I s08_prompt_compare.py <arbre> <dossier CONTEXT_GLOBAL> <invocation> <modèle> <tendance|-> <sortie>
`-` : aucune variable `brain_delegation` (ce que main faisait)."""
import sys
from pathlib import Path

tree, context_dir, invocation, model, level, out = sys.argv[1:7]
sys.path.insert(0, tree)
from jarvis.adapters import global_context  # noqa: E402
from jarvis.domain.prompt_registry import PromptTarget  # noqa: E402
from jarvis.runtime.claude_local import cli_prompt_argument  # noqa: E402
from jarvis.runtime.prompt_runtime import prompt_channel, resolve_prompt  # noqa: E402

variables = {"global_context": global_context.load_global_context(Path(context_dir)).prompt_variable()}
if level != "-":
    variables["brain_delegation"] = level
resolution = resolve_prompt(PromptTarget("backend", None, "claude", model or None, None, invocation), overrides=None,
                            variables=variables)
text = cli_prompt_argument(prompt_channel(resolution, "cli.append_system_prompt"), "claude.exe")
Path(out).write_text(text, encoding="utf-8")
print(resolution.program_id, len(text))
