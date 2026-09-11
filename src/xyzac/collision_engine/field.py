"""Champ d'obstacles : nuage de points classe, avec garantie conservative.

Un obstacle n'est pas un booleen, c'est une CLASSE. La regle physique qui
gouverne tout le moteur :

  - le troncon de COUPE a le droit d'etre dans le BRUT (c'est l'usinage) ;
  - aucun troncon n'a le droit d'etre dans la PIECE FINIE (ce serait une gouge) ;
  - aucun troncon n'a le droit d'etre dans un BRIDAGE (ce serait une casse) ;
  - le col, la tige, le porte-outil et le nez de broche n'ont le droit d'etre
    nulle part dans la matiere.

Confondre ces classes est l'erreur qui fait declarer inaccessible toute surface
noyee dans le brut, ou a l'inverse valider un porte-outil qui laboure la piece.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

import numpy as np

from ..tool_model.assembly import SegmentRole


class ObstacleClass(IntEnum):
    PART = 0      # piece finie (+ surepaisseur de finition)
    STOCK = 1     # brut non encore enleve
    FIXTURE = 2   # bridage, mors, plateau
    MACHINE = 3   # organes machine (berceau, plateau, carters)


#: Qui a le droit de penetrer quoi. True = penetration TOLEREE.
PENETRATION_ALLOWED: dict[tuple[SegmentRole, ObstacleClass], bool] = {}
for _role in SegmentRole:
    for _cls in ObstacleClass:
        PENETRATION_ALLOWED[(_role, _cls)] = (
            _role is SegmentRole.CUTTING and _cls is ObstacleClass.STOCK
        )


@dataclass
class ObstacleField:
    """Obstacles echantillonnes en repere PIECE, prets pour un test vectorise.

    ``inflation`` est le rayon dont chaque point est grossi. Il vaut au minimum
    le pas d'echantillonnage : c'est ce qui rend le test discret **majorant** du
    test exact, donc conservatif (ADR-001 / D2). Le reduire sous le pas
    d'echantillonnage casserait la garantie et n'est pas autorise.
    """

    points: np.ndarray      # (N,3)
    classes: np.ndarray     # (N,) ObstacleClass
    inflation: np.ndarray   # (N,) rayon d'inflation par point, mm

    def __post_init__(self) -> None:
        self.points = np.ascontiguousarray(self.points, dtype=np.float64).reshape(-1, 3)
        self.classes = np.asarray(self.classes, dtype=np.int8).reshape(-1)
        self.inflation = np.asarray(self.inflation, dtype=np.float64).reshape(-1)
        n = self.points.shape[0]
        if not (self.classes.shape[0] == self.inflation.shape[0] == n):
            raise ValueError("ObstacleField : tailles points/classes/inflation incoherentes")

    def __len__(self) -> int:
        return int(self.points.shape[0])

    @staticmethod
    def build(
        part_points: np.ndarray,
        *,
        part_spacing: float,
        finish_allowance: float = 0.0,
        stock_points: np.ndarray | None = None,
        stock_spacing: float = 0.0,
        fixture_points: np.ndarray | None = None,
        fixture_spacing: float = 0.0,
        fixture_keepout: float = 0.0,
        safety_clearance: float = 0.5,
    ) -> "ObstacleField":
        """Assemble un champ a partir des trois sources, avec leurs marges propres.

        ``safety_clearance`` s'ajoute a l'inflation d'echantillonnage. C'est la
        marge de securite pilotable par l'utilisateur ; l'inflation
        d'echantillonnage, elle, n'est pas negociable.
        """
        pts, cls, inf = [], [], []

        pp = np.asarray(part_points).reshape(-1, 3)
        pts.append(pp)
        cls.append(np.full(len(pp), ObstacleClass.PART))
        inf.append(np.full(len(pp), part_spacing + finish_allowance + safety_clearance))

        if stock_points is not None and len(stock_points):
            sp = np.asarray(stock_points).reshape(-1, 3)
            pts.append(sp)
            cls.append(np.full(len(sp), ObstacleClass.STOCK))
            inf.append(np.full(len(sp), stock_spacing + safety_clearance))

        if fixture_points is not None and len(fixture_points):
            fp = np.asarray(fixture_points).reshape(-1, 3)
            pts.append(fp)
            cls.append(np.full(len(fp), ObstacleClass.FIXTURE))
            inf.append(np.full(len(fp), fixture_spacing + fixture_keepout + safety_clearance))

        return ObstacleField(np.vstack(pts), np.concatenate(cls), np.concatenate(inf))

    def subset_near(self, center: np.ndarray, radius: float) -> "ObstacleField":
        """Restreint le champ a une sphere. Pre-filtre O(N) avant le test fin.

        Sans cela, chaque orientation testee balaierait tout le nuage ; avec, on
        ne garde que ce que l'outil peut physiquement atteindre depuis ce point.
        """
        d2 = np.sum((self.points - np.asarray(center)) ** 2, axis=1)
        m = d2 <= radius * radius
        return ObstacleField(self.points[m], self.classes[m], self.inflation[m])
