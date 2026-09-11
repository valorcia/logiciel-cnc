"""Accessibility solver, orientation solver, et leurs proprietes attendues."""

import numpy as np
import pytest

from xyzac.accessibility_solver import (
    AccessibilityConfig,
    AccessibilitySolver,
    RejectReason,
    tcp_from_contact,
)
from xyzac.collision_engine import ObstacleClass, ObstacleField
from xyzac.orientation_solver import OrientationSolver, OrientationWeights
from xyzac.tool_model import build_ballnose, build_endmill  # noqa: F401


#: Hauteur de la face d'essai au-dessus de l'origine piece.
#: Le plateau C du modele machine occupe z in [-12, 0] : poser la face a z = 0
#: la placerait EXACTEMENT sur le plateau, et le garde machine rejetterait
#: toutes les orientations — a juste titre. On travaille donc a une hauteur de
#: piece realiste.
FACE_Z = 30.0


@pytest.fixture
def open_field():
    """Un plan horizontal seul, au-dessus du plateau : cas le plus permissif."""
    g = np.stack(np.meshgrid(np.linspace(-40, 40, 40), np.linspace(-40, 40, 40)), -1)
    pts = np.concatenate([g.reshape(-1, 2), np.full((1600, 1), FACE_Z)], axis=1)
    return ObstacleField.build(pts, part_spacing=2.0, safety_clearance=0.2)


def test_tcp_equals_contact_for_flat_endmill_on_normal_axis():
    t = build_endmill("e", 6.0, 20.0, stickout=45.0)
    p = np.array([1.0, 2.0, 3.0])
    n = np.array([0.0, 0.0, 1.0])
    assert np.allclose(tcp_from_contact(p, n, n, t), p)


def test_tcp_offsets_by_radius_for_ballnose():
    """Confondre le bec et le point de contact decale la piece du rayon de
    l'outil — erreur silencieuse et systematique."""
    t = build_ballnose("b", 6.0, 20.0, stickout=45.0)
    p = np.array([0.0, 0.0, 0.0])
    n = np.array([0.0, 0.0, 1.0])
    tcp = tcp_from_contact(p, n, n, t)
    assert np.allclose(tcp, [0, 0, 0], atol=1e-9)   # axe = normale : bec au contact
    d = np.array([1.0, 0.0, 1.0]) / np.sqrt(2)
    tcp2 = tcp_from_contact(p, n, d, t)
    assert np.linalg.norm(tcp2 - p) == pytest.approx(t.radius * np.sqrt(2 - np.sqrt(2)),
                                                     rel=0.2)


def test_back_facing_directions_are_rejected(machine, tool, open_field):
    s = AccessibilitySolver(tool, machine, open_field,
                            AccessibilityConfig(subdivisions=2, max_lead_deg=45.0))
    m = s.solve_point(np.array([0.0, 0.0, FACE_Z]), np.array([0.0, 0.0, 1.0]))
    assert np.all(m.directions[m.feasible] @ np.array([0, 0, 1.0]) > 0)


def test_lead_limit_is_enforced(machine, tool, open_field):
    lead = 30.0
    s = AccessibilitySolver(tool, machine, open_field,
                            AccessibilityConfig(subdivisions=3, max_lead_deg=lead))
    m = s.solve_point(np.array([0.0, 0.0, FACE_Z]), np.array([0.0, 0.0, 1.0]))
    ang = np.degrees(np.arccos(np.clip(m.directions[m.feasible] @ np.array([0, 0, 1.0]), -1, 1)))
    assert ang.size == 0 or ang.max() <= lead + 1e-6


def test_rejection_always_carries_a_reason_and_a_remedy(machine, tool):
    """Un rejet sans remede laisse l'utilisateur bloque sans levier."""
    from xyzac.accessibility_solver.solver import REMEDY
    wall = np.array([[x, y, z] for x in (-9.0, 9.0)
                     for y in np.linspace(-30, 30, 25)
                     for z in np.linspace(-5, 90, 40)])
    f = ObstacleField.build(wall, part_spacing=2.0, safety_clearance=0.2)
    s = AccessibilitySolver(tool, machine, f, AccessibilityConfig(subdivisions=2))
    m = s.solve_point(np.array([0.0, 0.0, FACE_Z]), np.array([0.0, 0.0, 1.0]))
    assert not m.accessible, "une rainure de 18 mm ne laisse pas passer un ER16"
    dom = m.dominant_reason()
    assert dom is not None and dom is not RejectReason.OK
    assert dom in REMEDY, f"aucun remede propose pour {dom.name}"


def test_singularity_is_rejected_when_configured(machine, tool, open_field):
    """Une face horizontale place l'axe outil sur Z piece : A -> 0, C indetermine."""
    s = AccessibilitySolver(tool, machine, open_field,
                            AccessibilityConfig(subdivisions=3, max_lead_deg=5.0,
                                                reject_singular=True))
    m = s.solve_point(np.array([0.0, 0.0, FACE_Z]), np.array([0.0, 0.0, 1.0]))
    assert np.all(np.abs(m.a_deg[m.feasible]) >= machine.singularity_a_deg - 1e-9)


def test_accessibility_map_exposes_cones(machine, tool, open_field):
    s = AccessibilitySolver(tool, machine, open_field, AccessibilityConfig(subdivisions=3))
    m = s.solve_point(np.array([0.0, 0.0, FACE_Z]), np.array([0.0, 0.0, 1.0]))
    if m.accessible:
        cones = m.cones()
        assert cones and sum(len(c) for c in cones) == m.n_feasible


def test_two_sided_bounds_never_disagree_with_exact_test(machine, tool, open_field):
    """Une borne qui contredit le test exact n'est pas une borne : c'est un
    second solveur, plus faux que le premier."""
    a = AccessibilitySolver(tool, machine, open_field,
                            AccessibilityConfig(subdivisions=2, use_two_sided_bounds=True))
    b = AccessibilitySolver(tool, machine, open_field,
                            AccessibilityConfig(subdivisions=2, use_two_sided_bounds=False))
    for p in ([0, 0, FACE_Z], [10, -5, FACE_Z], [-20, 15, FACE_Z]):
        ma = a.solve_point(np.array(p, float), np.array([0.0, 0.0, 1.0]))
        mb = b.solve_point(np.array(p, float), np.array([0.0, 0.0, 1.0]))
        assert np.array_equal(ma.feasible, mb.feasible)


# ---------------------------------------------------------------- orientation

@pytest.fixture(scope="module")
def ballnose():
    """Les essais d'orientation utilisent une hemispherique, et ce n'est pas un
    detail de commodite.

    Sur une face plane, une fraise a bout DROIT ne peut pas etre inclinee sans
    que son talon gouge : la seule orientation saine est verticale, c'est-a-dire
    exactement la singularite A = 0. C'est un conflit reel et connu du 5 axes
    AC, pas un artefact du solveur — et c'est precisement pourquoi on surface
    ces formes a l'hemispherique, dont le bec spherique tolere l'inclinaison.
    """
    return build_ballnose("BN6", 6.0, 20.0, stickout=45.0, holder_type="ER16")


def _maps(machine, tool, field_, n=12, normal=(0.0, 0.0, 1.0)):
    s = AccessibilitySolver(tool, machine, field_,
                            AccessibilityConfig(subdivisions=3, max_lead_deg=45.0))
    pts = np.stack([np.linspace(-15, 15, n), np.zeros(n), np.full(n, FACE_Z)], axis=1)
    return pts, [s.solve_point(p, np.array(normal)) for p in pts]


def test_orientation_plan_is_deterministic(machine, ballnose, open_field):
    """Deux executions sur la meme entree doivent donner le meme G-code.
    Propriete non negociable pour une machine."""
    pts, amaps = _maps(machine, ballnose, open_field)
    o = OrientationSolver(machine, ballnose, OrientationWeights())
    p1 = o.solve(amaps, path_points=pts)
    p2 = o.solve(amaps, path_points=pts)
    assert np.array_equal(p1.a_deg, p2.a_deg)
    assert np.array_equal(p1.c_deg, p2.c_deg)
    assert p1.total_cost == p2.total_cost


def test_orientation_sequence_has_no_plateau_flip(machine, ballnose, open_field):
    """Le symptome que toute l'architecture de sequence existe pour eviter :
    un retournement de C de 180 deg en pleine passe."""
    pts, amaps = _maps(machine, ballnose, open_field)
    assert all(m.accessible for m in amaps)
    plan = OrientationSolver(machine, ballnose).solve(amaps, path_points=pts)
    assert plan.feasible
    assert np.abs(np.diff(plan.c_deg)).max() < 170.0


def test_common_orientation_yields_indexed_segment(machine, ballnose, open_field):
    """Une face plane admet une orientation commune : le moteur doit conclure
    en 3+2, pas en simultane. C'est la regle « 3+2 quand possible »."""
    pts, amaps = _maps(machine, ballnose, open_field)
    assert all(m.accessible for m in amaps)
    plan = OrientationSolver(machine, ballnose).solve(amaps, path_points=pts)
    assert plan.feasible
    assert plan.indexed_fraction > 0.9, (
        "une face plane accessible doit se couvrir en 3+2")
    assert all(s.mode == "3+2" for s in plan.segments)


def test_plan_reports_inaccessible_points_instead_of_guessing(machine, ballnose):
    """Une trajectoire partiellement inaccessible n'est pas 'presque bonne' :
    le plan doit le dire et nommer les points."""
    box = np.array([[x, y, z] for x in np.linspace(-8, 8, 18)
                    for y in np.linspace(-8, 8, 18)
                    for z in (FACE_Z - 2.0, FACE_Z + 60.0)])
    f = ObstacleField.build(box, part_spacing=1.5, safety_clearance=0.5)
    pts, amaps = _maps(machine, ballnose, f, n=6)
    plan = OrientationSolver(machine, ballnose).solve(amaps, path_points=pts)
    if not plan.feasible:
        assert plan.failures
        assert "INCOMPLET" in plan.summary()


# ------------------------------------------------------------- jalon M2

def test_seeds_can_only_enlarge_the_admissible_set(machine, tool):
    """Propriete GARANTIE des germes : ils ajoutent des candidats, ils n'en
    retirent aucun. L'ensemble admissible avec germes contient donc toujours
    celui sans germes.

    C'est ce que l'on peut affirmer sans condition. Le gain reel, lui, depend
    de la geometrie — il est mesure par le test suivant.
    """
    g = np.stack(np.meshgrid(np.linspace(-30, 30, 30), np.linspace(10, 70, 30)), -1)
    g = g.reshape(-1, 2)
    pts = np.concatenate([np.zeros((len(g), 1)), g], axis=1)
    f = ObstacleField.build(pts, part_spacing=2.0, safety_clearance=0.2)

    def solve(seeds: bool, p, n):
        cfg = AccessibilityConfig(subdivisions=3, max_lead_deg=45.0,
                                  seed_directions=seeds, check_machine=False)
        return AccessibilitySolver(tool, machine, f, cfg).solve_point(p, n)

    for z in (25.0, 40.0, 55.0):
        p, n = np.array([0.0, 0.0, z]), np.array([1.0, 0.0, 0.0])
        assert solve(True, p, n).n_feasible >= solve(False, p, n).n_feasible


def test_seeds_recover_directions_the_uniform_grid_misses(machine, tool):
    """Sur une face usinee en bout a la fraise a bout DROIT, l'ensemble
    admissible est une lamelle etroite autour de la normale : incliner l'outil
    enfonce son talon dans la matiere.

    Une grille icospherique de pas 8,6 deg n'a aucune raison d'avoir un sommet
    dans cette lamelle. Les germes garantissent que la normale EXACTE et son
    voisinage immediat sont toujours evalues — sans quoi la solution depend de
    l'alignement fortuit entre la grille et la piece, ce qui est exactement ce
    qu'un moteur deterministe ne doit pas tolerer.

    Mesure sur ce cas : 1 direction admissible avec la grille seule, 2 avec les
    germes, dont la normale exacte a 0,000 deg pres.
    """
    g = np.stack(np.meshgrid(np.linspace(-30, 30, 35), np.linspace(10, 70, 35)), -1)
    g = g.reshape(-1, 2)
    pts = np.concatenate([np.zeros((len(g), 1)), g], axis=1)
    f = ObstacleField.build(pts, part_spacing=2.0, safety_clearance=0.2)
    p, n = np.array([0.0, 0.0, 40.0]), np.array([1.0, 0.0, 0.0])

    def solve(seeds: bool):
        cfg = AccessibilityConfig(subdivisions=3, max_lead_deg=45.0,
                                  seed_directions=seeds, check_machine=False)
        return AccessibilitySolver(tool, machine, f, cfg).solve_point(p, n)

    sans, avec = solve(False), solve(True)
    assert avec.n_feasible > sans.n_feasible

    # La normale exacte doit figurer parmi les candidats ET etre admissible.
    dots = avec.directions @ n
    k = int(np.argmax(dots))
    assert np.degrees(np.arccos(np.clip(dots[k], -1, 1))) < 1e-6
    assert avec.feasible[k], "la normale exacte a ete evaluee mais rejetee"


def test_machine_guard_rejects_a_part_sitting_on_the_table(machine, ballnose):
    """Une piece posee a l'origine du plateau y est encastree : le garde doit
    le refuser, et c'est un defaut de MONTAGE, pas de solveur.

    On emploie une hemispherique pour que le rejet vienne bien du PLATEAU : avec
    une fraise a bout droit, les collisions piece domineraient et masqueraient
    ce que ce test cherche a verifier.
    """
    g = np.stack(np.meshgrid(np.linspace(-30, 30, 30), np.linspace(-30, 30, 30)), -1)
    pts = np.concatenate([g.reshape(-1, 2), np.zeros((900, 1))], axis=1)
    f = ObstacleField.build(pts, part_spacing=2.0, safety_clearance=0.2)
    s = AccessibilitySolver(ballnose, machine, f,
                            AccessibilityConfig(subdivisions=2, check_machine=True))
    m = s.solve_point(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]))
    assert m.n_feasible == 0
    assert m.dominant_reason() is RejectReason.MACHINE_COLLISION


def test_indexed_segment_is_verified_exactly_not_just_proposed(machine, ballnose, open_field):
    """L'intersection d'ensembles travaille sur des indices de grille, or les
    germes n'en sont pas — ils sont rattaches au sommet le plus proche. La
    segmentation 3+2 doit donc REVERIFIER l'orientation qu'elle propose.
    """
    pts, amaps = _maps(machine, ballnose, open_field)
    calls = {"n": 0}

    def verify(index, direction):
        calls["n"] += 1
        return True, 1.0

    plan = OrientationSolver(machine, ballnose).solve(amaps, path_points=pts, verify=verify)
    assert calls["n"] > 0, "l'orientation commune a ete acceptee sans verification"
    assert any(s.mode == "3+2" for s in plan.segments)


def test_indexed_segment_falls_back_when_verification_refuses(machine, ballnose, open_field):
    """Si la verification refuse toutes les candidates, le segment doit basculer
    en simultane — jamais etre indexe sur une orientation non verifiee."""
    pts, amaps = _maps(machine, ballnose, open_field)
    plan = OrientationSolver(machine, ballnose).solve(
        amaps, path_points=pts, verify=lambda i, d: (False, -1.0))
    assert all(s.mode == "simultane" for s in plan.segments)


def test_refinement_respects_machine_limits(machine, ballnose, open_field):
    """Mesure qui a impose ``make_pose_verifier`` : un raffinement qui ne
    connait que la piece gagne de la marge en poussant un axe lineaire hors
    course — meilleur sur le critere optimise, irrealisable sur la machine."""
    from xyzac.kinematics_solver import KinematicsSolver

    pts, amaps = _maps(machine, ballnose, open_field)
    osolver = OrientationSolver(machine, ballnose)
    plan = osolver.solve(amaps, path_points=pts)
    if not plan.feasible:
        pytest.skip("scene trop contrainte")

    kin = KinematicsSolver(machine)
    refined = osolver.refine(plan, amaps, lambda i, d: (True, 1.0),
                             half_angle_deg=5.0, iterations=1)
    for i in range(refined.n_points):
        assert kin.ik_best(refined.directions[i]) is not None
        assert machine.a.contains(refined.a_deg[i])


def test_refinement_does_not_blow_up_rotary_travel(machine, ballnose, open_field):
    """Le raffinement optimise la marge, mais pas au prix de n'importe quoi.

    Mesure qui a impose le terme de course rotative dans son score : en ne
    penalisant que l'ecart angulaire entre directions VOISINES, le raffinement
    gagnait 0,26 mm de marge en faisant passer la course A+C de 86 a 145 deg.
    Deux directions peuvent etre tres proches sur la sphere et demander des
    couples (A, C) tres eloignes — c'est la difficulte propre a la cinematique
    AC, et un proxy purement geometrique ne la voit pas.

    On borne donc l'augmentation acceptable plutot que de la laisser libre.
    """
    pts, amaps = _maps(machine, ballnose, open_field)
    osolver = OrientationSolver(machine, ballnose)
    plan = osolver.solve(amaps, path_points=pts)
    if not plan.feasible:
        pytest.skip("scene trop contrainte")

    refined = osolver.refine(plan, amaps, lambda i, d: (True, 2.0),
                             half_angle_deg=5.0, iterations=1)
    before = sum(plan.rotary_travel())
    after = sum(refined.rotary_travel())
    assert after <= before * 1.5 + 30.0, (
        f"course rotative A+C passee de {before:.1f} a {after:.1f} deg")
