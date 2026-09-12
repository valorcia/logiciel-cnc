"""Erreurs geometriques MESUREES d'une machine donnee, et ce qu'on en fait.

Manque de fond des jalons M1 a M6, jamais mis en avant assez clairement :
**toutes les marges rapportees jusqu'ici sont calculees sur une machine
parfaite.** Les jeux valent 0,0, les pivots A et C sont a leur cote nominale,
les axes lineaires sont exactement orthogonaux. Une marge de 0,7 mm annoncee
sur une poche est donc une marge geometrique, pas une marge machine.

Ce module porte la distinction qui manquait, et elle decide de tout le reste :

  - une erreur geometrique **mesuree** est COMPENSABLE. Les axes lineaires
    translatent l'outil dans le repere machine, donc n'importe quelle erreur de
    position se corrige exactement en deplacant la commande. Une erreur
    d'orientation se corrige en re-resolvant (A, C) sur les axes reels.
  - l'**incertitude** de cette mesure ne se compense pas. Elle se propage a la
    piece, elle grandit avec la distance au pivot, et c'est elle — pas l'erreur
    nominale — qui borne ce qu'on a le droit d'affirmer.

D'ou la regle que ce module impose : une machine non calibree n'a pas une
erreur nulle, elle a une incertitude **inconnue**. ``MachineGeometry.nominal()``
le declare en mettant ``measured=False``, et tout ce qui consomme un budget
d'incertitude doit refuser de conclure dans cet etat plutot que de lire des
zeros.
"""

from __future__ import annotations

import math

import numpy as np
from pydantic import BaseModel, Field, model_validator

from ..geometry_core.types import normalize
from .machine import MachineKinematics


def _rodrigues(axis: np.ndarray, angle_rad: float) -> np.ndarray:
    """Rotation d'angle donne autour d'un axe quelconque (unitaire)."""
    u = normalize(axis)
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    k = np.array([[0.0, -u[2], u[1]], [u[2], 0.0, -u[0]], [-u[1], u[0], 0.0]])
    return np.eye(3) * c + s * k + (1.0 - c) * np.outer(u, u)


class AxisLocationError(BaseModel):
    """Localisation MESUREE d'un axe rotatif : un point et une direction.

    ``offset_mm`` est l'ecart du point de l'axe par rapport a la valeur nominale
    portee par ``MachineKinematics.pivot_a`` / ``pivot_c``. ``direction`` est la
    direction reellement mesuree de l'axe, normalisee — nominalement +X pour A
    et +Z pour C ; son ecart au nominal est l'erreur de parallelisme.

    Les deux incertitudes ne sont pas decoratives : ce sont elles qui sortent
    dans le budget, et un appelant qui les ignore annonce une precision qu'il
    n'a pas mesuree.
    """

    offset_mm: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    direction: list[float] = Field(default_factory=lambda: [1.0, 0.0, 0.0])
    offset_uncertainty_mm: float = Field(0.0, ge=0.0)
    direction_uncertainty_deg: float = Field(0.0, ge=0.0)

    @model_validator(mode="after")
    def _check(self) -> "AxisLocationError":
        if len(self.offset_mm) != 3 or len(self.direction) != 3:
            raise ValueError("offset_mm et direction sont des vecteurs de dimension 3")
        if float(np.linalg.norm(self.direction)) < 1e-9:
            raise ValueError("direction d'axe nulle : une direction non mesuree "
                             "se declare nominale, pas nulle")
        return self

    @property
    def u(self) -> np.ndarray:
        return normalize(np.asarray(self.direction, dtype=np.float64))

    @property
    def d(self) -> np.ndarray:
        return np.asarray(self.offset_mm, dtype=np.float64)


class MachineGeometry(BaseModel):
    """Erreurs geometriques d'UNE machine, telles que mesurees.

    ``measured=False`` signifie « aucune mesure » et non « erreurs nulles ».
    La difference est celle entre une machine parfaite et une machine inconnue,
    et elle est verifiee par ``require_measured``.
    """

    machine_id: str = "inconnu"
    measured: bool = False
    a_axis: AxisLocationError = Field(
        default_factory=lambda: AxisLocationError(direction=[1.0, 0.0, 0.0]))
    c_axis: AxisLocationError = Field(
        default_factory=lambda: AxisLocationError(direction=[0.0, 0.0, 1.0]))

    #: Defauts d'equerrage du triedre lineaire, en degres. ``xy`` est l'ecart a
    #: 90 deg entre X et Y, etc. Nominalement nuls.
    squareness_xy_deg: float = 0.0
    squareness_xz_deg: float = 0.0
    squareness_yz_deg: float = 0.0
    squareness_uncertainty_deg: float = Field(0.0, ge=0.0)

    #: Erreurs d'echelle des vis, en ppm (1000 ppm = 1 mm pour 1 m).
    scale_x_ppm: float = 0.0
    scale_y_ppm: float = 0.0
    scale_z_ppm: float = 0.0

    #: Repetabilite de prise d'origine, mesuree par reprises successives.
    homing_repeatability_mm: float = Field(0.0, ge=0.0)

    @staticmethod
    def nominal(machine_id: str = "inconnu") -> "MachineGeometry":
        """Geometrie NON MESUREE. A ne jamais confondre avec une machine juste."""
        return MachineGeometry(machine_id=machine_id, measured=False)

    # -- triedre lineaire -------------------------------------------------

    def linear_matrix(self) -> np.ndarray:
        """Matrice qui transforme une commande d'axes en deplacement reel.

        L'equerrage incline les axes les uns par rapport aux autres et l'echelle
        les dilate. On garde X comme reference — un triedre ne se mesure qu'en
        relatif, et choisir une reference explicitement evite de repartir
        arbitrairement l'erreur sur les trois axes.
        """
        exy = math.radians(self.squareness_xy_deg)
        exz = math.radians(self.squareness_xz_deg)
        eyz = math.radians(self.squareness_yz_deg)
        s = np.array([1.0 + self.scale_x_ppm * 1e-6,
                      1.0 + self.scale_y_ppm * 1e-6,
                      1.0 + self.scale_z_ppm * 1e-6])
        # Colonnes = directions reelles des axes commandes.
        ex = np.array([1.0, 0.0, 0.0])
        ey = np.array([math.sin(exy), math.cos(exy), 0.0])
        ez = np.array([math.sin(exz), math.sin(eyz), 1.0])
        ez = ez / float(np.linalg.norm(ez))
        return np.column_stack([ex * s[0], ey * s[1], ez * s[2]])

    # -- rotations reelles ------------------------------------------------

    def real_rotation(self, a_deg: float, c_deg: float) -> np.ndarray:
        """``R_machine<-piece`` sur les axes REELS, dans l'ordre C puis A."""
        rz = _rodrigues(self.c_axis.u, math.radians(c_deg))
        rx = _rodrigues(self.a_axis.u, math.radians(a_deg))
        return rx @ rz

    def real_part_to_machine(self, machine: MachineKinematics, p_part: np.ndarray,
                             a_deg: float, c_deg: float) -> np.ndarray:
        """Transport piece -> machine sur la geometrie REELLE.

        Meme chaine que ``KinematicsSolver.part_to_machine_point``, aux points
        et directions d'axes mesures pres.
        """
        pc = np.asarray(machine.pivot_c, dtype=np.float64) + self.c_axis.d
        pa = np.asarray(machine.pivot_a, dtype=np.float64) + self.a_axis.d
        rz = _rodrigues(self.c_axis.u, math.radians(c_deg))
        rx = _rodrigues(self.a_axis.u, math.radians(a_deg))
        p = np.asarray(p_part, dtype=np.float64)
        p = rz @ (p - pc) + pc
        p = rx @ (p - pa) + pa
        return p

    def real_tool_axis_in_part(self, a_deg: float, c_deg: float) -> np.ndarray:
        """Direction d'axe outil dans le repere piece, sur les axes reels.

        L'axe de broche est fixe dans le repere machine ; c'est la piece qui
        tourne. La direction vue de la piece est donc ``R^T . z_broche``.
        """
        return normalize(self.real_rotation(a_deg, c_deg).T @ np.array([0.0, 0.0, 1.0]))

    # -- budget d'incertitude ---------------------------------------------

    def require_measured(self) -> None:
        if not self.measured:
            raise RuntimeError(
                f"geometrie de la machine '{self.machine_id}' NON MESUREE. "
                "Une machine non calibree n'a pas une erreur nulle : elle a une "
                "incertitude inconnue. Executer assembly_calibration avant "
                "d'utiliser un budget d'incertitude ou de generer un programme."
            )

    def position_uncertainty_mm(self, reach_mm: float, *, worst_case: bool = True
                                ) -> float:
        """Incertitude de position a la piece, pour un point a ``reach_mm`` du pivot.

        C'est la grandeur que les erreurs mesurees NE reduisent pas : une fois
        l'erreur connue on la compense, mais l'incertitude de la mesure reste et
        elle grandit avec le bras de levier. Une incertitude d'orientation
        d'axe de 0,01 deg vaut 17 um a 100 mm du pivot.

        ``worst_case=True`` (defaut) somme les contributions : c'est le choix
        conservatif, celui qu'exige un budget de securite (meme discipline que
        l'inflation du champ d'obstacles). ``False`` les compose en quadrature,
        ce qui convient a un enonce de precision sur des sources independantes
        — et donne un chiffre plus flatteur, donc a ne pas employer pour decider
        d'une garde.
        """
        self.require_measured()
        r = max(float(reach_mm), 0.0)
        terms = [
            float(self.a_axis.offset_uncertainty_mm),
            float(self.c_axis.offset_uncertainty_mm),
            r * math.radians(float(self.a_axis.direction_uncertainty_deg)),
            r * math.radians(float(self.c_axis.direction_uncertainty_deg)),
            r * math.radians(float(self.squareness_uncertainty_deg)),
            float(self.homing_repeatability_mm),
        ]
        if worst_case:
            return float(sum(terms))
        return float(math.sqrt(sum(t * t for t in terms)))

    def backlash_budget_mm(self, machine: MachineKinematics, reach_mm: float) -> float:
        """Contribution des jeux, en pire cas : une inversion peut tout perdre.

        Les jeux rotatifs se convertissent en deplacement lineaire par le bras
        de levier, ce qui les rend beaucoup plus couteux qu'ils n'en ont l'air
        sur une cinematique table/table.
        """
        r = max(float(reach_mm), 0.0)
        lin = float(machine.x.backlash_mm + machine.y.backlash_mm + machine.z.backlash_mm)
        rot = r * (math.radians(float(machine.a.backlash_deg))
                   + math.radians(float(machine.c.backlash_deg)))
        return lin + rot

    def describe(self) -> str:
        if not self.measured:
            return (f"Geometrie '{self.machine_id}' : NON MESUREE. Aucun budget "
                    "d'incertitude ne peut etre calcule, et aucune tolerance "
                    "annoncee.")
        return (
            f"Geometrie '{self.machine_id}' mesuree : "
            f"pivot A decale de {np.round(self.a_axis.d, 4)} mm "
            f"(+/-{self.a_axis.offset_uncertainty_mm:.4f}), axe a "
            f"{math.degrees(float(np.arccos(np.clip(self.a_axis.u @ np.array([1.0, 0.0, 0.0]), -1, 1)))):.4f} deg "
            f"du nominal (+/-{self.a_axis.direction_uncertainty_deg:.4f}) ; "
            f"pivot C decale de {np.round(self.c_axis.d, 4)} mm "
            f"(+/-{self.c_axis.offset_uncertainty_mm:.4f}), axe a "
            f"{math.degrees(float(np.arccos(np.clip(self.c_axis.u @ np.array([0.0, 0.0, 1.0]), -1, 1)))):.4f} deg "
            f"du nominal (+/-{self.c_axis.direction_uncertainty_deg:.4f}) ; "
            f"equerrage XY/XZ/YZ {self.squareness_xy_deg:.4f}/"
            f"{self.squareness_xz_deg:.4f}/{self.squareness_yz_deg:.4f} deg ; "
            f"repetabilite d'origine {self.homing_repeatability_mm:.4f} mm"
        )
