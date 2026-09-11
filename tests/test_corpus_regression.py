"""Non-regression sur les 20 geometries STEP synthetiques.

Le corpus a une verite terrain calculable (volumes, faces, axes). Ces tests
affirment donc autre chose que « ca n'a pas plante ».
"""

import numpy as np
import pytest

from xyzac.feature_engine import detect_revolution_regions
from xyzac.geometry_core import brep
from xyzac.turning_engine import evaluate_turning


def _case(manifest, cid):
    return next(c for c in manifest if c["id"] == cid)


@pytest.mark.parametrize("cid", [f"C{i:02d}" for i in range(1, 21)])
def test_every_case_imports_with_stable_topology(corpus_dir, manifest, cid):
    """Import STEP + topologie identiques a la generation. Detecte toute derive
    d'OCCT, de tolerance ou d'unites."""
    c = _case(manifest, cid)
    shape = brep.load_step(corpus_dir / c["file"])
    assert not shape.IsNull()
    assert brep.volume(shape) == pytest.approx(c["volume_mm3"], rel=1e-6)
    assert len(brep.face_info(shape)) == c["n_faces"]
    assert brep.count_solids(shape) == c["n_solids"]


@pytest.mark.parametrize("cid", [f"C{i:02d}" for i in range(1, 21)])
def test_every_case_tessellates_and_samples(corpus_dir, manifest, cid):
    c = _case(manifest, cid)
    shape = brep.load_step(corpus_dir / c["file"])
    s = brep.sample_surface(shape, spacing=3.0)
    assert len(s) > 0
    assert np.all(np.isfinite(s.points))
    assert np.allclose(np.linalg.norm(s.normals, axis=1), 1.0, atol=1e-6)


def test_units_are_millimetres(corpus_dir, manifest):
    """Un STEP interprete en pouces donnerait des trajectoires fausses d'un
    facteur 25,4 — sans aucun message d'erreur."""
    c = _case(manifest, "C01")
    bb = brep.bounding_box(brep.load_step(corpus_dir / c["file"]))
    assert np.allclose(bb.size, [60, 40, 20], atol=1e-3)


def test_micro_detail_survives_tessellation(corpus_dir):
    """C20 : un percage D1,2 dans une piece de 60 mm. Si la tessellation le
    perd, le solveur usinera dans un trou qu'il ne voit pas."""
    shape = brep.load_step(corpus_dir / "C20_micro_detail.step")
    cyls = [f for f in brep.face_info(shape) if f.surface_type == "cylinder"]
    assert len(cyls) == 1
    assert cyls[0].radius == pytest.approx(0.6, abs=1e-6)
    s = brep.sample_surface(shape, spacing=0.5)
    assert np.any(s.face_ids == cyls[0].index), "le micro-percage n'est plus echantillonne"


def test_compound_with_two_solids_is_handled(corpus_dir):
    """C19 : l'import ne doit pas supposer un solide unique."""
    shape = brep.load_step(corpus_dir / "C19_deux_solides.step")
    assert brep.count_solids(shape) == 2
    assert brep.volume(shape) == pytest.approx(25000.0, rel=1e-6)


@pytest.mark.parametrize("cid,expect_aligned", [
    ("C12_arbre_etage", True),
    ("C13_arbre_gorge_torique", True),
    ("C14_hybride_meplats", True),
    ("C15_revolution_hors_axe", False),
    ("C01_bloc_simple", False),
])
def test_revolution_detection_rejects_off_axis(corpus_dir, machine, cid, expect_aligned):
    """C15 est le cas piege : un cylindre lateral EST de revolution, mais autour
    du mauvais axe. Le proposer au tournage ferait tournoyer la piece a
    1500 tr/min pour usiner un percage."""
    shape = brep.load_step(corpus_dir / f"{cid}.step")
    verdict = evaluate_turning(shape, machine)
    assert verdict.suitable is expect_aligned, verdict.reason


def test_torus_axis_is_extracted(corpus_dir):
    """C13 : sans l'axe du tore, la gorge sortirait de la region de revolution."""
    shape = brep.load_step(corpus_dir / "C13_arbre_gorge_torique.step")
    tori = [f for f in brep.face_info(shape) if f.surface_type == "torus"]
    assert tori and tori[0].axis_direction is not None
    regions = detect_revolution_regions(shape)
    assert tori[0].index in regions[0].face_indices
