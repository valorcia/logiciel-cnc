"""Dossier de calibration : ce qui a ete mesure, et ce qu'on a le droit d'en dire.

Le dossier entre dans le hash du setup (``machine_model.setup``). Ce n'est pas
decoratif : une recalibration change la machine, donc invalide une approbation
de securite, exactement comme un changement de montage. Une approbation portee
par une geometrie qui a change depuis est une approbation fausse.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, Field

from ..machine_model.geometry import MachineGeometry
from .interfaces import CalibrationReport, CalibrationStep
from .procedures import HARDWARE_ONLY


class CalibrationRecord(BaseModel):
    """Geometrie mesuree d'une machine, avec la trace de ce qui l'a produite."""

    machine_id: str
    geometry: MachineGeometry
    steps_passed: list[str] = Field(default_factory=list)
    steps_blocking: list[str] = Field(default_factory=list)
    #: Incertitude de position a la piece pour un point a 100 mm des pivots.
    #: Grandeur de reference pour comparer deux calibrations, et la seule qui
    #: soit directement comparable a une tolerance de piece.
    uncertainty_at_100mm_mm: float = 0.0
    notes: str = ""

    @property
    def geometry_complete(self) -> bool:
        """Les etapes GEOMETRIQUES sont faites : la cinematique n'est plus provisoire.

        Ne dit rien de la precision obtenue — pour cela il faut la piece
        d'epreuve, qui exige la machine.
        """
        need = {s.name for s in CalibrationStep if s not in HARDWARE_ONLY}
        return need.issubset(set(self.steps_passed)) and self.geometry.measured

    @property
    def qualified(self) -> bool:
        """La machine a ete qualifiee sur piece d'epreuve MESUREE."""
        return CalibrationStep.QUALIFICATION_PART.name in self.steps_passed

    def fingerprint(self) -> dict:
        """Donnees canoniques dont depend la validite d'une approbation."""
        g = self.geometry
        return {
            "machine_id": self.machine_id,
            "measured": g.measured,
            "a_offset": [round(v, 6) for v in g.a_axis.offset_mm],
            "a_direction": [round(v, 9) for v in g.a_axis.direction],
            "c_offset": [round(v, 6) for v in g.c_axis.offset_mm],
            "c_direction": [round(v, 9) for v in g.c_axis.direction],
            "squareness": [round(g.squareness_xy_deg, 6),
                           round(g.squareness_xz_deg, 6),
                           round(g.squareness_yz_deg, 6)],
            "scale_ppm": [round(g.scale_x_ppm, 3), round(g.scale_y_ppm, 3),
                          round(g.scale_z_ppm, 3)],
            "homing": round(g.homing_repeatability_mm, 6),
            "steps_passed": sorted(self.steps_passed),
        }

    def calibration_hash(self) -> str:
        blob = json.dumps(self.fingerprint(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def tolerance_statement(self) -> str:
        """Ce qu'on a le droit d'affirmer. Aucun autre chiffre ne doit sortir.

        Regle non negociable depuis M1 (ADR-001 / R3) : **+/-0,02 mm n'est pas
        un acquis.** Cette methode est le seul endroit autorise a enoncer une
        precision, et elle refuse de le faire tant que la piece d'epreuve n'a
        pas ete usinee ET mesuree.
        """
        if not self.geometry.measured:
            return ("Geometrie NON MESUREE : la cinematique est provisoire, "
                    "aucune tolerance ne peut etre annoncee et aucun programme "
                    "ne doit etre genere.")
        if not self.geometry_complete:
            return (f"Geometrie partielle ({len(self.steps_blocking)} etapes "
                    f"bloquantes : {', '.join(self.steps_blocking[:4])}). "
                    "Aucune tolerance annoncable.")
        if not self.qualified:
            return (f"Geometrie mesuree, machine NON QUALIFIEE. Incertitude de "
                    f"position calculee a 100 mm des pivots : "
                    f"{self.uncertainty_at_100mm_mm * 1000:.1f} um (pire cas, "
                    "hors effets thermiques, flexion et hysteresis). C'est un "
                    "budget geometrique, PAS une tolerance de piece : celle-ci "
                    "exige la piece d'epreuve usinee puis mesuree.")
        return (f"Machine qualifiee. Budget geometrique a 100 mm : "
                f"{self.uncertainty_at_100mm_mm * 1000:.1f} um. La tolerance "
                "annoncable est celle mesuree sur la piece d'epreuve, non ce "
                "budget.")

    def describe(self) -> str:
        return (f"Dossier de calibration '{self.machine_id}' "
                f"[{self.calibration_hash()[:12]}]\n"
                f"  {self.geometry.describe()}\n"
                f"  etapes reussies : {len(self.steps_passed)} ; "
                f"bloquantes : {', '.join(self.steps_blocking) or 'aucune'}\n"
                f"  {self.tolerance_statement()}")


def record_from_report(machine_id: str, geometry: MachineGeometry,
                       report: CalibrationReport) -> CalibrationRecord:
    passed = [r.step.name for r in report.results if r.passed]
    blocking = [r.step.name for r in report.results if not r.passed]
    unc = (geometry.position_uncertainty_mm(100.0) if geometry.measured else 0.0)
    return CalibrationRecord(
        machine_id=machine_id, geometry=geometry,
        steps_passed=passed, steps_blocking=blocking,
        uncertainty_at_100mm_mm=float(unc),
    )
