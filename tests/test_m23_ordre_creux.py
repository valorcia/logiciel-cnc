"""L'ordre des creux entre eux (jalon M23).

Trois termes, trois ordres de grandeur, et un piege
====================================================

L'ordre decide le nombre de changements d'outil (une intervention de
l'operateur sur ce kit sans changeur), le nombre de re-indexations (A, C), et
le transport. Les resumer en un seul chiffre supposerait un taux de change
entre une intervention, une rotation et un millimetre — taux qui demanderait
un modele de temps bati sur des vitesses DE PLAN.

Le piege est ailleurs : des que l'ordre est decide, la matiere evolue avec lui,
et un creux REFUSE ne doit rien avancer. Le dernier test de ce fichier porte
la-dessus, et c'est le seul qui protege contre une erreur silencieuse et du
cote optimiste.
"""

import numpy as np
import pytest

from xyzac.geometry_core.voxelize import VoxelGrid
from xyzac.machine_model.fiche import FicheMachine
from xyzac.recipe_profiles.interfaces import Quality
from xyzac.recipe_profiles.recipes import build_recipe
from xyzac.stock_engine.material import MaterialState
from xyzac.strategy_planner.gamme import gamme_des_creux
from xyzac.strategy_planner.ordre_creux import ordonner_les_creux
from xyzac.tool_model import build_endmill

from tests.test_m21_gamme_gcode import FauxParcours, _setup


def _outil(diametre):
    return build_endmill(f"F{diametre:.0f}", diametre, 12.0, stickout=45.0,
                         holder_type="ER16")


def _creux(index, x, y, a=0.0, c=0.0, diametre=10.0, longueur=4.0):
    """Un creux reduit a ce que l'ordonnanceur regarde : ou, quel outil, quelle
    orientation."""
    pts = [[x, y, 10.0], [x + longueur, y, 10.0]]
    return (FauxParcours(pts, [False, False], a, c, index=index),
            _outil(diametre), None)


def _matiere(pitch=1.0):
    g = VoxelGrid.covering(np.array([-60.0, -60.0, 0.0]),
                           np.array([60.0, 60.0, 30.0]), pitch)
    return MaterialState(g, np.zeros(g.shape, dtype=bool),
                         np.zeros(g.shape, dtype=bool))


# ------------------------------------------- 1. les trois termes, dans l'ordre

def test_grouping_by_tool_is_optimal_and_not_a_heuristic():
    """Pour k outils, le minimum de changements vaut k-1. Tout groupement
    l'atteint — ce terme n'est donc pas approche, il est exact.

    L'ordre recu alterne deliberement : trois outils, cinq creux, quatre
    changements. Groupe, il en reste deux.
    """
    elements = [_creux(1, 0, 0, diametre=10.0),
                _creux(2, 10, 0, diametre=6.0),
                _creux(3, 20, 0, diametre=10.0),
                _creux(4, 30, 0, diametre=3.0),
                _creux(5, 40, 0, diametre=6.0)]
    g = ordonner_les_creux(elements)
    assert g.outils_avant == 4
    assert g.outils_apres == 2, "trois outils ⇒ deux changements, pas plus"
    assert sorted(g.ordre) == list(range(5)), "aucun creux perdu ni dupliqué"


def test_the_big_tools_come_first_when_it_costs_nothing():
    """Regle d'atelier : la grosse fraise sort la matiere, la petite finit.

    Mais c'est une PREFERENCE, pas une contrainte — avec un outil par creux,
    l'ordre des groupes ne change pas qui coupe quoi. On la suit donc quand
    elle ne coûte rien, et la garantie globale la cede quand elle coûterait du
    trajet pour rien (test suivant).
    """
    elements = [_creux(1, 20, 0, diametre=3.0),
                _creux(2, 0, 0, diametre=10.0),
                _creux(3, 10, 0, diametre=6.0)]
    g = ordonner_les_creux(elements)
    diams = [10.0, 6.0, 3.0]
    vus = [max(s.r_max for s in elements[i][1].segments
               if s.role.value == "cutting") * 2 for i in g.ordre]
    assert vus == diams, f"attendu du plus gros au plus petit, vu {vus}"
    assert g.transport_apres_mm < g.transport_avant_mm, (
        "ici la préférence est gratuite : elle raccourcit aussi le trajet")


def test_a_reordering_that_gains_nothing_and_costs_distance_is_refused():
    """**La garantie, au niveau de la SEQUENCE et pas du sous-groupe.**

    Le 2-opt garantit de ne pas rallonger a l'interieur d'un sous-groupe. Cela
    ne dit rien de l'ordre DES sous-groupes — et c'est exactement par la que la
    premiere version de ce module degradait : sur C05, deux creux, un seul
    outil, deux orientations, elle les intervertissait et faisait passer le
    transport de 36 a 61 mm pour zero changement d'outil economise.

    Trois outils pour trois creux : quel que soit l'ordre, il y aura deux
    changements. Grouper n'economise donc RIEN, et le trajet recu est le plus
    court. L'ordre recu doit etre garde.
    """
    elements = [_creux(1, 0, 0, diametre=3.0),
                _creux(2, 10, 0, diametre=10.0),
                _creux(3, 20, 0, diametre=6.0)]
    g = ordonner_les_creux(elements)
    assert g.outils_avant == 2 and g.outils_apres == 2, (
        "trois outils ⇒ deux changements, quel que soit l'ordre")
    assert g.ordre == [0, 1, 2]
    assert g.transport_apres_mm == pytest.approx(g.transport_avant_mm)


def test_two_orientations_and_one_tool_do_not_get_shuffled_for_nothing():
    """Le cas C05, reduit a ce qui le faisait echouer.

    Le premier sous-groupe d'orientation etait choisi par ``min()`` sur un
    couple d'angles — c'est-a-dire sur un ordre lexicographique de nombres,
    donc sur rien. A defaut d'orientation courante, le depart naturel est
    l'ordre RECU.
    """
    elements = [_creux(1, 0, 0, a=-90.0, c=0.0),
                _creux(2, 30, 0, a=-90.0, c=-180.0)]
    g = ordonner_les_creux(elements)
    assert g.ordre == [0, 1], "rien ne justifie de les intervertir"
    assert g.transport_apres_mm <= g.transport_avant_mm + 1e-9


def test_orientation_groups_inside_a_tool_group():
    """Changer d'orientation fait tourner le plateau et basculer le berceau.
    A outil egal, on ne re-indexe pas deux fois pour rien."""
    elements = [_creux(1, 0, 0, a=0.0, c=0.0),
                _creux(2, 10, 0, a=-90.0, c=0.0),
                _creux(3, 20, 0, a=0.0, c=0.0),
                _creux(4, 30, 0, a=-90.0, c=0.0)]
    g = ordonner_les_creux(elements)
    assert g.indexations_avant == 3
    assert g.indexations_apres == 1, "deux orientations ⇒ une ré-indexation"
    assert g.outils_apres == 0, "un seul outil : aucun changement"


def test_transport_is_shortened_when_nothing_else_separates_the_cavities():
    """Meme outil, meme orientation : il ne reste que le trajet, et c'est la
    que le plus-proche-voisin et le 2-opt travaillent."""
    # places en zigzag volontaire : l'ordre recu traverse la piece a chaque fois
    xs = [0.0, 50.0, 10.0, 60.0, 20.0]
    elements = [_creux(i + 1, x, 0.0) for i, x in enumerate(xs)]
    g = ordonner_les_creux(elements)
    assert g.transport_apres_mm < g.transport_avant_mm
    assert g.outils_apres == 0 and g.indexations_apres == 0


def test_the_received_order_is_kept_when_it_is_already_the_shortest():
    """Le module ne doit jamais rendre pire que ce qu'on lui donne, a termes
    superieurs egaux. L'ordre recu est donc un candidat evalue comme un autre.
    """
    elements = [_creux(i + 1, 10.0 * i, 0.0) for i in range(5)]
    g = ordonner_les_creux(elements)
    assert g.ordre == [0, 1, 2, 3, 4]
    assert g.transport_apres_mm == pytest.approx(g.transport_avant_mm)


def test_a_longer_trip_is_accepted_to_save_a_tool_change_and_it_is_SAID():
    """**Le compromis assume, et le refus de le cacher.**

    Grouper par outil peut eloigner deux creux voisins. C'est le prix de
    l'echelon superieur — une intervention de l'operateur contre quelques
    centaines de millimetres — mais un module qui l'appliquerait sans le dire
    presenterait une degradation comme une optimisation.
    """
    # deux paires voisines, outils croises : grouper par outil oblige a
    # traverser la piece.
    elements = [_creux(1, 0, 0, diametre=10.0),
                _creux(2, 5, 0, diametre=6.0),
                _creux(3, 100, 0, diametre=10.0),
                _creux(4, 105, 0, diametre=6.0)]
    g = ordonner_les_creux(elements)
    assert g.outils_avant == 3 and g.outils_apres == 1
    assert g.transport_pire, "ce montage doit rallonger le trajet"
    assert "transport augmente" in g.resume()
    assert "intervention de l'opérateur" in g.resume()


def test_one_cavity_has_no_order_to_decide():
    g = ordonner_les_creux([_creux(1, 0, 0)])
    assert g.ordre == [0] and "aucun ordre" in g.resume()
    assert ordonner_les_creux([]).ordre == []


# ----------------------------------- 2. le piege : la matiere suit l'ordre

def test_a_refused_cavity_does_not_advance_the_material():
    """**Le test qui protege contre une erreur silencieuse et optimiste.**

    Dès que les creux sont verifies dans l'ordre, chacun l'est contre ce que
    ses predecesseurs ont sorti. Si un creux REFUSE avancait quand meme la
    matiere, tous les suivants seraient verifies contre un usinage qu'on ne
    fera pas — donc avec MOINS de matiere qu'il n'y en aura reellement, et le
    porte-outil serait declare degage la ou il ne le sera pas.

    Rien ne crierait : la gamme serait complete, les verdicts verts, le fichier
    emis. C'est exactement la famille de defaut que ce projet rencontre depuis
    le debut.
    """
    fiche = FicheMachine.du_kit()
    m = fiche.machine()
    outil = _outil(10.0)
    rec = build_recipe("aluminium-6061", outil, m, quality=Quality.ROUGHING)
    setup = _setup(m, outil)
    demi = fiche.valeur("berceau_largeur_mm") / 2.0

    # le premier est REFUSE par le garde machine (il entre dans une joue),
    # le second est bon. L'etat vu par le second ne doit rien devoir au premier.
    mauvais = FauxParcours([[0, 0, 10], [demi - 5.0, 0, 10]], [False, False],
                           0.0, 0.0, index=1)
    bon = FauxParcours([[0, 0, 10], [5, 0, 10]], [False, False], 0.0, 0.0, index=2)

    vide = _matiere()
    plan, verifs, gain = gamme_des_creux(
        setup, [(mauvais, outil, rec), (bon, outil, rec)],
        plan_id="refus", material=vide, reordonner=False)

    assert [o.op_id for o in plan.operations] == ["creux-2"]
    assert not verifs[0][1].ok and verifs[1][1].ok
    # la matiere fournie n'a pas bouge : c'est l'appelant qui la garde
    assert not vide.remaining.any()


def test_the_cavities_are_verified_in_the_order_they_are_emitted():
    """Verifier dans un ordre et emettre dans un autre annulerait le sens de la
    verification : chaque creux serait valide contre une matiere qui ne sera
    pas celle qu'il trouvera."""
    fiche = FicheMachine.du_kit()
    m = fiche.machine()
    gros, petit = _outil(10.0), _outil(6.0)
    rec_g = build_recipe("aluminium-6061", gros, m, quality=Quality.ROUGHING)
    rec_p = build_recipe("aluminium-6061", petit, m, quality=Quality.ROUGHING)
    setup = _setup(m, gros)

    elements = [
        (FauxParcours([[0, 0, 10], [4, 0, 10]], [False, False], 0.0, 0.0, index=1),
         petit, rec_p),
        (FauxParcours([[20, 0, 10], [24, 0, 10]], [False, False], 0.0, 0.0, index=2),
         gros, rec_g),
        (FauxParcours([[40, 0, 10], [44, 0, 10]], [False, False], 0.0, 0.0, index=3),
         petit, rec_p),
    ]
    plan, verifs, gain = gamme_des_creux(setup, elements, plan_id="ordre",
                                         material=_matiere())
    emis = [o.op_id for o in plan.operations]
    verifies = [f"creux-{i}" for i, _, _ in verifs]
    assert emis == verifies, "l'ordre d'émission doit être l'ordre de vérification"
    assert emis[0] == "creux-2", "le gros outil d'abord"
    assert gain.outils_apres == 1 and gain.outils_avant == 2


def test_a_cavity_without_a_path_has_no_rank_and_crashes_nothing():
    """**Trouvé en ouvrant l'écran des creux, pas par un test.**

    Un creux peut être déclaré usinable, recevoir un outil, et n'avoir AUCUN
    parcours : la marge de tranchage le refuse (ADR-016). Sur C21, deux poches
    sur six sont dans ce cas — elles annoncent une Ø 10 et ne produisent rien.

    Un tel creux n'a ni début ni fin. La première version le passait quand même
    à l'ordonnanceur, qui levait un `IndexError` sur un tableau vide : l'écran
    des creux rendait une erreur 500 et ne s'ouvrait plus du tout sur cette
    pièce. Le module dit maintenant son contrat, et l'appelant écarte ces creux
    de l'ordre — sans les faire disparaître du rapport.
    """
    vide = FauxParcours(np.zeros((0, 3)), np.zeros(0, dtype=bool), 0.0, 0.0, index=9)
    with pytest.raises(ValueError, match="aucun parcours"):
        ordonner_les_creux([_creux(1, 0, 0), (vide, _outil(10.0), None)])

    # et la gamme, elle, les garde dans son rapport au lieu de les perdre
    fiche = FicheMachine.du_kit()
    m = fiche.machine()
    outil = _outil(10.0)
    rec = build_recipe("aluminium-6061", outil, m, quality=Quality.ROUGHING)
    setup = _setup(m, outil)
    bon = FauxParcours([[0, 0, 10], [5, 0, 10]], [False, False], 0.0, 0.0, index=1)

    plan, verifs, gain = gamme_des_creux(
        setup, [(vide, outil, rec), (bon, outil, rec)],
        plan_id="avec-vide", material=_matiere())
    assert [o.op_id for o in plan.operations] == ["creux-1"]
    assert sorted(i for i, _, _ in verifs) == [1, 9], (
        "le creux sans parcours doit rester dans le rapport")
    assert gain.n_creux == 1, "il ne compte pas dans l'ordre"
