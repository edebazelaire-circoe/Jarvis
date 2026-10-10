"""Manifeste de la capacité locale Remotion (handoff jarvis-remotion-presentation-integration, Slice 04).

Source unique des versions épinglées. `jarvis/capabilities/remotion/package.json`
et `package-lock.json` les répètent pour npm ; `tests/unit/test_remotion_capability.py`
échoue si l'un des trois diverge. Pour changer de version : modifier ici,
régénérer le verrou (`docs/remotion-runtime.md` §7), puis `update` explicite.

Pur : aucune E/S.
"""

from __future__ import annotations

from jarvis.domain.local_capabilities import CapabilityManifest, new_manifest

REMOTION_CAPABILITY_ID = "remotion"
REMOTION_VERSION = "4.0.534"
REACT_VERSION = "19.3.0"
#: `remotion` (cœur), `@remotion/player` (aperçu embarqué), `@remotion/cli` (Studio, rendu), `@remotion/bundler`
#: (compile le TSX pour le navigateur : source du bundle du Player), `react` / `react-dom` (pairs requis).
REMOTION_COMPONENTS = {
    "@remotion/bundler": REMOTION_VERSION,
    "@remotion/cli": REMOTION_VERSION,
    "@remotion/player": REMOTION_VERSION,
    "react": REACT_VERSION,
    "react-dom": REACT_VERSION,
    "remotion": REMOTION_VERSION,
}
#: Plus haut `engines.node` du verrou : 18.12 (`@rspack/core`) ; Node 18 est en fin de vie, on exige 20.
NODE_MINIMUM = "20.0.0"
NPM_MINIMUM = "9.0.0"
#: Plateformes pour lesquelles le verrou porte les binaires natifs de Remotion (compositor) ET du bundler (rspack).
SUPPORTED_PLATFORMS = frozenset({"win32-x64", "darwin-x64", "darwin-arm64", "linux-x64", "linux-arm64"})


def remotion_manifest() -> CapabilityManifest:
    return new_manifest(capability_id=REMOTION_CAPABILITY_ID, display_name="Remotion", components=REMOTION_COMPONENTS,
                        requirements=[("node", NODE_MINIMUM)], entrypoint="main")
