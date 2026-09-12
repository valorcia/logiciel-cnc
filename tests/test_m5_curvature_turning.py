"""Courbure locale, pas de finition reel, et tournage sur l'axe C (jalon M5)."""

import numpy as np
import pytest
from scipy.optimize import brentq

from xyzac.geometry_core import brep
from xyzac.geometry_core.curvature import curvature_stepover, face_curvature
from xyzac.machine_model import default_xyzac_kit
from xyzac.subtractive_slicer import (
    generate_finishing_passes,
    group_faces_by_normal,
    scallop_stepover,
)
from xyzac.tool_model import build_ballnose
from xyzac.turning_engine import (
    TurningTool,
    evaluate_turning,
    plan_turning_passes,
    require_c_mode,
    revolution_profile,
)
from xyzac.machine_model.machine import CAxisMode


# --------------------------------------------- crete : le sens de l'erreur

def _exact_cusp(R: float, rho: float, s: float, convex: bool) -> float:
    """Crete EXACTE entre deux passes, par intersection des positions d'outil."""
    dth = s / rho
    oc = rho + R if convex else rho - R

    def f(h):
        r = rho + h if convex else rho - h
        return oc * oc + r * r - 2 * r * oc * np.cos(dth / 2) - R * R

    return brentq(f, 0.0, R * 0.999)


@pytest.mark.parametrize("rho", [6.0, 12.0, 20.0])
@pytest.mark.parametrize("h", [0.002, 0.01, 0.05, 0.15])
def test_curvature_stepover_hits_the_requested_cusp_exactly(rho, h):
    """Aller-retour : le pas rendu doit laisser la crete DEMANDEE.

    ``curvature_stepover`` resout la loi des cosinus en forme fermee ; on lui
    demande un pas, on recalcule la crete que ce pas laisse reellement par
    intersection des deux positions d'outil, et les deux doivent coincider.
    C'est le seul test qui distingue une forme exacte d'un developpement
    plausible.
    """
    R = 3.0
    for convex in (True, False):
        kappa = (1.0 / rho) if convex else (-1.0 / rho)
        s = curvature_stepover(R, h, kappa)
        assert _exact_cusp(R, rho, s, convex) == pytest.approx(h, rel=1e-6), (
            f"rho={rho} h={h} convexe={convex}")


@pytest.mark.parametrize("s", [0.2, 0.5, 1.0, 1.5])
def test_first_order_expansion_stays_optimistic_on_convex(s):
    """Pourquoi la forme fermee, et pas ``h = (s^2/8).(1/R + kappa)``.

    Le developpement au premier ordre SOUS-ESTIME la crete sur une bosse, donc
    il sur-estime le pas admissible : c'est le mauvais sens de l'erreur. Ce
    test enregistre l'ampleur mesuree du biais (R = 3 mm, bosse de 6 mm), pour
    que sa reintroduction par commodite soit visible.

        s = 0,2 mm  ->  -0,08 %      s = 1,0 mm  ->  -2,05 %
        s = 0,5 mm  ->  -0,51 %      s = 1,5 mm  ->  -4,68 %
    """
    R, rho = 3.0, 6.0
    exact = _exact_cusp(R, rho, s, convex=True)
    first_order = (s * s / 8.0) * (1.0 / R + 1.0 / rho)
    assert first_order < exact, "le premier ordre sous-estime la crete convexe"

    # La forme fermee, elle, retrouve le pas exact a partir de cette crete.
    assert curvature_stepover(R, exact, 1.0 / rho) == pytest.approx(s, rel=1e-6)


def test_plane_formula_is_optimistic_on_CONVEX_surfaces():
    """RECTIFICATION du jalon M4, qui affirmait l'inverse.

    La documentation de M4 disait la formule plane optimiste en concave et
    pessimiste en convexe. C'est faux, et le calcul exact le montre : sur une
    bosse la crete reelle DEPASSE la prevision plane, d'un facteur qui atteint
    1,5 quand le rayon de la surface approche celui de l'outil.

    Le sens de l'erreur est ce qui compte, puisqu'il decide si l'on sur-decoupe
    ou sous-decoupe. Dimensionner une finition de bosse sur la formule plane
    laisse la piece hors tolerance sans qu'aucun indicateur ne le signale.
    """
    R, s = 3.0, 0.5
    plane = R - np.sqrt(R * R - (s / 2) ** 2)
    convex = _exact_cusp(R, 6.0, s, convex=True)
    concave = _exact_cusp(R, 6.0, s, convex=False)

    assert convex > plane, "sur une bosse la crete reelle depasse la prevision plane"
    assert concave < plane, "dans un creux elle est plus faible"
    assert convex / plane > 1.4


@pytest.mark.parametrize("kappa,expect", [
    (0.0, "egal"), (0.05, "plus_petit"), (-0.05, "plus_grand"),
])
def test_curvature_stepover_goes_in_the_right_direction(kappa, expect):
    plane = scallop_stepover(3.0, 0.01)
    curved = curvature_stepover(3.0, 0.01, kappa)
    if expect == "egal":
        assert curved == pytest.approx(plane, rel=1e-6)
    elif expect == "plus_petit":
        assert curved < plane          # convexe : il faut resserrer
    else:
        assert curved > plane          # concave : on peut elargir


def test_stepover_refuses_a_pocket_tighter_than_the_tool():
    """Dans un creux plus serre que l'outil, celui-ci ne touche pas le fond.
    Un pas plus petit n'y change rien : c'est l'outil qu'il faut changer."""
    with pytest.raises(ValueError, match="ne touche pas le fond"):
        curvature_stepover(3.0, 0.01, -1.0 / 2.5)


# ------------------------------------------- courbure mesuree sur le B-Rep

@pytest.mark.parametrize("case,face_kind,sign,radius", [
    ("C10_dome_convexe", "sphere", +1, 22.0),
    ("C11_cavite_spherique", "sphere", -1, 20.0),
    ("C13_arbre_gorge_torique", "cylinder", +1, 18.0),
])
def test_curvature_sign_and_radius_match_the_known_geometry(
        corpus_dir, case, face_kind, sign, radius):
    """Le signe est le point delicat : l'orientation topologique d'une face
    inverse la normale, donc la courbure. L'ignorer echangerait convexe et
    concave — et donc le sens de la correction de pas."""
    shape = brep.load_step(corpus_dir / f"{case}.step")
    found = False
    for f in brep.face_info(shape):
        if f.surface_type != face_kind:
            continue
        fc = face_curvature(shape, f.index)
        if fc is None:
            continue
        if abs(abs(fc.kappa_worst) - 1.0 / radius) < 1e-3:
            assert np.sign(fc.kappa_worst) == sign
            found = True
            break
    assert found, f"aucune face {face_kind} de rayon {radius} trouvee dans {case}"


def test_finishing_uses_curvature_when_available(corpus_dir):
    shape = brep.load_step(corpus_dir / "C10_dome_convexe.step")
    tool = build_ballnose("BN6", 6.0, 20.0, stickout=45.0, holder_type="ER16")
    shared = brep.sample_surface(shape, spacing=0.8)
    for g in group_faces_by_normal(shape):
        fp = generate_finishing_passes(shape, g, tool, scallop_mm=0.01, samples=shared)
        flat = generate_finishing_passes(shape, g, tool, scallop_mm=0.01,
                                         use_curvature=False, samples=shared)
        if fp is None or abs(fp.kappa_used) < 1e-6:
            continue
        # Le dome est convexe : le pas doit etre RESSERRE par rapport au plan.
        assert fp.stepover < flat.stepover
        return
    pytest.skip("aucun groupe courbe sur cette geometrie")


# --------------------------------------------------------------- tournage

@pytest.fixture(scope="module")
def lathe_tool():
    return TurningTool("TNMG", nose_radius=0.4, clearance_angle_deg=7.0,
                       max_depth_of_cut_mm=1.5)


def _profile(corpus_dir, case):
    shape = brep.load_step(corpus_dir / f"{case}.step")
    return shape, revolution_profile(shape, np.zeros(3), np.array([0.0, 0.0, 1.0]),
                                     n_z=120, n_theta=36, sample_spacing=0.6)


def test_profile_recovers_the_shaft_radii(corpus_dir):
    """L'arbre C12 fait R20 / R14 / R9 puis un cone 9 -> 4."""
    _, prof = _profile(corpus_dir, "C12_arbre_etage")
    assert prof.max_radius == pytest.approx(20.0, abs=0.1)
    assert prof.radius_at(25.0) == pytest.approx(14.0, abs=0.2)
    assert prof.radius_at(45.0) == pytest.approx(9.0, abs=0.2)
    assert prof.length == pytest.approx(70.0, abs=1.0)


def test_ovality_is_near_zero_on_a_true_revolution(corpus_dir):
    """Mesure sur THETA, et non sur l'etendue de la tranche.

    Un indicateur base sur r_max - r_min confondait la variation axiale d'un
    epaulement (parfaitement tournable) avec un meplat. L'arbre C12 etait ainsi
    declare non revolutif a 6 mm pres — exactement l'ecart entre deux de ses
    diametres.
    """
    for case in ("C12_arbre_etage", "C13_arbre_gorge_torique"):
        _, prof = _profile(corpus_dir, case)
        oor = prof.out_of_round()
        assert float(np.percentile(oor, 95)) < 0.1, case


def test_ovality_detects_real_flats(corpus_dir):
    """C14 porte deux meplats fraises : ils doivent ressortir nettement."""
    _, prof = _profile(corpus_dir, "C14_hybride_meplats")
    assert float(np.percentile(prof.out_of_round(), 95)) > 1.0


def test_roughing_descends_to_the_smallest_radius(corpus_dir, lathe_tool):
    """Une premiere version s'arretait au rayon MAXIMAL du profil : sur un arbre
    etage de R20 a R4, elle produisait deux passes et laissait les etages
    intacts."""
    _, prof = _profile(corpus_dir, "C12_arbre_etage")
    rep = plan_turning_passes(prof, lathe_tool, stock_radius=prof.max_radius + 2.0,
                              finish_allowance=0.2)
    rough = [p for p in rep.passes if p.kind == "ebauche"]
    assert len(rough) > 8, f"seulement {len(rough)} passes d'ebauche"
    assert min(float(p.r.min()) for p in rough) < prof.r.min() + 1.0
    assert any(p.kind == "finition" for p in rep.passes)


def test_turning_refuses_a_profile_steeper_than_the_tool(corpus_dir):
    """Un profil plus raide que l'outil n'est pas une question de trajectoire :
    aucun recalcul de passes n'y remedie."""
    _, prof = _profile(corpus_dir, "C12_arbre_etage")
    blunt = TurningTool("degagement-45", clearance_angle_deg=45.0)
    rep = plan_turning_passes(prof, blunt, stock_radius=22.0)
    assert not rep.feasible
    assert rep.too_steep_zones
    assert "outil inadapte" in rep.describe()


def test_turning_refuses_a_stock_below_the_profile(corpus_dir, lathe_tool):
    _, prof = _profile(corpus_dir, "C12_arbre_etage")
    rep = plan_turning_passes(prof, lathe_tool, stock_radius=1.0)
    assert not rep.feasible
    assert "brut" in rep.detail


def test_c_mode_switch_is_a_locked_transition():
    """Le passage indexation <-> tournage n'est pas un reglage : il invalide
    l'approbation et exige une nouvelle simulation (ADR-001 / D8)."""
    m = default_xyzac_kit()
    assert m.c_mode is CAxisMode.INDEXED
    require_c_mode(m, CAxisMode.INDEXED)
    with pytest.raises(RuntimeError, match="invalide l'approbation"):
        require_c_mode(m, CAxisMode.CONTINUOUS_SPINDLE)


def test_turning_candidate_still_rejects_off_axis_revolution(corpus_dir):
    """Regression M1 : un cylindre lateral EST de revolution, mais autour du
    mauvais axe."""
    m = default_xyzac_kit()
    shape = brep.load_step(corpus_dir / "C15_revolution_hors_axe.step")
    assert not evaluate_turning(shape, m).suitable
