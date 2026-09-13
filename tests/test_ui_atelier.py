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
    assert b":root{" in serveur("/style.css")


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


# ---------------------------------------------------- les lanceurs (M12c)

def test_the_double_click_launchers_only_delegate():
    """Les lanceurs ne doivent porter AUCUNE logique.

    Un ``.bat`` ne s'eprouve pas sur une machine Linux, et un ``.command``
    ne s'eprouve pas sur Windows. S'ils installaient eux-memes, la moitie de ce
    que recoit l'utilisateur ne serait jamais essayee. Ils se contentent donc
    de trouver Python et de passer la main a ``tools/demarrer_atelier.py``, qui
    est le meme partout — et qui, lui, est execute ici.
    """
    racine = Path(__file__).resolve().parents[1]
    for nom in ("demarrer-atelier.bat", "demarrer-atelier.command"):
        f = racine / nom
        assert f.is_file(), nom
        texte = f.read_text(encoding="utf-8")
        assert "demarrer_atelier.py" in texte, nom
        # On cherche la logique EXECUTEE, pas le mot. Le premier jet
        # interdisait la chaine « venv », et tombait sur « sudo apt install
        # python3-venv » dans un message d'aide — un motif large qui ramasse
        # un element qu'il ne possede pas, pour la deuxieme fois dans ce
        # fichier.
        for appel in ("-m venv", "-m pip", "pip install", "make_corpus"):
            assert appel not in texte, (nom, appel)


def test_the_starter_installs_the_extra_the_readme_names():
    """Le lanceur et le README doivent installer la MEME chose. Deux chemins
    d'installation qui divergent, c'est un utilisateur sur deux qui tombe."""
    racine = Path(__file__).resolve().parents[1]
    starter = (racine / "tools" / "demarrer_atelier.py").read_text(encoding="utf-8")
    assert "[atelier]" in starter
    assert "PySide6" not in starter and "[ui]" not in starter


def test_the_starter_needs_nothing_but_the_standard_library():
    """Il tourne AVANT l'installation : s'il importait numpy, il ne pourrait
    pas s'executer sur la machine ou il doit justement installer numpy."""
    racine = Path(__file__).resolve().parents[1]
    arbre = ast.parse((racine / "tools" / "demarrer_atelier.py")
                      .read_text(encoding="utf-8"))
    import sys as _sys

    for n in ast.walk(arbre):
        noms = ([a.name for a in n.names] if isinstance(n, ast.Import)
                else [n.module] if isinstance(n, ast.ImportFrom) and n.module
                else [])
        for nom in noms:
            racine_module = nom.split(".")[0]
            assert racine_module in _sys.stdlib_module_names, nom


def test_the_starter_only_names_python_versions_with_ready_made_wheels():
    """Mesure faite sur PyPI, pas supposee : cadquery-ocp ne publie pas de roue
    pour n'importe quelle version, et sans roue il faudrait compiler OCCT."""
    from tools_import_demarrer import VERSIONS_SURES

    assert (3, 11) in VERSIONS_SURES
    assert (3, 14) in VERSIONS_SURES, (
        "mesure sur une installation reelle sous Windows 11 : cp314 existe "
        "pour toutes les dependances, donc avertir etait faux")
    assert all(v >= (3, 11) for v in VERSIONS_SURES)


def test_the_starter_keeps_a_log_that_survives_the_window_closing(monkeypatch,
                                                                  tmp_path):
    """Defaut rapporte depuis une vraie machine Windows : « il dit appuyer sur
    une touche pour continuer puis plus rien ».

    Une fenetre lancee au double-clic se referme des qu'on appuie sur une
    touche, et elle emporte le message. L'utilisateur ne peut alors meme pas
    dire ce qui s'est passe — la panne devient indiagnosticable, ce qui est
    pire que la panne. Le journal survit a la fermeture.
    """
    import tools_import_demarrer as passerelle

    m = passerelle.module
    journal = tmp_path / "demarrage.log"
    monkeypatch.setattr(m, "JOURNAL", journal)

    m.ouvrir_journal()
    m.dire("quelque chose s'est passe")
    texte = journal.read_text(encoding="utf-8")

    import platform
    import sys

    assert "quelque chose s'est passe" in texte
    # l'entete doit porter ce qu'on demanderait de toute facon en premier
    assert platform.platform() in texte
    assert sys.version.splitlines()[0] in texte


def test_the_log_never_breaks_the_start(monkeypatch, tmp_path):
    """Un journal qu'on n'arrive pas a ecrire ne doit pas empecher de demarrer :
    il sert a expliquer une panne, pas a en creer une."""
    import tools_import_demarrer as passerelle

    m = passerelle.module
    monkeypatch.setattr(m, "JOURNAL", tmp_path / "absent" / "x" / "y.log")
    m.dire("ceci ne doit pas lever")          # le dossier parent n'existe pas


def test_the_windows_launcher_points_at_the_log():
    """Le message qui reste a l'ecran juste avant que la fenetre se ferme doit
    dire ou retrouver ce qu'elle emporte."""
    racine = Path(__file__).resolve().parents[1]
    bat = (racine / "demarrer-atelier.bat").read_text(encoding="utf-8")
    assert "demarrage.log" in bat


def test_an_already_used_port_is_explained_not_dumped(monkeypatch, capsys):
    """Arrive des qu'on double-clique deux fois. Sans filet, l'utilisateur
    recoit « OSError: [Errno 98] Address already in use » et dix lignes de
    trace, pour une situation qui n'a rien d'anormal."""
    import sys

    from xyzac.ui.atelier import __main__ as lanceur
    from xyzac.ui.atelier.server import servir

    occupe = servir(0)
    port = occupe.server_address[1]
    try:
        monkeypatch.setattr(sys, "argv",
                            ["atelier", "--port", str(port), "--sans-navigateur"])
        code = lanceur.main()            # ne doit PAS lever
    finally:
        occupe.server_close()

    assert code == 2
    sortie = capsys.readouterr().out
    assert "Traceback" not in sortie
    assert f"http://127.0.0.1:{port}/" in sortie, "il faut dire quoi essayer"
    assert f"--port {port + 1}" in sortie, "il faut dire comment en lancer un autre"


def test_a_workshop_that_never_started_is_not_called_stopped(capsys):
    """Defaut rapporte depuis une vraie machine : l'atelier ne s'ouvrait pas,
    et le lanceur repondait « La page de votre navigateur ne repond plus ».

    Cette phrase est fausse pour quelqu'un qui n'a jamais eu de page, et elle
    poussait la vraie raison hors de l'ecran. Un arret NORMAL, c'est un atelier
    qui a d'abord TOURNE ; un processus qui se termine en une demi-seconde n'a
    pas ete arrete, il n'a pas demarre.
    """
    import tools_import_demarrer as passerelle

    m = passerelle.module
    assert m.DUREE_MINIMALE > 0

    m.rapporter_echec(2, 0.2, ["Le port 8765 est deja occupe."])
    sortie = capsys.readouterr().out
    assert "PAS LANCE" in sortie
    assert "ne repond plus" not in sortie
    # la raison doit etre REMONTREE : le temps qu'on lise, elle a defile
    assert "Le port 8765 est deja occupe." in sortie
    assert "demarrage.log" in sortie


def test_retrying_after_a_failure_is_not_the_default(monkeypatch):
    """Relancer a l'identique ce qui vient de ne pas marcher n'a aucune raison
    de marcher. Proposer « oui » par defaut enverrait tourner en rond."""
    import tools_import_demarrer as passerelle

    m = passerelle.module

    class FauxClavier:
        @staticmethod
        def isatty():
            return True

    monkeypatch.setattr(m.sys, "stdin", FauxClavier)
    monkeypatch.setattr("builtins.input", lambda _: "")     # touche Entree

    assert m.relancer(anormal=False) is True, "apres un arret normal, oui"
    assert m.relancer(anormal=True) is False, "apres un echec, non"


def test_nothing_is_asked_when_no_one_can_answer(monkeypatch):
    """Une invite sans clavier derriere bloque pour toujours : c'est la pire
    facon d'echouer."""
    import tools_import_demarrer as passerelle

    m = passerelle.module

    class SansClavier:
        @staticmethod
        def isatty():
            return False

    monkeypatch.setattr(m.sys, "stdin", SansClavier)
    monkeypatch.setattr("builtins.input",
                        lambda _: pytest.fail("rien ne doit etre demande"))
    assert m.relancer() is False
    assert m.relancer(anormal=True) is False


# --------------------------------------- l'affichage 3D selon le systeme

@pytest.mark.parametrize("plateforme,environnement,attendu", [
    ("win32", {}, False),
    ("darwin", {}, False),
    ("linux", {}, True),
    ("linux", {"DISPLAY": ":0"}, False),
    ("linux", {"WAYLAND_DISPLAY": "wayland-0"}, False),
])
def test_software_rendering_is_only_forced_on_linux(plateforme, environnement,
                                                    attendu):
    """Defaut trouve en cassant l'atelier sur la machine de quelqu'un d'autre.

    ``DISPLAY`` et ``WAYLAND_DISPLAY`` sont des variables X11 et Wayland :
    elles n'existent pas sous Windows ni sous macOS. « Pas de DISPLAY donc pas
    d'ecran » y est donc TOUJOURS vrai, et le rendu logiciel s'y trouvait force
    sur toutes les machines — or osmesa.dll n'est pas livre avec Windows.
    Violation d'acces memoire au demarrage (code 3221225477), sur un poste qui
    a pourtant un ecran.

    Une absence de variable X11 mesure l'absence de X11, pas l'absence
    d'ecran. Les deux coincident sur Linux et nulle part ailleurs.
    """
    from xyzac.ui.atelier.__main__ import rendu_logiciel

    assert rendu_logiciel(plateforme, environnement) is attendu


def _faux_essai(code=0, sortie="", erreur=""):
    class R:
        returncode = code
        stdout = sortie
        stderr = erreur
    return lambda *a, **kw: R()


@pytest.mark.parametrize("code,sortie,attendu", [
    (1, "ModuleNotFoundError: No module named 'pyvista'", "pip install"),
    (1, "ModuleNotFoundError: No module named 'pyvista'", "[atelier]"),
    (3221225477, "osmesa.dll not found", "VTK_DEFAULT_OPENGL_WINDOW"),
    (3221225477, "", "pilote"),
    (1, "RuntimeError: quelque chose", "quelque chose"),
])
def test_a_render_crash_becomes_a_sentence(monkeypatch, code, sortie, attendu):
    """Le pilote graphique est du code natif : il ne leve pas d'exception, il
    fait TOMBER le processus. Le controle tourne donc dans un processus a part,
    ou le meme plantage devient un code de retour — donc une phrase.

    Un controle qui tue le programme qu'il controle ne controle plus rien.
    """
    import xyzac.ui.atelier.session as sess

    monkeypatch.setattr(sess.subprocess, "run", _faux_essai(code, sortie))
    monkeypatch.setattr(sess, "_RENDU", [None])
    message = sess.rendu_3d()
    assert message, "un echec doit etre signale"
    assert attendu in message, message


def test_a_working_render_reports_nothing(monkeypatch):
    """Et le cas qui marche ne doit rien inventer : le controle s'appuie sur un
    temoin ECRIT par la sonde, pas sur le seul code de retour — un processus
    peut sortir a zero sans avoir rien dessine."""
    import xyzac.ui.atelier.session as sess

    monkeypatch.setattr(sess.subprocess, "run", _faux_essai(0, "RENDU-OK\n"))
    monkeypatch.setattr(sess, "_RENDU", [None])
    assert sess.rendu_3d() == ""

    monkeypatch.setattr(sess.subprocess, "run", _faux_essai(0, "rien du tout"))
    monkeypatch.setattr(sess, "_RENDU", [None])
    assert sess.rendu_3d() != "", "sortir a zero sans image n'est pas un succes"


def test_the_quoted_failure_lines_reach_the_log(monkeypatch, tmp_path, capsys):
    """Le premier journal recu d'une vraie machine s'arretait a « Les dernieres
    lignes qu'il a ecrites : » suivi de RIEN : les lignes citees partaient a
    l'ecran sans passer par le journal. La partie la plus utile du rapport
    etait exactement celle qui ne survivait pas a la fermeture de la fenetre."""
    import tools_import_demarrer as passerelle

    m = passerelle.module
    journal = tmp_path / "d.log"
    monkeypatch.setattr(m, "JOURNAL", journal)
    m.rapporter_echec(3221225477, 12.0, ["osmesa.dll not found"])
    assert "osmesa.dll not found" in journal.read_text(encoding="utf-8")


def test_a_real_native_crash_does_not_take_the_workshop_down(monkeypatch):
    """L'isolement est eprouve par un VRAI plantage, pas par une imitation.

    ``os.abort()`` dans le processus fils fait ce que fait un pilote graphique
    defaillant : il tombe, sans exception Python. Si la sonde tournait encore
    dans le processus courant, ce test ferait tomber pytest — ce qui est
    exactement ce qui est arrive a l'atelier sur une machine Windows.

    Verifier avec un ``subprocess.run`` simule aurait mesure la simulation.
    """
    import xyzac.ui.atelier.session as sess

    monkeypatch.setattr(sess, "_SONDE", "import os; os.abort()")
    monkeypatch.setattr(sess, "_RENDU", [None])

    message = sess.rendu_3d()                 # ne doit PAS tuer ce processus
    assert message, "un plantage doit etre signale"
    assert "pilote" in message, message
    # et on est toujours vivant pour le dire
    assert sess.rendu_3d() == message


# ------------------------------------------------------- le code couleur

def test_the_legend_comes_from_the_single_colour_source():
    """La legende de la vue 3D ne doit pas etre recopiee dans l'interface.

    ``ui.debug.palette`` est l'unique source du code couleur. Une deuxieme
    liste de teintes dans la feuille de style ou dans le JavaScript aurait
    fini par diverger — et c'est la copie AFFICHEE qui aurait menti, donc
    celle sur laquelle quelqu'un se serait fie pour lire une image.

    Manque signale a la relecture des captures : rien a l'ecran ne disait
    « bleu = le brut ». Une image qu'il faut se faire expliquer n'informe pas.
    """
    from xyzac.ui.atelier.session import legende
    from xyzac.ui.debug import palette

    entrees = legende()
    assert entrees, "la legende ne doit pas etre vide"
    connues = ({palette.PART, palette.STOCK, palette.PATH, palette.WARNING,
                palette.MACHINE} | set(palette.TOOL_ROLE.values()))
    for e in entrees:
        assert e["couleur"] in connues, e
        assert e["nom"] and e["nom"][0].islower(), e

    # et aucune teinte en dur dans les fichiers de la page
    for nom in ("style.css", "app.js"):
        texte = (ATELIER / "static" / nom).read_text(encoding="utf-8")
        for teinte in connues:
            assert teinte.lower() not in texte.lower(), (nom, teinte)


def test_every_word_shown_to_the_operator_is_accented():
    """Une interface francaise qui ecrit « la piece finie » a quelqu'un qui
    n'est pas developpeur a l'air cassee.

    Ne porte que sur les textes RENDUS a l'ecran, pas sur les commentaires ni
    les noms de champs : le code du projet est volontairement sans accents.
    """
    from xyzac.ui.atelier.session import REMEDES, Session, legende

    a_verifier = [e["nom"] for e in legende()]
    a_verifier += list(REMEDES.values())
    a_verifier += [Session().lancement()["jamais"]]
    for c in Session().lancement()["conditions"]:
        a_verifier += [c["titre"], c["action"]]

    suspects = []
    for phrase in a_verifier:
        for mot in ("piece", "arete", "deplacement", "etre", "mesures",
                    "geometrique", "complete", "qualifiee", "epreuve",
                    "executer", "cinematique", "etapes", "securite",
                    "demarre", "meme", "ecrit", "operateur", "reduit"):
            if mot in phrase.lower().split() or f" {mot} " in f" {phrase.lower()} ":
                suspects.append((mot, phrase[:60]))
    assert not suspects, suspects


@rendu
def test_tightening_the_frame_actually_moves_the_camera(corpus_dir):
    """Defaut trouve en comparant deux images censees differer.

    Le premier jet resserrait par ``plotter.camera.zoom()``. Or ``zoom()``
    agit sur l'ANGLE DE VUE, que ``camera_position`` ne transporte pas : le
    parametre etait sans effet, et deux cadrages differents rendaient deux
    images identiques au pixel. Un parametre qui ne fait rien est un mensonge,
    et celui-la se serait tu.

    Le resserrage rapproche donc la camera de son point vise, ce qui SE VOIT
    dans la position rendue.
    """
    import numpy as np

    from xyzac.ui.debug import scene as sc
    from xyzac.ui.debug.state import BenchState

    b = BenchState()
    b.load_step(corpus_dir / "C01_bloc_simple.step")
    b.set_default_tool("ballnose", diameter=6.0, stickout=45.0)

    large = sc.camera_serie(b, window_size=(200, 160))
    serre = sc.camera_serie(b, window_size=(200, 160), zoom=1.6)

    cible = np.asarray(large[1], float)
    assert np.allclose(cible, np.asarray(serre[1], float)), (
        "le point vise ne doit pas bouger")
    d_large = np.linalg.norm(np.asarray(large[0], float) - cible)
    d_serre = np.linalg.norm(np.asarray(serre[0], float) - cible)
    assert d_serre < d_large * 0.7, (d_large, d_serre)


def test_the_atelier_frames_every_corpus_part_without_cutting_it():
    """Le resserrage est verifie sur le corpus, pas suppose.

    Ce test protege le CHIFFRE (``ZOOM_3D``), pas le rendu : le relever sans
    regarder ferait sortir la piece du cadre aux poses basculees, et personne
    ne s'en apercevrait avant de voir une capture.
    """
    from xyzac.ui.atelier.session import ZOOM_3D

    assert 1.0 <= ZOOM_3D <= 1.6, (
        "au-dela de 1,6 la piece sort du cadre aux poses basculees ; "
        "mesure sur les deux poses extremes d'une gamme")


# --------------------------------------------- l'ecran de 10 pouces (M12d)

def test_the_page_shows_one_step_at_a_time():
    """L'atelier tourne sur un ecran de 10 pouces.

    Cinq cartes empilees y donnaient une page de 5 000 pixels de haut dont
    quatre cinquiemes etaient inaccessibles — et la barre pour avancer se
    retrouvait hors de portee. Les etapes sont donc des PAGES : une seule
    affichee, les autres absentes.
    """
    html = (ATELIER / "static" / "index.html").read_text(encoding="utf-8")
    js = (ATELIER / "static" / "app.js").read_text(encoding="utf-8")
    css = (ATELIER / "static" / "style.css").read_text(encoding="utf-8")

    # La coquille est fixe et UNE SEULE zone defile. Verifie sur les
    # declarations, espaces retires — une assertion qui se rattrape par des
    # remplacements de chaine n'est plus une assertion.
    compact = "".join(css.split())
    assert "overflow:hidden" in compact, "le corps ne doit pas defiler"
    i = compact.index("main{")
    bloc_main = compact[i:compact.index("}", i)]
    assert "overflow-y:auto" in bloc_main, bloc_main

    # une etape n'est visible que si elle porte la classe
    assert ".etape{display:none" in css
    assert ".etape.affichee{display:block}" in css

    # la navigation existe dans les deux sens, et le fil est cliquable
    for sel in ('id="precedent"', 'id="suivant"', 'class="nav-bas"'):
        assert sel in html, sel
    assert "allerA" in js
    # les onglets sont des boutons et non des ancres : une ancre ferait
    # defiler une page qui ne defile pas
    assert 'href="#etape-' not in html


def test_the_part_summary_survives_moving_between_pages():
    """Defaut trouve en paginant : la fiche de la piece vivait dans la premiere
    page, donc elle disparaissait des qu'on avancait. Savoir quelle piece est
    chargee vaut a CHAQUE etape — c'est meme la seule information qui vaut sur
    les cinq."""
    html = (ATELIER / "static" / "index.html").read_text(encoding="utf-8")
    i_fiche = html.index('id="piece-info"')
    i_main = html.index("<main")
    assert i_fiche < i_main, "la fiche doit etre hors des pages"


def test_the_long_caveat_keeps_a_visible_short_form():
    """La reserve longue est repliee sur un petit ecran — mais ce qui CHANGE
    une decision reste a l'ecran. Deux champs et non une phrase tronquee : une
    reserve coupee en deux ne se lit plus."""
    class FauxRapport:
        removed_fraction = 0.6
        unreachable_mm3 = 0.0
        final_removable_mm3 = 0.0
        gouged_voxels = 0

    s = Session()
    s.n_images = 36
    s.film = [{"dans_courses": False}] * 16 + [{"dans_courses": True}] * 20
    s._noter_simulation([(np.zeros((5, 3)), None, None, [0])], FauxRapport())

    assert s.simulation_resume, "il faut une forme courte"
    assert len(s.simulation_resume) < len(s.simulation_note) / 2
    assert "60 %" in s.simulation_resume
    assert "16 image(s) sur 36" in s.simulation_resume
    # et la forme longue garde ce que la courte laisse tomber
    assert "finition" in s.simulation_note
    assert "finition" not in s.simulation_resume
