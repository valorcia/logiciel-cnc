"""Interfaces du planificateur de gammes. NON IMPLEMENTE au jalon M1.

Ce fichier fixe les CONTRATS pour que les modules aval puissent etre ecrits et
testes contre une interface stable. Les corps levent ``NotImplementedError`` :
un stub qui renvoie une valeur plausible est pire qu'un stub qui echoue, parce
qu'il laisse croire que la chaine fonctionne.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

import numpy as np

from ..machine_model.setup import Setup
from ..tool_model.assembly import ToolAssembly


class Kinematic(str, Enum):
    """Cinematique de coupe d'une operation. JAMAIS melangee dans un meme bloc
    de trajectoire (ADR-001 / D8)."""

    MILLING_3AXIS = "fraisage_3axes"
    MILLING_3PLUS2 = "fraisage_3+2"
    MILLING_5AXIS = "fraisage_5axes"
    TURNING = "tournage"


@dataclass
class Toolpath:
    """Trajectoire brute : points de contact et normales, sans orientation.

    L'orientation est ajoutee par ``orientation_solver``. Separer les deux est
    delibere : cela permet de tester le generateur de passes sans le solveur
    5 axes, et inversement.
    """

    points: np.ndarray            # (P,3) points de contact, repere piece
    normals: np.ndarray           # (P,3)
    feed_dirs: np.ndarray | None = None
    depth_of_cut: float = 0.0
    is_rapid: np.ndarray | None = None
    label: str = ""


@dataclass
class Operation:
    """Une operation de la gamme."""

    op_id: str
    kinematic: Kinematic
    tool: ToolAssembly
    toolpath: Toolpath
    spindle_rpm: float = 0.0
    feed_mm_min: float = 0.0
    coolant: bool = False
    notes: str = ""


@dataclass
class ProcessPlan:
    """Gamme complete : suite d'operations ordonnee.

    ``requires_kinematic_switch`` marque les frontieres ou la machine change de
    mode (indexation <-> tournage). Chacune impose un point de synchronisation
    explicite et une nouvelle validation ; elles ne peuvent pas etre franchies
    silencieusement.
    """

    plan_id: str
    setup: Setup
    operations: list[Operation] = field(default_factory=list)
    requires_kinematic_switch: list[int] = field(default_factory=list)

    def kinematics_used(self) -> set[Kinematic]:
        return {o.kinematic for o in self.operations}

    def is_hybrid(self) -> bool:
        k = self.kinematics_used()
        return Kinematic.TURNING in k and len(k) > 1


class ToolpathBackend(Protocol):
    """Backend generateur de passes.

    C'est ici que ``OpenCAMLib`` s'insere comme ADAPTER pour les passes 3 axes
    et 3+2 indexees (ADR-001 / D3) : excellent sur son domaine, et hors sujet
    au-dela, puisqu'il ne connait ni porte-outil ni orientation.
    """

    name: str

    def supports(self, kinematic: Kinematic) -> bool: ...

    def generate(self, setup: Setup, tool: ToolAssembly, region, params: dict) -> Toolpath: ...


class StrategyPlanner(Protocol):
    """Choisit les operations, les outils et les cinematiques."""

    def plan(self, setup: Setup) -> ProcessPlan: ...


def plan_process(setup: Setup) -> ProcessPlan:
    raise NotImplementedError(
        "strategy_planner non implemente au jalon M1. Prerequis : stock_engine "
        "avec suivi de matiere enlevee, et subtractive_slicer. "
        "Voir docs/adr/ADR-001-architecture-fondatrice.md §6."
    )
