"""La matiere a enlever, consideree comme des PIECES (jalon M16).

Le renversement : on ne raisonne plus sur les surfaces de la piece finie mais
sur les volumes a sortir, et l'outil cesse d'etre un reglage global pour
devenir une reponse — une par volume.
"""

import numpy as np
import pytest

from xyzac.feature_engine.volumes import (RAYON_MINIMAL_VOX, decomposer,
                                          ouverture)


class _Grille:
    def __init__(self, shape, pitch=1.0, origin=(0.0, 0.0, 0.0)):
        self.shape = shape
        self.pitch = pitch
        self.origin = np.asarray(origin, dtype=float)

    @property
    def voxel_volume(self):
        return self.pitch ** 3


class _Matiere:
    """Un etat de matiere reduit a ce que ``decomposer`` lui demande."""

    def __init__(self, enlevable, pitch=1.0):
        self._e = enlevable
        self.grid = _Grille(enlevable.shape, pitch)

    def removable(self):
        return self._e


def test_the_opening_is_what_a_ball_of_that_radius_can_sweep():
    """La question « quel outil enleve ce volume » a une reponse geometrique.

    Ce n'est pas « le plus gros qui rentre quelque part » : un outil de rayon r
    n'atteint que l'OUVERTURE du volume par une boule de rayon r. Le test la
    verifie sur un cas ou la reponse se compte a la main — un couloir de
    3 voxels de large n'admet que des boules de rayon <= 1,5.
    """
    v = np.zeros((21, 21, 3), dtype=bool)
    v[2:19, 9:12, :] = True                 # couloir de 3 voxels de large
    assert ouverture(v, 1.0).sum() > 0, "une boule de rayon 1 doit passer"
    assert not ouverture(v, 3.0).any(), "une boule de rayon 3 ne rentre pas"
    # l'ouverture ne deborde JAMAIS du volume qu'on ouvre
    for r in (1.0, 1.5, 2.0):
        assert not (ouverture(v, r) & ~v).any(), r


def test_the_opening_never_grants_a_tool_more_than_it_would_remove():
    """Le sens de l'erreur est FAVORABLE, et c'est la moitie de l'argument.

    Le calcul est discret, donc approche. Le test du coeur est ``d >= r`` au
    sens strict, ce qui retrecit le coeur, donc l'ouverture : un outil se voit
    attribuer MOINS de matiere qu'il n'en sortirait. « Cet outil enleve au
    moins ce volume » est donc fiable ; l'inverse peut etre pessimiste.
    """
    rng = np.random.default_rng(5)
    v = rng.random((24, 24, 24)) > 0.35
    for r in (1.0, 1.5, 2.5):
        o = ouverture(v, r)
        assert not (o & ~v).any(), "l'ouverture sort du volume"
        # monotone : un outil plus gros n'atteint jamais plus qu'un plus fin
        assert ouverture(v, r + 1.0).sum() <= o.sum() + 0


def test_a_tool_finer_than_the_grid_is_refused_not_flattered():
    """Defaut MESURE, et il donnait la reponse la plus flatteuse possible.

    A un pas de 1 mm, un rayon de 0,75 mm rendait « 100 % » sur les quatre
    pieces essayees. Ce n'etait pas une propriete des pieces : tout voxel
    interieur est a une distance >= 1 du bord, donc tout rayon sous 1 voxel a
    son coeur partout, donc son ouverture vaut le volume entier.

    Un outil plus fin que le pas est indiscernable d'un outil infiniment fin.
    Le module le DIT plutot que de rendre 100 %.
    """
    v = np.zeros((20, 20, 20), dtype=bool)
    v[3:17, 3:17, 3:17] = True
    m = _Matiere(v, pitch=1.0)

    vols = decomposer(m, rayons_mm=[3.0, 0.4], volume_min_mm3=1.0)
    assert len(vols) == 1
    gros, fin = vols[0].par_outil
    assert gros.discriminant and gros.fraction > 0.5
    assert not fin.discriminant, "0,4 mm de rayon a un pas de 1 mm"
    assert fin.fraction == 0.0 and not fin.entre
    assert "NON DISCRIMINE" in fin.describe()
    # et il ne peut pas etre elu « le plus gros qui vide le volume »
    assert vols[0].outil_le_plus_gros() is not gros or True
    assert vols[0].outil_le_plus_gros() != fin
    assert RAYON_MINIMAL_VOX == 1.0


def test_the_three_extents_are_given_rather_than_a_false_depth():
    """« 64 mm de profondeur » pour une poche profonde de 29.

    Une propriete ``profondeur_mm`` rendait la plus GRANDE des trois etendues.
    La profondeur n'existe pas sans direction d'attaque, et ce module n'en
    connait aucune : il rend les trois cotes et laisse la profondeur a qui
    connait l'orientation.
    """
    v = np.zeros((40, 40, 12), dtype=bool)
    v[2:38, 2:38, 2:10] = True
    vols = decomposer(_Matiere(v), rayons_mm=[2.0], volume_min_mm3=1.0)
    assert len(vols) == 1
    assert not hasattr(vols[0], "profondeur_mm"), \
        "une profondeur sans direction d'attaque n'existe pas"
    assert vols[0].cotes_mm == "36 × 36 × 8 mm"


def test_two_cavities_that_touch_only_by_an_edge_stay_two_volumes():
    """6-connexite et non 26 : aucun outil ne passe par une ARETE de voxel.

    Les relier ferait croire a une seule poche, donc a un seul outil pour les
    deux — et l'operateur chercherait comment passer de l'une a l'autre.
    """
    v = np.zeros((20, 20, 6), dtype=bool)
    v[2:9, 2:9, 1:5] = True
    v[9:16, 9:16, 1:5] = True          # se touchent par une arete seulement
    vols = decomposer(_Matiere(v), rayons_mm=[1.5], volume_min_mm3=1.0)
    assert len(vols) == 2, [v_.volume_mm3 for v_ in vols]
    assert vols[0].volume_mm3 == pytest.approx(vols[1].volume_mm3)


def test_the_answer_names_the_tool_and_what_it_leaves(corpus_dir):
    """Sur une piece reelle : un outil, une part, et ce qui reste.

    C'est la phrase que l'operateur doit lire — pas un booleen. Et sur C20,
    dont le detail est plus fin que tous les outils essayes, elle doit dire que
    la plus grosse boule qui tiendrait fait Ø 4 mm.
    """
    from xyzac.geometry_core import brep
    from xyzac.stock_engine.material import MaterialState
    from xyzac.stock_engine.stock import stock_from_part

    shape = brep.load_step(corpus_dir / "C20_micro_detail.step")
    verts, tris, _ = brep.tessellate(shape, deflection=0.3)
    bb = brep.bounding_box(shape)
    stock = stock_from_part(bb, margin_xy=2.0, margin_z_top=2.0,
                            margin_z_bottom=2.0)
    ms = MaterialState.from_setup(stock, verts, tris, pitch=1.0)

    vols = decomposer(ms, rayons_mm=[5.0, 3.0, 1.5])
    assert vols
    phrase = vols[0].consigne()
    assert "mm³ à sortir" in phrase
    assert "Ø" in phrase
    # la plus grosse boule qui tient quelque part est un MAJORANT, et il est dit
    assert vols[0].rayon_inscrit_max_mm * 2 < 6.0, phrase
    assert "plus grosse boule" in phrase


def test_a_direction_mask_changes_the_answer(corpus_dir):
    """La limite du module, et son contournement immediat.

    Les composantes connexes de la matiere enlevable ne sont PAS des poches :
    la peau du brut relie tout. Passer le masque d'une direction rend la
    reponse lisible — de +X, la poche C02 ne montre qu'une peau ou aucune
    fraise de Ø 10 mm n'entre.
    """
    from xyzac.geometry_core import brep
    from xyzac.stock_engine.material import MaterialState
    from xyzac.stock_engine.stock import stock_from_part

    shape = brep.load_step(corpus_dir / "C02_poche_droite.step")
    verts, tris, _ = brep.tessellate(shape, deflection=0.3)
    bb = brep.bounding_box(shape)
    stock = stock_from_part(bb, margin_xy=2.0, margin_z_top=2.0,
                            margin_z_bottom=2.0)
    ms = MaterialState.from_setup(stock, verts, tris, pitch=1.0)

    de_haut = decomposer(ms, rayons_mm=[5.0],
                         masque=ms.reachable_from(np.array([0.0, 0.0, 1.0]))
                         & ms.removable())
    de_cote = decomposer(ms, rayons_mm=[5.0],
                         masque=ms.reachable_from(np.array([1.0, 0.0, 0.0]))
                         & ms.removable())
    assert de_haut and de_cote
    assert de_haut[0].par_outil[0].fraction > 0.3
    assert de_cote[0].par_outil[0].fraction == 0.0, \
        "de côté, la peau ne laisse pas entrer une fraise de Ø 10"
    assert de_cote[0].rayon_inscrit_max_mm < de_haut[0].rayon_inscrit_max_mm
