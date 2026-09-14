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

    # LES RESULTATS ARRIVENT EN DIRECT. Mesure avant : rien pendant 51 s.
    # La liste, elle, ne depend que des normales et peut s'afficher tout de
    # suite ; les verdicts la remplissent ensuite.
    page.wait_for_selector("#resultat:not([hidden])", timeout=120000)
    t_liste = time.time() - t0
    n_lignes = page.eval_on_selector_all("#surfaces li", "l => l.length")
    print(f"   liste de {n_lignes} surfaces affichee en {t_liste:.1f} s")
    page.wait_for_function(
        "document.querySelectorAll('#surfaces li:not(.en-cours)').length >= 1",
        timeout=180000)
    t_premier = time.time() - t0
    print(f"   premier verdict en {t_premier:.1f} s")
    page.wait_for_function(
        "document.querySelectorAll('#surfaces li:not(.en-cours)').length >= 3",
        timeout=300000)
    print(f"   trois verdicts en {time.time()-t0:.1f} s")
    page.screenshot(path=SORTIE / "3a-en-cours.png", full_page=True)
    assert t_liste < 20, f"la liste doit apparaitre tot, pas en {t_liste:.0f} s"

    page.wait_for_function(
        "document.querySelectorAll('#surfaces li.en-cours').length === 0",
        timeout=600000)
    print(f"   verdict complet en {time.time()-t0:.0f} s")
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

    # --- 6ter. « et avec quel outil, alors ? » -----------------------------
    # Un refus qui ne dit pas quoi commander renvoie l'operateur dans sa CAO.
    bloquantes = [k for k in range(len(lignes))
                  if "usinable" not in lignes[k].inner_text()
                  and "analyse" not in lignes[k].inner_text()]
    assert bloquantes, "la piece d'essai doit avoir des surfaces qui bloquent"
    for k in bloquantes:
        page.query_selector_all("#surfaces li")[k].click()
        page.wait_for_function(
            "!document.querySelector('#surface-diag').classList"
            ".contains('cherche')", timeout=180000)
        nom = page.inner_text("#surface-nom")
        print(f"6ter. {nom}")
        print("      ", page.inner_text("#surface-diag"))
    tient_dans_l_ecran("diagnostic")
    page.locator("#surfaces li.choisie").scroll_into_view_if_needed()
    page.wait_for_timeout(400)
    page.screenshot(path=SORTIE / "3c-diagnostic.png", full_page=True)
    page.locator("#surfaces li.choisie").scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    page.screenshot(path=SORTIE / "3b-surface.png", full_page=True)

    # Le BRIDAGE : declare un etau et verifie que le verdict est jete — le
    # bridage change ce qui est atteignable, contrairement a la matiere.
    assert page.locator("#bloc-bridage").is_visible()
    avant = page.inner_text("#bridage-resume")
    assert "OPTIMISTES" in avant, avant
    page.select_option("#b-forme", "etau")
    page.wait_for_function("() => etat.bridage.forme === 'etau'", timeout=30000)
    assert page.evaluate("() => (etat.surfaces || []).length") == 0, \
        "declarer un bridage doit jeter le verdict : il change l'accessibilite"
    assert "Étau" in page.inner_text("#bridage-resume")
    print("6bis-b. bridage déclaré :", page.inner_text("#bridage-resume"))
    page.locator("#bloc-bridage").screenshot(path=SORTIE / "3d-bridage.png")
    page.select_option("#b-forme", "aucun")   # on repart sans bridage
    page.wait_for_function("() => etat.bridage.forme === 'aucun'", timeout=30000)
    page.click("#verifier")
    page.wait_for_function("() => etat && !etat.occupe && "
                           "(etat.surfaces || []).length > 0", timeout=600000)
    print("        verdict refait apres retour sans bridage :",
          page.evaluate("() => etat.surfaces.length"), "surfaces")

    page.get_by_text("Ma machine n'a pas ces cotes").click()   # refermer
    page.click("#suivant")                    # vers l'etape 4
    tient_dans_l_ecran("usinage")

    # La MATIERE : elle change le temps, pas la faisabilite, et elle a donc sa
    # place ici plutot que dans les cotes de machine. Le verdict ne doit PAS
    # etre invalide par ce changement — le relancer pour un alliage ferait
    # attendre quarante secondes pour rien.
    n_surf = page.evaluate("() => (etat.surfaces || []).length")
    page.select_option("#matiere", "aluminium-6061")
    page.wait_for_function(
        "() => etat.matiere === 'aluminium-6061'", timeout=30000)
    assert page.evaluate("() => (etat.surfaces || []).length") == n_surf, \
        "changer de matiere ne doit pas jeter le verdict"
    print("6quater. matière :", page.evaluate("() => etat.matiere"),
          f"(verdict conservé : {n_surf} surfaces)")

    page.click("#simuler")
    # DEUX issues possibles, et l'epreuve doit accepter les deux. Trouve par
    # cette epreuve elle-meme : sur C05 aucune indexation ne tient dans les
    # courses, donc aucun programme n'est produit et le lecteur n'apparait
    # jamais — l'epreuve attendait dix minutes un element qui ne viendrait pas.
    # Le chemin « aucun programme » n'avait aucune couverture navigateur,
    # c'est-a-dire exactement le chemin ou l'operateur a le plus besoin qu'on
    # lui parle.
    page.wait_for_function(
        "() => !document.querySelector('#bloc-simu').hidden"
        " || !document.querySelector('#sans-simu').hidden", timeout=600000)
    programme = page.locator("#bloc-simu").is_visible()
    if not programme:
        texte = page.inner_text("#sans-simu")
        print("7. AUCUN programme, et la page le dit :")
        print("     ", texte)
        assert texte.strip(), "une absence muette serait pire qu'une absence"
        page.screenshot(path=SORTIE / "4d-sans-programme.png", full_page=True)
        tient_dans_l_ecran("usinage sans programme")

    if programme:
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
        # Le TEMPS, et sa reserve dans le meme souffle. « au moins » fait
        # partie du chiffre : sans lui, quelqu'un organise sa journee sur un
        # minorant.
        assert page.locator("#bloc-duree").is_visible(), \
            "un temps de cycle doit etre affiche quand la matiere est connue"
        t = page.inner_text("#duree-texte")
        print("   temps de cycle :", t, "|", page.inner_text("#duree-part"))
        assert "au moins" in t, t
        note_t = page.evaluate(
            "() => document.querySelector('#duree-note').textContent")
        assert "accélérations" in note_t, note_t
        assert "environ" not in note_t.lower(), note_t
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

        # La FINITION : c'est elle qui fait la piece. Deux issues possibles, et
        # l'epreuve exige l'une ou l'autre — jamais le silence.
        #
        #   * une orientation VERIFIEE existe : l'image de finition doit dire sur
        #     combien de points la verification porte, parce qu'un echantillon
        #     annonce comme une preuve serait une fausse valeur ;
        #   * aucune ne degage dans le montage de depart (cas de C05) : le refus
        #     doit etre NOMME. Une absence muette se lirait comme une simulation
        #     complete, et c'est exactement ce que l'ancienne version faisait — en
        #     animant une orientation qui degageait sur 1 % des points.
        finitions = page.evaluate(
            "() => film.images.map((f, i) => [i, f])"
            ".filter(([, f]) => f.finition).map(([i]) => i)")
        if finitions:
            page.fill("#curseur", str(finitions[len(finitions) // 2]))
            page.dispatch_event("#curseur", "input")
            page.wait_for_function(
                "document.querySelector('#film').complete && "
                "document.querySelector('#film').naturalWidth > 0", timeout=60000)
            page.wait_for_timeout(400)
            titre = page.inner_text("#film-titre")
            print(f"   finition animee ({len(finitions)} images) :", titre)
            assert "Finition" in titre, titre
            assert "vérifiée en" in titre and "répartis sur" in titre, (
                "le titre doit dire la PORTEE de la verification", titre)
            page.locator("#bloc-simu").screenshot(path=SORTIE / "4c-finition.png")
        else:
            court = page.inner_text("#simu-resume")
            page.locator("#bloc-note summary").click()
            longue = page.inner_text("#simu-note")
            page.locator("#bloc-note summary").click()
            assert "sans orientation qui dégage" in court, court
            assert "n'ont pas de finition simulée" in longue, longue
            print("   aucune finition animee, et le refus est nomme :")
            print("     ", court)

        # --- 8. le bouton LANCER -----------------------------------------------
        page.click("#suivant")                    # vers l'etape 5
        tient_dans_l_ecran("lancement")
        page.click("#lancer")
        page.wait_for_selector("#lancement:not([hidden])", timeout=30000)
    print("8. LANCER :", page.inner_text("#lancement-resume"))
    for li in page.query_selector_all("#conditions li"):
        print("     ", li.inner_text().replace("\n", " — ")[:110])
    page.screenshot(path=SORTIE / "5-lancer.png", full_page=True)

    # --- 8bis. la CORRECTION de pose, quand le moteur en propose une --------
    #
    # Le cas mesure : sur C05 aucune indexation ne tient dans les courses — la
    # hauteur de la piece se paie en course Y des que le berceau bascule — et
    # aucun programme n'est produit. Le moteur calcule le decalage qui
    # rattraperait ça (-6,0 mm en Z), et l'atelier doit l'OFFRIR : un decalage
    # au dixieme de millimetre que l'operateur devrait retrouver lui-meme
    # serait le travail qu'on pretend lui enlever.
    #
    # Les deux issues sont eprouvees : bouton present et efficace, ou bloc
    # absent parce qu'il n'y a rien a corriger.
    page.click('[data-fil="etape-simu"]')
    cor = page.evaluate("() => etat.correction && etat.correction.texte")
    if cor:
        print("8bis. correction proposée :", cor)
        assert page.locator("#bloc-correction").is_visible(), \
            "une correction calculée doit être offerte, pas seulement écrite"
        page.locator("#bloc-correction").screenshot(
            path=SORTIE / "5b-correction.png")
        page.click("#corriger")
        page.wait_for_function(
            "() => etat && (etat.decalage_piece || []).some("
            "(v) => Math.abs(v) >= 0.005)", timeout=30000)
        d = page.evaluate("() => etat.decalage_piece")
        print("      pièce reposée de", d)
        # la pose est un fait PERMANENT du montage : elle s'affiche dans la
        # fiche de la piece, pas dans un message qui disparait
        fiche = page.inner_text("#piece-info")
        assert "reposée" in fiche, fiche
        # et le verdict precedent est parti : il portait sur l'ancienne pose
        assert page.evaluate("() => (etat.surfaces || []).length") == 0
        page.screenshot(path=SORTIE / "5c-reposee.png", full_page=True)
    else:
        print("8bis. aucune correction à proposer (toutes les indexations "
              "retenues tiennent dans les courses)")
        assert not page.locator("#bloc-correction").is_visible()

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
