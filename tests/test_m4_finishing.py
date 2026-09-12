"""Finition, accessibilite adaptative, garde machine inverse (jalon M4)."""

import numpy as np
import pytest

from xyzac.accessibility_solver import AccessibilityConfig, AccessibilitySolver
from xyzac.collision_engine import ObstacleField
from xyzac.collision_engine.machine_guard import MachineGuard
from xyzac.geometry_core import brep
from xyzac.orientation_solver import OrientationSolver
from xyzac.subtractive_slicer import (
    generate_finishing_passes,
    group_faces_by_normal,
    scallop_stepover,
)
from xyzac.tool_model import build_ballnose, build_endmill


# ------------------------------------------------------ hauteur de crete

@pytest.mark.parametrize("scallop", [0.002, 0.005, 0.01, 0.05])
def test_scallop_stepover_round_trips(scallop):
    """h = R - sqrt(R^2 - (s/2)^2) doit redonner la consigne."""
    R = 3.0
    s = scallop_stepover(R, scallop)
    back = R - np.sqrt(R * R - (s / 2.0) ** 2)
    assert back == pytest.approx(scallop, rel=1e-9)


def test_finer_scallop_means_smaller_stepover():
    assert scallop_stepover(3.0, 0.002) < scallop_stepover(3.0, 0.02)


def test_scallop_is_clamped_below_tool_radius():
    """Une crete superieure au rayon d'outil n'a pas de sens geometrique."""
    s = scallop_stepover(3.0, 99.0)
    assert 0 < s <= 2.0 * 3.0


# ------------------------------------------------------ generation de passes

def test_flat_endmill_is_refused_for_finishing(corpus_dir):
    """Une fraise a bout droit laisse une marche a chaque passe et enfonce son
    talon des qu'on l'incline. On refuse explicitement plutot que de produire
    une passe inexploitable."""
    shape = brep.load_step(corpus_dir / "C01_bloc_simple.step")
    flat = build_endmill("EM6", 6.0, 20.0, stickout=45.0)
    with pytest.raises(ValueError, match="bout droit"):
        generate_finishing_passes(shape, [0], flat, scallop_mm=0.01)


@pytest.fixture(scope="module")
def ballnose():
    return build_ballnose("BN6", 6.0, 20.0, stickout=45.0, holder_type="ER16")


def test_planar_group_uses_parallel_topology(corpus_dir, ballnose):
    shape = brep.load_step(corpus_dir / "C01_bloc_simple.step")
    fp = generate_finishing_passes(shape, [0], ballnose, scallop_mm=0.05)
    assert fp is not None and fp.topology == "parallele"
    assert fp.normal_spread_deg() < 5.0


def test_curved_group_switches_to_waterline(corpus_dir, ballnose):
    """Les bandes paralleles projettent sur un plan tangent MOYEN, qui n'existe
    pas sur une calotte : elles se replient et deux points consecutifs sautent
    d'un bord a l'autre."""
    shape = brep.load_step(corpus_dir / "C10_dome_convexe.step")
    groups = group_faces_by_normal(shape)
    curved = [g for g in groups
              if (fp := generate_finishing_passes(shape, g, ballnose, scallop_mm=0.2))
              and fp.normal_spread_deg() > 60.0]
    assert curved, "le dome doit produire au moins un groupe fortement courbe"
    fp = generate_finishing_passes(shape, curved[0], ballnose, scallop_mm=0.2)
    assert fp.topology == "waterline"


def test_waterline_keeps_consecutive_points_close(corpus_dir, ballnose):
    """Propriete essentielle d'une passe : deux points consecutifs sont
    voisins. Sans cela l'orientation solver paie une course rotative enorme
    pour un chemin qui n'existe pas."""
    shape = brep.load_step(corpus_dir / "C10_dome_convexe.step")
    groups = group_faces_by_normal(shape)
    for g in groups:
        fp = generate_finishing_passes(shape, g, ballnose, scallop_mm=0.2)
        if fp is None or fp.topology != "waterline":
            continue
        d = np.linalg.norm(np.diff(fp.points, axis=0), axis=1)
        # La majorite des pas doit rester de l'ordre du pas demande ; quelques
        # sauts subsistent aux changements de niveau, c'est normal.
        assert float(np.median(d)) < 5.0 * fp.stepover
        return
    pytest.skip("aucun groupe waterline sur cette geometrie")


# --------------------------------------------- accessibilite adaptative

@pytest.fixture(scope="module")
def flat_scene(machine, ballnose):
    g = np.stack(np.meshgrid(np.linspace(-40, 40, 40), np.linspace(-40, 40, 40)), -1)
    pts = np.concatenate([g.reshape(-1, 2), np.full((1600, 1), 30.0)], axis=1)
    f = ObstacleField.build(pts, part_spacing=2.0, safety_clearance=0.2)
    solver = AccessibilitySolver(
        ballnose, machine, f,
        AccessibilityConfig(subdivisions=3, max_lead_deg=45.0),
        mount_offset_mm=np.array([0.0, 0.0, 20.0]))
    P = np.stack([np.linspace(-15, 15, 32), np.zeros(32), np.full(32, 30.0)], axis=1)
    N = np.tile([0.0, 0.0, 1.0], (32, 1))
    return solver, P, N


def test_adaptive_is_a_subset_of_the_full_solve(flat_scene):
    """Le test exact reste exact : ce qui est perdu, c'est l'EXHAUSTIVITE.
    Le resultat doit donc etre un sous-ensemble — conservatif."""
    solver, P, N = flat_scene
    full = solver.solve_points(P, N)
    adap = solver.solve_points_adaptive(P, N, stride=8)
    assert len(full) == len(adap)
    for f, a in zip(full, adap):
        assert a.n_feasible <= f.n_feasible


@pytest.mark.parametrize("stride", [2, 4, 8, 16])
def test_adaptive_never_loses_feasibility_where_the_full_solve_has_it(flat_scene, stride):
    """Regression du defaut le plus subtil du jalon.

    L'orientation retenue sur une face plane est proche de la verticale, donc
    A ~ 5 deg : tout pres de la singularite, ou le gain dC/d(axe) vaut 10,8.
    Les directions voisines sur la grille correspondent a des C repartis sur
    tout le cercle, et la contrainte de vitesse rotative interdit de passer de
    l'une a l'autre. La passe n'est donc realisable QUE par une orientation
    commune a tous ses points.

    Tout elagage qui la retire d'un seul point rend la sequence infaisable — ce
    qui donnait des resultats erratiques selon le stride (faisable a 8 et 32,
    infaisable a 2, 4 et 16). D'ou l'injection des directions communes dans
    chaque ensemble candidat : la faisabilite ne doit pas dependre de la chance
    du classement.
    """
    solver, P, N = flat_scene
    machine, tool = solver.machine, solver.tool
    osolver = OrientationSolver(machine, tool)

    full_plan = osolver.solve(solver.solve_points(P, N), path_points=P)
    if not full_plan.feasible:
        pytest.skip("le calcul complet lui-meme echoue : rien a comparer")

    adap_plan = osolver.solve(
        solver.solve_points_adaptive(P, N, stride=stride), path_points=P)
    assert adap_plan.feasible, (
        f"stride={stride} rend le plan infaisable alors que le calcul complet "
        "y parvient")
    assert np.abs(np.diff(adap_plan.c_deg)).max() < 170.0


def test_adaptive_costs_less_than_the_full_solve(flat_scene):
    import time

    solver, P, N = flat_scene
    solver.solve_point(P[0], N[0])
    t0 = time.perf_counter(); solver.solve_points(P, N); t_full = time.perf_counter() - t0
    t0 = time.perf_counter(); solver.solve_points_adaptive(P, N, stride=8)
    t_adap = time.perf_counter() - t0
    assert t_adap < t_full


# ------------------------------------------------ garde machine inverse

def test_guard_inversion_agrees_with_the_direct_transform(machine, tool):
    """On transporte desormais le TCP vers le repere de chaque organe, au lieu
    de transporter les organes vers le repere machine : un rapport de un a
    plusieurs milliers de vecteurs, et le nuage devient partageable entre
    toutes les orientations candidates (150 ms sur 199 avant correction).

    Le verdict doit etre inchange — c'est une reecriture, pas un
    assouplissement.
    """
    from xyzac.collision_engine import ObstacleClass
    from xyzac.collision_engine.tool_collision import ToolCollisionChecker

    g = MachineGuard(machine, tool)
    checker = ToolCollisionChecker(tool)
    rng = np.random.default_rng(0)

    for _ in range(12):
        a = float(rng.uniform(-110.0, 25.0))
        c = float(rng.uniform(-180.0, 180.0))
        tcp = rng.uniform([-60, -60, -60], [60, 60, 40])

        # Reference : organes transportes vers le repere machine, axe outil +Z.
        pts = g._points_in_machine_frame(a, c)
        field_ = ObstacleField(pts, np.full(len(pts), ObstacleClass.MACHINE),
                               np.full(len(pts), g.spacing + g.clearance))
        ref = not checker.check(tcp, np.array([0.0, 0.0, 1.0]), field_).collided
        got = bool(g.check_many(tcp[None, :], np.array([[a, c]]))[0])
        within = (bool(machine.x.contains(tcp[0])) and bool(machine.y.contains(tcp[1]))
                  and bool(machine.z.contains(tcp[2])))
        assert got == (ref and within), f"desaccord a A={a:.1f} C={c:.1f}"
