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
with sync_playwright() as pw:
    chemin_nav = os.environ.get("NAVIGATEUR", "")
    nav = (pw.chromium.launch(executable_path=chemin_nav) if chemin_nav
           else pw.chromium.launch())
    page = nav.new_page(viewport={"width": 900, "height": 1100})
    page.on("console", lambda m: erreurs.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: erreurs.append(f"pageerror: {e}"))
    page.goto("http://127.0.0.1:8792/", wait_until="networkidle")
    page.screenshot(path=SORTIE / "1-accueil.png", full_page=True)
    print("1. accueil :", page.title())
    print("   bouton VERIFIER desactive au depart :",
          page.is_disabled("#verifier"))

    page.select_option("#exemples", "C10_dome_convexe.step")
    page.click("#charger")
    page.wait_for_selector("#piece-info:not([hidden])", timeout=60000)
    page.wait_for_function(
        "document.querySelector('#image').complete && "
        "document.querySelector('#image').naturalWidth > 0", timeout=90000)
    print("2. piece chargee :", page.inner_text("#piece-info").split("\n")[0])
    print("   image affichee :",
          page.eval_on_selector("#image", "e => e.naturalWidth + 'x' + e.naturalHeight"))
    page.screenshot(path=SORTIE / "2-chargee.png", full_page=True)

    av = page.get_attribute("#image", "src")
    page.click("[data-tourne='45']")
    page.wait_for_timeout(3000)
    print("3. rotation :", "l'image a change" if page.get_attribute("#image","src") != av else "IMAGE INCHANGEE")

    page.fill("#r-diametre_outil", "6")
    page.dispatch_event("#r-diametre_outil", "change")
    page.wait_for_timeout(1500)
    print("4. reglage outil -> 3 mm, verdict precedent efface :",
          page.is_hidden("#resultat"))

    page.click("#verifier")
    print("5. verification lancee...")
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
    print("6. simulation :", page.get_attribute("#curseur", "max"), "images")
    page.click("#jouer")
    page.wait_for_timeout(1200)
    print("   lecture :", page.inner_text("#jouer"),
          "| image", page.input_value("#curseur"))
    page.screenshot(path=SORTIE / "4-simulation.png", full_page=True)
    nav.close()

srv.shutdown()
print("\nerreurs console :", erreurs if erreurs else "aucune")


if erreurs:
    raise SystemExit(f"erreurs dans la page : {erreurs}")
print("captures dans", SORTIE)
