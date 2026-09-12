"""Banc de debug visuel, V0.

Ce que ces tests couvrent, et ce qu'ils ne couvrent pas — la distinction est le
point important, parce que le conteneur de developpement n'a pas d'ecran :

  COUVERT   l'etat (``state``) et la scene (``scene``), qui sont sans Qt : le
            chargement d'un STEP par l'importeur controle, la coherence des
            valeurs affichees avec les modules metier, le fait qu'un calque
            masque change reellement l'image, le cadrage, la securite.

  NON COUVERT  le glisser-deposer de la camera et le rendu dans le widget Qt.
            La rotation et le zoom a la souris sont assures par l'interacteur de
            VTK, qui n'est pas du code de ce projet. Le banc expose ``orbit`` et
            ``zoom``, qui sont la meme operation par programme, et celles-la
            sont testees via ``capture``.
"""

import os

import numpy as np
import pytest

from xyzac.geometry_core import brep
from xyzac.kinematics_solver.solver import KinematicsSolver
from xyzac.machine_model import default_xyzac_kit
from xyzac.ui.debug import palette
from xyzac.ui.debug.state import BenchState

# Le rendu logiciel (OSMesa) n'est pas present partout. On saute les tests
# d'image plutot que de les faire echouer sur une machine sans rendu — mais on
# ne saute PAS les tests d'etat, qui n'en ont pas besoin.
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


render = pytest.mark.skipif(not _can_render(),
                            reason="pas de rendu 3D disponible (OSMesa absent)")


def _img_sum(path) -> int:
    from PIL import Image

    return int(np.asarray(Image.open(path).convert("RGB")).astype(np.int64).sum())


# --------------------------------------------------------------- code couleur

def test_palette_is_one_source_and_states_are_distinguishable():
    """Une couleur qui veut dire deux choses ne sert a rien.

    Verifie aussi que valide et collision se separent en LUMINANCE, pas
    seulement en teinte : sinon un daltonien rouge-vert lit la meme chose.
    """
    for name in ("VALID", "COLLISION", "WARNING", "PATH", "PART", "STOCK"):
        c = getattr(palette, name)
        assert isinstance(c, str) and c.startswith("#") and len(c) == 7, name

    def lum(hexa: str) -> float:
        r, g, b = (int(hexa[i:i + 2], 16) for i in (1, 3, 5))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    assert abs(lum(palette.VALID) - lum(palette.COLLISION)) > 20.0
    assert palette.role_color("inconnu") == palette.NEUTRAL
    assert palette.role_color("holder") != palette.role_color("cutting")


# ----------------------------------------------------------------- chargement

def test_load_step_uses_the_guarded_importer(corpus_dir):
    """Le banc doit voir ce que le MOTEUR voit.

    Il passe donc par ``healing.load_step_checked`` et non par
    ``brep.load_step`` : c'est lui qui separe un defaut geometrique d'une
    invraisemblance de cote et refuse une reparation qui deplace la matiere. Un
    banc qui contournerait ce chemin montrerait autre chose que le moteur.
    """
    st = BenchState()
    info = st.load_step(corpus_dir / "C01_bloc_simple.step")
    assert info.n_solids == 1
    assert info.n_faces == 6
    assert info.size == pytest.approx([60.0, 40.0, 20.0], abs=1e-3)
    assert info.volume_mm3 == pytest.approx(60.0 * 40.0 * 20.0, rel=1e-4)
    assert st.stock is not None, "le brut doit etre derive automatiquement"
    assert info.diagnosis, "le diagnostic d'import doit etre conserve"


def test_load_step_refuses_an_unusable_shape(degraded_dir):
    """Une coque ouverte n'est pas un solide : le banc doit REFUSER, pas
    afficher un objet sur lequel aucun calcul n'a de sens."""
    from xyzac.geometry_core.healing import UnusableShapeError

    st = BenchState()
    with pytest.raises(UnusableShapeError):
        st.load_step(degraded_dir / "D01_shell_ouvert.step")


# ------------------------------------------------- regle de non-invention

def test_absent_values_say_so_and_are_never_zero(corpus_dir):
    """Regle du projet portee a l'affichage : ce qui n'est pas calcule
    s'affiche « non disponible ». Un zero se confond avec une mesure."""
    st = BenchState()
    assert "aucune piece" in st.axis_readout().source

    st.load_step(corpus_dir / "C01_bloc_simple.step")
    st.set_default_tool()

    tool = dict(st.tool_lines())
    assert "non disponible" in tool["Avance"]
    assert "non disponible" in tool["Vitesse broche"]

    axes = dict(st.axis_readout().lines())
    assert "aucune trajectoire" in axes["Origine des valeurs"], (
        "les valeurs d'axes sont une pose d'inspection, pas un resultat de calcul")

    machine = dict(st.machine_lines())
    assert "NON MESUREE" in machine["Geometrie"]
    assert "SIMULATION" in machine["Machine"]


# ------------------------------------------ pas de logique metier dupliquee

def test_machine_tcp_comes_from_the_kinematics_solver(corpus_dir):
    """Test differentiel : l'IHM ne doit pas reimplementer le transport.

    Si ce test casse, c'est que le banc calcule sa propre cinematique — et une
    image juste sur une cinematique differente de celle du moteur est pire
    qu'aucune image.
    """
    st = BenchState()
    st.load_step(corpus_dir / "C10_dome_convexe.step")
    st.inspect_a_deg, st.inspect_c_deg = -35.0, 42.0

    ks = KinematicsSolver(st.machine)
    attendu = ks.part_to_machine_point(
        np.asarray(st.inspect_tcp) + st.mount_offset, -35.0, 42.0)
    assert st.machine_tcp() == pytest.approx(attendu)

    r = st.axis_readout()
    assert (r.x_mm, r.y_mm, r.z_mm) == pytest.approx(tuple(attendu))
    assert r.a_deg == -35.0 and r.c_deg == 42.0


def test_transport_agrees_with_the_solver_point_by_point(corpus_dir):
    """Le maillage transporte doit coincider avec la chaine du moteur.

    C'est le test qui interdit une image « presque juste » : un repere melange
    faisait traverser le brut par le plateau, et ce genre de faute ne se voit
    pas sans comparer aux nombres.
    """
    from xyzac.ui.debug.scene import box_mesh, transport_to_machine

    m = default_xyzac_kit()
    mesh = box_mesh([0.0, 0.0, 0.0], [10.0, 20.0, 30.0])
    mo = np.array([1.0, -2.0, 25.0])
    got = transport_to_machine(mesh, m, mo, -20.0, 33.0)

    ks = KinematicsSolver(m)
    want = np.array([ks.part_to_machine_point(p + mo, -20.0, 33.0)
                     for p in np.asarray(mesh.points, dtype=float)])
    assert np.asarray(got.points) == pytest.approx(want)


def test_mesh_keeps_face_ids_from_the_engine_tesselator(corpus_dir):
    """La selection de face a besoin de l'identifiant de face, et il doit venir
    du tesselateur du moteur — pas d'un maillage refait autrement."""
    from xyzac.ui.debug.scene import occt_to_mesh

    shape = brep.load_step(corpus_dir / "C01_bloc_simple.step")
    _, tris, face_id = brep.tessellate(shape, deflection=0.05)
    mesh = occt_to_mesh(shape, deflection=0.05)
    assert mesh.n_cells == len(tris)
    assert np.array_equal(mesh.cell_data["face_id"], face_id)


# ------------------------------------------------------------ calques et image

def test_a_layer_without_actors_cannot_claim_to_be_shown():
    """Une case cochee sur un calque vide affirmerait un affichage inexistant.
    ``set_visible`` rend donc l'etat REEL, pas la demande."""
    from xyzac.ui.debug.scene import DebugScene

    sc = DebugScene(plotter=None)
    assert sc.set_visible("path", True) is False
    assert sc.visible["path"] is False


@render
def test_capture_produces_an_image_and_hiding_a_layer_changes_it(corpus_dir, tmp_path):
    """LE test du bouton « afficher/cacher ».

    Il compare deux IMAGES et non deux etats internes. Mesure qui a impose ce
    choix : sur le rendu logiciel sans ecran, une fenetre de rendu ne produit
    qu'une seule image et ignore tout changement ulterieur — visibilite, camera,
    fond. ``capture`` construit donc une fenetre par appel, et c'est ce que ce
    test verifie reellement.
    """
    from xyzac.ui.debug.scene import capture

    st = BenchState()
    st.load_step(corpus_dir / "C10_dome_convexe.step")
    st.set_default_tool()

    tout = _img_sum(capture(st, tmp_path / "a.png"))
    sans_brut = _img_sum(capture(st, tmp_path / "b.png", hidden={"stock"}))
    sans_outil = _img_sum(capture(
        st, tmp_path / "c.png",
        hidden={"tool_cutting", "tool_shank", "tool_holder", "tool_spindle"}))

    assert tout != sans_brut, "cacher le brut n'a rien change a l'image"
    assert tout != sans_outil, "cacher l'outil n'a rien change a l'image"
    assert sans_brut != sans_outil


@render
def test_camera_moves_change_the_image(corpus_dir, tmp_path):
    """Rotation et zoom par programme : le pendant testable du glisser-deposer."""
    from xyzac.ui.debug.scene import capture

    st = BenchState()
    st.load_step(corpus_dir / "C01_bloc_simple.step")
    st.set_default_tool()

    base = _img_sum(capture(st, tmp_path / "v0.png"))
    tourne = _img_sum(capture(st, tmp_path / "v1.png", azimuth_deg=70.0))
    zoome = _img_sum(capture(st, tmp_path / "v2.png", zoom=2.0))
    assert base != tourne, "la rotation n'a rien change"
    assert base != zoome, "le zoom n'a rien change"


@render
def test_default_framing_is_tighter_than_seeing_everything(corpus_dir, tmp_path):
    """Regression d'un cadrage qui ne cadrait pas.

    ``reset_camera(bounds=...)`` est ignore par la version de PyVista employee :
    les deux cadrages rendaient une camera identique, a 819,6 mm du point vise,
    celle de la scene entiere — courses machine de 300 x 240 x 180 mm comprises,
    ce qui rend une piece de 60 mm minuscule. La camera est donc posee a la
    main, et ce test compare les deux distances.
    """
    import pyvista as pv

    from xyzac.ui.debug.scene import build_scene

    st = BenchState()
    st.load_step(corpus_dir / "C01_bloc_simple.step")
    st.set_default_tool()

    def distance(fit: str) -> float:
        pv.OFF_SCREEN = True
        p = pv.Plotter(off_screen=True, window_size=(200, 150))
        build_scene(st, plotter=p, off_screen=True, fit=fit)
        d = float(np.linalg.norm(np.array(p.camera.position)
                                 - np.array(p.camera.focal_point)))
        p.close()
        return d

    assert distance("part") < distance("all") / 2.0


# ------------------------------------------------------------------ securite

def test_no_debug_module_can_reach_the_machine():
    """Regle absolue : aucun bouton du banc ne peut deplacer une machine.

    Verifie sur l'ARBRE SYNTAXIQUE et non par recherche de texte : une premiere
    version cherchait la chaine « linuxcnc_gateway » dans le source et se
    declenchait sur les commentaires qui promettent justement de ne pas
    l'importer. Un test de securite qui se trompe de cible ne protege de rien,
    et il apprend a ignorer son propre echec.

    L'arbre attrape en revanche un import place dans une branche rarement
    prise, qu'un test a l'execution laisserait passer.
    """
    import ast
    from pathlib import Path

    import xyzac.ui.debug as pkg

    interdit = {"linuxcnc_gateway", "postprocessor_linuxcnc"}
    root = Path(pkg.__file__).parent
    fautifs = []
    for f in sorted(root.glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            noms: list[str] = []
            if isinstance(node, ast.Import):
                noms = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                noms = [node.module or ""] + [a.name for a in node.names]
            for n in noms:
                if any(bad in n for bad in interdit):
                    fautifs.append(f"{f.name}:{node.lineno} -> {n}")
    assert not fautifs, f"le banc ne doit pas atteindre la machine : {fautifs}"


def test_the_scene_layer_stays_free_of_qt():
    """``state`` et ``scene`` doivent rester sans Qt.

    Ce n'est pas une elegance : c'est ce qui les rend testables sans ecran, donc
    ce qui fait que la moitie utile du banc est verifiee. Y glisser un import Qt
    ferait basculer ce code du cote non teste.
    """
    from pathlib import Path

    import xyzac.ui.debug as pkg

    root = Path(pkg.__file__).parent
    for name in ("state.py", "scene.py", "palette.py"):
        src = (root / name).read_text(encoding="utf-8")
        assert "PySide6" not in src and "pyvistaqt" not in src, name


def test_no_compute_module_depends_on_the_ui_stack():
    """L'IHM est optionnelle, et cela doit rester verifiable.

    Le moteur doit s'installer et tourner sans PySide6 ni PyVista — c'est ce qui
    permet de le faire tourner sur une machine sans ecran, et c'est ce que
    l'extra ``ui`` de ``pyproject.toml`` affirme. Une affirmation d'installation
    non testee devient fausse au premier import de confort.
    """
    import ast
    from pathlib import Path

    import xyzac

    root = Path(xyzac.__file__).parent
    ui_stack = {"PySide6", "pyvista", "pyvistaqt", "vtk", "PIL"}
    fautifs = []
    for f in sorted(root.rglob("*.py")):
        if "ui" in f.relative_to(root).parts:
            continue                      # le banc, lui, a le droit
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            noms: list[str] = []
            if isinstance(node, ast.Import):
                noms = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                noms = [node.module or ""]
            for n in noms:
                if n.split(".")[0] in ui_stack:
                    fautifs.append(f"{f.relative_to(root)}:{node.lineno} -> {n}")
    assert not fautifs, f"le moteur ne doit pas dependre de l'IHM : {fautifs}"
