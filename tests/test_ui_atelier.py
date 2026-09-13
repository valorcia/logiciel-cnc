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
import urllib.parse
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
    ([0, 1, 0], "le flanc arrière"),
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
    # Accentues : ces phrases s'affichent telles quelles a l'operateur, et une
    # interface qui ecrit « surelevez » a quelqu'un qui n'est pas developpeur
    # a l'air cassee. Le test suit la forme affichee, pas une forme interne.
    verbes = ("prenez", "sortez", "surélevez", "rapprochez", "retourner",
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


@pytest.fixture()
def televerser(tmp_path):
    """Poste un corps BRUT sur ``/api/televerser``, en-tete de nom compris.

    ``taille_annoncee`` permet d'annoncer une taille differente de celle des
    octets reellement envoyes : c'est le seul moyen de verifier que le serveur
    decide AVANT de lire.
    """
    import http.client

    srv = servir(0, travail=tmp_path / "u")
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def poster(nom, donnees, *, taille_annoncee=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        c.putrequest("POST", "/api/televerser")
        c.putheader("X-Fichier", urllib.parse.quote(nom))
        c.putheader("Content-Length",
                    str(len(donnees) if taille_annoncee is None
                        else taille_annoncee))
        c.endheaders()
        if donnees:
            c.send(donnees)
        r = c.getresponse()
        corps = json.loads(r.read().decode("utf-8"))
        c.close()
        return r.status, corps

    yield poster
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
    assert "échantillon" in joint
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
    assert "surélevez" in surf.consigne.lower() or "posez" in surf.consigne.lower()


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


# ------------------------------------------- le fichier de l'operateur (M12b)

def test_an_uploaded_name_never_reaches_the_disk_as_it_arrived(tmp_path, corpus_dir):
    """Le nom vient de la machine de quelqu'un d'autre — cle USB, piece jointe.

    Un nom recu de l'exterieur et repris tel quel pour ecrire un fichier est
    exactement la faute qu'on commet en se disant « c'est local, donc c'est
    sans risque ». Le serveur n'ecoute que la boucle locale, et « local »
    n'est pas une politique de securite.
    """
    s = Session()
    d = tmp_path / "recu"
    s.televerser("../../../etc/C01\x00 bloc.step",
                 (corpus_dir / "C01_bloc_simple.step").read_bytes(), d)
    assert s.piece_chargee, s.erreur
    ecrits = list(d.iterdir())
    assert len(ecrits) == 1
    assert ecrits[0].parent == d, "le fichier est sorti de son dossier"
    assert ".." not in ecrits[0].name and "\x00" not in ecrits[0].name
    assert s.origine == "votre fichier"


@pytest.mark.parametrize("nom,donnees,attendu", [
    ("notice.txt", b"bonjour", "STEP"),
    ("vide.step", b"", "vide"),
    ("enorme.step", None, "trop gros"),
])
def test_a_rejected_upload_says_what_to_do(tmp_path, nom, donnees, attendu):
    """Un refus qui ne dit pas quoi faire laisse quelqu'un devant un constat
    sans suite — la seule chose qu'un refus ne doit jamais faire."""
    from xyzac.ui.atelier.session import TAILLE_MAX

    s = Session()
    if donnees is None:
        donnees = b"x" * (TAILLE_MAX + 1)
    s.televerser(nom, donnees, tmp_path / "recu")
    assert not s.piece_chargee
    assert attendu in s.erreur, s.erreur
    assert not (tmp_path / "recu").exists() or \
        not list((tmp_path / "recu").iterdir()), "un fichier refuse a ete ecrit"


def test_the_upload_route_carries_a_real_part_through(televerser, corpus_dir):
    """Bout en bout par HTTP : corps BRUT, nom dans l'en-tete.

    C'est la forme du corps qui est en cause, donc le client JSON des autres
    tests ne convient pas : il faut poster les octets du fichier tels quels.
    """
    code, etat = televerser("C01_bloc_simple.step",
                            (corpus_dir / "C01_bloc_simple.step").read_bytes())
    assert code == 200, etat
    assert etat["chargee"] and etat["origine"] == "votre fichier"
    assert etat["dimensions"] == "60 x 40 x 20 mm"
    assert not etat["erreur"]


def test_an_upload_bigger_than_the_cap_is_refused_before_being_read(televerser):
    """La taille est verifiee sur ``Content-Length`` AVANT lecture.

    Le test ANNONCE un corps enorme et n'en envoie pas un octet. Un serveur qui
    lirait d'abord et mesurerait ensuite resterait bloque a attendre le corps,
    et le test echouerait par expiration — ce qui est exactement la faute que
    l'on veut interdire : mesurer apres avoir lu laisse n'importe quel envoi
    remplir la memoire du Raspberry Pi, et la borne ne sert qu'apres le mal.
    """
    from xyzac.ui.atelier.session import TAILLE_MAX

    code, corps = televerser("enorme.step", b"",
                             taille_annoncee=TAILLE_MAX + 1)
    assert code == 413, (code, corps)
    assert "trop gros" in corps["erreur"]


# --------------------------------------------------- la simulation d'usinage

def test_the_simulation_note_is_computed_from_the_real_plan():
    """Une phrase qui decrit un manque doit etre calculee depuis l'etat reel,
    pas ecrite : ecrite, elle survit a la disparition du manque."""
    class FauxRapport:
        removed_fraction = 0.42
        unreachable_mm3 = 0.0
        final_removable_mm3 = 0.0
        gouged_voxels = 3

    s = Session()
    s.n_images = 7
    s.film = [{"dans_courses": True}] * 6 + [{"dans_courses": False}]
    s._noter_simulation([(np.zeros((5, 3)), None, None, [0])], FauxRapport())
    assert "1 opération(s)" in s.simulation_note
    assert "42 %" in s.simulation_note
    assert "3 points" in s.simulation_note          # voxels gouges
    assert "1 image(s) sur 7" in s.simulation_note  # hors courses, compte reel
    assert "finition" in s.simulation_note          # ce qui n'est PAS montre


def test_the_simulation_says_when_it_has_nothing_to_show(corpus_dir, tmp_path):
    """Rien plutot qu'une animation de remplacement : une image fausse est pire
    qu'une absence d'image, parce que l'absence se remarque."""
    s = Session()
    s.charger(corpus_dir / "C01_bloc_simple.step")

    class PlanVide:
        operations = []

    s._banc.plan_roughing_preview = lambda **kw: (PlanVide(), None)
    s.occupe = True                       # ce que ``simuler`` aurait pose
    s._simuler(tmp_path / "sim", 4)
    assert s.n_images == 0
    assert "rien à montrer" in s.simulation_note
    assert not s.erreur


# ------------------------------------------------------------- le lancement

def test_the_page_and_the_deposit_refuse_for_the_same_reasons():
    """LE test de ce jalon.

    L'atelier AFFICHE les conditions de lancement ; la passerelle les FAIT
    RESPECTER. Ecrites deux fois, elles auraient fini par diverger — et la
    copie divergente aurait ete celle qu'on lit a l'ecran, donc celle sur
    laquelle quelqu'un se serait fie. Ce test les attache l'une a l'autre.
    """
    from xyzac import production_gate
    from xyzac.linuxcnc_gateway.deposit import DepositRefused, deposit_program

    class SansPorte:
        def require_postprocess(self, h):
            return None

    manquantes = production_gate.manquantes(
        approbation=True, calibration=None,
        destination=production_gate.MATERIEL)
    assert manquantes, "une machine sans calibration ne peut pas etre prete"

    with pytest.raises(DepositRefused) as e:
        deposit_program("G21\nM30\n", "/tmp/jamais-ecrit", target="materiel",
                        safety=SansPorte(), setup_hash="x", calibration=None)
    # le refus rendu par le depot est celui de la PREMIERE condition bloquante
    assert str(e.value) == manquantes[0].refus


def test_the_launch_button_can_never_report_a_machine_as_ready():
    """L'atelier n'a ni approbation ni dossier de calibration : les quatre
    conditions doivent ressortir non remplies. C'est exact, et il n'y a aucune
    raison de l'habiller."""
    s = Session()
    l = s.lancement()
    assert l["possible"] is False
    assert len(l["conditions"]) == 4
    assert all(not c["satisfaite"] for c in l["conditions"])
    for c in l["conditions"]:
        assert c["action"].strip(), c["titre"]
    assert "ne démarre aucun cycle" in l["jamais"]


def test_no_page_file_offers_to_start_a_cycle():
    """La page peut dire LANCER — elle ne doit promettre nulle part de faire
    partir la machine. Verifie sur les trois fichiers servis."""
    for nom in ("index.html", "app.js"):
        texte = (ATELIER / "static" / nom).read_text(encoding="utf-8").lower()
        for interdit in ("depart cycle", "démarrer le cycle", "cycle start",
                         "envoyer a la machine", "envoyer à la machine"):
            assert interdit not in texte, (nom, interdit)


# ---------------------------------------------------------- la vue et l'etat

def test_a_view_is_never_served_for_the_previous_part(serveur, corpus_dir):
    """Les vues etaient nommees d'apres l'angle seul : deux chargements
    rapproches pouvaient servir l'image de la piece PRECEDENTE sous le nom de
    la nouvelle. Une image d'une autre piece est le genre d'erreur qu'on ne
    voit pas — elle ressemble a une image."""
    a = json.loads(serveur("/api/piece", {"fichier": "C01_bloc_simple.step"}))
    b = json.loads(serveur("/api/piece", {"fichier": "C02_poche_droite.step"}))
    assert b["revision"] > a["revision"]
    c = json.loads(serveur("/api/reglages", {"diametre_outil": 4}))
    assert c["revision"] > b["revision"], "un reglage doit invalider les vues"


# ----------------------------------------- la simulation bouge vraiment (M12b)

def _rendu_possible() -> bool:
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


rendu = pytest.mark.skipif(not _rendu_possible(), reason="pas de rendu 3D")


@rendu
def test_the_series_camera_does_not_follow_the_tool(corpus_dir):
    """Le cadrage automatique porte sur « piece + brut + OUTIL ».

    C'est le bon cadrage pour UNE image et le mauvais pour une suite : l'outil
    se deplace, donc le cadrage le suit, donc la piece saute d'une image a
    l'autre — et ce saut se lit comme un mouvement de la machine. La camera de
    serie doit donc etre insensible a la position de l'outil.
    """
    import numpy as np

    from xyzac.ui.debug import scene as sc
    from xyzac.ui.debug.state import BenchState

    b = BenchState()
    b.load_step(corpus_dir / "C01_bloc_simple.step")
    b.set_default_tool("ballnose", diameter=6.0, stickout=45.0)

    b.inspect_tcp = np.array([0.0, 0.0, 10.0])
    c1 = sc.camera_serie(b, window_size=(200, 160))
    b.inspect_tcp = np.array([25.0, -18.0, 60.0])
    c2 = sc.camera_serie(b, window_size=(200, 160))
    assert np.allclose(np.asarray(c1, float), np.asarray(c2, float)), (c1, c2)


@rendu
def test_the_simulation_walks_the_tool_along_a_real_toolpath(corpus_dir, tmp_path):
    """Ce que ce jalon promet : l'outil parcourt SA trajectoire.

    Trois choses sont verifiees, parce qu'une seule se satisferait d'un tour de
    manege : les images changent, la pose d'axes changent d'une image a
    l'autre, et les A/C rapportes sont ceux que le PLANNER a choisis — pas des
    valeurs inventees par l'interface.
    """
    from PIL import Image

    s = Session()
    s.charger(corpus_dir / "C01_bloc_simple.step")
    dossier = tmp_path / "sim"
    s.occupe = True                       # ce que ``simuler`` aurait pose
    s._simuler(dossier, 4)
    assert not s.erreur, s.erreur
    assert s.n_images >= 2, s.simulation_note
    assert len(s.film) == s.n_images

    sommes = [int(np.asarray(Image.open(dossier / f"f{i:03d}.png").convert("RGB"),
                             dtype=np.int64).sum())
              for i in range(s.n_images)]
    assert len(set(sommes)) > 1, "toutes les images sont identiques"

    poses = {(f["x"], f["y"], f["z"]) for f in s.film}
    assert len(poses) > 1, "l'outil n'a pas bouge"

    # Les A/C viennent du plan, pas de l'interface.
    plan_ac = {(round(c.a_deg, 1), round(c.c_deg, 1))
               for c in s._banc.plan_report.chosen}
    film_ac = {(f["a"], f["c"]) for f in s.film}
    assert film_ac <= plan_ac, (film_ac, plan_ac)

    # Et la pose d'inspection du banc est rendue ou elle a ete prise : sinon la
    # vue de l'etape « Regardez » montrerait la machine basculee a la derniere
    # pose de l'ebauche, en contradiction avec la phrase qui l'accompagne.
    assert s._banc.inspect_a_deg == 0.0 and s._banc.inspect_c_deg == 0.0


# ------------------------------------------------- l'installation (M12c)

def test_the_atelier_extra_exists_and_does_not_drag_qt_along():
    """Defaut trouve en repondant a « je fais quoi avec cette commande ? ».

    Le README envoyait installer ``.[viz]``, qui ne contient pas PyVista :
    l'atelier demarrait, la piece se chargeait, et la premiere vue mourait sur
    un ``ModuleNotFoundError`` que seul le terminal montrait. Une consigne
    d'installation fausse se paie exactement la ou l'utilisateur n'a aucun
    moyen de diagnostiquer.

    L'extra doit aussi rester SANS Qt : le serveur est en bibliotheque
    standard et les vues sont rendues hors ecran, donc PySide6 n'y sert a rien
    — et c'est ~200 Mo sur un Raspberry Pi.
    """
    racine = Path(__file__).resolve().parents[1]
    toml = (racine / "pyproject.toml").read_text(encoding="utf-8")
    ligne = next(l for l in toml.splitlines() if l.startswith("atelier ="))
    assert "pyvista" in ligne, ligne
    assert "PySide6" not in ligne and "pyvistaqt" not in ligne, ligne

    readme = (racine / "README.md").read_text(encoding="utf-8")
    i = readme.index("python -m xyzac.ui.atelier")
    avant = readme[:i]
    j = avant.rindex("pip install")
    assert "[atelier]" in avant[j:], avant[j:i]


def test_the_render_check_says_what_to_install(monkeypatch):
    """Un controle qui echoue doit nommer une action.

    ``sys.modules[nom] = None`` fait lever ``ImportError`` a l'import suivant :
    c'est la facon de rejouer une installation incomplete sans en fabriquer
    une.
    """
    import sys

    import xyzac.ui.atelier.session as sess

    monkeypatch.setitem(sys.modules, "pyvista", None)
    monkeypatch.setattr(sess, "_RENDU", [None])
    message = sess.rendu_3d()
    assert message, "une installation sans pyvista doit etre signalee"
    assert "pip install" in message and "[atelier]" in message, message


def test_a_render_failure_reaches_the_page_instead_of_cutting_the_line(serveur):
    """Sans filet, une panne de rendu remontait dans ``http.server``, qui coupe
    la connexion : le navigateur affichait une image vide et ne disait rien.
    Une panne doit se dire la ou on la subit."""
    from xyzac.ui.atelier.server import Atelier

    serveur("/api/piece", {"fichier": "C01_bloc_simple.step"})

    def tombe(*a, **kw):
        raise RuntimeError("pilote graphique absent")

    Atelier.session.vue = tombe
    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            serveur("/api/vue?a=35&e=18")
        assert e.value.code == 500
        corps = json.loads(e.value.read())
        assert corps["erreur"], corps
    finally:
        del Atelier.session.vue


def test_the_state_carries_the_render_verdict_to_the_page():
    """La page doit pouvoir le dire : le terminal ne suffit pas, personne ne
    le regarde une fois le navigateur ouvert."""
    e = Session().etat()
    assert "rendu" in e
    assert isinstance(e["rendu"], str)
