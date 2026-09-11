"""Cinematique XYZAC : l'identite fondatrice et ses consequences."""

import math

import numpy as np
import pytest

from xyzac.kinematics_solver import KinematicsSolver


def test_forward_kinematics_maps_tool_axis_to_machine_z(machine):
    """R_machine<-piece . d_piece(A,C) = +Z machine, pour tout (A, C).

    Toute la cinematique du projet decoule de cette identite. Si elle tombe,
    chaque orientation calculee est fausse et rien en aval ne peut le rattraper.
    """
    rng = np.random.default_rng(0)
    for _ in range(500):
        a = rng.uniform(-180, 180)
        c = rng.uniform(-360, 360)
        d = machine.tool_axis_in_part(a, c)
        r = machine.rotation_machine_from_part(a, c)
        assert np.allclose(r @ d, [0, 0, 1], atol=1e-12)


def test_ik_fk_round_trip_on_random_directions(machine):
    k = KinematicsSolver(machine)
    rng = np.random.default_rng(1)
    for _ in range(400):
        d = rng.normal(size=3)
        d /= np.linalg.norm(d)
        for sol in k.ik_branches(d):
            assert sol.residual_deg < 1e-6


def test_ik_always_returns_two_branches(machine):
    """Chaque direction admet deux couples (A, C). En oublier un ferait
    declarer inaccessibles des faces que la machine atteint."""
    k = KinematicsSolver(machine)
    br = k.ik_branches(np.array([0.3, 0.5, 0.8]))
    assert len(br) == 2
    assert {b.branch for b in br} == {0, 1}
    assert br[0].a_deg * br[1].a_deg <= 0.0


def test_asymmetric_a_travel_selects_mirror_branch(machine):
    """Le berceau va de -120 a +30 deg : une direction a A=+45 n'est
    atteignable que par la branche miroir A=-45."""
    k = KinematicsSolver(machine)
    d = machine.tool_axis_in_part(45.0, 30.0)
    best = k.ik_best(d)
    assert best is not None
    assert best.a_deg == pytest.approx(-45.0, abs=1e-6)
    assert machine.a.min_deg <= best.a_deg <= machine.a.max_deg


def test_singularity_severity_peaks_at_zero(machine):
    k = KinematicsSolver(machine)
    assert k.singularity_severity(0.0) == pytest.approx(1.0)
    assert k.singularity_severity(machine.singularity_a_deg + 1.0) == 0.0
    assert k.singularity_severity(1.0) > k.singularity_severity(2.0)


def test_conditioning_explodes_near_zero(machine):
    """dC/d(direction) = 1/|sin A| : a A=1 deg, 1 deg d'axe outil demande
    57 deg de plateau. C'est une contrainte dynamique, pas un confort."""
    k = KinematicsSolver(machine)
    assert k.conditioning(1.0) == pytest.approx(57.3, rel=0.01)
    assert k.conditioning(90.0) == pytest.approx(1.0, rel=1e-6)


def test_unwrap_sequence_removes_plateau_flip(machine):
    k = KinematicsSolver(machine)
    _, c = k.unwrap_sequence([0, 0, 0], [179.0, -179.0, -170.0])
    assert np.all(np.abs(np.diff(c)) < 30.0)


def test_pivot_offsets_affect_machine_coordinates(machine):
    """Ignorer les offsets de pivot donne une simulation juste et une piece
    fausse : c'est l'erreur classique du 5 axes table/table."""
    k = KinematicsSolver(machine)
    p = np.array([10.0, 5.0, 20.0])
    assert not np.allclose(k.part_to_machine_point(p, 45.0, 0.0),
                           k.part_to_machine_point(p, 0.0, 0.0))
    assert np.allclose(k.part_to_machine_point(p, 0.0, 0.0), p)
