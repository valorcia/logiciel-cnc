"""Slicer soustractif : decoupe du volume ``brut \\ piece`` en couches usinables.

C'est l'analogue soustractif du slicing additif, mais l'analogie s'arrete tot et
il vaut mieux le dire : en additif la couche est POSEE et rien ne s'oppose a
l'outil ; en soustractif la couche est ENLEVEE, l'outil doit y entrer, et son
corps doit y tenir. Une couche n'est donc pas seulement une tranche geometrique,
c'est une tranche ACCESSIBLE.

NON IMPLEMENTE au jalon M1. Prerequis : suivi de matiere enlevee dans
``stock_engine`` (aujourd'hui le brut est traite comme intact, hypothese
conservative mais inutilisable pour de l'ebauche multi-passes).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class LayerMode(str, Enum):
    PLANAR_Z = "planaire_z"          # couches planes, cas 3 axes classique
    PLANAR_INDEXED = "planaire_indexee"  # couches planes dans un plan A/C indexe
    CONFORMAL = "conforme"           # couches suivant la surface (analogue courbe)


@dataclass
class RemovalLayer:
    """Une couche de matiere a enlever."""

    index: int
    mode: LayerMode
    reference_dir: np.ndarray
    depth: float
    boundary: np.ndarray | None = None
    residual_volume_mm3: float = 0.0


def slice_removal_volume(stock, part_shape, tool, mode: LayerMode = LayerMode.PLANAR_Z):
    raise NotImplementedError(
        "subtractive_slicer non implemente au jalon M1.\n"
        "Prerequis : (1) suivi de matiere enlevee (dexel/voxel) dans stock_engine ; "
        "(2) booleens de volume robustes sur B-Rep degrade. "
        "Le mode CONFORMAL n'est envisage qu'apres validation des deux precedents."
    )
