"""Du parcours par creux au G-code (jalon M21).

Ce que ce fichier garde, et pourquoi chacun compte
==================================================

La chaine existait aux deux bouts : ``creux.py`` decide outil et orientation,
``emit.py`` ecrit du G-code compense derriere les portes de securite. Entre les
deux il n'y avait rien, et « rien » n'etait pas un simple trou de plomberie —
c'etait trois verifications que personne ne faisait.

Aucun de ces tests ne verifie une recopie de champs. Chacun verifie qu'une
question a laquelle personne ne repondait recoit maintenant une reponse, ET
que la reponse est la bonne quand on fait varier ce qui doit la commander.
"""

import math

import numpy as np
import pytest

from xyzac.assembly_calibration import calibrate_on_twin, record_from_report
from xyzac.geometry_core.types import AABB, normalize
from xyzac.kinematics_solver import KinematicsSolver
from xyzac.kinematics_solver.compensation import CompensatedMove, realised_pose
from xyzac.machine_model import Setup, default_xyzac_kit
from xyzac.machine_model.fiche import FicheMachine
from xyzac.machine_model.geometry import AxisLocationError, MachineGeometry, _rodrigues
from xyzac.postprocessor_linuxcnc import parse_poses, post_process
from xyzac.recipe_profiles.interfaces import Quality
from xyzac.recipe_profiles.recipes import build_recipe
from xyzac.safety_state_machine import SafetyStateMachine
from xyzac.stock_engine import stock_from_part
from xyzac.strategy_planner.gamme import (direction_de, freiner_les_descentes,
                                          gamme_des_creux, operation_du_creux,
                                          verifier_le_parcours)
from xyzac.strategy_planner.interfaces import Kinematic
from xyzac.tool_model import build_endmill


class FauxParcours:
    """Un ``ParcoursCreux`` reduit a ce que la gamme lui demande.

    Volontairement pas un vrai : le vrai coûte une minute de voxelisation par
    piece, et ce que ces tests eprouvent est la CONVERSION, pas le trancheur.
    Les champs portent les memes noms — si le contrat change, ces tests cassent.
    """

    def __init__(self, points, rapide, a_deg, c_deg, index=1):
        self.points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        self.rapide = np.asarray(rapide, dtype=bool).reshape(-1)
        self.a_deg = float(a_deg)
        self.c_deg = float(c_deg)
        self.index = index


def _machine_et_outil():
    m = FicheMachine.du_kit().machine()
    outil = build_endmill("F10", 10.0, 30.0, stickout=45.0, holder_type="ER16")
    return m, outil


# ------------------------------------------------- 1. la descente en rapide

def test_a_descent_is_never_a_rapid_move():
    """Le defaut vu sur le PREMIER fichier produit, et pas avant.

    ``abaisser_les_liaisons`` remplace une liaison par quatre sommets : monter,
    traverser, redescendre. Ce qui est demontre degage est le COULOIR
    HORIZONTAL. La descente finale, elle, rejoint le debut de la passe
    suivante — une position ou il y a de la matiere par definition, puisque
    c'est la qu'on va couper. Le fichier emis la portait en G0 : un rapide
    vers un point de contact, exactement ce que l'emetteur refuse deja pour le
    premier point d'une operation.

    La montee doit rester en rapide : remonter le long de l'axe outil depuis
    une position que l'outil occupait deja ne rencontre que le vide qu'il
    vient de laisser. Un test qui freinerait aussi la montee ne protegerait
    rien de plus et coûterait du temps de cycle.
    """
    d = np.array([0.0, 0.0, 1.0])
    pts = np.array([[0, 0, 0], [0, 0, 5], [10, 0, 5], [10, 0, 1], [10, 0, 0]], float)
    rap = np.array([False, True, True, True, False])

    freine, n = freiner_les_descentes(pts, rap, d)
    assert n == 1
    assert list(freine) == [False, True, True, False, False], (
        "la montee et la traversee restent rapides, la descente non")

    # et la regle suit l'AXE OUTIL, pas Z : berceau bascule, « descendre »
    # n'est plus « Z diminue ».
    d2 = normalize(np.array([0.0, 1.0, 0.0]))
    pts2 = np.array([[0, 0, 0], [0, 5, 0], [10, 5, 0], [10, 1, 0]], float)
    rap2 = np.array([False, True, True, True])
    freine2, n2 = freiner_les_descentes(pts2, rap2, d2)
    assert n2 == 1 and list(freine2) == [False, True, True, False]


def test_braking_the_descents_reaches_the_emitted_file():
    """Un drapeau change dans un tableau ne protege personne : c'est la LIGNE
    du fichier qui doit changer."""
    m, outil = _machine_et_outil()
    rec = build_recipe("aluminium-6061", outil, m, quality=Quality.ROUGHING)
    pts = np.array([[0, 0, 0], [0, 0, 20], [20, 0, 20], [20, 0, 2]], float)
    op = operation_du_creux(FauxParcours(pts, [False, True, True, True], 0.0, 0.0),
                            outil, rec, m, op_id="essai")
    assert list(np.asarray(op.toolpath.is_rapid)) == [False, True, True, False]
    assert "descentes de liaison" in op.notes


# ------------------------------------- 2. le couple (A, C) n'est pas redevine

def test_the_approved_posture_crosses_the_chain_instead_of_being_guessed():
    """La quinzieme occurrence de la meme famille de defaut.

    ``ik_best(d)`` repond a « quel couple donne cet axe outil ». Ce n'est pas la
    question posee : la question est « quel couple le controle de collision
    a-t-il approuve ». Les deux branches de l'inverse, (a, c) et (-a, c + 180),
    donnent le MEME axe outil dans le repere piece en posant la piece de deux
    facons DIFFERENTES dans le berceau — donc avec deux verdicts de collision
    differents, puisque les joues et les carters ne sont pas au meme endroit
    par rapport a elle.

    Sur le kit, les butees A = [-120, +30] n'en laissent souvent qu'une, et les
    deux reponses coincident : le defaut est alors invisible. On elargit donc
    les butees pour que les DEUX branches soient atteignables — c'est le seul
    moyen de montrer que le choix est fait au bon endroit.
    """
    m = FicheMachine.du_kit().machine()
    m.a.min_deg, m.a.max_deg = -120.0, 120.0      # les deux branches passent
    outil = build_endmill("F10", 10.0, 30.0, stickout=45.0, holder_type="ER16")
    ks = KinematicsSolver(m)

    a_vise, c_vise = -20.0, 35.0
    d = direction_de(m, a_vise, c_vise)

    # temoin : laisse a lui-meme, l'inverse choisit l'AUTRE branche
    seul = ks.ik_best(d, allow_singular=True)
    assert seul is not None
    assert abs(seul.a_deg - a_vise) > 1.0, (
        "si l'inverse retombait deja sur la bonne branche, ce test ne "
        "testerait rien")
    assert abs(abs(seul.a_deg) - abs(a_vise)) < 1e-6, "meme |A|, autre signe"

    rec = build_recipe("aluminium-6061", outil, m, quality=Quality.ROUGHING)
    pts = np.array([[0, 0, 0], [5, 0, 0], [10, 0, 0]], float)
    op = operation_du_creux(FauxParcours(pts, [False] * 3, a_vise, c_vise),
                            outil, rec, m, op_id="indexe")
    assert op.kinematic is Kinematic.MILLING_3PLUS2
    assert op.ac_impose == (a_vise, c_vise)

    gcode = _emettre(m, [op], outil)
    poses = parse_poses(gcode)
    # tolerance large devant l'ecart qu'on cherche : les deux branches sont a
    # 40 degres l'une de l'autre en A, la compensation geometrique corrige de
    # quelques milliemes. Exiger l'egalite stricte confondrait les deux.
    assert all(abs(p["A"] - a_vise) < 0.05 for p in poses), (
        "le fichier doit porter la posture VERIFIEE, pas celle que l'inverse "
        f"prefere ({sorted({p['A'] for p in poses})})")
    assert all(abs(p["C"] - c_vise) < 0.05 for p in poses)


def test_an_imposed_couple_that_does_not_carry_its_own_axis_is_refused():
    """Un couple impose FAUX serait pire que pas de couple du tout.

    L'operation decide de l'orientation ; l'emetteur doit donc pouvoir
    constater qu'elle est coherente avec la trajectoire qu'elle accompagne,
    sinon le fait de porter le couple ne ferait que deplacer la confiance sans
    la fonder.
    """
    m, outil = _machine_et_outil()
    rec = build_recipe("aluminium-6061", outil, m, quality=Quality.ROUGHING)
    pts = np.array([[0, 0, 0], [5, 0, 0]], float)
    op = operation_du_creux(FauxParcours(pts, [False, False], 0.0, 0.0),
                            outil, rec, m, op_id="menteuse")
    op.ac_impose = (-45.0, 0.0)          # l'axe de la trajectoire est reste +Z

    with pytest.raises(RuntimeError, match="ne porte pas l'axe outil"):
        _emettre(m, [op], outil)


def test_an_imposed_couple_outside_the_stops_is_refused():
    """Hors butees, le fichier serait rejete par le controleur — ou pire, il
    serait accepte apres un modulo silencieux."""
    m, outil = _machine_et_outil()
    rec = build_recipe("aluminium-6061", outil, m, quality=Quality.ROUGHING)
    a_hors = m.a.min_deg - 10.0
    d = direction_de(m, a_hors, 0.0)
    pts = np.array([[0, 0, 0], [5, 0, 0]], float)
    op = operation_du_creux(FauxParcours(pts, [False, False], a_hors, 0.0),
                            outil, rec, m, op_id="hors-butee")
    assert np.allclose(np.asarray(op.toolpath.normals)[0], d)

    with pytest.raises(RuntimeError, match="hors des butees"):
        _emettre(m, [op], outil)


# ------------------------------------------- 3. le parcours entier est garde

def test_the_whole_path_is_checked_and_not_only_the_border_points():
    """``decider_creux`` verifie quelques dizaines de points de BORD.

    Un parcours en compte des milliers et descend couche par couche. Entre les
    deux, rien ne garantissait que le nez de broche degage encore au dernier
    niveau. Ce test met une pose dans une joue du berceau — celle que l'ADR-019
    a remise a sa place — et exige que la gamme la refuse au lieu de la poster.
    """
    fiche = FicheMachine.du_kit()
    m = fiche.machine()
    outil = build_endmill("F10", 10.0, 30.0, stickout=45.0, holder_type="ER16")
    demi = fiche.valeur("berceau_largeur_mm") / 2.0
    joue = fiche.valeur("berceau_profondeur_mm")

    au_centre = np.array([[0.0, 0.0, 10.0], [5.0, 0.0, 10.0]])
    bon = verifier_le_parcours(FauxParcours(au_centre, [False, False], 0.0, 0.0),
                               m, outil)
    assert bon.ok, bon.consigne()

    dans_la_joue = np.vstack([au_centre,
                              [[demi - joue / 2.0, 0.0, 10.0]]])
    mauvais = verifier_le_parcours(
        FauxParcours(dans_la_joue, [False, False, True], 0.0, 0.0), m, outil)
    assert not mauvais.ok
    assert mauvais.n_collision == 1 and mauvais.n_hors_course == 0
    assert mauvais.premieres == [2], "il faut pouvoir aller REGARDER la pose"
    assert "organe" in mauvais.consigne() and "à changer" in mauvais.consigne()


def test_a_pose_out_of_travel_is_named_as_such_and_not_as_a_collision():
    """Deux causes, deux leviers. Les confondre enverrait l'utilisateur
    raccourcir son outil alors que sa piece est trop loin du centre."""
    m, outil = _machine_et_outil()
    loin = np.array([[0.0, 0.0, 10.0], [m.x.max_mm + 50.0, 0.0, 10.0]])
    v = verifier_le_parcours(FauxParcours(loin, [False, True], 0.0, 0.0), m, outil)
    assert not v.ok
    assert v.n_hors_course == 1
    assert v.n_collision == 0, (
        "une pose hors course n'est pas testee en collision : la compter deux "
        "fois ferait croire a deux defauts la ou il y en a un")
    assert "hors des courses" in v.consigne()


def test_a_refused_cavity_is_left_out_of_the_plan_but_not_out_of_the_report():
    """Une gamme amputee sans dire de quoi laisserait croire que les creux
    manquants n'existaient pas."""
    fiche = FicheMachine.du_kit()
    m = fiche.machine()
    outil = build_endmill("F10", 10.0, 30.0, stickout=45.0, holder_type="ER16")
    rec = build_recipe("aluminium-6061", outil, m, quality=Quality.ROUGHING)
    setup = _setup(m, outil)

    bon = FauxParcours([[0, 0, 10], [5, 0, 10]], [False, False], 0.0, 0.0, index=1)
    demi = fiche.valeur("berceau_largeur_mm") / 2.0
    mauvais = FauxParcours([[0, 0, 10], [demi - 5.0, 0, 10]], [False, False],
                           0.0, 0.0, index=2)

    plan, verifs, _ = gamme_des_creux(setup, [(bon, outil, rec), (mauvais, outil, rec)],
                                   plan_id="partielle", material=_matiere(mur=((-30, -30, 0), (-29, -29, 1))))
    assert [o.op_id for o in plan.operations] == ["creux-1"]
    assert [i for i, _, _ in verifs] == [1, 2]
    assert verifs[0][1].ok and not verifs[1][1].ok


def test_an_operation_without_a_recipe_is_refused_before_the_plan_is_built():
    """Refuser a la derniere ligne ferait batir une gamme entiere pour rien, et
    surtout : une avance inventee est ce que ce projet refuse partout."""
    m, outil = _machine_et_outil()
    with pytest.raises(ValueError, match="aucune recette"):
        operation_du_creux(FauxParcours([[0, 0, 0], [1, 0, 0]], [False, False],
                                        0.0, 0.0), outil, None, m, op_id="nue")


# --------------------------------------------- 4. l'honnetete de l'en-tete

def test_the_header_no_longer_signs_for_a_verification_it_did_not_do():
    """L'en-tete annoncait « liaisons valides comme le reste du mouvement ».

    C'etait vrai du temps ou les seules trajectoires venaient d'un module qui
    validait tout. C'est devenu faux le jour ou une gamme par creux est arrivee,
    dont les liaisons sont demontrees degagees sur leur couloir HORIZONTAL et
    pas sur leurs descentes. Un en-tete qui signe une verification qu'il n'a pas
    faite est exactement la fausse valeur que ce projet interdit.
    """
    m, outil = _machine_et_outil()
    rec = build_recipe("aluminium-6061", outil, m, quality=Quality.ROUGHING)
    pts = np.array([[0, 0, 0], [0, 0, 20], [20, 0, 20], [20, 0, 2]], float)
    op = operation_du_creux(FauxParcours(pts, [False, True, True, True], 0.0, 0.0),
                            outil, rec, m, op_id="creux-1")

    gcode = _emettre(m, [op], outil)
    tete = gcode.split("G21")[0]
    assert "valides comme le reste du mouvement" not in tete
    assert "ne les VERIFIE pas" in tete
    # et ce que l'operation a REELLEMENT subi est dit a cote d'elle
    assert "descentes de liaison" in gcode
    assert "verrouille" in tete, "le fichier doit dire qu'il n'est pas parti"


# ----------------------------------------------------- 5. l'aller-retour

def test_the_round_trip_on_an_indexed_cavity_path_stays_inside_the_budget():
    """Un emetteur verifie contre son propre calcul ne verifie rien.

    On relit le fichier, on rejoue la cinematique REELLE sur les valeurs
    relues, et on compare au point demande. Deux fois : sur la geometrie
    MESUREE, ou il ne doit rester que la quantification du format ; puis sur la
    VRAIE machine, ou il reste l'erreur residuelle de calibration — et le
    budget annonce doit la majorer, sinon il n'annonce rien.
    """
    m, outil = _machine_et_outil()
    rec = build_recipe("aluminium-6061", outil, m, quality=Quality.ROUGHING)
    pts = np.array([[x, y, 12.0 - 0.5 * i]
                    for i, (x, y) in enumerate(
                        [(-20 + 4 * k, -12 + 3 * (k % 5), ) for k in range(30)])])
    op = operation_du_creux(FauxParcours(pts, [False] * len(pts), -15.0, 40.0),
                            outil, rec, m, op_id="creux-1")
    setup = _setup(m, outil)
    h, sm = _portes(setup)

    verite = MachineGeometry(
        machine_id=m.machine_id, measured=True,
        a_axis=AxisLocationError(
            offset_mm=[0.10, -0.20, 0.30],
            direction=list(_rodrigues([0, 0, 1], math.radians(0.20)) @ np.array([1.0, 0, 0]))),
        c_axis=AxisLocationError(
            offset_mm=[-0.15, 0.05, 0.0],
            direction=list(_rodrigues([1, 0, 0], math.radians(0.15)) @ np.array([0, 0, 1.0]))))
    rapport, mesure = calibrate_on_twin(m, verite, probe_noise_mm=0.002, seed=7)
    dossier = record_from_report(m.machine_id, mesure, rapport)

    from xyzac.strategy_planner.interfaces import ProcessPlan
    plan = ProcessPlan(plan_id="ar", setup=setup, operations=[op])
    gcode, emis = post_process(plan, sm, h, dossier, recipe=rec)
    poses = parse_poses(gcode)
    assert len(poses) == len(pts) == emis.n_points

    wo = np.asarray(setup.work_offset.origin_mm, float)
    mount = np.asarray(setup.mount_offset, float)
    pire_mes = pire_vrai = 0.0
    for p, q in zip(pts, poses):
        mv = CompensatedMove(q["X"], q["Y"], q["Z"], q["A"], q["C"], 0.0, 0.0, True, 0)
        pire_mes = max(pire_mes, float(np.linalg.norm(
            realised_pose(m, mesure, mv, work_offset=wo)[0] - (p + mount))))
        pire_vrai = max(pire_vrai, float(np.linalg.norm(
            realised_pose(m, verite, mv, work_offset=wo)[0] - (p + mount))))

    assert pire_mes < 1e-3, f"{pire_mes*1e3:.3f} um au-dela de la quantification"
    assert pire_vrai > 1e-3, "sans erreur residuelle, ce test ne teste rien"
    assert pire_vrai <= dossier.uncertainty_at_100mm_mm, (
        f"residuel {pire_vrai*1e3:.1f} um > budget annonce "
        f"{dossier.uncertainty_at_100mm_mm*1e3:.1f} um")


def test_nothing_is_emitted_without_the_safety_gates():
    """La regle du projet, re-eprouvee sur ce chemin-ci.

    La gamme par creux est une NOUVELLE porte d'entree vers l'emetteur. Une
    porte derobee qui contournerait l'automate de securite annulerait tout le
    reste, et il ne suffit pas que la porte existe ailleurs : il faut qu'elle
    tienne ici.
    """
    m, outil = _machine_et_outil()
    rec = build_recipe("aluminium-6061", outil, m, quality=Quality.ROUGHING)
    op = operation_du_creux(FauxParcours([[0, 0, 0], [5, 0, 0]], [False, False],
                                         0.0, 0.0), outil, rec, m, op_id="creux-1")
    setup = _setup(m, outil)
    from xyzac.strategy_planner.interfaces import ProcessPlan
    plan = ProcessPlan(plan_id="sans-portes", setup=setup, operations=[op])

    h = setup.setup_hash()
    sm = SafetyStateMachine(setup_hash=h)
    sm.define_setup(h)                 # ni collision, ni cinematique, ni simulation
    dossier = _calibration(m)
    with pytest.raises(Exception):
        post_process(plan, sm, h, dossier, recipe=rec)

    # et une geometrie NON MESUREE est refusee meme portes franchies
    sm.pass_collision(True); sm.pass_kinematics(True); sm.pass_simulation(True)
    sm.approve("test")
    from xyzac.assembly_calibration import CalibrationRecord
    nu = CalibrationRecord(machine_id=m.machine_id,
                           geometry=MachineGeometry(machine_id=m.machine_id))
    with pytest.raises(RuntimeError, match="NON MESUREE"):
        post_process(plan, sm, h, nu, recipe=rec)


# ------------------------------------------------------------- utilitaires

def _matiere(mur=None, pitch=1.0):
    """Un brut de 60 x 60 x 30 mm centre sur l'origine piece, plein.

    Construit a la main plutot que voxelise depuis un STEP : ce qui est eprouve
    ici est la REGLE — qui a le droit d'etre dans la matiere, et a quel
    moment — pas le voxeliseur, qui a ses propres tests.

    ``mur`` vide tout sauf une dalle, pour fabriquer un obstacle a l'endroit
    voulu.
    """
    from xyzac.geometry_core.voxelize import VoxelGrid
    from xyzac.stock_engine.material import MaterialState

    g = VoxelGrid.covering(np.array([-30.0, -30.0, 0.0]),
                           np.array([30.0, 30.0, 30.0]), pitch)
    rem = np.ones(g.shape, dtype=bool)
    if mur is not None:
        lo, hi = mur
        rem[:] = False
        i0 = np.floor((np.asarray(lo) - g.origin) / pitch).astype(int)
        i1 = np.ceil((np.asarray(hi) - g.origin) / pitch).astype(int)
        i0 = np.maximum(i0, 0); i1 = np.minimum(i1, g.shape)
        rem[i0[0]:i1[0], i0[1]:i1[1], i0[2]:i1[2]] = True
    return MaterialState(g, rem, np.zeros(g.shape, dtype=bool))


def _setup(machine, outil):
    bb = AABB(np.array([-32.0, -32.0, 0.0]), np.array([32.0, 32.0, 25.0]))
    return Setup(setup_id="m21", machine=machine, part_step_path="(aucune)",
                 stock=stock_from_part(bb, margin_xy=2.0, margin_z_top=2.0,
                                       margin_z_bottom=2.0),
                 tools=[outil], part_to_table_mm=[0.0, 0.0, 20.0])


def _portes(setup):
    h = setup.setup_hash()
    sm = SafetyStateMachine(setup_hash=h)
    sm.define_setup(h)
    sm.pass_collision(True); sm.pass_kinematics(True); sm.pass_simulation(True)
    sm.approve("test m21")
    return h, sm


def _calibration(machine):
    verite = MachineGeometry(machine_id=machine.machine_id, measured=True)
    rapport, mesure = calibrate_on_twin(machine, verite, probe_noise_mm=0.001, seed=3)
    return record_from_report(machine.machine_id, mesure, rapport)


def _emettre(machine, ops, outil):
    from xyzac.strategy_planner.interfaces import ProcessPlan
    setup = _setup(machine, outil)
    h, sm = _portes(setup)
    plan = ProcessPlan(plan_id="m21", setup=setup, operations=ops)
    rec = build_recipe("aluminium-6061", outil, machine, quality=Quality.ROUGHING)
    gcode, _ = post_process(plan, sm, h, _calibration(machine), recipe=rec)
    return gcode


def test_the_plan_verifies_the_machine_it_will_post():
    """Verifier a zero et emettre decale, c'est verifier une AUTRE machine.

    L'emetteur ajoute le decalage de montage et l'origine piece a chaque pose.
    Si la gamme verifiait les positions brutes, elle approuverait un chemin au
    centre du plateau et posterait le meme chemin 100 mm plus loin, dans une
    joue. L'ecart ne se verrait nulle part — jusqu'a la piece.
    """
    fiche = FicheMachine.du_kit()
    m = fiche.machine()
    outil = build_endmill("F10", 10.0, 30.0, stickout=45.0, holder_type="ER16")
    rec = build_recipe("aluminium-6061", outil, m, quality=Quality.ROUGHING)
    demi = fiche.valeur("berceau_largeur_mm") / 2.0

    setup = _setup(m, outil)
    # un montage qui pousse la piece juste dans la joue droite
    setup.part_to_table_mm = [demi - 2.0, 0.0, 10.0]

    au_centre = FauxParcours([[0, 0, 0], [3, 0, 0]], [False, False], 0.0, 0.0)
    plan, verifs, _ = gamme_des_creux(
        setup, [(au_centre, outil, rec)], plan_id="decale",
        material=_matiere(mur=((-30, -30, 0), (-29, -29, 1))))

    assert not verifs[0][1].ok, (
        "le chemin est au centre dans le repère PIÈCE, mais le montage le pose "
        "dans la joue : c'est la position POSTÉE qu'il faut vérifier")
    assert plan.operations == []
