"""Ré-exportation des doubles de périphérique, désormais dans le produit.

Slice 06 (Category 2 Test Lab) les a déplacés dans
`jarvis/testlab/virtual/devices.py` : le harnais de conversation asynchrone est
devenu le profil `virtual` du Test Lab, donc du code produit, et le code produit
ne peut pas importer `tests.`. Même classes, même comportement.
"""

from __future__ import annotations

from jarvis.testlab.virtual.devices import BufferedInputStream, BufferedOutputStream

__all__ = ["BufferedInputStream", "BufferedOutputStream"]
