"""Verdict d'indexation sur une passe de finition COMPLETE (jalon M10).

Ce que ces tests protegent : le renversement explorer/verifier. Jusqu'ici la
finition etait decidee sur un PREFIXE contigu, parce qu'un point de contact
coute 65 ms en resolution complete — trois heures pour les 159 899 points d'une
gamme du dome C10. Le mode annonce etait donc celui du prefixe, et il changeait
avec la couverture.

``verify_direction`` retourne le probleme : une orientation deja connue se
verifie en 1,6 ms par point, vectorisee. Le verdict 3+2 porte alors sur la
passe entiere. Mesure : la gamme complete du dome est decidee en 192 s, contre
1 091 s pour 18 % de couverture auparavant.
"""

import numpy as np
import pytest

from xyzac.accessibility_solver.solver import (
    AccessibilityConfig,
    AccessibilitySolver,
    RejectReason,
    tcp_from_contact,
)
from xyzac.collision_engine import ObstacleField
from xyzac.collision_engine.field import ObstacleClass
from xyzac.machine_model import default_xyzac_kit
from xyzac.strategy_planner.indexed_pass import decide_indexed_pass
from xyzac.tool_model import build_ballnose


@pytest.fixture(scope="module")
def tool():
    return build_ballnose("BN6", 6.0, 20.0, stickout=45.0, holder_type="ER16")


@pytest.fixture(scope="module")
def solver(tool):
    """Scene minimale : un plan horizontal comme obstacle, rien d'autre.

    Volontairement pauvre. Ces tests portent sur la MECANIQUE du verdict, pas
    sur une geometrie de corpus : une scene riche rendrait les attentes
    fragiles sans rien prouver de plus.
    """
    g = np.mgrid[-40:41:2.0, -40:41:2.0].reshape(2, -1).T
    pts = np.column_stack([g, np.zeros(len(g))])
    nrm = np.tile([0.0, 0.0, 1.0], (len(pts), 1))
    obst = ObstacleField(pts, np.full(len(pts), ObstacleClass.PART, np.int8),
                         np.full(len(pts), 0.2))
    cfg = AccessibilityConfig(subdivisions=3, max_lead_deg=45.0, cutting_depth=0.0)
    return AccessibilitySolver(tool, default_xyzac_kit(), obst, cfg,
                               mount_offset_mm=np.array([0.0, 0.0, 40.0]))


def _plan_points(n=200, r=12.0):
    """Petit chemin circulaire sur le plan z=0, normales verticales."""
    t = np.linspace(0.0, 2.0 * np.pi, n)
    pts = np.column_stack([r * np.cos(t), r * np.sin(t), np.zeros(n)])
    nrm = np.tile([0.0, 0.0, 1.0], (n, 1))
    return pts, nrm


# --------------------------------------------------- fidelite du vectorise

def test_vectorised_tcp_matches_the_scalar_formula(solver):
    """Une reecriture vectorisee est l'endroit exact ou un signe se perd sans
    que rien ne le signale. On compare terme pour terme."""
    rng = np.random.default_rng(7)
    pts = rng.normal(scale=10.0, size=(40, 3))
    nrm = rng.normal(size=(40, 3))
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)
    for d in (np.array([0.0, 0.0, 1.0]), np.array([0.3, -0.4, 0.87]),
              np.array([-0.6, 0.2, 0.77])):
        d = d / np.linalg.norm(d)
        vec = solver._tcps_for_direction(pts, nrm, d)
        ref = np.array([tcp_from_contact(p, n, d, solver.tool)
                        for p, n in zip(pts, nrm)])
        # Algebriquement identiques, mais pas bit a bit : l'ordre des
        # operations differe dans la normalisation de la composante radiale.
        # Sur les normales du corpus l'ecart etait nul, ce qui etait une
        # chance et non une propriete — d'ou une tolerance, serree.
        assert np.abs(vec - ref).max() < 1e-12, d


@pytest.mark.parametrize("block", [1, 4, 16, 64, 300])
def test_block_size_changes_the_cost_never_the_verdict(solver, block):
    """LE point a ne pas perdre. Le prefiltre d'obstacles de ``check_many`` se
    rabat sur une sphere de rayon « portee + etendue du bloc » : un bloc large
    le rend inoperant, et le premier prototype, a 256, etait aussi lent que le
    champ complet (25,9 ms/pt contre 1,6). La taille de bloc est donc un
    reglage de COÛT, et ce test interdit qu'elle devienne un reglage de
    resultat."""
    pts, nrm = _plan_points()
    d = np.array([0.2, 0.0, 0.98])
    ref = solver.verify_direction(pts, nrm, d, block=16)
    got = solver.verify_direction(pts, nrm, d, block=block)
    assert np.array_equal(ref.ok, got.ok)
    assert ref.a_deg == got.a_deg and ref.c_deg == got.c_deg


# --------------------------------------------------- ce que la marge veut dire

def test_the_all_segment_margin_is_dominated_by_the_cutting_edge(solver):
    """Regression du defaut du jalon M6, reapparu ici.

    Le minimum sur TOUS les tronçons est domine par l'arete de coupe, tangente
    a la surface **par construction**. Mesure sur les parois du dome C10 : la
    marge tous tronçons vaut 0,0004 a 0,007 mm tandis que le degagement des
    tronçons NON COUPANTS vaut 14 a 16 mm — quatre ordres de grandeur. Lire la
    premiere comme un degagement ferait croire a un passage au micron.
    """
    pts, nrm = _plan_points()
    d = np.array([0.25, 0.0, 0.97])
    v = solver.verify_direction(pts, nrm, d, with_clearance=True)
    assert v.clears_all, v.describe()
    assert v.min_margin() < 0.05
    assert v.min_clearance() > 1.0
    assert v.min_clearance() > 100.0 * max(v.min_margin(), 1e-9)


def test_clearance_is_none_unless_asked(solver):
    """Le degagement hors coupe double le coût : il n'est pas calcule par
    defaut, et l'absence se lit ``None`` et non 0.0 — un zero passerait pour
    une mesure serree."""
    pts, nrm = _plan_points(n=40)
    v = solver.verify_direction(pts, nrm, np.array([0.2, 0.0, 0.98]))
    assert v.clearance is None
    assert v.min_clearance() is None
    assert "NON CALCULE" in v.describe()


# --------------------------------------------------- le verdict lui-meme

def test_a_verified_verdict_covers_the_whole_pass(solver):
    pts, nrm = _plan_points(n=300)
    v = decide_indexed_pass(solver, pts, nrm, n_probe=12, max_candidates=3)
    assert v.verdict == "3+2", v.describe()
    assert v.coverage == pytest.approx(1.0)
    assert v.n_points == 300
    assert v.min_clearance_mm is not None and v.min_clearance_mm > 0.0
    assert "VERIFIE en chacun des 300 points" in v.describe()
    assert v.basis == "verification"


def test_the_candidate_kept_is_the_one_with_the_most_clearance(solver):
    """Pas le premier qui passe. Mesure sur le dome C10 : le premier candidat
    donne 12,0 mm de degagement, le meilleur des six 16,1 mm — 25 % de moins
    pour rien."""
    pts, nrm = _plan_points(n=150)
    un = decide_indexed_pass(solver, pts, nrm, n_probe=8, max_candidates=1)
    six = decide_indexed_pass(solver, pts, nrm, n_probe=8, max_candidates=6)
    assert un.verdict == six.verdict == "3+2"
    assert six.n_verified >= un.n_verified
    assert six.min_clearance_mm >= un.min_clearance_mm - 1e-9


def test_an_unreachable_probe_point_is_a_verdict_against_simultaneous_too(solver):
    """Un point qu'AUCUNE orientation n'atteint ne sera pas davantage atteint
    par une trajectoire simultanee. Le verdict doit le dire, et nommer le
    remede : un rejet muet n'aide personne."""
    pts, nrm = _plan_points(n=60)
    # une normale retournee : plus aucune direction admissible au-dessus
    nrm = nrm.copy()
    nrm[30] = [0.0, 0.0, -1.0]
    v = decide_indexed_pass(solver, pts, nrm, n_probe=60, max_candidates=2)
    assert v.verdict == "inatteignable", v.describe()
    assert v.n_probe_unreachable >= 1
    assert v.unreachable_points
    assert v.unreachable_reasons
    assert "simultane" in v.detail


def test_the_verdict_names_a_remedy_for_each_blocking_reason():
    """Chaque motif de blocage doit renvoyer a une action, et l'action doit
    etre celle que la geometrie autorise : un porte-outil qui touche se corrige
    par la jauge, une arete de coupe qui ne rentre pas par le RAYON DE BEC —
    aucun montage n'y changera rien."""
    from xyzac.strategy_planner.indexed_pass import _remede

    assert "jauge" in _remede({"COLLISION_HOLDER": 1})
    assert "bec" in _remede({"COLLISION_CUTTING": 1})
    assert "montage" in _remede({"AXIS_LIMITS": 1})
    assert _remede({}) == ""
    # un motif inconnu ne doit pas inventer un remede
    assert "OK" in _remede({"OK": 1})


def test_an_empty_pass_is_refused_not_declared_indexable(solver):
    v = decide_indexed_pass(solver, np.zeros((0, 3)), np.zeros((0, 3)))
    assert v.verdict == "inatteignable"
    assert v.n_points == 0


def test_mismatched_lengths_raise(solver):
    with pytest.raises(ValueError, match="points pour"):
        solver.verify_direction(np.zeros((5, 3)), np.zeros((4, 3)),
                                np.array([0.0, 0.0, 1.0]))


def test_a_vertical_orientation_is_usable_when_the_table_is_locked(solver):
    """En 3+2 le plateau C est bloque : A = 0 est une POSITION, et la
    singularite est un probleme de MOUVEMENT (ADR-001 / D6). La refuser ici
    ecarterait l'orientation verticale, qui est la plus utile de toutes."""
    pts, nrm = _plan_points(n=40)
    d = np.array([0.0, 0.0, 1.0])
    permis = solver.verify_direction(pts, nrm, d, allow_singular=True)
    refuse = solver.verify_direction(pts, nrm, d, allow_singular=False)
    assert permis.a_deg is not None
    assert refuse.a_deg is None
    assert not refuse.ok.any()
    assert (refuse.reason == RejectReason.AXIS_LIMITS).any()


# ------------------------------------------- portee de la conclusion

def test_a_negative_verdict_is_conclusive_not_a_sample(solver):
    """Le rapport annonçait « MAQUETTE : 0,2 % de la passe » pour un verdict
    definitif, et sous-estimait donc son propre resultat.

    Un point sonde qu'aucune orientation n'atteint est un CONTRE-EXEMPLE : il
    conclut sur la passe entiere. Et une intersection calculee sur un
    sous-ensemble CONTIENT celle de l'ensemble — vide sur 24 points implique
    vide sur 73 792. Les deux negatifs portent loin ; ce qui est partiel, c'est
    l'examen, pas la conclusion.
    """
    pts, nrm = _plan_points(n=80)
    nrm = nrm.copy()
    nrm[40] = [0.0, 0.0, -1.0]
    v = decide_indexed_pass(solver, pts, nrm, n_probe=80, max_candidates=1)
    assert v.verdict == "inatteignable"
    assert v.basis == "contre-exemple"
    assert v.conclusive
    assert "DEFINITIF" in v.describe()
    # et l'examen, lui, est partiel : les deux informations coexistent
    assert v.coverage <= 1.0


def test_a_positive_verdict_rests_on_an_example_a_negative_on_exhaustion(solver):
    """Asymetrie structurelle, et elle merite d'etre dite : le positif exhibe
    une orientation et la teste en chaque point ; le negatif epuise une GRILLE
    de 642 directions, donc il vaut a la resolution de cette grille."""
    pts, nrm = _plan_points(n=120)
    v = decide_indexed_pass(solver, pts, nrm, n_probe=10, max_candidates=3)
    assert v.verdict == "3+2"
    assert v.basis == "verification"
    assert v.conclusive
    doc = decide_indexed_pass.__doc__ or ""
    assert "REPARTIS" in doc
    from xyzac.strategy_planner.indexed_pass import IndexedPassVerdict
    assert "resolution de la grille" in (IndexedPassVerdict.conclusive.__doc__ or "")


def test_probe_points_are_spread_not_a_prefix(solver):
    """Choix INVERSE de celui d'une maquette, et pour une bonne raison : ici on
    veut faire retrecir l'intersection le plus vite possible, donc des points
    dissemblables. Un prefixe contigu, lui, preserve la continuite du chemin —
    ce qu'il faut pour une trajectoire, pas pour une intersection.

    Verification concrete : une passe dont seul le debut est inaccessible doit
    etre vue comme telle, et une dont seule la FIN l'est aussi.
    """
    for mauvais in (0, 59, 119):
        pts, nrm = _plan_points(n=120)
        nrm = nrm.copy()
        nrm[mauvais] = [0.0, 0.0, -1.0]
        v = decide_indexed_pass(solver, pts, nrm, n_probe=120, max_candidates=1)
        assert v.verdict == "inatteignable", (mauvais, v.describe())
        assert mauvais in v.unreachable_points


# ------------------------------------------- le banc de performance

def test_the_benchmark_kernels_use_the_measured_sizes():
    """Le banc a d'abord mesure ses micro-noyaux a N = 34 146 — la taille du
    champ AVANT prefiltre — puis a 1 980, la taille avant la bande par
    coquille. Les deux surestimaient, d'un facteur 17 et 3,5.

    Mesurer une taille qui n'existe pas donne un chiffre exact et faux. Les
    constantes sont donc celles qui ont ete OBSERVEES dans la boucle chaude,
    et ce test les y attache.
    """
    import importlib.util
    from pathlib import Path

    chemin = Path(__file__).resolve().parents[1] / "tools" / "bench_platform.py"
    spec = importlib.util.spec_from_file_location("bench_platform", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.N_OBST == 1980, "mediane du champ apres prefiltre spherique"
    assert mod.N_ROWS == 691, "mediane des lignes apres la bande par coquille"
    assert mod.M_POSES == 16, "taille de bloc de verify_direction"
    assert mod.N_ROWS < mod.N_OBST, (
        "la bande par coquille filtre : l'inverse signalerait qu'elle ne sert "
        "a rien, ou que la mesure porte sur la mauvaise etape")
    # le banc doit tourner sans corpus, sinon il est inutilisable la ou il
    # importe le plus : sur une machine qu'on vient de mettre en service
    res = mod.micro()
    assert res[f"clearance_{mod.N_ROWS}x{mod.M_POSES}_us"] > 0.0
    assert res["triade_4Mo_Go_par_s"] > 0.0
    assert "surcout_appel_numpy_us" in res


def test_the_benchmark_never_prints_an_extrapolation():
    """Le banc mesure ; il ne predit pas. Aucun facteur d'extrapolation ne
    doit y figurer, faute de quoi il redeviendrait la phrase qu'il remplace."""
    from pathlib import Path

    lignes = (Path(__file__).resolve().parents[1] / "tools" / "bench_platform.py"
              ).read_text(encoding="utf-8").lower().splitlines()
    # Fenetre de +/-2 lignes et non la ligne seule : la prose passe a la ligne,
    # et un test ligne par ligne sur du texte enroule est la meme faute que
    # chercher un import par grep au lieu de l'AST. Elle vient de se reproduire.
    marqueurs = ("ne predit", "pas extrapol", "reste une extrapolation",
                 "n'apparait", "aucun chiffre", "mesures, pas extrapoles")
    for i, ligne in enumerate(lignes):
        if "extrapol" not in ligne:
            continue
        fenetre = " ".join(lignes[max(0, i - 2):i + 3])
        assert any(m in fenetre for m in marqueurs), lignes[i]
