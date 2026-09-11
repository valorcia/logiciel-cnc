"""Invariants du noyau geometrique et de l'import STEP."""

import numpy as np
import pytest

from xyzac.geometry_core import brep
from xyzac.geometry_core.sphere import icosphere, local_refine
from xyzac.geometry_core.types import Transform, angle_between, normalize, unwrap_towards, vec3


def test_transform_inverse_is_identity():
    t = Transform.rot_z(0.7) @ Transform.rot_x(-0.3) @ Transform.translation([1, 2, 3])
    back = t.inverse() @ t
    assert np.allclose(back.R, np.eye(3), atol=1e-12)
    assert np.allclose(back.t, 0.0, atol=1e-12)


def test_unwrap_keeps_continuity_across_pi():
    """Sans deroulage, une trajectoire traversant +/-180 deg retourne le plateau."""
    c = np.degrees(unwrap_towards(np.radians(-179.0), np.radians(179.0)))
    assert abs(c - 181.0) < 1e-9


def test_angle_between_is_stable_at_extremes():
    z = vec3(0, 0, 1)
    assert angle_between(z, z) == pytest.approx(0.0, abs=1e-12)
    assert angle_between(z, -z) == pytest.approx(np.pi, abs=1e-9)
    # acos(dot) perdrait la precision ici ; atan2(|cross|, dot) la conserve.
    near = normalize(vec3(1e-9, 0, 1))
    assert angle_between(z, near) == pytest.approx(1e-9, rel=1e-3)


@pytest.mark.parametrize("sub,n", [(0, 12), (1, 42), (2, 162), (3, 642)])
def test_icosphere_counts_and_unit_norm(sub, n):
    g = icosphere(sub)
    assert len(g) == n
    assert np.allclose(np.linalg.norm(g.directions, axis=1), 1.0)


def test_connected_components_separates_disjoint_caps():
    g = icosphere(3)
    mask = (g.directions[:, 2] > 0.8) | (g.directions[:, 2] < -0.8)
    assert len(g.connected_components(mask)) == 2
    assert len(g.connected_components(g.directions[:, 2] > 0.0)) == 1


def test_local_refine_stays_in_cone():
    d = normalize(vec3(0.3, -0.5, 1.0))
    r = local_refine(d, 12.0, 4, 10)
    ang = np.degrees(np.arccos(np.clip(r @ d, -1, 1)))
    assert ang.max() <= 12.0 + 1e-9


def test_sample_surface_respects_spacing_bound(corpus_dir):
    """Garantie conservative : aucun point de surface plus loin que max_spacing.

    C'est l'hypothese dont depend TOUT le collision engine. Si elle tombe, le
    test discret n'est plus un majorant et le solveur peut valider une collision.
    """
    shape = brep.load_step(corpus_dir / "C01_bloc_simple.step")
    s = brep.sample_surface(shape, spacing=3.0)
    v, t, _ = brep.tessellate(shape, deflection=0.5)
    from scipy.spatial import cKDTree
    tree = cKDTree(s.points)
    centroids = v[t].mean(axis=1)
    d, _ = tree.query(centroids)
    assert d.max() <= s.max_spacing, (
        f"point de surface a {d.max():.3f} mm du plus proche echantillon, "
        f"max_spacing annonce {s.max_spacing:.3f} mm")


def test_sampled_normals_point_outward(corpus_dir):
    """Une normale rentrante inverserait le sens d'approche de l'outil."""
    shape = brep.load_step(corpus_dir / "C01_bloc_simple.step")
    s = brep.sample_surface(shape, spacing=4.0)
    center = brep.bounding_box(shape).center
    outward = s.points - center
    outward /= np.linalg.norm(outward, axis=1, keepdims=True)
    assert float(np.sum(s.normals * outward, axis=1).mean()) > 0.5
