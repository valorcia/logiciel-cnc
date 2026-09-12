"""Setup : l'etat physique complet a partir duquel un plan devient executable.

Le point critique (ADR-001 / D9) : toute approbation de securite est liee au
``setup_hash``. Si quoi que ce soit change — bridage deplace, outil remesure,
origine piece corrigee — le hash change et l'approbation tombe. Il n'existe
aucun chemin permettant de rejouer un G-code approuve sous un autre setup.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum

import numpy as np
from pydantic import BaseModel, Field

from ..stock_engine.stock import Stock
from ..tool_model.assembly import ToolAssembly
from .machine import MachineKinematics


class FixtureKind(str, Enum):
    VISE = "vise"
    CLAMP = "clamp"
    CHUCK = "chuck"
    SOFT_JAWS = "soft_jaws"
    FIXTURE_PLATE = "fixture_plate"
    CUSTOM_STEP = "custom_step"


class Fixture(BaseModel):
    """Element de bridage, exprime dans le repere PIECE.

    Un bridage est un obstacle de premiere importance : sur une machine 5 axes
    table/table, il tourne avec la piece et entre donc dans le champ de l'outil
    pour certaines orientations. C'est souvent lui, et non la piece, qui limite
    l'accessibilite.
    """

    name: str
    kind: FixtureKind
    lo: list[float] | None = None
    hi: list[float] | None = None
    step_path: str | None = None
    #: Zone interdite d'usinage autour du bridage (mm). Marge de securite dure.
    keepout_mm: float = Field(3.0, ge=0.0)

    def surface_samples(self, spacing: float = 2.0) -> tuple[np.ndarray, np.ndarray]:
        """Peau du bridage : boite analytique, ou STEP si un fichier est fourni.

        Un bridage reel (equerre, montage imprime, mors doux usines) n'est pas
        une boite. Le forcer a en etre une surestime son encombrement et fait
        rejeter des orientations valides — ou pire, le sous-estime si on ajuste
        la boite « au plus juste » a la main.
        """
        if self.step_path:
            from ..geometry_core import brep

            s = brep.sample_surface(brep.load_step(self.step_path), spacing=spacing)
            return s.points, s.normals
        if self.lo is None or self.hi is None:
            raise ValueError(
                f"bridage '{self.name}': ni boite (lo/hi) ni step_path fourni"
            )
        from ..stock_engine.stock import _box_samples

        return _box_samples(np.array(self.lo, float), np.array(self.hi, float), spacing)


class WorkOffset(BaseModel):
    """Origine piece dans le repere machine (G54...G59).

    Mesuree au palpeur (``probing_service``), jamais saisie a la main sans
    verification : c'est l'entree qui decale toute la gamme si elle est fausse.
    """

    name: str = "G54"
    origin_mm: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation_deg: float = 0.0
    probed: bool = False
    probe_uncertainty_mm: float | None = None


class Setup(BaseModel):
    """Montage complet : machine + piece + brut + bridages + outils + origine."""

    setup_id: str
    machine: MachineKinematics
    part_step_path: str
    stock: Stock
    fixtures: list[Fixture] = Field(default_factory=list)
    tools: list[ToolAssembly] = Field(default_factory=list)
    work_offset: WorkOffset = Field(default_factory=WorkOffset)

    #: Position de l'origine PIECE dans le repere du plateau C.
    #:
    #: Laisser (0, 0, 0) pose la piece a l'origine exacte du plateau, c'est-a-dire
    #: ENCASTREE dans lui : le plateau occupe z < 0 et la piece demarrerait a sa
    #: surface. Une piece reelle repose sur des cales, une equerre ou un plateau
    #: martyr, donc plus haut. Ne pas renseigner ce champ fait rejeter des
    #: orientations parfaitement saines, l'outil etant declare en collision avec
    #: un plateau qu'il n'approche pas.
    part_to_table_mm: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])

    #: Hash du dossier de calibration sous lequel ce montage est approuve.
    #:
    #: Entre dans l'empreinte, donc une RECALIBRATION invalide une approbation
    #: exactement comme un changement de bridage. Ce n'est pas une precaution
    #: de forme : la calibration change les pivots A et C, donc la geometrie
    #: contre laquelle les collisions ont ete verifiees. Une approbation portee
    #: par une geometrie qui a change depuis est une approbation fausse.
    #:
    #: Laisser vide signifie « non renseigne » et non « pas de calibration » :
    #: le post-processeur refuse alors seulement sur l'etat de la geometrie.
    calibration_hash: str = ""

    notes: str = ""

    def fingerprint(self) -> dict:
        """Donnees canoniques dont depend la validite d'une approbation.

        Volontairement exhaustif sur la geometrie et les cotes, et volontairement
        exclusif de tout ce qui est cosmetique (``notes``, ``description``) :
        un commentaire ne doit pas invalider une approbation, une cote si.
        """
        return {
            "setup_id": self.setup_id,
            "machine": {
                "id": self.machine.machine_id,
                "limits": self.machine.describe_limits(),
                "pivot_a": self.machine.pivot_a,
                "pivot_c": self.machine.pivot_c,
                "c_mode": self.machine.c_mode.value,
            },
            "part": self.part_step_path,
            "stock": self.stock.model_dump(exclude={"material"}),
            "stock_material": self.stock.material,
            "fixtures": [f.model_dump() for f in self.fixtures],
            "tools": [
                {
                    "id": t.tool_id,
                    "d": t.diameter,
                    "gauge": t.gauge_length,
                    "segments": [s.model_dump() for s in t.segments],
                }
                for t in self.tools
            ],
            "work_offset": self.work_offset.model_dump(),
            "part_to_table": self.part_to_table_mm,
            "calibration": self.calibration_hash,
        }

    def setup_hash(self) -> str:
        """SHA-256 du fingerprint canonique. Toute approbation y est liee."""
        blob = json.dumps(self.fingerprint(), sort_keys=True, separators=(",", ":"),
                          default=str).encode()
        return hashlib.sha256(blob).hexdigest()

    def part_to_table(self, p_part: np.ndarray) -> np.ndarray:
        """Transporte un point du repere PIECE vers le repere du plateau C."""
        return np.asarray(p_part, dtype=np.float64) + np.asarray(self.part_to_table_mm,
                                                                 dtype=np.float64)

    @property
    def mount_offset(self) -> np.ndarray:
        return np.asarray(self.part_to_table_mm, dtype=np.float64)

    def tool(self, tool_id: str) -> ToolAssembly:
        for t in self.tools:
            if t.tool_id == tool_id:
                return t
        raise KeyError(f"outil '{tool_id}' absent du setup {self.setup_id}")

    def obstacle_samples(self, spacing: float = 2.0) -> tuple[np.ndarray, np.ndarray]:
        """Obstacles NON-piece (brut + bridages), en repere piece.

        La piece elle-meme est ajoutee separement par l'appelant : elle joue un
        role different (on l'approche volontairement, avec une surepaisseur).
        """
        pts, nrm = [], []
        p, n = self.stock.surface_samples(spacing)
        pts.append(p); nrm.append(n)
        for f in self.fixtures:
            p, n = f.surface_samples(spacing)
            pts.append(p); nrm.append(n)
        return np.vstack(pts), np.vstack(nrm)
