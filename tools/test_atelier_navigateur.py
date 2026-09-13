#!/usr/bin/env python3
"""Epreuve de l'atelier dans un VRAI navigateur.

Pourquoi ce fichier existe et n'est pas dans ``tests/`` : il demande
``playwright`` et un navigateur, ce qui ferait de la suite du projet une suite
a dependances lourdes pour un seul fichier. Les tests de ``tests/`` couvrent la
session, le serveur et le langage ; celui-ci couvre ce qu'aucun d'eux ne peut
voir — que la PAGE marche quand on clique dessus.

    pip install playwright && playwright install chromium
    python tools/test_atelier_navigateur.py

Sur une machine ou le navigateur est deja present mais d'une autre revision,
passer son chemin :

    NAVIGATEUR=/chemin/vers/chrome python tools/test_atelier_navigateur.py

Il prend des captures dans ``out/atelier/`` : c'est aussi la façon de montrer
a quoi ressemble l'atelier sans l'ouvrir.
"""

import os, sys, threading, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from playwright.sync_api import sync_playwright
from xyzac.ui.atelier.server import servir

#: Piece d'essai. Les ailettes rapprochees sont le cas difficile du corpus :
#: beaucoup de faces, des passages etroits, et une ebauche qui produit
#: enormement de liaisons.
PIECE = os.environ.get("PIECE", "C05_ailettes_rapprochees.step")

SORTIE = Path(__file__).resolve().parents[1] / "out" / "atelier"
SORTIE.mkdir(parents=True, exist_ok=True)
import tempfile
srv = servir(8792, travail=Path(tempfile.mkdtemp(prefix="atelier-")))
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.4)

erreurs = []
# L'etape 9 COUPE le serveur volontairement : le navigateur signale alors un
# ERR_CONNECTION_REFUSED, qui est le comportement attendu et non un defaut.
# Sans ce drapeau, l'epreuve echouait sur la panne qu'elle provoque elle-meme.
coupure_voulue = [False]


def _console(m):
    if m.type == "error" and not coupure_voulue[0]:
        erreurs.append(m.text)


with sync_playwright() as pw:
    chemin_nav = os.environ.get("NAVIGATEUR", "")
    nav = (pw.chromium.launch(executable_path=chemin_nav) if chemin_nav
           else pw.chromium.launch())
    # ECRAN DE 10 POUCES, la cible reelle : 1280 x 800, moins la barre du
    # navigateur. Eprouver sur une fenetre haute laissait passer exactement ce
    # qu'on veut interdire — une page ou le bouton pour avancer est hors
    # d'atteinte.
    page = nav.new_page(viewport={"width": int(os.environ.get("LARGEUR", 1280)),
                                  "height": int(os.environ.get("HAUTEUR", 740))})
    page.on("console", _console)
    page.on("pageerror", lambda e: erreurs.append(f"pageerror: {e}"))
    page.goto("http://127.0.0.1:8792/", wait_until="networkidle")
    page.screenshot(path=SORTIE / "1-accueil.png", full_page=True)
    print("1. accueil :", page.title())
    print("   bouton VERIFIER desactive au depart :",
          page.is_disabled("#verifier"))

    # RIEN de ce qui porte l'attribut ``hidden`` ne doit etre VISIBLE.
    #
    # Structurel, et c'est le pas le plus utile de cette epreuve : le premier
    # jet verifiait « #coupe:not([hidden]) », c'est-a-dire l'ATTRIBUT. Il
    # passait donc alors que le bandeau « l'atelier est arrete » s'affichait en
    # permanence sur un atelier qui marche — une regle de classe en
    # ``display:flex`` battait ``[hidden]{display:none}`` a specificite egale.
    # Un test qui mesure l'attribut ne mesure pas ce que l'oeil voit.
    def tient_dans_l_ecran(quoi):
        """Le bouton pour avancer doit etre A L'ECRAN, sans defiler.

        C'est l'exigence du 10 pouces, et elle se mesure : on demande au
        navigateur ou se trouve le bouton, et on verifie qu'il est dans la
        fenetre. Verifier que la page « ne defile pas » ne dirait rien — une
        coquille a ``overflow:hidden`` ne defile jamais, meme quand elle coupe
        son contenu.
        """
        h = page.viewport_size["height"]
        for sel in ("#suivant", ".nav-in", ".fil-in"):
            b = page.locator(sel).bounding_box()
            assert b, (quoi, sel, "introuvable")
            assert b["y"] >= 0 and b["y"] + b["height"] <= h + 1, (
                quoi, sel, b, f"hors de l'ecran (hauteur {h})")
        return True

    fantomes = page.evaluate("""() => [...document.querySelectorAll('[hidden]')]
        .filter(e => e.offsetParent !== null || e.getClientRects().length)
        .map(e => e.id || e.className)""")
    assert not fantomes, f"caches mais visibles : {fantomes}"
    print("   aucun element cache n'est visible :", len(
        page.query_selector_all("[hidden]")), "verifies")
    print("   ecran :", page.viewport_size, "— navigation atteignable :",
          tient_dans_l_ecran("accueil"))
    print("   etapes affichees a la fois :",
          page.eval_on_selector_all(".etape.affichee", "l => l.length"))

    # --- 2. le fichier de l'operateur, par le selecteur de fichier ---------
    # Le chemin que quelqu'un empruntera reellement : il a un STEP sur une cle
    # et il le depose. Le corpus sert de fichier « a lui » — ce qui compte est
    # qu'il passe par /api/televerser et non par la liste d'exemples.
    sien = str(sorted((Path(__file__).resolve().parents[1] / "tests" / "corpus"
                       / "step").glob("C02*.step"))[0])
    page.set_input_files("#fichier", sien)
    page.wait_for_selector("#piece-info:not([hidden])", timeout=60000)
    print("2. fichier televerse :", page.inner_text("#piece-info").split("\n")[0])
    assert "votre fichier" in page.inner_text("#piece-info"), \
        "la piece doit etre annoncee comme venant de l'operateur"

    # un fichier qui n'est pas du STEP doit etre refuse en clair, pas en 500
    mauvais = SORTIE / "pas_un_step.txt"
    mauvais.write_text("ceci n'est pas un STEP")
    page.set_input_files("#fichier", str(mauvais))
    page.wait_for_selector("#etape-piece .erreur", timeout=30000)
    print("   refus d'un non-STEP :",
          page.inner_text("#etape-piece .erreur")[:90])

    page.click("[data-fil='etape-piece']")
    page.get_by_text("Je n'ai pas encore de fichier").click()
    page.select_option("#exemples", PIECE)
    page.click("#charger")
    page.wait_for_selector("#piece-info:not([hidden])", timeout=60000)
    page.wait_for_function(
        "document.querySelector('#image').complete && "
        "document.querySelector('#image').naturalWidth > 0", timeout=90000)
    print("3. exemple charge :", page.inner_text("#piece-info").split("\n")[0])
    print("   page ouverte apres chargement :",
          page.eval_on_selector(".etape.affichee", "e => e.id"))
    tient_dans_l_ecran("vue")
    print("   image affichee :",
          page.eval_on_selector("#image", "e => e.naturalWidth + 'x' + e.naturalHeight"))
    page.screenshot(path=SORTIE / "2-chargee.png", full_page=True)

    av = page.get_attribute("#image", "src")
    page.click("[data-tourne='45']")
    page.wait_for_timeout(3000)
    print("4. rotation :", "l'image a change" if page.get_attribute("#image","src") != av else "IMAGE INCHANGEE")

    page.click("#suivant")                    # vers l'etape 3
    tient_dans_l_ecran("verification")
    page.get_by_text("Ma machine n'a pas ces cotes").click()
    page.fill("#r-diametre_outil", "6")
    page.dispatch_event("#r-diametre_outil", "change")
    page.wait_for_timeout(1500)
    print("5. reglage outil -> 3 mm, verdict precedent efface :",
          page.is_hidden("#resultat"))

    page.click("#verifier")
    print("6. verification lancee...")
    page.wait_for_selector("#progres:not([hidden])", timeout=15000)
    t0 = time.time()
    page.wait_for_selector("#resultat:not([hidden])", timeout=600000)
    print(f"   verdict rendu en {time.time()-t0:.0f} s")
    print("   resume :", page.inner_text("#resume"))
    n = page.eval_on_selector_all("#surfaces li", "l => l.length")
    print("   surfaces listees :", n)
    for cl in ("faisable", "a-changer", "impossible"):
        c = page.eval_on_selector_all(f"#surfaces li.{cl}", "l => l.length")
        if c: print(f"     {cl}: {c}")
    # --- 6bis. le verdict est RELIE a la geometrie -------------------------
    # Manque le plus coûteux avant cette etape : le verdict disait « le flanc
    # arriere — a changer » et rien ne montrait de quelle surface il parlait.
    page.wait_for_function(
        "document.querySelector('#image-surface').complete && "
        "document.querySelector('#image-surface').naturalWidth > 0",
        timeout=90000)
    tient_dans_l_ecran("verdict")
    nom0 = page.inner_text("#surface-nom")
    src0 = page.get_attribute("#image-surface", "src")
    choisies = page.eval_on_selector_all("#surfaces li.choisie", "l => l.length")
    print("6bis. surface designee d'office :", nom0, f"({choisies} ligne surlignee)")
    assert choisies == 1, choisies
    page.screenshot(path=SORTIE / "3-verdict.png", full_page=True)

    # on en clique une autre : la vue et le nom doivent suivre
    lignes = page.query_selector_all("#surfaces li")
    autre = next(k for k in range(len(lignes) - 1, -1, -1)
                 if lignes[k].inner_text() != nom0)
    lignes[autre].click()
    page.wait_for_function(
        "document.querySelector('#image-surface').complete && "
        "document.querySelector('#image-surface').naturalWidth > 0",
        timeout=90000)
    nom1 = page.inner_text("#surface-nom")
    assert page.get_attribute("#image-surface", "src") != src0, "la vue n'a pas suivi"
    assert nom1 != nom0, (nom0, nom1)
    assert page.eval_on_selector_all("#surfaces li.choisie", "l => l.length") == 1
    print("      apres un clic sur une autre ligne :", nom1)
    page.locator("#surfaces li.choisie").scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    page.screenshot(path=SORTIE / "3b-surface.png", full_page=True)

    page.get_by_text("Ma machine n'a pas ces cotes").click()   # refermer
    page.click("#suivant")                    # vers l'etape 4
    tient_dans_l_ecran("usinage")
    page.click("#simuler")
    page.wait_for_selector("#bloc-simu:not([hidden])", timeout=600000)
    page.wait_for_function(
        "document.querySelector('#film').complete && "
        "document.querySelector('#film').naturalWidth > 0", timeout=60000)
    n_images = int(page.get_attribute("#curseur", "max")) + 1
    print("7. simulation :", n_images, "images")
    # EXIGENCE du 10 pouces : la vue 3D doit etre ENTIEREMENT visible sans
    # defiler. Le premier jet tenait dans l'ecran mais coupait le haut de la
    # scene — « la page ne debord pas » n'est pas « on voit ce qu'on vient
    # regarder ».
    b = page.locator("#bloc-simu .scene img").bounding_box()
    h = page.viewport_size["height"]
    assert b and b["y"] >= 0 and b["y"] + b["height"] <= h + 1, (
        "la vue 3D est coupee", b, h)
    print(f"   vue 3D entierement visible : {b['width']:.0f}x{b['height']:.0f} "
          f"a y={b['y']:.0f} (ecran {h})")
    # et les commandes doivent etre a l'ecran elles aussi : une vue entiere
    # dont le curseur est sous la ligne de flottaison ne se regarde pas.
    for sel in ("#jouer", "#curseur", "#axes", "#simu-resume"):
        bb = page.locator(sel).bounding_box()
        assert bb and bb["y"] + bb["height"] <= h + 1, (sel, bb, h)
    print("   lecteur, axes et reserves a l'ecran : oui")
    print("   pose affichee :", page.inner_text("#film-titre"))
    print("   axes           :", page.inner_text("#axes").replace("\n", " | "))
    page.click("#jouer")
    page.wait_for_timeout(1600)
    print("   lecture :", page.inner_text("#compteur").strip(),
          "| bouton", page.inner_text("#jouer"))
    apres = page.inner_text("#film-titre")
    page.click("#jouer")                          # pause
    print("   la pose suit le film :", apres)
    # La reserve longue est REPLIEE sur un petit ecran : il faut l'ouvrir pour
    # la lire. Sans cela l'epreuve imprimait une ligne vide et n'aurait pas vu
    # une reserve disparue.
    print("   ce qui reste a l'ecran :", page.inner_text("#simu-resume"))
    page.locator("#bloc-note summary").click()
    texte_note = page.inner_text("#simu-note")
    assert texte_note.strip(), "la reserve longue doit rester lisible"
    print("   ce que la simulation NE montre PAS :")
    print("     ", texte_note)
    page.locator("#bloc-note summary").click()

    # On s'arrete EN PLEINE COUPE, et non sur la premiere image : une capture
    # prise a l'image 0 montre l'outil au point de depart, c'est-a-dire la
    # seule image ou il ne se passe rien. La page connait, pour chaque image,
    # si l'outil coupe ou se deplace en rapide — on lui demande.
    milieu = page.evaluate("""() => {
        const coupe = film.images.map((f, i) => [i, f]).filter(([, f]) => f.coupe);
        if (!coupe.length) return Math.floor(film.n / 2);
        return coupe[Math.floor(coupe.length * 0.6)][0];
    }""")
    page.fill("#curseur", str(milieu))
    page.dispatch_event("#curseur", "input")
    page.wait_for_function(
        "document.querySelector('#film').complete && "
        "document.querySelector('#film').naturalWidth > 0", timeout=60000)
    page.wait_for_timeout(400)
    print(f"   capture en pleine coupe : image {milieu} sur {n_images}")
    print("     ", page.inner_text("#film-titre"))
    print("     ", page.inner_text("#axes").replace("\n", " | "))
    page.screenshot(path=SORTIE / "4-simulation.png", full_page=True)
    # ET un gros plan du seul bloc de simulation : sur une page longue, la
    # vignette de la trajectoire est illisible.
    # Le fil d'etapes est ``sticky`` : il se superpose au haut de l'element si
    # l'on capture sans avoir degage la place. La capture montrait alors une
    # barre de navigation en travers de la trajectoire.
    page.locator("#bloc-simu").scroll_into_view_if_needed()
    page.evaluate("window.scrollBy(0, -90)")
    page.wait_for_timeout(300)
    page.locator("#bloc-simu").screenshot(path=SORTIE / "4b-trajectoire.png")

    # --- 8. le bouton LANCER -----------------------------------------------
    page.click("#suivant")                    # vers l'etape 5
    tient_dans_l_ecran("lancement")
    page.click("#lancer")
    page.wait_for_selector("#lancement:not([hidden])", timeout=30000)
    print("8. LANCER :", page.inner_text("#lancement-resume"))
    for li in page.query_selector_all("#conditions li"):
        print("     ", li.inner_text().replace("\n", " — ")[:110])
    page.screenshot(path=SORTIE / "5-lancer.png", full_page=True)

    # --- 9. l'atelier s'arrete : la page doit le DIRE -----------------------
    # Le defaut que ce pas couvre : une page qui reste affichee, boutons
    # bleus, et ne repond plus. Personne ne fait le lien entre « j'ai ferme la
    # fenetre noire » et « la page ne fait plus rien » — ce sont deux objets
    # differents a l'ecran.
    coupure_voulue[0] = True
    srv.shutdown()
    srv.server_close()
    page.locator("#coupe").wait_for(state="visible", timeout=30000)
    print("9. atelier arrete — la page reagit en",
          "moins de 30 s :", page.inner_text("#coupe").split("\n")[0])
    assert page.evaluate("document.body.classList.contains('coupee')"), \
        "les etapes doivent etre grisees quand plus rien ne repond"
    texte = page.inner_text("#coupe")
    assert "demarrer-atelier" in texte, "il faut dire COMMENT repartir"
    print("   consigne donnee :", texte.replace("\n", " ")[-110:])
    # Le bandeau est ``sticky`` : dans une capture pleine page il se dessine a
    # la position de defilement courante, pas en haut de l'image. On remonte
    # d'abord, sinon la capture montre une bande vide la ou l'utilisateur, lui,
    # voit le message.
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(400)
    page.screenshot(path=SORTIE / "6-arrete.png", full_page=True)
    page.locator("#coupe").screenshot(path=SORTIE / "6b-bandeau.png")
    nav.close()

print("\nerreurs console :", erreurs if erreurs else "aucune")


if erreurs:
    raise SystemExit(f"erreurs dans la page : {erreurs}")
print("captures dans", SORTIE)
