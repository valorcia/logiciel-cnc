"""Profils : matieres, outils, recettes de coupe.

Inspiration UX assumee des slicers 3D (ADR-001 / D10) : l'utilisateur choisit
une matiere et une qualite, pas des parametres de coupe. Inspiration UX
seulement — Orca et Prusa sont AGPL-3.0, on regarde leur interface, pas leur
code.

Les valeurs livrees seront des POINTS DE DEPART conservateurs, jamais des
garanties : sur une machine en kit, la rigidite depend de l'assemblage de
l'acheteur. Une recette qui suppose une broche parfaitement rigide casse des
outils chez l'utilisateur.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Quality(str, Enum):
    ROUGHING = "ebauche"
    BALANCED = "equilibre"
    FINISH = "finition"


@dataclass
class MaterialProfile:
    name: str
    surface_speed_m_min: float
    feed_per_tooth_mm: float
    max_depth_ratio: float   # x diametre
    max_width_ratio: float   # x diametre
    source: str = "point de depart conservateur, NON qualifie sur machine"


@dataclass
class CuttingRecipe:
    spindle_rpm: float
    feed_mm_min: float
    depth_of_cut_mm: float
    width_of_cut_mm: float
    derived_from: str


def build_recipe(material: MaterialProfile, tool, quality: Quality) -> CuttingRecipe:
    raise NotImplementedError(
        "recipe_profiles non implemente au jalon M1. Les valeurs doivent etre "
        "qualifiees sur machine reelle avant d'etre proposees a un utilisateur."
    )
