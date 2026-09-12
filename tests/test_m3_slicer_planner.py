"""Slicer soustractif, planificateur de gammes, import STEP (jalon M3)."""

import numpy as np
import pytest

from xyzac.geometry_core import brep
from xyzac.geometry_core.healing import (
    UnusableShapeError,
    diagnose_step,
    load_step_checked,
    require_usable,
)
from xyzac.kinematics_solver import KinematicsSolver
from xyzac.machine_model import Setup, default_xyzac_kit
from xyzac.stock_engine import stock_from_part
from xyzac.stock_engine.material import MaterialState
from xyzac.strategy_planner import (
    candidate_directions,
    evaluate_candidates,
    indexed_orientation_plan,
    plan_roughing,
)
from xyzac.subtractive_slicer import (
    continuous_path,
    indexed_frame,
    simulate_removal,
    slice_for_direction,
)
from xyzac.subtractive_slicer.slicer import _disc, _dilate2d
from xyzac.tool_model import build_endmill


@pytest.fixture(scope="module")
def pocket(corpus_dir):
    shape = brep.load_step(corpus_dir / "C02_poche_droite.step")
    verts, tris, _ = brep.tessellate(shape, deflection=0.3)
    bb = brep.bounding_box(shape)
    stock = stock_from_part(bb, margin_xy=2.0, margin_z_top=2.0, margin_z_bottom=2.0)
    return shape, verts, tris, stock, bb


def _material(pocket, pitch=1.5, allowance=None):
    _, verts, tris, stock, _ = pocket
    return MaterialState.from_setup(stock, verts, tris, pitch=pitch,
                                    finish_allowance=allowance)


# ------------------------------------------------- surepaisseur metrique

@pytest.mark.parametrize("pitch", [1.6, 1.0, 0.7])
def test_finish_allowance_is_independent_of_grid_pitch(pocket, pitch):
    """Defaut mesure avant correction : une surepaisseur demandee a 0,2 mm
    devenait 1,6 / 1,0 / 0,7 mm selon le pas de grille, parce qu'elle etait
    realisee par une dilatation d'un nombre ENTIER de voxels.

    L'utilisateur reglait sa finition, et c'etait la resolution du solveur qui
    decidait. La transformee de distance respecte la valeur demandee.
    """
    _, _, _, _, _ = pocket
    ms = _material(pocket, pitch=pitch, allowance=0.2)
    part_volume = 72000.0
    # A 0,2 mm de surepaisseur, le protege depasse la piece de quelques pour
    # cent au plus — et non d'un tiers comme avec la dilatation entiere.
    assert ms.protected_volume_mm3 == pytest.approx(part_volume, rel=0.06)


def test_larger_allowance_protects_more(pocket):
    small = _material(pocket, pitch=1.0, allowance=0.2).protected_volume_mm3
    large = _material(pocket, pitch=1.0, allowance=2.0).protected_volume_mm3
    assert large > small * 1.2


# -------------------------------------------------------- visibilite

def test_reachability_is_direction_dependent_and_sensible(pocket):
    """Une poche ouverte vers le haut doit etre vue d'en haut, pas de cote."""
    ms = _material(pocket)
    top = ms.reachable_volume_mm3(np.array([0.0, 0.0, 1.0]))
    side = ms.reachable_volume_mm3(np.array([1.0, 0.0, 0.0]))
    assert top > side * 1.3


def test_protected_material_blocks_rays_but_removable_does_not(pocket):
    """Le brut rencontre en chemin ne bloque pas : il sera parti quand on
    arrivera la. Le compter comme obstacle declarerait tout inaccessible."""
    ms = _material(pocket)
    reach = ms.reachable_from(np.array([0.0, 0.0, 1.0]))
    assert reach.sum() > 0
    assert not (reach & ms.protected).any()


# ------------------------------------------------------- dilatation 2D

@pytest.mark.parametrize("r", [2.0, 3.0, 5.0])
def test_disc_dilation_has_the_right_area(r):
    d = _disc(r)
    assert d.sum() == pytest.approx(np.pi * r * r, rel=0.08)


@pytest.mark.parametrize("r,offset", [(3.0, (2, 2)), (5.0, (3, 4)), (5.0, (4, 3))])
def test_disc_covers_diagonals_that_the_l1_ball_misses(r, offset):
    """Une dilatation 4-connexe repetee donne la boule L1 — un LOSANGE plus
    PETIT que le disque dans les diagonales.

    Exemple : l'offset (2, 2) est a 2,83 du centre, donc DANS le disque de
    rayon 3, mais a 4 en distance L1, donc hors du losange. Appliquee a la zone
    interdite, la boule L1 autoriserait des positions d'outil qui gougent.
    """
    dx, dy = offset
    assert np.hypot(dx, dy) <= r, "l'offset doit etre dans le disque"
    assert dx + dy > r, "et hors du losange L1, sinon le test ne prouve rien"
    d = _disc(r)
    c = d.shape[0] // 2
    assert d[c + dy, c + dx]


def test_dilation_reaches_the_full_radius():
    m = np.zeros((21, 21), dtype=bool)
    m[10, 10] = True
    grown = _dilate2d(m, 3.0)
    assert grown[10, 13] and grown[13, 10]     # axes
    assert grown[12, 12]                       # diagonale a 2,83 <= 3


# ------------------------------------------------------------ tranchage

def test_indexed_frame_maps_direction_to_z():
    for d in ([0, 0, 1], [1, 0, 0], [0.3, 0.5, 0.8]):
        d = np.array(d, float) / np.linalg.norm(d)
        assert np.allclose(indexed_frame(d) @ d, [0, 0, 1], atol=1e-12)


def test_slicing_produces_layers_and_a_clearance_plane(pocket, tool):
    ms = _material(pocket)
    r = slice_for_direction(ms, np.array([0.0, 0.0, 1.0]), tool, layer_thickness=2.5)
    assert r.layers
    assert np.allclose(indexed_frame(r.direction), r.frame)
    # ``clearance_z`` est une COTE dans le repere indexe, ``depth_from_top`` une
    # profondeur relative : les comparer directement n'aurait pas de sens. Ce
    # qui doit tenir, c'est que le plan de degagement domine tous les points de
    # coupe, exprimes dans le meme repere.
    pts, rapid = continuous_path(r, 2.0)
    z_index = (pts @ r.frame.T)[:, 2]
    assert r.clearance_z >= z_index.max() - 1e-6
    assert r.clearance_z > z_index[~rapid].max()


def test_roughing_never_gouges_the_protected_part(pocket, tool):
    """Propriete la plus importante du slicer : il peut laisser de la matiere,
    il ne doit JAMAIS entamer la piece."""
    ms = _material(pocket, pitch=1.5)
    r = slice_for_direction(ms, np.array([0.0, 0.0, 1.0]), tool,
                            layer_thickness=2.5, safety_clearance=0.3)
    stats = simulate_removal(ms, r, tool, point_spacing=1.5)
    assert stats.gouged_voxels == 0, (
        f"{stats.gouged_voxels} voxels de la piece finale ont ete entames")


def test_roughing_removes_a_large_share_of_what_it_sees(pocket, tool):
    ms = _material(pocket, pitch=1.5)
    r = slice_for_direction(ms, np.array([0.0, 0.0, 1.0]), tool, layer_thickness=2.5)
    stats = simulate_removal(ms, r, tool, point_spacing=1.5)
    assert stats.removed_mm3 > 0.4 * r.reachable_mm3


def test_grid_extends_beyond_the_stock_for_profiling(pocket, tool):
    """Pour profiler un flanc, le centre de l'outil est HORS du brut. Une grille
    calee sur la matiere n'a pas de cellule pour l'accueillir, et le flanc reste
    intact — 8 000 mm3 jamais touches sur un simple pave, avant correction."""
    ms = _material(pocket, pitch=1.5)
    r = slice_for_direction(ms, np.array([0.0, 0.0, 1.0]), tool, layer_thickness=2.5)
    pts, _ = continuous_path(r, 2.0)
    lo, hi = ms.grid.origin, ms.grid.origin + np.array(ms.grid.shape) * ms.grid.pitch
    outside = np.any((pts < lo) | (pts > hi), axis=1)
    assert outside.any(), "aucune position d'outil hors du brut : pas de profilage"


def test_link_moves_are_explicit_and_flagged(pocket, tool):
    """Les liaisons entre passes doivent exister dans la trajectoire.

    Sans elles, le validateur relie les extremites en ligne droite — et cette
    droite traverse la matiere. Les collisions signalees etaient reelles : la
    trajectoire, telle que decrite, passait dans la piece.
    """
    ms = _material(pocket, pitch=1.5)
    r = slice_for_direction(ms, np.array([0.0, 0.0, 1.0]), tool, layer_thickness=2.5)
    pts, rapid = continuous_path(r, 2.0)
    assert rapid.any() and not rapid.all()
    # Les liaisons remontent au plan de degagement, exprime dans le repere indexe.
    z_index = pts @ r.frame.T
    assert z_index[rapid, 2].max() == pytest.approx(r.clearance_z, abs=1e-6)
    assert z_index[~rapid, 2].max() < r.clearance_z


def test_link_moves_are_sparse(pocket, tool):
    """Une liaison est une droite : la densifier au pas des points de coupe
    gonflait le programme de 94 % de points qui n'enlevent rien. La subdivision
    est le travail du verificateur de balayage."""
    ms = _material(pocket, pitch=1.5)
    r = slice_for_direction(ms, np.array([0.0, 0.0, 1.0]), tool, layer_thickness=2.5)
    _, rapid = continuous_path(r, 2.0)
    assert rapid.mean() < 0.5


# ----------------------------------------------------------- planning

def test_vertical_indexation_is_a_valid_candidate(machine):
    """La singularite A -> 0 est un probleme de MOUVEMENT, pas de POSITION.

    En 3+2 l'axe C est bloque : il n'y a rien a suivre, donc rien de mal
    conditionne. Refuser A = 0 en indexation interdirait l'usinage vertical —
    la prise la plus courante d'une XYZAC. Avant correction, le planner ne
    proposait jamais +Z et laissait intacte toute poche ouverte vers le haut.
    """
    kin = KinematicsSolver(machine)
    up = np.array([0.0, 0.0, 1.0])
    assert kin.ik_best(up) is None                       # refuse par defaut
    sol = kin.ik_best(up, allow_singular=True)
    assert sol is not None and abs(sol.a_deg) < 1e-9


def test_candidates_are_filtered_by_machine_travel(pocket, tool):
    """-Z demande A = 180 deg : hors des courses du berceau. Le planner ne doit
    pas le proposer — usiner le dessous exige une reprise, pas une indexation."""
    shape, _, _, stock, bb = pocket
    setup = Setup(setup_id="p", machine=default_xyzac_kit(), part_step_path="x.step",
                  stock=stock, tools=[tool])
    ms = _material(pocket)
    cands = evaluate_candidates(candidate_directions(shape, setup), ms, setup)
    dirs = [c.direction for c in cands]
    assert any(np.allclose(d, [0, 0, 1]) for d in dirs), "+Z doit etre candidate"
    assert not any(np.allclose(d, [0, 0, -1]) for d in dirs), "-Z est hors courses"


def test_greedy_plan_covers_most_of_the_material(pocket, tool):
    shape, _, _, stock, bb = pocket
    setup = Setup(setup_id="p", machine=default_xyzac_kit(), part_step_path="x.step",
                  stock=stock, tools=[tool],
                  part_to_table_mm=[float(-bb.center[0]), float(-bb.center[1]), 25.0])
    ms = _material(pocket, pitch=1.6)
    plan, report = plan_roughing(shape, setup, ms, tool, layer_thickness=3.0,
                                 point_spacing=2.0, max_setups=4)
    assert plan.operations
    assert report.removed_fraction > 0.4
    assert report.gouged_voxels == 0


def test_plan_report_keeps_the_full_candidate_list(pocket, tool):
    """Bug corrige : la liste des candidates etait videe pendant la boucle, ce
    qui faisait attribuer a « aucune direction ne le voit » de la matiere que
    des directions non retenues voyaient parfaitement."""
    shape, _, _, stock, bb = pocket
    setup = Setup(setup_id="p", machine=default_xyzac_kit(), part_step_path="x.step",
                  stock=stock, tools=[tool],
                  part_to_table_mm=[0.0, 0.0, 25.0])
    ms = _material(pocket, pitch=2.0)
    _, report = plan_roughing(shape, setup, ms, tool, layer_thickness=4.0,
                              point_spacing=3.0, max_setups=2)
    assert len(report.candidates) >= len(report.chosen)
    assert len(report.candidates) >= 4


def test_indexed_plan_has_constant_orientation(pocket, tool):
    _, _, _, stock, _ = pocket
    setup = Setup(setup_id="p", machine=default_xyzac_kit(), part_step_path="x.step",
                  stock=stock, tools=[tool])
    pts = np.zeros((7, 3))
    plan = indexed_orientation_plan(pts, np.array([0.0, 0.0, 1.0]), setup)
    assert plan.feasible
    assert len(set(plan.a_deg)) == 1 and len(set(plan.c_deg)) == 1
    assert plan.indexed_fraction == 1.0


# ------------------------------------------------------- import STEP

def test_clean_step_is_not_healed(corpus_dir):
    """ShapeFix peut deteriorer une geometrie saine. On ne repare pas ce qui
    n'est pas casse."""
    _, diag, heal = load_step_checked(corpus_dir / "C11_cavite_spherique.step")
    assert not diag.needs_healing
    assert not heal.applied


def test_open_shell_is_detected_and_refused(degraded_dir):
    """Un shell ouvert est topologiquement VALIDE et OCCT lui calcule meme un
    volume plausible, par integration sur ses faces. Ce qui trahit le defaut,
    c'est l'absence de solide — sans quoi le lancer de rayons de la voxelisation
    remplit la matiere n'importe comment, et le moteur rend une gamme credible
    et fausse.
    """
    shape, diag, heal = load_step_checked(degraded_dir / "D01_shell_ouvert.step")
    assert diag.n_solids == 0
    assert diag.needs_healing
    assert not heal.resolved, "ShapeFix ne peut pas inventer la face manquante"
    with pytest.raises(UnusableShapeError, match="aucun solide"):
        require_usable(shape, heal.after or diag)


def test_unit_confusion_is_flagged_as_plausibility_not_defect(degraded_dir):
    """Une piece de 2 mm est saine : ce n'est pas un defaut a reparer, c'est une
    question a poser. Confondre les deux ferait passer ShapeFix sur une piece
    intacte."""
    _, diag, heal = load_step_checked(degraded_dir / "D02_unites_pouces.step")
    assert not diag.geometry_issues
    assert diag.plausibility_warnings
    assert not heal.applied
    assert "25,4" in " ".join(diag.plausibility_warnings)


def test_oversized_part_is_flagged(degraded_dir):
    _, diag, heal = load_step_checked(degraded_dir / "D03_trop_grande.step")
    assert diag.plausibility_warnings and not diag.geometry_issues
    assert not heal.applied


def test_healing_refuses_to_change_the_part(corpus_dir):
    """Garde-fou : une reparation qui deplace la matiere de plus d'un millieme
    n'est plus une reparation, c'est une modification de la piece — et ce n'est
    pas a un outil de la decider a la place du concepteur."""
    from xyzac.geometry_core.healing import heal_shape

    shape = brep.load_step(corpus_dir / "C13_arbre_gorge_torique.step")
    diag = diagnose_step(corpus_dir / "C13_arbre_gorge_torique.step", shape=shape)
    # On force un besoin de reparation avec une precision absurde.
    diag.geometry_issues.append("defaut simule pour le test")
    res = heal_shape(shape, diag, tolerance=5.0, max_volume_change_ratio=1e-9)
    if res.applied:
        assert res.volume_change_ratio <= 1e-9
    else:
        assert "REFUSEE" in res.reason or "saine" in res.reason


def test_fixtures_are_protected_material(pocket, tool):
    """Le slicer ne connait que deux choses : la matiere a enlever et la piece a
    conserver. Un bridage n'etant ni l'une ni l'autre, il planifiait des passes
    jusqu'au fond du brut — c'est-a-dire DANS l'etau. Le validateur les refusait
    ensuite avec des penetrations de plusieurs millimetres.

    Les traiter comme « protege » est la bonne semantique : un bridage ne
    s'enleve pas, et il masque une direction exactement comme la piece.
    """
    from xyzac.machine_model import Fixture, FixtureKind

    _, _, _, stock, _ = pocket
    jaw = Fixture(name="mors", kind=FixtureKind.VISE,
                  lo=[float(stock.lo[0]) - 10, float(stock.lo[1]) - 4,
                      float(stock.lo[2]) - 10],
                  hi=[float(stock.lo[0]) + 1, float(stock.hi[1]) + 4,
                      float(stock.lo[2]) + 4],
                  keepout_mm=1.5)
    setup = Setup(setup_id="fx", machine=default_xyzac_kit(), part_step_path="x.step",
                  stock=stock, fixtures=[jaw], tools=[tool])

    ms = _material(pocket, pitch=1.5)
    before = ms.protected_volume_mm3
    added = ms.protect_fixtures(setup)
    assert added > 0
    assert ms.protected_volume_mm3 > before

    # Et la consequence attendue : la zone du mors n'est plus enlevable.
    centers = ms.grid.centers().reshape(ms.grid.shape + (3,))
    in_jaw = np.all((centers >= np.array(jaw.lo)) & (centers <= np.array(jaw.hi)), axis=-1)
    assert not (ms.removable() & in_jaw).any()
