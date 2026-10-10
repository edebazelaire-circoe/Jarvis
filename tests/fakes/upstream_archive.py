"""Archives `tar.gz` façon GitHub `codeload` pour les tests de l'importeur amont (Slice 18) : racine `<dépôt>-<sha>/`, en-tête pax
global dont le `comment` est le SHA du commit (c'est ce que GitHub écrit), et des variantes hostiles (lien, `..`, doublon...)."""

from __future__ import annotations

import gzip
import io
import tarfile
from typing import Mapping

SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
MIT = """MIT License

Copyright (c) 2026 Example Authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
"""
GPL = "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n\nEveryone is permitted to copy and distribute verbatim copies\n"
REMOTION_LICENCE = "Remotion License\n\nNote that for some entities a company license is needed.\n"

PACKAGE = '{"name": "demo", "license": "MIT", "dependencies": {"react": "^19.0.0", "remotion": "4.0.499", "react-dom": "^19.0.0", "zod": "4.0.0", "@remotion/cli": "^4.0.0"}}'
ROOT_TSX = """import React from 'react';
import {Composition} from 'remotion';
import {Demo} from './Demo';
import {defaults} from './defaults';
import {z} from 'zod';

export const Root: React.FC = () => (
  <Composition id="DemoScene" component={Demo} durationInFrames={90} fps={30} width={1280} height={720}
    // comment: <Composition id="Ghost" />
    defaultProps={{title: "Hello", palette: defaults}} />
);
"""
DEMO_TSX = """import React from 'react';
import {AbsoluteFill, Img, staticFile, useCurrentFrame} from 'remotion';
import {Badge} from './lib/Badge';

export const Demo = ({title, palette}: {title: string; palette: {bg: string}}) => {
  const frame = useCurrentFrame();
  return (<AbsoluteFill style={{background: palette.bg}}><Badge text={title + frame} />
    <Img src={staticFile("logo.png")} /></AbsoluteFill>);
};
"""
BADGE_TSX = "import React from 'react';\nexport const Badge = ({text}: {text: string}) => <b>{text}</b>;\n"
DEFAULTS_TS = "export const defaults = {bg: '#101820'};\n"
UNUSED_TS = "import {z} from 'zod';\nexport const schema = z.object({});\n"
INDEX_TS = "import {registerRoot} from 'remotion';\nimport {Root} from './Root';\nregisterRoot(Root);\n"
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c63f8cfc0f01f0005000100ffab3a8dc8000000004945"
                    "4e44ae426082")


def good_project() -> dict[str, str | bytes]:
    return {"LICENSE": MIT, "package.json": PACKAGE, "README.md": "# demo\n", "remotion.config.ts": "export {};\n",
            "src/Root.tsx": ROOT_TSX, "src/Demo.tsx": DEMO_TSX, "src/lib/Badge.tsx": BADGE_TSX, "src/defaults.ts": DEFAULTS_TS,
            "src/unused.ts": UNUSED_TS, "src/index.ts": INDEX_TS, "public/logo.png": PNG, "public/unused.mp4": b"\x00\x00\x00\x18ftypmp42"}


def make_tarball(files: Mapping[str, str | bytes], *, sha: str = SHA, repo: str = "demo", comment: str | None = None,
                 extra: list[tarfile.TarInfo] | None = None, extra_data: Mapping[str, bytes] | None = None, root: str | None = None,
                 raw_names: Mapping[str, bytes] | None = None) -> bytes:
    """`files` : chemins relatifs à la racine du dépôt. `extra` : membres spéciaux (liens...) ajoutés tels quels."""

    top = root if root is not None else f"{repo}-{sha}"
    buffer = io.BytesIO()
    pax = {} if comment == "" else {"comment": comment if comment is not None else sha}
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT, pax_headers=pax) as archive:
        folder = tarfile.TarInfo(top + "/")
        folder.type = tarfile.DIRTYPE
        archive.addfile(folder)
        for path, body in files.items():
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            info = tarfile.TarInfo(f"{top}/{path}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        for info in extra or []:
            archive.addfile(info, io.BytesIO(b"") if info.isreg() else None)
        for name, data in (extra_data or {}).items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return gzip.compress(buffer.getvalue(), mtime=0)


def link(name: str, target: str, *, hard: bool = False) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = tarfile.LNKTYPE if hard else tarfile.SYMTYPE
    info.linkname = target
    return info
