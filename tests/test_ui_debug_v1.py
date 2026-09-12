"""Banc de debug V1 : accessibilite, orientations, collisions.

Discipline reprise de M6 et M7 : **faire varier le parametre qui doit commander
le resultat, et verifier qu'il le commande** — et son revers, qu'une grandeur
stable sous un parametre qui varie est une information, pas une confirmation.

Le defaut le plus instructif de cette version s'est pris ainsi : le banc
ouvrait sur une fraise a bout droit et rejetait la singularite, ce qui faisait
declarer « inaccessible » presque toutes les faces du corpus. Le calcul etait
juste ; les reglages par defaut faisaient conclure le contraire de la verite.
"""

import os

import numpy as np
import pytest

from xyzac.ui.debug import palette
from xyzac.ui.debug.state import BenchState

os.environ.setdefault("VTK_DEFAULT_OPENGL_WINDOW", "vtkOSOpenGLRenderWindow")


def _can_render() -> bool:
    try:
        import pyvista as pv

        pv.OFF_SCREEN = True
        p = pv.Plotter(off_screen=True, window_size=(32, 32))
        p.add_mesh(pv.Sphere())
        p.screenshot(return_img=True)
        p.close()
        return True
    except Exception:                                            # noqa: BLE001
        return False


render = pytest.mark.skipif(not _can_render(), reason="pas de rendu 3D")


def _img_sum(path) -> int:
    from PIL import Image

    return int(np.asarray(Image.open(path).convert("RGB")).astype(np.int64).sum())


@pytest.fixture(scope="module")
def bench(corpus_dir):
    st = BenchState()
    st.load_step(corpus_dir / "C04_rainure_profonde.step")
    st.set_default_tool()
    return st


# --------------------------------------------------- coherence du resultat

def test_every_reject_reason_has_a_colour_and_a_family():
    """Un motif sans couleur s'afficherait en gris neutre, donc indistinguable
    d'un rejet geometrique. Un motif sans famille ne serait compte nulle part."""
    from xyzac.accessibility_solver.solver import RejectReason

    for r in RejectReason:
        assert r.name in palette.REASON_COLOR, r.name
        assert r.name in palette.REASON_FAMILY, r.name
        assert palette.reason_family(r.name) in palette.FAMILY_COLOR


def test_counts_account_for_every_candidate(bench):
    """Les compteurs par famille doivent totaliser les orientations evaluees.

    Un candidat qui n'entre dans aucune famille disparaitrait du panneau, et le
    total afficherait moins que ce qui a ete calcule.
    """
    res = bench.analyse_face(1, max_points=2)
    assert sum(res.counts.values()) == len(res.candidates)
    assert res.counts.get("admissible", 0) == res.n_feasible
    assert 0 < res.n_points_solved <= res.n_points_face


def test_result_reports_the_hypotheses_that_produced_it(bench):
    """Un nombre d'orientations admissibles ne veut rien dire sans ses reglages.

    Le meme point passe de 2 a 118 orientations selon l'outil et le traitement
    de la singularite : les taire rendrait le panneau trompeur. L'absence de
    bridage doit en particulier etre annoncee comme rendant le resultat
    OPTIMISTE.
    """
    res = bench.analyse_face(1, max_points=2)
    h = res.hypotheses
    assert "outil" in h and "singularite A=0" in h and "lead maximal" in h
    assert "OPTIMISTE" in h["bridage"], "l'absence de bridage doit etre dite"
    texte = dict(res.summary_lines())
    assert "— hypotheses —" in texte


def test_sample_never_passes_for_the_whole_face(bench):
    """Un echantillon qui se presenterait comme la face entiere serait un
    mensonge par omission."""
    res = bench.analyse_face(1, max_points=3)
    assert res.n_points_face > res.n_points_solved
    assert f"{res.n_points_solved} sur {res.n_points_face}" in dict(
        res.summary_lines())["Points analyses"]


# ------------------------------- les parametres commandent-ils le resultat ?

def test_tool_shape_commands_the_number_of_orientations(corpus_dir):
    """LE defaut de reglage par defaut de cette version, fixe par un test.

    Sur la face superieure du bloc C01, une fraise a bout DROIT a 2 orientations
    admissibles, une hemispherique en a plus de cent. Ce n'est pas un defaut du
    moteur mais la physique connue depuis M1 : une fraise a bout droit sur une
    face plane ne peut ni travailler verticale (singularite) ni inclinee (son
    talon enfonce la matiere). Le banc ouvrait sur cet outil, et faisait donc
    conclure que tout etait inaccessible.
    """
    st = BenchState()
    st.load_step(corpus_dir / "C01_bloc_simple.step")

    n = {}
    for kind in ("endmill", "ballnose"):
        st.set_default_tool(kind)
        n[kind] = st.analyse_face(5, max_points=1).n_feasible

    assert n["ballnose"] > 10 * n["endmill"], n
    assert n["endmill"] >= 1, "le bout droit doit garder quelques orientations"


def test_singularity_setting_commands_the_result(corpus_dir):
    """La singularite est un probleme de MOUVEMENT, pas de position (ADR-003).

    En indexation 3+2 l'axe C est bloque et A = 0 est utilisable. Le banc la
    permet donc par defaut — la rejeter ferait declarer inatteignable une face
    que trois axes suffisent a usiner.
    """
    st = BenchState()
    st.load_step(corpus_dir / "C01_bloc_simple.step")
    st.set_default_tool("ballnose")

    permise = st.analyse_face(5, max_points=1, reject_singular=False).n_feasible
    rejetee = st.analyse_face(5, max_points=1, reject_singular=True).n_feasible
    assert permise > rejetee, (permise, rejetee)


def test_unknown_tool_kind_is_refused():
    st = BenchState()
    with pytest.raises(ValueError, match="type d'outil inconnu"):
        st.set_default_tool("fraise-magique")


# --------------------------------------- accord avec le moteur, pas re-calcul

def test_collision_matrix_agrees_with_the_solver_margin(bench):
    """Test differentiel : le panneau et le solveur doivent dire la meme chose.

    Un panneau de debug qui contredit le moteur est pire que pas de panneau.
    Regression de deux defauts reels : la tolerance d'arete manquante, qui
    faisait signaler « arete / PART : 804 points en violation » sur des
    orientations declarees admissibles, et la marge globale reportee ligne par
    ligne, qui affichait « degage, -2,335 mm ».
    """
    res = bench.analyse_face(1, max_points=3)
    admis = [c for c in res.candidates if c.feasible]
    assert admis, "cette face doit avoir des orientations admissibles"
    best = max(admis, key=lambda c: c.margin_mm)
    bench.set_inspect_from_candidate(res, best)

    rows = bench.collision_matrix(best.direction)
    part = [r for r in rows if r[1] == "PART"]

    # Aucune collision annoncee sur une orientation que le solveur accepte.
    assert not any("COLLISION" in r[2] for r in part), part

    # Et la marge de synthese est celle du solveur, au millieme.
    synth = [r for r in part if r[0] == "(synthese)"][0][2]
    marge = float(synth.split("marge minimale")[1].split("mm")[0])
    assert marge == pytest.approx(best.margin_mm, abs=1e-3)


def test_collision_matrix_asks_the_machine_guard(bench):
    """Les organes machine ne sont pas dans le champ d'obstacles : ils viennent
    du garde. Sans l'interroger, la ligne MACHINE annoncait « aucun obstacle »
    alors que c'est la cause de rejet la plus frequente sur ce corpus."""
    res = bench.analyse_face(1, max_points=3)
    refuses = [c for c in res.candidates if c.reason_name == "MACHINE_COLLISION"]
    assert refuses, "cette face doit avoir des rejets machine"
    bench.set_inspect_from_candidate(res, refuses[0])

    rows = bench.collision_matrix(refuses[0].direction)
    machine = [r for r in rows if r[1] == "MACHINE"]
    assert machine, "la ligne MACHINE doit exister"
    assert any("collision" in r[2].lower() for r in machine), machine


def test_collision_matrix_aggregates_by_role(bench):
    """Un bec hemispherique compte huit troncons de role ``cutting`` : les
    lister huit fois repetait la meme information."""
    rows = bench.collision_matrix()
    for cls in ("PART", "STOCK"):
        roles = [r[0] for r in rows if r[1] == cls and r[0] != "(synthese)"]
        assert len(roles) == len(set(roles)), (cls, roles)


def test_placing_the_tool_uses_the_solver_tcp(bench):
    """La pose affichee doit etre CELLE que le solveur a evaluee.

    Elle vient donc de ``tcp_from_contact``, la meme fonction, et non d'un
    placement approche — sinon l'image montrerait une pose voisine de celle
    dont on affiche le verdict.
    """
    from xyzac.accessibility_solver.solver import tcp_from_contact

    res = bench.analyse_face(1, max_points=2)
    cnd = res.candidates[0]
    bench.set_inspect_from_candidate(res, cnd)

    attendu = tcp_from_contact(res.point, res.normal, cnd.direction, bench.tool)
    assert bench.inspect_tcp == pytest.approx(attendu)
    assert bench.inspect_a_deg == pytest.approx(cnd.a_deg)
    assert bench.inspect_c_deg == pytest.approx(cnd.c_deg)


def test_rejected_orientations_do_not_invent_a_machine_position(bench):
    """Une orientation rejetee n'a pas de pose realisable : afficher un X/Y/Z
    serait inventer. Le panneau doit dire « non disponible »."""
    res = bench.analyse_face(1, max_points=2)
    for c in res.candidates:
        if c.feasible:
            assert c.tcp_machine is not None
        else:
            assert c.tcp_machine is None
            assert "non disponible" in dict(c.lines())["X"]


# ------------------------------------------------- solidarite du montage

def test_part_and_table_stay_rigidly_attached_under_rotation(bench):
    """Regression d'une image fausse.

    Les organes machine etaient dessines sans etre animes par (A, C) : a
    A = -75 deg la piece partait a 116 mm en Y et -61 mm en Z tandis que le
    plateau restait plat, donc l'image montrait une piece detachee du plateau
    sur lequel elle est bridee. Sur une vue dont le sujet EST le degagement
    machine, c'est l'inverse de ce qu'on vient verifier.

    La distance entre le centre de la piece et celui du plateau ne depend donc
    d'aucune pose : les deux sont solidaires.
    """
    from xyzac.ui.debug import scene as S

    mesh = S.occt_to_mesh(bench.part_shape)
    cv = [c for c in bench.machine.collision_volumes if c.frame == "table_C"][0]
    plateau = S.cylinder_mesh(cv.base, cv.axis, cv.radius, cv.height)

    ref = None
    for a, c in ((0.0, 0.0), (-40.0, 30.0), (-74.8, -9.7), (25.0, -180.0)):
        pt = S.transport_to_machine(mesh, bench.machine, bench.mount_offset, a, c)
        pl = S.transport_by_frame(plateau, bench.machine, "table_C", a, c)
        d = float(np.linalg.norm(np.asarray(pt.points).mean(axis=0)
                                 - np.asarray(pl.points).mean(axis=0)))
        if ref is None:
            ref = d
        assert d == pytest.approx(ref, abs=1e-6), f"A={a} C={c} : {d} vs {ref}"


def test_an_unknown_volume_frame_is_refused():
    """Un repere inconnu doit lever, pas etre dessine a l'origine."""
    from xyzac.ui.debug import scene as S
    from xyzac.machine_model import default_xyzac_kit

    with pytest.raises(ValueError, match="repere de volume machine inconnu"):
        S.transport_by_frame(S.box_mesh([0, 0, 0], [1, 1, 1]),
                             default_xyzac_kit(), "poignee_de_porte", 10.0, 0.0)


# ------------------------------------------------------------------ image

@render
def test_orientation_arrows_change_the_image(bench, tmp_path):
    """Les fleches doivent etre visibles, et masquer une famille doit se voir."""
    from xyzac.ui.debug.scene import capture

    res = bench.analyse_face(1, max_points=2)
    sans = _img_sum(capture(bench, tmp_path / "a.png"))
    avec = _img_sum(capture(bench, tmp_path / "b.png", accessibility=res))
    assert sans != avec, "les fleches d'orientation ne se voient pas"

    sans_rejets = _img_sum(capture(
        bench, tmp_path / "c.png", accessibility=res,
        hidden={"orient_machine", "orient_tool", "orient_kin"}))
    assert sans_rejets != avec, "masquer les rejets n'a rien change"


@render
def test_the_pose_shown_changes_with_the_selected_orientation(bench, tmp_path):
    """Choisir une orientation doit replacer l'outil, donc changer l'image."""
    from xyzac.ui.debug.scene import capture

    res = bench.analyse_face(1, max_points=3)
    admis = [c for c in res.candidates if c.feasible]
    a, b = admis[0], admis[-1]
    assert abs(a.a_deg - b.a_deg) + abs(a.c_deg - b.c_deg) > 1.0

    bench.set_inspect_from_candidate(res, a)
    i1 = _img_sum(capture(bench, tmp_path / "p1.png", accessibility=res))
    bench.set_inspect_from_candidate(res, b)
    i2 = _img_sum(capture(bench, tmp_path / "p2.png", accessibility=res))
    assert i1 != i2


# ------------------------------------------------ trajectoire dans le banc

def test_the_bench_shows_what_would_be_posted(corpus_dir):
    """Un G-code qu'on ne peut pas inspecter visuellement n'est livre qu'a
    moitie. Le banc doit donc afficher la trajectoire de l'operation — celle
    que le post-processeur ecrira, liaisons et approche comprises.
    """
    st = BenchState()
    st.load_step(corpus_dir / "C02_poche_droite.step")
    st.set_default_tool("endmill")

    assert st.operation_path(0) is None, (
        "sans gamme calculee, il faut rendre None et non un tableau vide : "
        "un tableau vide se confondrait avec une gamme sans mouvement")
    assert dict(st.plan_lines())["Gamme"] == "non calculee"

    plan, rep = st.plan_roughing_preview(layer_thickness=4.0, pitch=2.5)
    assert plan.operations
    P, R = st.operation_path(0)
    assert len(P) > 100
    assert R is not None and R.any() and not R.all(), (
        "la trajectoire doit porter coupe ET liaisons")
    assert "Operations" in dict(st.plan_lines())


def test_loading_a_new_part_forgets_the_previous_plan(corpus_dir):
    """Une gamme calculee sur une autre piece ne s'y applique plus : la garder
    afficherait une trajectoire qui n'a rien a voir avec la matiere visible."""
    st = BenchState()
    st.load_step(corpus_dir / "C02_poche_droite.step")
    st.set_default_tool("endmill")
    st.plan_roughing_preview(layer_thickness=5.0, pitch=3.0)
    assert st.plan is not None

    st.load_step(corpus_dir / "C01_bloc_simple.step")
    assert st.plan is None and st.operation_path(0) is None


@render
def test_the_toolpath_is_visible_and_separable(corpus_dir, tmp_path):
    """Coupe et liaisons sont deux calques : la question « ou est-ce que ca
    coupe » et la question « par ou est-ce que ca passe » ne se lisent pas sur
    la meme couleur."""
    from xyzac.ui.debug.scene import capture

    st = BenchState()
    st.load_step(corpus_dir / "C02_poche_droite.step")
    st.set_default_tool("endmill")
    st.plan_roughing_preview(layer_thickness=5.0, pitch=3.0)
    tp = st.operation_path(0)

    sans = _img_sum(capture(st, tmp_path / "s.png"))
    avec = _img_sum(capture(st, tmp_path / "a.png", toolpath=tp))
    sans_rapides = _img_sum(capture(st, tmp_path / "r.png", toolpath=tp,
                                    hidden={"path_rapid"}))
    assert sans != avec, "la trajectoire ne se voit pas"
    assert sans_rapides != avec, "masquer les liaisons n'a rien change"
