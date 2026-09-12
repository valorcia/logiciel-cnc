"""Ajustements geometriques sur des points palpes.

Toutes les fonctions de ce module rendent une mesure ET son residu. Un
ajustement sans residu ne dit pas s'il a reussi : une sphere ajustee sur des
points qui ne sont pas sur une sphere rend quand meme un centre, et ce centre
a l'air d'une mesure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..geometry_core.types import normalize


@dataclass
class SphereFit:
    centre: np.ndarray
    radius_mm: float
    residual_rms_mm: float
    n_points: int


@dataclass
class AxisFit:
    """Axe de rotation deduit du deplacement d'un point sous rotation.

    ``point`` est un point DE l'axe, et non « le » point de l'axe : la position
    le long de l'axe n'est pas observable par cette methode, et elle n'a aucun
    effet cinematique — tourner autour de deux points d'une meme droite donne la
    meme transformation. Le champ ``offset_perp_mm`` porte donc l'ecart au
    nominal **perpendiculairement** a l'axe, seule composante qui a un sens.
    """

    point: np.ndarray
    direction: np.ndarray
    circle_radius_mm: float
    residual_rms_mm: float
    n_points: int
    offset_perp_mm: np.ndarray
    direction_error_deg: float

    #: Incertitudes estimees par JACKKNIFE sur l'ajustement, pas par formule.
    #:
    #: Une premiere version les deduisait de ``residu / rayon`` et de
    #: ``residu / sqrt(n)``. Mesure sur erreur injectee : elles SOUS-ESTIMAIENT
    #: l'erreur reelle d'un facteur ~3,7, constant sur trois niveaux de bruit.
    #: Une incertitude sous-estimee est exactement la confiance fabriquee que ce
    #: module existe pour empecher, donc la formule a ete remplacee.
    #:
    #: La cause de l'ecart est l'ETENDUE ANGULAIRE : ces formules supposent un
    #: cercle complet, alors qu'on mesure un arc — 160 deg pour C, et seulement
    #: 80 deg pour A, borne par la course du berceau. Un arc partiel contraint
    #: beaucoup moins bien la normale, et aucune des deux formules ne le voit.
    #: Le jackknife, lui, le voit sans qu'on ait a le modeliser : il mesure la
    #: sensibilite de l'ajustement au retrait d'un point, donc il integre
    #: l'etendue, le nombre de points et le bruit d'un seul coup.
    direction_uncertainty_deg: float = float("inf")
    point_uncertainty_mm: float = float("inf")


def fit_sphere(points: np.ndarray) -> SphereFit:
    """Centre et rayon d'une sphere, par moindres carres algebriques.

    Formulation lineaire : ``|p|^2 = 2.p.c + (r^2 - |c|^2)``, donc les inconnues
    ``(c, r^2 - |c|^2)`` sortent d'un systeme lineaire. Pas d'iteration, pas
    d'amorce, donc pas de dependance a un point de depart — ce qui compte pour
    une mesure qui doit etre reproductible.
    """
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if len(p) < 4:
        raise ValueError(f"{len(p)} points : une sphere en demande au moins 4")
    a = np.column_stack([2.0 * p, np.ones(len(p))])
    b = (p * p).sum(axis=1)

    # Refus des configurations degenerees, et non correction silencieuse.
    #
    # Des points tous pris sur UN MEME CERCLE de la sphere appartiennent a une
    # infinite de spheres : le probleme n'a pas de solution unique. ``lstsq``
    # rend pourtant un centre, et ce centre a l'air d'une mesure. Defaut
    # rencontre exactement ainsi au jalon M7 : un palpeur simule qui prenait
    # ses huit points sur une seule latitude donnait un residu de 1,1 mm
    # INSENSIBLE au bruit de palpage — le signe qu'il s'agissait d'un defaut
    # systematique et non statistique — et une localisation d'axe fausse de
    # 178 deg.
    sv = np.linalg.svd(a, compute_uv=False)
    if sv[0] < 1e-12 or sv[-1] / sv[0] < 1e-6:
        raise ValueError(
            f"ajustement de sphere mal conditionne (sv_min/sv_max = "
            f"{sv[-1] / max(sv[0], 1e-300):.2e}) : les {len(p)} points sont "
            "quasi coplanaires ou tous sur un meme cercle, configuration qui "
            "appartient a une infinite de spheres. Palper sur AU MOINS DEUX "
            "latitudes.")

    sol, *_ = np.linalg.lstsq(a, b, rcond=None)
    centre = sol[:3]
    r2 = sol[3] + float(centre @ centre)
    if r2 <= 0.0:
        raise ValueError("ajustement de sphere degenere : points quasi coplanaires")
    radius = math.sqrt(r2)
    res = np.linalg.norm(p - centre, axis=1) - radius
    return SphereFit(centre=centre, radius_mm=float(radius),
                     residual_rms_mm=float(np.sqrt((res * res).mean())),
                     n_points=len(p))


def fit_circle_3d(points: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Cercle passant par des points 3D : centre, normale, rayon, residu RMS.

    Le plan sort d'une SVD (donc du meilleur plan au sens des moindres carres),
    puis le cercle s'ajuste dans ce plan par la meme formulation algebrique que
    la sphere. Le residu combine l'ecart au plan et l'ecart au cercle : les deux
    comptent, et n'en rapporter qu'un laisserait passer un axe mal oriente.
    """
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if len(p) < 3:
        raise ValueError(f"{len(p)} points : un cercle en demande au moins 3")
    g = p.mean(axis=0)
    q = p - g
    _, _, vt = np.linalg.svd(q, full_matrices=False)
    normal = normalize(vt[2])
    e1, e2 = vt[0], vt[1]

    uv = np.column_stack([q @ e1, q @ e2])
    a = np.column_stack([2.0 * uv, np.ones(len(uv))])
    b = (uv * uv).sum(axis=1)
    sol, *_ = np.linalg.lstsq(a, b, rcond=None)
    cu, cv = float(sol[0]), float(sol[1])
    r2 = sol[2] + cu * cu + cv * cv
    radius = math.sqrt(max(r2, 0.0))
    centre = g + cu * e1 + cv * e2

    d_plane = q @ normal
    d_circle = np.linalg.norm(uv - np.array([cu, cv]), axis=1) - radius
    res = np.sqrt((d_plane ** 2 + d_circle ** 2).mean())
    return centre, normal, float(radius), float(res)


def fit_axis_from_rotation(
    centres: np.ndarray, angles_deg: np.ndarray,
    nominal_point: np.ndarray, nominal_direction: np.ndarray,
) -> AxisFit:
    """Localise un axe de rotation depuis les positions d'un point qui tourne.

    C'est la procedure qui leve le verrou nomme par le post-processeur : sur une
    cinematique table/table, l'erreur de position des pivots A et C se propage
    directement a la piece, et aucun calcul ne la remplace — il faut la mesurer.

    Methode : une sphere de reference solidaire du plateau est palpee a
    plusieurs valeurs de l'axe. Ses centres decrivent un cercle dont la normale
    est la direction de l'axe et dont le centre est un point de l'axe.

    Le signe de la normale est fixe par le SENS de rotation mesure, et non par
    la proximite au nominal : se recaler sur le nominal ferait retrouver le
    nominal, ce qui est exactement l'erreur que la procedure doit eviter. On
    n'emploie le nominal que pour rendre l'ECART, jamais pour contraindre la
    mesure.
    """
    c = np.asarray(centres, dtype=np.float64).reshape(-1, 3)
    ang = np.asarray(angles_deg, dtype=np.float64).ravel()
    if len(c) != len(ang):
        raise ValueError(f"{len(c)} centres pour {len(ang)} angles")
    if len(c) < 3:
        raise ValueError(f"{len(c)} positions : la localisation d'axe en demande "
                         "au moins 3, et 5 a 8 pour une incertitude utile")

    point, normal, radius, res = fit_circle_3d(c)

    # Incertitudes par jackknife : n reajustements a un point retire. Le cout
    # est negligeable (n moindres carres de taille 3) et le resultat integre
    # l'etendue angulaire reelle, que les formules fermees ignorent.
    dir_spread = 0.0
    pt_spread = 0.0
    if len(c) >= 4:
        norms, pts = [], []
        for k in range(len(c)):
            sub = np.delete(c, k, axis=0)
            pk, nk, _, _ = fit_circle_3d(sub)
            if float(nk @ normal) < 0.0:
                nk = -nk
            norms.append(nk)
            pts.append(pk)
        norms = np.array(norms)
        pts = np.array(pts)
        n_k = len(c)
        # Ecart-type jackknife : (n-1)/n . somme des ecarts au carre.
        #
        # NE PAS nommer cette variable ``ang`` : c'est le nom du parametre
        # portant les angles COMMANDES, et l'ecraser fait trier les positions
        # par les ecarts du jackknife au lieu des angles. La determination du
        # sens de la normale devient alors arbitraire, et l'erreur rapportee
        # vaut 179,999 deg au lieu de 0,001 — un nombre plausible et faux.
        jk_ang = np.array([
            math.degrees(math.acos(float(np.clip(nk @ normal, -1.0, 1.0))))
            for nk in norms])
        dir_spread = math.sqrt((n_k - 1) / n_k * float((jk_ang ** 2).sum()))
        dp = np.linalg.norm(pts - point, axis=1)
        pt_spread = math.sqrt((n_k - 1) / n_k * float((dp ** 2).sum()))

    # Sens de la normale : la rotation doit etre positive autour d'elle quand
    # l'angle commande croit.
    #
    # **Se mesure pas a pas, et non des extremites.** Une premiere version
    # comparait le premier et le dernier point : sur un balayage de 300 deg, le
    # produit vectoriel v0 x v_fin pointe a l'oppose (300 deg equivaut a
    # -60 deg), la normale etait retournee a tort, et l'erreur d'orientation
    # rapportee valait 179,85 deg au lieu de 0,15. On somme donc les angles
    # SIGNES entre positions consecutives, chacun non ambigu tant que le pas
    # reste sous 180 deg.
    order = np.argsort(ang)
    cs, as_ = c[order], ang[order]
    steps = np.diff(as_)
    if steps.size and float(steps.max()) >= 180.0:
        raise ValueError(
            f"pas angulaire de {steps.max():.1f} deg entre deux positions : "
            "au-dela de 180 deg le sens de rotation n'est pas deductible des "
            "positions seules. Repartir les mesures sous 180 deg de pas.")

    v = cs - point
    swept = 0.0
    for k in range(len(v) - 1):
        swept += math.atan2(float(np.cross(v[k], v[k + 1]) @ normal),
                            float(v[k] @ v[k + 1]))
    if swept < 0.0 and (as_[-1] - as_[0]) > 0.0:
        normal = -normal

    u_nom = normalize(np.asarray(nominal_direction, dtype=np.float64))
    p_nom = np.asarray(nominal_point, dtype=np.float64)

    # Ecart de position PERPENDICULAIRE a l'axe : la composante axiale n'est ni
    # observable ni cinematiquement pertinente.
    d = point - p_nom
    offset_perp = d - float(d @ normal) * normal

    err = math.degrees(math.acos(float(np.clip(normal @ u_nom, -1.0, 1.0))))
    return AxisFit(point=point, direction=normal, circle_radius_mm=radius,
                   residual_rms_mm=res, n_points=len(c),
                   offset_perp_mm=offset_perp, direction_error_deg=float(err),
                   direction_uncertainty_deg=float(dir_spread),
                   point_uncertainty_mm=float(pt_spread))


def fit_plane_normal(points: np.ndarray) -> tuple[np.ndarray, float]:
    """Normale d'un plan au sens des moindres carres, et residu RMS.

    SVD sur les points centres : la normale est la direction de moindre
    variance. Le residu est l'ecart-type des distances au plan, et c'est lui
    qui donne l'incertitude d'orientation une fois divise par l'etendue palpee
    — un plan palpe sur 10 mm ne dit rien de son equerrage a 0,001 deg.
    """
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if len(p) < 3:
        raise ValueError(f"{len(p)} points : un plan en demande au moins 3")
    g = p.mean(axis=0)
    q = p - g
    sv = np.linalg.svd(q, compute_uv=False)
    if sv[0] > 1e-12 and sv[1] / sv[0] < 1e-6:
        raise ValueError(
            f"ajustement de plan mal conditionne (sv2/sv1 = {sv[1] / sv[0]:.2e}) : "
            f"les {len(p)} points sont quasi colineaires, configuration qui "
            "appartient a une infinite de plans.")
    _, _, vt = np.linalg.svd(q, full_matrices=False)
    normal = normalize(vt[2])
    d = q @ normal
    return normal, float(np.sqrt((d * d).mean()))
