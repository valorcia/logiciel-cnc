"""Modele d'outil COMPLET : bec, goujure, col, tige, porte-outil, nez de broche.

C'est le differenciateur produit (ADR-001 / D4). Un outil n'est jamais un rayon
et une longueur : c'est une **pile de troncons coaxiaux**, chacun avec son role.

Repere outil : origine au **bout de l'outil** (TCP), axe ``+z`` vers la broche.
Un troncon occupe ``z in [z_start, z_end]`` avec un rayon lineaire par morceaux.
Cette forme donne le test d'appartenance vectorisable ``r < R(z)`` qui rend le
solveur d'accessibilite tenable sur Raspberry Pi 5.
"""

from __future__ import annotations

import math
from enum import Enum

import numpy as np
from pydantic import BaseModel, Field, field_validator, model_validator


class SegmentRole(str, Enum):
    """Role d'un troncon. Determine la GRAVITE d'une collision, pas seulement son existence."""

    CUTTING = "cutting"            # arete de coupe : contact normal, gouge si hors passe
    FLUTE = "flute"                # corps goujure (diametre nominal, pas de coupe utile en bout)
    NECK = "neck"                  # col degage : contact = defaut de degagement
    SHANK = "shank"                # tige : contact = collision franche
    HOLDER = "holder"              # porte-outil : contact = collision franche
    SPINDLE_NOSE = "spindle_nose"  # nez de broche : contact = collision grave


#: Roles autorises a toucher la matiere pendant la coupe. Tout le reste est une collision.
CUTTING_ROLES = frozenset({SegmentRole.CUTTING})


class ToolSegment(BaseModel):
    """Troncon coaxial : cylindre si r_start == r_end, cone tronque sinon."""

    role: SegmentRole
    z_start: float = Field(..., description="mm depuis le bec de l'outil")
    z_end: float = Field(..., description="mm depuis le bec de l'outil")
    r_start: float = Field(..., ge=0.0)
    r_end: float = Field(..., ge=0.0)
    label: str = ""

    @model_validator(mode="after")
    def _check(self) -> "ToolSegment":
        if self.z_end <= self.z_start:
            raise ValueError(f"troncon '{self.label}': z_end doit etre > z_start")
        return self

    @property
    def length(self) -> float:
        return self.z_end - self.z_start

    @property
    def r_max(self) -> float:
        return max(self.r_start, self.r_end)

    def radius_at(self, z: float | np.ndarray) -> np.ndarray:
        """Rayon interpole. Hors du troncon, retourne -inf (jamais en collision)."""
        z = np.asarray(z, dtype=np.float64)
        t = (z - self.z_start) / self.length
        r = self.r_start + t * (self.r_end - self.r_start)
        return np.where((z >= self.z_start) & (z <= self.z_end), r, -np.inf)


class ToolAssembly(BaseModel):
    """Ensemble outil + porte-outil + nez de broche, monte et mesure.

    ``gauge_length`` est la cote de jauge reelle : c'est elle qui decide si le
    porte-outil degage ou non. Une assemblage mal mesuree produit un plan
    valide en simulation et faux sur la machine ; le hash du Setup lie donc
    l'approbation a cette valeur.
    """

    tool_id: str
    description: str = ""
    segments: list[ToolSegment]

    diameter: float = Field(..., gt=0.0, description="diametre nominal de coupe, mm")
    flute_count: int = Field(2, ge=1)
    corner_radius: float = Field(0.0, ge=0.0, description="0 = bout droit ; d/2 = hemispherique")
    gauge_length: float = Field(..., gt=0.0, description="bec -> face de broche, mm")

    max_ramp_angle_deg: float = Field(3.0, ge=0.0, le=90.0)
    can_plunge: bool = False

    @field_validator("segments")
    @classmethod
    def _sorted_contiguous(cls, v: list[ToolSegment]) -> list[ToolSegment]:
        if not v:
            raise ValueError("ToolAssembly: au moins un troncon requis")
        v = sorted(v, key=lambda s: s.z_start)
        if abs(v[0].z_start) > 1e-6:
            raise ValueError("ToolAssembly: le premier troncon doit demarrer a z=0 (le bec)")
        for a, b in zip(v, v[1:]):
            if abs(b.z_start - a.z_end) > 1e-6:
                raise ValueError(
                    f"ToolAssembly: trou ou recouvrement entre '{a.label}' et '{b.label}' "
                    f"(z={a.z_end} vs {b.z_start}). La pile doit etre continue."
                )
        return v

    @model_validator(mode="after")
    def _check_gauge(self) -> "ToolAssembly":
        total = self.segments[-1].z_end
        if self.gauge_length > total + 1e-6:
            raise ValueError(
                f"gauge_length ({self.gauge_length}) depasse la pile modelisee ({total}). "
                "Le nez de broche ne serait pas modelise : refus, car le solveur "
                "conclurait a tort a l'absence de collision."
            )
        return self

    # -- geometrie derivee ------------------------------------------------

    @property
    def radius(self) -> float:
        return 0.5 * self.diameter

    @property
    def total_length(self) -> float:
        return self.segments[-1].z_end

    @property
    def cutting_length(self) -> float:
        """Longueur utile de coupe : borne la profondeur de passe admissible."""
        zs = [s.z_end for s in self.segments if s.role is SegmentRole.CUTTING]
        return max(zs) if zs else 0.0

    @property
    def max_radius(self) -> float:
        return max(s.r_max for s in self.segments)

    def profile(self, n: int = 256) -> tuple[np.ndarray, np.ndarray]:
        """Profil (z, r) echantillonne : sert au rendu et aux tests de regression."""
        z = np.linspace(0.0, self.total_length, n)
        return z, self.radius_profile(z)

    def radius_profile(self, z: np.ndarray) -> np.ndarray:
        """Rayon de l'enveloppe en chaque z. Vectorise sur tous les troncons."""
        z = np.asarray(z, dtype=np.float64)
        r = np.full(z.shape, -np.inf)
        for s in self.segments:
            r = np.maximum(r, s.radius_at(z))
        return r

    def segment_role_at(self, z: float) -> SegmentRole | None:
        for s in self.segments:
            if s.z_start - 1e-9 <= z <= s.z_end + 1e-9:
                return s.role
        return None

    def envelope_radius_above(self, z: float) -> float:
        """Rayon maximal de l'outil AU-DESSUS de la cote z.

        Utilise par le pre-filtre d'accessibilite : majore l'encombrement de
        tout ce qui suit le point de contact le long de l'axe.
        """
        zz = np.linspace(z, self.total_length, 128)
        r = self.radius_profile(zz)
        r = r[np.isfinite(r)]
        return float(r.max()) if r.size else 0.0

    def describe(self) -> str:
        lines = [
            f"ToolAssembly {self.tool_id} — D{self.diameter} Z{self.flute_count} "
            f"jauge {self.gauge_length} mm"
        ]
        for s in self.segments:
            shape = "cyl" if abs(s.r_start - s.r_end) < 1e-9 else "cone"
            lines.append(
                f"  [{s.role.value:12s}] z {s.z_start:7.2f}..{s.z_end:7.2f}  "
                f"r {s.r_start:6.2f}->{s.r_end:6.2f}  {shape}  {s.label}"
            )
        return "\n".join(lines)


def build_endmill(
    tool_id: str,
    diameter: float,
    flute_length: float,
    shank_diameter: float | None = None,
    stickout: float = 45.0,
    holder_type: str = "ER32",
    corner_radius: float = 0.0,
    flute_count: int = 3,
    neck_diameter: float | None = None,
    neck_length: float = 0.0,
) -> ToolAssembly:
    """Construit un assemblage fraise 2 tailles + pince + nez de broche.

    ``stickout`` est la longueur libre hors porte-outil. C'est le levier
    principal de l'accessibilite : plus il est grand, plus l'outil degage,
    moins il est rigide. Le compromis est explicite et remonte a l'UI.
    """
    shank_diameter = shank_diameter or diameter
    holder = _HOLDERS.get(holder_type)
    if holder is None:
        raise ValueError(f"porte-outil inconnu : {holder_type}. Connus : {sorted(_HOLDERS)}")

    segs: list[ToolSegment] = []
    z = 0.0

    r = diameter / 2.0
    cr = min(max(corner_radius, 0.0), r)
    if cr > 0.0:
        # Le BEC doit exister dans la geometrie de collision, pas seulement dans
        # le calcul du TCP. Modelise en cylindre droit, une hemispherique se
        # comporterait comme une fraise a bout droit : son talon serait declare
        # en gouge des qu'on l'incline, c'est-a-dire dans tous les cas ou l'on
        # se sert d'une hemispherique.
        segs.extend(_tip_segments(r, cr))
        z = cr

    body = flute_length - z
    if body <= 0.0:
        raise ValueError(
            f"flute_length ({flute_length}) doit depasser le rayon de bec ({cr})")
    segs.append(ToolSegment(role=SegmentRole.CUTTING, z_start=z, z_end=z + body,
                            r_start=r, r_end=r, label="arete de coupe"))
    z += body

    if neck_length > 0.0:
        nd = neck_diameter or diameter * 0.9
        segs.append(ToolSegment(role=SegmentRole.NECK, z_start=z, z_end=z + neck_length,
                                r_start=nd / 2, r_end=nd / 2, label="col degage"))
        z += neck_length

    shank_len = stickout - z
    if shank_len <= 0.0:
        raise ValueError(
            f"stickout ({stickout}) trop court : coupe + col font deja {z} mm. "
            "Un outil sans tige hors pince n'est pas montable."
        )
    segs.append(ToolSegment(role=SegmentRole.SHANK, z_start=z, z_end=z + shank_len,
                            r_start=shank_diameter / 2, r_end=shank_diameter / 2, label="tige"))
    z += shank_len

    for (ln, r0, r1, label) in holder["stages"]:
        segs.append(ToolSegment(role=SegmentRole.HOLDER, z_start=z, z_end=z + ln,
                                r_start=r0, r_end=r1, label=label))
        z += ln

    segs.append(ToolSegment(role=SegmentRole.SPINDLE_NOSE, z_start=z, z_end=z + 40.0,
                            r_start=holder["nose_radius"], r_end=holder["nose_radius"],
                            label="nez de broche"))
    z += 40.0

    return ToolAssembly(
        tool_id=tool_id,
        description=f"Fraise D{diameter} L{flute_length} / {holder_type}",
        segments=segs,
        diameter=diameter,
        flute_count=flute_count,
        corner_radius=corner_radius,
        gauge_length=z,
        can_plunge=(flute_count <= 2),
    )


def _tip_segments(radius: float, corner_radius: float, n: int = 8) -> list[ToolSegment]:
    """Approxime le bec torique/hemispherique par ``n`` troncons de cone.

    Le profil du bec est un quart de cercle de rayon ``cr`` centre a
    ``(r - cr, cr)`` dans le plan (rayon, z). On l'echantillonne en cordes.
    Pour un bec de 3 mm en 8 troncons, l'ecart au cercle exact vaut environ
    0,015 mm — un ordre de grandeur sous la resolution du test par nuage de
    points, donc sans effet sur les conclusions du solveur.
    """
    segs: list[ToolSegment] = []
    ang = np.linspace(-np.pi / 2.0, 0.0, n + 1)
    zc = corner_radius + corner_radius * np.sin(ang)
    rc = (radius - corner_radius) + corner_radius * np.cos(ang)
    for i in range(n):
        z0, z1 = float(zc[i]), float(zc[i + 1])
        if z1 - z0 < 1e-9:
            continue
        segs.append(ToolSegment(role=SegmentRole.CUTTING, z_start=z0, z_end=z1,
                                r_start=float(rc[i]), r_end=float(rc[i + 1]),
                                label="bec"))
    if segs:
        segs[0] = segs[0].model_copy(update={"z_start": 0.0})
    return segs


#: Geometries de porte-outils. (longueur, r_debut, r_fin, libelle).
#: Valeurs realistes d'ordre de grandeur — a remplacer par les cotes reelles du
#: kit avant tout usinage : voir docs/testplan (T-TOOL-1).
_HOLDERS: dict[str, dict] = {
    "ER16": {"stages": [(6.0, 11.0, 13.5, "ecrou ER16"), (28.0, 13.5, 17.0, "corps ER16")],
             "nose_radius": 30.0},
    "ER32": {"stages": [(8.0, 16.0, 21.0, "ecrou ER32"), (35.0, 21.0, 25.0, "corps ER32")],
             "nose_radius": 40.0},
    "ISO20": {"stages": [(10.0, 14.0, 19.0, "nez ISO20"), (30.0, 19.0, 24.5, "corps ISO20")],
              "nose_radius": 35.0},
}


def build_ballnose(tool_id: str, diameter: float, flute_length: float, **kw) -> ToolAssembly:
    """Fraise hemispherique : bec de rayon d/2, modelise geometriquement."""
    kw.pop("corner_radius", None)
    t = build_endmill(tool_id, diameter, flute_length, corner_radius=diameter / 2.0, **kw)
    return t.model_copy(update={"can_plunge": True,
                                "description": f"Hemispherique D{diameter}"})


def tilt_axis_from_lead_tilt(
    normal: np.ndarray, feed_dir: np.ndarray, lead_deg: float, tilt_deg: float
) -> np.ndarray:
    """Axe outil obtenu en inclinant la normale de ``lead`` (dans le sens d'avance)
    puis de ``tilt`` (perpendiculairement).

    Convention CAM classique : ``lead`` positif = outil penche en avant (tire la
    matiere), ``tilt`` = deport lateral. Sert a exprimer une preference
    technologique que l'orientation solver traite comme un cout, pas comme une
    contrainte dure.
    """
    from ..geometry_core.types import normalize

    n = normalize(normal)
    f = normalize(feed_dir - np.dot(feed_dir, n) * n)  # avance projetee dans le plan tangent
    s = np.cross(n, f)

    la, ti = math.radians(lead_deg), math.radians(tilt_deg)
    d = (math.cos(la) * math.cos(ti) * n
         + math.sin(la) * math.cos(ti) * f
         + math.sin(ti) * s)
    return normalize(d)
