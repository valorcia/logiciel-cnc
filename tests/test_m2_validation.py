"""Garde machine, balayage, validation de trajectoire, gouge exacte (jalon M2).

Ces tests portent sur les quatre verifications qui font desormais de la porte
de simulation une porte reelle, et non un interrupteur.
"""

import numpy as np
import pytest
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

from xyzac.collision_engine import ObstacleClass, ObstacleField
from xyzac.collision_engine.exact_gouge import verify_gouge_exact, verify_plan_sparse
from xyzac.collision_engine.machine_guard import MachineGuard
from xyzac.collision_engine.sweep import SweepChecker
from xyzac.geometry_core.types import AABB
from xyzac.machine_model import Setup, default_xyzac_kit
from xyzac.orientation_solver import OrientationPlan
from xyzac.safety_state_machine import SafetyState, SafetyStateMachine
from xyzac.simulation_engine import TrajectoryValidator, run_simulation_gate
from xyzac.stock_engine import stock_from_part
from xyzac.tool_model import build_endmill


# ------------------------------------------------------- garde machine

def test_machine_volumes_move_with_the_cradle(machine, tool):
    """Le berceau A et le plateau C ne sont pas statiques : les traiter comme
    tels rendrait le garde aveugle des qu'on bascule."""
    g = MachineGuard(machine, tool)
    p0 = g._points_in_machine_frame(0.0, 0.0)
    p90 = g._points_in_machine_frame(-90.0, 0.0)
    assert len(p0) == len(p90)
    assert not np.allclose(p0, p90), "les organes machine n'ont pas bouge avec A"


def test_guard_detects_collision_with_the_cradle(machine, tool):
    g = MachineGuard(machine, tool)
    assert g.check_pose(np.array([0.0, 0.0, 30.0]), 0.0, 0.0).ok
    bad = g.check_pose(np.array([0.0, -88.0, -20.0]), 0.0, 0.0)
    assert not bad.ok and bad.axis_limits_ok
    assert "organe machine" in bad.reason()


def test_guard_detects_linear_travel_violation(machine, tool):
    g = MachineGuard(machine, tool)
    out = g.check_pose(np.array([0.0, 0.0, -400.0]), 0.0, 0.0)
    assert not out.ok and not out.axis_limits_ok
    assert "hors course" in out.reason()


def test_guard_check_many_matches_check_pose(machine, tool):
    g = MachineGuard(machine, tool)
    tcps = np.array([[0.0, 0.0, 30.0], [0.0, -88.0, -20.0], [0.0, 0.0, -400.0]])
    ac = np.zeros((3, 2))
    assert np.array_equal(g.check_many(tcps, ac),
                          np.array([g.check_pose(t, 0.0, 0.0).ok for t in tcps]))


# ------------------------------------------------------------ balayage

def test_sweep_bound_grows_with_rotation(machine, tool):
    """La borne doit dominer la rotation : sur une machine table/table, une
    petite rotation deplace enormement un point eloigne du pivot."""
    sw = SweepChecker(machine, tool)
    straight = sw.displacement_bound([0, 0, 0], [0, 0, 1], [10, 0, 0], [0, 0, 1])
    turned = sw.displacement_bound([0, 0, 0], [0, 0, 1], [0, 0, 0], [0, 0.5, 0.866])
    assert straight == pytest.approx(10.0, rel=1e-6)
    assert turned > 60.0, "une rotation de 30 deg deplace l'outil de bien plus que 10 mm"


def test_sweep_catches_what_both_endpoints_miss(machine, tool):
    """LE test du jalon M2.

    Deux poses parfaitement degagees, un obstacle entre les deux. Sans
    verification du balayage, la trajectoire serait declaree valide et l'outil
    percuterait l'obstacle en chemin.
    """
    sw = SweepChecker(machine, tool, max_step_mm=0.5)
    obstacle = np.array([[5.0, 0.0, 40.0]])
    f = ObstacleField(obstacle, [ObstacleClass.FIXTURE], [1.0])
    p0, p1 = np.array([-30.0, 0.0, 0.0]), np.array([40.0, 0.0, 0.0])
    axis = np.array([0.0, 0.0, 1.0])

    assert not sw.checker.check(p0, axis, f).collided
    assert not sw.checker.check(p1, axis, f).collided
    rep = sw.check_segment(p0, axis, 0.0, 0.0, p1, axis, 0.0, 0.0, f)
    assert not rep.ok
    assert 0.0 < rep.first_failure_t < 1.0
    assert "balayage" in rep.reason()


def test_sweep_passes_on_a_clear_move(machine, tool):
    sw = SweepChecker(machine, tool, max_step_mm=1.0)
    f = ObstacleField(np.array([[0.0, 0.0, -200.0]]), [ObstacleClass.FIXTURE], [1.0])
    rep = sw.check_segment(np.array([-20.0, 0, 0]), [0, 0, 1], 0.0, 0.0,
                           np.array([20.0, 0, 0]), [0, 0, 1], 0.0, 0.0, f)
    assert rep.ok and rep.n_samples > 1


def test_sweep_interpolates_axes_not_directions(machine, tool):
    """Le controleur interpole les AXES. Interpoler les directions sur la
    sphere donnerait un chemin different de celui que la machine parcourt."""
    sw = SweepChecker(machine, tool)
    tcps, axes, a_seq, c_seq = sw.interpolate(
        np.zeros(3), [0, 0, 1], 0.0, 0.0, np.zeros(3), None, -60.0, 90.0, 6)
    assert a_seq[0] == 0.0 and a_seq[-1] == pytest.approx(-60.0)
    assert np.allclose(np.diff(a_seq), np.diff(a_seq)[0])  # rampe lineaire en A
    for a, c, ax in zip(a_seq, c_seq, axes):
        assert np.allclose(ax, machine.tool_axis_in_part(a, c))


def test_sweep_unwraps_c_across_the_seam(machine, tool):
    """Sans deroulage, un passage de 179 a -179 deg ferait interpoler un tour
    complet du plateau — et le test balaierait un volume qui n'existe pas."""
    sw = SweepChecker(machine, tool)
    _, _, _, c_seq = sw.interpolate(np.zeros(3), [0, 0, 1], -45.0, 179.0,
                                    np.zeros(3), None, -45.0, -179.0, 8)
    assert abs(c_seq[-1] - c_seq[0]) < 10.0


# --------------------------------------------------------- validation

@pytest.fixture
def mini_setup():
    bb = AABB(np.array([0.0, 0, 0]), np.array([40.0, 40, 20]))
    return Setup(setup_id="V", machine=default_xyzac_kit(), part_step_path="x.step",
                 stock=stock_from_part(bb),
                 tools=[build_endmill("EM6", 6.0, 20.0, stickout=45.0)],
                 part_to_table_mm=[0.0, 0.0, 60.0])


def _flat_plan(n=6, z=40.0):
    pts = np.stack([np.linspace(-10, 10, n), np.zeros(n), np.full(n, z)], axis=1)
    nrm = np.tile([0.0, 0.0, 1.0], (n, 1))
    d = np.tile([0.0, 0.0, 1.0], (n, 1))
    return pts, nrm, OrientationPlan(directions=d, a_deg=np.zeros(n), c_deg=np.zeros(n),
                                     margin=np.full(n, 5.0), feasible=True)


def test_validator_runs_all_four_checks(mini_setup):
    pts, nrm, plan = _flat_plan()
    f = ObstacleField(np.array([[0.0, 0.0, -500.0]]), [ObstacleClass.PART], [0.1])
    rep = TrajectoryValidator(mini_setup, f, max_sweep_step_mm=2.0).validate(plan, pts, nrm)
    assert rep.checks_run == ["poses", "cinematique", "machine", "balayage"]


def test_validator_reports_every_defect_not_just_the_first(mini_setup):
    """Un rapport qui s'arrete au premier defaut oblige a corriger-relancer en
    boucle. On veut la liste complete du premier coup."""
    pts, nrm, plan = _flat_plan(n=6)
    plan.a_deg = np.full(6, -200.0)              # hors course A, partout
    f = ObstacleField(np.array([[0.0, 0.0, -500.0]]), [ObstacleClass.PART], [0.1])
    rep = TrajectoryValidator(mini_setup, f, max_sweep_step_mm=5.0).validate(plan, pts, nrm)
    assert len([i for i in rep.errors if i.check == "cinematique"]) >= 6


def test_singularity_is_a_warning_not_an_error(mini_setup):
    pts, nrm, plan = _flat_plan()
    f = ObstacleField(np.array([[0.0, 0.0, -500.0]]), [ObstacleClass.PART], [0.1])
    rep = TrajectoryValidator(mini_setup, f, max_sweep_step_mm=5.0).validate(plan, pts, nrm)
    sing = [i for i in rep.issues if "singularite" in i.message]
    assert sing and all(i.severity == "avertissement" for i in sing)


def test_incomplete_plan_is_refused(mini_setup):
    pts, nrm, plan = _flat_plan()
    plan.feasible = False
    plan.failures = [2, 3]
    f = ObstacleField(np.array([[0.0, 0.0, -500.0]]), [ObstacleClass.PART], [0.1])
    rep = TrajectoryValidator(mini_setup, f, max_sweep_step_mm=5.0).validate(plan, pts, nrm)
    assert not rep.passed
    assert any("incomplet" in i.message for i in rep.errors)


def test_simulation_gate_cannot_be_passed_without_validating(mini_setup):
    """``run_simulation_gate`` est le seul chemin vers l'etat « simule » : il
    impose qu'une validation ait reellement eu lieu."""
    pts, nrm, plan = _flat_plan()
    f = ObstacleField(np.array([[0.0, 0.0, -500.0]]), [ObstacleClass.PART], [0.1])
    v = TrajectoryValidator(mini_setup, f, max_sweep_step_mm=5.0)

    sm = SafetyStateMachine(setup_hash=mini_setup.setup_hash())
    sm.define_setup(mini_setup.setup_hash())
    sm.pass_collision(True)
    sm.pass_kinematics(True)
    rep = run_simulation_gate(v, plan, pts, nrm, sm)
    assert sm.state is (SafetyState.SIMULATED if rep.passed else SafetyState.FAULT)


# ------------------------------------------------------ gouge exacte

@pytest.fixture(scope="module")
def box_shape():
    return BRepPrimAPI_MakeBox(60.0, 60.0, 30.0).Shape()


def test_exact_verifier_detects_a_five_hundredth_gouge(box_shape, tool):
    """Ce que le nuage de points ne peut PAS voir : 0,05 mm sur un pas de 2 mm.

    Volume attendu : pi . r^2 . profondeur = pi . 9 . 0,05 = 1,414 mm3.
    """
    r = verify_gouge_exact(box_shape, tool, np.array([30.0, 30.0, 29.95]),
                           np.array([0.0, 0.0, 1.0]), include_cutting=True)
    assert not r.ok
    assert r.gouge_volume_mm3 == pytest.approx(np.pi * 9.0 * 0.05, rel=0.02)


def test_exact_verifier_accepts_tangential_contact(box_shape, tool):
    """Poser l'outil exactement sur la face ne doit pas etre signale : en
    fraisage la coupe est tangente par construction."""
    r = verify_gouge_exact(box_shape, tool, np.array([30.0, 30.0, 30.0]),
                           np.array([0.0, 0.0, 1.0]), cutting_depth=1.0)
    assert r.ok


def test_exact_verifier_catches_the_spindle_nose(box_shape, tool):
    r = verify_gouge_exact(box_shape, tool, np.array([-14.0, 30.0, -50.0]),
                           np.array([0.0, 0.0, 1.0]), cutting_depth=1.0)
    assert not r.ok and r.role == "spindle_nose"


def test_sparse_verification_is_documented_as_a_sample(box_shape, tool):
    tcps = np.stack([np.full(20, 30.0), np.linspace(5, 55, 20), np.full(20, 30.0)], axis=1)
    axes = np.tile([0.0, 0.0, 1.0], (20, 1))
    res = verify_plan_sparse(box_shape, tool, tcps, axes, n_samples=5, cutting_depth=1.0)
    assert len(res) == 5
    assert all(r.ok for r in res)
