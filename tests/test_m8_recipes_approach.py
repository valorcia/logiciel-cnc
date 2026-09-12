"""Recettes de coupe et mouvements d'approche (jalon M8).

Les deux trous qui rendaient tout programme emis inexecutable :

  - aucune avance qualifiee. Le post-processeur ecrivait ``F300`` par defaut,
    un nombre invente dans du code livre ;
  - ni approche ni degagement. Le chemin commencait AU premier point de coupe
    et finissait AU dernier, donc le controleur amenait l'outil par un
    mouvement non decrit et le laissait dans la matiere.
"""

import math

import numpy as np
import pytest

from xyzac.geometry_core import brep
from xyzac.machine_model import Setup, default_xyzac_kit
from xyzac.recipe_profiles import (
    MATERIALS,
    UnknownMaterialError,
    build_recipe,
    effective_diameter,
    radial_chip_thinning,
)
from xyzac.stock_engine import stock_from_part
from xyzac.subtractive_slicer import indexed_frame, with_approach_retract
from xyzac.tool_model import build_ballnose, build_endmill


@pytest.fixture(scope="module")
def machine():
    return default_xyzac_kit()


@pytest.fixture(scope="module")
def em6():
    return build_endmill("EM6", 6.0, 20.0, stickout=45.0, holder_type="ER16")


# ------------------------------------------------------- refus d'inventer

def test_an_unknown_material_is_refused_not_guessed(machine, em6):
    """Usiner de l'inox avec des parametres d'aluminium casse l'outil au premier
    engagement. Une matiere absente de la table LEVE donc."""
    with pytest.raises(UnknownMaterialError, match="absente de la table"):
        build_recipe("titane-grade5", em6, machine)


def test_an_unknown_quality_is_refused(machine, em6):
    with pytest.raises(ValueError, match="qualite"):
        build_recipe("aluminium-6061", em6, machine, quality="tres-tres-vite")


def test_no_recipe_is_ever_declared_qualified(machine, em6):
    """Le logiciel ne peut pas qualifier une chaine mecanique assemblee par
    l'acheteur. ``qualified`` est donc faux, toujours, et l'enonce le dit."""
    for mat in MATERIALS:
        r = build_recipe(mat, em6, machine)
        assert r.qualified is False
        assert "NON QUALIFIEE" in r.describe()
        assert r.source and r.uncertainty


def test_load_is_derated_by_default_and_says_so(machine, em6):
    """Une note disant « commencer nettement en dessous » ne protege personne
    si le code livre quand meme les valeurs de table.

    La machine etant un kit dont la rigidite depend de l'assemblage, la charge
    est ramenee par defaut et le coefficient est rapporte.
    """
    reduit = build_recipe("aluminium-6061", em6, machine)
    plein = build_recipe("aluminium-6061", em6, machine, derating=1.0)

    assert reduit.derating < 1.0
    assert reduit.derating_reason
    assert reduit.depth_of_cut_mm < plein.depth_of_cut_mm
    assert reduit.width_of_cut_mm < plein.width_of_cut_mm
    assert reduit.feed_mm_min < plein.feed_mm_min
    assert "Charge reduite a" in dict(reduit.lines())

    with pytest.raises(ValueError, match="hors"):
        build_recipe("aluminium-6061", em6, machine, derating=1.8)


# ------------------------------------------------- physique du copeau

@pytest.mark.parametrize("ap,attendu", [
    (0.2, 2.15), (0.5, 3.32), (1.0, 4.47), (3.0, 6.0), (5.0, 6.0),
])
def test_effective_diameter_of_a_ball_nose(ap, attendu):
    """Une hemispherique engagee sous son rayon ne coupe pas a son diametre
    nominal : ``D_eff = 2.sqrt(D.ap - ap^2)``.

    A 0,2 mm de profondeur une fraise de 6 mm coupe a 2,15 mm. Employer la
    vitesse de broche du diametre nominal donne une vitesse de coupe reelle
    trois fois trop faible, et l'outil frotte au lieu de couper.
    """
    bn = build_ballnose("BN6", 6.0, 20.0, stickout=45.0, holder_type="ER16")
    assert effective_diameter(bn, ap) == pytest.approx(attendu, abs=0.01)


def test_a_flat_endmill_has_no_effective_diameter_correction(em6):
    for ap in (0.1, 1.0, 3.0):
        assert effective_diameter(em6, ap) == pytest.approx(6.0)


def test_radial_chip_thinning_is_one_at_half_diameter_and_grows_below():
    """Le facteur vaut 1 a ``ae = D/2`` et croit quand l'engagement diminue.

    Ne pas le poser fait travailler l'outil en frottement, ce qui l'use sans
    enlever de matiere.
    """
    assert radial_chip_thinning(6.0, 3.0) == pytest.approx(1.0)
    assert radial_chip_thinning(6.0, 4.0) == pytest.approx(1.0)
    croissant = [radial_chip_thinning(6.0, ae) for ae in (2.0, 1.0, 0.5, 0.2)]
    assert croissant == sorted(croissant), croissant
    assert radial_chip_thinning(6.0, 1e-9) <= 4.0, "le facteur doit rester borne"


# ------------------------------- les bridages sont dits, pas silencieux

def test_spindle_clamping_is_reported_and_vc_recomputed(machine):
    """Une recette qui plafonne sans le dire ferait croire a une vitesse de
    coupe qu'on n'atteint pas. La Vc rapportee vient de la vitesse BRIDEE."""
    petit = build_endmill("EM2", 2.0, 8.0, stickout=30.0, holder_type="ER16")
    r = build_recipe("bois-mdf", petit, machine, quality="finition")
    assert r.clamped, "une fraise de 2 mm en MDF doit plafonner la broche"
    assert r.spindle_rpm <= machine.spindle_max_rpm
    attendu = math.pi * r.effective_diameter_mm * r.spindle_rpm / 1000.0
    assert r.vc_effective_m_min == pytest.approx(attendu, rel=1e-9)


def test_a_cutting_speed_out_of_reach_raises_a_warning(machine, em6):
    """Cas reel de cette machine : plancher de broche a 6 000 tr/min.

    L'acier doux se coupe alors a 113 m/min au lieu des 40 vises — presque le
    triple, ce qui brule l'arete. Ce n'est pas un plafonnement benin mais une
    recette hors domaine, et le taire serait le pire service a rendre.
    """
    r = build_recipe("acier-s235", em6, machine, quality="ebauche")
    assert r.warnings, "aucun avertissement sur une Vc triple de la cible"
    assert "TROP ELEVEE" in r.warnings[0]
    assert r.vc_effective_m_min > 2.0 * MATERIALS["acier-s235"].vc_m_min["ebauche"]


def test_the_remedy_points_in_the_right_direction(machine):
    """Regression d'un conseil INVERSE.

    La broche etant bridee, ``Vc = pi.D.N/1000`` croit avec le diametre : pour
    BAISSER une vitesse trop elevee il faut un outil plus PETIT. Une premiere
    version conseillait le contraire, et la mesure l'avait pourtant montre —
    passer de 6 a 12 mm faisait monter Vc de 113 a 226 m/min.
    """
    vcs = {}
    for d in (3.0, 6.0, 12.0):
        t = build_endmill(f"EM{d:.0f}", d, 20.0, stickout=45.0, holder_type="ER16")
        r = build_recipe("acier-s235", t, machine, quality="ebauche")
        vcs[d] = r.vc_effective_m_min
        assert "plus PETIT" in r.warnings[0], (d, r.warnings)
    assert vcs[3.0] < vcs[6.0] < vcs[12.0], vcs

    # Et le diametre conseille doit effectivement tenir la cible.
    t = build_endmill("EM6", 6.0, 20.0, stickout=45.0, holder_type="ER16")
    r = build_recipe("acier-s235", t, machine, quality="ebauche")
    d_conseille = 1000.0 * MATERIALS["acier-s235"].vc_m_min["ebauche"] / (
        math.pi * r.spindle_rpm)
    t2 = build_endmill("EMc", round(d_conseille, 2), 8.0, stickout=30.0,
                       holder_type="ER16")
    r2 = build_recipe("acier-s235", t2, machine, quality="ebauche")
    assert not r2.warnings, (d_conseille, r2.warnings)


# --------------------------------------------- approche et degagement

def test_approach_starts_above_and_retract_ends_above():
    """Le chemin doit commencer et finir AU PLAN DE DEGAGEMENT, en rapide."""
    d = np.array([0.0, 0.0, 1.0])
    F = indexed_frame(d)
    P = np.array([[0.0, 0.0, 10.0], [5.0, 0.0, 10.0], [5.0, 5.0, 10.0]])
    R = np.zeros(len(P), dtype=bool)

    pts, rap = with_approach_retract(P, R, d, clearance_z=30.0, frame=F,
                                     standoff_mm=2.0)
    zi = (F @ pts.T).T[:, 2]

    assert len(pts) == len(P) + 4
    assert rap[0] and rap[-1], "les extremites doivent etre en rapide"
    assert zi[0] == pytest.approx(30.0)
    assert zi[-1] == pytest.approx(30.0)
    assert zi[1] == pytest.approx(12.0), "standoff de 2 mm au-dessus du point"
    assert not rap[2], "le dernier segment d'approche est en avance travail"
    assert zi[~rap].max() <= 12.0 + 1e-9


def test_clearance_below_the_path_is_raised_not_obeyed():
    """Un plan de degagement sous la matiere ferait descendre l'approche depuis
    l'interieur de la piece. On le releve au lieu de l'appliquer."""
    d = np.array([0.0, 0.0, 1.0])
    F = indexed_frame(d)
    P = np.array([[0.0, 0.0, 50.0], [5.0, 0.0, 50.0]])
    pts, _ = with_approach_retract(P, np.zeros(2, bool), d, clearance_z=1.0,
                                   frame=F, standoff_mm=3.0)
    zi = (F @ pts.T).T[:, 2]
    assert zi[0] >= 53.0 - 1e-9, zi[0]


def test_mismatched_flags_are_refused():
    d = np.array([0.0, 0.0, 1.0])
    with pytest.raises(ValueError, match="indicateurs"):
        with_approach_retract(np.zeros((3, 3)), np.zeros(2, bool), d,
                              clearance_z=10.0, frame=indexed_frame(d))


def test_an_empty_path_stays_empty():
    d = np.array([0.0, 0.0, 1.0])
    pts, rap = with_approach_retract(np.zeros((0, 3)), np.zeros(0, bool), d,
                                     clearance_z=10.0, frame=indexed_frame(d))
    assert len(pts) == 0 and len(rap) == 0


@pytest.mark.parametrize("direction", [
    [0.0, 0.0, 1.0], [0.0, -0.7071, 0.7071], [0.5, 0.5, 0.7071],
])
def test_approach_works_for_any_indexation(direction):
    """L'approche est definie dans le repere INDEXE : elle doit donc valoir
    pour toute direction d'outil, pas seulement +Z."""
    d = np.asarray(direction, dtype=float)
    d = d / np.linalg.norm(d)
    F = indexed_frame(d)
    P = np.array([[1.0, 2.0, 3.0], [4.0, 2.0, 3.0]])
    pts, rap = with_approach_retract(P, np.zeros(2, bool), d, clearance_z=40.0,
                                     frame=F, standoff_mm=1.5)
    zi = (F @ pts.T).T[:, 2]
    assert zi[0] == pytest.approx(40.0)
    # L'approche descend le long de la direction d'outil, donc elle ne bouge
    # pas dans le plan perpendiculaire.
    xy0 = (F @ pts[0])[:2]
    xy1 = (F @ pts[2])[:2]
    assert xy0 == pytest.approx(xy1, abs=1e-9)


# --------------------------------------- le plan porte tout le mouvement

def test_roughing_operations_carry_links_and_approach(corpus_dir):
    """Ce qui est POSTE doit etre ce qui a ete valide.

    L'operation portait ``toolpath_points``, qui ecarte les liaisons parce
    qu'il sert a la simulation d'enlevement de matiere. Le post-processeur
    reliait donc deux passes par une avance travail en ligne droite — a travers
    la piece.
    """
    from xyzac.stock_engine.material import MaterialState
    from xyzac.strategy_planner.planner import plan_roughing

    path = corpus_dir / "C02_poche_droite.step"
    shape = brep.load_step(path)
    bb = brep.bounding_box(shape)
    m = default_xyzac_kit()
    tool = build_endmill("EM6", 6.0, 20.0, stickout=45.0, holder_type="ER16")
    stock = stock_from_part(bb, margin_xy=2.0, margin_z_top=2.0, margin_z_bottom=2.0)
    setup = Setup(setup_id="m8", machine=m, part_step_path=str(path), stock=stock,
                  tools=[tool],
                  part_to_table_mm=[float(-bb.center[0]), float(-bb.center[1]), 25.0])
    verts, tris, _ = brep.tessellate(shape, deflection=0.5)
    mat = MaterialState.from_setup(stock, verts, tris, pitch=2.0)

    plan, rep = plan_roughing(shape, setup, mat, tool, max_setups=1,
                              layer_thickness=3.0)
    assert plan.operations, "aucune operation produite"
    op = plan.operations[0]

    assert op.toolpath.is_rapid is not None, "les liaisons ne sont pas marquees"
    R = np.asarray(op.toolpath.is_rapid, dtype=bool)
    assert R.any(), "aucun mouvement rapide : les liaisons ont disparu"
    assert not R.all(), "aucun mouvement de coupe"
    assert R[0] and R[-1], "l'approche et le degagement doivent etre en rapide"

    F = indexed_frame(np.asarray(rep.chosen[0].direction, dtype=float))
    zi = (F @ np.asarray(op.toolpath.points).T).T[:, 2]
    assert zi[0] > zi[~R].max(), "le depart doit etre au-dessus de toute coupe"
    assert zi[-1] > zi[~R].max(), "l'arrivee doit etre au-dessus de toute coupe"


def test_approach_and_retract_pass_the_sweep_gate(corpus_dir):
    """L'en-tete du G-code affirme que ces mouvements sont valides comme les
    autres. Ce test le VERIFIE, au lieu de laisser l'affirmation seule.

    L'approche descend d'un plan de degagement jusqu'a la surface et le
    degagement remonte : deux segments longs, exactement le genre que la
    subdivision de balayage existe pour couvrir. Les ajouter sans les faire
    valider serait la faute que ce projet refuse — et l'ecrire dans l'en-tete
    sans le tester en serait une autre.
    """
    from xyzac.collision_engine.sweep import SweepChecker
    from xyzac.kinematics_solver.solver import KinematicsSolver
    from xyzac.simulation_engine.scene import build_scene
    from xyzac.stock_engine.material import MaterialState
    from xyzac.strategy_planner.planner import plan_roughing

    path = corpus_dir / "C02_poche_droite.step"
    shape = brep.load_step(path)
    bb = brep.bounding_box(shape)
    m = default_xyzac_kit()
    tool = build_endmill("EM6", 6.0, 20.0, stickout=45.0, holder_type="ER16")
    stock = stock_from_part(bb, margin_xy=2.0, margin_z_top=2.0, margin_z_bottom=2.0)
    setup = Setup(setup_id="m8s", machine=m, part_step_path=str(path), stock=stock,
                  tools=[tool],
                  part_to_table_mm=[float(-bb.center[0]), float(-bb.center[1]), 25.0])
    verts, tris, _ = brep.tessellate(shape, deflection=0.5)
    mat = MaterialState.from_setup(stock, verts, tris, pitch=2.0)
    plan, rep = plan_roughing(shape, setup, mat, tool, max_setups=1,
                              layer_thickness=3.0)
    assert plan.operations

    op = plan.operations[0]
    P = np.asarray(op.toolpath.points, dtype=float)
    d = np.asarray(rep.chosen[0].direction, dtype=float)

    # Scene avec le BRUT intact : c'est l'etat dans lequel l'approche a lieu.
    scene = build_scene(setup, material_state="intact")
    ks = KinematicsSolver(m)
    sol = ks.ik_best(d, allow_singular=True)
    assert sol is not None

    # Les deux segments d'approche, et les deux de degagement.
    idx = [0, 1, 2, len(P) - 3, len(P) - 2, len(P) - 1]
    tcps = P[idx] + np.asarray(setup.mount_offset, dtype=float)
    axes = np.tile(d, (len(idx), 1))
    a_seq = np.full(len(idx), sol.a_deg)
    c_seq = np.full(len(idx), sol.c_deg)

    sweep = SweepChecker(m, tool, max_step_mm=0.5)
    reports = sweep.check_path(tcps, axes, a_seq, c_seq, scene.obstacles,
                              cutting_allowance=1.0)
    mauvais = [i for i, r in enumerate(reports) if not r.ok]
    assert not mauvais, (
        f"segments d'approche ou de degagement en collision : {mauvais} ; "
        f"{[reports[i].reason() for i in mauvais[:2]]}")
    assert all(r.n_samples >= 2 for r in reports), (
        "un segment long doit etre subdivise, pas teste a ses seules extremites")
