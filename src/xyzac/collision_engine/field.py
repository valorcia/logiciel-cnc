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
from .spatial import UniformGrid


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

    #: En deca de cette fraction du volume de la scene, la requete est assez
    #: selective pour que l'index spatial soit rentable. Au-dela, la sphere
    #: couvre presque tout le nuage et le balayage direct est plus rapide que
    #: la visite des cellules. Mesure a l'appui : sur une piece plus petite que
    #: la portee de l'outil, l'index ne gagne rien (x1,5 au mieux) ; il devient
    #: decisif des que la piece est grande devant l'outil.
    INDEX_VOLUME_FRACTION = 0.15

    def _grid(self, cell_size: float) -> UniformGrid:
        cached = getattr(self, "_grid_cache", None)
        if cached is not None and abs(cached.cell_size - cell_size) < 1e-9:
            return cached
        g = UniformGrid(self.points, cell_size)
        object.__setattr__(self, "_grid_cache", g)
        return g

    def _scene_volume(self) -> float:
        cached = getattr(self, "_vol_cache", None)
        if cached is None:
            span = self.points.max(axis=0) - self.points.min(axis=0) if len(self) else np.zeros(3)
            cached = float(np.prod(np.maximum(span, 1e-6)))
            object.__setattr__(self, "_vol_cache", cached)
        return cached

    def subset_near(self, center: np.ndarray, radius: float) -> "ObstacleField":
        """Restreint le champ a une sphere.

        Deux strategies, choisies sur un critere mesurable plutot que par
        principe : index spatial quand la requete est selective, balayage
        direct sinon. Dans les deux cas le filtrage par distance est EXACT —
        l'index ne fait que reduire l'ensemble candidat, jamais l'ensemble
        retourne, sans quoi la garantie conservative en amont tomberait.
        """
        if len(self) == 0:
            return self

        sphere_vol = 4.18879 * radius ** 3
        if sphere_vol < self.INDEX_VOLUME_FRACTION * self._scene_volume():
            idx = self._grid(max(radius, 1e-3)).query_ball(center, radius)
            return ObstacleField(self.points[idx], self.classes[idx], self.inflation[idx])

        d2 = np.sum((self.points - np.asarray(center)) ** 2, axis=1)
        m = d2 <= radius * radius
        return ObstacleField(self.points[m], self.classes[m], self.inflation[m])

    def subset_capsule(self, p0: np.ndarray, p1: np.ndarray, radius: float) -> "ObstacleField":
        """Restreint le champ au voisinage d'un SEGMENT.

        Requete du test de balayage : entre deux poses, l'outil parcourt un
        volume allonge. Une sphere englobant ce volume retournerait presque tout
        le nuage des que le deplacement depasse quelques millimetres.
        """
        if len(self) == 0:
            return self
        idx = self._grid(max(radius, 1e-3)).query_capsule(p0, p1, radius)
        return ObstacleField(self.points[idx], self.classes[idx], self.inflation[idx])
