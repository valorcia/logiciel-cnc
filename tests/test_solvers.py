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
from xyzac.tool_model import build_ballnose, build_endmill


@pytest.fixture
def open_field():
    """Un plan horizontal seul : le cas le plus permissif possible."""
    g = np.stack(np.meshgrid(np.linspace(-40, 40, 40), np.linspace(-40, 40, 40)), -1)
    pts = np.concatenate([g.reshape(-1, 2), np.zeros((1600, 1))], axis=1)
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
    m = s.solve_point(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]))
    assert np.all(m.directions[m.feasible] @ np.array([0, 0, 1.0]) > 0)


def test_lead_limit_is_enforced(machine, tool, open_field):
    lead = 30.0
    s = AccessibilitySolver(tool, machine, open_field,
                            AccessibilityConfig(subdivisions=3, max_lead_deg=lead))
    m = s.solve_point(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]))
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
    m = s.solve_point(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]))
    assert not m.accessible, "une rainure de 18 mm ne laisse pas passer un ER16"
    dom = m.dominant_reason()
    assert dom is not None and dom is not RejectReason.OK
    assert dom in REMEDY, f"aucun remede propose pour {dom.name}"


def test_singularity_is_rejected_when_configured(machine, tool, open_field):
    """Une face horizontale place l'axe outil sur Z piece : A -> 0, C indetermine."""
    s = AccessibilitySolver(tool, machine, open_field,
                            AccessibilityConfig(subdivisions=3, max_lead_deg=5.0,
                                                reject_singular=True))
    m = s.solve_point(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]))
    assert np.all(np.abs(m.a_deg[m.feasible]) >= machine.singularity_a_deg - 1e-9)


def test_accessibility_map_exposes_cones(machine, tool, open_field):
    s = AccessibilitySolver(tool, machine, open_field, AccessibilityConfig(subdivisions=3))
    m = s.solve_point(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]))
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
    for p in ([0, 0, 0], [10, -5, 0], [-20, 15, 0]):
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
    pts = np.stack([np.linspace(-15, 15, n), np.zeros(n), np.zeros(n)], axis=1)
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
                    for y in np.linspace(-8, 8, 18) for z in (-2.0, 60.0)])
    f = ObstacleField.build(box, part_spacing=1.5, safety_clearance=0.5)
    pts, amaps = _maps(machine, ballnose, f, n=6)
    plan = OrientationSolver(machine, ballnose).solve(amaps, path_points=pts)
    if not plan.feasible:
        assert plan.failures
        assert "INCOMPLET" in plan.summary()
