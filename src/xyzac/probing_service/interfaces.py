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
    """Palpage d'origine piece sur la MACHINE REELLE.

    Les ajustements et la propagation d'incertitude sont implementes et
    verifies depuis le jalon M7 (``fitting``, ``simulator``). Ce qui manque
    n'est pas le calcul mais le mouvement : ``linuxcnc_gateway`` est verrouille.
    """
    raise NotImplementedError(
        "palpage d'origine sur machine reelle : linuxcnc_gateway est verrouille. "
        "Les ajustements sont disponibles et testes dans probing_service.fitting, "
        "et ProbeSimulator permet de les verifier sur le jumeau."
    )


def probe_tool_length(*args, **kw) -> ProbeResult:
    """Mesure de longueur d'outil sur la MACHINE REELLE. Voir ci-dessus."""
    raise NotImplementedError(
        "mesure de longueur d'outil sur machine reelle : linuxcnc_gateway est "
        "verrouille."
    )
