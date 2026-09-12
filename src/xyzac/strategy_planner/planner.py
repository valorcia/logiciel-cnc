"""Planificateur de gammes : de la piece a la suite d'operations.

C'est ici que se joue la promesse produit — « l'utilisateur ne programme pas du
CAM ». Il n'y a pas d'operation a choisir, pas de poche a designer : le planner
decide seul quelles indexations utiliser, dans quel ordre, et avec quels outils.

Methode : **couverture gloutonne du volume a enlever par des indexations**.

  1. proposer des directions candidates (axes du brut, normales dominantes) ;
  2. ne garder que celles que la cinematique XYZAC atteint reellement ;
  3. choisir la direction qui voit le plus de matiere restante ;
  4. trancher, simuler l'enlevement, mettre l'etat matiere a jour ;
  5. recommencer tant qu'une direction apporte un gain significatif.

Le glouton est assume. Le probleme sous-jacent est une couverture d'ensembles,
donc NP-difficile ; un glouton sur la fonction « volume atteignable » — qui est
sous-modulaire — a une garantie classique de 1 - 1/e. Surtout, il est
**deterministe et explicable** : on peut montrer a l'utilisateur pourquoi telle
indexation a ete retenue, et combien elle apporte. Un optimiseur global serait
meilleur de quelques pourcents et impossible a justifier devant une piece ratee.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..geometry_core import brep
from ..geometry_core.types import normalize
from ..kinematics_solver.solver import KinematicsSolver
from ..machine_model.setup import Setup
from ..stock_engine.material import MaterialState
from ..subtractive_slicer.slicer import (
    SliceResult,
    simulate_removal,
    slice_for_direction,
    toolpath_points,
)
from ..tool_model.assembly import ToolAssembly
from .interfaces import Kinematic, Operation, ProcessPlan, Toolpath


@dataclass
class DirectionCandidate:
    """Une indexation candidate, avec ce qu'elle apporte."""

    direction: np.ndarray
    a_deg: float
    c_deg: float
    reachable_mm3: float
    label: str = ""

    def describe(self) -> str:
        return (f"{self.label or 'dir'} {np.round(self.direction, 3)} "
                f"(A={self.a_deg:7.2f} C={self.c_deg:8.2f}) : "
                f"{self.reachable_mm3:8.0f} mm3 atteignables")


@dataclass
class PlanReport:
    """Trace de la decision. Un plan sans justification n'est pas auditable."""

    candidates: list[DirectionCandidate] = field(default_factory=list)
    chosen: list[DirectionCandidate] = field(default_factory=list)
    removed_per_step: list[float] = field(default_factory=list)
    initial_removable_mm3: float = 0.0
    final_removable_mm3: float = 0.0
    unreachable_mm3: float = 0.0
    gouged_voxels: int = 0

    @property
    def removed_fraction(self) -> float:
        if self.initial_removable_mm3 <= 0:
            return 1.0
        return 1.0 - self.final_removable_mm3 / self.initial_removable_mm3

    def describe(self) -> str:
        lines = [
            f"Gamme : {len(self.chosen)} indexation(s) retenue(s) sur "
            f"{len(self.candidates)} candidates evaluees",
            f"  matiere a enlever : {self.initial_removable_mm3:.0f} mm3",
            f"  enlevee           : {self.removed_fraction * 100:.1f} % "
            f"({self.initial_removable_mm3 - self.final_removable_mm3:.0f} mm3)",
            f"  restante          : {self.final_removable_mm3:.0f} mm3 "
            f"(dont {self.unreachable_mm3:.0f} mm3 qu'aucune indexation candidate ne voit)",
        ]
        if self.gouged_voxels:
            lines.append(f"  ATTENTION : {self.gouged_voxels} voxels proteges touches")
        for c, vol in zip(self.chosen, self.removed_per_step):
            lines.append(f"    {c.describe()}  -> a enleve {vol:.0f} mm3")
        return "\n".join(lines)


def candidate_directions(
    shape, setup: Setup, *, include_face_normals: bool = True,
    min_face_area: float = 50.0, max_candidates: int = 14,
) -> list[np.ndarray]:
    """Directions d'indexation a envisager.

    Les six axes du brut sont toujours proposes : ce sont les prises naturelles
    d'un montage, et elles couvrent l'essentiel des pieces prismatiques. On y
    ajoute les normales des faces significatives, sans quoi une face inclinee
    n'aurait jamais d'indexation qui la regarde de face — et serait usinee en
    rampe par une direction voisine, avec l'etat de surface correspondant.
    """
    dirs = [np.array(v, dtype=np.float64) for v in
            ((0, 0, 1), (0, 0, -1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0))]

    if include_face_normals:
        samples = brep.sample_surface(shape, spacing=2.0)
        for f in brep.face_info(shape):
            if f.area < min_face_area:
                continue
            m = samples.face_ids == f.index
            if not np.any(m):
                continue
            n = samples.normals[m].mean(axis=0)
            nn = float(np.linalg.norm(n))
            if nn < 0.7:
                continue  # face trop courbe pour avoir une normale representative
            d = n / nn
            if all(float(d @ e) < 0.985 for e in dirs):
                dirs.append(d)

    return dirs[:max_candidates]


def evaluate_candidates(
    directions: list[np.ndarray], material: MaterialState, setup: Setup,
) -> list[DirectionCandidate]:
    """Filtre par la cinematique, puis classe par volume atteignable.

    Une direction que le berceau n'atteint pas n'est pas une option, quelle que
    soit la matiere qu'elle verrait. Le filtre cinematique passe donc AVANT le
    classement, et non apres : classer d'abord donnerait un palmares dont la
    tete est irrealisable.
    """
    kin = KinematicsSolver(setup.machine)
    out: list[DirectionCandidate] = []
    for d in directions:
        d = normalize(d)
        # ``allow_singular=True`` : une operation INDEXEE bloque l'axe C, donc la
        # singularite A -> 0 ne gene rien. Voir KinematicsSolver.ik_best.
        sol = kin.ik_best(d, allow_singular=True)
        if sol is None:
            continue
        out.append(DirectionCandidate(
            direction=d, a_deg=sol.a_deg, c_deg=sol.c_deg,
            reachable_mm3=material.reachable_volume_mm3(d),
            label=_axis_label(d),
        ))
    out.sort(key=lambda c: -c.reachable_mm3)
    return out


def _axis_label(d: np.ndarray) -> str:
    names = {(0, 0, 1): "+Z", (0, 0, -1): "-Z", (1, 0, 0): "+X",
             (-1, 0, 0): "-X", (0, 1, 0): "+Y", (0, -1, 0): "-Y"}
    for k, v in names.items():
        if float(d @ np.array(k, dtype=float)) > 0.999:
            return v
    return "oblique"


def plan_roughing(
    shape, setup: Setup, material: MaterialState, tool: ToolAssembly,
    *,
    layer_thickness: float = 2.0,
    stepover_ratio: float = 0.45,
    point_spacing: float = 1.5,
    min_gain_mm3: float = 50.0,
    max_setups: int = 4,
) -> tuple[ProcessPlan, PlanReport]:
    """Construit une gamme d'ebauche par couverture gloutonne.

    ``min_gain_mm3`` arrete la boucle quand une indexation supplementaire
    n'apporte plus grand-chose. Sans ce seuil, le planner ajouterait des
    operations entieres pour quelques dizaines de mm3 — un changement
    d'indexation coûte une reprise, une revalidation et du temps machine, et
    n'est jamais gratuit.
    """
    report = PlanReport(initial_removable_mm3=float(material.removable().sum())
                        * material.grid.voxel_volume)
    plan = ProcessPlan(plan_id=f"gamme-{setup.setup_id}", setup=setup)

    dirs = candidate_directions(shape, setup)
    report.candidates = evaluate_candidates(dirs, material, setup)
    # Vivier de travail, distinct de la liste rapportee : celle-ci doit rester
    # l'ensemble des candidates EVALUEES, faute de quoi le calcul final de la
    # matiere « vue par aucune direction » ne porterait plus que sur les
    # directions retenues, et surestimerait grossierement l'inaccessible.
    pool = [c.direction for c in report.candidates]

    for step in range(max_setups):
        ranked = evaluate_candidates(pool, material, setup)
        if not ranked or ranked[0].reachable_mm3 < min_gain_mm3:
            break

        best = ranked[0]
        sl: SliceResult = slice_for_direction(
            material, best.direction, tool,
            layer_thickness=layer_thickness, stepover_ratio=stepover_ratio)
        if not sl.layers:
            # La direction voyait de la matiere mais l'outil n'a pas de position
            # valide : on la retire pour ne pas boucler dessus.
            pool = [d for d in pool if not np.allclose(d, best.direction)]
            continue

        stats = simulate_removal(material, sl, tool, point_spacing=point_spacing)
        report.gouged_voxels += stats.gouged_voxels

        if stats.removed_mm3 < min_gain_mm3:
            pool = [d for d in pool if not np.allclose(d, best.direction)]
            continue

        pts, nrm = toolpath_points(sl, point_spacing)
        plan.operations.append(Operation(
            op_id=f"ebauche-{step + 1}-{best.label}",
            kinematic=Kinematic.MILLING_3PLUS2,
            tool=tool,
            toolpath=Toolpath(points=pts, normals=nrm,
                              depth_of_cut=layer_thickness,
                              label=f"ebauche indexee {best.label}"),
            notes=(f"A={best.a_deg:.2f} C={best.c_deg:.2f} ; "
                   f"{len(sl.layers)} couches de {layer_thickness} mm ; "
                   f"{stats.removed_mm3:.0f} mm3"),
        ))
        report.chosen.append(best)
        report.removed_per_step.append(stats.removed_mm3)
        pool = [d for d in pool if not np.allclose(d, best.direction)]

    left = material.removable()
    vv = material.grid.voxel_volume
    report.final_removable_mm3 = float(left.sum()) * vv

    # Matiere qu'AUCUNE direction candidate ne voit : ce n'est pas un echec du
    # planner mais une contrainte de montage, et l'utilisateur doit le savoir.
    seen = np.zeros_like(left)
    for c in report.candidates:
        seen |= material.reachable_from(c.direction)
    report.unreachable_mm3 = float((left & ~seen).sum()) * vv

    return plan, report


def indexed_orientation_plan(points: np.ndarray, direction: np.ndarray,
                             setup: Setup, *, margin: float = 0.0):
    """Construit un ``OrientationPlan`` a orientation CONSTANTE.

    Une operation indexee n'a pas besoin du solveur d'orientation : l'axe outil
    est fixe par definition, et lancer un Viterbi sur des milliers de points
    pour redecouvrir une constante serait absurde. Le plan est donc construit
    directement, puis soumis au MEME validateur que n'importe quelle
    trajectoire — c'est la validation qui doit etre uniforme, pas le chemin qui
    y mene.
    """
    from ..orientation_solver.solver import OrientationPlan, OrientationSegment

    d = normalize(direction)
    n = len(points)
    kin = KinematicsSolver(setup.machine)
    sol = kin.ik_best(d, allow_singular=True)
    if sol is None:
        raise ValueError(f"direction {d} hors des courses A/C de la machine")

    plan = OrientationPlan(
        directions=np.tile(d, (n, 1)),
        a_deg=np.full(n, sol.a_deg),
        c_deg=np.full(n, sol.c_deg),
        margin=np.full(n, margin),
        feasible=True,
    )
    plan.segments = [OrientationSegment(
        0, max(0, n - 1), "3+2", a_deg=sol.a_deg, c_deg=sol.c_deg,
        reason="operation indexee : orientation fixe par construction")]
    return plan
