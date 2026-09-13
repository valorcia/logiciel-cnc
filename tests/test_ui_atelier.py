"""L'atelier : l'interface de l'utilisateur (jalon M12).

Le banc de debug montre ce que le moteur CALCULE ; l'atelier montre ce que
l'utilisateur DOIT FAIRE. Ces tests protegent cette difference : une phrase
affichee ici doit toujours designer une action, et jamais laisser quelqu'un
devant un constat sans suite.
"""

import ast
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pytest

from xyzac.ui.atelier.server import servir
from xyzac.ui.atelier.session import REMEDES, Reglages, Session, nommer

ATELIER = Path(__file__).resolve().parents[1] / "src" / "xyzac" / "ui" / "atelier"


# ------------------------------------------------------------------ securite

def test_no_atelier_module_can_reach_a_machine():
    """LA regle : cette interface est 100 % simulation.

    Verifie sur l'AST et non par ``grep`` : un commentaire qui NOMME
    ``linuxcnc_gateway`` — comme celui-ci — ferait echouer une recherche
    textuelle, et l'a deja fait au jalon precedent.
    """
    interdits = {"linuxcnc_gateway", "socket", "telnetlib", "serial", "linuxcnc"}
    for f in ATELIER.rglob("*.py"):
        arbre = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for n in ast.walk(arbre):
            if isinstance(n, ast.Import):
                for a in n.names:
                    assert a.name.split(".")[0] not in interdits, (f, a.name)
            elif isinstance(n, ast.ImportFrom) and n.module:
                racine = n.module.lstrip(".").split(".")[0]
                assert racine not in interdits, (f, n.module)


def test_the_page_says_it_is_a_simulation_before_anything_else():
    """L'avertissement doit etre lu AVANT le premier bouton, pas en pied de
    page : quelqu'un qui clique sans lire doit quand meme l'avoir vu."""
    html = (ATELIER / "static" / "index.html").read_text(encoding="utf-8")
    i_avert = html.index("SIMULATION UNIQUEMENT")
    i_bouton = html.index("<button")
    assert i_avert < i_bouton


def test_the_server_only_listens_on_the_loopback():
    srv = servir(0)
    try:
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        srv.server_close()


# --------------------------------------------------------------- le langage

@pytest.mark.parametrize("normale,attendu", [
    ([0, 0, 1], "le dessus"),
    ([0, 0, -1], "le dessous"),
    ([1, 0, 0], "le flanc droit"),
    ([-1, 0, 0], "le flanc gauche"),
    ([0, 1, 0], "le flanc arriere"),
    ([0, -1, 0], "le flanc avant"),
])
def test_surfaces_are_named_by_something_one_can_point_at(normale, attendu):
    """« Surface 3 — 11 980 points » ne dit rien a personne ; « le dessous » se
    montre du doigt. Le nom vient de la normale calculee par le moteur."""
    assert nommer(normale) == attendu


def test_every_blocking_reason_the_engine_can_report_has_a_plain_remedy():
    """Structurel, et c'est le plus important de ce fichier.

    Si un motif du moteur n'a pas de traduction, l'utilisateur recoit un
    constat sans suite — la seule chose qu'une consigne ne doit jamais faire.
    Ce test attache le vocabulaire de l'interface a celui du moteur, de sorte
    qu'un motif ajoute plus tard ne puisse pas passer en silence.
    """
    from xyzac.accessibility_solver.solver import RejectReason

    manquants = [r.name for r in RejectReason
                 if r is not RejectReason.OK and r.name not in REMEDES]
    assert not manquants, f"motifs sans consigne : {manquants}"


def test_a_remedy_names_an_action_not_a_diagnosis():
    """Chaque consigne doit contenir un verbe d'action : « il faut un outil
    plus fin » agit, « collision du porte-outil » informe."""
    verbes = ("prenez", "sortez", "surelevez", "rapprochez", "retourner",
              "il faut", "posez", "ajoutez", "allongez", "essayez")
    sans = [k for k, v in REMEDES.items()
            if not any(x in v.lower() for x in verbes)]
    # deux motifs decrivent un etat sans action possible a ce niveau ; ils sont
    # nommes ici pour qu'on ne puisse pas en ajouter sans y penser
    assert set(sans) <= {"SINGULARITY", "LEAD_LIMIT", "BACK_FACING"}, sans


# ------------------------------------------------------------- le chargement

def test_loading_a_healthy_part_reports_it_in_plain_words(corpus_dir):
    s = Session()
    s.charger(corpus_dir / "C01_bloc_simple.step")
    assert s.piece_chargee
    assert s.dimensions == "60 x 40 x 20 mm"
    assert "solide" in s.import_detail and "surfaces" in s.import_detail
    assert not s.erreur


def test_the_import_line_never_contradicts_itself(corpus_dir):
    """``healing`` est renseigne MEME quand rien n'a ete repare : il dit alors
    « Reparation non appliquee ». L'introduire par « Reparation appliquee : »
    donnait « Reparation appliquee : Reparation non appliquee », qui se
    contredit en six mots."""
    s = Session()
    for f in sorted(corpus_dir.glob("C0*.step"))[:5]:
        s.charger(f)
        bas = s.import_detail.lower()
        assert not ("reparation :" in bas and "non appliquee" in bas), (
            f.name, s.import_detail)


def test_a_refused_geometry_gives_an_instruction_not_a_crash():
    """L'importeur REFUSE une coque non fermee, et il a raison. Son message dit
    quoi faire ; il doit arriver a l'ecran, pas remonter en erreur 500."""
    d = Path(__file__).resolve().parents[1] / "tests" / "corpus" / "step_degraded"
    fichier = d / "D01_shell_ouvert.step"
    if not fichier.exists():
        pytest.skip("corpus degrade absent")
    s = Session()
    s.charger(fichier)                       # ne doit PAS lever
    assert not s.piece_chargee
    assert s.erreur
    assert "re-exporter" in s.erreur or "Refermer" in s.erreur


# ------------------------------------------------------------------ le web

def _client(port):
    def appel(chemin, corps=None):
        url = f"http://127.0.0.1:{port}{chemin}"
        if corps is None:
            r = urllib.request.urlopen(url, timeout=60)
        else:
            r = urllib.request.urlopen(urllib.request.Request(
                url, method="POST", data=json.dumps(corps).encode(),
                headers={"Content-Type": "application/json"}), timeout=120)
        return r.read()
    return appel


@pytest.fixture()
def serveur(tmp_path):
    srv = servir(0, travail=tmp_path / "t")
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield _client(port)
    srv.shutdown()
    srv.server_close()


def test_the_page_and_its_assets_are_served(serveur):
    assert b"Atelier XYZAC" in serveur("/")
    assert b"function" in serveur("/app.js") or b"const" in serveur("/app.js")
    assert b"--primaire" in serveur("/style.css")


def test_the_page_asks_the_network_for_nothing():
    """Elle doit marcher hors ligne, sur un Pi sans internet. Aucune balise ne
    doit pointer vers un domaine exterieur."""
    html = (ATELIER / "static" / "index.html").read_text(encoding="utf-8")
    for motif in ("http://", "https://", "//cdn", "//unpkg", "//fonts"):
        assert motif not in html.replace(
            "http://www.w3.org/2000/svg", ""), motif


def test_only_corpus_files_can_be_loaded(serveur):
    """« Local » n'est pas une politique de securite : un chemin arbitraire
    doit etre refuse, meme sur la boucle locale."""
    for mauvais in ("../../../etc/passwd", "/etc/passwd", "inexistant.step"):
        with pytest.raises(urllib.error.HTTPError) as e:
            serveur("/api/piece", {"fichier": mauvais})
        assert e.value.code == 400


def test_changing_a_setting_drops_the_previous_verdict(serveur, corpus_dir):
    """Un verdict calcule sous d'autres cotes ne doit pas rester affiche : il
    serait faux, et rien a l'ecran ne le dirait."""
    serveur("/api/piece", {"fichier": "C01_bloc_simple.step"})
    s = Session()
    e = json.loads(serveur("/api/reglages", {"diametre_outil": 3}))
    assert e["reglages"]["diametre_outil"] == 3.0
    assert e["surfaces"] == [] and e["resume"] == ""


def _faux_verdict(atteignable: bool):
    """Un depistage synthetique, avec les vraies classes du moteur."""
    from xyzac.strategy_planner.setups import (CANONICAL_MOUNTS, PassScreen,
                                               SetupCoverage)

    class FaussePasse:
        n_points = 1000
        normals = np.tile([0.0, 0.0, 1.0], (4, 1))

    couv = []
    for i, o in enumerate(CANONICAL_MOUNTS):
        ok = atteignable if i == 0 else False
        couv.append(SetupCoverage(
            orientation=o, mount_offset_mm=(0.0, 0.0, 25.0),
            screens=[PassScreen(pass_index=0, reachable=ok, n_probe=6,
                                n_unreachable=0 if ok else 3,
                                reasons={} if ok else {"MACHINE_COLLISION": 3},
                                field_inflation_mm=1.0, probe_nose_mm=1.5)]))
    return [FaussePasse()], couv


def test_the_warnings_that_bound_the_result_travel_with_it():
    """Le resultat est etabli sur un echantillon, sans bridage. Les deux
    reserves doivent voyager avec lui, sans quoi il se lit comme une garantie."""
    s = Session()
    passes, couv = _faux_verdict(atteignable=True)
    s._rediger(passes, couv)
    joint = " ".join(s.avertissements).lower()
    assert "echantillon" in joint
    assert "bridage" in joint and "optimiste" in joint
    assert s.resume and "usinables telles quelles" in s.resume


def test_an_unreachable_surface_always_gets_an_instruction():
    """Aucune surface ne doit ressortir avec un constat sans suite."""
    s = Session()
    passes, couv = _faux_verdict(atteignable=False)
    s._rediger(passes, couv)
    assert len(s.surfaces) == 1
    surf = s.surfaces[0]
    assert surf.verdict == "impossible"
    assert surf.consigne.strip().endswith(".")
    assert "surelevez" in surf.consigne.lower() or "posez" in surf.consigne.lower()


def test_several_setups_warn_that_errors_add_up():
    """Chaque remontage repositionne la piece : le dire fait partie du
    resultat, pas des petits caracteres."""
    from xyzac.strategy_planner.setups import (CANONICAL_MOUNTS, PassScreen,
                                               SetupCoverage)

    class FaussePasse:
        n_points = 500
        normals = np.tile([0.0, 0.0, -1.0], (4, 1))

    couv = []
    for i, o in enumerate(CANONICAL_MOUNTS):
        ok = (i == 1)                     # seule la pose « retourne » y arrive
        couv.append(SetupCoverage(
            orientation=o, mount_offset_mm=(0.0, 0.0, 25.0),
            screens=[PassScreen(pass_index=0, reachable=ok, n_probe=6,
                                n_unreachable=0 if ok else 6,
                                reasons={} if ok else {"AXIS_LIMITS": 6},
                                field_inflation_mm=1.0, probe_nose_mm=1.5)]))
    s = Session()
    s._rediger([FaussePasse()], couv)
    assert s.surfaces[0].verdict == "a-changer"
    assert "Retournez" in s.surfaces[0].consigne
    joint = " ".join(s.avertissements).lower()
    assert "erreurs s'additionnent" in joint or "s'additionnent" in joint


def test_the_settings_that_can_be_tried_are_the_ones_that_change_the_verdict():
    """Cinq cotes de machine et deux d'outil : ce sont celles qui changent
    l'ACCESSIBILITE. Les avances changent le temps d'usinage, pas la
    faisabilite, et les melanger ferait croire qu'elles se valent."""
    champs = set(vars(Reglages()))
    assert champs == {"course_x", "course_y", "course_z_bas", "course_z_haut",
                      "a_min", "a_max", "rayon_plateau", "diametre_outil",
                      "jauge_outil"}
    m = Reglages(course_x=99.0, a_min=-60.0, rayon_plateau=40.0).machine()
    assert m.x.max_mm == 99.0 and m.a.min_deg == -60.0
    rayons = [v.radius for v in m.collision_volumes if v.radius is not None]
    assert 40.0 in rayons, "le rayon du plateau doit atteindre le volume machine"


def test_the_page_files_are_declared_as_package_data():
    """Defaut qui ne se voit qu'a l'installation sur la machine cible.

    Le HTML, le CSS et le JS ne sont pas du code Python : sans declaration
    ``package-data``, ils sont absents d'une installation non editable. Tout
    marche en developpement, et l'atelier rend une page vide sur le Pi.
    Verifie sur le pyproject ET sur le disque, parce que les deux peuvent
    diverger.
    """
    racine = Path(__file__).resolve().parents[1]
    toml = (racine / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.setuptools.package-data]" in toml
    assert '"xyzac.ui.atelier" = ["static/*"]' in toml

    from xyzac.ui.atelier import server

    for nom in ("index.html", "app.js", "style.css"):
        assert (server.STATIQUE / nom).is_file(), nom
