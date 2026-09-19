"""Abaisser les liaisons : le plus gros levier de temps du projet.

``continuous_path`` relie deux passes en remontant au plan de degagement,
c'est-a-dire au-dessus de TOUTE la matiere. Sûr partout, y compris la ou il
n'y a plus rien : sur la poche de C02, onze aller-retours au plan pour douze
couches, alors que l'outil reste dans la meme poche, deja videe au-dessus de
lui.
"""

import copy

import numpy as np
import pytest

from xyzac.geometry_core.voxelize import VoxelGrid
from xyzac.stock_engine.material import MaterialState
from xyzac.subtractive_slicer.liaisons import (GARDE_MM, _echantillonner,
                                               _runs, abaisser_les_liaisons,
                                               hauteur_libre, touche)
from xyzac.tool_model import build_endmill


def _poche():
    """Bloc de 40 x 40 x 20 avec une poche de 20 x 20 ouverte sur le dessus.

    Le brut monte a 22 : il y a donc 2 mm de peau au-dessus de la piece, et
    une liaison naive qui resterait basse la percuterait.
    """
    forme = (44, 44, 26)
    piece = np.zeros(forme, dtype=bool)
    piece[2:42, 2:42, 2:22] = True
    piece[12:32, 12:32, 10:22] = False
    brut = np.zeros(forme, dtype=bool)
    brut[1:43, 1:43, 1:24] = True
    grille = VoxelGrid(origin=np.zeros(3), pitch=1.0, shape=forme)
    return MaterialState(grid=grille, remaining=brut, protected=piece)


def _outil():
    return build_endmill("e", 6.0, 20.0, stickout=40.0, holder_type="ER16")


Z = np.array([0.0, 0.0, 1.0])


def test_a_link_inside_an_emptied_pocket_stays_inside_it():
    """Le cas qui motive le module.

    Deux passes au fond d'une poche déjà vidée au-dessus : la liaison n'a
    aucune raison de remonter au-dessus du brut.
    """
    m = _poche()
    # on vide la poche au-dessus de z = 14
    m.remaining[12:32, 12:32, 14:24] = False
    # Les extrémités sont prises AU MILIEU de la poche : collées à une paroi,
    # le corps de l'outil la toucherait, et la liaison devrait alors remonter
    # — ce qui serait juste, mais ne dirait rien de ce qu'on teste ici.
    h = hauteur_libre(m, np.array([18.0, 18.0, 13.0]),
                      np.array([26.0, 26.0, 13.0]), Z, _outil())
    assert h < 20.0, f"la liaison devrait rester dans la poche, h={h}"
    assert h >= 13.0 + GARDE_MM


def test_a_link_over_uncut_stock_rises_above_it():
    """Et le cas inverse, qui est la raison pour laquelle on ne devine pas.

    La même liaison, poche INTACTE : la matière est encore là, et la liaison
    doit passer au-dessus — sinon elle traverse le brut.
    """
    m = _poche()
    h = hauteur_libre(m, np.array([15.0, 15.0, 13.0]),
                      np.array([28.0, 28.0, 13.0]), Z, _outil())
    assert h > 23.0, f"la liaison doit dépasser le brut (24), h={h}"


def test_the_computed_height_is_confirmed_by_the_full_tool_sweep():
    """Deux calculs indépendants pour la même question.

    ``hauteur_libre`` raisonne par tronçon d'outil et par maximum ; ``touche``
    passe l'outil ENTIER sur la liaison et regarde ce qu'il prendrait. Si les
    deux divergeaient, celui qu'on croirait serait celui qui autorise.

    C'est ce recoupement qui a montré que la première version de la
    vérification était fausse — elle reprochait à la plongée d'entrer dans la
    matière qu'elle allait couper.
    """
    m = _poche()
    m.remaining[12:32, 12:32, 16:24] = False        # poche vidée en partie
    outil = _outil()
    a = np.array([15.0, 15.0, 15.0])
    b = np.array([28.0, 28.0, 15.0])
    h = hauteur_libre(m, a, b, Z, outil)

    traverse = np.array([[a[0], a[1], h], [b[0], b[1], h]])
    assert not touche(m, _echantillonner(traverse, 0.5), Z, outil), \
        "la hauteur calculée doit être confirmée par le balayage complet"
    # et un demi-millimètre plus bas que la garde, elle ne l'est plus
    bas = np.array([[a[0], a[1], h - GARDE_MM - 1.5],
                    [b[0], b[1], h - GARDE_MM - 1.5]])
    assert touche(m, _echantillonner(bas, 0.5), Z, outil), \
        "la hauteur trouvée doit être serrée, pas confortable"


def test_the_clearance_plane_stays_the_ceiling():
    """Ce module ne peut pas rendre une liaison PIRE que celle qu'il remplace.

    C'est ce qui permet de l'activer sans rien risquer : au pire il ne change
    rien, et le comportement d'avant est son cas le plus défavorable.
    """
    m = _poche()
    outil = _outil()
    pts = np.array([[18.0, 18.0, 13.0], [19.0, 18.0, 13.0],
                    [19.0, 18.0, 40.0], [26.0, 26.0, 40.0],
                    [26.0, 26.0, 13.0], [27.0, 26.0, 13.0]])
    rapide = np.array([False, False, True, True, True, False])
    Q, F, g = abaisser_les_liaisons(pts, rapide, m, outil, Z, clearance_z=40.0)
    assert g.apres_mm <= g.avant_mm + 1e-6, "jamais pire"
    # et la traversée ne dépasse JAMAIS le plafond qu'on lui a donné
    for deb, fin in _runs(F):
        assert float(max(Q[deb:fin] @ Z)) <= 40.0 + 1e-6

    # Un plafond plus BAS que ce que la matière exige : le module s'y tient,
    # et c'est exactement le comportement d'avant.
    _, F2, g2 = abaisser_les_liaisons(pts, rapide, m, outil, Z,
                                      clearance_z=26.0)
    assert g2.apres_mm <= g2.avant_mm + 1e-6


def test_a_cut_run_is_removed_before_the_next_link_is_measured():
    """C'est ce qui permet de descendre dans une poche qu'on vient de vider.

    Et ce qui interdit de descendre dans une poche qu'on n'a pas encore
    ouverte : la matière est suivie au fur et à mesure, pas prise au départ.
    """
    import inspect

    from xyzac.subtractive_slicer import liaisons as mod

    src = inspect.getsource(mod.abaisser_les_liaisons)
    assert "remove_tool_sweep" in src
    assert "copy.deepcopy(material)" in src, \
        "la matière de l'appelant ne doit pas être modifiée"

    m = _poche()
    avant = m.remaining.sum()
    outil = _outil()
    pts = np.array([[15.0, 15.0, 13.0], [25.0, 15.0, 13.0],
                    [25.0, 15.0, 30.0], [25.0, 25.0, 30.0],
                    [25.0, 25.0, 13.0], [25.0, 26.0, 13.0]])
    rapide = np.array([False, False, True, True, True, False])
    abaisser_les_liaisons(pts, rapide, m, outil, Z, clearance_z=30.0)
    assert m.remaining.sum() == avant, "l'appelant garde sa matière intacte"


def test_the_runs_of_a_path_are_found_exactly():
    """Une liaison mal découpée ferait abaisser un morceau de coupe."""
    assert _runs(np.array([False, True, True, False, True])) == [(1, 3), (4, 5)]
    assert _runs(np.zeros(4, dtype=bool)) == []
    assert _runs(np.ones(3, dtype=bool)) == [(0, 3)]


def test_lowering_a_real_pocket_pays_and_stays_clear(corpus_dir):
    """La mesure qui compte, sur une vraie pièce, avec sa vérification.

    Sur la poche de C02 : 358 mm de liaisons deviennent 160, et la part du
    chemin qui coupe passe de 70 % à 89 %. Chaque traversée abaissée est
    ensuite repassée au balayage complet de l'outil.
    """
    from xyzac.feature_engine.volumes import CAVITE, decomposer
    from xyzac.geometry_core import brep
    from xyzac.stock_engine.stock import stock_from_part
    from xyzac.subtractive_slicer.slicer import (continuous_path,
                                                 slice_for_direction)

    shape = brep.load_step(corpus_dir / "C02_poche_droite.step")
    verts, tris, _ = brep.tessellate(shape, deflection=0.3)
    bb = brep.bounding_box(shape)
    stock = stock_from_part(bb, margin_xy=2.0, margin_z_top=2.0,
                            margin_z_bottom=2.0)
    ms = MaterialState.from_setup(stock, verts, tris, pitch=1.0)
    creux = [v for v in decomposer(ms, rayons_mm=[5.0, 3.0, 1.5],
                                   separer_peau=True)
             if v.nature == CAVITE][0]
    outil = build_endmill("e", 10.0, 30.0, stickout=45.0, holder_type="ER16")

    tranche = slice_for_direction(ms, Z, outil, layer_thickness=1.5,
                                  masque=creux.masque)
    P, R = continuous_path(tranche, point_spacing=1.5, tool=outil)
    Q, F, g = abaisser_les_liaisons(P, R, ms, outil, Z,
                                    clearance_z=float(tranche.clearance_z))
    assert g.n_abaissees >= 8, g.describe()
    assert g.gain > 0.3, g.describe()

    # VÉRIFICATION : chaque traversée, rejouée sur l'état du moment, au
    # balayage complet de l'outil.
    etat = copy.deepcopy(ms)
    cur = 0
    for deb, fin in _runs(F):
        coupe = Q[cur:deb]
        if len(coupe):
            etat.remove_tool_sweep(coupe, np.tile(Z, (len(coupe), 1)), outil)
        cur = fin
        lien = Q[deb:fin]
        if len(lien) < 4:
            continue
        trav = _echantillonner(lien[1:3], 0.5)
        assert not touche(etat, trav, Z, outil), \
            f"traversée {deb}-{fin} en faute : {lien}"
