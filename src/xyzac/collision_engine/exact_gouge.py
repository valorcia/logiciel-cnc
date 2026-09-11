"""Verification EXACTE de gouge, par requetes de distance sur le B-Rep.

Limite reconnue au jalon M1 : le test par nuage de points a une resolution
bornee par le pas d'echantillonnage (typiquement 2 mm). Il garantit qu'aucun
organe non coupant ne penetre la matiere, mais il ne peut rien dire d'une gouge
de quelques centiemes — precisement l'ordre de grandeur qui decide qu'une piece
est bonne ou rebutee.

Ce module comble l'ecart avec l'outil adapte : ``BRepExtrema_DistShapeShape``,
qui calcule la distance exacte entre deux formes OCCT, sans discretisation.

**Pourquoi ne pas s'en servir partout** : une requete exacte coûte des ordres de
grandeur de plus qu'un test vectorise sur nuage. L'utiliser pour explorer des
centaines d'orientations par point serait intenable. La repartition des roles
est donc :

  - nuage de points : EXPLORATION, sur toutes les orientations candidates ;
  - B-Rep exact     : VERIFICATION, sur les poses finalement retenues.

C'est le meme principe que la programmation dynamique suivie d'un raffinement
continu : on cherche large et grossier, on conclut fin et exact.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCone, BRepPrimAPI_MakeCylinder
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

from ..geometry_core.types import orthonormal_basis
from ..tool_model.assembly import SegmentRole, ToolAssembly


@dataclass
class GougeResult:
    """Verdict exact en une pose."""

    index: int
    gouge_volume_mm3: float
    min_distance_mm: float
    role: str
    ok: bool

    def describe(self) -> str:
        if self.ok:
            return (f"pose {self.index} : pas de gouge "
                    f"(distance {self.min_distance_mm:.4f} mm)")
        return (f"pose {self.index} : GOUGE de {self.gouge_volume_mm3:.4f} mm3 "
                f"par le troncon '{self.role}'")


def _segment_solid(seg, tcp: np.ndarray, axis: np.ndarray):
    """Construit le solide OCCT d'un troncon place (cylindre ou cone tronque)."""
    u, v, d = orthonormal_basis(axis)
    base = np.asarray(tcp, float) + d * seg.z_start
    ax2 = gp_Ax2(gp_Pnt(*base), gp_Dir(*d), gp_Dir(*u))
    if abs(seg.r_start - seg.r_end) < 1e-9:
        if seg.r_start < 1e-9:
            return None
        return BRepPrimAPI_MakeCylinder(ax2, float(seg.r_start), float(seg.length)).Shape()
    return BRepPrimAPI_MakeCone(ax2, float(seg.r_start), float(seg.r_end),
                                float(seg.length)).Shape()


def _volume(shape) -> float:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return float(props.Mass())


def verify_gouge_exact(
    part_shape,
    tool: ToolAssembly,
    tcp: np.ndarray,
    axis: np.ndarray,
    *,
    index: int = 0,
    cutting_depth: float = 0.0,
    tolerance_mm: float = 0.01,
    include_cutting: bool = False,
) -> GougeResult:
    """Verifie exactement si l'outil place penetre la piece FINALE.

    ``include_cutting=False`` (defaut) exclut l'arete de coupe : en fraisage de
    flanc elle est tangente a la face par construction, et l'inclure
    signalerait une gouge a chaque passe. Elle est verifiee separement, au-dela
    de ``cutting_depth``, la ou sa presence n'est plus voulue.

    ``tolerance_mm`` : en deca de ce volume d'intersection, on considere qu'il
    s'agit du contact tangentiel normal et non d'une gouge. Un booleen OCCT sur
    deux surfaces tangentes produit toujours un residu numerique minuscule ;
    exiger un volume strictement nul rendrait le test inutilisable.
    """
    worst_vol, worst_role = 0.0, ""
    min_dist = np.inf

    for seg in tool.segments:
        if seg.role is SegmentRole.CUTTING and not include_cutting:
            # L'arete n'est verifiee qu'au-dela de la zone de prise volontaire.
            if seg.z_end <= cutting_depth:
                continue
            seg = seg.model_copy(update={"z_start": max(seg.z_start, cutting_depth)})
            if seg.z_end - seg.z_start < 1e-6:
                continue

        solid = _segment_solid(seg, tcp, axis)
        if solid is None:
            continue

        dist = BRepExtrema_DistShapeShape(solid, part_shape)
        if dist.IsDone():
            min_dist = min(min_dist, float(dist.Value()))
            if dist.Value() > 1e-9:
                continue  # separes : aucun booleen a calculer

        common = BRepAlgoAPI_Common(solid, part_shape)
        if not common.IsDone():
            continue
        vol = _volume(common.Shape())
        if vol > worst_vol:
            worst_vol, worst_role = vol, seg.role.value

    return GougeResult(
        index=index, gouge_volume_mm3=worst_vol,
        min_distance_mm=float(min_dist) if np.isfinite(min_dist) else np.inf,
        role=worst_role, ok=worst_vol <= tolerance_mm,
    )


def verify_plan_sparse(
    part_shape, tool: ToolAssembly, tcps: np.ndarray, axes: np.ndarray,
    *, n_samples: int = 12, cutting_depth: float = 0.0, tolerance_mm: float = 0.01,
) -> list[GougeResult]:
    """Verifie exactement un ECHANTILLON des poses d'une trajectoire.

    Le cout exact interdit de tout verifier. On echantillonne donc
    regulierement, et le resultat doit etre lu pour ce qu'il est : **un
    sondage**, pas une preuve d'absence de gouge sur toute la passe. Une gouge
    detectee ici est certaine ; une absence de gouge ici ne prouve rien entre
    les echantillons.

    C'est la raison pour laquelle ce verificateur ne peut pas, seul, lever le
    verrou du post-processeur.
    """
    tcps = np.asarray(tcps, float).reshape(-1, 3)
    axes = np.asarray(axes, float).reshape(-1, 3)
    n = len(tcps)
    idx = np.unique(np.linspace(0, n - 1, min(n_samples, n)).astype(int))
    return [verify_gouge_exact(part_shape, tool, tcps[i], axes[i], index=int(i),
                               cutting_depth=cutting_depth, tolerance_mm=tolerance_mm)
            for i in idx]
