"""Index spatial, voxelisation et suivi de matiere (jalon M2)."""

import numpy as np
import pytest

from xyzac.collision_engine import ObstacleClass, ObstacleField
from xyzac.collision_engine.spatial import UniformGrid
from xyzac.geometry_core import brep
from xyzac.geometry_core.voxelize import VoxelGrid, solid_mask
from xyzac.stock_engine import stock_from_part
from xyzac.stock_engine.material import MaterialState
from xyzac.tool_model import build_endmill


# ------------------------------------------------------------------ index

@pytest.mark.parametrize("radius", [3.0, 12.0, 40.0, 500.0])
def test_grid_query_matches_brute_force(radius):
    """L'index ne doit JAMAIS changer l'ensemble retourne, seulement le cout.

    Un index qui retournerait un point de trop, ou de moins, casserait la
    garantie conservative du moteur de collision, qui suppose un voisinage exact.
    """
    rng = np.random.default_rng(0)
    pts = rng.uniform(-50, 50, size=(4000, 3))
    g = UniformGrid(pts, 15.0)
    c = rng.uniform(-50, 50, 3)
    ref = np.flatnonzero(np.linalg.norm(pts - c, axis=1) <= radius)
    assert np.array_equal(ref, np.sort(g.query_ball(c, radius)))


def test_grid_capsule_matches_brute_force():
    rng = np.random.default_rng(1)
    pts = rng.uniform(-40, 40, size=(3000, 3))
    g = UniformGrid(pts, 10.0)
    p0, p1, r = rng.uniform(-30, 30, 3), rng.uniform(-30, 30, 3), 7.0
    v = p1 - p0
    t = np.clip(((pts - p0) @ v) / (v @ v), 0, 1)
    ref = np.flatnonzero(np.linalg.norm(pts - (p0 + t[:, None] * v), axis=1) <= r)
    assert np.array_equal(np.sort(ref), np.sort(g.query_capsule(p0, p1, r)))


def test_obstacle_field_subset_identical_with_and_without_index():
    """Le choix de strategie est une optimisation, pas un changement de semantique."""
    rng = np.random.default_rng(2)
    pts = rng.uniform(-200, 200, size=(8000, 3))
    f = ObstacleField.build(pts, part_spacing=1.0, safety_clearance=0.0)
    c, r = np.zeros(3), 20.0
    indexed = f.subset_near(c, r)                      # petit rayon -> index
    brute = np.flatnonzero(np.linalg.norm(pts - c, axis=1) <= r)
    assert len(indexed) == len(brute)
    assert np.allclose(np.sort(indexed.points, axis=0), np.sort(pts[brute], axis=0))


def test_empty_field_is_handled():
    f = ObstacleField(np.zeros((0, 3)), np.zeros(0), np.zeros(0))
    assert len(f.subset_near(np.zeros(3), 10.0)) == 0
    assert len(f.subset_capsule(np.zeros(3), np.ones(3), 10.0)) == 0


# ------------------------------------------------------- voxelisation

def test_voxel_volume_is_exact_on_a_box(corpus_dir):
    """Un pave aligne sur la grille doit donner le volume EXACT : toute derive
    ici signalerait une erreur de parite du lancer de rayons, pas une erreur
    de discretisation."""
    shape = brep.load_step(corpus_dir / "C01_bloc_simple.step")
    v, t, _ = brep.tessellate(shape, deflection=0.2)
    bb = brep.bounding_box(shape)
    g = VoxelGrid.covering(bb.lo, bb.hi, pitch=0.5, margin=1.0)
    vol = solid_mask(v, t, g).sum() * g.voxel_volume
    assert vol == pytest.approx(48000.0, rel=1e-6)


@pytest.mark.parametrize("case,expected", [
    ("C08_trou_incline", 103887.46),
    ("C11_cavite_spherique", 91244.84),
    ("C19_deux_solides", 25000.0),
])
def test_voxel_volume_converges_on_curved_solids(corpus_dir, case, expected):
    """Sur une geometrie courbe, l'ecart doit rester de l'ordre de la
    discretisation. On tolere 3 % a 0,8 mm de pas — au-dela ce ne serait plus
    de la discretisation mais une fuite du remplissage."""
    shape = brep.load_step(corpus_dir / f"{case}.step")
    v, t, _ = brep.tessellate(shape, deflection=0.2)
    bb = brep.bounding_box(shape)
    g = VoxelGrid.covering(bb.lo, bb.hi, pitch=0.8, margin=1.0)
    vol = solid_mask(v, t, g).sum() * g.voxel_volume
    assert vol == pytest.approx(expected, rel=0.03)


def test_voxelization_handles_two_disjoint_solids(corpus_dir):
    shape = brep.load_step(corpus_dir / "C19_deux_solides.step")
    v, t, _ = brep.tessellate(shape, deflection=0.2)
    bb = brep.bounding_box(shape)
    g = VoxelGrid.covering(bb.lo, bb.hi, pitch=0.5, margin=1.0)
    m = solid_mask(v, t, g)
    # Deux blocs separes : la tranche mediane en X doit etre vide.
    mid = m.shape[0] // 2
    assert not m[mid].any(), "le vide entre les deux solides a ete rempli"


# ------------------------------------------------------------- matiere

@pytest.fixture
def material(corpus_dir):
    shape = brep.load_step(corpus_dir / "C01_bloc_simple.step")
    v, t, _ = brep.tessellate(shape, deflection=0.2)
    stock = stock_from_part(brep.bounding_box(shape), margin_xy=3.0,
                            margin_z_top=3.0, margin_z_bottom=3.0)
    return MaterialState.from_setup(stock, v, t, pitch=1.0), stock


def test_initial_material_matches_stock_volume(material):
    ms, stock = material
    assert ms.remaining_volume_mm3 == pytest.approx(float(np.prod(stock.bbox.size)), rel=0.02)


def test_part_is_protected_and_never_removed(material):
    """La matiere protegee ne disparait pas, meme si l'outil la traverse dans le
    modele : ce serait une gouge, et masquer une gouge en l'enlevant du suivi
    serait le pire comportement possible."""
    ms, _ = material
    tool = build_endmill("EM6", 6.0, 20.0, stickout=45.0)
    before = ms.protected_volume_mm3
    # Le corps de l'outil s'etend depuis le bec VERS la broche (+axe). Pour que
    # l'outil traverse la piece (z de 0 a 20), le bec doit donc etre DANS la
    # piece, pas au-dessus : a z=25 l'outil s'en eloignerait.
    tcps = np.array([[30.0, 20.0, 12.0]])
    axes = np.array([[0.0, 0.0, 1.0]])
    ms.remove_tool_sweep(tcps, axes, tool)
    assert ms.protected_volume_mm3 == pytest.approx(before)
    assert ms.count_gouged_voxels(tcps, axes, tool) > 0


def test_sweep_removes_material(material):
    ms, _ = material
    tool = build_endmill("EM6", 6.0, 20.0, stickout=45.0)
    before = ms.remaining_volume_mm3
    tcps = np.stack([np.linspace(-2, 62, 40), np.full(40, -2.0), np.full(40, 21.0)], axis=1)
    axes = np.tile([0.0, 0.0, 1.0], (40, 1))
    n = ms.remove_tool_sweep(tcps, axes, tool)
    assert n > 0
    assert ms.remaining_volume_mm3 < before


def test_carve_to_finished_leaves_only_the_protected_part(material):
    ms, _ = material
    ms.carve_to_finished()
    assert ms.remaining_volume_mm3 == pytest.approx(ms.protected_volume_mm3)


def test_boundary_points_are_conservative(material):
    """Le rayon d'inflation doit couvrir le demi-diagonal du voxel, sans quoi
    des morceaux de matiere echapperaient a l'enveloppe des obstacles."""
    ms, _ = material
    pts, inf = ms.boundary_points()
    assert len(pts) > 0
    assert inf == pytest.approx(0.5 * ms.grid.pitch * np.sqrt(3.0))


def test_material_state_feeds_the_obstacle_field(material):
    ms, _ = material
    pts, inf = ms.boundary_points()
    f = ObstacleField.build(np.zeros((1, 3)), part_spacing=0.1,
                            stock_points=pts, stock_spacing=inf, safety_clearance=0.0)
    stock_rows = f.classes == int(ObstacleClass.STOCK)
    assert stock_rows.sum() == len(pts)
    assert f.inflation[stock_rows].min() >= inf
