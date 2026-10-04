"""La cinematique de la machine ENTIERE, et le refus qui va avec (jalon M25).

Le defaut
=========

``linuxcnc_gateway.config`` ecrivait ``KINEMATICS = xyzac-trt-kins`` pour
n'importe quelle machine. Ce module de LinuxCNC pose que les articulations 0,
1 et 2 SONT X, Y et Z — vrai sur un portique, faux sur la delta de ce kit, ou
ce sont trois chariots dont la course est celle des colonnes.

Le fichier produit demarrait, prenait son origine, et commandait les chariots
comme des axes cartesiens. Aucune erreur signalee, chaque deplacement faux :
le pire mode d'echec de tout ce projet.

Ce fichier garde les deux moities de la correction : le refus, et la reference
numerique sur laquelle le module C devra s'aligner.
"""

import math

import numpy as np
import pytest

from xyzac.kinematics_solver.delta_ac import (TOLERANCE_ALLER_RETOUR_MM,
                                              Articulations, correspondance_hal,
                                              courses_chariots, direct,
                                              direct_trt, inverse, inverse_trt,
                                              plateforme_depuis_chariots)
from xyzac.linuxcnc_gateway.config import build_config
from xyzac.machine_model.fiche import FicheMachine
from xyzac.machine_model.machine import default_xyzac_kit


def _delta():
    return FicheMachine.du_kit().machine()


# ------------------------------------------------------ 1. le refus

def test_a_delta_machine_is_refused_a_gantry_configuration():
    """**Le cœur de ce jalon.**

    Un fichier qui décrit une autre machine que celle qu'on a est pire qu'une
    absence de fichier : il démarre. Le refus doit donc être total — pas un
    avertissement dans une liste que personne ne lit.
    """
    m = _delta()
    assert m.lineaire_parallele, "le kit de la fiche EST une delta"

    with pytest.raises(RuntimeError) as e:
        build_config(m)
    motif = str(e.value)
    assert "DELTA" in motif
    assert "chariots" in motif.lower()
    # le refus donne les VRAIES butées, pour qu'on voie l'écart
    mini, maxi = courses_chariots(m)
    assert f"{mini:.0f} a {maxi:.0f}" in motif
    # et il dit où est la réponse, au lieu de laisser sans suite
    assert "delta_ac" in motif


def test_a_gantry_machine_is_still_configured():
    """La correction ne doit rien retirer à qui n'a rien demandé.

    Une XYZAC à portique reste exactement la machine de `xyzac-trt-kins`, et sa
    configuration doit continuer de se générer sans un mot de plus.
    """
    m = default_xyzac_kit()
    assert not m.lineaire_parallele
    cfg = build_config(m)
    ini = cfg.ini if isinstance(cfg.ini, str) else "\n".join(cfg.ini)
    assert "xyzac-trt-kins" in ini


# ----------------------------------- 2. la composition, et son aller-retour

def test_the_two_stages_compose_without_a_cross_term():
    """La plateforme de la delta TRANSLATE : c'est ce qui rend la composition
    simple, et c'est une affirmation qui se vérifie.

    Si les deux étages se composaient avec un terme croisé, l'inverse complet
    différerait de « inverse TRT puis formule des chariots ». On compare les
    deux calculs, sur des poses qui font travailler A et C.
    """
    m = _delta()
    hal = correspondance_hal(m)
    for p, a, c in [((0, 0, 0), 0.0, 0.0), ((12, -7, 9), -35.0, 70.0),
                    ((-20, 15, -5), -90.0, -120.0), ((5, 5, 20), -60.0, 180.0)]:
        art = inverse(m, p, a, c)
        xyz = inverse_trt(p, a, c, **hal)
        q = np.asarray(m.delta.chariots(xyz.reshape(1, 3)))[0]
        assert np.allclose(art.q, q, equal_nan=True), (
            f"la composition diffère des deux étages pris séparément en {p}")
        assert art.a_deg == a and art.c_deg == c, (
            "les rotatifs traversent sans être touchés")


def test_the_round_trip_closes_on_the_whole_working_volume():
    """Un inverse sans direct qui le referme n'est qu'une formule.

    La position de plateforme à partir des trois chariots n'existait nulle
    part — `DeltaLineaire` n'en avait pas besoin pour DÉCIDER. Elle est
    résolue ici par intersection de trois sphères, et c'est l'aller-retour qui
    la vérifie.
    """
    m = _delta()
    rng = np.random.default_rng(11)
    pire, n = 0.0, 0
    for _ in range(400):
        p = rng.uniform(-45, 45, 3) * np.array([1.0, 1.0, 0.4])
        a = float(rng.uniform(m.a.min_deg, m.a.max_deg))
        c = float(rng.uniform(-180.0, 180.0))
        art = inverse(m, p, a, c)
        if not art.joignable:
            continue
        pire = max(pire, float(np.linalg.norm(direct(m, art) - p)))
        n += 1
    assert n > 300, f"seulement {n} poses atteignables : l'épreuve ne porte rien"
    assert pire < TOLERANCE_ALLER_RETOUR_MM, f"écart max {pire:.2e} mm"


def test_the_branch_chosen_is_the_one_where_the_arms_go_down():
    """Trois sphères se coupent en DEUX points. L'autre décrirait un montage où
    les bras remontent vers la plateforme — mécaniquement impossible sur ce
    châssis, et c'est le même choix de signe que `DeltaLineaire.chariots`.

    Si les deux modules prenaient des racines différentes, l'aller-retour ne se
    refermerait pas : ce test nomme la raison plutôt que de la laisser
    implicite.
    """
    m = _delta()
    d = m.delta
    p = np.array([8.0, -4.0, 12.0])
    q = np.asarray(d.chariots(p.reshape(1, 3)))[0]
    assert np.all(q > p[2]), "les chariots sont AU-DESSUS de la plateforme"
    retour = plateforme_depuis_chariots(d, q)
    assert np.allclose(retour, p, atol=1e-9)


def test_an_unreachable_pose_is_a_nan_and_not_a_number():
    """Rendre un nombre pour une pose que les bras n'atteignent pas en ferait
    une position. Un NaN compare faux partout, ce qui est le sens voulu."""
    m = _delta()
    art = inverse(m, (0.0, 0.0, 0.0), 0.0, 0.0)
    assert art.joignable
    loin = inverse(m, (10_000.0, 0.0, 0.0), 0.0, 0.0)
    assert not loin.joignable
    assert "hors d'atteinte" in str(loin)


def test_composing_is_refused_on_a_machine_that_has_no_delta():
    """Sur un portique, les trois premières articulations SONT X, Y et Z.

    Rendre la position cartésienne sous un nom qui promet des chariots serait
    exactement la confusion que ce jalon corrige.
    """
    m = default_xyzac_kit()
    with pytest.raises(ValueError, match="pas de structure delta"):
        inverse(m, (0.0, 0.0, 0.0), 0.0, 0.0)
    with pytest.raises(ValueError, match="pas de structure delta"):
        direct(m, Articulations(q=np.zeros(3), a_deg=0.0, c_deg=0.0))


# --------------------------- 3. l'étage TRT est celui de LinuxCNC

def test_the_trt_stage_is_the_one_the_hal_mapping_feeds():
    """Une seule définition des offsets, partagée par le générateur de
    configuration et par ce module.

    C'est sur cette correspondance que le projet s'est déjà trompé une fois :
    la même table écrite deux fois finit par dire deux choses.
    """
    m = _delta()
    hal = correspondance_hal(m)
    pa, pc = np.asarray(m.pivot_a), np.asarray(m.pivot_c)
    assert hal["x_rp"] == pytest.approx(pc[0])
    assert hal["y_rp"] == pytest.approx(pc[1])
    assert hal["dy"] == pytest.approx(pa[1] - pc[1])
    assert hal["dz"] == pytest.approx(pa[2])


def test_the_trt_round_trip_is_exact():
    """`direct_trt` n'est pas recopié d'une seconde source : il est écrit comme
    la composition inverse des rotations, et c'est l'aller-retour qui
    l'établit."""
    hal = dict(x_rp=3.0, y_rp=-2.0, z_rp=1.0, dy=0.7, dz=-40.0)
    rng = np.random.default_rng(5)
    pire = 0.0
    for _ in range(300):
        p = rng.uniform(-60, 60, 3)
        a = float(rng.uniform(-120, 30))
        c = float(rng.uniform(-180, 180))
        xyz = inverse_trt(p, a, c, **hal)
        pire = max(pire, float(np.linalg.norm(direct_trt(xyz, a, c, **hal) - p)))
    assert pire < 1e-9, f"écart max {pire:.2e} mm"


def test_the_transcription_matches_the_published_formula_term_by_term():
    """La transcription de `xyzacKinematicsInverse` doit rester LITTÉRALE.

    Sa fidélité n'est pas prouvée par ce test — elle l'est par
    `tools/verify_kinematics_linuxcnc.py --etage source`, qui COMPILE la
    fonction de LinuxCNC 2.9 et compare les nombres (7,1e-15 mm sur 56 poses).
    Ce test-ci garde le cas dégénéré que n'importe quelle erreur de signe
    casserait, pour que la suite ne passe pas en silence si quelqu'un
    « simplifie » la formule.
    """
    hal = dict(x_rp=0.0, y_rp=0.0, z_rp=0.0, dy=0.0, dz=0.0)
    # A = C = 0 : la cinématique est l'identité
    assert np.allclose(inverse_trt((7.0, -3.0, 11.0), 0.0, 0.0, **hal),
                       [7.0, -3.0, 11.0])
    # C = 90° seul : rotation du plateau dans son plan
    got = inverse_trt((10.0, 0.0, 0.0), 0.0, 90.0, **hal)
    assert np.allclose(got, [0.0, 10.0, 0.0], atol=1e-12)
    # A = 90° seul : le berceau bascule Y vers Z
    got = inverse_trt((0.0, 10.0, 0.0), 90.0, 0.0, **hal)
    assert np.allclose(got, [0.0, 0.0, 10.0], atol=1e-12)
    # et la combinaison n'est pas commutative : si elle l'était, la
    # transcription aurait perdu un terme croisé.
    ac = inverse_trt((10.0, 0.0, 0.0), 45.0, 45.0, **hal)
    ca = inverse_trt((10.0, 0.0, 0.0), 45.0, -45.0, **hal)
    assert not np.allclose(ac, ca)
    assert math.isclose(float(np.linalg.norm(ac)), 10.0, abs_tol=1e-12), (
        "une rotation conserve la norme")
