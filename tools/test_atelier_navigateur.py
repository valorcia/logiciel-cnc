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
    page = nav.new_page(viewport={"width": 900, "height": 1100})
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
    fantomes = page.evaluate("""() => [...document.querySelectorAll('[hidden]')]
        .filter(e => e.offsetParent !== null || e.getClientRects().length)
        .map(e => e.id || e.className)""")
    assert not fantomes, f"caches mais visibles : {fantomes}"
    print("   aucun element cache n'est visible :", len(
        page.query_selector_all("[hidden]")), "verifies")

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

    page.get_by_text("Je n'ai pas encore de fichier").click()
    page.select_option("#exemples", "C10_dome_convexe.step")
    page.click("#charger")
    page.wait_for_selector("#piece-info:not([hidden])", timeout=60000)
    page.wait_for_function(
        "document.querySelector('#image').complete && "
        "document.querySelector('#image').naturalWidth > 0", timeout=90000)
    print("3. exemple charge :", page.inner_text("#piece-info").split("\n")[0])
    print("   image affichee :",
          page.eval_on_selector("#image", "e => e.naturalWidth + 'x' + e.naturalHeight"))
    page.screenshot(path=SORTIE / "2-chargee.png", full_page=True)

    av = page.get_attribute("#image", "src")
    page.click("[data-tourne='45']")
    page.wait_for_timeout(3000)
    print("4. rotation :", "l'image a change" if page.get_attribute("#image","src") != av else "IMAGE INCHANGEE")

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
    page.screenshot(path=SORTIE / "3-verdict.png", full_page=True)

    page.click("#simuler")
    page.wait_for_selector("#bloc-simu:not([hidden])", timeout=600000)
    page.wait_for_function(
        "document.querySelector('#film').complete && "
        "document.querySelector('#film').naturalWidth > 0", timeout=60000)
    n_images = int(page.get_attribute("#curseur", "max")) + 1
    print("7. simulation :", n_images, "images")
    print("   pose affichee :", page.inner_text("#film-titre"))
    print("   axes           :", page.inner_text("#axes").replace("\n", " | "))
    page.click("#jouer")
    page.wait_for_timeout(1600)
    print("   lecture :", page.inner_text("#jouer"),
          "| image", page.input_value("#curseur"))
    apres = page.inner_text("#film-titre")
    page.click("#jouer")                          # pause
    print("   la pose suit le film :", apres)
    print("   ce que la simulation NE montre PAS :")
    print("     ", page.inner_text("#simu-note"))

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
    page.locator("#bloc-simu").screenshot(path=SORTIE / "4b-trajectoire.png")

    # --- 8. le bouton LANCER -----------------------------------------------
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
