"""Courbures principales d'une face, et rayon de courbure utile a la finition.

Necessaire pour que la hauteur de crete demandee en finition veuille dire
quelque chose. Le pas transversal deduit d'une surface PLANE se trompe des que
la surface est courbe, et il se trompe dans un sens qui compte.

Convention de signe employee partout ici : la courbure normale ``kappa`` est
comptee POSITIVE quand la surface est convexe vue du cote de la normale
sortante (une bosse), NEGATIVE quand elle est concave (un creux). Le rayon de
courbure vaut ``1/|kappa|``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepLProp import BRepLProp_SLProps
from OCP.TopAbs import TopAbs_Orientation

from . import brep


@dataclass
class FaceCurvature:
    """Courbures principales echantillonnees sur une face."""

    face_index: int
    kappa_min: float          # courbure principale la plus faible (signee)
    kappa_max: float          # la plus forte (signee)
    kappa_worst: float        # celle qui MAJORE la crete : la plus convexe
    n_samples: int
    n_undefined: int

    @property
    def radius_worst_mm(self) -> float:
        """Rayon de courbure correspondant, ``inf`` si quasi plan."""
        k = abs(self.kappa_worst)
        return float("inf") if k < 1e-9 else 1.0 / k

    @property
    def is_convex(self) -> bool:
        return self.kappa_worst > 0.0

    def describe(self) -> str:
        # « plane » qualifie la DIRECTION DIMENSIONNANTE, pas la face : un cone
        # concave a une generatrice droite, donc une courbure dimensionnante
        # nulle, tout en etant courbe circonferentiellement.
        kind = ("convexe" if self.kappa_worst > 1e-6
                else "concave" if self.kappa_worst < -1e-6
                else "droite dans la direction dimensionnante")
        r = self.radius_worst_mm
        rtxt = "inf" if not np.isfinite(r) else f"{r:.2f} mm"
        return (f"face {self.face_index} : {kind}, courbure dimensionnante "
                f"{self.kappa_worst:+.5f} /mm (R = {rtxt}), "
                f"{self.n_samples} echantillons"
                + (f", {self.n_undefined} sans courbure definie"
                   if self.n_undefined else ""))


def face_curvature(shape, face_index: int, *, n_u: int = 9, n_v: int = 9,
                   resolution: float = 1e-6) -> FaceCurvature | None:
    """Echantillonne les courbures principales d'une face.

    On retient ``kappa_worst`` = la courbure la PLUS CONVEXE rencontree, et non
    une moyenne. Motif : c'est elle qui majore la hauteur de crete (voir
    ``curvature_stepover``), et dimensionner une finition sur une moyenne
    laisserait les zones convexes hors tolerance sans que rien ne le signale.
    """
    face = None
    for idx, f in brep.iter_faces(shape):
        if idx == face_index:
            face = f
            break
    if face is None:
        return None

    ad = BRepAdaptor_Surface(face)
    u0, u1 = ad.FirstUParameter(), ad.LastUParameter()
    v0, v1 = ad.FirstVParameter(), ad.LastVParameter()
    if not all(np.isfinite([u0, u1, v0, v1])):
        return None

    # BRepLProp_SLProps attend un ADAPTER, pas une Geom_Surface : la facade
    # absorbe cette contrainte comme les autres derives de l'API OCP.
    surf = BRepAdaptor_Surface(face)
    # L'orientation topologique inverse le sens de la normale, donc le signe
    # des courbures : l'ignorer echangerait convexe et concave.
    flip = face.Orientation() == TopAbs_Orientation.TopAbs_REVERSED

    kmins, kmaxs = [], []
    undefined = 0
    for u in np.linspace(u0, u1, n_u):
        for v in np.linspace(v0, v1, n_v):
            props = BRepLProp_SLProps(2, resolution)
            props.SetSurface(surf)
            props.SetParameters(float(u), float(v))
            if not props.IsCurvatureDefined():
                undefined += 1
                continue
            try:
                a = float(props.MinCurvature())
                b = float(props.MaxCurvature())
            except Exception:
                undefined += 1
                continue
            if flip:
                a, b = -b, -a
            kmins.append(a)
            kmaxs.append(b)

    if not kmaxs:
        return None

    # OCCT compte la courbure positive vers l'interieur de la matiere selon sa
    # propre convention de normale ; apres correction d'orientation, une bosse
    # vue de l'exterieur donne une courbure NEGATIVE. On retourne le signe pour
    # retrouver la convention du module (convexe > 0).
    kmin = -max(kmaxs)
    kmax = -min(kmins)
    return FaceCurvature(
        face_index=face_index,
        kappa_min=float(min(kmin, kmax)), kappa_max=float(max(kmin, kmax)),
        kappa_worst=float(max(kmin, kmax)),
        n_samples=len(kmaxs), n_undefined=undefined,
    )


def curvature_stepover(tool_radius: float, scallop_mm: float,
                       kappa: float = 0.0) -> float:
    """Pas transversal donnant ``scallop_mm`` de crete sur une surface courbe.

    Deux positions successives d'un outil spherique de rayon R suivant un
    cercle osculateur de rayon ``rho = 1/|kappa|`` ont leurs centres sur un
    cercle de rayon ``oc = rho + sigma.R`` (sigma = +1 bosse, -1 creux). La
    crete subsiste a l'angle median, a la distance ``P = rho + sigma.h`` du
    centre de courbure. Le triangle (centre de courbure, centre d'outil, crete)
    donne alors directement, par la loi des cosinus :

        1 - cos(theta/2) = (2Rh - h^2) / (2.oc.P)

    d'ou, ecrit en demi-angle pour rester bien conditionne quand ``rho`` est
    grand devant l'outil :

        s = rho.theta = 4.rho.arcsin( sqrt( (2Rh - h^2) / (4.oc.P) ) )

    C'est une forme **exacte**, pas un developpement : verifiee a mieux que
    1e-6 % contre une resolution numerique de la crete, pour rho de 6 a 20 mm,
    h de 2 a 150 um, dans les deux sens. Quand ``kappa`` tend vers zero elle
    tend continument vers la forme plane ``s = 2.sqrt(2Rh - h^2)`` de
    ``subtractive_slicer.scallop_stepover`` (ecart relatif 1,5e-9 a
    kappa = 1e-9 /mm) et lui est egale au flottant pres a kappa = 0.

    Le developpement au premier ordre ``h = (s^2/8).(1/R + kappa)``, employe
    dans une premiere version de ce module, reste **optimiste en convexe** la
    ou cela compte : -1,6 % de crete annoncee a s = 1 mm sur une bosse de
    6 mm, -3,7 % a s = 1,5 mm. La forme fermee coute le meme arcsin et supprime
    ce biais, donc il n'y a aucune raison de garder l'approximation.

    **Le signe compte, et il est contre-intuitif.** Crete reelle laissee par un
    pas de 0,5 mm avec un outil R = 3 mm, comparee a la prevision plane :

        surface            crete reelle    formule plane
        plan                  10,43 um        10,43 um
        convexe R = 20 mm     12,01 um        10,43 um   <- plan OPTIMISTE
        convexe R =  6 mm     15,70 um        10,43 um   <- plan OPTIMISTE (x1,5)
        concave R = 20 mm      8,86 um        10,43 um   <- plan conservatif
        concave R =  6 mm      5,21 um        10,43 um   <- plan conservatif

    La formule plane se trompe donc **en CONVEXE**, et d'un facteur qui atteint
    1,5 quand le rayon de la surface approche celui de l'outil. Sur une bosse,
    dimensionner la finition sur un plan laisse la piece hors tolerance sans
    qu'aucun indicateur ne le signale.

    (La documentation du jalon M4 affirmait l'inverse — plan optimiste en
    concave. C'etait faux, et la mesure ci-dessus le montre. Le sens de
    l'erreur est ce qui compte, puisqu'il decide si l'on sur-decoupe ou
    sous-decoupe.)

    Un creux de rayon inferieur ou egal a celui de l'outil est refuse par
    ``ValueError`` : l'outil n'en atteint pas le fond, et aucun pas, meme nul,
    n'y change quoi que ce soit.
    """
    R = float(tool_radius)
    h = float(min(max(scallop_mm, 1e-5), R * 0.99))
    k = float(kappa)
    chord2 = max(2.0 * R * h - h * h, 1e-12)        # (s/2)^2 de la forme plane

    if abs(k) < 1e-12:                              # plan : forme plane exacte
        return float(2.0 * np.sqrt(chord2))

    rho = 1.0 / abs(k)
    sigma = 1.0 if k > 0.0 else -1.0
    oc = rho + sigma * R                            # rayon du cercle des centres
    if oc <= 1e-9:
        raise ValueError(
            f"courbure {k:+.5f} /mm (R_surface = {rho:.2f} mm) incompatible "
            f"avec un outil de rayon {R} mm : dans un creux plus serre que "
            "l'outil, celui-ci ne touche pas le fond. Il faut un outil plus "
            "fin, pas un pas plus petit.")

    arg = chord2 / (4.0 * oc * (rho + sigma * h))
    if arg >= 1.0:
        # Creux dont le rayon depasse a peine celui de l'outil : le fond epouse
        # l'outil sur un large arc et la crete demandee est atteinte avant
        # meme un tour complet. Le pas n'est plus limite par la crete ; on rend
        # la circonference, c'est-a-dire "une seule passe suffit".
        return float(2.0 * np.pi * rho)
    return float(4.0 * rho * np.arcsin(np.sqrt(arg)))
