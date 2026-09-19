"""L'ordre des passes : ce qui reste du transport une fois les liaisons basses.

C10 a dit pourquoi ce module existe. Ses 117 liaisons, pour un seul creux,
enjambent le dome lui-meme, qui est de la matiere protegee : aucune hauteur
plus basse n'existait, et l'abaissement n'avait rien a trouver — 4 % de gain.
Ce qui coûte la n'est pas la hauteur d'une liaison, c'est leur nombre et leur
longueur, donc l'ordre de visite.
"""

import numpy as np
import pytest

from xyzac.subtractive_slicer.ordre import MINIMUM, GainOrdre, _cout, ordonner
from xyzac.subtractive_slicer.slicer import (BALAYAGE_ALTERNE,
                                             BALAYAGE_UNIDIRECTIONNEL,
                                             LayerToolpath, SliceResult)


def _passe(x0, y0, x1, y1, z=0.0):
    return np.array([[x0, y0, z], [x1, y1, z]])


def _resultat(polys, balayage=BALAYAGE_ALTERNE):
    r = SliceResult(direction=np.array([0.0, 0.0, 1.0]), layer_thickness=1.0,
                    stepover=2.0, safety_clearance=0.3, balayage=balayage)
    r.layers.append(LayerToolpath(index=0, depth_from_top=1.0,
                                  polylines=list(polys),
                                  target_area_mm2=0.0, covered_area_mm2=0.0))
    return r


def test_a_bad_order_is_shortened():
    """Le cas d'ecole : quatre passes visitees en sautant d'un bout a l'autre.

    L'ordre 0, 2, 1, 3 fait trois grands sauts la ou 0, 1, 2, 3 en fait trois
    petits.
    """
    polys = [_passe(0, 0, 10, 0), _passe(0, 30, 10, 30),
             _passe(0, 10, 10, 10), _passe(0, 20, 10, 20)]
    r = _resultat(polys)
    g = ordonner(r)
    assert g.gain_mm > 0.0, g.describe()
    assert g.apres_mm < g.avant_mm
    # les passes sont bien toutes la, aucune perdue ni dupliquee
    y = sorted(float(p[0][1]) for p in r.layers[0].polylines)
    assert y == [0.0, 10.0, 20.0, 30.0]


def test_the_order_is_never_made_worse():
    """Ce module ne peut pas rendre un parcours PIRE.

    L'ordre d'origine est evalue lui aussi, et on ne le quitte que pour plus
    court. C'est ce qui permet de l'activer sans rien risquer.

    Sur quatre passes paralleles deja rangees, il CHANGE pourtant quelque
    chose : toutes dans le meme sens, chaque saut traverse la passe entiere,
    alors qu'en alternant on ne saute que d'une rangee. Ce n'est donc pas
    « deja le meilleur » — et c'est bien ce qui rend le test utile.
    """
    polys = [_passe(0, 0, 10, 0), _passe(0, 2, 10, 2),
             _passe(0, 4, 10, 4), _passe(0, 6, 10, 6)]
    r = _resultat(polys)
    g = ordonner(r)
    assert g.apres_mm <= g.avant_mm + 1e-9
    assert g.apres_mm == pytest.approx(6.0), \
        "en alternant, les trois sauts font 2 mm chacun"

    # Un ordre qu'on ne peut plus raccourcir ne doit PAS bouger.
    deja = [_passe(0, 0, 10, 0), _passe(10, 2, 0, 2), _passe(0, 4, 10, 4)]
    r2 = _resultat(deja)
    avant = [np.array(p) for p in r2.layers[0].polylines]
    g2 = ordonner(r2)
    assert g2.gain_mm == 0.0
    for a, b in zip(avant, r2.layers[0].polylines):
        assert np.allclose(a, b), "un ordre déjà optimal ne doit pas bouger"


def test_a_one_way_sweep_is_never_reversed():
    """Le sens de parcours est le sens de COUPE.

    ``unidirectionnel`` existe precisement pour le garder constant : l'avalant
    et l'opposition n'usent pas l'outil de la meme facon, et quelqu'un qui a
    choisi ce mode l'a choisi. Retourner une passe la raccourcirait et
    trahirait le reglage.
    """
    polys = [_passe(0, 0, 10, 0), _passe(0, 30, 10, 30),
             _passe(0, 10, 10, 10), _passe(0, 20, 10, 20)]
    r = _resultat(polys, balayage=BALAYAGE_UNIDIRECTIONNEL)
    ordonner(r)
    for p in r.layers[0].polylines:
        assert p[0][0] < p[-1][0], f"passe retournee : {p}"

    # …alors qu'en zigzag, l'alternance est deja dans le contrat
    r2 = _resultat(polys, balayage=BALAYAGE_ALTERNE)
    ordonner(r2)
    retournees = sum(1 for p in r2.layers[0].polylines if p[0][0] > p[-1][0])
    assert retournees > 0, "en zigzag, retourner une passe est permis"


def test_reversing_a_chunk_flips_every_pass_inside_it():
    """Parcourir un bout de chemin a l'envers, c'est entrer dans chaque passe
    par son autre bout.

    L'oublier donnerait un coût calcule sur un tour qui n'est pas celui qu'on
    emettrait — et le gain annonce serait faux.
    """
    debuts = np.array([[0.0, 0, 0], [10.0, 0, 0], [20.0, 0, 0]])
    fins = np.array([[5.0, 0, 0], [15.0, 0, 0], [25.0, 0, 0]])
    droit = [(0, False), (1, False), (2, False)]
    # le meme tour, morceau [0..2] renverse ET chaque passe retournee
    envers = [(2, True), (1, True), (0, True)]
    assert _cout(droit, debuts, fins, None) == pytest.approx(10.0)
    assert _cout(envers, debuts, fins, None) == pytest.approx(10.0)


def test_layers_are_never_reordered_between_themselves():
    """L'ordre des couches est une contrainte physique, pas une preference.

    On ne peut pas usiner la couche 5 avant la 4. Melanger cette regle a une
    question de trajet serait confondre les deux.
    """
    import inspect

    from xyzac.subtractive_slicer import ordre as mod

    src = inspect.getsource(mod.ordonner)
    assert "for couche in resultat.layers" in src
    # le depart d'une couche est la FIN de la precedente : gratuit, et cela
    # raccourcit aussi la liaison entre deux couches
    assert "ou_apres" in src


def test_a_layer_with_too_few_passes_is_left_alone():
    """Deux passes n'ont qu'un ordre utile : il n'y a rien a chercher."""
    r = _resultat([_passe(0, 0, 10, 0), _passe(0, 5, 10, 5)])
    avant = [np.array(p) for p in r.layers[0].polylines]
    ordonner(r)
    for a, b in zip(avant, r.layers[0].polylines):
        assert np.allclose(a, b)
    assert MINIMUM == 3


def test_reordering_the_dome_pays_where_lowering_could_not(corpus_dir):
    """La mesure qui a motive le module, sur la piece qui l'a motive.

    Sur le dome de C10, l'abaissement des liaisons ne gagnait que 4 % : ses
    liaisons enjambent le dome, et aucune hauteur plus basse n'existe.

    Reordonner SEUL ramene le transport de 10,9 m a 6,9 m — 37 %. Combine a
    l'abaissement, qui trouve alors des hauteurs basses sur des sauts devenus
    courts, l'ensemble descend a 3,0 m. Les deux chiffres sont distincts et ce
    test ne mesure que le premier : attribuer a l'ordre le gain des deux
    serait compter deux fois.
    """
    from xyzac.feature_engine.volumes import CAVITE, decomposer
    from xyzac.geometry_core import brep
    from xyzac.stock_engine.material import MaterialState
    from xyzac.stock_engine.stock import stock_from_part
    from xyzac.subtractive_slicer.slicer import (continuous_path,
                                                 slice_for_direction)
    from xyzac.tool_model import build_endmill

    shape = brep.load_step(corpus_dir / "C10_dome_convexe.step")
    verts, tris, _ = brep.tessellate(shape, deflection=0.3)
    bb = brep.bounding_box(shape)
    stock = stock_from_part(bb, margin_xy=2.0, margin_z_top=2.0,
                            margin_z_bottom=2.0)
    ms = MaterialState.from_setup(stock, verts, tris, pitch=1.0)
    creux = max((v for v in decomposer(ms, rayons_mm=[5.0, 3.0, 1.5],
                                       separer_peau=True)
                 if v.nature == CAVITE), key=lambda v: v.volume_mm3)
    outil = build_endmill("e", 10.0, 30.0, stickout=45.0, holder_type="ER16")
    Z = np.array([0.0, 0.0, 1.0])

    def transport(reordonne: bool) -> float:
        t = slice_for_direction(ms, Z, outil, layer_thickness=1.5,
                                masque=creux.masque)
        if reordonne:
            ordonner(t)
        P, R = continuous_path(t, point_spacing=1.5, tool=outil)
        d = np.linalg.norm(np.diff(P, axis=0), axis=1)
        return float(d[R[:-1] | R[1:]].sum())

    sans, avec = transport(False), transport(True)
    assert avec < sans * 0.7, f"{sans:.0f} -> {avec:.0f} mm"
    assert sans > 9000.0, f"le cas doit rester celui qui a motive le module"
