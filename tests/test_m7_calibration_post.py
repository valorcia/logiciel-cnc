"""Calibration, compensation et post-processeur sous scelles (jalon M7).

Discipline de ce fichier : aucune procedure de calibration ne se verifie contre
elle-meme. On **injecte dans le jumeau une erreur geometrique connue**, on
simule le palpage a travers elle, et on exige que la procedure la retrouve.
C'est la regle degagee au jalon M6 — faire varier le parametre qui doit
commander le resultat — appliquee au seul sujet ou aucune machine n'existe.
"""

import math

import numpy as np
import pytest

from xyzac.assembly_calibration import (
    HARDWARE_ONLY,
    CalibrationRecord,
    CalibrationStep,
    calibrate_on_twin,
    record_from_report,
)
from xyzac.geometry_core import brep
from xyzac.geometry_core.types import angle_between, normalize
from xyzac.kinematics_solver import KinematicsSolver
from xyzac.kinematics_solver.compensation import (
    CompensatedMove,
    compensate_pose,
    realised_pose,
    solve_real_orientation,
)
from xyzac.machine_model import Setup, default_xyzac_kit
from xyzac.machine_model.geometry import AxisLocationError, MachineGeometry, _rodrigues
from xyzac.postprocessor_linuxcnc import parse_poses, post_process
from xyzac.probing_service import (
    DatumSphere,
    ProbeSimulator,
    fit_axis_from_rotation,
    fit_sphere,
)
from xyzac.safety_state_machine import SafetyStateMachine
from xyzac.stock_engine import stock_from_part
from xyzac.strategy_planner.interfaces import Kinematic, Operation, ProcessPlan, Toolpath
from xyzac.tool_model import build_ballnose


def _tilt(u, axis, deg):
    return _rodrigues(axis, math.radians(deg)) @ np.asarray(u, dtype=float)


TRUE_A_OFFSET = [0.10, -0.20, 0.30]
TRUE_C_OFFSET = [-0.15, 0.05, 0.0]
TRUE_A_TILT_DEG = 0.20
TRUE_C_TILT_DEG = 0.15


@pytest.fixture(scope="module")
def truth() -> MachineGeometry:
    """Machine REELLE simulee : c'est l'erreur a retrouver."""
    return MachineGeometry(
        machine_id="XYZAC-kit-v0", measured=True,
        a_axis=AxisLocationError(offset_mm=TRUE_A_OFFSET,
                                 direction=list(_tilt([1, 0, 0], [0, 0, 1], TRUE_A_TILT_DEG))),
        c_axis=AxisLocationError(offset_mm=TRUE_C_OFFSET,
                                 direction=list(_tilt([0, 0, 1], [1, 0, 0], TRUE_C_TILT_DEG))))


# ------------------------------ une machine non mesuree n'est pas une machine juste

def test_unmeasured_geometry_refuses_to_give_a_budget():
    """La distinction qui fonde tout le module : une machine non calibree n'a
    pas une erreur nulle, elle a une incertitude INCONNUE. Lire des zeros
    reviendrait a croire une machine parfaite."""
    g = MachineGeometry.nominal("kit")
    assert not g.measured
    with pytest.raises(RuntimeError, match="NON MESUREE"):
        g.position_uncertainty_mm(100.0)
    assert "NON MESUREE" in g.describe()


def test_margins_were_computed_on_a_perfect_machine_until_now():
    """Constat, pas regression : la machine par defaut a tous ses defauts a zero.

    C'est delibere (declarer une valeur non mesuree serait pire), mais cela veut
    dire que toute marge rapportee des jalons M1 a M6 est une marge GEOMETRIQUE
    et non une marge machine. Ce test fixe ce fait pour qu'il ne se perde pas.
    """
    m = default_xyzac_kit()
    assert m.x.backlash_mm == 0.0 and m.a.backlash_deg == 0.0
    assert not MachineGeometry.nominal(m.machine_id).measured


# --------------------------------------------------- compensation

@pytest.mark.parametrize("label,direction,kw", [
    ("pivot A decale", [0.3, 0.2, 0.93],
     {"a_axis": AxisLocationError(offset_mm=[0.1, -0.2, 0.3])}),
    ("axe A incline", [0.3, 0.2, 0.93],
     {"a_axis": AxisLocationError(direction=list(_tilt([1, 0, 0], [0, 0, 1], 0.20)))}),
    ("axe C incline", [0.3, 0.2, 0.93],
     {"c_axis": AxisLocationError(direction=list(_tilt([0, 0, 1], [1, 0, 0], 0.15)))}),
    # Equerrage et echelle se mesurent A = 0 / C = 0, et pas par commodite :
    # leur effet est proportionnel a l'EXCURSION dans le repere machine, donc il
    # s'annule pres de l'origine machine. A la pose inclinee ci-dessus, la meme
    # erreur ne produit que 0,5 um et le test ne testerait rien.
    ("equerrage et echelle", [0.0, 0.0, 1.0],
     {"squareness_xy_deg": 0.05, "squareness_xz_deg": -0.03, "scale_x_ppm": 120.0}),
])
def test_compensation_recovers_an_injected_error(label, direction, kw):
    """Une erreur MESUREE est compensable : c'est la these du module.

    On mesure d'abord ce que coute l'erreur sans compensation — sinon le test ne
    dit pas si le probleme existait — puis ce qu'il en reste apres.
    """
    m = default_xyzac_kit()
    g = MachineGeometry(machine_id="T", measured=True, **kw)
    ks = KinematicsSolver(m)
    wo = np.array([0.0, 0.0, 30.0])
    p = np.array([60.0, -25.0, 2.0])
    d = normalize(np.array(direction))
    sol = ks.ik_best(d, allow_singular=True)

    raw = CompensatedMove(*(list(ks.part_to_machine_point(p, sol.a_deg, sol.c_deg) + wo)
                            + [sol.a_deg, sol.c_deg, 0.0, 0.0, True, 0]))
    p_raw, d_raw = realised_pose(m, g, raw, work_offset=wo)
    err_raw = float(np.linalg.norm(p_raw - p))

    mv = compensate_pose(m, g, p, d, a_nominal=sol.a_deg, c_nominal=sol.c_deg,
                         work_offset=wo)
    p_ok, d_ok = realised_pose(m, g, mv, work_offset=wo)

    assert err_raw > 20e-3, f"{label} : erreur non compensee de seulement {err_raw*1000:.1f} um"
    assert float(np.linalg.norm(p_ok - p)) < 1e-9, label
    assert math.degrees(angle_between(d_ok, d)) < 1e-6, label


def test_compensating_a_perfect_machine_changes_nothing():
    m = default_xyzac_kit()
    g = MachineGeometry(machine_id="parfaite", measured=True)
    ks = KinematicsSolver(m)
    p, d = np.array([20.0, 10.0, 5.0]), normalize(np.array([0.0, 0.0, 1.0]))
    sol = ks.ik_best(d, allow_singular=True)
    mv = compensate_pose(m, g, p, d, a_nominal=sol.a_deg, c_nominal=sol.c_deg)
    assert mv.linear == pytest.approx(ks.part_to_machine_point(p, sol.a_deg, sol.c_deg))
    assert mv.a_deg == pytest.approx(sol.a_deg)


def test_damping_is_required_where_the_normal_equations_are_singular():
    """Regression d'une affirmation FAUSSE que j'avais ecrite.

    Le docstring disait qu'un Gauss-Newton pur « diverge en produisant un C
    arbitrairement grand » pres de la singularite. Mesure : il converge, et plus
    vite. Le vrai mode d'echec est ailleurs — axe C exactement nominal et A = 0,
    la direction d'outil ne depend plus de C, ``J^T J`` est exactement singulier
    et la resolution LEVE. Ce test fixe le mecanisme reel.
    """
    g = MachineGeometry(
        machine_id="nomC", measured=True,
        a_axis=AxisLocationError(direction=list(_tilt([1, 0, 0], [0, 0, 1], 0.2))),
        c_axis=AxisLocationError(direction=[0.0, 0.0, 1.0]))
    d = normalize(np.array([0.0872, 0.0, 0.9962]))          # 5 deg de l'axe

    j = np.column_stack([
        (g.real_tool_axis_in_part(1e-6, 0.0) - g.real_tool_axis_in_part(-1e-6, 0.0)) / 2e-6,
        (g.real_tool_axis_in_part(0.0, 1e-6) - g.real_tool_axis_in_part(0.0, -1e-6)) / 2e-6,
    ])
    assert np.linalg.matrix_rank(j.T @ j, tol=1e-12) < 2, (
        "le systeme normal doit etre singulier ici, sinon ce test ne teste rien")

    a, c, res, ok, n = solve_real_orientation(g, d, 0.0, 0.0)
    assert ok and res < 1e-6, f"residu {res} apres {n} iterations"
    # Et il en faut BEAUCOUP : une borne a 20 iterations faisait echouer ce cas
    # d'un cheveu, en rendant 0,044 deg de residu.
    assert n > 15, f"{n} iterations : ce cas est censé etre le cas difficile"


def test_the_seed_selects_which_solution_not_whether_one_is_found():
    """Rectification d'une affirmation que j'avais ecrite trop vite.

    J'avais ecrit que l'amorce decide de la CONVERGENCE. Mesure : les deux
    amorces convergent, au meme residu (2e-9 deg). Elle decide de **laquelle
    des solutions** on atteint — ici C = -89,80 deg depuis (0, 0) contre
    C = +90,20 deg depuis la solution nominale, soit 180 deg de plateau
    d'ecart, pour la meme direction d'outil.

    C'est la raison de fond pour laquelle ``compensate_pose`` exige les valeurs
    nominales : choisir la branche est une decision de trajectoire — continuite,
    singularite, courses — et la laisser a un solveur numerique la rendrait
    invisible.
    """
    g = MachineGeometry(
        machine_id="G", measured=True,
        a_axis=AxisLocationError(direction=list(_tilt([1, 0, 0], [0, 0, 1], 0.2))),
        c_axis=AxisLocationError(direction=[0.0, 0.0, 1.0]))
    d = normalize(np.array([0.0872, 0.0, 0.9962]))
    sol = KinematicsSolver(default_xyzac_kit()).ik_best(d, allow_singular=True)

    _, c_zero, res_zero, ok_zero, n_zero = solve_real_orientation(g, d, 0.0, 0.0)
    _, c_seed, res_seed, ok_seed, n_seed = solve_real_orientation(
        g, d, sol.a_deg, sol.c_deg)

    assert ok_zero and ok_seed, "les deux amorces convergent : c'est le point"
    assert res_zero < 1e-6 and res_seed < 1e-6
    assert abs(c_zero - sol.c_deg) > 170.0, (
        f"depuis (0,0) on attend l'autre branche, ecart {abs(c_zero - sol.c_deg):.1f} deg")
    assert abs(c_seed - sol.c_deg) < 1.0
    assert n_seed < n_zero / 3.0, (n_seed, n_zero)


def test_compensation_near_the_singularity_costs_rotary_travel():
    """Fait physique isole a ce jalon, et il a une consequence de planification.

    Pres de A = 0, corriger une erreur d'orientation minuscule demande une
    grande rotation de plateau : un defaut d'axe de 0,15 deg coute 16,6 deg de C
    a A = 0,5 deg, contre 1,5 deg a A = 5 deg. La compensation n'est donc pas
    neutre vis-a-vis des courses rotatives, et un plan qui frole A = 0 peut
    devenir infaisable apres compensation alors qu'il passait avant.
    """
    m = default_xyzac_kit()
    g = MachineGeometry(
        machine_id="G", measured=True,
        a_axis=AxisLocationError(direction=list(_tilt([1, 0, 0], [0, 0, 1], 0.2))),
        c_axis=AxisLocationError(direction=list(_tilt([0, 0, 1], [1, 0, 0], 0.15))))
    ks = KinematicsSolver(m)
    cost = {}
    for label, d in (("A=0.5", normalize(np.array([0.0087, 0.0, 1.0]))),
                     ("A=5", normalize(np.array([0.0872, 0.0, 0.9962])))):
        sol = ks.ik_best(d, allow_singular=True)
        _, c, _, ok, _ = solve_real_orientation(g, d, sol.a_deg, sol.c_deg)
        assert ok
        cost[label] = abs(c - sol.c_deg)
    assert cost["A=0.5"] > 10.0 * cost["A=5"], cost


# --------------------------------------------------- ajustements

def test_fit_sphere_refuses_a_single_latitude():
    """Regression du defaut qui a fausse toute la localisation d'axe.

    Des points pris sur UN MEME CERCLE de la sphere appartiennent a une infinite
    de spheres. ``lstsq`` rendait pourtant un centre, ce centre avait l'air d'une
    mesure, et l'axe qui en decoulait se trompait de 178 deg avec un residu de
    1,1 mm INSENSIBLE au bruit — le signe qu'il s'agissait d'un defaut
    systematique et non statistique.
    """
    centre, r = np.array([10.0, 5.0, 20.0]), 12.5
    theta = math.radians(45.0)
    pts = np.array([
        centre + r * np.array([math.sin(theta) * math.cos(phi),
                               math.sin(theta) * math.sin(phi), math.cos(theta)])
        for phi in np.linspace(0.0, 2.0 * math.pi, 8, endpoint=False)])
    with pytest.raises(ValueError, match="DEUX latitudes"):
        fit_sphere(pts)


def test_fit_axis_refuses_angular_steps_over_180_deg():
    """Au-dela de 180 deg de pas, le sens de rotation n'est pas deductible des
    positions seules — et s'y tromper retourne la normale."""
    ang = np.array([0.0, 200.0, 350.0])
    c = np.array([[1.0, 0.0, 0.0], [-0.94, -0.34, 0.0], [0.98, -0.17, 0.0]])
    with pytest.raises(ValueError, match="180 deg"):
        fit_axis_from_rotation(c, ang, np.zeros(3), np.array([0.0, 0.0, 1.0]))


# --------------------------------------------- localisation des axes

@pytest.mark.parametrize("noise_mm", [0.001, 0.003, 0.010])
def test_axis_location_recovers_the_injected_error(truth, noise_mm):
    """LE test du jalon : la procedure retrouve-t-elle ce qu'on a injecte ?"""
    m = default_xyzac_kit()
    sim = ProbeSimulator(m, truth, noise_mm=noise_mm, seed=7)
    sphere = DatumSphere(centre_part=np.array([70.0, 0.0, 40.0]))
    ang = np.linspace(0.0, 160.0, 8)
    centres = np.array([sim.measure_sphere_centre(sphere, 0.0, float(a)).centre
                        for a in ang])
    fit = fit_axis_from_rotation(centres, ang, np.asarray(m.pivot_c, float),
                                 np.array([0.0, 0.0, 1.0]))
    # Le signe doit etre bon : une normale retournee donnerait ~180 deg.
    assert fit.direction_error_deg < 1.0, "normale retournee"
    assert fit.direction_error_deg == pytest.approx(TRUE_C_TILT_DEG, abs=0.02)

    # La composante AXIALE de l'offset n'est pas observable, et n'a pas d'effet
    # cinematique : la procedure ne doit donc pas pretendre la mesurer.
    assert abs(fit.offset_perp_mm @ fit.direction) < 1e-9


def test_reported_uncertainty_brackets_the_true_error(truth):
    """Regression d'un defaut grave : l'incertitude SOUS-ESTIMAIT l'erreur.

    Les formules fermees ``residu / rayon`` et ``residu / sqrt(n)`` la
    sous-estimaient d'un facteur ~3,7, constant sur trois niveaux de bruit,
    parce qu'elles supposent un cercle COMPLET alors qu'on mesure un arc (160
    deg pour C, 80 pour A). Une incertitude sous-estimee est exactement la
    confiance fabriquee que ce module existe pour empecher. Elles ont ete
    remplacees par un jackknife, qui voit l'etendue sans qu'on la modelise.
    """
    m = default_xyzac_kit()
    for noise in (0.001, 0.003, 0.010):
        _, meas = calibrate_on_twin(m, truth, probe_noise_mm=noise, seed=7)
        for got, want in ((meas.a_axis, truth.a_axis), (meas.c_axis, truth.c_axis)):
            err = math.degrees(angle_between(got.u, want.u))
            assert got.direction_uncertainty_deg >= err, (
                f"bruit {noise}: erreur {err:.5f} deg > incertitude annoncee "
                f"{got.direction_uncertainty_deg:.5f} deg")


def test_a_sphere_further_from_the_axis_measures_the_angle_better(truth):
    """L'incertitude d'orientation vaut residu / rayon du cercle decrit : placer
    la sphere loin de l'axe est le seul levier gratuit de la procedure."""
    m = default_xyzac_kit()
    unc = {}
    for r in (30.0, 70.0):
        sim = ProbeSimulator(m, truth, noise_mm=0.010, seed=7)
        sphere = DatumSphere(centre_part=np.array([r, 0.0, 40.0]))
        ang = np.linspace(0.0, 160.0, 8)
        centres = np.array([sim.measure_sphere_centre(sphere, 0.0, float(a)).centre
                            for a in ang])
        unc[r] = fit_axis_from_rotation(
            centres, ang, np.asarray(m.pivot_c, float),
            np.array([0.0, 0.0, 1.0])).direction_uncertainty_deg
    assert unc[70.0] < unc[30.0] * 0.75, unc


# ------------------------------------------- dossier de calibration

def test_hardware_steps_are_never_reported_as_passed(truth):
    """Cinq etapes exigent la machine. Les declarer reussies serait fabriquer de
    la confiance, et c'est precisement ce que ce projet refuse."""
    m = default_xyzac_kit()
    report, meas = calibrate_on_twin(m, truth)
    rec = record_from_report(m.machine_id, meas, report)

    assert not report.complete
    assert set(report.blocking()) == set(HARDWARE_ONLY)
    for r in report.results:
        if r.step in HARDWARE_ONLY:
            assert not r.passed and r.remedy, r.step
    # Mais la geometrie, elle, est mesuree : c'est ce qui leve la moitie
    # LOGICIELLE du verrou du post-processeur.
    assert rec.geometry_complete
    assert not rec.qualified


def test_tolerance_statement_refuses_to_quote_a_part_tolerance(truth):
    """Regle non negociable depuis M1 : +/-0,02 mm n'est pas un acquis.

    Le dossier est le seul endroit autorise a enoncer une precision, et il
    refuse d'en enoncer une tant que la piece d'epreuve n'a pas ete usinee ET
    mesuree — ce qui exige la machine.
    """
    m = default_xyzac_kit()
    report, meas = calibrate_on_twin(m, truth)
    rec = record_from_report(m.machine_id, meas, report)
    txt = rec.tolerance_statement()
    assert "NON QUALIFIEE" in txt
    assert "budget geometrique" in txt
    assert "0,02" not in txt and "0.02" not in txt

    nominal = CalibrationRecord(machine_id="x",
                                geometry=MachineGeometry.nominal("x"))
    assert "NON MESUREE" in nominal.tolerance_statement()


def test_calibration_hash_tracks_geometry_and_ignores_notes(truth):
    m = default_xyzac_kit()
    report, meas = calibrate_on_twin(m, truth)
    rec = record_from_report(m.machine_id, meas, report)
    h = rec.calibration_hash()

    rec.notes = "recalibration du mardi"
    assert rec.calibration_hash() == h, "un commentaire ne doit pas invalider"

    rec.geometry = rec.geometry.model_copy(update={
        "a_axis": rec.geometry.a_axis.model_copy(update={"offset_mm": [9.9, 0.0, 0.0]})})
    assert rec.calibration_hash() != h, "un pivot deplace DOIT invalider"


# ----------------------------------------- post-processeur sous scelles

@pytest.fixture(scope="module")
def approved_plan(corpus_dir):
    path = corpus_dir / "C10_dome_convexe.step"
    shape = brep.load_step(path)
    bb = brep.bounding_box(shape)
    m = default_xyzac_kit()
    tool = build_ballnose("BN6", 6.0, 20.0, stickout=45.0, holder_type="ER16")
    stock = stock_from_part(bb, margin_xy=2.0, margin_z_top=2.0, margin_z_bottom=2.0)
    setup = Setup(setup_id="m7", machine=m, part_step_path=str(path), stock=stock,
                  tools=[tool],
                  part_to_table_mm=[float(-bb.center[0]), float(-bb.center[1]), 25.0])
    samp = brep.sample_surface(shape, spacing=3.0)
    pts, nrm = samp.points[:30], samp.normals[:30]
    plan = ProcessPlan(plan_id="m7", setup=setup, operations=[Operation(
        op_id="finition", kinematic=Kinematic.MILLING_5AXIS, tool=tool,
        toolpath=Toolpath(points=pts, normals=nrm), spindle_rpm=12000.0,
        feed_mm_min=250.0)])
    h = setup.setup_hash()
    sm = SafetyStateMachine(setup_hash=h)
    sm.define_setup(h)
    sm.pass_collision(True)
    sm.pass_kinematics(True)
    sm.pass_simulation(True)
    sm.approve("test")
    return plan, sm, h, pts, nrm


def test_header_carries_the_tolerance_statement_before_any_motion(approved_plan, truth):
    """Un operateur qui ouvre le fichier doit tomber sur ce qu'il n'a pas le
    droit d'esperer AVANT la premiere ligne de mouvement."""
    plan, sm, h, _, _ = approved_plan
    m = plan.setup.machine
    report, meas = calibrate_on_twin(m, truth, probe_noise_mm=0.002)
    rec = record_from_report(m.machine_id, meas, report)

    gcode, emit = post_process(plan, sm, h, rec)
    head = gcode.split("G21")[0]
    assert "TOLERANCE" in head and "NON QUALIFIEE" in head
    assert "NON QUALIFIEES" in head, "avances non qualifiees"
    assert "verrouille" in head, "le fichier doit dire qu'il n'a pas ete envoye"
    assert rec.calibration_hash()[:16] in head
    assert emit.n_points == 30


def test_round_trip_is_exact_on_the_measured_geometry(approved_plan, truth):
    """Un emetteur verifie contre son propre calcul ne verifie rien.

    On relit donc le G-code produit et on rejoue la cinematique reelle sur les
    valeurs RELUES. Ce qui reste est la quantification du format : quatre
    decimales, donc 0,1 um, plancher que rien en aval ne peut franchir.
    """
    plan, sm, h, pts, nrm = approved_plan
    m = plan.setup.machine
    report, meas = calibrate_on_twin(m, truth, probe_noise_mm=0.002)
    rec = record_from_report(m.machine_id, meas, report)

    gcode, _ = post_process(plan, sm, h, rec)
    poses = parse_poses(gcode)
    assert len(poses) == len(pts)

    wo = np.asarray(plan.setup.work_offset.origin_mm, float)
    mount = np.asarray(plan.setup.mount_offset, float)
    worst = 0.0
    for (p, n), q in zip(zip(pts, nrm), poses):
        mv = CompensatedMove(q["X"], q["Y"], q["Z"], q["A"], q["C"], 0.0, 0.0, True, 0)
        got, _ = realised_pose(m, meas, mv, work_offset=wo)
        worst = max(worst, float(np.linalg.norm(got - (p + mount))))
    assert worst < 1e-3, f"{worst*1000:.3f} um : au-dela de la quantification du format"


def test_round_trip_on_the_true_machine_stays_within_the_announced_budget(
        approved_plan, truth):
    """La relation qui donne un sens au budget.

    Sur la machine VRAIE — et non sur celle qu'on a mesuree — il reste l'erreur
    residuelle de calibration. Le budget annonce doit la MAJORER, sinon il
    n'annonce rien.
    """
    plan, sm, h, pts, nrm = approved_plan
    m = plan.setup.machine
    report, meas = calibrate_on_twin(m, truth, probe_noise_mm=0.002)
    rec = record_from_report(m.machine_id, meas, report)

    gcode, _ = post_process(plan, sm, h, rec)
    poses = parse_poses(gcode)
    wo = np.asarray(plan.setup.work_offset.origin_mm, float)
    mount = np.asarray(plan.setup.mount_offset, float)

    worst = 0.0
    for (p, n), q in zip(zip(pts, nrm), poses):
        mv = CompensatedMove(q["X"], q["Y"], q["Z"], q["A"], q["C"], 0.0, 0.0, True, 0)
        got, _ = realised_pose(m, truth, mv, work_offset=wo)
        worst = max(worst, float(np.linalg.norm(got - (p + mount))))

    assert worst > 1e-3, "sans erreur residuelle, ce test ne teste rien"
    assert worst <= rec.uncertainty_at_100mm_mm, (
        f"erreur residuelle {worst*1000:.1f} um > budget annonce "
        f"{rec.uncertainty_at_100mm_mm*1000:.1f} um")


def test_post_process_refuses_a_hybrid_plan(approved_plan, truth):
    """Le basculement du mode C est une transition verrouillee (ADR-001 / D8) et
    l'ordonnancement fraisage/tournage n'existe pas."""
    plan, sm, h, _, _ = approved_plan
    m = plan.setup.machine
    report, meas = calibrate_on_twin(m, truth)
    rec = record_from_report(m.machine_id, meas, report)

    hybrid = ProcessPlan(plan_id="hybride", setup=plan.setup,
                         operations=list(plan.operations) + [Operation(
                             op_id="tournage", kinematic=Kinematic.TURNING,
                             tool=plan.operations[0].tool,
                             toolpath=Toolpath(points=np.zeros((1, 3)),
                                               normals=np.array([[0.0, 0.0, 1.0]])))])
    with pytest.raises(RuntimeError, match="hybride"):
        post_process(hybrid, sm, h, rec)


def test_the_gateway_is_still_locked():
    """M7 leve la moitie LOGICIELLE du verrou. L'envoi reel reste interdit."""
    from xyzac.linuxcnc_gateway import LinuxCncGateway
    g = LinuxCncGateway()
    with pytest.raises(NotImplementedError, match="portes de securite"):
        g.connect()
    assert g.estop_is_hardware() is True


def test_recalibration_invalidates_an_approval(approved_plan, truth):
    """Une recalibration change les pivots, donc la geometrie contre laquelle les
    collisions ont ete verifiees. Elle doit invalider une approbation exactement
    comme un bridage deplace."""
    plan, _, _, _, _ = approved_plan
    base = plan.setup.setup_hash()
    with_cal = plan.setup.model_copy(update={"calibration_hash": "abc123"})
    assert with_cal.setup_hash() != base
    other = plan.setup.model_copy(update={"calibration_hash": "def456"})
    assert other.setup_hash() != with_cal.setup_hash()
    # Et un commentaire ne doit toujours rien invalider.
    assert with_cal.model_copy(update={"notes": "note"}).setup_hash() == with_cal.setup_hash()


def test_posting_under_a_different_calibration_than_approved_is_refused(
        approved_plan, truth):
    """Le trou de securite que ce garde ferme : approuver sous une calibration et
    poster sous une autre annule la signification de l'approbation."""
    plan, _, _, _, _ = approved_plan
    m = plan.setup.machine
    report, meas = calibrate_on_twin(m, truth, probe_noise_mm=0.002)
    rec = record_from_report(m.machine_id, meas, report)

    setup2 = plan.setup.model_copy(
        update={"calibration_hash": "0" * 64})          # approuve sous une AUTRE
    plan2 = ProcessPlan(plan_id=plan.plan_id, setup=setup2,
                        operations=plan.operations)
    h2 = setup2.setup_hash()
    sm2 = SafetyStateMachine(setup_hash=h2)
    sm2.define_setup(h2)
    sm2.pass_collision(True)
    sm2.pass_kinematics(True)
    sm2.pass_simulation(True)
    sm2.approve("test")

    with pytest.raises(RuntimeError, match="approuve"):
        post_process(plan2, sm2, h2, rec)


def test_no_rapid_move_goes_to_a_contact_point(approved_plan, truth):
    """Regression d'un defaut de l'emetteur : le premier point de chaque
    operation sortait en G0, c'est-a-dire un rapide DANS la piece.

    Les mouvements d'approche et de degagement ne sont pas generes par ce module,
    qui ne connait pas le plan de degagement des operations. Le defaut prudent
    est donc l'avance travail partout, et le manque est ecrit dans l'en-tete.
    """
    plan, sm, h, _, _ = approved_plan
    m = plan.setup.machine
    report, meas = calibrate_on_twin(m, truth, probe_noise_mm=0.002)
    rec = record_from_report(m.machine_id, meas, report)

    gcode, _ = post_process(plan, sm, h, rec)
    body = [l for l in gcode.splitlines() if not l.startswith("(")]
    assert not any(l.startswith("G0 ") for l in body), "un G0 vise un point de contact"
    assert "APPROCHE ET DEGAGEMENT NON GENERES" in gcode


def test_squareness_is_measured_between_two_faces_not_on_one():
    """Regression d'une procedure qui avait l'air de mesurer sans mesurer.

    Le palpeur simule ne convertissait pas les positions en coordonnees
    d'AXES : le jumeau ne portait donc aucun defaut du triedre lineaire, et
    ``measure_squareness`` rendait une incertitude sans jamais pouvoir rendre
    une valeur. Un palpeur reel rend les valeurs des axes au declenchement,
    donc un defaut d'equerrage distord la lecture — et c'est par cette
    distorsion, et pas autrement, qu'on peut l'apercevoir.
    """
    from xyzac.assembly_calibration.procedures import measure_squareness

    m = default_xyzac_kit()
    for injected in (0.0, 0.10, 0.30):
        g = MachineGeometry(machine_id="sq", measured=True, squareness_xz_deg=injected)
        sim = ProbeSimulator(m, g, noise_mm=0.001, seed=3)
        res = measure_squareness(m, sim)
        assert res.measured["separates_three_angles"] is True
        got = res.measured["squareness_xz_deg"]
        unc = res.uncertainty["squareness_deg"]
        assert abs(abs(got) - injected) <= max(unc, 0.01), (
            f"injecte {injected} deg, mesure {got:+.4f} deg (+/-{unc:.4f})")
        # Et les deux autres paires ne doivent pas bouger : un equerrage XZ ne
        # doit pas se retrouver sur YZ.
        assert abs(res.measured["squareness_yz_deg"]) <= max(unc, 0.01)
