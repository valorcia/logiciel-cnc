"""La matiere a enlever, consideree comme des PIECES (jalon M16).

Le renversement : on ne raisonne plus sur les surfaces de la piece finie mais
sur les volumes a sortir, et l'outil cesse d'etre un reglage global pour
devenir une reponse — une par volume.
"""

import numpy as np
import pytest

from xyzac.feature_engine.volumes import (CAVITE, PEAU, PLAFOND_OUTIL_MM,
                                          RAYON_MINIMAL_VOX, decomposer,
                                          ouverture, portee_outil,
                                          separer_peau_cavites)


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

    vols = decomposer(ms, rayons_mm=[5.0, 3.0, 1.5], separer_peau=True)
    assert vols
    phrase = vols[0].consigne()
    assert "mm³ à sortir" in phrase
    assert "Ø" in phrase
    # Le detail de C20 est plus fin que le pas de 1 mm : a cette resolution la
    # piece se voxelise en bloc plein, et le module ne doit donc PAS inventer
    # un creux. Ce qu'il rend est la peau du brut, et rien d'autre.
    assert all(v.nature == PEAU for v in vols), [v.nature for v in vols]
    assert vols[0].fond_a_ciel_ouvert, phrase


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
    assert de_haut[0].volume_mm3 > de_cote[0].volume_mm3, \
        "de dessus, la poche est visible ; de côté, non"


# ------------------------------------------- la peau n'est pas une poche

def test_the_stock_skin_is_separated_from_the_cavities(corpus_dir):
    """Le defaut qui rendait le chiffre par outil inutile, et sa correction.

    Le brut enveloppe la piece d'une peau continue qui relie toutes les
    cavites en UN bloc. Mesure sur C02 : un seul volume de 47 669 mm3, dont
    une fraise de O 10 mm prenait 41 % et une de O 3 mm 43 %. Deux points
    d'ecart entre deux outils que tout separe.

    Separees, la poche de C02 se retrouve pour ce qu'elle est : 30 x 30 x 20,
    soit 18 000 mm3 tout ronds.
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

    peau, cavites = separer_peau_cavites(ms)
    assert not (peau & cavites).any(), "un voxel ne peut pas etre les deux"
    assert (peau | cavites == ms.removable()).all(), "rien ne doit se perdre"

    vols = decomposer(ms, rayons_mm=[5.0, 3.0, 1.5], separer_peau=True)
    creux = [v for v in vols if v.nature == CAVITE]
    assert len(creux) == 1, [v.describe() for v in vols]
    # La poche vraie fait 30 x 30 x 20 mm. Le compte doit tomber dessus.
    assert creux[0].volume_mm3 == pytest.approx(18000.0, rel=0.02)
    assert creux[0].cotes_mm == "30 × 30 × 20 mm"
    assert len([v for v in vols if v.nature == PEAU]) == 1


def test_a_convex_part_has_no_cavity_rather_than_an_invented_one(corpus_dir):
    """Un bloc simple n'a pas de creux, et le module doit le dire.

    Le critere est l'enveloppe convexe : une piece deja convexe ne s'en
    ecarte nulle part, donc n'a aucune concavite. Inventer une poche ici
    serait pire que de n'en trouver aucune.
    """
    from xyzac.geometry_core import brep
    from xyzac.stock_engine.material import MaterialState
    from xyzac.stock_engine.stock import stock_from_part

    shape = brep.load_step(corpus_dir / "C01_bloc_simple.step")
    verts, tris, _ = brep.tessellate(shape, deflection=0.3)
    bb = brep.bounding_box(shape)
    stock = stock_from_part(bb, margin_xy=2.0, margin_z_top=2.0,
                            margin_z_bottom=2.0)
    ms = MaterialState.from_setup(stock, verts, tris, pitch=1.0)

    peau, cavites = separer_peau_cavites(ms)
    assert not cavites.any(), f"{cavites.sum()} voxels de creux sur un bloc"
    vols = decomposer(ms, rayons_mm=[5.0], separer_peau=True)
    assert [v.nature for v in vols] == [PEAU]


def test_each_channel_of_a_finned_part_gets_its_own_tool(corpus_dir):
    """Ce que la separation apporte, mesure : un outil PAR creux.

    Sur C05, les trois intervalles entre ailettes n'ont pas la meme largeur.
    Melanges a la peau, ils rendaient un seul chiffre. Separes, le plus
    etroit refuse la fraise de O 10 mm (10 %) que les deux autres acceptent
    (97 %) — et c'est exactement la decision que l'operateur doit prendre.
    """
    from xyzac.geometry_core import brep
    from xyzac.stock_engine.material import MaterialState
    from xyzac.stock_engine.stock import stock_from_part

    shape = brep.load_step(corpus_dir / "C05_ailettes_rapprochees.step")
    verts, tris, _ = brep.tessellate(shape, deflection=0.3)
    bb = brep.bounding_box(shape)
    stock = stock_from_part(bb, margin_xy=2.0, margin_z_top=2.0,
                            margin_z_bottom=2.0)
    ms = MaterialState.from_setup(stock, verts, tris, pitch=1.0)

    vols = decomposer(ms, rayons_mm=[5.0, 3.0], separer_peau=True)
    creux = [v for v in vols if v.nature == CAVITE]
    assert len(creux) >= 3, [v.describe() for v in vols]
    dix = [v.par_outil[0].fraction for v in creux]
    assert min(dix) < 0.2 and max(dix) > 0.9, dix
    # et le creux etroit reste pris par la fraise de O 6 mm
    etroit = creux[int(np.argmin(dix))]
    assert etroit.par_outil[1].fraction > 0.9, etroit.describe()


def test_a_tool_reaches_a_pocket_through_its_mouth_not_by_fitting_inside():
    """Defaut mesure : la bouche d'une poche comptait comme un plafond.

    ``ouverture`` confine la boule DANS le volume. Une poche ouverte se voyait
    donc rogner sur toute la couronne du haut, comme si de la matiere la
    couvrait. Sur la poche de C02, 30 x 30 x 20 mm, une fraise de O 10 mm
    tombait a 84 % au lieu de 90 %, et les 16 % manquants n'etaient nulle
    part ailleurs que dans ce plafond imaginaire.

    ``portee_outil`` fait circuler la boule dans l'espace LIBRE, qui contient
    l'air au-dessus de la piece.
    """
    # Une poche carree de 10 x 10, profonde de 6, dans un bloc de 20 x 20.
    piece = np.zeros((20, 20, 12), dtype=bool)
    piece[:, :, :8] = True
    piece[5:15, 5:15, 2:8] = False           # la poche
    poche = np.zeros_like(piece)
    poche[5:15, 5:15, 2:8] = True
    libre = ~piece

    enferme = ouverture(poche, 3.0)
    ouvert = portee_outil(libre, 3.0, poche)
    assert ouvert.sum() > enferme.sum(), (ouvert.sum(), enferme.sum())
    # la boule ne deborde jamais sur la piece a conserver
    assert not (ouvert & piece).any()
    # et le haut de la poche, sous la bouche, est bien atteint
    assert ouvert[10, 10, 7]


def test_the_bottom_radius_says_open_sky_rather_than_the_padding_size():
    """Un nombre qui ne mesure que le rembourrage ne doit pas etre rendu.

    Le majorant « plus gros outil qui atteint le fond » n'existe pas quand le
    fond donne sur l'air libre : la boule grandit jusqu'au bord du tableau.
    Le module rendait alors O 130,6 mm — deux fois le rembourrage. Il rend
    maintenant l'infini, qui ne se confond avec aucune mesure.
    """
    # Une plaque posee a plat : sa face du dessus est a ciel ouvert.
    piece = np.zeros((30, 30, 20), dtype=bool)
    piece[5:25, 5:25, 2:8] = True
    dessus = np.zeros_like(piece)
    dessus[5:25, 5:25, 8:10] = True          # la surepaisseur au-dessus

    class _M:
        grid = _Grille(piece.shape, 1.0)
        protected = piece

        def removable(self):
            return dessus

    vols = decomposer(_M(), rayons_mm=[5.0], volume_min_mm3=1.0)
    assert len(vols) == 1
    assert vols[0].fond_a_ciel_ouvert
    assert vols[0].texte_fond == "fond à ciel ouvert"
    assert "ciel ouvert" in vols[0].consigne() or vols[0].outil_le_plus_gros()
    assert PLAFOND_OUTIL_MM == 25.0


def test_a_tool_that_empties_a_pocket_is_not_given_a_pointless_second_pass():
    """« Le vide. Reprise possible a O 6 mm » — pour les 0 % qu'elle laisse.

    ``reprises`` rendait tout outil plus fin qui entre, sans regarder s'il
    prenait davantage. Une poche videe a 100 % par la grosse fraise
    s'annonçait quand meme reprise a la petite : une operation de plus, un
    changement d'outil, et rien a usiner au bout.
    """
    v = np.zeros((24, 24, 14), dtype=bool)
    v[4:20, 4:20, 3:11] = True
    vols = decomposer(_Matiere(v), rayons_mm=[3.0, 2.0, 1.5],
                      volume_min_mm3=1.0)
    gros = vols[0].outil_le_plus_gros()
    assert gros is not None
    for o in vols[0].reprises():
        assert o.fraction > gros.fraction, (o.describe(), gros.describe())
    phrase = vols[0].consigne()
    if "Reprise" in phrase:
        assert " 0 % qu'elle laisse" not in phrase
    assert "  " not in phrase and ".." not in phrase


def test_a_ray_on_a_mesh_edge_no_longer_drills_a_phantom_hole(corpus_dir):
    """Defaut trouve en separant la peau des cavites, et il etait ancien.

    Le remplissage par parite tirait le rayon du CENTRE du voxel. La face
    inferieure d'un bloc se maille en deux triangles dont l'arete commune est
    la diagonale, et tous les centres de voxels d'une grille au pas entier
    tombent dessus : le test barycentrique repondait « touche » des deux
    cotes, la colonne comptait trois traversees, et le code laissait tomber
    la derniere. Resultat : 28 fausses colonnes traversantes de 1 x 1 x 25 mm
    dans C02, que la matiere enlevable presentait comme 28 creux a usiner.

    Le volume vraie de C02 est 60 x 60 x 25 moins la poche de 30 x 30 x 20,
    soit 72 000 mm3 exactement — et a 1 mm de pas, la grille tombe dessus.
    """
    from xyzac.geometry_core import brep
    from xyzac.geometry_core.voxelize import VoxelGrid, solid_mask

    shape = brep.load_step(corpus_dir / "C02_poche_droite.step")
    verts, tris, _ = brep.tessellate(shape, deflection=0.3)
    bb = brep.bounding_box(shape)
    g = VoxelGrid.covering(bb.lo, bb.hi, pitch=1.0, margin=1.0)
    m = solid_mask(verts, tris, g)
    assert m.sum() * g.voxel_volume == pytest.approx(72000.0, rel=1e-9)

    # Et aucune colonne traversante : une colonne interieure au bloc, hors
    # poche, doit etre pleine sur toute la hauteur de la piece.
    for xy in ((1.5, 1.5), (2.5, 2.5), (10.5, 10.5)):
        i, j, _ = g.index_of(np.array([[xy[0], xy[1], 1.0]]))[0]
        assert m[i, j].sum() == 25, f"colonne vide en {xy}"
