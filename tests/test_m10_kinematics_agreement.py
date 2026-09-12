"""Accord numerique entre la cinematique du projet et celle de LinuxCNC.

Ce que ces tests etablissent : que ``part_to_machine_point`` et
``xyzacKinematicsInverse`` calculent la MEME fonction, avec la correspondance
de broches que ``build_config`` ecrit reellement dans le HAL.

La formule de LinuxCNC est ici TRANSCRITE (``trtfuncs.c``). Cette transcription
a ete verifiee contre la fonction COMPILEE — ecart max 7,1e-15 mm sur 56 poses
— par ``tools/verify_kinematics_linuxcnc.py --etage source``, qui demande un
arbre source LinuxCNC et n'a donc pas sa place dans la suite. La procedure et
le resultat sont consignes dans ``docs/validation-linuxcnc.md``.

Point de methode : la correspondance n'est pas recopiee ici, elle est LUE dans
le HAL produit. Une copie testerait la copie ; c'est exactement de cette
maniere qu'un [JOINT_5] ecrit a la main a survecu a un JOINT_AXIS disant 4.
"""

import itertools
import math

import numpy as np
import pytest

from xyzac.kinematics_solver.solver import KinematicsSolver
from xyzac.linuxcnc_gateway import KINEMATICS_MODULE, build_config
from xyzac.machine_model import default_xyzac_kit

POINTS = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 12.0, 0.0),
          (0.0, 0.0, 15.0), (7.0, -3.0, 11.0), (-18.0, 22.0, -8.0),
          (23.3, 12.7, 5.5)]
ANGLES = [(0.0, 0.0), (0.0, 90.0), (0.0, -37.0), (-30.0, 0.0),
          (-75.0, 120.0), (-45.0, -160.0), (-12.5, 33.3), (25.0, 210.0)]

#: Pivots volontairement grands. Avec des pivots nuls, TOUTE correspondance de
#: broches — juste ou fausse — donne le meme resultat : le test ne serait pas
#: faux, il serait aveugle. Le test de sensibilite ci-dessous est ce qui
#: interdit d'y revenir sans le voir.
PIVOT_C = [1.5, -2.5, 4.0]
PIVOT_A = [0.7, 3.1, -39.2]


def _machine(pc=PIVOT_C, pa=PIVOT_A):
    m = default_xyzac_kit().model_copy(deep=True)
    m.pivot_c = list(pc)
    m.pivot_a = list(pa)
    return m


def _pins_du_hal(cfg) -> dict[str, float]:
    """Valeurs que le HAL genere pose sur les broches de la cinematique."""
    pins = {}
    for ligne in cfg.hal.splitlines():
        if not ligne.startswith("setp"):
            continue
        _, pin, valeur = ligne.split()
        if pin.startswith(KINEMATICS_MODULE + "."):
            pins[pin.split(".", 1)[1]] = float(valeur)
    return pins


def _linuxcnc_inverse(pos, a_deg, c_deg, pins):
    """Transcription litterale de ``xyzacKinematicsInverse`` (trtfuncs.c).

    Les broches absentes du HAL valent 0, comme dans LinuxCNC : une broche que
    personne ne pose garde sa valeur initiale. C'est pourquoi ne PAS ecrire
    ``x-offset`` est correct (la cinematique xyzac ne la lit pas) alors que ne
    pas ecrire ``x-rot-point`` serait une erreur silencieuse.
    """
    x_rp = pins.get("x-rot-point", 0.0)
    y_rp = pins.get("y-rot-point", 0.0)
    z_rp = pins.get("z-rot-point", 0.0)
    dy = pins.get("y-offset", 0.0)
    dz = pins.get("z-offset", 0.0) + pins.get("tool-offset", 0.0)
    a = math.radians(a_deg)
    c = math.radians(c_deg)
    px, py, pz = pos
    return np.array([
        math.cos(c) * (px - x_rp) - math.sin(c) * (py - y_rp) + x_rp,
        (math.sin(c) * math.cos(a) * (px - x_rp)
         + math.cos(c) * math.cos(a) * (py - y_rp)
         - math.sin(a) * (pz - z_rp)
         - math.cos(a) * dy + math.sin(a) * dz + dy + y_rp),
        (math.sin(c) * math.sin(a) * (px - x_rp)
         + math.cos(c) * math.sin(a) * (py - y_rp)
         + math.cos(a) * (pz - z_rp)
         - math.sin(a) * dy - math.cos(a) * dz + dz + z_rp),
    ])


def _ecart_max(machine, pins) -> float:
    ks = KinematicsSolver(machine)
    pire = 0.0
    for p, (a, c) in itertools.product(POINTS, ANGLES):
        mien = ks.part_to_machine_point(np.asarray(p, dtype=float), a, c)
        leur = _linuxcnc_inverse(p, a, c, pins)
        pire = max(pire, float(np.max(np.abs(mien - leur))))
    return pire


def test_the_two_kinematics_agree_through_the_generated_hal():
    """Le recoupement central.

    Ce que la correspondance FAUSSE donnait, mesure : 10,286 mm d'ecart. Ce
    n'est pas une subtilite numerique, c'est un centimetre sur la piece.
    """
    m = _machine()
    pins = _pins_du_hal(build_config(m))
    assert _ecart_max(m, pins) < 1e-9


@pytest.mark.parametrize("pc,pa", [
    ([0, 0, 0], [0, 0, -40]),
    ([1.5, -2.5, 0], [0, 0, -40]),
    ([0, 0, 0], [0.7, 3.1, -39.2]),
    ([-12.0, 8.0, -3.0], [5.0, -6.0, -55.0]),
])
def test_agreement_holds_for_any_pivot_configuration(pc, pa):
    m = _machine(pc, pa)
    assert _ecart_max(m, _pins_du_hal(build_config(m))) < 1e-9


@pytest.mark.parametrize("pin", ["x-rot-point", "y-rot-point", "y-offset",
                                 "z-offset"])
def test_the_comparison_actually_sees_each_pin(pin):
    """Un test d'accord qui passerait quoi qu'on fasse ne protege de rien.

    Chaque broche employee est perturbee de 1 mm, et l'accord doit se rompre.
    Si une perturbation ne change rien, c'est que la broche n'entre pas dans
    la comparaison — donc que le test est aveugle a son sujet. C'est le defaut
    de forme le plus repandu de ce projet, et il se detecte ainsi : faire
    varier le parametre et exiger que la grandeur bouge.
    """
    m = _machine()
    pins = _pins_du_hal(build_config(m))
    assert pin in pins, f"{pin} n'est pas posee par le HAL : {sorted(pins)}"
    faux = dict(pins)
    faux[pin] = faux[pin] + 1.0
    assert _ecart_max(m, faux) > 0.5, (
        f"perturber {pin} de 1 mm ne change pas le resultat : la comparaison "
        "ne la voit pas")


def test_a_dead_pin_cannot_carry_the_calibration():
    """``x-offset`` n'est lue que par la variante xyzbc.

    Y porter la composante X de l'axe C — ce que faisait le HAL — est
    indetectable a l'execution : ni erreur, ni effet. Ici on le rend
    detectable : la poser ne doit RIEN changer, et c'est precisement pourquoi
    elle ne doit pas etre employee.
    """
    m = _machine()
    pins = _pins_du_hal(build_config(m))
    reference = _ecart_max(m, pins)
    avec = dict(pins)
    avec["x-offset"] = 25.0
    assert _ecart_max(m, avec) == pytest.approx(reference, abs=1e-12)
