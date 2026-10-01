"""Le CORPS de l'outil contre la MATIERE, le long du chemin (jalon M22).

Le dernier trou de verification du parcours. Trois gardes existaient :
l'orientation sur les points de bord, la non-gouge de la matiere protegee, et
les organes de la machine. Aucun ne disait si le porte-outil traverse du brut.

Ce fichier porte sur la seule chose qui rend ce garde utile plutot que
decoratif : il doit repondre NON quand il faut, et OUI quand il faut — et la
grandeur qui commande la bascule doit etre la bonne.
"""

import numpy as np
import pytest

from xyzac.geometry_core.voxelize import VoxelGrid
from xyzac.stock_engine.material import ROLES_DANS_LA_COUPE, MaterialState
from xyzac.subtractive_slicer.corps import (roles_du_corps, verifier_le_corps)
from xyzac.tool_model import build_endmill

HAUT = np.array([0.0, 0.0, 1.0])


def _brut(lo=(-30.0, -30.0, 0.0), hi=(30.0, 30.0, 30.0), pitch=1.0, plein=True):
    g = VoxelGrid.covering(np.asarray(lo, float), np.asarray(hi, float), pitch)
    return MaterialState(g, np.full(g.shape, bool(plein)),
                         np.zeros(g.shape, dtype=bool))


def _remplir(etat, lo, hi, valeur=True):
    g = etat.grid
    i0 = np.maximum(0, np.floor((np.asarray(lo, float) - g.origin) / g.pitch).astype(int))
    i1 = np.minimum(g.shape, np.ceil((np.asarray(hi, float) - g.origin) / g.pitch).astype(int))
    etat.remaining[i0[0]:i1[0], i0[1]:i1[1], i0[2]:i1[2]] = valeur
    return etat


def _outil(jauge=45.0, coupe=12.0, diametre=10.0):
    return build_endmill("F", diametre, coupe, stickout=jauge, holder_type="ER16")


# ------------------------------------------------- 1. la regle de base

def test_the_cutting_edge_may_be_in_the_material_but_the_holder_may_not():
    """La distinction qui fonde tout le module.

    Une fraise est CENSEE entrer dans la matiere qu'elle enleve. Un garde qui
    refuserait tout contact refuserait l'usinage. Un garde qui autoriserait tout
    contact laisserait passer un porte-outil traversant 20 mm de brut. Ce test
    exige les deux reponses sur la MEME pose : le bec dans la matiere, le corps
    dehors.
    """
    outil = _outil(jauge=45.0, coupe=12.0)
    assert "cutting" in {s.role.value for s in outil.segments}
    assert roles_du_corps(outil) == {"shank", "holder", "spindle_nose"}
    assert not (roles_du_corps(outil) & ROLES_DANS_LA_COUPE)

    # une dalle de 5 mm au fond : le bec plonge dedans, le corps est 45 mm plus
    # haut, donc tres au-dessus.
    etat = _remplir(_brut(plein=False), (-30, -30, 0), (30, 30, 5))
    chemin = np.array([[0.0, 0.0, 2.0], [10.0, 0.0, 2.0]])
    v = verifier_le_corps(chemin, [False, False], etat, outil, HAUT)
    assert v.ok, v.consigne()
    assert v.n_poses_testees > len(chemin), "le trajet entre poses doit être testé"


def test_the_holder_inside_a_wall_is_refused_and_the_organ_is_named():
    """Un refus qui ne dit pas QUOI toucher et QUOI changer n'est qu'un refus."""
    outil = _outil(jauge=20.0, coupe=12.0)
    # un mur haut, a cote du chemin : le porte-outil (r 11 a 17 mm) le percute,
    # le bec passe a cote.
    etat = _remplir(_brut(plein=False), (14, -30, 0), (30, 30, 30))
    chemin = np.array([[0.0, 0.0, 2.0], [6.0, 0.0, 2.0]])

    v = verifier_le_corps(chemin, [False, False], etat, outil, HAUT)
    assert not v.ok
    assert v.defauts[0].organe in ("holder", "shank")
    c = v.consigne()
    assert "porte-outil" in c or "tige" in c
    assert "À changer" in c and "pince" in c
    assert "pose" in str(v.defauts[0])


def test_the_verdict_is_commanded_by_the_stickout_and_nothing_else():
    """On fait varier LA grandeur qui doit commander le resultat.

    Tout est tenu fixe — piece, chemin, outil, diametre — sauf la longueur
    sortie de pince. Le verdict doit basculer, et basculer dans le bon sens :
    plus l'outil sort court, plus le porte-outil descend bas.
    """
    etat = _remplir(_brut(plein=False), (14, -30, 0), (30, 30, 30))
    chemin = np.array([[0.0, 0.0, 2.0], [6.0, 0.0, 2.0]])

    verdicts = [(j, verifier_le_corps(chemin, [False, False], etat,
                                      _outil(jauge=j), HAUT).ok)
                for j in (60.0, 45.0, 30.0, 20.0, 15.0)]
    assert verdicts[0][1] is True, "sorti long, le corps est au-dessus de tout"
    assert verdicts[-1][1] is False, "sorti court, le porte-outil est dans le mur"
    # et la bascule est MONOTONE : une fois refuse, sortir encore moins ne peut
    # pas redevenir degage.
    vus = [ok for _, ok in verdicts]
    assert vus == sorted(vus, reverse=True), f"verdict non monotone : {verdicts}"


# ------------------------- 2. la matiere SUIVIE, qui est tout le sujet

def test_the_same_pose_is_refused_before_the_pocket_is_opened_and_passed_after():
    """**Le test qui justifie l'existence de ce module.**

    Le meme chemin, le meme outil, la meme piece — et deux verdicts opposes
    selon ce qui a ete COUPE avant d'arriver la. En rapide, rien ne s'ouvre et
    le porte-outil arrive dans du brut intact ; en avance travail, l'outil
    ouvre son propre canal et le corps y descend derriere lui. Verifier contre
    le brut initial refuserait
    tout usinage profond ; verifier contre la piece finie laisserait passer un
    porte-outil traversant 20 mm de brut. Les deux reponses sont fausses, et
    dans les deux sens.

    Le montage est choisi pour que la reponse « apres » soit VRAIE et pas une
    indulgence : une fraise de Ø 40 mm (rayon 20) ouvre un canal plus large que
    son porte-outil (rayon 11 a 17). Le corps peut donc suivre le bec dans ce
    qu'il vient de couper — c'est exactement le cas que ce module doit savoir
    reconnaitre, et que le test grossier, lui, refuse.
    """
    outil = _outil(jauge=18.0, coupe=12.0, diametre=40.0)
    r_corps = max(s.r_max for s in outil.segments if s.role.value == "holder")
    r_coupe = max(s.r_max for s in outil.segments if s.role.value == "cutting")
    assert r_corps < r_coupe, "sinon le passage « après » serait impossible"

    fond = [0.0, 0.0, 6.0]
    plein = _brut(plein=True)
    descente = np.array([[0.0, 0.0, float(z)] for z in np.arange(29.0, 5.9, -0.5)])

    # a) EN RAPIDE : rien n'est coupé, donc rien ne s'ouvre, et le porte-outil
    #    arrive au fond dans du brut intact.
    direct = verifier_le_corps(descente, [True] * len(descente), plein, outil, HAUT)
    assert not direct.ok, "un rapide jusqu'au fond plonge le porte-outil dans le bloc"
    assert direct.defauts[0].organe in ("shank", "holder")

    # b) LE MEME CHEMIN, en avance travail : l'outil ouvre son propre canal en
    #    descendant, et le corps y descend derrière lui. Rien d'autre ne change
    #    — même état de départ, même outil, même géométrie, mêmes points.
    apres = verifier_le_corps(descente, [False] * len(descente),
                              plein, outil, HAUT)
    assert apres.ok, (
        "après avoir ouvert le puits, le même point doit passer : "
        + apres.consigne())
    assert apres.n_fins >= 1, (
        "le test grossier doit avoir signalé quelque chose — c'est la marche "
        "fine, chronologique, qui conclut que tout va bien")
    assert direct.defauts and not apres.defauts, (
        "c'est bien la MÊME géométrie qui donne les deux verdicts")
    # et l'etat de depart n'a pas bouge
    assert plein.remaining.all()


def test_the_state_given_is_not_modified():
    """Un verificateur qui consomme la matiere qu'il verifie ne peut servir
    qu'une fois, et la deuxieme reponse serait fausse sans prevenir."""
    outil = _outil(jauge=45.0)
    etat = _brut(plein=True)
    avant = etat.remaining.sum()
    v1 = verifier_le_corps(np.array([[0.0, 0.0, 25.0], [8.0, 0.0, 25.0]]),
                           [False, False], etat, outil, HAUT)
    assert etat.remaining.sum() == avant, "l'état fourni doit rester intact"
    v2 = verifier_le_corps(np.array([[0.0, 0.0, 25.0], [8.0, 0.0, 25.0]]),
                           [False, False], etat, outil, HAUT)
    assert v1.ok == v2.ok and v1.n_poses_testees == v2.n_poses_testees


def test_a_move_between_two_poses_cannot_slip_through_a_wall():
    """Deux poses degagees de part et d'autre d'un mur ne font pas un trajet
    degage. Sans densification, le mur serait invisible — et c'est le defaut
    qui a deja ete corrige dans les liaisons, pour la meme raison."""
    outil = _outil(jauge=20.0, coupe=12.0)
    # un mur mince, perpendiculaire au trajet, qui tient entre deux poses
    etat = _remplir(_brut(plein=False), (-1, -30, 0), (1, 30, 30))
    chemin = np.array([[-25.0, 0.0, 2.0], [25.0, 0.0, 2.0]])   # deux poses seulement

    v = verifier_le_corps(chemin, [False, False], etat, outil, HAUT)
    assert not v.ok, "le mur est entre les deux poses, il doit être vu"
    assert v.n_poses_testees >= 50, (
        "la densification doit être plus fine que la grille")


# ------------------------------------------- 3. l'honnetete du resultat

def test_without_a_material_state_the_check_says_so_instead_of_passing():
    """« Pas d'etat de matiere » doit donner « je ne sais pas », jamais
    « degage ». C'est la fausse valeur que ce projet interdit."""
    v = verifier_le_corps(np.array([[0.0, 0.0, 5.0]]), [False], None,
                          _outil(), HAUT)
    assert not v.faite
    assert not v.ok, "non vérifié n'est pas dégagé"
    assert "NON VÉRIFIÉ" in v.consigne()


def test_a_plan_cannot_be_built_without_the_material_state():
    """Et la gamme refuse plutot que de poster un programme dont une des quatre
    verifications n'a pas eu lieu."""
    from xyzac.machine_model.fiche import FicheMachine
    from xyzac.recipe_profiles.interfaces import Quality
    from xyzac.recipe_profiles.recipes import build_recipe
    from xyzac.strategy_planner.gamme import gamme_des_creux

    m = FicheMachine.du_kit().machine()
    outil = _outil()
    rec = build_recipe("aluminium-6061", outil, m, quality=Quality.ROUGHING)
    with pytest.raises(ValueError, match="aucun etat de matiere"):
        gamme_des_creux(None, [], plan_id="nue", material=None)
    assert rec.feed_mm_min > 0


def test_the_sweep_used_here_is_the_one_the_material_model_uses():
    """Deux geometries d'outil pour la meme question divergeraient, et celle
    qu'on croirait serait celle qui autorise.

    Le balayage de verification et le balayage d'enlevement sont la MEME
    fonction, avec le meme filtre de roles — on verifie ici que le filtre
    partitionne bien l'outil, sans trou ni recouvrement.
    """
    outil = _outil()
    tous = {s.role.value for s in outil.segments}
    assert roles_du_corps(outil) | (tous & ROLES_DANS_LA_COUPE) == tous
    assert not (roles_du_corps(outil) & ROLES_DANS_LA_COUPE)

    etat = _brut(plein=True)
    pose = np.array([[0.0, 0.0, 10.0]])
    axe = HAUT.reshape(1, 3)

    a = MaterialState(etat.grid, etat.remaining.copy(), np.zeros(etat.grid.shape, bool))
    b = MaterialState(etat.grid, etat.remaining.copy(), np.zeros(etat.grid.shape, bool))
    c = MaterialState(etat.grid, etat.remaining.copy(), np.zeros(etat.grid.shape, bool))
    n_tout = a.remove_tool_sweep(pose, axe, outil, only_cutting=False)
    n_coupe = b.remove_tool_sweep(pose, axe, outil)
    n_corps = c.remove_tool_sweep(pose, axe, outil, roles=roles_du_corps(outil))
    assert n_tout > 0 and n_coupe > 0 and n_corps > 0
    # les deux moities recouvrent le tout, et se chevauchent au plus la ou les
    # troncons se touchent — jamais moins que le tout.
    assert n_coupe + n_corps >= n_tout
    assert max(n_coupe, n_corps) <= n_tout


def test_the_report_says_when_the_coarse_filter_had_to_be_reopened():
    """Un chiffre qu'il faut regarder : les tronçons que le test grossier a crus
    fautifs et que la marche chronologique a innocentés.

    S'il reste nul, le filtre fait son travail et le coût reste celui du cas
    normal. S'il monte, c'est que le filtre ne filtre plus grand-chose — et on
    le saura par ce compteur plutôt que par un temps de calcul qui gonfle sans
    explication.
    """
    outil = _outil(jauge=18.0, coupe=12.0, diametre=40.0)
    plein = _brut(plein=True)
    descente = np.array([[0.0, 0.0, float(z)] for z in np.arange(29.0, 5.9, -0.5)])

    v = verifier_le_corps(descente, [False] * len(descente), plein, outil, HAUT)
    assert v.ok and v.n_fins == 1
    assert "repris pose par pose" in v.consigne()

    # un chemin qui ne frôle rien ne déclenche pas la marche fine
    loin = np.array([[0.0, 0.0, 40.0], [10.0, 0.0, 40.0]])
    w = verifier_le_corps(loin, [True, True], plein, outil, HAUT)
    assert w.ok and w.n_fins == 0
    assert "repris pose par pose" not in w.consigne()


def test_the_number_of_reported_faults_is_bounded():
    """Localiser coûte une marche pose par pose. Au-delà de quelques fautes on
    sait déjà que le parcours est refusé, et continuer ne dirait rien de plus.
    """
    outil = _outil(jauge=18.0, coupe=12.0)
    etat = _brut(plein=True)
    long_chemin = np.array([[x, 0.0, 6.0] for x in np.arange(-20.0, 20.0, 0.5)])
    v = verifier_le_corps(long_chemin, [True] * len(long_chemin), etat, outil,
                          HAUT, maximum=2)
    assert not v.ok
    assert len(v.defauts) <= 2
