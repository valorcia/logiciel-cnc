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
