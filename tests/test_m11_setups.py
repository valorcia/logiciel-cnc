"""Ordonnancement de plusieurs MONTAGES (jalon M11).

Ce que ces tests protegent, avant tout : la separation des questions. Un
booleen « atteignable » en confond deux, et le plan renvoyait alors a « revoir
l'outil ou le bridage » — un fourre-tout qui ne designe rien. Or la mesure dit,
elle, que la passe 1 du dome est ouverte a un point pres par un simple
retournement.
"""

import numpy as np
import pytest

from xyzac.accessibility_solver.solver import (AccessibilityConfig,
                                               AccessibilitySolver)
from xyzac.collision_engine import ObstacleField
from xyzac.collision_engine.field import ObstacleClass
from xyzac.machine_model import default_xyzac_kit
from xyzac.strategy_planner.setups import (CANONICAL_MOUNTS, PROBE_TOOL_SCALE,
                                           PartOrientation, SetupPlan,
                                           _rotated_bbox, derive_mount,
                                           ideal_machine, plan_setups,
                                           screen_orientation)
from xyzac.tool_model import build_ballnose


# ------------------------------------------------ les six montages

def test_the_six_mounts_are_proper_rotations():
    for o in CANONICAL_MOUNTS:
        assert np.allclose(o.rotation @ o.rotation.T, np.eye(3), atol=1e-12), o.name
        assert np.isclose(np.linalg.det(o.rotation), 1.0), o.name


def test_no_mount_is_a_rotation_about_z_because_the_c_axis_does_that():
    """LE point qui reduit l'espace de recherche de 24 a 6, et ce n'est pas une
    heuristique : c'est la cinematique de la machine.

    Le cube a 24 rotations. Mais l'axe C est continu, donc deux montages qui ne
    different que par une rotation autour du Z du montage sont LE MEME montage
    — la machine fait la difference toute seule. Y faire figurer une rotation
    en Z ferait croire a un cout de remontage qui n'existe pas.
    """
    z = np.array([0.0, 0.0, 1.0])
    images = [o.rotation @ z for o in CANONICAL_MOUNTS]
    # les six montages envoient +Z de la piece sur six directions distinctes
    for i, a in enumerate(images):
        for j, b in enumerate(images):
            if i != j:
                assert not np.allclose(a, b, atol=1e-9), (
                    f"{CANONICAL_MOUNTS[i].name} et {CANONICAL_MOUNTS[j].name} "
                    "posent la meme face : ils ne differeraient que par C")
    assert len(CANONICAL_MOUNTS) == 6


def test_the_rotated_box_uses_all_eight_corners():
    """Tourner seulement ``lo`` et ``hi`` donne une boite fausse des que la
    rotation n'est pas alignee sur les axes, et le montage derive s'en
    trouverait decale."""
    lo, hi = np.array([0.0, 0.0, 0.0]), np.array([10.0, 2.0, 1.0])
    a = np.radians(30.0)
    R = np.array([[np.cos(a), -np.sin(a), 0.0],
                  [np.sin(a), np.cos(a), 0.0], [0.0, 0.0, 1.0]])
    blo, bhi = _rotated_bbox(lo, hi, R)
    naif_lo = np.minimum(R @ lo, R @ hi)
    naif_hi = np.maximum(R @ lo, R @ hi)
    assert not np.allclose(blo, naif_lo) or not np.allclose(bhi, naif_hi)
    # la vraie boite contient les huit sommets tournes
    coins = np.array([[x, y, z] for x in (lo[0], hi[0])
                      for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]) @ R.T
    assert (coins >= blo - 1e-9).all() and (coins <= bhi + 1e-9).all()


def test_the_mount_centres_the_part_and_raises_it():
    dx, dy, dz = derive_mount([0.0, 0.0, -12.0], [60.0, 60.0, 32.0], riser_mm=25.0)
    assert (dx, dy) == (-30.0, -30.0)
    assert dz == pytest.approx(37.0)          # 25 mm sous le DESSOUS de la piece


def test_the_orientation_rotates_points_and_keeps_normals_unit():
    o = CANONICAL_MOUNTS[2]
    p = np.array([[1.0, 2.0, 3.0], [-4.0, 0.5, 2.0]])
    n = np.array([[0.0, 0.0, 1.0], [0.6, 0.8, 0.0]])
    tp, tn = o.points(p), o.directions(n)
    assert np.allclose(np.linalg.norm(tn, axis=1), 1.0)
    # une rotation conserve les angles : le produit scalaire point-normale aussi
    assert np.allclose(np.sum(p * n, axis=1), np.sum(tp * tn, axis=1))


def test_the_field_rotates_but_keeps_classes_and_inflation():
    f = ObstacleField(np.array([[1.0, 0.0, 0.0], [0.0, 2.0, 0.0]]),
                      np.array([int(ObstacleClass.PART), int(ObstacleClass.STOCK)],
                               np.int8),
                      np.array([0.5, 0.7]))
    g = CANONICAL_MOUNTS[1].field(f)
    assert np.array_equal(g.classes, f.classes)
    assert np.allclose(g.inflation, f.inflation)
    assert np.allclose(np.linalg.norm(g.points, axis=1),
                       np.linalg.norm(f.points, axis=1))


# ------------------------------------------------ la machine ideale

def test_the_ideal_machine_removes_limits_and_organs_without_mutating():
    m = default_xyzac_kit()
    avant = (m.a.min_deg, m.a.max_deg, len(m.collision_volumes))
    i = ideal_machine(m)
    assert i.a.min_deg <= -360.0 and i.a.max_deg >= 360.0
    assert i.collision_volumes == []
    assert (m.a.min_deg, m.a.max_deg, len(m.collision_volumes)) == avant, (
        "la machine reelle a ete modifiee : le depistage se comparerait a "
        "lui-meme")


# ------------------------------------------------ la scene de test

@pytest.fixture(scope="module")
def scene():
    tool = build_ballnose("BN6", 6.0, 20.0, stickout=45.0, holder_type="ER16")
    sonde = build_ballnose("sonde", 6.0 * PROBE_TOOL_SCALE, 20.0,
                           stickout=45.0, holder_type="ER16")
    g = np.mgrid[-30:31:3.0, -30:31:3.0].reshape(2, -1).T
    pts = np.column_stack([g, np.zeros(len(g))])
    f = ObstacleField(pts, np.full(len(pts), int(ObstacleClass.PART), np.int8),
                      np.full(len(pts), 0.3))
    cfg = AccessibilityConfig(subdivisions=3, max_lead_deg=45.0, cutting_depth=0.0)

    def make_solver(field, mount, machine, t):
        return AccessibilitySolver(t, machine, field, cfg, mount_offset_mm=mount)

    return tool, sonde, f, make_solver


def _pass(normal, n=6, r=8.0):
    t = np.linspace(0.0, 2.0 * np.pi, n)
    pts = np.column_stack([r * np.cos(t), r * np.sin(t), np.zeros(n)])
    return pts, np.tile(normal, (n, 1)).astype(float)


def test_a_downward_face_is_mount_limited_and_the_flip_opens_it(scene):
    """Le cas physique meme : une face qui regarde le plateau ne peut pas etre
    presentee a l'outil, et le retournement la presente. Le depistage doit
    ranger cela dans le MONTAGE, jamais dans l'outil."""
    tool, sonde, f, mk = scene
    m = default_xyzac_kit()
    passes = [_pass([0.0, 0.0, -1.0])]
    tel_quel = screen_orientation(CANONICAL_MOUNTS[0], passes, f, mk, m, tool,
                                  probe_tool=sonde, bbox_lo=[-10, -10, -1],
                                  bbox_hi=[10, 10, 1], n_probe=6)
    retourne = screen_orientation(CANONICAL_MOUNTS[1], passes, f, mk, m, tool,
                                  probe_tool=sonde, bbox_lo=[-10, -10, -1],
                                  bbox_hi=[10, 10, 1], n_probe=6)
    sc = tel_quel.screens[0]
    assert not sc.reachable
    assert sc.mount_limited > 0, sc.detail
    assert sc.n_tool_limited == 0, (
        "une face qui regarde le plateau n'est pas un probleme d'outil : "
        f"{sc.detail}")
    assert retourne.screens[0].reachable, retourne.screens[0].detail


def test_the_probe_tool_declares_itself_inconclusive_when_too_fine(scene):
    """Regression de la faute commise ici, et c'est la TROISIEME fois dans ce
    projet qu'une grandeur dominee par une autre est lue comme si elle mesurait
    ce qu'on voulait (marge du certificat de gouge en M6, marge tous tronçons
    en M10).

    La premiere version testait les points durs avec un bec de 0,1 mm pour
    conclure « aucun rayon ne leve ce point, donc c'est la geometrie ». Or le
    champ est gonfle d'au moins 1,26 mm au pas courant : l'outil etait bloque
    par le gonflement seul, et son echec ne prouvait rien. Au pas de 0,5 mm le
    meme point devenait atteignable.

    Un bec de sondage qui ne depasse pas le gonflement doit donc se DECLARER
    non concluant, au lieu de produire une categorie plausible.
    """
    tool, _, f, mk = scene
    m = default_xyzac_kit()
    minuscule = build_ballnose("minuscule", 0.2, 2.0, stickout=45.0,
                               holder_type="ER16")
    cov = screen_orientation(CANONICAL_MOUNTS[0], [_pass([0.0, 0.0, -1.0])],
                             f, mk, m, tool, probe_tool=minuscule,
                             bbox_lo=[-10, -10, -1], bbox_hi=[10, 10, 1],
                             n_probe=4)
    sc = cov.screens[0]
    assert sc.probe_nose_mm == pytest.approx(0.1)
    assert sc.field_inflation_mm >= 0.3
    assert not sc.probe_conclusive, (
        "un bec de 0,1 mm contre un champ gonfle de 0,3 mm ne discrimine rien")


def test_a_probe_tool_larger_than_the_inflation_is_conclusive(scene):
    tool, sonde, f, mk = scene
    cov = screen_orientation(CANONICAL_MOUNTS[0], [_pass([0.0, 0.0, -1.0])],
                             f, mk, default_xyzac_kit(), tool, probe_tool=sonde,
                             bbox_lo=[-10, -10, -1], bbox_hi=[10, 10, 1],
                             n_probe=4)
    assert cov.screens[0].probe_conclusive


# ------------------------------------------------ le plan

def test_the_plan_prefers_no_remount_on_a_tie(scene):
    """A egalite de passes couvertes, « tel quel » d'abord : un remontage evite
    vaut mieux qu'un remontage arbitrairement equivalent."""
    tool, sonde, f, mk = scene
    passes = [_pass([0.0, 0.0, 1.0])]
    pl = plan_setups(passes, f, mk, default_xyzac_kit(), tool, probe_tool=sonde,
                     bbox_lo=[-10, -10, -1], bbox_hi=[10, 10, 1], n_probe=4)
    assert pl.n_setups == 1
    assert pl.setups[0].orientation.name == "tel quel"
    assert not pl.uncovered


def test_two_opposite_faces_can_share_one_setup(scene):
    """Resultat contre-intuitif, et c'est l'interet de l'ordonnanceur.

    On attendrait deux montages pour deux faces opposees : l'une en haut,
    l'autre en bas. La machine en trouve UN — couchee sur le cote, les deux
    faces deviennent laterales et l'inclinaison A les presente toutes deux.

    Ce test a d'abord ete ecrit avec l'attente naive (deux montages) et c'est
    elle qui etait fausse. Un remontage evite est du temps, un palpage et une
    composition d'incertitudes en moins : le chercher a un sens.
    """
    tool, sonde, f, mk = scene
    passes = [_pass([0.0, 0.0, 1.0]), _pass([0.0, 0.0, -1.0])]
    pl = plan_setups(passes, f, mk, default_xyzac_kit(), tool, probe_tool=sonde,
                     bbox_lo=[-10, -10, -1], bbox_hi=[10, 10, 1], n_probe=4)
    assert pl.n_setups == 1, pl.describe()
    assert not pl.uncovered
    assert pl.setups[0].reachable == {0, 1}
    # et le montage retenu n'est justement PAS « tel quel » : la preference
    # pour le non-remontage ne doit pas ecraser une couverture meilleure
    assert pl.setups[0].orientation.name != "tel quel"
    assert "Un seul montage" in pl.tolerance_warning()


def test_more_than_one_setup_refuses_to_quote_a_tolerance():
    """Chaque remontage rereference la piece : les budgets SE COMPOSENT. Le
    moteur ne sait pas encore chiffrer cette composition, donc il refuse
    d'annoncer un chiffre et dit pourquoi — plutot que de laisser croire
    qu'une tolerance etablie dans un montage vaut d'un montage a l'autre."""
    un = SetupPlan(setups=[None], n_passes=1).tolerance_warning()
    deux = SetupPlan(setups=[None, None], n_passes=2).tolerance_warning()
    assert "aucun transfert" in un
    assert "SE COMPOSENT" in deux
    assert "aucune tolerance" in deux.lower()
    assert not any(c.isdigit() and c not in "12" for c in deux.replace("2 montages", ""))


def test_the_plan_says_that_screening_is_optimistic(scene):
    tool, sonde, f, mk = scene
    pl = plan_setups([_pass([0.0, 0.0, 1.0])], f, mk, default_xyzac_kit(), tool,
                     probe_tool=sonde, bbox_lo=[-10, -10, -1],
                     bbox_hi=[10, 10, 1], n_probe=4)
    t = pl.describe()
    assert "OPTIMISTE" in t
    assert "sans bridage" in t
    assert "decide_indexed_pass" in t


def test_the_screens_are_kept_so_the_plan_can_be_argued(scene):
    tool, sonde, f, mk = scene
    pl = plan_setups([_pass([0.0, 0.0, -1.0])], f, mk, default_xyzac_kit(), tool,
                     probe_tool=sonde, bbox_lo=[-10, -10, -1],
                     bbox_hi=[10, 10, 1], n_probe=4)
    assert len(pl.all_screens) == 6, "un plan qui ne dit pas ce qu'il a essaye"
    assert all(len(c.screens) == 1 for c in pl.all_screens)
