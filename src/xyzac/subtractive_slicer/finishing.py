"""Passes de FINITION : celles qui donnent la piece.

L'ebauche du jalon M3 ne fait que degrossir — elle laisse le long des parois une
surepaisseur de l'ordre du rayon d'outil plus la marge de discretisation. C'est
la finition qui produit la surface, et elle obeit a des regles differentes :

  - l'outil suit la SURFACE, pas des plans de coupe horizontaux ;
  - le pas transversal n'est plus une fraction du diametre mais se deduit d'une
    **hauteur de crete** admissible ;
  - le contact se fait sur le bec, donc l'outil hemispherique est la regle et
    l'orientation de l'axe redevient un degre de liberte utile.

C'est donc ici que le differenciateur 5 axes sert reellement : sur une face
plane, une orientation indexee suffit ; sur un dome, les normales varient trop
et il faut du simultane. Le moteur tranche par la meme regle qu'ailleurs —
l'intersection des ensembles admissibles.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..geometry_core import brep
from ..geometry_core.types import normalize, orthonormal_basis
from ..tool_model.assembly import ToolAssembly


def scallop_stepover(tool_radius: float, scallop_mm: float) -> float:
    """Pas transversal donnant une hauteur de crete ``scallop_mm`` sur un PLAN.

    Entre deux passes d'un outil hemispherique de rayon R espacees de ``s``, la
    matiere non enlevee forme une crete de hauteur

        h = R - sqrt(R^2 - (s/2)^2)     d'ou     s = 2.sqrt(2Rh - h^2)

    **Valable sur une surface plane uniquement.** Sur une surface convexe la
    crete reelle est plus faible (les passes se recouvrent davantage), sur une
    surface concave elle est plus forte. La formule plane est donc OPTIMISTE en
    concave — c'est le sens d'erreur defavorable, et il faut le savoir : sur un
    conge interieur de rayon proche de celui de l'outil, la hauteur de crete
    reelle peut depasser plusieurs fois la consigne.

    Le calcul exact demande la courbure locale de la surface. Il n'est pas fait
    ici, et tant qu'il ne l'est pas ``scallop_mm`` doit etre lu comme une
    consigne indicative, pas comme une garantie d'etat de surface.
    """
    R = float(tool_radius)
    h = float(min(max(scallop_mm, 1e-4), R * 0.99))
    return 2.0 * math.sqrt(max(2.0 * R * h - h * h, 1e-12))


@dataclass
class FinishingPass:
    """Une passe de finition sur un groupe de faces."""

    face_indices: list[int]
    points: np.ndarray                  # (N,3) points de contact
    normals: np.ndarray                 # (N,3) normales sortantes
    stepover: float
    scallop_mm: float
    pass_direction: np.ndarray = field(default_factory=lambda: np.array([1.0, 0.0, 0.0]))
    n_stripes: int = 0
    #: "parallele" (bandes dans le plan tangent) ou "waterline" (niveaux
    #: constants autour d'un axe). Voir ``generate_finishing_passes``.
    topology: str = "parallele"

    @property
    def n_points(self) -> int:
        return int(len(self.points))

    def normal_spread_deg(self) -> float:
        """Ouverture angulaire des normales de la passe.

        C'est l'indicateur qui decide 3+2 ou simultane : tant qu'elle reste
        sous l'ouverture d'un cone d'accessibilite, une orientation fixe peut
        couvrir la passe.
        """
        if len(self.normals) < 2:
            return 0.0
        mean = normalize(self.normals.mean(axis=0))
        cos = np.clip(self.normals @ mean, -1.0, 1.0)
        return float(np.degrees(np.arccos(cos.min())) * 2.0)

    def describe(self) -> str:
        return (f"Finition faces {self.face_indices} : {self.n_points} points, "
                f"{self.n_stripes} passes, pas {self.stepover:.3f} mm "
                f"(crete {self.scallop_mm:.3f} mm), "
                f"ouverture des normales {self.normal_spread_deg():.1f} deg")


def generate_finishing_passes(
    shape,
    face_indices: list[int],
    tool: ToolAssembly,
    *,
    scallop_mm: float = 0.01,
    pass_direction: np.ndarray | None = None,
    point_spacing: float | None = None,
    sample_spacing: float | None = None,
    waterline_above_deg: float = 60.0,
) -> FinishingPass | None:
    """Genere une passe de finition en zigzag sur un groupe de faces.

    Les points de contact sont pris sur la surface EXACTE (echantillonnage
    B-Rep), et non sur un maillage de la couche : en finition, l'erreur de
    tessellation se retrouve telle quelle sur la piece.

    ``pass_direction`` est la direction d'avance. Par defaut, la plus longue
    dimension du groupe de faces : on minimise ainsi le nombre de changements
    de sens, qui sont les moments ou l'outil marque la surface.

    **Deux topologies, choisies sur l'ouverture des normales.**

    Les bandes paralleles projettent les points sur un plan tangent MOYEN. C'est
    juste pour un groupe quasi plan, et faux des que la surface se referme : sur
    un dome, le plan tangent moyen n'existe pas (176 deg d'ouverture), les
    bandes se replient sur elles-memes, et deux points consecutifs sautent d'un
    bord a l'autre de la calotte.

    Mesure de ce que cela coûte : une passe de 150 points sur un dome demandait
    **18 630 deg de course A+C** — cinquante-deux tours de plateau. Au-dela de
    ``waterline_above_deg``, on passe donc a des niveaux constants autour de
    l'axe du groupe, ordonnes par angle : le chemin fait le tour de la calotte
    au lieu de la traverser.
    """
    if tool.corner_radius <= 0.0:
        # Une fraise a bout droit ne finit pas une surface quelconque : son
        # arete laisse une marche a chaque passe, et l'incliner enfonce son
        # talon. On refuse explicitement plutot que de produire une passe
        # inexploitable.
        raise ValueError(
            f"outil '{tool.tool_id}' a bout droit : la finition d'une surface "
            "demande un rayon de bec (fraise hemispherique ou torique)")

    step = scallop_stepover(tool.corner_radius, scallop_mm)
    spacing = point_spacing or max(step * 0.8, 0.2)
    samp = sample_spacing or max(min(step, spacing) * 0.5, 0.15)

    full = brep.sample_surface(shape, spacing=samp)
    mask = np.isin(full.face_ids, np.asarray(face_indices))
    if not np.any(mask):
        return None
    pts, nrm = full.points[mask], full.normals[mask]

    # Ouverture des normales : c'est elle qui decide la topologie.
    mean_n_raw = nrm.mean(axis=0)
    spread_deg = float(np.degrees(np.arccos(np.clip(
        (nrm @ normalize(mean_n_raw)).min() if np.linalg.norm(mean_n_raw) > 1e-6 else -1.0,
        -1.0, 1.0))) * 2.0)

    if spread_deg > waterline_above_deg:
        ordered_pts, ordered_nrm, n_levels = _waterline_order(pts, nrm, step, spacing)
        topology = "waterline"
        u = np.array([0.0, 0.0, 1.0])
    else:
        mean_n = normalize(mean_n_raw)
        if pass_direction is None:
            span = pts.max(axis=0) - pts.min(axis=0)
            axes = np.eye(3)
            order = np.argsort(-span)
            pass_direction = axes[order[0]]
            if abs(float(pass_direction @ mean_n)) > 0.9:
                pass_direction = axes[order[1]]
        u = normalize(np.asarray(pass_direction, float))
        u = normalize(u - float(u @ mean_n) * mean_n)
        v = np.cross(mean_n, u)

        su, sv = pts @ u, pts @ v
        n_levels = max(1, int(np.ceil((sv.max() - sv.min()) / step)) + 1)
        stripe = np.clip(((sv - sv.min()) / step).astype(int), 0, n_levels - 1)

        ordered_pts, ordered_nrm = [], []
        for k in range(n_levels):
            sel = np.flatnonzero(stripe == k)
            if sel.size == 0:
                continue
            order = sel[np.argsort(su[sel] * (-1 if k % 2 else 1))]
            keep = [order[0]]
            for j in order[1:]:
                if abs(su[j] - su[keep[-1]]) >= spacing:
                    keep.append(j)
            ordered_pts.append(pts[keep])
            ordered_nrm.append(nrm[keep])
        topology = "parallele"

    if not ordered_pts:
        return None

    return FinishingPass(
        face_indices=list(face_indices),
        points=np.vstack(ordered_pts), normals=np.vstack(ordered_nrm),
        stepover=step, scallop_mm=scallop_mm,
        pass_direction=u, n_stripes=len([p for p in ordered_pts if len(p)]),
        topology=topology,
    )


def _waterline_order(pts: np.ndarray, nrm: np.ndarray, step: float, spacing: float):
    """Ordonne les points en niveaux constants autour de l'axe du groupe.

    Topologie standard pour une paroi raide ou une calotte : on tranche par
    cotes le long de l'axe dominant, et dans chaque niveau on ordonne par angle
    autour de cet axe. Le chemin fait alors le TOUR de la surface, alors que
    des bandes paralleles la traverseraient a chaque changement de bande.

    L'axe retenu est la normale moyenne quand elle existe, sinon la direction de
    plus faible etendue du nuage — pour une calotte, c'est bien son axe.
    """
    mean_n = nrm.mean(axis=0)
    if float(np.linalg.norm(mean_n)) > 0.3:
        axis = normalize(mean_n)
    else:
        span = pts.max(axis=0) - pts.min(axis=0)
        axis = np.eye(3)[int(np.argmin(span))]

    u, v, w = orthonormal_basis(axis)

    # Coordonnees RELATIVES au centre du nuage, et non absolues.
    #
    # Defaut mesure : l'angle etait calcule autour de l'ORIGINE du repere piece.
    # Une calotte centree en (30, 30, 10) donnait alors des angles sans rapport
    # avec sa propre geometrie, et l'ordonnancement par angle sautait d'un bord
    # a l'autre — 12,5 mm d'ecart median entre deux points consecutifs pour un
    # pas demande de 2,2 mm. Un ordonnancement angulaire n'a de sens qu'autour
    # de l'axe de la surface, pas autour d'un point arbitraire.
    center = pts.mean(axis=0)
    rel = pts - center

    h = rel @ w
    n_levels = max(1, int(np.ceil((h.max() - h.min()) / step)) + 1)
    level = np.clip(((h - h.min()) / step).astype(int), 0, n_levels - 1)

    out_p, out_n = [], []
    for k in range(n_levels):
        sel = np.flatnonzero(level == k)
        if sel.size == 0:
            continue
        theta = np.arctan2(rel[sel] @ v, rel[sel] @ u)
        order = sel[np.argsort(theta)]
        # Decimation par distance reelle le long du niveau, et non par angle :
        # a rayon faible (pres du pole) un grand angle est un petit deplacement.
        keep = [order[0]]
        for j in order[1:]:
            if float(np.linalg.norm(pts[j] - pts[keep[-1]])) >= spacing:
                keep.append(j)
        out_p.append(pts[keep])
        out_n.append(nrm[keep])
    return out_p, out_n, n_levels


def group_faces_by_normal(shape, *, tol_deg: float = 20.0,
                          min_area: float = 20.0,
                          curved_above_deg: float = 30.0) -> list[list[int]]:
    """Regroupe les faces dont les normales sont proches.

    Un groupe est un candidat a une passe unique. Le seuil est volontairement
    large : c'est l'accessibility solver qui dira si une orientation commune
    existe reellement, et lui seul connait le porte-outil.

    **Une face COURBE forme toujours son propre groupe.** Le critere est
    l'etalement de ses normales, et non la norme de leur moyenne : pour un
    hemisphere cette norme vaut exactement 0,5, ce qui le faisait passer pour
    une face plane d'axe vertical — et des faces planes voisines venaient s'y
    agreger a 20 deg pres.

    La consequence n'etait pas anodine. Le groupe melangeait alors une calotte
    et un plan, et la topologie waterline suppose que chaque niveau est un
    ANNEAU : sur un niveau qui contient aussi une zone plane, l'ordonnancement
    par angle saute radialement. Ecart median mesure entre deux points
    consecutifs : 12,6 mm pour un pas demande de 2,2 mm.
    """
    samples = brep.sample_surface(shape, spacing=2.0)
    groups: list[dict] = []
    cos_tol = math.cos(math.radians(tol_deg))

    for f in brep.face_info(shape):
        if f.area < min_area:
            continue
        m = samples.face_ids == f.index
        if not np.any(m):
            continue
        n_face = samples.normals[m]
        mean = n_face.mean(axis=0)
        nn = float(np.linalg.norm(mean))
        spread = (float(np.degrees(np.arccos(np.clip(
            (n_face @ (mean / nn)).min(), -1.0, 1.0)))) if nn > 1e-6 else 180.0)

        if spread > curved_above_deg:
            # Face courbe : elle forme son propre groupe et n'en accueille
            # aucune autre. La topologie waterline suppose des niveaux en
            # anneau ; y meler une zone plane la casse.
            groups.append({"n": None, "faces": [f.index]})
            continue

        n = mean / nn
        for g in groups:
            if g["n"] is not None and float(g["n"] @ n) >= cos_tol:
                g["faces"].append(f.index)
                break
        else:
            groups.append({"n": n, "faces": [f.index]})

    return [g["faces"] for g in groups]
