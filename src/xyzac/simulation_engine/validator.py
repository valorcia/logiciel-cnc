"""Validation complete d'une trajectoire orientee. Porte de simulation.

C'est le module qui manquait au jalon M1 et qui rendait le verrou ADR-001 §6
inevitable : les portes de securite existaient, mais la porte de simulation ne
verifiait rien. Une approbation n'aurait donc rien signifie.

Quatre verifications, toutes necessaires, dans l'ordre du moins cher au plus
cher — et **toutes executees**, meme si la premiere echoue : un rapport qui
s'arrete au premier defaut oblige l'utilisateur a corriger, relancer, decouvrir
le suivant, recommencer. On veut la liste complete du premier coup.

  V1  poses           l'outil complet degage a chaque point de contact
  V2  cinematique     (A, C) dans les courses, hors singularite, continuite
  V3  machine         organes machine et courses lineaires
  V4  balayage        le mouvement CONTINU entre poses successives

V4 est celle qui change tout : V1 a V3 portent sur des instants, V4 sur le
trajet. Deux poses saines reliees par un chemin qui ne l'est pas, c'est le mode
de collision le plus courant en 5 axes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..accessibility_solver.solver import tcp_from_contact
from ..collision_engine.field import ObstacleField
from ..collision_engine.machine_guard import MachineGuard
from ..collision_engine.sweep import SweepChecker, SweepReport
from ..collision_engine.tool_collision import ToolCollisionChecker, check_path_poses
from ..kinematics_solver.solver import KinematicsSolver
from ..machine_model.setup import Setup
from ..orientation_solver.solver import OrientationPlan


@dataclass
class ValidationIssue:
    """Un defaut localise. Toujours un indice de point et une cause nommee."""

    check: str            # "poses" | "cinematique" | "machine" | "balayage"
    index: int
    severity: str         # "erreur" | "avertissement"
    message: str


@dataclass
class ValidationReport:
    """Rapport complet. C'est lui qui alimente la porte de simulation."""

    setup_hash: str
    n_points: int
    issues: list[ValidationIssue] = field(default_factory=list)
    min_margin_poses: float = np.inf
    min_margin_sweep: float = np.inf
    sweep_samples: int = 0
    checks_run: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "erreur"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "avertissement"]

    @property
    def passed(self) -> bool:
        """Une seule erreur suffit a refuser. Il n'y a pas de « presque bon »."""
        return not self.errors

    def summary(self) -> str:
        lines = [
            f"Validation — {'ACCEPTEE' if self.passed else 'REFUSEE'} "
            f"({self.n_points} points, setup {self.setup_hash[:12]})",
            f"  verifications : {', '.join(self.checks_run)}",
            f"  marge min poses    : {self.min_margin_poses:.3f} mm",
            f"  marge min balayage : {self.min_margin_sweep:.3f} mm "
            f"({self.sweep_samples} poses interpolees)",
            f"  erreurs : {len(self.errors)}   avertissements : {len(self.warnings)}",
        ]
        for i in self.issues[:15]:
            tag = "ERREUR" if i.severity == "erreur" else "avert."
            lines.append(f"    [{tag}] {i.check:12s} pt {i.index:5d} : {i.message}")
        if len(self.issues) > 15:
            lines.append(f"    ... {len(self.issues) - 15} de plus")
        return "\n".join(lines)


class TrajectoryValidator:
    """Valide un ``OrientationPlan`` contre une scene et une machine."""

    def __init__(self, setup: Setup, obstacles: ObstacleField, tool=None,
                 *, max_sweep_step_mm: float = 0.5, cutting_allowance: float = 0.0,
                 cutting_depth: float = 0.0, work_offset_mm: np.ndarray | None = None,
                 mount_offset_mm: np.ndarray | None = None):
        self.setup = setup
        self.obstacles = obstacles
        self.tool = tool or setup.tools[0]
        self.kin = KinematicsSolver(setup.machine)
        self.checker = ToolCollisionChecker(self.tool)
        self.sweep = SweepChecker(setup.machine, self.tool, max_step_mm=max_sweep_step_mm)
        self.guard = (MachineGuard(setup.machine, self.tool)
                      if setup.machine.collision_volumes else None)
        self.cutting_allowance = cutting_allowance
        self.cutting_depth = cutting_depth
        self.work_offset = (np.zeros(3) if work_offset_mm is None
                            else np.asarray(work_offset_mm, float))
        self.mount_offset = (setup.mount_offset if mount_offset_mm is None
                             else np.asarray(mount_offset_mm, float))

    def validate(self, plan: OrientationPlan, contacts: np.ndarray,
                 normals: np.ndarray) -> ValidationReport:
        contacts = np.asarray(contacts, float).reshape(-1, 3)
        normals = np.asarray(normals, float).reshape(-1, 3)
        rep = ValidationReport(setup_hash=self.setup.setup_hash(), n_points=plan.n_points)

        if not plan.feasible:
            rep.issues.append(ValidationIssue(
                "poses", plan.failures[0] if plan.failures else 0, "erreur",
                f"le plan d'orientation est incomplet : {len(plan.failures)} points "
                "sans orientation admissible"))

        tcps = np.array([tcp_from_contact(contacts[i], normals[i], plan.directions[i], self.tool)
                         for i in range(plan.n_points)])

        self._check_poses(plan, tcps, rep)
        self._check_kinematics(plan, contacts, rep)
        self._check_machine(plan, tcps, rep)
        self._check_sweep(plan, tcps, rep)
        return rep

    # -- V1 ----------------------------------------------------------------

    def _check_poses(self, plan, tcps, rep) -> None:
        rep.checks_run.append("poses")
        feas, margin, blocking = check_path_poses(
            self.checker, tcps, plan.directions, self.obstacles,
            cutting_depth=self.cutting_depth, cutting_allowance=self.cutting_allowance)
        finite = margin[np.isfinite(margin)]
        rep.min_margin_poses = float(finite.min()) if finite.size else np.inf
        for i in np.flatnonzero(~feas):
            si = int(blocking[i])
            role = self.tool.segments[si].role.value if si >= 0 else "?"
            rep.issues.append(ValidationIssue(
                "poses", int(i), "erreur",
                f"collision {role} (penetration {-margin[i]:.3f} mm)"))

    # -- V2 ----------------------------------------------------------------

    def _check_kinematics(self, plan, contacts, rep) -> None:
        rep.checks_run.append("cinematique")
        m = self.setup.machine
        steps = np.ones(plan.n_points)
        if plan.n_points > 1:
            steps[1:] = np.maximum(np.linalg.norm(np.diff(contacts, axis=0), axis=1), 1e-3)

        for i in range(plan.n_points):
            a, c = float(plan.a_deg[i]), float(plan.c_deg[i])
            if not m.a.contains(a):
                rep.issues.append(ValidationIssue(
                    "cinematique", i, "erreur",
                    f"A={a:.2f} hors course [{m.a.min_deg}, {m.a.max_deg}]"))
            if not m.c.contains(c):
                rep.issues.append(ValidationIssue(
                    "cinematique", i, "erreur",
                    f"C={c:.2f} hors course [{m.c.min_deg}, {m.c.max_deg}]"))
            if m.is_singular(a):
                # Avertissement et non erreur : la singularite degrade le
                # conditionnement, elle ne casse rien par elle-meme. C'est la
                # rotation C associee qui pose probleme, et elle est attrapee
                # par la contrainte de vitesse rotative ci-dessous.
                rep.issues.append(ValidationIssue(
                    "cinematique", i, "avertissement",
                    f"A={a:.2f} dans la bande de singularite "
                    f"(gain dC/d(axe) = {self.kin.conditioning(a):.1f})"))
            if i > 0 and self.kin.violates_rotary_rate(
                    float(plan.a_deg[i - 1]), float(plan.c_deg[i - 1]), a, c, float(steps[i])):
                rep.issues.append(ValidationIssue(
                    "cinematique", i, "erreur",
                    f"variation rotative excessive sur un pas de {steps[i]:.2f} mm : "
                    f"dA={a - plan.a_deg[i - 1]:.1f} dC={c - plan.c_deg[i - 1]:.1f} deg "
                    "— l'avance au point de contact exploserait"))

    # -- V3 ----------------------------------------------------------------

    def _check_machine(self, plan, tcps, rep) -> None:
        if self.guard is None:
            return
        rep.checks_run.append("machine")
        tcps_m = np.array([
            self.kin.part_to_machine_point(tcps[i] + self.mount_offset,
                                           float(plan.a_deg[i]), float(plan.c_deg[i]))
            + self.work_offset for i in range(plan.n_points)])
        ac = np.stack([plan.a_deg, plan.c_deg], axis=1)
        ok = self.guard.check_many(tcps_m, ac)
        for i in np.flatnonzero(~ok):
            chk = self.guard.check_pose(tcps_m[i], float(plan.a_deg[i]), float(plan.c_deg[i]))
            rep.issues.append(ValidationIssue("machine", int(i), "erreur", chk.reason()))

    # -- V4 ----------------------------------------------------------------

    def _check_sweep(self, plan, tcps, rep) -> None:
        if plan.n_points < 2:
            return
        rep.checks_run.append("balayage")
        reports: list[SweepReport] = self.sweep.check_path(
            tcps, plan.directions, plan.a_deg, plan.c_deg, self.obstacles,
            cutting_depth=self.cutting_depth, cutting_allowance=self.cutting_allowance)
        rep.sweep_samples = sum(r.n_samples for r in reports)
        finite = [r.worst_margin for r in reports if np.isfinite(r.worst_margin)]
        rep.min_margin_sweep = float(min(finite)) if finite else np.inf
        for i, r in enumerate(reports):
            if not r.ok:
                rep.issues.append(ValidationIssue("balayage", i, "erreur", r.reason()))


def run_simulation_gate(validator: TrajectoryValidator, plan, contacts, normals,
                        safety) -> ValidationReport:
    """Execute la validation ET renseigne la porte de simulation.

    Cette fonction est le seul chemin par lequel ``safety.pass_simulation``
    devrait etre appele en production : elle garantit que l'etat « simule » ne
    peut pas etre atteint sans qu'une validation ait reellement eu lieu.
    """
    report = validator.validate(plan, contacts, normals)
    safety.pass_simulation(report.passed, report.summary().splitlines()[0])
    return report


def make_pose_verifier(setup: Setup, obstacles: ObstacleField, tool,
                       contacts: np.ndarray, normals: np.ndarray,
                       *, cutting_depth: float = 0.0, cutting_allowance: float = 0.0,
                       work_offset_mm: np.ndarray | None = None):
    """Fabrique la fonction ``verify(index, direction) -> (ok, marge)``.

    C'est la brique que consomment la segmentation 3+2 **et** le raffinement
    continu. Elle existe ici, et non dans chaque appelant, pour une raison
    apprise a l'usage : une premiere version cote demonstration ne testait que
    la piece. Le raffinement, libre d'optimiser le degagement sans contrainte
    machine, a gagne 0,24 mm de marge en poussant l'axe Z a 60,1 mm pour une
    course qui s'arrete a 60,0 — un plan meilleur sur le critere optimise et
    irrealisable sur la machine.

    Toute verification de pose doit donc porter sur les DEUX : ce que l'outil
    rencontre, et ce que la machine peut atteindre.
    """
    contacts = np.asarray(contacts, float).reshape(-1, 3)
    normals = np.asarray(normals, float).reshape(-1, 3)
    kin = KinematicsSolver(setup.machine)
    checker = ToolCollisionChecker(tool)
    guard = MachineGuard(setup.machine, tool) if setup.machine.collision_volumes else None
    wo = np.zeros(3) if work_offset_mm is None else np.asarray(work_offset_mm, float)
    mount = setup.mount_offset

    def verify(index: int, direction: np.ndarray):
        tcp = tcp_from_contact(contacts[index], normals[index], direction, tool)
        rep = checker.check(tcp, direction, obstacles,
                            cutting_depth=cutting_depth, cutting_allowance=cutting_allowance)
        if rep.collided:
            return False, rep.min_margin

        sol = kin.ik_best(direction)
        if sol is None:
            return False, -np.inf
        if guard is not None:
            chk = guard.check_pose(
                kin.part_to_machine_point(tcp + mount, sol.a_deg, sol.c_deg) + wo,
                sol.a_deg, sol.c_deg)
            if not chk.ok:
                return False, -np.inf
        return True, rep.min_margin

    return verify


@dataclass
class OperationReport:
    """Validation d'une operation d'ebauche, couche par couche."""

    op_id: str
    n_layers: int
    n_points: int
    layers_ok: int
    issues: list[ValidationIssue] = field(default_factory=list)
    min_margin: float = np.inf
    removed_mm3: float = 0.0

    @property
    def passed(self) -> bool:
        return not [i for i in self.issues if i.severity == "erreur"]

    def describe(self) -> str:
        head = (f"Operation {self.op_id} : "
                f"{'ACCEPTEE' if self.passed else 'REFUSEE'} — "
                f"{self.layers_ok}/{self.n_layers} couches valides, "
                f"{self.n_points} points, marge min {self.min_margin:.3f} mm, "
                f"{self.removed_mm3:.0f} mm3 enleves")
        for i in self.issues[:5]:
            head += f"\n      [{i.severity}] {i.check} couche {i.index} : {i.message}"
        if len(self.issues) > 5:
            head += f"\n      ... {len(self.issues) - 5} de plus"
        return head


def validate_roughing_progressive(
    setup: Setup, material, slice_result, tool, *,
    point_spacing: float = 1.5, sweep_step_mm: float = 2.0,
    fixture_points=None, fixture_spacing: float = 2.0, safety_clearance: float = 0.3,
    op_id: str = "ebauche",
) -> OperationReport:
    """Valide une ebauche indexee en suivant l'etat REEL de la matiere.

    Point qui n'a rien d'accessoire : valider toute l'operation contre l'etat
    INITIAL de la matiere serait a la fois trop severe et faux. Pendant une
    ebauche profonde, la tige de l'outil occupe l'espace que les couches
    superieures viennent de liberer. Contre le brut intact, elle serait declaree
    en collision a chaque passe — le moteur refuserait toute ebauche de plus
    d'une couche.

    On valide donc **couche par couche**, en enlevant la matiere au fur et a
    mesure : c'est l'ordre dans lequel la machine travaille, et c'est le seul
    etat contre lequel la question a un sens.
    """
    from ..collision_engine.field import ObstacleField
    from ..stock_engine.material import MaterialState  # noqa: F401

    if abs(getattr(slice_result, "safety_clearance", safety_clearance)
           - safety_clearance) > 1e-9:
        raise ValueError(
            "le tranchage et la validation n'emploient pas la meme marge de "
            "securite : les deux modeles conservatifs divergeraient et le "
            "validateur refuserait des trajectoires jugees sûres par le slicer")

    rep = OperationReport(op_id=op_id, n_layers=len(slice_result.layers),
                          n_points=0, layers_ok=0)
    d = np.asarray(slice_result.direction, float)
    d = d / np.linalg.norm(d)
    part_pts = None
    part_inf = 0.0
    removed_total = 0

    from ..subtractive_slicer.slicer import continuous_path

    for layer in slice_result.layers:
        # Chemin CONTINU de la couche : passes de coupe ET liaisons. Ne valider
        # que les passes laisserait hors controle les mouvements qui les
        # relient — precisement ceux qui traversent la matiere quand ils sont
        # implicites.
        P, is_rapid = continuous_path(slice_result, point_spacing, layers=[layer])
        if len(P) == 0:
            rep.layers_ok += 1
            continue
        rep.n_points += len(P)

        # Obstacles vus par CETTE couche : peau de la matiere encore en place.
        skin, skin_inf = material.boundary_points()
        if part_pts is None:
            part_pts, part_inf = material.protected_boundary_points()
        field_ = ObstacleField.build(
            part_pts, part_spacing=part_inf,
            stock_points=skin, stock_spacing=skin_inf,
            fixture_points=fixture_points, fixture_spacing=fixture_spacing,
            safety_clearance=safety_clearance)

        plan = _fixed_plan(P, d, setup)
        v = TrajectoryValidator(setup, field_, tool, max_sweep_step_mm=sweep_step_mm,
                                cutting_allowance=float(field_.inflation.max()),
                                cutting_depth=slice_result.layer_thickness)
        sub = v.validate(plan, P, np.tile(d, (len(P), 1)))

        rep.min_margin = min(rep.min_margin, sub.min_margin_poses)
        errs = [i for i in sub.errors]
        if errs:
            rep.issues.append(ValidationIssue(
                errs[0].check, layer.index, "erreur",
                f"{len(errs)} erreur(s), premiere : {errs[0].message}"))
        else:
            rep.layers_ok += 1

        # Seuls les points de COUPE enlevent de la matiere : une liaison au
        # plan de degagement passe dans le vide.
        cut = P[~is_rapid]
        if len(cut):
            removed_total += material.remove_tool_sweep(
                cut, np.tile(d, (len(cut), 1)), tool, only_cutting=True)

    rep.removed_mm3 = float(removed_total) * material.grid.voxel_volume
    return rep


def _fixed_plan(points: np.ndarray, direction: np.ndarray, setup: Setup):
    from ..kinematics_solver.solver import KinematicsSolver
    from ..orientation_solver.solver import OrientationPlan, OrientationSegment

    kin = KinematicsSolver(setup.machine)
    sol = kin.ik_best(direction, allow_singular=True)
    if sol is None:
        raise ValueError(f"direction {direction} hors des courses A/C")
    n = len(points)
    plan = OrientationPlan(directions=np.tile(direction, (n, 1)),
                           a_deg=np.full(n, sol.a_deg), c_deg=np.full(n, sol.c_deg),
                           margin=np.zeros(n), feasible=True)
    plan.segments = [OrientationSegment(0, max(0, n - 1), "3+2",
                                        a_deg=sol.a_deg, c_deg=sol.c_deg,
                                        reason="operation indexee")]
    return plan
