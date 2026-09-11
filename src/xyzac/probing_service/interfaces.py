"""Palpage : mesure de l'origine piece, du brut et des outils.

Toute mesure retournee porte son INCERTITUDE. Une origine palpee sans
incertitude associee donne une fausse confiance, et c'est exactement le genre
de fausse confiance qui fait annoncer une precision qu'on n'a pas mesuree.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ProbeResult:
    name: str
    value_mm: np.ndarray
    uncertainty_mm: float
    n_samples: int
    accepted: bool
    detail: str = ""


def probe_work_offset(*args, **kw) -> ProbeResult:
    raise NotImplementedError(
        "probing_service non implemente au jalon M1 : le palpage exige des "
        "mouvements reels, donc les portes de securite (ADR-001 §6)."
    )


def probe_tool_length(*args, **kw) -> ProbeResult:
    raise NotImplementedError("probing_service non implemente au jalon M1")
