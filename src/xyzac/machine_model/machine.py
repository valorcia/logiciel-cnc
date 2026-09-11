"""Modele de la machine XYZAC : courses, butees, chaine cinematique, volumes de collision.

Cinematique table/table (ADR-001 / D5) : la broche est FIXE selon +Z machine ;
c'est la piece qui s'oriente via le berceau A (rotation autour de X) portant le
plateau C (rotation autour de Z local).

    R_machine<-piece = Rx(A) . Rz(C)

d'ou la direction d'axe outil exprimee dans le repere PIECE :

    d_piece(A, C) = ( sin A . sin C ,  sin A . cos C ,  cos A )
"""

from __future__ import annotations

import math
from enum import Enum

import numpy as np
from pydantic import BaseModel, Field, model_validator


class CAxisMode(str, Enum):
    """Mode de l'axe C.

    Le passage d'un mode a l'autre est une transition d'etat explicite
    (ADR-001 / D8) : en mode broche, les obstacles ne sont plus quasi statiques
    dans le repere piece et les hypotheses du collision engine tombent.
    """

    INDEXED = "indexed"                      # positionnement angulaire, fraisage
    CONTINUOUS_SPINDLE = "continuous_spindle"  # rotation continue, tournage


class LinearAxis(BaseModel):
    name: str
    min_mm: float
    max_mm: float
    max_feed_mm_min: float = Field(3000.0, gt=0)
    max_accel_mm_s2: float = Field(500.0, gt=0)
    backlash_mm: float = Field(0.0, ge=0.0, description="mesure a la calibration, pas suppose")

    @model_validator(mode="after")
    def _check(self) -> "LinearAxis":
        if self.max_mm <= self.min_mm:
            raise ValueError(f"axe {self.name}: course nulle ou negative")
        return self

    @property
    def travel(self) -> float:
        return self.max_mm - self.min_mm

    def contains(self, v: float | np.ndarray) -> np.ndarray:
        return (np.asarray(v) >= self.min_mm) & (np.asarray(v) <= self.max_mm)


class RotaryAxis(BaseModel):
    name: str
    min_deg: float
    max_deg: float
    continuous: bool = False
    max_feed_deg_min: float = Field(3600.0, gt=0)
    max_accel_deg_s2: float = Field(360.0, gt=0)
    backlash_deg: float = Field(0.0, ge=0.0)
    max_rpm: float | None = Field(None, description="non nul seulement si l'axe peut tourner en broche")

    @model_validator(mode="after")
    def _check(self) -> "RotaryAxis":
        if not self.continuous and self.max_deg <= self.min_deg:
            raise ValueError(f"axe {self.name}: course angulaire nulle ou negative")
        return self

    def contains(self, deg: float | np.ndarray) -> np.ndarray:
        deg = np.asarray(deg, dtype=np.float64)
        if self.continuous:
            return np.ones_like(deg, dtype=bool)
        return (deg >= self.min_deg) & (deg <= self.max_deg)

    def clamp(self, deg: float) -> float:
        return deg if self.continuous else min(max(deg, self.min_deg), self.max_deg)


class CollisionVolume(BaseModel):
    """Volume de collision machine, attache a un maillon de la chaine.

    Modelise en cylindre coaxial ou en boite : suffisant pour un berceau, un
    plateau et un nez de broche, et testable sans BVH.
    """

    name: str
    frame: str = Field(..., description="maillon porteur : 'machine' | 'cradle_A' | 'table_C'")
    kind: str = Field("box", pattern="^(box|cylinder)$")
    # box : coins ; cylinder : base, axe, rayon, hauteur (tous en coords du maillon)
    lo: list[float] | None = None
    hi: list[float] | None = None
    base: list[float] | None = None
    axis: list[float] | None = None
    radius: float | None = None
    height: float | None = None


class MachineKinematics(BaseModel):
    """Description complete de la machine XYZAC.

    ``pivot_a`` et ``pivot_c`` sont les points des axes rotatifs exprimes dans le
    repere machine, au home. Ce sont des grandeurs **mesurees a la calibration**
    (``assembly_calibration``), jamais des valeurs nominales de plan : sur une
    machine en kit, l'ecart nominal/reel est la premiere source d'erreur 5 axes.
    """

    machine_id: str = "XYZAC-kit"
    description: str = ""

    x: LinearAxis
    y: LinearAxis
    z: LinearAxis
    a: RotaryAxis
    c: RotaryAxis

    c_mode: CAxisMode = CAxisMode.INDEXED

    pivot_a: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    pivot_c: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])

    spindle_axis: list[float] = Field(default_factory=lambda: [0.0, 0.0, 1.0])
    spindle_max_rpm: float = 24000.0
    spindle_min_rpm: float = 6000.0

    collision_volumes: list[CollisionVolume] = Field(default_factory=list)

    #: Butee de singularite : sous cet angle A, l'axe C est mal conditionne.
    #: Ce n'est pas un confort mais une contrainte dynamique (ADR-001 / D5).
    singularity_a_deg: float = Field(3.0, ge=0.0)

    #: Rapport de vitesse rotatif/lineaire utilise pour borner les transitions.
    max_rotary_per_linear_deg_mm: float = Field(15.0, gt=0)

    @model_validator(mode="after")
    def _check_modes(self) -> "MachineKinematics":
        if self.c_mode is CAxisMode.CONTINUOUS_SPINDLE and not self.c.max_rpm:
            raise ValueError(
                "c_mode=CONTINUOUS_SPINDLE exige c.max_rpm : un plateau d'indexation "
                "ne peut pas etre declare broche de tournage sans sa vitesse limite."
            )
        return self

    # -- cinematique ------------------------------------------------------

    def tool_axis_in_part(self, a_deg: float, c_deg: float) -> np.ndarray:
        """Direction d'axe outil dans le repere PIECE pour un couple (A, C).

        Pointe du bec vers la broche (convention du projet).
        """
        a, c = math.radians(a_deg), math.radians(c_deg)
        sa = math.sin(a)
        return np.array([sa * math.sin(c), sa * math.cos(c), math.cos(a)])

    def rotation_machine_from_part(self, a_deg: float, c_deg: float) -> np.ndarray:
        """Matrice R_machine<-piece = Rx(A) . Rz(C)."""
        a, c = math.radians(a_deg), math.radians(c_deg)
        ca, sa, cc, sc = math.cos(a), math.sin(a), math.cos(c), math.sin(c)
        rx = np.array([[1, 0, 0], [0, ca, -sa], [0, sa, ca]], dtype=np.float64)
        rz = np.array([[cc, -sc, 0], [sc, cc, 0], [0, 0, 1]], dtype=np.float64)
        return rx @ rz

    def is_singular(self, a_deg: float) -> bool:
        return abs(a_deg) < self.singularity_a_deg

    def within_limits(self, a_deg: float, c_deg: float) -> bool:
        return bool(self.a.contains(a_deg)) and bool(self.c.contains(c_deg))

    def describe_limits(self) -> str:
        return (
            f"X[{self.x.min_mm},{self.x.max_mm}] Y[{self.y.min_mm},{self.y.max_mm}] "
            f"Z[{self.z.min_mm},{self.z.max_mm}] "
            f"A[{self.a.min_deg},{self.a.max_deg}] "
            f"C[{'continu' if self.c.continuous else f'{self.c.min_deg},{self.c.max_deg}'}] "
            f"mode C={self.c_mode.value}"
        )


def default_xyzac_kit() -> MachineKinematics:
    """Machine de reference du kit.

    HYPOTHESE EXPLICITE : ces valeurs sont **provisoires** et servent au digital
    twin. Elles doivent etre remplacees par les mesures d'``assembly_calibration``
    avant toute generation destinee a une machine reelle. Les jeux (backlash)
    sont volontairement laisses a 0.0 : declarer une valeur non mesuree serait
    pire que de ne rien declarer.
    """
    return MachineKinematics(
        machine_id="XYZAC-kit-v0",
        description="Centre XYZAC maker en kit — parametres provisoires, non calibres",
        x=LinearAxis(name="X", min_mm=-150.0, max_mm=150.0, max_feed_mm_min=4000.0),
        y=LinearAxis(name="Y", min_mm=-120.0, max_mm=120.0, max_feed_mm_min=4000.0),
        z=LinearAxis(name="Z", min_mm=-120.0, max_mm=60.0, max_feed_mm_min=3000.0),
        # Berceau A : course dissymetrique, typique d'un berceau maker.
        a=RotaryAxis(name="A", min_deg=-120.0, max_deg=30.0, max_feed_deg_min=3600.0),
        # Plateau C : continu mecaniquement, mais en mode INDEXED a ce jalon.
        c=RotaryAxis(name="C", min_deg=-360.0, max_deg=360.0, continuous=True,
                     max_feed_deg_min=7200.0, max_rpm=1500.0),
        c_mode=CAxisMode.INDEXED,
        pivot_a=[0.0, 0.0, -40.0],
        pivot_c=[0.0, 0.0, 0.0],
        collision_volumes=[
            CollisionVolume(name="plateau C", frame="table_C", kind="cylinder",
                            base=[0, 0, -12.0], axis=[0, 0, 1], radius=75.0, height=12.0),
            CollisionVolume(name="berceau A", frame="cradle_A", kind="box",
                            lo=[-110.0, -95.0, -70.0], hi=[110.0, -80.0, 40.0]),
        ],
    )
