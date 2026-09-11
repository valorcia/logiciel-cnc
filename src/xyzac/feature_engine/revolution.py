"""Detection des regions de revolution.

Prealable indispensable au choix fraisage / tournage / hybride (ADR-001 / D8).
La question n'est pas "y a-t-il des cylindres" mais : **existe-t-il un axe unique
autour duquel une part significative de la matiere est de revolution, et cet axe
est-il celui de l'axe C ?**

Un cylindre isole sur le flanc d'une piece prismatique est un percage, pas un
tournage. Confondre les deux proposerait de faire tourner la piece a 1500 tr/min
pour usiner un trou lateral — d'ou le cas C15 du corpus, dont le seul role est de
verifier que ce faux positif est bien rejete.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..geometry_core import brep
from ..geometry_core.types import normalize

#: Types de surface intrinsequement de revolution autour de leur axe propre.
REVOLUTION_TYPES = frozenset({"cylinder", "cone", "torus", "revolution"})


@dataclass
class RevolutionRegion:
    """Groupe de faces coaxiales autour d'un meme axe."""

    axis_point: np.ndarray
    axis_dir: np.ndarray
    face_indices: list[int]
    total_area: float
    max_radius: float
    #: Part de l'aire totale de la piece portee par ces faces.
    area_fraction: float

    def is_aligned_with(self, direction: np.ndarray, tol_deg: float = 1.0) -> bool:
        d = normalize(direction)
        c = abs(float(np.dot(normalize(self.axis_dir), d)))
        return c >= np.cos(np.radians(tol_deg))

    def describe(self) -> str:
        return (f"axe {np.round(self.axis_dir, 3)} passant par "
                f"{np.round(self.axis_point, 2)} : {len(self.face_indices)} faces, "
                f"{self.total_area:.0f} mm2 ({self.area_fraction * 100:.1f} % de la piece), "
                f"R_max {self.max_radius:.2f} mm")


def detect_revolution_regions(
    shape, *, angle_tol_deg: float = 1.0, dist_tol_mm: float = 0.05,
    min_area_fraction: float = 0.05,
) -> list[RevolutionRegion]:
    """Regroupe les faces de revolution par axe commun.

    Deux faces sont coaxiales si leurs axes sont paralleles ET si leurs lignes
    d'axe coincident. Tester le seul parallelisme est l'erreur classique : deux
    percages paralleles mais decales seraient declares coaxiaux, et la piece
    passerait pour tournable.
    """
    infos = brep.face_info(shape)
    total_area = sum(f.area for f in infos) or 1.0

    cands = [f for f in infos
             if f.surface_type in REVOLUTION_TYPES
             and f.axis_direction is not None and f.axis_location is not None]

    groups: list[dict] = []
    for f in cands:
        d = normalize(f.axis_direction)
        p = np.asarray(f.axis_location, dtype=np.float64)
        placed = False
        for g in groups:
            if abs(float(np.dot(d, g["dir"]))) < np.cos(np.radians(angle_tol_deg)):
                continue
            # Distance entre les deux lignes d'axe (paralleles) : composante de
            # (p - p_ref) orthogonale a l'axe.
            v = p - g["point"]
            if float(np.linalg.norm(v - np.dot(v, g["dir"]) * g["dir"])) > dist_tol_mm:
                continue
            g["faces"].append(f)
            placed = True
            break
        if not placed:
            groups.append({"dir": d, "point": p, "faces": [f]})

    out: list[RevolutionRegion] = []
    for g in groups:
        area = sum(f.area for f in g["faces"])
        frac = area / total_area
        if frac < min_area_fraction:
            continue  # detail local (un percage), pas une region de revolution
        out.append(RevolutionRegion(
            axis_point=g["point"], axis_dir=g["dir"],
            face_indices=sorted(f.index for f in g["faces"]),
            total_area=area, max_radius=max((f.radius or 0.0) for f in g["faces"]),
            area_fraction=frac,
        ))
    out.sort(key=lambda r: -r.total_area)
    return out
