"""La fiche de la machine : toutes ses cotes, et D'OU chacune vient.

La machine n'existe pas encore. Le jour ou elle sera montee, quelqu'un devra
mesurer ses cotes et les dire au logiciel. Ces tests portent sur la seule
chose qui rend cet ecran utile plutot que decoratif : taper une valeur ne la
rend pas mesuree.
"""

import json

import pytest

from xyzac.machine_model.fiche import (CALIBRE, CRITIQUES, ESSAI, GROUPES,
                                       MESURE, PLAN,
                                       RESERVEES_A_LA_CALIBRATION,
                                       FicheMachine, parametres_du_kit)


def test_a_typed_value_is_a_try_not_a_measurement():
    """La regle du module, et la seule qui le rende honnete.

    Sans elle, un operateur presse tape les cotes du plan, l'ecran affiche
    « mesuré », et plus personne — lui le premier — ne sait ce que les
    verdicts valent. Le projet interdit ailleurs d'annoncer ±0,02 mm comme
    acquis ; la meme interdiction vaut pour 250 mm de bras.
    """
    f = FicheMachine.du_kit()
    assert f["delta_longueur_bras_mm"].provenance == PLAN

    f.regler("delta_longueur_bras_mm", 248.7)
    p = f["delta_longueur_bras_mm"]
    assert p.valeur == pytest.approx(248.7)
    assert p.provenance == ESSAI, "une valeur tapée reste un essai"
    assert not p.suffisante
    assert p.moyen == ""


def test_a_measurement_must_name_what_measured_it():
    """« Mesuré » sans dire avec quoi ne vaut pas mieux qu'un essai.

    Le laisser passer rendrait la provenance decorative : il suffirait de
    cocher une case pour transformer une cote du plan en fait.
    """
    f = FicheMachine.du_kit()
    with pytest.raises(ValueError, match="avec QUOI"):
        f.mesurer("delta_longueur_bras_mm", 248.7, moyen="   ")

    p = f.mesurer("delta_longueur_bras_mm", 248.7,
                  moyen="pied à coulisse Mitutoyo", incertitude=0.05)
    assert p.provenance == MESURE and p.suffisante
    assert "Mitutoyo" in p.moyen
    assert p.date_mesure, "une mesure porte sa date"
    assert "± 0.05 mm" in p.describe()


def test_a_pivot_cannot_be_measured_by_hand():
    """Un pivot ne se releve pas au pied a coulisse.

    Il s'ajuste sur un cercle palpe, et pretendre l'avoir mesure autrement
    serait annoncer une precision qu'on n'a pas. Ces cotes restent saisissables
    — on peut vouloir essayer « et si le pivot etait la ? » — mais la saisie
    les marque ESSAI.
    """
    f = FicheMachine.du_kit()
    with pytest.raises(ValueError, match="calibration"):
        f.mesurer("pivot_a_z_mm", -38.4, moyen="pied à coulisse")

    # saisissable, mais jamais « mesurée »
    assert f.regler("pivot_a_z_mm", -38.4).provenance == ESSAI
    # seule la calibration l'atteste
    p = f.calibrer("pivot_a_z_mm", -38.412, procedure="ROTARY_AC",
                   incertitude=0.004)
    assert p.provenance == CALIBRE and p.suffisante
    for cle in RESERVEES_A_LA_CALIBRATION:
        assert cle in f.parametres, cle


def test_an_implausible_value_is_refused_with_its_bounds():
    """La virgule oubliee : 2 500 mm de bras au lieu de 250.

    Les bornes ne disent pas « votre machine doit etre comme la notre » —
    elles attrapent la faute de frappe, et elles disent laquelle.
    """
    f = FicheMachine.du_kit()
    with pytest.raises(ValueError, match="hors des bornes"):
        f.regler("delta_longueur_bras_mm", 2500.0)
    assert f["delta_longueur_bras_mm"].valeur == 250.0, "rien n'a bougé"


def test_the_summary_counts_what_rests_on_a_measurement_not_what_is_filled():
    """« 46 cotes renseignées » ne veut rien dire : elles le sont toutes.

    Le chiffre qui compte est combien reposent sur autre chose qu'un dessin.
    """
    f = FicheMachine.du_kit()
    r = f.resume()
    assert "Aucune" in r and "plan" in r
    assert "DESSINÉE" in r

    for cle in CRITIQUES:
        if cle in RESERVEES_A_LA_CALIBRATION:
            f.calibrer(cle, f.valeur(cle), procedure="ROTARY_AC")
        else:
            f.mesurer(cle, f.valeur(cle), moyen="pied à coulisse")
    assert f.mesuree
    assert "toutes les cotes critiques" in f.resume()


def test_the_sheet_survives_a_restart_and_keeps_the_code_s_words():
    """Ce qui est mesuré ne doit pas se retaper à chaque lancement.

    Mais seules la valeur et la provenance viennent du fichier : les libelles,
    les bornes et les phrases de mesure viennent du code. Une fiche
    enregistree il y a six mois profite donc des corrections apportees depuis,
    au lieu de figer un texte faux.
    """
    import tempfile
    from pathlib import Path

    f = FicheMachine.du_kit()
    f.nom = "Delta n°1"
    f.mesurer("delta_longueur_bras_mm", 248.7, moyen="pied à coulisse")
    with tempfile.TemporaryDirectory() as d:
        chemin = Path(d) / "machine.json"
        f.enregistrer(chemin)
        # lisible a l'oeil : le jour ou quelque chose cloche, on doit pouvoir
        # l'ouvrir dans un Bloc-notes
        brut = json.loads(chemin.read_text(encoding="utf-8"))
        assert brut["cotes"]["delta_longueur_bras_mm"]["provenance"] == MESURE

        g = FicheMachine.charger(chemin)
    assert g.nom == "Delta n°1"
    assert g.valeur("delta_longueur_bras_mm") == pytest.approx(248.7)
    assert g["delta_longueur_bras_mm"].provenance == MESURE
    # le texte vient du code, pas du fichier
    assert g["delta_longueur_bras_mm"].comment_mesurer == \
        f["delta_longueur_bras_mm"].comment_mesurer
    # une cote absente du fichier garde sa valeur de plan
    assert g["broche_rpm_max"].provenance == PLAN


def test_an_unknown_key_in_the_file_is_ignored_rather_than_fatal():
    """Le fichier peut venir d'une version plus recente du logiciel.

    Refuser de demarrer parce qu'une cote inconnue traine serait punir
    l'utilisateur d'avoir essaye une mise a jour.
    """
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        chemin = Path(d) / "machine.json"
        chemin.write_text(json.dumps({
            "nom": "Venue du futur",
            "cotes": {"cote_qui_n_existe_pas": {"valeur": 1.0,
                                                "provenance": "mesure"},
                      "delta_rayon_base_mm": {"valeur": 149.2,
                                              "provenance": "essai"}},
        }), encoding="utf-8")
        g = FicheMachine.charger(chemin)
    assert g.valeur("delta_rayon_base_mm") == pytest.approx(149.2)
    assert "cote_qui_n_existe_pas" not in g.parametres


def test_every_parameter_says_how_to_measure_it_and_what_it_changes():
    """C'est ce qui transforme un formulaire en fiche de mise en service.

    Une cote sans phrase de mesure est une cote que personne ne saura
    renseigner le jour du montage — donc une cote qui restera au plan.
    """
    from xyzac.machine_model.fiche import (FAISABILITE, PRECISION, SECURITE,
                                           TEMPS)

    connus = {cle for cle, _ in GROUPES}
    for p in parametres_du_kit():
        assert p.groupe in connus, p.cle
        assert p.effet in (FAISABILITE, TEMPS, PRECISION, SECURITE), p.cle
        assert len(p.comment_mesurer) > 40, p.cle
        assert p.mini < p.maxi, p.cle
        assert p.mini <= p.valeur <= p.maxi, p.cle
        assert p.unite, p.cle


def test_the_machine_built_from_the_sheet_carries_its_own_provenance():
    """La machine construite doit dire sur quoi elle repose.

    Une cinematique delta batie sur des cotes de plan et une batie sur des
    cotes mesurees se ressemblent trait pour trait. La seule difference
    lisible est ce qu'elles DISENT d'elles-memes, et c'est cette phrase qui
    remonte jusqu'aux conditions de lancement.
    """
    f = FicheMachine.du_kit()
    assert "PROVISOIRES" in f.delta().source
    m = f.machine()
    assert "DESSINÉE" in m.description
    assert m.x.min_mm == -f.valeur("course_x_mm")
    assert m.a.min_deg == f.valeur("a_min_deg")
    assert list(m.pivot_a) == [f.valeur("pivot_a_x_mm"),
                               f.valeur("pivot_a_y_mm"),
                               f.valeur("pivot_a_z_mm")]
    # le plateau de collision suit le rayon declare
    cyl = [v for v in m.collision_volumes if v.kind == "cylinder"][0]
    assert cyl.radius == f.valeur("plateau_rayon_mm")

    for cle in CRITIQUES:
        if cle in RESERVEES_A_LA_CALIBRATION:
            f.calibrer(cle, f.valeur(cle), procedure="ROTARY_AC")
        else:
            f.mesurer(cle, f.valeur(cle), moyen="pied à coulisse")
    assert "mesurées" in f.delta().source


def test_safety_is_a_declaration_the_software_never_satisfies_by_itself():
    """Cocher une case n'arrete aucune broche.

    Les organes de securite sont MATERIELS et independants du logiciel par
    construction. Ils sont dans la fiche pour etre CONSTATES, et leur absence
    doit remonter jusqu'au resume — pas y etre passee sous silence.
    """
    f = FicheMachine.du_kit()
    manque = f.securite_declaree()
    assert len(manque) == 3, manque
    assert "Sécurité non déclarée" in f.resume()

    for cle in ("arret_urgence_materiel", "fins_de_course_materielles",
                "capot_interverrouille"):
        f.regler(cle, 1.0)
        assert f.oui(cle)
    assert f.securite_declaree() == []
    assert "Sécurité non déclarée" not in f.resume()


def test_the_cradle_is_a_U_not_a_wall():
    """La forme du berceau decide quelles orientations sont refusees.

    Une seule boite derriere la piece se trompait DEUX fois : elle barrait
    l'arriere, ou la vraie machine ne porte rien, et elle laissait les cotes
    libres, la ou se trouvent les joues. Ce test ne verifie pas une tournure
    de code : il verifie que la matiere declaree est la ou elle est sur le
    dessin de la machine, et nulle part ailleurs.
    """
    f = FicheMachine.du_kit()
    organes = f.organes()
    noms = [v.name for v in organes]
    assert noms.count("joue gauche") == 1 and noms.count("joue droite") == 1
    assert noms.count("moteur A gauche") == 1 and noms.count("moteur A droite") == 1

    demi = f.valeur("berceau_largeur_mm") / 2.0
    joue = f.valeur("berceau_profondeur_mm")
    boites = {v.name: v for v in organes if v.kind == "box"}

    def dedans(v, p):
        return all(v.lo[i] - 1e-9 <= p[i] <= v.hi[i] + 1e-9 for i in range(3))

    # entre les deux joues, la ou la piece est posee : rien.
    for organe in boites.values():
        assert not dedans(organe, [0.0, 0.0, 10.0]), (
            f"{organe.name} occupe la place de la piece")
    # DERRIERE la piece : rien non plus. C'est ce que l'ancien mur barrait.
    for organe in boites.values():
        assert not dedans(organe, [0.0, -88.0, 10.0]), (
            f"{organe.name} barre l'arriere, ou la machine ne porte rien")
    # sur les COTES, en revanche, il y a de la matiere, des deux cotes.
    milieu = demi - joue / 2.0
    assert dedans(boites["joue droite"], [milieu, 0.0, 10.0])
    assert dedans(boites["joue gauche"], [-milieu, 0.0, 10.0])


def test_a_motor_carter_does_not_turn_with_the_part():
    """Le stator est boulonne sur le bati ; seul le rotor tourne.

    Le piege est discret : un carter place dans le repere du berceau basculerait
    avec la piece, donc s'ecarterait tout seul des orientations ou il gene le
    plus — une collision qui disparait precisement quand on en a besoin.
    """
    f = FicheMachine.du_kit()
    organes = {v.name: v for v in f.organes()}
    assert organes["joue droite"].frame == "cradle_A", "une joue tourne avec A"
    assert organes["moteur A droite"].frame == "machine", (
        "un carter de moteur ne tourne pas")
    assert organes["moteur A gauche"].frame == "machine"
    # et le carter est centre sur l'axe A, pas sur le plateau.
    mot = organes["moteur A droite"]
    assert (mot.lo[2] + mot.hi[2]) / 2.0 == pytest.approx(f.valeur("pivot_a_z_mm"))
    assert (mot.lo[1] + mot.hi[1]) / 2.0 == pytest.approx(f.valeur("pivot_a_y_mm"))


def test_a_square_carter_is_a_box_and_not_a_cylinder_of_the_same_diameter():
    """Le carre contient le cercle, et non l'inverse.

    Un carter NEMA 17 de 42 mm de cote modelise par un cylindre de 42 mm de
    DIAMETRE laisse ses quatre coins dehors : la simulation declare degagees
    des poses ou l'outil touche le coin du carter. L'ecart n'est pas une
    subtilite — il vaut 8,7 mm sur la diagonale d'un NEMA 17.
    """
    f = FicheMachine.du_kit()
    cote = f.valeur("moteur_a_diametre_mm")
    mot = {v.name: v for v in f.organes()}["moteur A droite"]
    assert mot.kind == "box"
    assert mot.hi[1] - mot.lo[1] == pytest.approx(cote)
    assert mot.hi[2] - mot.lo[2] == pytest.approx(cote)
    # le coin du carter est hors d'un cylindre de meme diametre : c'est tout
    # le propos du choix de forme.
    coin = (cote / 2.0) * 2.0 ** 0.5
    assert coin > cote / 2.0 + 8.0


def test_the_organs_follow_the_measured_sheet():
    """Mesurer une cote doit deplacer de la matiere, sinon l'ecran est decoratif.

    C'est la seule chose qui relie les 50 cotes de la fiche aux verdicts
    d'accessibilite : si une cote mesuree ne change pas les organes, la fiche
    ne sert a rien le jour ou la machine existe.
    """
    f = FicheMachine.du_kit()
    avant = {v.name: v for v in f.organes()}
    f.mesurer("moteur_a_diametre_mm", 57.0, moyen="pied à coulisse")
    f.mesurer("berceau_largeur_mm", 260.0, moyen="mètre ruban")
    apres = {v.name: v for v in f.organes()}

    assert apres["moteur A droite"].hi[1] - apres["moteur A droite"].lo[1] \
        == pytest.approx(57.0)
    assert apres["joue droite"].hi[0] == pytest.approx(130.0)
    assert avant["joue droite"].hi[0] == pytest.approx(110.0)
    # et la machine construite porte bien ces organes, pas ceux du defaut.
    m = f.machine()
    assert [v.name for v in m.collision_volumes] == list(apres)


def _mur_d_avant(fiche):
    """L'ancien modele : le plateau, et UNE boite pleine a l'arriere."""
    from xyzac.machine_model.machine import CollisionVolume

    ep = fiche.valeur("plateau_epaisseur_mm")
    larg = fiche.valeur("berceau_largeur_mm") / 2.0
    haut = fiche.valeur("berceau_hauteur_mm")
    prof = fiche.valeur("berceau_profondeur_mm")
    return [
        CollisionVolume(name="plateau C", frame="table_C", kind="cylinder",
                        base=[0.0, 0.0, -ep], axis=[0.0, 0.0, 1.0],
                        radius=fiche.valeur("plateau_rayon_mm"), height=ep),
        CollisionVolume(name="berceau A", frame="cradle_A", kind="box",
                        lo=[-larg, -95.0, -haut + 40.0],
                        hi=[larg, -95.0 + prof, 40.0]),
    ]


def _garde(fiche, organes, nom):
    import numpy as np

    from xyzac.collision_engine.machine_guard import MachineGuard
    from xyzac.tool_model import build_endmill

    m = fiche.machine().model_copy(deep=True)
    m.machine_id = nom           # la mise en cache des nuages porte dessus
    m.collision_volumes = organes
    outil = build_endmill("t", 6.0, 30.0, stickout=40.0, holder_type="ER16")
    garde = MachineGuard(m, outil)
    return lambda tcp, a=0.0, c=0.0: garde.check_pose(np.array(tcp, float), a, c).ok


def test_the_guard_now_refuses_the_sides_and_frees_the_back():
    """L'inversion, prouvee par le garde de collision et non par la fiche.

    C'est le test qui justifie tout le changement. Aux MEMES poses, l'ancien
    mur et le nouveau U rendent des verdicts opposes, et dans les deux cas
    c'est le nouveau qui a raison sur le dessin de la machine :

      - derriere la piece l'ancien modele voyait un mur sur 220 mm de large ;
        il n'y a rien. Des orientations etaient refusees pour une matiere
        imaginaire.
      - sur les cotes l'ancien modele ne voyait rien ; il y a deux joues de
        15 mm. Des poses ou l'outil entre dans une joue etaient declarees
        degagees — exactement la fausse securite que ce projet refuse.
    """
    f = FicheMachine.du_kit()
    avant = _garde(f, _mur_d_avant(f), "avant-mur")
    apres = _garde(f, f.organes(), "apres-u")

    arriere = [0.0, -88.0, 20.0]
    joue_droite = [102.0, 0.0, 20.0]
    joue_gauche = [-102.0, 0.0, 20.0]

    assert not avant(arriere), "temoin : l'ancien mur barrait bien l'arriere"
    assert apres(arriere), "l'arriere est libre, il n'y a rien derriere la pièce"

    assert avant(joue_droite) and avant(joue_gauche), (
        "temoin : l'ancien modele laissait les côtés libres")
    assert not apres(joue_droite), "la joue droite doit arrêter l'outil"
    assert not apres(joue_gauche), "la joue gauche doit arrêter l'outil"

    # et la place de la piece, au milieu du U, reste libre dans les deux.
    assert avant([0.0, 0.0, 20.0]) and apres([0.0, 0.0, 20.0])


def test_a_cheek_swings_with_A_but_a_carter_stays_put():
    """La difference de repere, verifiee par ses consequences.

    Une joue tourne avec le berceau : basculer A de 90 degres la fait sortir
    du chemin de l'outil. Un carter de moteur est boulonne sur le bati : il
    reste exactement ou il est, quel que soit A. Si le carter avait ete place
    dans le repere du berceau, il se serait ecarte tout seul des basculements
    ou il gene le plus — une collision qui s'efface quand on en a besoin.
    """
    f = FicheMachine.du_kit()
    voir = _garde(f, f.organes(), "repere-u")

    joue = [102.0, 0.0, 20.0]
    carter = [134.0, 0.0, -30.0]

    assert not voir(joue, a=0.0), "berceau droit : la joue est sur le chemin"
    assert voir(joue, a=-90.0), "berceau basculé : la joue s'est écartée"

    for a in (0.0, -45.0, -90.0):
        assert not voir(carter, a=a), (
            f"le carter doit rester là à A = {a:.0f}° : il ne tourne pas")
