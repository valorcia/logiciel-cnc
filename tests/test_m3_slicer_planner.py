"""Slicer soustractif, planificateur de gammes, import STEP (jalon M3)."""

import numpy as np
import pytest

from xyzac.geometry_core import brep
from xyzac.geometry_core.healing import (
    UnusableShapeError,
    diagnose_step,
    load_step_checked,
    require_usable,
)
from xyzac.kinematics_solver import KinematicsSolver
from xyzac.machine_model import Setup, default_xyzac_kit
from xyzac.stock_engine import stock_from_part
from xyzac.stock_engine.material import MaterialState
from xyzac.strategy_planner import (
    candidate_directions,
    evaluate_candidates,
    indexed_orientation_plan,
    plan_roughing,
)
from xyzac.subtractive_slicer import (
    continuous_path,
    indexed_frame,
    simulate_removal,
    slice_for_direction,
)
from xyzac.subtractive_slicer.slicer import _disc, _dilate2d
from xyzac.tool_model import build_endmill


@pytest.fixture(scope="module")
def pocket(corpus_dir):
    shape = brep.load_step(corpus_dir / "C02_poche_droite.step")
    verts, tris, _ = brep.tessellate(shape, deflection=0.3)
    bb = brep.bounding_box(shape)
    stock = stock_from_part(bb, margin_xy=2.0, margin_z_top=2.0, margin_z_bottom=2.0)
    return shape, verts, tris, stock, bb


def _material(pocket, pitch=1.5, allowance=None):
    _, verts, tris, stock, _ = pocket
    return MaterialState.from_setup(stock, verts, tris, pitch=pitch,
                                    finish_allowance=allowance)


# ------------------------------------------------- surepaisseur metrique

@pytest.mark.parametrize("pitch", [1.6, 1.0, 0.7])
def test_finish_allowance_is_independent_of_grid_pitch(pocket, pitch):
    """Defaut mesure avant correction : une surepaisseur demandee a 0,2 mm
    devenait 1,6 / 1,0 / 0,7 mm selon le pas de grille, parce qu'elle etait
    realisee par une dilatation d'un nombre ENTIER de voxels.

    L'utilisateur reglait sa finition, et c'etait la resolution du solveur qui
    decidait. La transformee de distance respecte la valeur demandee.
    """
    _, _, _, _, _ = pocket
    ms = _material(pocket, pitch=pitch, allowance=0.2)
    part_volume = 72000.0
    # A 0,2 mm de surepaisseur, le protege depasse la piece de quelques pour
    # cent au plus — et non d'un tiers comme avec la dilatation entiere.
    assert ms.protected_volume_mm3 == pytest.approx(part_volume, rel=0.06)


def test_larger_allowance_protects_more(pocket):
    small = _material(pocket, pitch=1.0, allowance=0.2).protected_volume_mm3
    large = _material(pocket, pitch=1.0, allowance=2.0).protected_volume_mm3
    assert large > small * 1.2


# -------------------------------------------------------- visibilite

def test_reachability_is_direction_dependent_and_sensible(pocket):
    """Une poche ouverte vers le haut doit etre vue d'en haut, pas de cote."""
    ms = _material(pocket)
    top = ms.reachable_volume_mm3(np.array([0.0, 0.0, 1.0]))
    side = ms.reachable_volume_mm3(np.array([1.0, 0.0, 0.0]))
    assert top > side * 1.3


def test_protected_material_blocks_rays_but_removable_does_not(pocket):
    """Le brut rencontre en chemin ne bloque pas : il sera parti quand on
    arrivera la. Le compter comme obstacle declarerait tout inaccessible."""
    ms = _material(pocket)
    reach = ms.reachable_from(np.array([0.0, 0.0, 1.0]))
    assert reach.sum() > 0
    assert not (reach & ms.protected).any()


# ------------------------------------------------------- dilatation 2D

@pytest.mark.parametrize("r", [2.0, 3.0, 5.0])
def test_disc_dilation_has_the_right_area(r):
    d = _disc(r)
    assert d.sum() == pytest.approx(np.pi * r * r, rel=0.08)


@pytest.mark.parametrize("r,offset", [(3.0, (2, 2)), (5.0, (3, 4)), (5.0, (4, 3))])
def test_disc_covers_diagonals_that_the_l1_ball_misses(r, offset):
    """Une dilatation 4-connexe repetee donne la boule L1 — un LOSANGE plus
    PETIT que le disque dans les diagonales.

    Exemple : l'offset (2, 2) est a 2,83 du centre, donc DANS le disque de
    rayon 3, mais a 4 en distance L1, donc hors du losange. Appliquee a la zone
    interdite, la boule L1 autoriserait des positions d'outil qui gougent.
    """
    dx, dy = offset
    assert np.hypot(dx, dy) <= r, "l'offset doit etre dans le disque"
    assert dx + dy > r, "et hors du losange L1, sinon le test ne prouve rien"
    d = _disc(r)
    c = d.shape[0] // 2
    assert d[c + dy, c + dx]


def test_dilation_reaches_the_full_radius():
    m = np.zeros((21, 21), dtype=bool)
    m[10, 10] = True
    grown = _dilate2d(m, 3.0)
    assert grown[10, 13] and grown[13, 10]     # axes
    assert grown[12, 12]                       # diagonale a 2,83 <= 3


# ------------------------------------------------------------ tranchage

def test_indexed_frame_maps_direction_to_z():
    for d in ([0, 0, 1], [1, 0, 0], [0.3, 0.5, 0.8]):
        d = np.array(d, float) / np.linalg.norm(d)
        assert np.allclose(indexed_frame(d) @ d, [0, 0, 1], atol=1e-12)


def test_slicing_produces_layers_and_a_clearance_plane(pocket, tool):
    ms = _material(pocket)
    r = slice_for_direction(ms, np.array([0.0, 0.0, 1.0]), tool, layer_thickness=2.5)
    assert r.layers
    assert np.allclose(indexed_frame(r.direction), r.frame)
    # ``clearance_z`` est une COTE dans le repere indexe, ``depth_from_top`` une
    # profondeur relative : les comparer directement n'aurait pas de sens. Ce
    # qui doit tenir, c'est que le plan de degagement domine tous les points de
    # coupe, exprimes dans le meme repere.
    pts, rapid = continuous_path(r, 2.0)
    z_index = (pts @ r.frame.T)[:, 2]
    assert r.clearance_z >= z_index.max() - 1e-6
    assert r.clearance_z > z_index[~rapid].max()


def test_roughing_never_gouges_the_protected_part(pocket, tool):
    """Propriete la plus importante du slicer : il peut laisser de la matiere,
    il ne doit JAMAIS entamer la piece."""
    ms = _material(pocket, pitch=1.5)
    r = slice_for_direction(ms, np.array([0.0, 0.0, 1.0]), tool,
                            layer_thickness=2.5, safety_clearance=0.3)
    stats = simulate_removal(ms, r, tool, point_spacing=1.5)
    assert stats.gouged_voxels == 0, (
        f"{stats.gouged_voxels} voxels de la piece finale ont ete entames")


def test_roughing_removes_a_large_share_of_what_it_sees(pocket, tool):
    ms = _material(pocket, pitch=1.5)
    r = slice_for_direction(ms, np.array([0.0, 0.0, 1.0]), tool, layer_thickness=2.5)
    stats = simulate_removal(ms, r, tool, point_spacing=1.5)
    assert stats.removed_mm3 > 0.4 * r.reachable_mm3


def test_grid_extends_beyond_the_stock_for_profiling(pocket, tool):
    """Pour profiler un flanc, le centre de l'outil est HORS du brut. Une grille
    calee sur la matiere n'a pas de cellule pour l'accueillir, et le flanc reste
    intact — 8 000 mm3 jamais touches sur un simple pave, avant correction."""
    ms = _material(pocket, pitch=1.5)
    r = slice_for_direction(ms, np.array([0.0, 0.0, 1.0]), tool, layer_thickness=2.5)
    pts, _ = continuous_path(r, 2.0)
    lo, hi = ms.grid.origin, ms.grid.origin + np.array(ms.grid.shape) * ms.grid.pitch
    outside = np.any((pts < lo) | (pts > hi), axis=1)
    assert outside.any(), "aucune position d'outil hors du brut : pas de profilage"


def test_link_moves_are_explicit_and_flagged(pocket, tool):
    """Les liaisons entre passes doivent exister dans la trajectoire.

    Sans elles, le validateur relie les extremites en ligne droite — et cette
    droite traverse la matiere. Les collisions signalees etaient reelles : la
    trajectoire, telle que decrite, passait dans la piece.
    """
    ms = _material(pocket, pitch=1.5)
    r = slice_for_direction(ms, np.array([0.0, 0.0, 1.0]), tool, layer_thickness=2.5)
    pts, rapid = continuous_path(r, 2.0)
    assert rapid.any() and not rapid.all()
    # Les liaisons remontent au plan de degagement, exprime dans le repere indexe.
    z_index = pts @ r.frame.T
    assert z_index[rapid, 2].max() == pytest.approx(r.clearance_z, abs=1e-6)
    assert z_index[~rapid, 2].max() < r.clearance_z


def test_link_moves_are_sparse(pocket, tool):
    """Une liaison est une droite : la densifier au pas des points de coupe
    gonflait le programme de 94 % de points qui n'enlevent rien. La subdivision
    est le travail du verificateur de balayage."""
    ms = _material(pocket, pitch=1.5)
    r = slice_for_direction(ms, np.array([0.0, 0.0, 1.0]), tool, layer_thickness=2.5)
    _, rapid = continuous_path(r, 2.0)
    assert rapid.mean() < 0.5


# ----------------------------------------------------------- planning

def test_vertical_indexation_is_a_valid_candidate(machine):
    """La singularite A -> 0 est un probleme de MOUVEMENT, pas de POSITION.

    En 3+2 l'axe C est bloque : il n'y a rien a suivre, donc rien de mal
    conditionne. Refuser A = 0 en indexation interdirait l'usinage vertical —
    la prise la plus courante d'une XYZAC. Avant correction, le planner ne
    proposait jamais +Z et laissait intacte toute poche ouverte vers le haut.
    """
    kin = KinematicsSolver(machine)
    up = np.array([0.0, 0.0, 1.0])
    assert kin.ik_best(up) is None                       # refuse par defaut
    sol = kin.ik_best(up, allow_singular=True)
    assert sol is not None and abs(sol.a_deg) < 1e-9


def test_candidates_are_filtered_by_machine_travel(pocket, tool):
    """-Z demande A = 180 deg : hors des courses du berceau. Le planner ne doit
    pas le proposer — usiner le dessous exige une reprise, pas une indexation."""
    shape, _, _, stock, bb = pocket
    setup = Setup(setup_id="p", machine=default_xyzac_kit(), part_step_path="x.step",
                  stock=stock, tools=[tool])
    ms = _material(pocket)
    cands = evaluate_candidates(candidate_directions(shape, setup), ms, setup)
    dirs = [c.direction for c in cands]
    assert any(np.allclose(d, [0, 0, 1]) for d in dirs), "+Z doit etre candidate"
    assert not any(np.allclose(d, [0, 0, -1]) for d in dirs), "-Z est hors courses"


def test_greedy_plan_covers_most_of_the_material(pocket, tool):
    """Ce que la gamme couvre — de ce qu'elle a le droit de couvrir.

    Ce test exigeait 40 %, et c'est l'ajout de la mesure des courses
    LINEAIRES qui l'a fait tomber a 31 %. La raison est instructive :
    l'indexation ``+Z``, la plus riche des cinq (36 028 mm3), sort de la
    course Z sur 532 de ses 5 512 positions — de **0,2 mm**. Le plan
    l'incluait et annonçait 40 % d'une gamme que la machine aurait refusee a
    la premiere ligne.

    Puis la porte de COLLISION sur l'entree en matiere l'a fait tomber a
    16 % : les indexations laterales, a 45 mm de jauge, font traverser le brut
    par le nez de broche ou le porte-outil avant meme de couper.

    16 % executables valent mieux que 40 % dont une operation s'arrete en
    pleine matiere. Et aucun rejet n'est muet : celui des courses porte le
    decalage qui rendrait l'indexation utilisable — et reposer la piece de
    2 mm suffit a remonter la gamme a 30 % (voir
    ``test_the_cutting_edge_touching_material_is_not_a_crash``). C'est cette
    pose corrigee qui est la bonne, et c'est l'atelier qui la propose.
    """
    shape, _, _, stock, bb = pocket
    setup = Setup(setup_id="p", machine=default_xyzac_kit(), part_step_path="x.step",
                  stock=stock, tools=[tool],
                  part_to_table_mm=[float(-bb.center[0]), float(-bb.center[1]), 25.0])
    ms = _material(pocket, pitch=1.6)
    plan, report = plan_roughing(shape, setup, ms, tool, layer_thickness=3.0,
                                 point_spacing=2.0, max_setups=4)
    assert plan.operations
    # Le seuil dit ce que cette POSE permet, et rien de plus. Le relever
    # reviendrait a exiger une gamme que la machine refuserait.
    assert report.removed_fraction > 0.1
    assert report.gouged_voxels == 0

    # AUCUNE operation retenue ne sort des courses : c'est la condition qui
    # remplace le seuil de 40 %.
    assert report.courses and all(c.tient for c in report.courses)
    assert len(report.courses) == len(plan.operations)

    # et l'indexation ecartee est rapportee, avec de quoi la recuperer
    assert report.refuses_course, "un rejet muet ferait croire a une limite"
    ref = report.refuses_course[0]
    assert 0.0 < max(ref.course.exces_mm) < 1.0, ref.describe()
    assert "Décaler la pièce" in ref.course.consigne()
    assert ref.candidate.reachable_mm3 > report.removed_per_step[0], \
        "l'indexation ecartee etait la plus riche : ca vaut la peine de le dire"


def test_plan_report_keeps_the_full_candidate_list(pocket, tool):
    """Bug corrige : la liste des candidates etait videe pendant la boucle, ce
    qui faisait attribuer a « aucune direction ne le voit » de la matiere que
    des directions non retenues voyaient parfaitement."""
    shape, _, _, stock, bb = pocket
    setup = Setup(setup_id="p", machine=default_xyzac_kit(), part_step_path="x.step",
                  stock=stock, tools=[tool],
                  part_to_table_mm=[0.0, 0.0, 25.0])
    ms = _material(pocket, pitch=2.0)
    _, report = plan_roughing(shape, setup, ms, tool, layer_thickness=4.0,
                              point_spacing=3.0, max_setups=2)
    assert len(report.candidates) >= len(report.chosen)
    assert len(report.candidates) >= 4


def test_indexed_plan_has_constant_orientation(pocket, tool):
    _, _, _, stock, _ = pocket
    setup = Setup(setup_id="p", machine=default_xyzac_kit(), part_step_path="x.step",
                  stock=stock, tools=[tool])
    pts = np.zeros((7, 3))
    plan = indexed_orientation_plan(pts, np.array([0.0, 0.0, 1.0]), setup)
    assert plan.feasible
    assert len(set(plan.a_deg)) == 1 and len(set(plan.c_deg)) == 1
    assert plan.indexed_fraction == 1.0


# ------------------------------------------------------- import STEP

def test_clean_step_is_not_healed(corpus_dir):
    """ShapeFix peut deteriorer une geometrie saine. On ne repare pas ce qui
    n'est pas casse."""
    _, diag, heal = load_step_checked(corpus_dir / "C11_cavite_spherique.step")
    assert not diag.needs_healing
    assert not heal.applied


def test_open_shell_is_detected_and_refused(degraded_dir):
    """Un shell ouvert est topologiquement VALIDE et OCCT lui calcule meme un
    volume plausible, par integration sur ses faces. Ce qui trahit le defaut,
    c'est l'absence de solide — sans quoi le lancer de rayons de la voxelisation
    remplit la matiere n'importe comment, et le moteur rend une gamme credible
    et fausse.
    """
    shape, diag, heal = load_step_checked(degraded_dir / "D01_shell_ouvert.step")
    assert diag.n_solids == 0
    assert diag.needs_healing
    assert not heal.resolved, "ShapeFix ne peut pas inventer la face manquante"
    with pytest.raises(UnusableShapeError, match="aucun solide"):
        require_usable(shape, heal.after or diag)


def test_unit_confusion_is_flagged_as_plausibility_not_defect(degraded_dir):
    """Une piece de 2 mm est saine : ce n'est pas un defaut a reparer, c'est une
    question a poser. Confondre les deux ferait passer ShapeFix sur une piece
    intacte."""
    _, diag, heal = load_step_checked(degraded_dir / "D02_unites_pouces.step")
    assert not diag.geometry_issues
    assert diag.plausibility_warnings
    assert not heal.applied
    assert "25,4" in " ".join(diag.plausibility_warnings)


def test_oversized_part_is_flagged(degraded_dir):
    _, diag, heal = load_step_checked(degraded_dir / "D03_trop_grande.step")
    assert diag.plausibility_warnings and not diag.geometry_issues
    assert not heal.applied


def test_healing_refuses_to_change_the_part(corpus_dir):
    """Garde-fou : une reparation qui deplace la matiere de plus d'un millieme
    n'est plus une reparation, c'est une modification de la piece — et ce n'est
    pas a un outil de la decider a la place du concepteur."""
    from xyzac.geometry_core.healing import heal_shape

    shape = brep.load_step(corpus_dir / "C13_arbre_gorge_torique.step")
    diag = diagnose_step(corpus_dir / "C13_arbre_gorge_torique.step", shape=shape)
    # On force un besoin de reparation avec une precision absurde.
    diag.geometry_issues.append("defaut simule pour le test")
    res = heal_shape(shape, diag, tolerance=5.0, max_volume_change_ratio=1e-9)
    if res.applied:
        assert res.volume_change_ratio <= 1e-9
    else:
        assert "REFUSEE" in res.reason or "saine" in res.reason


def test_fixtures_are_protected_material(pocket, tool):
    """Le slicer ne connait que deux choses : la matiere a enlever et la piece a
    conserver. Un bridage n'etant ni l'une ni l'autre, il planifiait des passes
    jusqu'au fond du brut — c'est-a-dire DANS l'etau. Le validateur les refusait
    ensuite avec des penetrations de plusieurs millimetres.

    Les traiter comme « protege » est la bonne semantique : un bridage ne
    s'enleve pas, et il masque une direction exactement comme la piece.
    """
    from xyzac.machine_model import Fixture, FixtureKind

    _, _, _, stock, _ = pocket
    jaw = Fixture(name="mors", kind=FixtureKind.VISE,
                  lo=[float(stock.lo[0]) - 10, float(stock.lo[1]) - 4,
                      float(stock.lo[2]) - 10],
                  hi=[float(stock.lo[0]) + 1, float(stock.hi[1]) + 4,
                      float(stock.lo[2]) + 4],
                  keepout_mm=1.5)
    setup = Setup(setup_id="fx", machine=default_xyzac_kit(), part_step_path="x.step",
                  stock=stock, fixtures=[jaw], tools=[tool])

    ms = _material(pocket, pitch=1.5)
    before = ms.protected_volume_mm3
    added = ms.protect_fixtures(setup)
    assert added > 0
    assert ms.protected_volume_mm3 > before

    # Et la consequence attendue : la zone du mors n'est plus enlevable.
    centers = ms.grid.centers().reshape(ms.grid.shape + (3,))
    in_jaw = np.all((centers >= np.array(jaw.lo)) & (centers <= np.array(jaw.hi)), axis=-1)
    assert not (ms.removable() & in_jaw).any()


# ------------------------------------------ le sens d'attaque de l'outil


def _tranche(pocket, tool, **kw):
    material = _material(pocket)
    return slice_for_direction(material, np.array([0.0, 0.0, 1.0]), tool,
                               layer_thickness=3.0, **kw)


def test_no_pass_is_entered_at_rapid_feed(pocket, tool):
    """LE defaut signale par l'utilisateur : « attention au sens de l'attaque
    de l'outil ».

    Mesure avant correction, sur une ebauche du corpus : 1 615 passes sur
    1 615 arrivaient a la profondeur de coupe par une descente verticale EN
    RAPIDE, s'arretant exactement sur le premier point de coupe, sans aucune
    marge — et 0 palier d'approche en avance travail.

    Le plus instructif est que la regle etait deja ecrite dans
    ``with_approach_retract`` : « un rapide qui finit exactement sur la
    surface n'a aucune marge pour une erreur d'origine palpee, et c'est le
    mouvement qui casse les outils ». Elle etait appliquee UNE fois, au
    premier point de l'operation. Un principe juste applique une fois sur
    mille n'est pas un principe.
    """
    sl = _tranche(pocket, tool)
    P, R = continuous_path(sl, point_spacing=2.0)
    assert len(P) > 100
    d = np.array([0.0, 0.0, 1.0])
    h = P @ d
    so = max(sl.safety_clearance, 1.0)

    entrees = np.flatnonzero(R[:-1] & ~R[1:])
    assert len(entrees) > 5, "il faut plusieurs passes pour que le test porte"
    for i in entrees:
        # le mouvement qui ARRIVE sur la coupe se parcourt en avance : c'est
        # le drapeau du point d'arrivee qui le dit, et il vaut False
        assert not R[i + 1]
        # et il descend d'exactement la hauteur d'approche, a la verticale
        dh = h[i + 1] - h[i]
        lat = np.linalg.norm((P[i + 1] - P[i]) - dh * d)
        assert dh < 0, (i, dh)
        assert abs(abs(dh) - so) < 1e-6, (i, dh, so)
        assert lat < 1e-6, (i, lat)


def test_no_pass_is_left_at_rapid_feed(pocket, tool):
    """La sortie de matiere est le defaut symetrique, et il casse aussi : un
    rapide qui part de la profondeur de coupe arrache au lieu de couper."""
    sl = _tranche(pocket, tool)
    P, R = continuous_path(sl, point_spacing=2.0)
    d = np.array([0.0, 0.0, 1.0])
    h = P @ d
    so = max(sl.safety_clearance, 1.0)

    # un point rapide precede d'un point de coupe : la sortie
    sorties = np.flatnonzero(~R[:-1] & R[1:])
    assert len(sorties) > 5
    for i in sorties:
        # le degagement de ``so`` mm a deja eu lieu EN AVANCE avant ce rapide
        dh = h[i] - h[i - 1]
        assert dh > 0, (i, dh)
        assert abs(dh - so) < 1e-6, (i, dh, so)


def test_the_sweep_direction_is_a_declared_choice(pocket, tool):
    """Mesure avant correction : 4 634 segments de coupe dans un sens et
    4 634 dans l'autre — exactement moitie-moitie, parce que le zigzag inverse
    chaque rangee. En fraisage, cela alterne l'avalant et l'opposition a
    chaque passe.

    Le defaut n'etait pas l'alternance, qui est defendable en ebauche, mais que
    PERSONNE ne l'ait choisie : aucun parametre, aucune trace. Elle est
    desormais nommee, portee par le resultat, et ecrite dans les notes.
    """
    from xyzac.subtractive_slicer.slicer import (BALAYAGE_ALTERNE,
                                                 BALAYAGE_UNIDIRECTIONNEL)

    def sens(sl):
        P, R = continuous_path(sl, point_spacing=2.0)
        coupe = ~(R[1:] | R[:-1])
        v = (P[1:] - P[:-1])[coupe]
        v = v[np.linalg.norm(v, axis=1) > 1e-9]
        u = v / np.linalg.norm(v, axis=1, keepdims=True)
        ps = u @ u[0]
        return int((ps > 0.9).sum()), int((ps < -0.9).sum())

    zz = _tranche(pocket, tool, balayage=BALAYAGE_ALTERNE)
    uni = _tranche(pocket, tool, balayage=BALAYAGE_UNIDIRECTIONNEL)

    assert zz.balayage == BALAYAGE_ALTERNE
    assert uni.balayage == BALAYAGE_UNIDIRECTIONNEL

    meme_zz, inv_zz = sens(zz)
    meme_uni, inv_uni = sens(uni)
    assert inv_zz > 0, "le zigzag DOIT alterner : c'est ce qui le definit"
    assert inv_uni == 0, (meme_uni, inv_uni)
    assert meme_uni > 10

    # le mode par defaut ne change pas en silence : le changer changerait
    # toutes les gammes deja validees et le temps d'usinage
    assert _tranche(pocket, tool).balayage == BALAYAGE_ALTERNE


def test_an_unknown_sweep_is_refused(pocket, tool):
    """Un mode inconnu doit lever, et non retomber sur un defaut : « balayge »
    mal orthographie donnerait alors du zigzag en croyant l'autre."""
    with pytest.raises(ValueError, match="balayage"):
        _tranche(pocket, tool, balayage="avalant")


def test_the_plan_records_the_sweep_it_used(pocket, tool):
    """Une gamme dont on ne peut pas relire le sens de coupe n'est pas
    auditable — et le sens de coupe se relit sur la piece."""
    shape, _, _, stock, _ = pocket
    setup = Setup(setup_id="s", machine=default_xyzac_kit(),
                  part_step_path="x.step", stock=stock, tools=[tool])
    plan, _ = plan_roughing(shape, setup, _material(pocket), tool,
                            max_setups=1, layer_thickness=3.0,
                            point_spacing=2.0,
                            balayage="unidirectionnel")
    assert plan.operations
    assert "balayage unidirectionnel" in plan.operations[0].notes


def test_a_tool_that_cannot_plunge_never_plunges(pocket):
    """Second defaut du sens d'attaque, et le plus instructif.

    ``ToolAssembly`` porte depuis le debut ``can_plunge`` et
    ``max_ramp_angle_deg``. Une recherche sur tout le code source ne trouvait
    AUCUNE lecture de ces deux champs hors du module qui les definit : le
    slicer produisait des plongees avec une fraise a trois dents, qui declare
    elle-meme ne pas pouvoir plonger. Une donnee juste, presente et ignoree
    est pire qu'une donnee absente — on croit l'avoir prise en compte.
    """
    from xyzac.tool_model import build_endmill

    droit = build_endmill("EM3", 6.0, 20.0, stickout=45.0, flute_count=3)
    assert not droit.can_plunge, "le presuppose du test"
    assert droit.max_ramp_angle_deg > 0

    sl = _tranche(pocket, droit)
    P, R = continuous_path(sl, point_spacing=2.0, tool=droit)
    d = np.array([0.0, 0.0, 1.0])
    h = P @ d
    coupe = ~(R[1:] | R[:-1])
    dh = h[1:] - h[:-1]
    lat = np.linalg.norm((P[1:] - P[:-1]) - np.outer(dh, d), axis=1)

    # aucune descente VERTICALE en coupe : ce serait une plongee
    plongees = coupe & (dh < -1e-9) & (lat < 1e-9)
    assert not plongees.any(), int(plongees.sum())

    # et toute descente en coupe reste sous l'angle que l'outil declare
    rampes = coupe & (dh < -1e-9) & (lat > 1e-9)
    assert rampes.sum() > 20, "il doit y avoir des rampes"
    angles = np.degrees(np.arctan2(-dh[rampes], lat[rampes]))
    assert angles.max() <= droit.max_ramp_angle_deg + 1e-6, angles.max()


def test_a_tool_that_can_plunge_is_allowed_to(pocket):
    """La rampe n'est pas imposee a tout le monde : une hemispherique coupe au
    centre et le declare. Lui imposer une rampe doublerait le programme pour
    rien — mesure : 5 595 points contre 10 044."""
    from xyzac.tool_model import build_ballnose

    bille = build_ballnose("BN6", 6.0, 20.0, stickout=45.0)
    assert bille.can_plunge

    sl = _tranche(pocket, bille)
    court, _ = continuous_path(sl, point_spacing=2.0, tool=bille)
    from xyzac.tool_model import build_endmill
    droit = build_endmill("EM3", 6.0, 20.0, stickout=45.0, flute_count=3)
    long_, _ = continuous_path(sl, point_spacing=2.0, tool=droit)
    assert len(court) < len(long_)


def test_a_tool_that_can_neither_plunge_nor_ramp_is_refused(pocket, tool):
    """Un outil qui declare ne pas pouvoir plonger ET un angle de rampe nul ne
    peut pas entrer en matiere. Le dire, plutot que de plonger quand meme."""
    impossible = tool.model_copy(update={"can_plunge": False,
                                         "max_ramp_angle_deg": 0.0})
    sl = _tranche(pocket, impossible)
    with pytest.raises(ValueError, match="ni plonger ni ramper"):
        continuous_path(sl, point_spacing=2.0, tool=impossible)


def test_ramps_that_could_not_be_built_are_counted_not_hidden(pocket, tool):
    """Des passes trop courtes pour une rampe existent reellement — mesure sur
    le corpus. Refuser toute la gamme pour l'une d'elles serait
    disproportionne ; les resoudre en silence serait pire. Elles sont donc
    entrees en plongee ET comptees, et le planner ecrit le compte dans les
    notes : une exception qu'on ne compte pas cesse d'etre une exception.
    """
    from xyzac.subtractive_slicer.slicer import _entree_en_matiere

    # une passe reduite a un seul point : aucune direction ou ramper
    un_point = np.array([[0.0, 0.0, 5.0]])
    journal: list = []
    pts = _entree_en_matiere(un_point, 1.0, tool, journal)
    assert len(pts) == 1, "faute de rampe, on entre au point de coupe"
    assert journal, "et cela doit etre consigne"
    assert "plongee" in journal[0]

    # sans journal fourni, le comportement ne change pas
    assert len(_entree_en_matiere(un_point, 1.0, tool)) == 1


# ------------------- les courses LINEAIRES entrent dans la decision (M13a)

def _machine_essai(**kw):
    """Une machine reduite, pour poser des questions de course sans piece."""
    from xyzac.machine_model.machine import LinearAxis, MachineKinematics, RotaryAxis

    d = dict(x=LinearAxis(name="X", min_mm=-100.0, max_mm=100.0,
                          max_feed_mm_min=4000.0),
             y=LinearAxis(name="Y", min_mm=-100.0, max_mm=100.0,
                          max_feed_mm_min=4000.0),
             z=LinearAxis(name="Z", min_mm=-100.0, max_mm=50.0,
                          max_feed_mm_min=3000.0),
             a=RotaryAxis(name="A", min_deg=-120.0, max_deg=30.0,
                          max_feed_deg_min=3600.0),
             c=RotaryAxis(name="C", min_deg=-360.0, max_deg=360.0,
                          continuous=True, max_feed_deg_min=7200.0),
             pivot_a=[0.0, 0.0, -40.0], pivot_c=[0.0, 0.0, 0.0])
    d.update(kw)
    return MachineKinematics(machine_id="essai", **d)


def test_a_trajectory_inside_the_travel_is_conclusive_both_ways():
    """Le domaine des courses est une BOITE, donc convexe.

    C'est ce qui rend ce test EXACT, et c'est le seul de tout le projet a
    l'etre dans les deux sens : un segment dont les deux extremites tiennent
    tient entierement, donc tester les sommets de la polyligne suffit. Rien
    n'est echantillonne, donc il n'y a pas de reserve a enoncer.
    """
    from xyzac.strategy_planner.travel import course_lineaire

    m = _machine_essai()
    P = np.array([[0.0, 0.0, 0.0], [10.0, 10.0, 10.0]])
    c = course_lineaire(m, P, (0.0, 0.0, 0.0), 0.0, 0.0, exact=True)
    assert c.tient and c.concluant and c.n_hors == 0
    assert c.correction_piece_mm is None       # rien a corriger
    assert "tient" in c.consigne()


def test_the_part_height_becomes_a_Y_travel_when_the_cradle_tips():
    """Le fait que personne ne peut deviner, et qui a mis C05 hors course.

    A -90° le berceau couche la piece : un point a la hauteur z se retrouve en
    Y = z + 40 (l'offset du pivot A). La hauteur de la piece se paie donc en
    course Y, et ce module doit le montrer plutot que le laisser decouvrir a la
    machine.
    """
    from xyzac.strategy_planner.travel import course_lineaire

    m = _machine_essai()
    # un point a 70 mm de haut, 25 mm de cales : Y attendu = 70 + 25 + 40 = 135
    c = course_lineaire(m, np.array([[0.0, 0.0, 70.0]]), (0.0, 0.0, 25.0),
                        -90.0, 0.0, exact=True)
    assert abs(c.hi[1] - 135.0) < 1e-6, c.describe()
    assert not c.tient
    assert c.axe_le_plus_court == "Y"
    assert abs(c.exces_mm[1] - 35.0) < 1e-6


def test_the_remedy_is_computed_in_the_frame_where_the_operator_acts():
    """Un depassement sans remede laisse l'utilisateur devant un constat.

    Le depassement se lit dans le repere MACHINE, les cales agissent dans le
    repere PIECE : le vecteur rendu est donc transporte, et l'appliquer doit
    reellement faire tenir la trajectoire. Ce test le VERIFIE en l'appliquant,
    au lieu de se fier au signe.
    """
    from xyzac.strategy_planner.travel import course_lineaire

    m = _machine_essai()
    P = np.array([[0.0, 0.0, 70.0], [10.0, 5.0, 60.0]])
    cales = np.array([0.0, 0.0, 25.0])
    c = course_lineaire(m, P, cales, -90.0, 0.0, exact=True)
    assert c.correction_piece_mm is not None, c.describe()

    corrige = course_lineaire(m, P, cales + np.asarray(c.correction_piece_mm),
                              -90.0, 0.0, exact=True)
    assert corrige.tient, corrige.describe()
    assert "Décaler la pièce" in c.consigne()
    # et la reserve est dite : ce calcul ne regarde pas les collisions
    assert "ne touche" in c.consigne()


def test_an_extent_longer_than_the_travel_admits_no_shift():
    """Deux echecs qui se ressemblent et ne se corrigent pas pareil.

    Une piece decalee sort par un bout : la translation la rattrape. Une piece
    plus LONGUE que la course sort par les deux bouts : translater ne fait que
    changer le bout qui depasse. Proposer un decalage dans ce cas serait
    envoyer l'operateur refaire son montage pour rien.
    """
    from xyzac.strategy_planner.travel import course_lineaire

    m = _machine_essai()          # X sur 200 mm
    P = np.array([[-130.0, 0.0, 0.0], [130.0, 0.0, 0.0]])
    c = course_lineaire(m, P, (0.0, 0.0, 0.0), 0.0, 0.0, exact=True)
    assert not c.tient
    assert c.correction_piece_mm is None
    assert "Aucun décalage" in c.consigne()
    assert abs(c.etendue_excedentaire_mm[0] - 60.0) < 1e-6


def test_the_envelope_test_never_discards_a_candidate_it_cannot_judge():
    """L'asymetrie du test de boite, et ce qu'on a donc le droit d'en faire.

    Les huit coins donnent EXACTEMENT l'enveloppe machine de la boite : « la
    boite tient » prouve que tout ce qu'elle contient tient. L'inverse ne
    prouve rien — la trajectoire n'occupe pas les coins. Le classement peut
    donc favoriser une candidate prouvee, jamais ecarter les autres.
    """
    from xyzac.strategy_planner.travel import enveloppe_indexation

    m = _machine_essai()
    dedans = enveloppe_indexation(m, (-10, -10, 0), (10, 10, 10),
                                  (0, 0, 25), 0.0, 0.0, marge_mm=1.0)
    assert dedans.tient and dedans.concluant and not dedans.exact

    dehors = enveloppe_indexation(m, (-10, -10, 0), (10, 10, 70),
                                  (0, 0, 25), -90.0, 0.0, marge_mm=1.0)
    assert not dehors.tient
    assert not dehors.concluant, "un « ne tient pas » de boite ne conclut pas"
    assert "peut-être" in dehors.consigne()


def test_the_planner_prefers_an_indexation_that_fits_and_measures_the_one_it_takes(
        corpus_dir):
    """Le defaut d'origine : le planner classait sur le seul volume enlevable.

    Sur C05 il retenait A = -90°, C = -90° et produisait 3 974 positions hors
    course sur 18 249, sans rien en dire. Deux exigences, donc : une candidate
    dont l'enveloppe TIENT passe devant celles qui ne tiennent pas, et
    l'operation retenue porte la mesure exacte de ce qu'elle demande.
    """
    from xyzac.ui.debug.state import BenchState

    st = BenchState()
    st.load_step(corpus_dir / "C01_bloc_simple.step")
    st.set_default_tool("ballnose", diameter=6.0, stickout=40.0)
    plan, rapport = st.plan_roughing_preview(layer_thickness=3.0, max_setups=1,
                                             pitch=3.0, point_spacing=3.0)

    # toutes les candidates portent une course, et le classement met celles
    # qui tiennent devant
    assert rapport.candidates
    assert all(c.course is not None for c in rapport.candidates)
    tiennent = [c.tient_en_course for c in rapport.candidates]
    assert tiennent == sorted(tiennent, reverse=True), \
        "une candidate qui tient doit passer devant une qui ne tient pas"

    # et l'operation retenue porte la mesure EXACTE, alignee sur ``chosen``
    assert len(rapport.courses) == len(rapport.chosen) == len(plan.operations)
    for co in rapport.courses:
        assert co.exact and co.n_points > 0
        # la note de l'operation dit le depassement, ou ne dit rien
        assert co.tient == ("HORS COURSE" not in plan.operations[0].notes)


def test_an_indexation_the_tool_cannot_enter_is_discarded(pocket, tool):
    """Le defaut que l'ajout des courses a fait apparaitre d'un coup.

    L'indexation d'ebauche etait choisie sur le volume, filtree sur la
    cinematique, puis sur les courses — jamais sur la COLLISION. Sur la poche
    C02 avec une fraise de 45 mm de jauge, l'indexation laterale A = -90° fait
    traverser le brut par le NEZ DE BROCHE pendant l'approche : 0,26 mm de
    penetration au premier segment, 6,5 mm au suivant. Le plan la retenait.

    Ce n'etait pas visible parce que l'indexation du dessus passait toujours
    en premier ; le jour ou elle a ete ecartee pour 2 mm de course, le defaut
    est sorti.
    """
    shape, _, _, stock, bb = pocket
    setup = Setup(setup_id="p", machine=default_xyzac_kit(), part_step_path="x.step",
                  stock=stock, tools=[tool],
                  part_to_table_mm=[float(-bb.center[0]), float(-bb.center[1]), 25.0])
    ms = _material(pocket, pitch=1.6)
    _plan, report = plan_roughing(shape, setup, ms, tool, layer_thickness=3.0,
                                  point_spacing=2.0, max_setups=4)
    assert report.refuses_entree, "les indexations laterales traversent le brut"
    r = report.refuses_entree[0]
    assert r.n_touche > 0 and r.n_segments >= r.n_touche
    # le motif NOMME l'organe : « la tige touche » et « le nez de broche
    # touche » ne se corrigent pas de la meme façon
    assert any(mot in r.motif for mot in
               ("spindle_nose", "holder", "shank", "neck")), r.motif
    assert "outil plus long" in r.consigne()


def test_the_cutting_edge_touching_material_is_not_a_crash(pocket, tool):
    """L'arete de coupe est FAITE pour toucher la matiere.

    Premiere version de cette porte : elle comptait tout contact, donc aussi
    « cutting / PART », et ecartait l'indexation du dessus de la poche C02
    pour avoir coupe. Combien l'ebauche entame la piece FINIE est une autre
    question, et elle a sa propre mesure — ``gouged_voxels``.

    Le test le verifie par sa consequence : l'indexation du dessus, une fois
    la piece reposee de 2 mm, est RETENUE, et la gamme passe de 2 % a 30 %.
    """
    shape, _, _, stock, bb = pocket
    cales = [float(-bb.center[0]), float(-bb.center[1]), 23.0]
    setup = Setup(setup_id="p", machine=default_xyzac_kit(), part_step_path="x.step",
                  stock=stock, tools=[tool], part_to_table_mm=cales)
    ms = _material(pocket, pitch=1.6)
    plan, report = plan_roughing(shape, setup, ms, tool, layer_thickness=3.0,
                                 point_spacing=2.0, max_setups=2)
    assert plan.operations, "l'indexation du dessus doit redevenir utilisable"
    assert any(c.label == "+Z" for c in report.chosen), \
        [c.label for c in report.chosen]
    assert report.removed_fraction > 0.25, report.removed_fraction
    assert not report.refuses_course, "a 23 mm de cales, +Z tient en course"
