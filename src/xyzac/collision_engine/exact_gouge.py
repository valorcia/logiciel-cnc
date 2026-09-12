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
    roles: "frozenset[SegmentRole] | None" = None,
) -> GougeResult:
    """Verifie exactement si l'outil place penetre la piece FINALE.

    ``roles`` restreint la verification a certains roles de troncons. Utile
    parce que les deux physiques en jeu ne se verifient pas de la meme facon :
    un troncon non coupant doit garder une distance, l'arete de coupe est
    tangente par construction. Voir ``certify_plan_exact``.

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
        if roles is not None and seg.role not in roles:
            continue
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


# ---------------------------------------------------------------------------
# Du SONDAGE a la PREUVE
# ---------------------------------------------------------------------------


@dataclass
class UncertifiedInterval:
    """Portion de passe qu'aucune requete exacte n'a pu couvrir."""

    i0: int
    i1: int
    clearance_mm: float          # meilleure garde mesuree aux deux bouts
    displacement_mm: float       # majorant du deplacement sur l'intervalle

    def describe(self) -> str:
        return (f"poses {self.i0}->{self.i1} : garde {self.clearance_mm:.4f} mm "
                f"pour un deplacement majore par {self.displacement_mm:.4f} mm")


@dataclass
class GougeCertificate:
    """Verdict de gouge sur une passe ENTIERE, et ce qui le fonde.

    Deux volets, parce qu'il y a deux physiques (voir ``certify_plan_exact``) :

      - ``holder_proven`` : aucun troncon NON COUPANT ne touche la piece, sur
        tout le parcours et non aux seules poses testees. C'est une preuve.
      - ``cutting_tested`` : l'arete de coupe a ete verifiee en CHAQUE pose.
        C'est exhaustif sur les poses, mais muet entre deux poses.

    ``complete`` exige les deux, et l'absence d'echec.
    """

    n_poses: int
    n_queries_holder: int
    n_queries_cutting: int
    n_intervals_certified: int
    min_clearance_mm: float
    holder_proven: bool = False
    cutting_tested: bool = False
    failures: list[GougeResult] = None
    uncertified: list[UncertifiedInterval] = None

    def __post_init__(self):
        self.failures = self.failures or []
        self.uncertified = self.uncertified or []

    @property
    def n_exact_queries(self) -> int:
        return self.n_queries_holder + self.n_queries_cutting

    @property
    def complete(self) -> bool:
        return (self.holder_proven and self.cutting_tested
                and not self.failures and not self.uncertified)

    def describe(self) -> str:
        head = (f"{self.n_poses} poses ; {self.n_queries_holder} requetes pour le "
                f"porte-outil ({self.n_intervals_certified} intervalles certifies, "
                f"garde minimale {self.min_clearance_mm:.4f} mm), "
                f"{self.n_queries_cutting} pour l'arete")
        if self.complete:
            return ("PROUVE : aucun troncon non coupant ne touche la piece sur "
                    f"tout le parcours, arete verifiee en chaque pose — {head}")
        lines = [f"NON PROUVE — {head}"]
        if not self.holder_proven:
            lines.append("   le porte-outil n'est pas couvert sur tout le parcours")
        if not self.cutting_tested:
            lines.append("   l'arete n'a pas ete verifiee en toutes les poses")
        for f in self.failures[:5]:
            lines.append("   gouge : " + f.describe())
        for u in self.uncertified[:5]:
            lines.append("   non couvert : " + u.describe())
        more = (len(self.failures) + len(self.uncertified)) - 10
        if more > 0:
            lines.append(f"   ... et {more} autres")
        return "\n".join(lines)


#: Troncons qui ne doivent JAMAIS toucher la piece finale. L'arete de coupe en
#: est exclue : elle est tangente a la surface par construction en finition, et
#: elle traverse la surepaisseur en ebauche. Ce sont deux physiques distinctes,
#: et les confondre rend toute majoration par distance vide de contenu.
NON_CUTTING_ROLES = frozenset({
    SegmentRole.FLUTE, SegmentRole.NECK, SegmentRole.SHANK,
    SegmentRole.HOLDER, SegmentRole.SPINDLE_NOSE,
})


def certify_plan_exact(
    part_shape,
    tool: ToolAssembly,
    tcps: np.ndarray,
    axes: np.ndarray,
    *,
    cutting_depth: float = 0.0,
    tolerance_mm: float = 0.01,
    max_queries: int = 4000,
    check_cutting: bool = True,
) -> GougeCertificate:
    """Verifie la gouge sur TOUTE la passe, et non sur un echantillon.

    ``verify_plan_sparse`` teste douze poses et ne peut rien dire des autres.
    Mesure de ce que cela laisse passer : une pose sur 200 enfoncee de 4 mm dans
    un bloc (113 mm3 de gouge) n'est **pas vue** par le sondage, et l'est ici.

    **Deux physiques, deux methodes.** C'est le point de conception, et l'avoir
    manque une premiere fois rendait ce certificat vide :

    *Troncons non coupants* (col, tige, porte-outil, nez de broche). Ils doivent
    garder une distance a la piece, donc une majoration suffit :

      - une requete exacte en la pose ``i`` rend la garde ``d_i``, distance
        minimale entre ces troncons places et la piece finale ;
      - tout point de l'outil se deplace d'au plus
        ``|Dtcp| + reach . angle(axe_i, axe_j)`` entre deux poses (majorant
        strict, demontre dans ``SweepChecker.displacement_bound``) ;
      - donc si le deplacement cumule de ``i`` a ``j`` reste sous ``d_i``,
        **aucune pose de l'intervalle ne peut toucher la piece** : l'intervalle
        est certifie sans qu'on y calcule quoi que ce soit.

    Le nombre de requetes n'est donc pas proportionnel au nombre de poses mais
    au rapport longueur de passe / garde disponible. C'est ce qui rend la preuve
    abordable la ou le test exhaustif ne l'est pas.

    *Arete de coupe*. Elle est tangente a la surface par construction : sa
    distance a la piece est nulle en finition, et une majoration par la distance
    n'y a aucun contenu — elle rendrait « non prouve » sur toute passe reelle.
    Elle est donc verifiee **en chaque pose**, par test de volume, ce qui reste
    abordable parce qu'elle ne compte qu'un ou deux troncons.

    **Ce que le certificat ne prouve pas**, et qui doit rester dit : pour
    l'arete, rien entre deux poses consecutives. Le majorant de deplacement est
    trop grossier pour cela (il borne le mouvement de tout point de l'outil par
    ``reach . angle``, alors que l'arete, elle, suit la surface). Resserrer
    cela demande une enveloppe balayee exacte, qui n'est pas faite.

    ``max_queries`` borne le budget du volet porte-outil. L'epuiser rend un
    certificat **incomplet**, jamais optimiste : les intervalles non couverts
    sont nommes avec leur position.
    """
    from .tool_collision import ToolCollisionChecker

    tcps = np.asarray(tcps, float).reshape(-1, 3)
    axes = np.asarray(axes, float).reshape(-1, 3)
    n = len(tcps)
    if n == 0:
        return GougeCertificate(0, 0, 0, 0, float("inf"),
                                holder_proven=True, cutting_tested=True)

    reach = ToolCollisionChecker(tool).reach

    def bound(t0, a0, t1, a1) -> float:
        dt = float(np.linalg.norm(t1 - t0))
        u0 = a0 / np.linalg.norm(a0)
        u1 = a1 / np.linalg.norm(a1)
        ang = float(np.arctan2(float(np.linalg.norm(np.cross(u0, u1))), float(u0 @ u1)))
        return dt + reach * ang

    failures: list[GougeResult] = []
    cache: dict[int, GougeResult] = {}
    n_holder = 0

    def probe(i: int) -> GougeResult:
        nonlocal n_holder
        r = cache.get(i)
        if r is None:
            r = verify_gouge_exact(part_shape, tool, tcps[i], axes[i], index=i,
                                   cutting_depth=cutting_depth,
                                   tolerance_mm=tolerance_mm,
                                   roles=NON_CUTTING_ROLES)
            cache[i] = r
            n_holder += 1
            if not r.ok:
                failures.append(r)
        return r

    # -- volet 1 : porte-outil, par majoration ---------------------------
    certified = 0
    uncertified: list[UncertifiedInterval] = []
    min_clear = float("inf")
    i = 0

    while i < n - 1:
        if n_holder >= max_queries:
            uncertified.append(UncertifiedInterval(
                i, n - 1, float("nan"),
                float(sum(bound(tcps[k], axes[k], tcps[k + 1], axes[k + 1])
                          for k in range(i, n - 1)))))
            break

        d = probe(i).min_distance_mm
        min_clear = min(min_clear, d)

        # Avance tant que le deplacement cumule reste STRICTEMENT sous la garde.
        acc, j = 0.0, i
        while j < n - 1:
            step = bound(tcps[j], axes[j], tcps[j + 1], axes[j + 1])
            if acc + step >= d:
                break
            acc += step
            j += 1

        if j > i:
            certified += 1
            i = j
            continue

        # Un seul pas suffit a depasser la garde en ``i``. La borne etant
        # symetrique, la garde en ``i+1`` peut encore couvrir l'intervalle.
        step = bound(tcps[i], axes[i], tcps[i + 1], axes[i + 1])
        d1 = probe(i + 1).min_distance_mm
        min_clear = min(min_clear, d1)
        if step < max(d, d1):
            certified += 1
            i += 1
            continue

        # Ni l'un ni l'autre : on bissecte l'intervalle geometriquement.
        if _certify_between(part_shape, tool, tcps[i], axes[i], tcps[i + 1],
                            axes[i + 1], max(d, d1), bound, cutting_depth,
                            tolerance_mm):
            certified += 1
        else:
            uncertified.append(UncertifiedInterval(i, i + 1, max(d, d1), step))
        i += 1

    if n == 1:
        min_clear = probe(0).min_distance_mm

    # -- volet 2 : arete de coupe, en CHAQUE pose ------------------------
    n_cut = 0
    if check_cutting:
        cut_roles = frozenset({SegmentRole.CUTTING})
        has_cutting = any(sg.role is SegmentRole.CUTTING for sg in tool.segments)
        for k in range(n):
            if not has_cutting:
                break
            r = verify_gouge_exact(part_shape, tool, tcps[k], axes[k], index=k,
                                   cutting_depth=cutting_depth,
                                   tolerance_mm=tolerance_mm,
                                   roles=cut_roles)
            n_cut += 1
            if not r.ok:
                failures.append(r)

    return GougeCertificate(
        n_poses=n, n_queries_holder=n_holder, n_queries_cutting=n_cut,
        n_intervals_certified=certified, min_clearance_mm=min_clear,
        holder_proven=not uncertified, cutting_tested=bool(check_cutting),
        failures=failures, uncertified=uncertified,
    )


def _certify_between(part_shape, tool, t0, a0, t1, a1, clearance, bound,
                     cutting_depth, tolerance_mm, depth: int = 0) -> bool:
    """Bissecte un intervalle non couvert par ses deux bouts.

    Interpole geometriquement (milieu du segment, axe median normalise). Ce
    n'est PAS l'interpolation du controleur — ``SweepChecker.interpolate`` la
    reproduit — mais la majoration employee ici ne suppose rien de la
    trajectoire suivie : elle borne le deplacement de tout point de l'outil
    entre deux poses quelconques. La bissection reste donc valide.

    Elle termine parce que le majorant est divise par deux a chaque etage. Elle
    ne termine PAS quand la garde tend elle-meme vers zero, c'est-a-dire quand
    le porte-outil frole reellement la piece. Ce n'est pas un echec de
    l'algorithme mais sa reponse, et ``depth`` la borne.
    """
    if depth >= 6:
        return False
    tm = 0.5 * (t0 + t1)
    am = a0 + a1
    nrm = float(np.linalg.norm(am))
    am = (a0 if nrm < 1e-9 else am / nrm)

    res = verify_gouge_exact(part_shape, tool, tm, am, index=-1,
                             cutting_depth=cutting_depth,
                             tolerance_mm=tolerance_mm, roles=NON_CUTTING_ROLES)
    if not res.ok:
        return False
    dm = res.min_distance_mm
    for (u0, ua, u1, ub) in ((t0, a0, tm, am), (tm, am, t1, a1)):
        step = bound(u0, ua, u1, ub)
        if step < max(dm, clearance):
            continue
        if not _certify_between(part_shape, tool, u0, ua, u1, ub,
                                max(dm, clearance), bound, cutting_depth,
                                tolerance_mm, depth + 1):
            return False
    return True
