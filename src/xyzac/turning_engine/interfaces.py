"""Tournage sur l'axe C. Detection implementee, generation NON implementee.

L'axe C a deux natures (ADR-001 / D8) : axe d'indexation, et broche de tournage.
Ce module porte la seconde. Ce qui existe au jalon M1 : l'EVALUATION d'une piece
comme candidate au tournage. Ce qui n'existe pas : la generation de trajectoires
de tournage, et c'est volontaire — produire des passes de tournage sans
simulation dediee reviendrait a franchir la frontiere de securite.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..feature_engine.revolution import RevolutionRegion, detect_revolution_regions
from ..machine_model.machine import CAxisMode, MachineKinematics


@dataclass
class TurningCandidate:
    """Verdict sur l'aptitude au tournage d'une piece donnee."""

    suitable: bool
    reason: str
    regions: list[RevolutionRegion]
    aligned_regions: list[RevolutionRegion]
    revolution_fraction: float

    def describe(self) -> str:
        lines = [f"Tournage : {'CANDIDAT' if self.suitable else 'NON RETENU'} — {self.reason}",
                 f"  regions de revolution : {len(self.regions)} "
                 f"(dont {len(self.aligned_regions)} alignees sur l'axe C)",
                 f"  part de revolution    : {self.revolution_fraction * 100:.1f} %"]
        for r in self.aligned_regions:
            lines.append(f"    {r.describe()}")
        return "\n".join(lines)


def evaluate_turning(
    shape, machine: MachineKinematics, *,
    c_axis_dir: np.ndarray | None = None,
    min_fraction: float = 0.30,
    align_tol_deg: float = 1.0,
) -> TurningCandidate:
    """Decide si une piece merite une gamme de tournage, et le justifie.

    Trois conditions cumulatives, toutes necessaires :
      1. la machine doit POUVOIR tourner (axe C continu, vitesse declaree) ;
      2. il doit exister des regions de revolution alignees sur l'axe C ;
      3. ces regions doivent representer une part significative de la piece.

    La condition 2 est celle qui rejette le cas C15 du corpus : un cylindre
    lateral est un percage, et le tourner ferait tournoyer la piece autour du
    mauvais axe.
    """
    c_axis_dir = np.array([0.0, 0.0, 1.0]) if c_axis_dir is None else np.asarray(c_axis_dir)

    regions = detect_revolution_regions(shape)
    aligned = [r for r in regions if r.is_aligned_with(c_axis_dir, align_tol_deg)]
    frac = sum(r.area_fraction for r in aligned)

    if not machine.c.continuous or not machine.c.max_rpm:
        return TurningCandidate(False, "l'axe C de cette machine n'est pas declare "
                                       "capable de rotation continue", regions, aligned, frac)
    if not aligned:
        why = ("aucune region de revolution" if not regions else
               "des regions de revolution existent mais AUCUNE n'est alignee sur l'axe C "
               "(ce sont des percages ou des formes laterales, pas du tournage)")
        return TurningCandidate(False, why, regions, aligned, frac)
    if frac < min_fraction:
        return TurningCandidate(False, f"revolution alignee trop marginale "
                                       f"({frac * 100:.1f} % < {min_fraction * 100:.0f} %)",
                                regions, aligned, frac)
    return TurningCandidate(True, f"{frac * 100:.1f} % de la piece est de revolution "
                                  f"autour de l'axe C", regions, aligned, frac)


def plan_turning(candidate: TurningCandidate, machine: MachineKinematics):
    raise NotImplementedError(
        "Generation de trajectoires de tournage non implementee au jalon M1.\n"
        "Prerequis BLOQUANT : en mode CONTINUOUS_SPINDLE, les obstacles ne sont "
        "plus quasi statiques dans le repere piece, et les hypotheses du "
        "collision_engine tombent. Il faut un modele de collision dedie au "
        "tournage AVANT toute generation. Voir ADR-001 / D8."
    )


def require_c_mode(machine: MachineKinematics, mode: CAxisMode) -> None:
    """Verrou de changement de cinematique.

    Le passage indexation <-> tournage n'est pas un reglage : c'est une
    transition d'etat qui invalide l'approbation en cours.
    """
    if machine.c_mode is not mode:
        raise RuntimeError(
            f"mode de l'axe C incompatible : {machine.c_mode.value} requis {mode.value}. "
            "Le changement de mode invalide l'approbation et exige une nouvelle simulation."
        )
