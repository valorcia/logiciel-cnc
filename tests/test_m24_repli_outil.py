"""Le choix de l'outil contre la marge de tranchage (jalon M24).

Deux criteres pour « cet outil entre-t-il », et celui qui DECIDAIT n'etait pas
celui qui TRANCHAIT :

  - ``outil_d_ebauche`` retient le plus gros qui entre et atteint le fond — une
    boule de rayon r circulant dans l'espace libre ;
  - le decoupage exige en plus une MARGE entre l'outil et la piece, sans quoi
    il proposerait des positions que le controle de gouge refuserait.

Sur une poche de 12 mm, une Ø 10 entre sans peine et le decoupage ne lui laisse
AUCUNE position : le logiciel annonçait un outil puis rendait un parcours vide.
Seizieme occurrence de la meme famille — une grandeur lue comme si elle
mesurait ce qu'on voulait.
"""

import numpy as np
import pytest

from xyzac.feature_engine.volumes import CAVITE, decomposer
from xyzac.geometry_core import brep
from xyzac.geometry_core.types import AABB
from xyzac.machine_model.fiche import FicheMachine
from xyzac.stock_engine.material import MaterialState
from xyzac.stock_engine.stock import stock_from_part
from xyzac.strategy_planner.creux import (marge_de_tranchage, parcours_creux,
                                          parcours_du_creux)
from xyzac.tool_model import build_endmill

PAS = 1.0
RAYONS = (5.0, 3.0, 1.5)


def _outil(rayon_mm, jauge=45.0):
    return build_endmill(f"F{2 * rayon_mm:.0f}", 2.0 * rayon_mm, 30.0,
                         stickout=jauge, holder_type="ER16")


# ----------------------------- 1. l'hypothese du confinement, prouvee

def test_a_thinner_tool_of_the_same_family_is_contained_in_the_bigger_one():
    """**L'hypothèse qui autorise à ne pas refaire la vérification d'orientation.**

    Descendre d'outil après l'étape 3 ne serait légitime que si le plus fin est
    CONTENU dans le plus gros : toute pose dégagée pour l'un le serait alors
    pour l'autre. C'est vrai pour cette famille — même porte-outil, même jauge,
    arête et tige de rayon plus petit — mais le supposer serait exactement ce
    que ce projet refuse. On le vérifie tronçon par tronçon.
    """
    gros, fin = _outil(5.0), _outil(3.0)
    par_role_gros = {}
    for s in gros.segments:
        par_role_gros.setdefault(s.role.value, []).append(s)

    for s in fin.segments:
        jumeaux = par_role_gros.get(s.role.value, [])
        assert jumeaux, f"le rôle {s.role.value} n'existe pas sur le gros outil"
        # à la même hauteur, le fin ne doit JAMAIS être plus large
        for z in np.linspace(s.z_start, s.z_end, 9):
            r_fin = s.r_start + (s.r_end - s.r_start) * (
                0.0 if s.z_end == s.z_start else (z - s.z_start) / (s.z_end - s.z_start))
            r_gros = max(
                (g.r_start + (g.r_end - g.r_start) * (
                    0.0 if g.z_end == g.z_start else (z - g.z_start) / (g.z_end - g.z_start))
                 for g in jumeaux if g.z_start - 1e-9 <= z <= g.z_end + 1e-9),
                default=None)
            assert r_gros is not None, (
                f"le gros outil n'occupe pas z = {z:.1f} sur le rôle {s.role.value}")
            assert r_fin <= r_gros + 1e-9, (
                f"à z = {z:.1f}, le Ø 6 ({r_fin:.2f}) déborde le Ø 10 ({r_gros:.2f})")
    assert gros.total_length == pytest.approx(fin.total_length), (
        "même jauge : sinon le fin pourrait dépasser en longueur")


# ------------------------------- 2. le défaut, sur une poche construite

def _poche(largeur_mm, longueur_mm=24.0, profondeur_mm=9.0):
    """Un bloc avec UNE poche droite de la largeur demandée, voxelisé."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    bloc = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 60.0, 40.0, 20.0).Shape()
    poche = BRepPrimAPI_MakeBox(
        gp_Pnt(30.0 - largeur_mm / 2.0, 20.0 - longueur_mm / 2.0,
               20.0 - profondeur_mm),
        largeur_mm, longueur_mm, profondeur_mm).Shape()
    forme = BRepAlgoAPI_Cut(bloc, poche).Shape()
    verts, tris, _ = brep.tessellate(forme, deflection=0.3)
    bb = brep.bounding_box(forme)
    stock = stock_from_part(bb, margin_xy=2.0, margin_z_top=2.0,
                            margin_z_bottom=2.0)
    matiere = MaterialState.from_setup(stock, verts, tris, pitch=PAS)
    creux = [v for v in decomposer(matiere, rayons_mm=list(RAYONS),
                                   separer_peau=True) if v.nature == CAVITE]
    assert len(creux) == 1, f"attendu une poche, trouvé {len(creux)}"
    return matiere, creux[0]


def _verdict(volume, rayon_mm, machine):
    """Le verdict qu'aurait rendu l'étape 3 : ouverture vers le haut."""
    from xyzac.strategy_planner.creux import ETAPE_AUCUNE, VerdictCreux

    return VerdictCreux(index=volume.index, etape=ETAPE_AUCUNE,
                        volume_mm3=volume.volume_mm3, cotes_mm=volume.cotes_mm,
                        rayon_mm=rayon_mm, fraction=1.0,
                        a_deg=0.0, c_deg=0.0, visibilite=1.0)


def test_a_tool_that_enters_can_still_have_no_sliceable_position():
    """Le fait brut, avant toute correction : la Ø 10 entre, et ne coupe rien.

    Une poche de 12 mm accepte une fraise de Ø 10 — 10 < 12 — mais le découpage
    garde 1,87 mm entre l'outil et la pièce au pas de 1 mm, et 5 + 1,87 = 6,87
    dépasse la demi-largeur de 6.
    """
    m = FicheMachine.du_kit().machine()
    matiere, volume = _poche(12.0)
    assert marge_de_tranchage(PAS) > 1.8

    gros = volume.outil_d_ebauche()
    assert gros is not None and gros.rayon_mm == 5.0, (
        "l'étape 2 choisit bien la Ø 10 : elle entre et atteint le fond")

    vide = parcours_creux(volume, _verdict(volume, 5.0, m), matiere,
                          _outil(5.0), m)
    assert len(vide.points) == 0, "c'est le défaut : un outil annoncé, rien à faire"

    # et une Ø 6, elle, a de la place
    bon = parcours_creux(volume, _verdict(volume, 3.0, m), matiere,
                         _outil(3.0), m)
    assert len(bon.points) > 0


def test_the_planner_steps_down_to_the_biggest_tool_that_can_be_sliced():
    """La correction : on pose la question à celui qui sait y répondre.

    Et on prend le plus GROS qui marche, pas le plus fin — descendre jusqu'à la
    Ø 3 serait une heure de travail pour ce qu'une Ø 6 fait en quelques
    minutes.
    """
    m = FicheMachine.du_kit().machine()
    matiere, volume = _poche(12.0)

    verdict, parcours = parcours_du_creux(
        volume, _verdict(volume, 5.0, m), matiere, m, fabrique_outil=_outil)

    assert len(parcours.points) > 0, "il doit maintenant y avoir un parcours"
    assert verdict.rayon_mm == 3.0, "la Ø 6, pas la Ø 3"
    assert parcours.rayon_mm == 3.0, (
        "le parcours et le verdict doivent parler du MÊME outil")
    assert verdict.repli_de_mm == 5.0


def test_the_substitution_is_said_and_not_silent():
    """Un outil remplacé en silence ferait mentir toutes les phrases d'avant.

    L'écran annonce l'outil du verdict ; si le verdict n'était pas reconstruit,
    il dirait Ø 10 au-dessus d'un parcours de Ø 6.
    """
    m = FicheMachine.du_kit().machine()
    matiere, volume = _poche(12.0)
    verdict, _ = parcours_du_creux(volume, _verdict(volume, 5.0, m), matiere, m,
                                   fabrique_outil=_outil)
    phrase = verdict.consigne()
    assert "Ø 6 mm" in verdict.outil
    assert "Ø 10 mm y entre" in phrase
    assert "aucune position" in phrase
    assert "marge" in phrase


def test_a_tool_that_works_is_never_replaced():
    """La correction ne doit pas coûter un outil à ceux qui n'ont rien demandé.

    Une poche large reçoit la Ø 10 et doit la garder : descendre d'un cran
    « par prudence » serait une dégradation déguisée en sécurité.
    """
    m = FicheMachine.du_kit().machine()
    matiere, volume = _poche(24.0)
    verdict, parcours = parcours_du_creux(
        volume, _verdict(volume, 5.0, m), matiere, m, fabrique_outil=_outil)
    assert verdict.rayon_mm == 5.0
    assert verdict.repli_de_mm is None
    assert "y entre, mais le découpage" not in verdict.consigne()
    assert len(parcours.points) > 0


def test_when_no_tool_can_be_sliced_the_refusal_is_kept_and_explained():
    """Descendre d'outil n'est pas une promesse de réussir.

    Sur une poche plus étroite que la plus petite fraise + sa marge, il n'y a
    rien à proposer — et c'est le message d'origine, qui nomme la marge et
    donne les deux leviers, qui doit rester.
    """
    m = FicheMachine.du_kit().machine()
    matiere, volume = _poche(5.0)
    verdict, parcours = parcours_du_creux(
        volume, _verdict(volume, 1.5, m), matiere, m, fabrique_outil=_outil)
    assert len(parcours.points) == 0
    assert verdict.repli_de_mm is None, (
        "aucun repli n'a abouti : ne pas prétendre qu'il y en a eu un")
    assert "marge" in parcours.consigne() or "mm" in parcours.consigne()


def test_the_finishing_tool_is_recomputed_on_the_new_roughing_tool():
    """« On ébauche à la Ø 6, reprise à Ø 6 » est une phrase qui se contredit.

    La reprise est, à l'étape 2, le plus gros outil strictement plus fin que
    celui d'ébauche et qui en prend davantage. Après un repli, l'outil
    d'ébauche a changé : garder l'ancienne reprise peut désigner l'outil qu'on
    vient de retenir pour ébaucher.
    """
    m = FicheMachine.du_kit().machine()
    matiere, volume = _poche(12.0)
    verdict, _ = parcours_du_creux(volume, _verdict(volume, 5.0, m), matiere, m,
                                   fabrique_outil=_outil)
    assert verdict.rayon_mm == 3.0
    assert verdict.reprise_mm is None or verdict.reprise_mm < verdict.rayon_mm, (
        f"reprise Ø {verdict.reprise_mm} sur une ébauche Ø {verdict.rayon_mm}")
    phrase = verdict.consigne()
    if verdict.reprise_mm is not None:
        assert phrase.index("ébauche") < phrase.index("Reprise")
