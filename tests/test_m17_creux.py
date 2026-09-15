"""Un creux, son outil, son orientation — et laquelle des trois etapes bloque.

L'enchainement est fixe : quel volume, quel outil, quelle orientation. Chaque
etape peut refuser pour sa propre raison, et nommer celle qui bloque, c'est
nommer ce qu'il faut changer. « Non usinable » tout court n'indique rien.
"""

import numpy as np
import pytest

from xyzac.feature_engine.volumes import CAVITE, decomposer
from xyzac.strategy_planner.creux import (ETAPE_AUCUNE, ETAPE_ORIENTATION,
                                          ETAPE_OUTIL, ETAPE_VOLUME,
                                          MOTIFS_NON_BLOQUANTS,
                                          TOLERANCE_DIRECTION_DEG,
                                          NOM_MOTIF, decider_creux,
                                          directions_candidates,
                                          points_du_creux)


class _Grille:
    def __init__(self, shape, pitch=1.0, origin=(0.0, 0.0, 0.0)):
        self.shape = shape
        self.pitch = pitch
        self.origin = np.asarray(origin, dtype=float)

    @property
    def voxel_volume(self):
        return self.pitch ** 3


class _Passe:
    def __init__(self, points, normals):
        self.points = np.asarray(points, dtype=float)
        self.normals = np.asarray(normals, dtype=float)

    @property
    def n_points(self):
        return len(self.points)


def _bloc_avec_poche():
    """Un bloc de 20 x 20 x 12 avec une poche de 10 x 10 profonde de 6."""
    piece = np.zeros((20, 20, 12), dtype=bool)
    piece[:, :, :8] = True
    piece[5:15, 5:15, 2:8] = False
    poche = np.zeros_like(piece)
    poche[5:15, 5:15, 2:8] = True
    return piece, poche


def _matiere(piece, enlevable):
    class _M:
        grid = _Grille(piece.shape, 1.0)
        protected = piece

        def removable(self):
            return enlevable

        def reachable_from(self, d, **kw):
            # Vu de +Z, toute la poche ; de cote, rien : le bloc la cache.
            d = np.asarray(d, dtype=float)
            if d[2] > 0.5:
                return enlevable.copy()
            return np.zeros_like(enlevable)
    return _M()


# ------------------------------------------- quels points bordent un creux

def test_the_points_that_bound_a_cavity_are_found_by_their_normal():
    """Le lien creux -> faces se fait par la normale, pas par la distance.

    Un point de contact borde le creux si le voxel situe juste DEVANT lui en
    fait partie. Un point du dessus du bloc, a cote de la poche, regarde en
    haut : il n'en fait pas partie, meme s'il en est proche.
    """
    _, poche = _bloc_avec_poche()
    grille = _Grille(poche.shape, 1.0)

    # Le fond de la poche regarde en haut ; le dessus du bloc aussi.
    fond = np.array([[10.5, 10.5, 2.0]])
    dessus = np.array([[2.5, 2.5, 8.0]])
    haut = np.array([[0.0, 0.0, 1.0]])

    k = points_du_creux(poche, grille, np.vstack([fond, dessus]),
                        np.vstack([haut, haut]))
    assert k.tolist() == [0], "seul le fond de la poche borde la poche"

    # Un flanc de la poche regarde vers l'interieur de la poche.
    flanc = np.array([[5.0, 10.5, 5.0]])
    vers_x = np.array([[1.0, 0.0, 0.0]])
    assert points_du_creux(poche, grille, flanc, vers_x).tolist() == [0]
    # et la meme position, normale retournee, regarde la matiere : hors creux
    assert len(points_du_creux(poche, grille, flanc, -vers_x)) == 0


def test_candidate_directions_are_deduplicated():
    """Chaque direction coûte un lancer de rayons sur toute la grille.

    Quatre flancs paralleles deux a deux donnent deux directions, pas quatre,
    et les six axes ne doivent pas s'ajouter a celles qu'ils repetent.
    """
    passes = [_Passe([[0, 0, 0]], [[0, 0, 1]]),
              _Passe([[0, 0, 0]], [[0.0, 0.05, 0.998]]),   # ~3 degres
              _Passe([[0, 0, 0]], [[1, 0, 0]])]
    dirs = directions_candidates(passes)
    cos_tol = np.cos(np.radians(TOLERANCE_DIRECTION_DEG))
    for i, a in enumerate(dirs):
        for b in dirs[i + 1:]:
            assert float(a @ b) < cos_tol, (a, b)
    # les six axes sont couverts, donc au moins six directions
    assert len(dirs) >= 6


# --------------------------------------------- l'ordre des trois etapes

def test_no_tool_fits_stops_before_the_orientation_is_even_asked():
    """L'ordre n'est pas cosmetique : il epargne un calcul entier.

    Sur un creux ou aucun outil n'entre, il n'y a rien a orienter. Demander
    au solveur de chercher une orientation serait lui faire perdre 30 s pour
    un refus deja connu — et rendre un motif qui parlerait de la machine
    alors que le probleme est l'outil.
    """
    piece, poche = _bloc_avec_poche()
    # Une fente d'un voxel de large : aucun de nos outils n'y entre.
    fente = np.zeros_like(piece)
    fente[9:10, 5:15, 2:8] = True
    mat = _matiere(piece, fente)
    vols = decomposer(mat, rayons_mm=[3.0, 2.0], volume_min_mm3=1.0)
    assert vols

    def _interdit(_r):
        raise AssertionError("le solveur ne doit pas etre appele")

    v = decider_creux(vols[0], [], mat, fabrique_solveur=_interdit,
                      machine=None, mount_offset=np.zeros(3))
    assert v.etape == ETAPE_OUTIL, v.describe()
    assert "outil" in v.consigne() and "orientation ne se pose pas" in v.consigne()
    assert not v.usinable


def test_a_volume_no_face_bounds_is_free_material_not_a_cavity():
    """Un volume qu'aucune face ne borde n'est pas un creux a usiner.

    Le dire, plutot que d'envoyer au solveur une passe vide dont il rendrait
    « inatteignable » — un refus qui ferait croire a un probleme de machine.
    """
    piece, poche = _bloc_avec_poche()
    mat = _matiere(piece, poche)
    vols = decomposer(mat, rayons_mm=[2.0], volume_min_mm3=1.0)
    v = decider_creux(vols[0], [], mat, fabrique_solveur=lambda r: (None, None),
                      machine=None, mount_offset=np.zeros(3))
    assert v.etape == ETAPE_VOLUME, v.describe()
    assert "matière libre" in v.consigne()


# ------------------------------- ce que le solveur doit ET ne doit pas bloquer

class _Verdict:
    def __init__(self, reason, a_deg=0.0, c_deg=0.0):
        from xyzac.accessibility_solver.solver import RejectReason
        self.reason = np.asarray(reason)
        self.ok = self.reason == int(RejectReason.OK)
        self.a_deg, self.c_deg = a_deg, c_deg
        self.clearance = np.where(self.reason == int(RejectReason.LEAD_LIMIT),
                                  -np.inf, 5.0)


class _Solveur:
    def __init__(self, reason):
        self._reason = reason
        self.vu = None

    def verify_direction(self, pts, nrm, direction, **kw):
        self.vu = np.asarray(direction, dtype=float)
        n = len(pts)
        r = np.resize(np.asarray(self._reason), n)
        return _Verdict(r)


class _Machine:
    a = type("A", (), {"min_deg": -120.0, "max_deg": 120.0})()

    def tool_axis_in_part(self, a_deg, c_deg):
        return np.array([0.0, 0.0, 1.0])


def _decider(reason, monkeypatch):
    from xyzac.strategy_planner import creux as mod

    piece, poche = _bloc_avec_poche()
    mat = _matiere(piece, poche)
    vols = decomposer(mat, rayons_mm=[2.0, 1.5], volume_min_mm3=1.0)
    # Le fond de la poche, et ses quatre flancs.
    passes = [_Passe([[x + 0.5, y + 0.5, 2.0] for x in range(5, 15)
                      for y in range(5, 15)],
                     [[0.0, 0.0, 1.0]] * 100),
              _Passe([[5.0, y + 0.5, 5.0] for y in range(5, 15)],
                     [[1.0, 0.0, 0.0]] * 10)]
    sol = _Solveur(reason)
    monkeypatch.setattr(mod, "course_lineaire", None, raising=False)

    class _Course:
        tient = True

        def consigne(self):
            return ""

    import xyzac.strategy_planner.travel as travel
    monkeypatch.setattr(travel, "course_lineaire",
                        lambda *a, **k: _Course())
    monkeypatch.setattr("xyzac.accessibility_solver.solver.tcp_from_contact",
                        lambda p, n, axe, outil: np.asarray(p, dtype=float))
    return decider_creux(vols[0], passes, mat,
                         fabrique_solveur=lambda r: (sol, object()),
                         machine=_Machine(), mount_offset=np.zeros(3)), sol


def test_a_wall_that_looks_sideways_is_not_a_refusal(monkeypatch):
    """Le defaut qui faisait refuser TOUTES les poches du corpus.

    ``decide_indexed_pass`` cherche une orientation qui mette le BEC face a
    chaque point. Une poche a un fond qui regarde en haut et quatre flancs a
    90 degres : aucune orientation ne les met tous face au bec, et il n'en
    manque aucune — les flancs se coupent par le flanc de l'outil.

    Mesure avant correction, sur la poche de C02 : « 8 des 8 points sondes ne
    sont atteignables par AUCUNE orientation », en accusant le plateau de la
    machine. La poche s'usine pourtant a A = 0, C = 0.
    """
    from xyzac.accessibility_solver.solver import RejectReason

    v, _ = _decider([int(RejectReason.OK)] * 9 + [int(RejectReason.LEAD_LIMIT)],
                    monkeypatch)
    assert v.etape == ETAPE_AUCUNE, v.describe()
    assert v.n_ailleurs > 0
    assert "regarde" in v.consigne() and "flanc" in v.consigne()
    assert "LEAD_LIMIT" in MOTIFS_NON_BLOQUANTS


def test_the_cutting_edge_touching_the_part_is_its_job_not_a_collision(monkeypatch):
    """Le piege deja tendu au portillon de collision, et retendu ici.

    Sur le fond d'une poche, tout point a moins d'un rayon du flanc met le
    cylindre de coupe en contact avec ce flanc. Le compter comme un blocage
    revient a ecarter une orientation POUR AVOIR COUPE.
    """
    from xyzac.accessibility_solver.solver import RejectReason

    v, _ = _decider([int(RejectReason.COLLISION_CUTTING)] * 9
                    + [int(RejectReason.OK)], monkeypatch)
    assert v.etape == ETAPE_AUCUNE, v.describe()
    assert v.n_en_coupe > 0
    assert "COLLISION_CUTTING" in MOTIFS_NON_BLOQUANTS


def test_the_holder_touching_IS_a_refusal_and_it_is_named(monkeypatch):
    """Ce qui bloque vraiment doit bloquer, et dire quoi.

    Le porte-outil, le col, la tige, le nez de broche et les organes de la
    machine : ceux-la ne sont pas le travail de l'outil.
    """
    from xyzac.accessibility_solver.solver import RejectReason

    v, _ = _decider([int(RejectReason.COLLISION_HOLDER)] * 10, monkeypatch)
    assert v.etape == ETAPE_ORIENTATION, v.describe()
    assert not v.usinable
    # EN FRANÇAIS, et non « COLLISION_HOLDER » : ce nom est celui que le motif
    # porte dans le moteur, et ecrit tel quel sur l'ecran d'un operateur il ne
    # veut rien dire. Le remede etait deja en clair ; il manquait la cause.
    phrase = v.consigne()
    assert "COLLISION" not in phrase, phrase
    assert "le porte-outil touche" in phrase, phrase
    assert "porte-outil plus élancé" in phrase, phrase


def test_the_direction_tried_is_the_mouth_of_the_cavity(monkeypatch):
    """L'orientation d'un creux est celle d'ou on le VOIT, pas une moyenne.

    La poche du bloc d'essai ne se voit que de +Z : c'est donc la direction
    que le solveur doit recevoir, et le creux doit etre annonce vu a 100 %.
    """
    from xyzac.accessibility_solver.solver import RejectReason

    v, sol = _decider([int(RejectReason.OK)] * 10, monkeypatch)
    assert sol.vu is not None
    assert sol.vu[2] > 0.9, sol.vu
    assert v.visibilite == pytest.approx(1.0)


def test_every_reject_reason_has_a_french_name():
    """Aucun motif ne doit pouvoir arriver a l'ecran sous son nom de code.

    Le dictionnaire est ecrit a la main, donc un motif ajoute au moteur
    passerait silencieusement au travers — et sortirait « COLLISION_NECK » sur
    la page d'un operateur qui n'est pas developpeur.
    """
    from xyzac.accessibility_solver.solver import RejectReason

    manquants = [r.name for r in RejectReason
                 if r is not RejectReason.OK and r.name not in NOM_MOTIF]
    assert not manquants, manquants
    for texte in NOM_MOTIF.values():
        assert "_" not in texte, texte
        assert texte.upper() != texte, texte
