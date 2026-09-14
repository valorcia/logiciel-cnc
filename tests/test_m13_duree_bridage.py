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
