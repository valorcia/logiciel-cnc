"""Le TEMPS d'usinage et le BRIDAGE (jalon M13b, M13c).

Deux sujets, une meme discipline : un chiffre doit dire sa portee, et une
reserve doit se calculer. Le temps est un MINORANT et le dit ; le bridage est
une hypothese dont l'erreur va dans le sens favorable, et le dit aussi.
"""

import numpy as np
import pytest

from xyzac.machine_model.machine import default_xyzac_kit


# ------------------------------------------------------------- le temps

def test_the_cycle_time_is_announced_as_a_floor_never_as_an_estimate():
    """« au moins », jamais « environ ».

    Les accelerations, l'anticipation, les changements d'outil et le palpage
    ne sont pas modelises : le chiffre est donc systematiquement OPTIMISTE.
    Quelqu'un organisera sa journee dessus, et la reserve doit voyager avec le
    nombre — pas en note de bas de page.
    """
    from xyzac.strategy_planner.duree import MANQUES, Duree

    d = Duree(longueur_coupe_mm=1000.0, longueur_rapide_mm=5000.0,
              coupe_s=120.0, rapide_s=75.0, rotation_s=5.0,
              n_reindexations=2, avance_coupe_mm_min=500.0, manques=MANQUES)
    p = d.consigne()
    assert "Au moins" in p
    assert "environ" not in p.lower()
    assert "accélérations" in p
    assert "changements d'outil" in p
    assert abs(d.total_s - 200.0) < 1e-9
    assert abs(d.part_en_coupe - 0.6) < 1e-9


def test_the_rapid_feed_is_limited_by_the_first_axis_to_saturate():
    """Une diagonale n'est pas plus rapide que son axe le plus lent.

    Prendre la plus petite des trois avances maximales serait pessimiste sur
    un mouvement selon un seul axe ; prendre la plus grande serait faux. La
    vitesse d'un vecteur est ``min_i (V_i / |d_i|)``.
    """
    from xyzac.strategy_planner.duree import avance_rapide_mm_min

    m = default_xyzac_kit()          # X 4000, Y 4000, Z 3000 mm/min
    f = avance_rapide_mm_min(m, np.array([
        [1.0, 0.0, 0.0],             # X seul : 4000
        [0.0, 0.0, 1.0],             # Z seul : 3000
        [0.0, 0.7071, 0.7071],       # Y+Z : bride par Z
    ]))
    assert abs(f[0] - 4000.0) < 1e-6
    assert abs(f[1] - 3000.0) < 1e-6
    assert abs(f[2] - 3000.0 / 0.7071) < 1.0
    assert f[2] < 4000.0 / 0.7071, "l'axe le plus lent doit imposer sa loi"


def test_the_length_is_measured_in_the_machine_frame(monkeypatch):
    """Les longueurs sont les memes dans les deux reperes, les DIRECTIONS non.

    Une rotation conserve les distances, donc mesurer la longueur dans le
    repere piece serait juste. Mais c'est la direction qui decide quel axe
    sature : un deplacement selon X de la piece, a A = -90° et C = -90°, est
    un deplacement selon Y de la machine — avec une autre avance maximale.
    """
    from xyzac.strategy_planner.duree import duree_trajectoire

    m = default_xyzac_kit()
    # un aller RAPIDE de 100 mm selon Z de la piece
    P = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 100.0]])
    rapide = np.array([True, True])

    # a A = 0 : Z piece = Z machine, bride a 3000 mm/min
    _, l1, _, t1 = duree_trajectoire(m, P, rapide, (0, 0, 0), 0.0, 0.0,
                                     avance_coupe_mm_min=500.0)
    # a A = -90 : Z piece devient Y machine, bride a 4000 mm/min
    _, l2, _, t2 = duree_trajectoire(m, P, rapide, (0, 0, 0), -90.0, 0.0,
                                     avance_coupe_mm_min=500.0)
    assert abs(l1 - 100.0) < 1e-6 and abs(l2 - 100.0) < 1e-6, \
        "la longueur ne depend pas de l'orientation"
    assert t2 < t1, "mais le temps si : l'axe employe n'est pas le meme"
    assert abs(t1 - 100.0 / 3000.0 * 60.0) < 1e-6
    assert abs(t2 - 100.0 / 4000.0 * 60.0) < 1e-6


def test_a_reindexation_turns_both_axes_at_once():
    """A et C partent ensemble : le temps est le MAXIMUM, pas la somme.

    Les additionner surestimerait — ce qui, pour un minorant declare, serait
    une incoherence interne.
    """
    from xyzac.strategy_planner.duree import duree_rotation_s

    m = default_xyzac_kit()          # A 3600 °/min, C 7200 °/min
    t = duree_rotation_s(m, 0.0, 0.0, -90.0, 180.0)
    assert abs(t - max(90.0 / 3600.0, 180.0 / 7200.0) * 60.0) < 1e-9
    assert t < (90.0 / 3600.0 + 180.0 / 7200.0) * 60.0


def test_no_time_is_shown_when_the_material_is_unknown():
    """``recipe_profiles`` refuse de deviner : l'atelier n'invente pas d'avance.

    Un temps calcule sur une avance inventee serait la fausse valeur type.
    L'interface affiche alors ce qui manque — la matiere — et pas un zero.
    """
    from xyzac.ui.atelier.session import Coupe
    from xyzac.tool_model import build_ballnose

    t = build_ballnose("bn", 6.0, 20.0, stickout=45.0, holder_type="ER16")
    m = default_xyzac_kit()
    assert Coupe(matiere="aluminium-6061").recette(t, m) is not None
    assert Coupe(matiere="titane-grade-5").recette(t, m) is None
    assert "aluminium-6061" in Coupe.matieres()


# ------------------------------------------------------------- le bridage

def test_a_vise_grips_from_underneath_and_overhangs_the_part():
    """Les deux cotes que l'operateur lit sur son etau.

    ``prise_mm`` est mesuree depuis le DESSOUS : c'est ainsi qu'on serre.
    ``debord_mm`` etend les mors au-dela de la piece, parce qu'un etau est
    plus large que ce qu'il tient — et l'oublier SOUS-estimerait l'obstacle,
    la seule erreur a ne pas commettre ici.
    """
    from xyzac.machine_model.bridage import etau

    lo, hi = (0.0, 0.0, 0.0), (70.0, 50.0, 53.0)
    mors = etau(lo, hi, axe="x", prise_mm=12.0, epaisseur_mors_mm=20.0,
                debord_mm=10.0)
    assert len(mors) == 2
    for f in mors:
        assert f.lo[2] == 0.0 and f.hi[2] == 12.0, "prise depuis le dessous"
        assert f.lo[1] < 0.0 and f.hi[1] > 50.0, "debord dans l'autre axe"
    # les deux mors serrent de part et d'autre, sans traverser la piece
    gauche, droite = sorted(mors, key=lambda f: f.lo[0])
    assert gauche.hi[0] <= 0.0 and droite.lo[0] >= 70.0

    with pytest.raises(ValueError):
        etau(lo, hi, axe="z")
    with pytest.raises(ValueError):
        etau(lo, hi, prise_mm=0.0)


def test_a_clamp_body_sits_outside_the_part_and_its_nose_bites_it():
    """Defaut corrige : les brides etaient posees a l'INTERIEUR de la piece.

    Le signe du corps etait inverse : les brides interdisaient d'usiner le
    centre de la piece et laissaient ses bords libres — exactement l'inverse
    d'un bridage. Le test verifie les deux bouts : le corps dehors, le nez
    dedans.
    """
    from xyzac.machine_model.bridage import brides_sur_plateau

    lo, hi = (0.0, 0.0, 0.0), (70.0, 50.0, 53.0)
    brides = brides_sur_plateau(lo, hi, n=4, recouvrement_mm=6.0,
                                longueur_mm=40.0, hauteur_mm=12.0)
    assert len(brides) == 4
    for f in brides:
        # le corps sort de la piece par un bord au moins
        dehors = (f.lo[0] < lo[0] - 1e-9 or f.hi[0] > hi[0] + 1e-9
                  or f.lo[1] < lo[1] - 1e-9 or f.hi[1] > hi[1] + 1e-9)
        assert dehors, f"{f.name} ne sort pas de la piece : {f.lo} {f.hi}"
        # et le nez la recouvre
        chevauche = (min(f.hi[0], hi[0]) > max(f.lo[0], lo[0])
                     and min(f.hi[1], hi[1]) > max(f.lo[1], lo[1]))
        assert chevauche, f"{f.name} ne mord pas la piece : {f.lo} {f.hi}"
        assert f.hi[2] == 12.0

    # moins de quatre brides : les GRANDS cotes d'abord, la ou ça bascule
    deux = brides_sur_plateau(lo, hi, n=2)
    assert len(deux) == 2
    assert all("Y" in f.name for f in deux), [f.name for f in deux]


def test_a_declared_fixture_reaches_every_verdict(corpus_dir):
    """Il suffit de le DECLARER : rien d'autre a brancher.

    ``build_scene`` echantillonne les bridages depuis le jalon M1. Le montage
    n'en portait simplement jamais, et tous les verdicts etaient donc
    optimistes. Ce test verifie que le declarer change le champ d'obstacles —
    donc le solveur d'accessibilite, la porte d'entree en matiere et la
    verification de finition, qui le lisent tous.
    """
    from xyzac.ui.debug.state import BenchState
    from xyzac.machine_model.bridage import etau

    st = BenchState()
    st.load_step(corpus_dir / "C01_bloc_simple.step")
    st.set_default_tool("ballnose", diameter=6.0, stickout=45.0)
    sans = len(st.obstacle_field())

    bb = st.part.bbox
    st.fixtures = etau(bb.lo, bb.hi, prise_mm=12.0)
    st._obstacles = None
    avec = len(st.obstacle_field())
    assert avec > sans, "un bridage declare doit ajouter des obstacles"
    assert st.build_setup().fixtures, "et entrer dans le montage"


def test_the_fixture_reserve_disappears_when_a_fixture_is_declared():
    """« les brides ne sont pas modelisees du tout » etait vrai hier.

    Une phrase qui decrit un manque survit a la disparition du manque si on ne
    la calcule pas. Celle-ci se calcule, et son contraire aussi : un verdict
    rendu AVEC bridage doit dire lequel, sans quoi l'operateur ne peut pas
    reconnaitre son montage.
    """
    from xyzac.ui.atelier.session import Bridage

    aucun = Bridage()
    assert not aucun.fixtures_declares()
    assert "OPTIMISTES" in aucun.resume()
    assert aucun.fixtures((0, 0, 0), (10, 10, 10)) == []

    avec = Bridage(forme="etau", prise_mm=12.0)
    assert avec.fixtures_declares()
    assert "Étau" in avec.resume() and "12 mm" in avec.resume()
    assert len(avec.fixtures((0, 0, 0), (10, 10, 10))) == 2

    brides = Bridage(forme="brides", n_brides=3.0)
    assert len(brides.fixtures((0, 0, 0), (40, 20, 10))) == 3


# ------------------------------------------- la delta lineaire (M14)

def _delta():
    from xyzac.machine_model.delta import DeltaLineaire

    return DeltaLineaire(rayon_base_mm=150.0, rayon_plateforme_mm=40.0,
                         longueur_bras_mm=250.0,
                         chariot_min_mm=0.0, chariot_max_mm=300.0)


def _machine_delta():
    m = default_xyzac_kit().model_copy(deep=True)
    m.delta = _delta()
    return m


def test_the_inverse_kinematics_puts_the_ball_joints_exactly_one_arm_apart():
    """La verification qui ne ment pas : reconstruire la longueur du bras.

    Une cinematique inverse se trompe silencieusement — elle rend toujours un
    nombre. Le seul controle qui vaille est de remonter a la grandeur physique
    qu'elle est censee respecter : l'entraxe des rotules doit valoir L, et pas
    « a peu pres ».
    """
    d = _delta()
    rng = np.random.default_rng(7)
    P = rng.uniform([-60, -60, 40], [60, 60, 160], size=(500, 3))
    q = d.chariots(P)
    assert np.isfinite(q).all()
    th = np.radians(np.asarray(d.angles_deg))
    for i in range(3):
        base = np.stack([np.full(len(P), d.rayon_base_mm * np.cos(th[i])),
                         np.full(len(P), d.rayon_base_mm * np.sin(th[i])),
                         q[:, i]], axis=1)
        plat = P + np.array([d.rayon_plateforme_mm * np.cos(th[i]),
                             d.rayon_plateforme_mm * np.sin(th[i]), 0.0])
        ecart = np.abs(np.linalg.norm(base - plat, axis=1) - d.longueur_bras_mm)
        assert ecart.max() < 1e-9, ecart.max()


def test_the_reach_does_not_depend_on_height():
    """Ce qui rend le volume analysable : la portee des bras est HORIZONTALE.

    ``a² + b²`` ne contient pas z. La contrainte de longueur de bras est donc
    un disque par colonne, et leur intersection — convexe — est l'empreinte
    atteignable. Monter ou descendre ne change que la butee de chariot.
    """
    d = _delta()
    p = np.array([[17.0, -23.0, 0.0]])
    portees = [d.portee(p + np.array([0.0, 0.0, z])) for z in (0.0, 50.0, 130.0)]
    for autre in portees[1:]:
        assert np.allclose(portees[0], autre)


def test_a_straight_segment_is_decided_exactly_not_sampled():
    """LA propriete a laquelle ce projet tient, et elle survit au parallele.

    Sur un portique, le domaine des courses est un pave : convexe, donc tester
    les deux bouts suffit. Ici le volume n'est pas convexe, et un segment peut
    SORTIR entre deux sommets qui tiennent. L'exactitude se demontre au lieu de
    se lire :

      * la portee des bras est une parabole convexe en t, maximum aux bouts ;
      * la position de chariot est concave en t, minimum aux bouts ;
      * son maximum interieur est la racine d'une equation du second degre.

    Le test compare le verdict exact a un echantillonnage a 401 points sur
    2 000 segments tires au hasard. Zero faux positif est la seule valeur
    acceptable : un faux positif est une machine qui part en butee.
    """
    d = _delta()
    rng = np.random.default_rng(11)
    faux_positifs = desaccords = 0
    for _ in range(2000):
        p0 = rng.uniform([-120, -120, -20], [120, 120, 260], size=3)
        p1 = p0 + rng.uniform(-90, 90, size=3)
        exact = d.segment_tient(p0, p1)
        t = np.linspace(0.0, 1.0, 401)[:, None]
        echantillon = bool(d.atteignable(p0 + t * (p1 - p0)).all())
        if exact and not echantillon:
            faux_positifs += 1
        if exact != echantillon:
            desaccords += 1
    assert faux_positifs == 0, f"{faux_positifs} segments declares bons a tort"
    assert desaccords == 0, desaccords


def test_a_segment_can_leave_the_volume_between_two_good_ends():
    """La non-convexite, montree plutot qu'affirmee.

    Si ce test ne trouvait aucun cas, c'est que le volume serait convexe et que
    tout le raisonnement precedent serait inutile. Il en existe, et c'est
    exactement pourquoi tester les sommets d'une polyligne ne suffit plus.
    """
    d = _delta()
    rng = np.random.default_rng(3)
    trouve = 0
    for _ in range(4000):
        p0 = rng.uniform([-100, -100, 0], [100, 100, 240], size=3)
        p1 = rng.uniform([-100, -100, 0], [100, 100, 240], size=3)
        if not (d.atteignable(p0[None, :])[0] and d.atteignable(p1[None, :])[0]):
            continue
        t = np.linspace(0.0, 1.0, 201)[:, None]
        if not d.atteignable(p0 + t * (p1 - p0)).all():
            trouve += 1
            assert not d.segment_tient(p0, p1), \
                "le test exact doit refuser ce segment"
    assert trouve > 0, "aucun contre-exemple : le volume serait convexe ?"


def test_the_travel_verdict_asks_the_machine_instead_of_assuming_a_box():
    """Le depassement d'une delta se mesure en millimetres de RAIL.

    Nommer un axe X, Y ou Z n'aurait aucun sens : les trois chariots melangent
    les trois coordonnees. Et « aucun remede » y recouvre deux causes tres
    differentes — hors de portee des bras, ou aucun decalage essaye ne suffit —
    que la version cartesienne confondait en une phrase absurde (« il manque
    0 mm de plus que toute la course X »).
    """
    from xyzac.strategy_planner.travel import course_lineaire

    m = _machine_delta()
    P = np.array([[0.0, 0.0, 0.0], [20.0, 0.0, 0.0], [20.0, 20.0, 0.0]])

    trop_haut = course_lineaire(m, P, (0, 0, 120), 0.0, 0.0, exact=True)
    assert trop_haut.parallele and not trop_haut.tient
    assert trop_haut.axe_le_plus_court == "chariot"
    assert "course de chariot" in trop_haut.consigne()

    # le remede propose doit AVOIR ETE VERIFIE : on le rejoue.
    assert trop_haut.correction_piece_mm is not None
    corrige = course_lineaire(
        m, P, np.array([0.0, 0.0, 120.0]) + np.asarray(
            trop_haut.correction_piece_mm), 0.0, 0.0, exact=True)
    assert corrige.tient, corrige.describe()

    # hors de PORTEE des bras : aucune longueur de rail n'y changerait rien
    loin = course_lineaire(m, np.array([[0.0, 0.0, 100.0], [400.0, 0.0, 100.0]]),
                           (0, 0, 0), 0.0, 0.0, exact=True)
    assert loin.correction_piece_mm is None
    assert "PORTÉE des bras" in loin.consigne()
    assert "course X" not in loin.consigne()


def test_the_cartesian_machine_is_untouched_by_the_delta_branch():
    """Les deux cinematiques coexistent, et la cartesienne garde son exactitude.

    La partie ROTATIVE est la meme — une table A/C sous une broche qui ne fait
    que translater —, et c'est elle qui porte tout le raisonnement 3+2. Seule
    la moitie lineaire change.
    """
    from xyzac.strategy_planner.travel import course_lineaire

    m = default_xyzac_kit()
    assert not m.lineaire_parallele
    c = course_lineaire(m, np.array([[0.0, 0.0, 0.0], [10.0, 10.0, 10.0]]),
                        (0, 0, 25), 0.0, 0.0, exact=True)
    assert not c.parallele and c.tient
    assert _machine_delta().lineaire_parallele
