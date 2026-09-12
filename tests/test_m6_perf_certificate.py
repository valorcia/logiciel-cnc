"""Coût du solveur, preuve de gouge, et corps de l'outil de tour (jalon M6).

Trois sujets, une meme exigence : une optimisation ne doit pas changer le
resultat, et une verification doit dire ce qu'elle couvre.
"""

import time

import numpy as np
import pytest

from xyzac.accessibility_solver.solver import AccessibilityConfig, AccessibilitySolver
from xyzac.collision_engine.exact_gouge import (
    NON_CUTTING_ROLES,
    certify_plan_exact,
    verify_gouge_exact,
    verify_plan_sparse,
)
from xyzac.collision_engine.machine_guard import MachineGuard
from xyzac.geometry_core import brep
from xyzac.machine_model import Setup, default_xyzac_kit
from xyzac.simulation_engine.scene import build_scene
from xyzac.stock_engine import stock_from_part
from xyzac.tool_model import build_ballnose, build_endmill
from xyzac.turning_engine import TurningTool, TurningToolBody, revolution_profile
from xyzac.turning_engine.profile import RevolutionProfile, plan_turning_passes


# ----------------------------------------------------- scenes partagees

def _scene(corpus_dir, case, ball=False):
    path = next(corpus_dir.glob(f"{case}*.step"))
    shape = brep.load_step(path)
    bb = brep.bounding_box(shape)
    tool = (build_ballnose("BN6", 6.0, 20.0, stickout=45.0, holder_type="ER16")
            if ball else
            build_endmill("EM6", 6.0, 20.0, stickout=45.0, holder_type="ER16"))
    stock = stock_from_part(bb, margin_xy=2.0, margin_z_top=2.0, margin_z_bottom=2.0)
    setup = Setup(setup_id="m6", machine=default_xyzac_kit(),
                  part_step_path=str(path), stock=stock, tools=[tool],
                  part_to_table_mm=[float(-bb.center[0]), float(-bb.center[1]), 25.0])
    scene = build_scene(setup, material_state="finished")
    return shape, tool, setup, scene


# ------------------------------------- l'ordre des tests exacts (D39/M6)

@pytest.mark.parametrize("case,ball", [
    ("C10_dome", True), ("C04_rainure", False), ("C02_poche", False),
])
def test_stage_order_does_not_change_the_feasible_set(corpus_dir, case, ball):
    """L'inversion garde machine / test piece est une optimisation, pas un
    assouplissement.

    La faisabilite est le ET de deux masques independants, donc elle ne peut pas
    dependre de l'ordre. Ce test le verifie au lieu de le supposer : c'est la
    seule chose qui autorise l'inversion, qui vaut un facteur 2,5 sur le temps
    total.
    """
    shape, tool, setup, scene = _scene(corpus_dir, case, ball)
    samp = brep.sample_surface(shape, spacing=2.5)
    pts, nrm = samp.points[:30], samp.normals[:30]

    out = {}
    for gf in (True, False):
        cfg = AccessibilityConfig(subdivisions=2, max_lead_deg=45.0,
                                  cutting_depth=0.0, guard_first=gf)
        sol = AccessibilitySolver(tool, setup.machine, scene.obstacles, cfg,
                                  mount_offset_mm=setup.mount_offset)
        out[gf] = sol.solve_points(pts, nrm)

    n_div = 0
    for ma, mb in zip(out[True], out[False]):
        assert np.array_equal(ma.grid_index, mb.grid_index)
        n_div += int((ma.feasible != mb.feasible).sum())
    assert n_div == 0, f"{n_div} orientations changent d'avis selon l'ordre"


def test_guard_first_shrinks_the_expensive_stage(corpus_dir):
    """Mesure de l'effet, sur un compteur et non sur un chronometre.

    Le test piece est le stage cher ; la garde machine rejette l'essentiel des
    candidats sur une calotte. L'ordre inverse doit donc faire porter le test
    cher sur une petite fraction des candidats.
    """
    shape, tool, setup, scene = _scene(corpus_dir, "C10_dome", ball=True)
    samp = brep.sample_surface(shape, spacing=2.5)
    pts, nrm = samp.points[:8], samp.normals[:8]

    counts = {}
    for gf in (True, False):
        cfg = AccessibilityConfig(subdivisions=2, max_lead_deg=45.0,
                                  cutting_depth=0.0, guard_first=gf)
        sol = AccessibilitySolver(tool, setup.machine, scene.obstacles, cfg,
                                  mount_offset_mm=setup.mount_offset)
        maps = sol.solve_points(pts, nrm)
        counts[gf] = sum(m.stage_counts.get("E4_tests_exacts", 0) for m in maps)

    assert counts[True] < counts[False] / 2.0, (
        f"garde d'abord : {counts[True]} tests piece ; test piece d'abord : "
        f"{counts[False]}")


def test_travel_mask_agrees_with_the_scalar_check(corpus_dir):
    """Le masque de courses rendu par ``check_many`` doit etre exactement celui
    que ``check_pose`` deduit — c'est lui qui porte desormais la distinction
    « hors course » / « collision organe »."""
    shape, tool, setup, scene = _scene(corpus_dir, "C02_poche")
    guard = MachineGuard(setup.machine, tool)
    rng = np.random.default_rng(7)
    tcps = rng.uniform(-40.0, 120.0, size=(24, 3))
    ac = np.stack([rng.uniform(-130.0, 40.0, 24), rng.uniform(-180.0, 180.0, 24)], axis=1)

    ok_v, within_v = guard.check_many(tcps, ac, return_travel=True)
    for i in range(len(tcps)):
        chk = guard.check_pose(tcps[i], float(ac[i, 0]), float(ac[i, 1]))
        assert bool(within_v[i]) == bool(chk.axis_limits_ok), f"pose {i}"
        assert bool(ok_v[i]) == bool(chk.ok), f"pose {i}"


# ------------------------------------------- du sondage a la preuve

@pytest.fixture(scope="module")
def block_and_tool(corpus_dir):
    shape = brep.load_step(corpus_dir / "C01_bloc_simple.step")
    tool = build_endmill("EM6", 6.0, 20.0, stickout=45.0, holder_type="ER16")
    return shape, tool, brep.bounding_box(shape)


def _surface_pass(bb, n=120, dz=0.0):
    z = float(bb.hi[2]) + dz
    xs = np.linspace(float(bb.lo[0]) + 3.0, float(bb.hi[0]) - 3.0, n)
    tcps = np.stack([xs, np.full_like(xs, float(bb.center[1])),
                     np.full_like(xs, z)], axis=1)
    return tcps, np.tile([0.0, 0.0, 1.0], (n, 1))


def test_certificate_proves_a_clear_pass_with_few_queries(block_and_tool):
    """La majoration doit rendre le nombre de requetes independant du nombre de
    poses : la garde disponible decide, pas la densite d'echantillonnage."""
    shape, tool, bb = block_and_tool
    tcps, axes = _surface_pass(bb, n=120)
    cert = certify_plan_exact(shape, tool, tcps, axes)

    assert cert.holder_proven and cert.cutting_tested and cert.complete
    # Garde de 20 mm sous un pas de 0,5 mm : quelques requetes suffisent.
    assert cert.n_queries_holder <= 10, cert.describe()
    assert cert.min_clearance_mm > 10.0


def test_certificate_catches_the_gouge_the_sparse_probe_misses(block_and_tool):
    """LE test qui justifie ce module.

    Une pose sur 120 enfoncee de 4 mm dans le bloc : le sondage a douze poses ne
    la voit pas, et son silence passe pour un verdict. Le certificat la voit.
    """
    shape, tool, bb = block_and_tool
    tcps, axes = _surface_pass(bb, n=120)
    tcps[57, 2] -= 4.0

    sparse = verify_plan_sparse(shape, tool, tcps, axes, n_samples=12)
    assert all(r.ok for r in sparse), "le sondage doit MANQUER cette gouge"

    cert = certify_plan_exact(shape, tool, tcps, axes)
    assert not cert.complete
    assert cert.failures and any(f.index == 57 for f in cert.failures)
    assert cert.failures[0].gouge_volume_mm3 > 1.0


def test_certificate_does_not_cry_wolf_on_a_near_miss(block_and_tool):
    """Une pose a 0,05 mm de la face ne touche pas. Un verificateur qui la
    signale est inutilisable en finition, ou l'outil frole par construction."""
    shape, tool, bb = block_and_tool
    tcps, axes = _surface_pass(bb, n=120)
    tcps[57, 2] += 0.05
    cert = certify_plan_exact(shape, tool, tcps, axes)
    assert cert.complete, cert.describe()


def test_certificate_reports_its_budget_instead_of_concluding(block_and_tool):
    """Budget epuise = certificat INCOMPLET, jamais optimiste."""
    shape, tool, bb = block_and_tool
    tcps, axes = _surface_pass(bb, n=120)
    cert = certify_plan_exact(shape, tool, tcps, axes, max_queries=1,
                              check_cutting=False)
    assert not cert.holder_proven
    assert cert.uncertified
    assert "NON PROUVE" in cert.describe()


def test_certificate_separates_the_two_physics(block_and_tool):
    """L'arete tangente ne doit pas rendre la garde du porte-outil nulle.

    Premiere version de ce module : la garde etait le minimum sur TOUS les
    troncons, arete comprise. Comme l'arete est tangente a la surface par
    construction, la garde valait 0 partout et aucun intervalle n'etait jamais
    certifie — un certificat vide qui avait l'air de fonctionner.
    """
    shape, tool, bb = block_and_tool
    tcps, axes = _surface_pass(bb, n=8)
    whole = verify_gouge_exact(shape, tool, tcps[0], axes[0])
    holder = verify_gouge_exact(shape, tool, tcps[0], axes[0], roles=NON_CUTTING_ROLES)
    # Tangente a 1 um pres : c'est la tolerance du corpus lui-meme, dont la
    # boite englobante vaut [-1e-6, 20.000001].
    assert whole.min_distance_mm < 1e-4
    assert holder.min_distance_mm > 10.0


# ------------------------------------------ corps de l'outil de tour

@pytest.fixture
def groove_profile():
    """Gorge de 3 mm de large et 10 mm de profond sur un arbre R20."""
    z = np.linspace(0.0, 60.0, 241)
    r = np.full_like(z, 20.0)
    r[(z > 28.0) & (z < 31.0)] = 10.0
    return RevolutionProfile(axis_point=np.zeros(3), axis_dir=np.array([0.0, 0.0, 1.0]),
                             z=z, r=r, ovality=np.zeros_like(r))


def test_body_not_given_is_reported_as_not_checked(groove_profile):
    """Le piege a eviter : une liste d'interferences vide qui passe pour un
    degagement alors qu'aucune silhouette n'a ete fournie."""
    rep = plan_turning_passes(groove_profile, TurningTool("T"), stock_radius=22.0)
    assert not rep.body_checked
    assert rep.body_interferences == []
    assert "NON verifie" in rep.describe()


def test_body_interference_depends_on_the_dimensions_that_decide_it(corpus_dir):
    """Le signe qui a revele le premier defaut de ce test.

    La penetration rapportee ne dependait d'AUCUN parametre du corps — parce que
    la silhouette incluait le flanc de la plaquette, dont le contact contre la
    pente locale est deja mesure par ``too_steep_zones``. Deux tests de la meme
    limite physique rendaient tout infaisable, y compris une lame de 2 mm dans
    une gorge de 3 mm.

    Le test verifie donc les deux cotes qui decident reellement, et elles ne
    sont pas celles qu'on croit : c'est l'ARETE INTERIEURE du corps qui touche,
    donc le debord axial et la hauteur de plaquette. La hauteur du corps, elle,
    ne change rien — ce qui est au-dessus de l'arete interieure est plus loin
    encore de la piece.
    """
    shape = brep.load_step(corpus_dir / "C12_arbre_etage.step")
    prof = revolution_profile(shape, np.zeros(3), np.array([0.0, 0.0, 1.0]),
                              n_z=120, n_theta=36, sample_spacing=0.6)
    tool = TurningTool("TNMG", clearance_angle_deg=7.0)

    def worst(**kw):
        rep = plan_turning_passes(prof, tool, stock_radius=prof.max_radius + 2.0,
                                  body=TurningToolBody.external(**kw))
        return max((b.penetration_mm for b in rep.body_interferences), default=0.0)

    # Un corps qui traine loin en arriere rencontre les gros diametres.
    assert worst(width_back_mm=25.0) > worst(width_back_mm=4.0)
    # Une plaquette qui souleve davantage le corps le degage.
    assert worst(nose_offset_mm=6.0) > worst(nose_offset_mm=18.0)
    # La hauteur du corps ne decide rien : l'arete interieure est la meme.
    assert worst(height_mm=6.0) == pytest.approx(worst(height_mm=40.0))


def test_body_check_majorises_with_coarser_sampling(groove_profile):
    """Le pas d'echantillonnage de la silhouette est AJOUTE a la penetration.

    Un pas plus grossier doit donc rapporter au moins autant : c'est le sens
    d'erreur qui laisse passer un talonnage s'il est inverse.
    """
    from xyzac.turning_engine import check_body_clearance
    body = TurningToolBody.external(height_mm=20.0)
    fine = check_body_clearance(groove_profile, body, groove_profile.z,
                                groove_profile.r, spacing=0.2)
    coarse = check_body_clearance(groove_profile, body, groove_profile.z,
                                  groove_profile.r, spacing=2.0)
    assert max(b.penetration_mm for b in coarse) >= max(b.penetration_mm for b in fine)


def test_a_smooth_shaft_clears_a_normal_body(corpus_dir):
    """L'arbre a gorge torique C13 n'a pas d'epaulement traitre : un corps
    ordinaire doit y passer, sinon la verification est inutilisable."""
    shape = brep.load_step(corpus_dir / "C13_arbre_gorge_torique.step")
    prof = revolution_profile(shape, np.zeros(3), np.array([0.0, 0.0, 1.0]),
                              n_z=120, n_theta=36, sample_spacing=0.6)
    rep = plan_turning_passes(prof, TurningTool("TNMG", clearance_angle_deg=7.0),
                              stock_radius=prof.max_radius + 2.0,
                              body=TurningToolBody.external(height_mm=20.0))
    assert rep.body_checked
    assert rep.body_interferences == [], rep.describe()
    assert rep.feasible
