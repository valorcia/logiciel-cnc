"""Modele d'outil complet et moteur de collision."""

import numpy as np
import pytest

from xyzac.collision_engine import (
    ObstacleClass,
    ObstacleField,
    ToolCollisionChecker,
    signed_clearance_to_segment,
)
from xyzac.tool_model import SegmentRole, ToolAssembly, ToolSegment, build_endmill


def test_tool_stack_must_be_contiguous():
    """Un trou dans la pile rendrait un morceau d'outil invisible au solveur."""
    with pytest.raises(ValueError, match="trou ou recouvrement"):
        ToolAssembly(
            tool_id="bad", diameter=6.0, gauge_length=60.0,
            segments=[
                ToolSegment(role=SegmentRole.CUTTING, z_start=0, z_end=20, r_start=3, r_end=3),
                ToolSegment(role=SegmentRole.SHANK, z_start=25, z_end=60, r_start=3, r_end=3),
            ])


def test_tool_must_start_at_the_tip():
    with pytest.raises(ValueError, match="z=0"):
        ToolAssembly(
            tool_id="bad", diameter=6.0, gauge_length=60.0,
            segments=[ToolSegment(role=SegmentRole.CUTTING, z_start=2, z_end=60,
                                  r_start=3, r_end=3)])


def test_gauge_beyond_modelled_stack_is_refused():
    """Si la jauge depasse la pile modelisee, une partie de l'assemblage est
    invisible au solveur, qui conclurait a tort a l'absence de collision."""
    good = build_endmill("x", 6.0, 20.0, stickout=45.0)
    payload = good.model_dump()
    payload["gauge_length"] = good.total_length + 50.0
    with pytest.raises(ValueError, match="nez de broche"):
        ToolAssembly.model_validate(payload)


def test_full_tool_is_modelled_up_to_spindle_nose(tool):
    roles = {s.role for s in tool.segments}
    assert SegmentRole.CUTTING in roles
    assert SegmentRole.HOLDER in roles
    assert SegmentRole.SPINDLE_NOSE in roles, (
        "sans nez de broche modelise, le differenciateur produit n'existe pas")
    assert tool.max_radius > tool.radius * 3


@pytest.mark.parametrize("r,z,expected", [
    (0.0, 99.0, -20.0),   # au centre : la face la plus proche est un fond
    (29.0, 99.0, -1.0),   # dedans, pres de la paroi laterale
    (31.0, 99.0, 1.0),    # dehors radialement
    (10.0, 125.0, 6.0),   # dehors axialement
    (35.0, 125.0, np.hypot(5.0, 6.0)),  # dehors en coin
])
def test_signed_clearance_on_cylinder(r, z, expected):
    got = float(signed_clearance_to_segment(np.array([r]), np.array([z]),
                                            79.0, 119.0, 30.0, 30.0)[0])
    assert got == pytest.approx(expected, abs=1e-9)


def test_holder_collision_is_named_not_just_detected(tool):
    """Un rejet doit designer le troncon fautif : c'est ce qui permet a l'UI de
    proposer un remede plutot que d'afficher 'echec'."""
    ck = ToolCollisionChecker(tool)
    wall = np.array([[10.0, y, z] for y in np.linspace(-30, 30, 30)
                     for z in np.linspace(0, 120, 50)])
    f = ObstacleField.build(wall, part_spacing=1.0, safety_clearance=0.0)
    rep = ck.check(np.zeros(3), np.array([0.0, 0.0, 1.0]), f)
    assert rep.collided
    assert rep.worst_role in (SegmentRole.SPINDLE_NOSE, SegmentRole.HOLDER)
    assert "collision" in rep.reason()


def test_cutting_edge_may_enter_stock_but_not_fixture(tool):
    """Regle physique du moteur : la coupe traverse le brut (c'est l'usinage),
    jamais un bridage."""
    ck = ToolCollisionChecker(tool)
    blob = np.array([[0.0, 0.0, 5.0]])
    stock = ObstacleField(blob, [ObstacleClass.STOCK], [0.1])
    fixture = ObstacleField(blob, [ObstacleClass.FIXTURE], [0.1])
    axis = np.array([0.0, 0.0, 1.0])
    assert not ck.check(np.zeros(3), axis, stock).collided
    assert ck.check(np.zeros(3), axis, fixture).collided


def test_vectorized_matches_reference_loop(tool):
    """check_many doit donner EXACTEMENT le meme verdict que la boucle check().

    Test differentiel : c'est la seule protection contre une optimisation qui
    diverge silencieusement du chemin de reference.
    """
    ck = ToolCollisionChecker(tool)
    rng = np.random.default_rng(1)
    obs = rng.uniform(-60, 60, size=(2500, 3))
    f = ObstacleField.build(obs, part_spacing=1.0, safety_clearance=0.0)
    th = np.linspace(0, np.pi / 3, 48)
    axes = np.stack([np.sin(th), np.zeros_like(th), np.cos(th)], axis=1)
    tcps = rng.normal(scale=0.5, size=(48, 3))

    ref = np.array([not ck.check(tcps[i], axes[i], f).collided for i in range(48)])
    got, margin, _ = ck.check_many(tcps, axes, f)
    assert np.array_equal(ref, got)

    ref_m = np.array([ck.check(tcps[i], axes[i], f).min_margin for i in range(48)])
    fin = np.isfinite(ref_m) & np.isfinite(margin)
    assert np.abs(ref_m[fin] - margin[fin]).max() < 1e-9


def test_per_direction_tcp_is_honoured(tool):
    """Un TCP unique pour toutes les orientations fausserait la reponse d'un
    rayon d'outil des qu'il y a un rayon de bec."""
    ck = ToolCollisionChecker(tool)
    obs = np.array([[8.0, 0.0, 10.0]])
    f = ObstacleField(obs, [ObstacleClass.PART], [0.1])
    axes = np.tile([0.0, 0.0, 1.0], (2, 1))
    tcps = np.array([[0.0, 0.0, 0.0], [6.0, 0.0, 0.0]])
    _, margin, _ = ck.check_many(tcps, axes, f)
    assert margin[0] > margin[1], "les deux TCP doivent donner des marges differentes"
