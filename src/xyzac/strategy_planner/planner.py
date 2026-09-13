"""Planificateur de gammes : de la piece a la suite d'operations.

C'est ici que se joue la promesse produit — « l'utilisateur ne programme pas du
CAM ». Il n'y a pas d'operation a choisir, pas de poche a designer : le planner
decide seul quelles indexations utiliser, dans quel ordre, et avec quels outils.

Methode : **couverture gloutonne du volume a enlever par des indexations**.

  1. proposer des directions candidates (axes du brut, normales dominantes) ;
  2. ne garder que celles que la cinematique XYZAC atteint reellement ;
  3. choisir la direction qui voit le plus de matiere restante ;
  4. trancher, simuler l'enlevement, mettre l'etat matiere a jour ;
  5. recommencer tant qu'une direction apporte un gain significatif.

Le glouton est assume. Le probleme sous-jacent est une couverture d'ensembles,
donc NP-difficile ; un glouton sur la fonction « volume atteignable » — qui est
sous-modulaire — a une garantie classique de 1 - 1/e. Surtout, il est
**deterministe et explicable** : on peut montrer a l'utilisateur pourquoi telle
indexation a ete retenue, et combien elle apporte. Un optimiseur global serait
meilleur de quelques pourcents et impossible a justifier devant une piece ratee.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..geometry_core import brep
from ..geometry_core.types import normalize
from ..kinematics_solver.solver import KinematicsSolver
from ..machine_model.setup import Setup
from ..stock_engine.material import MaterialState
from ..subtractive_slicer.slicer import (
    SliceResult,
    continuous_path,
    simulate_removal,
    slice_for_direction,
    toolpath_points,
    with_approach_retract,
)
from ..tool_model.assembly import ToolAssembly
from .interfaces import Kinematic, Operation, ProcessPlan, Toolpath


@dataclass
class DirectionCandidate:
    """Une indexation candidate, avec ce qu'elle apporte."""

    direction: np.ndarray
    a_deg: float
    c_deg: float
    reachable_mm3: float
    label: str = ""

    def describe(self) -> str:
        return (f"{self.label or 'dir'} {np.round(self.direction, 3)} "
                f"(A={self.a_deg:7.2f} C={self.c_deg:8.2f}) : "
                f"{self.reachable_mm3:8.0f} mm3 atteignables")


@dataclass
class PlanReport:
    """Trace de la decision. Un plan sans justification n'est pas auditable."""

    candidates: list[DirectionCandidate] = field(default_factory=list)
    chosen: list[DirectionCandidate] = field(default_factory=list)
    removed_per_step: list[float] = field(default_factory=list)
    initial_removable_mm3: float = 0.0
    final_removable_mm3: float = 0.0
    unreachable_mm3: float = 0.0
    gouged_voxels: int = 0

    @property
    def removed_fraction(self) -> float:
        if self.initial_removable_mm3 <= 0:
            return 1.0
        return 1.0 - self.final_removable_mm3 / self.initial_removable_mm3

    def describe(self) -> str:
        lines = [
            f"Gamme : {len(self.chosen)} indexation(s) retenue(s) sur "
            f"{len(self.candidates)} candidates evaluees",
            f"  matiere a enlever : {self.initial_removable_mm3:.0f} mm3",
            f"  enlevee           : {self.removed_fraction * 100:.1f} % "
            f"({self.initial_removable_mm3 - self.final_removable_mm3:.0f} mm3)",
            f"  restante          : {self.final_removable_mm3:.0f} mm3 "
            f"(dont {self.unreachable_mm3:.0f} mm3 qu'aucune indexation candidate ne voit)",
        ]
        if self.gouged_voxels:
            lines.append(f"  ATTENTION : {self.gouged_voxels} voxels proteges touches")
        for c, vol in zip(self.chosen, self.removed_per_step):
            lines.append(f"    {c.describe()}  -> a enleve {vol:.0f} mm3")
        return "\n".join(lines)


def candidate_directions(
    shape, setup: Setup, *, include_face_normals: bool = True,
    min_face_area: float = 50.0, max_candidates: int = 14,
) -> list[np.ndarray]:
    """Directions d'indexation a envisager.

    Les six axes du brut sont toujours proposes : ce sont les prises naturelles
    d'un montage, et elles couvrent l'essentiel des pieces prismatiques. On y
    ajoute les normales des faces significatives, sans quoi une face inclinee
    n'aurait jamais d'indexation qui la regarde de face — et serait usinee en
    rampe par une direction voisine, avec l'etat de surface correspondant.
    """
    dirs = [np.array(v, dtype=np.float64) for v in
            ((0, 0, 1), (0, 0, -1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0))]

    if include_face_normals:
        samples = brep.sample_surface(shape, spacing=2.0)
        for f in brep.face_info(shape):
            if f.area < min_face_area:
                continue
            m = samples.face_ids == f.index
            if not np.any(m):
                continue
            n = samples.normals[m].mean(axis=0)
            nn = float(np.linalg.norm(n))
            if nn < 0.7:
                continue  # face trop courbe pour avoir une normale representative
            d = n / nn
            if all(float(d @ e) < 0.985 for e in dirs):
                dirs.append(d)

    return dirs[:max_candidates]


def evaluate_candidates(
    directions: list[np.ndarray], material: MaterialState, setup: Setup,
) -> list[DirectionCandidate]:
    """Filtre par la cinematique, puis classe par volume atteignable.

    Une direction que le berceau n'atteint pas n'est pas une option, quelle que
    soit la matiere qu'elle verrait. Le filtre cinematique passe donc AVANT le
    classement, et non apres : classer d'abord donnerait un palmares dont la
    tete est irrealisable.
    """
    kin = KinematicsSolver(setup.machine)
    out: list[DirectionCandidate] = []
    for d in directions:
        d = normalize(d)
        # ``allow_singular=True`` : une operation INDEXEE bloque l'axe C, donc la
        # singularite A -> 0 ne gene rien. Voir KinematicsSolver.ik_best.
        sol = kin.ik_best(d, allow_singular=True)
        if sol is None:
            continue
        out.append(DirectionCandidate(
            direction=d, a_deg=sol.a_deg, c_deg=sol.c_deg,
            reachable_mm3=material.reachable_volume_mm3(d),
            label=_axis_label(d),
        ))
    out.sort(key=lambda c: -c.reachable_mm3)
    return out


def _axis_label(d: np.ndarray) -> str:
    names = {(0, 0, 1): "+Z", (0, 0, -1): "-Z", (1, 0, 0): "+X",
             (-1, 0, 0): "-X", (0, 1, 0): "+Y", (0, -1, 0): "-Y"}
    for k, v in names.items():
        if float(d @ np.array(k, dtype=float)) > 0.999:
            return v
    return "oblique"


def plan_roughing(
    shape, setup: Setup, material: MaterialState, tool: ToolAssembly,
    *,
    layer_thickness: float = 2.0,
    stepover_ratio: float = 0.45,
    point_spacing: float = 1.5,
    min_gain_mm3: float = 50.0,
    max_setups: int = 4,
    balayage: str | None = None,
) -> tuple[ProcessPlan, PlanReport]:
    """Construit une gamme d'ebauche par couverture gloutonne.

    ``min_gain_mm3`` arrete la boucle quand une indexation supplementaire
    n'apporte plus grand-chose. Sans ce seuil, le planner ajouterait des
    operations entieres pour quelques dizaines de mm3 — un changement
    d'indexation coûte une reprise, une revalidation et du temps machine, et
    n'est jamais gratuit.
    """
    report = PlanReport(initial_removable_mm3=float(material.removable().sum())
                        * material.grid.voxel_volume)
    plan = ProcessPlan(plan_id=f"gamme-{setup.setup_id}", setup=setup)

    dirs = candidate_directions(shape, setup)
    report.candidates = evaluate_candidates(dirs, material, setup)
    # Vivier de travail, distinct de la liste rapportee : celle-ci doit rester
    # l'ensemble des candidates EVALUEES, faute de quoi le calcul final de la
    # matiere « vue par aucune direction » ne porterait plus que sur les
    # directions retenues, et surestimerait grossierement l'inaccessible.
    pool = [c.direction for c in report.candidates]

    for step in range(max_setups):
        ranked = evaluate_candidates(pool, material, setup)
        if not ranked or ranked[0].reachable_mm3 < min_gain_mm3:
            break

        best = ranked[0]
        sl: SliceResult = slice_for_direction(
            material, best.direction, tool,
            layer_thickness=layer_thickness, stepover_ratio=stepover_ratio,
            **({} if balayage is None else {"balayage": balayage}))
        if not sl.layers:
            # La direction voyait de la matiere mais l'outil n'a pas de position
            # valide : on la retire pour ne pas boucler dessus.
            pool = [d for d in pool if not np.allclose(d, best.direction)]
            continue

        stats = simulate_removal(material, sl, tool, point_spacing=point_spacing)
        report.gouged_voxels += stats.gouged_voxels

        if stats.removed_mm3 < min_gain_mm3:
            pool = [d for d in pool if not np.allclose(d, best.direction)]
            continue

        # Chemin CONTINU, et non les seuls points de coupe.
        #
        # Defaut trouve en comblant le trou de l'approche : l'operation portait
        # ``toolpath_points``, qui ecarte les liaisons parce qu'il sert a la
        # simulation d'enlevement de matiere — celle-ci ne doit compter que la
        # coupe. Mais une OPERATION doit porter tout le mouvement, liaisons
        # comprises : sans elles le post-processeur relie deux passes par une
        # avance travail en ligne droite, donc a travers la piece. Ce qui
        # aurait ete poste n'etait pas ce qui avait ete valide.
        # Le journal recueille les passes ou la rampe d'entree n'a pas pu
        # etre construite. Elles existent — segments trop courts — et sont
        # entrees en plongee ; le compte est ECRIT dans les notes, parce
        # qu'une exception a la regle qu'on ne compte pas cesse d'etre une
        # exception.
        journal_entrees: list = []
        P, rapid = continuous_path(sl, point_spacing, tool=tool,
                                   journal=journal_entrees)
        P, rapid = with_approach_retract(P, rapid, best.direction,
                                         sl.clearance_z, sl.frame,
                                         standoff_mm=max(sl.safety_clearance, 1.0))
        nrm = np.tile(np.asarray(best.direction, dtype=float), (len(P), 1))
        plan.operations.append(Operation(
            op_id=f"ebauche-{step + 1}-{best.label}",
            kinematic=Kinematic.MILLING_3PLUS2,
            tool=tool,
            toolpath=Toolpath(points=P, normals=nrm, is_rapid=rapid,
                              depth_of_cut=layer_thickness,
                              label=f"ebauche indexee {best.label}"),
            # Le SENS DE BALAYAGE est ecrit dans les notes, donc dans tout ce
            # qui relit la gamme. Signale par l'utilisateur : le zigzag
            # alterne l'avalant et l'opposition a chaque rangee, ce qui est un
            # choix defendable en ebauche — mais qui n'etait consigne nulle
            # part, donc que personne n'avait fait.
            notes=(f"A={best.a_deg:.2f} C={best.c_deg:.2f} ; "
                   f"{len(sl.layers)} couches de {layer_thickness} mm ; "
                   f"{stats.removed_mm3:.0f} mm3 ; balayage {sl.balayage}"
                   + (f" ; {len(journal_entrees)} entrees en plongee faute de "
                      f"segment ou ramper" if journal_entrees else "")),
        ))
        report.chosen.append(best)
        report.removed_per_step.append(stats.removed_mm3)
        pool = [d for d in pool if not np.allclose(d, best.direction)]

    left = material.removable()
    vv = material.grid.voxel_volume
    report.final_removable_mm3 = float(left.sum()) * vv

    # Matiere qu'AUCUNE direction candidate ne voit : ce n'est pas un echec du
    # planner mais une contrainte de montage, et l'utilisateur doit le savoir.
    seen = np.zeros_like(left)
    for c in report.candidates:
        seen |= material.reachable_from(c.direction)
    report.unreachable_mm3 = float((left & ~seen).sum()) * vv

    return plan, report


def indexed_orientation_plan(points: np.ndarray, direction: np.ndarray,
                             setup: Setup, *, margin: float = 0.0):
    """Construit un ``OrientationPlan`` a orientation CONSTANTE.

    Une operation indexee n'a pas besoin du solveur d'orientation : l'axe outil
    est fixe par definition, et lancer un Viterbi sur des milliers de points
    pour redecouvrir une constante serait absurde. Le plan est donc construit
    directement, puis soumis au MEME validateur que n'importe quelle
    trajectoire — c'est la validation qui doit etre uniforme, pas le chemin qui
    y mene.
    """
    from ..orientation_solver.solver import OrientationPlan, OrientationSegment

    d = normalize(direction)
    n = len(points)
    kin = KinematicsSolver(setup.machine)
    sol = kin.ik_best(d, allow_singular=True)
    if sol is None:
        raise ValueError(f"direction {d} hors des courses A/C de la machine")

    plan = OrientationPlan(
        directions=np.tile(d, (n, 1)),
        a_deg=np.full(n, sol.a_deg),
        c_deg=np.full(n, sol.c_deg),
        margin=np.full(n, margin),
        feasible=True,
    )
    plan.segments = [OrientationSegment(
        0, max(0, n - 1), "3+2", a_deg=sol.a_deg, c_deg=sol.c_deg,
        reason="operation indexee : orientation fixe par construction")]
    return plan


@dataclass
class FinishingOpReport:
    """Ce qu'une passe de finition a donne, et sous quel mode."""

    face_indices: list[int]
    n_points: int
    mode: str                      # "3+2" | "simultane" | "inaccessible"
    a_deg: float | None = None
    c_deg: float | None = None
    min_margin: float = 0.0
    indexed_fraction: float = 0.0
    rotary_travel_deg: float = 0.0
    #: Ouverture des normales sur le SEGMENT reellement evalue.
    normal_spread_deg: float = 0.0
    #: Ouverture sur la passe COMPLETE, et nombre de points qu'elle compte.
    #: Les deux sont distincts et il faut les lire ensemble : un mode « 3+2 »
    #: obtenu sur le pole d'une calotte ne dit rien du reste de la calotte.
    group_spread_deg: float = 0.0
    pass_total_points: int = 0
    n_inaccessible: int = 0
    detail: str = ""
    #: Verdict d'indexation VERIFIE sur la passe entiere (jalon M10). Present
    #: seulement quand ``plan_finishing`` a ete appele avec ``verify=True``.
    #: Quand il est la, ``coverage`` vaut 1.0 et le mode n'est plus celui d'un
    #: prefixe.
    verdict: object | None = None

    @property
    def coverage(self) -> float:
        """Part de la passe reelle sur laquelle le mode annonce porte."""
        if self.verdict is not None:
            return float(self.verdict.coverage)
        return self.n_points / max(self.pass_total_points, 1)

    def describe(self) -> str:
        head = (f"faces {self.face_indices} : {self.n_points} points, "
                f"mode {self.mode}")
        if self.mode == "3+2":
            head += f" (A={self.a_deg:.2f} C={self.c_deg:.2f})"
        head += f", ouverture du segment {self.normal_spread_deg:.0f} deg"
        if self.verdict is None:
            # La marge tous tronçons confondus est dominee par l'arete de
            # coupe, tangente par construction. Ne l'afficher que faute de
            # mieux, et jamais a cote du degagement hors coupe qui, lui, veut
            # dire quelque chose.
            head += f", marge min {self.min_margin:.3f} mm"
        if self.verdict is not None and self.verdict.min_clearance_mm is not None:
            head += (f", degagement hors coupe min "
                     f"{self.verdict.min_clearance_mm:.2f} mm")
        if self.verdict is not None:
            if self.verdict.basis == "verification":
                head += (f" | VERIFIE sur les {self.pass_total_points} points "
                         f"de la passe ({self.verdict.n_verified} orientations "
                         f"essayees)")
            elif self.verdict.conclusive:
                head += (f" | DEFINITIF sur la passe entiere, etabli sur "
                         f"{self.verdict.n_probe} points sondes "
                         f"({self.verdict.basis})")
        if self.verdict is None and self.coverage < 0.999:
            head += (f" | MAQUETTE : {self.coverage * 100:.1f} % de la passe "
                     f"({self.pass_total_points} points, ouverture totale "
                     f"{self.group_spread_deg:.0f} deg) — le mode annonce ne "
                     f"vaut que pour ce segment")
        if self.mode == "simultane":
            head += (f", 3+2 {self.indexed_fraction * 100:.0f} %"
                     f", course A+C {self.rotary_travel_deg:.0f} deg")
        if self.n_inaccessible:
            head += f", {self.n_inaccessible} points INACCESSIBLES"
        if self.detail:
            head += f" — {self.detail}"
        return head


def _spread(normals: np.ndarray) -> float:
    """Ouverture angulaire (cone complet) d'un ensemble de normales."""
    if len(normals) < 2:
        return 0.0
    mean = normals.mean(axis=0)
    nn = float(np.linalg.norm(mean))
    if nn < 1e-6:
        return 360.0
    cos = np.clip(normals @ (mean / nn), -1.0, 1.0)
    return float(np.degrees(np.arccos(cos.min())) * 2.0)


def plan_finishing(
    shape, setup: Setup, obstacles, tool: ToolAssembly,
    *,
    scallop_mm: float = 0.01,
    max_points_per_pass: int = 4000,
    group_tol_deg: float = 20.0,
    stride: int = 8,
    accessibility_config=None,
    verify: bool = True,
    n_probe: int = 24,
    max_candidates: int = 6,
):
    """Construit les operations de FINITION, face par face.

    La decision 3+2 / simultane n'est pas un reglage : elle sort de la meme
    regle que partout ailleurs — **l'intersection des ensembles admissibles**.
    Si une orientation degage en tous les points d'une passe, la passe est
    indexee ; sinon elle est simultanee. L'ouverture angulaire des normales
    donne une intuition, mais elle ne decide pas : seul l'accessibility solver
    connait le porte-outil, et c'est lui qui tranche.

    ``max_points_per_pass`` limite chaque passe a un SEGMENT CONTIGU de tete,
    et le rapport annonce la couverture obtenue.

    **Valeur revue au jalon M6, sans que la limite soit levee.** Elle valait 400
    quand un point coûtait ~380 ms en resolution complete. Apres
    reordonnancement des deux tests exacts (voir
    ``AccessibilityConfig.guard_first``), un point coûte 68 ms en complet et
    ~28 ms en adaptatif — donc **×5,5 de couverture a budget egal**, et le
    plafond passe a 4 000.

    Ce que cela ne suffit PAS a faire : la gamme de finition du dome C10 compte
    **159 899 points** repartis sur huit groupes de faces, soit environ 75 min
    en mono-thread. Mesure sur le dome C10 : couverture 2 % au plafond de 400,
    **18 % a 4 000** (28 831 points, 1 091 s). Le plan reste donc une MAQUETTE.

    **Et le MODE rapporte depend de la couverture**, ce qui interdit de lire une
    maquette comme un resultat approche. Le meme dome rapporte
    ``{3+2: 3, simultane: 2, inaccessible: 3}`` a 2 % et
    ``{3+2: 2, simultane: 4, inaccessible: 2}`` a 18 % : un groupe indexable sur
    ses 400 premiers points exige du simultane sur 4 000, un autre declare
    inaccessible devient accessible. C'est la consequence directe de la regle du
    moteur — l'intersection des ensembles admissibles ne peut que retrecir quand
    on ajoute des points. Le mode d'une maquette est donc le mode d'un PREFIXE,
    pas une estimation de celui de la passe.

    ``FinishingOpReport.coverage`` n'est pour cette raison pas une note de
    qualite a cote du resultat : c'est la PORTEE du resultat.
    """
    from ..accessibility_solver.solver import AccessibilityConfig, AccessibilitySolver
    from ..orientation_solver.solver import OrientationSolver
    from .indexed_pass import decide_indexed_pass
    from ..subtractive_slicer.finishing import (
        generate_finishing_passes,
        group_faces_by_normal,
    )

    cfg = accessibility_config or AccessibilityConfig(
        subdivisions=3, max_lead_deg=45.0, cutting_depth=0.0)
    solver = AccessibilitySolver(tool, setup.machine, obstacles, cfg,
                                 mount_offset_mm=setup.mount_offset)
    osolver = OrientationSolver(setup.machine, tool)

    plan = ProcessPlan(plan_id=f"finition-{setup.setup_id}", setup=setup)
    reports: list[FinishingOpReport] = []

    groups = group_faces_by_normal(shape, tol_deg=group_tol_deg)
    # Un seul echantillonnage de surface pour tous les groupes : le pas de
    # finition est fin, et le refaire par groupe coûte des centaines de milliers
    # de points a chaque fois pour n'en garder qu'une fraction.
    samp = max(min(scallop_mm * 20.0, 1.0), 0.15)
    shared = brep.sample_surface(shape, spacing=samp)

    for faces in groups:
        fp = generate_finishing_passes(shape, faces, tool, scallop_mm=scallop_mm,
                                       samples=shared)
        if fp is None or fp.n_points == 0:
            continue

        pts, nrm = fp.points, fp.normals
        total_points = len(pts)
        group_spread = fp.normal_spread_deg()

        if verify:
            # Voie du jalon M10 : le verdict 3+2 porte sur la passe ENTIERE.
            # On ne tronque rien, et le mode annonce n'est plus celui d'un
            # prefixe. Voir ``indexed_pass.decide_indexed_pass``.
            v = decide_indexed_pass(solver, pts, nrm, n_probe=n_probe,
                                    max_candidates=max_candidates)
            if v.indexable:
                reports.append(FinishingOpReport(
                    face_indices=faces, n_points=total_points, mode="3+2",
                    a_deg=v.a_deg, c_deg=v.c_deg, indexed_fraction=1.0,
                    normal_spread_deg=group_spread, group_spread_deg=group_spread,
                    pass_total_points=total_points, verdict=v))
                plan.operations.append(Operation(
                    op_id=f"finition-{'-'.join(str(f) for f in faces)}",
                    kinematic=Kinematic.MILLING_3PLUS2, tool=tool,
                    toolpath=Toolpath(points=pts, normals=nrm, depth_of_cut=0.0,
                                      label=f"finition faces {faces} (3+2)"),
                    notes=(f"pas {fp.stepover:.3f} mm, crete {scallop_mm:.3f} mm, "
                           f"{fp.n_stripes} passes ; A={v.a_deg:.2f} "
                           f"C={v.c_deg:.2f} verifie sur {total_points} points"),
                ))
                continue
            # Pas indexable : le verdict porte quand meme, et il nomme la
            # cause. Aucune operation n'est emise — une trajectoire simultanee
            # demande le champ admissible complet en chaque point, ce que ce
            # jalon ne rend PAS abordable. Emettre une operation ici
            # laisserait croire le contraire.
            reports.append(FinishingOpReport(
                face_indices=faces, n_points=total_points,
                mode=("inaccessible" if v.verdict == "inatteignable"
                      else "simultane"),
                normal_spread_deg=group_spread, group_spread_deg=group_spread,
                pass_total_points=total_points,
                n_inaccessible=v.n_probe_unreachable, verdict=v,
                detail=v.detail))
            continue

        if len(pts) > max_points_per_pass:
            # Segment CONTIGU, et non un echantillonnage reparti.
            #
            # Un ``linspace`` sur toute la passe semble plus representatif, et
            # c'est un piege : il detruit la continuite du chemin. Sur une
            # calotte de 245 917 points, 150 points repartis sont distants de
            # 1 640 rangs — donc tres eloignes dans l'espace. Le resultat n'est
            # plus une passe mais une suite de sauts, et l'orientation solver
            # paie 13 000 deg de course A+C pour un chemin qui n'existe pas.
            #
            # Un prefixe contigu est une VRAIE portion de la passe reelle, avec
            # sa continuite. C'est une maquette, pas un resume.
            pts, nrm = pts[:max_points_per_pass], nrm[:max_points_per_pass]

        amaps = solver.solve_points_adaptive(pts, nrm, stride=stride)
        n_bad = sum(1 for m in amaps if not m.accessible)
        if n_bad == len(amaps):
            reports.append(FinishingOpReport(
                face_indices=faces, n_points=len(pts), mode="inaccessible",
                normal_spread_deg=_spread(nrm), group_spread_deg=group_spread,
                pass_total_points=total_points, n_inaccessible=n_bad,
                detail="aucune orientation admissible : outil ou bridage a revoir"))
            continue

        oplan = osolver.solve(amaps, path_points=pts)
        mode = ("3+2" if oplan.feasible and oplan.indexed_fraction > 0.99
                else "simultane")
        seg = oplan.segments[0] if oplan.segments else None
        ta, tc = oplan.rotary_travel()
        finite = oplan.margin[np.isfinite(oplan.margin)]

        reports.append(FinishingOpReport(
            face_indices=faces, n_points=len(pts), mode=mode,
            a_deg=seg.a_deg if seg and seg.mode == "3+2" else None,
            c_deg=seg.c_deg if seg and seg.mode == "3+2" else None,
            min_margin=float(finite.min()) if finite.size else -np.inf,
            indexed_fraction=oplan.indexed_fraction,
            rotary_travel_deg=ta + tc,
            normal_spread_deg=_spread(nrm), group_spread_deg=group_spread,
            pass_total_points=total_points, n_inaccessible=n_bad,
            detail="" if oplan.feasible else "plan d'orientation incomplet",
        ))

        plan.operations.append(Operation(
            op_id=f"finition-{'-'.join(str(f) for f in faces)}",
            kinematic=(Kinematic.MILLING_3PLUS2 if mode == "3+2"
                       else Kinematic.MILLING_5AXIS),
            tool=tool,
            toolpath=Toolpath(points=pts, normals=nrm, depth_of_cut=0.0,
                              label=f"finition faces {faces} ({mode})"),
            notes=(f"pas {fp.stepover:.3f} mm, crete {scallop_mm:.3f} mm, "
                   f"{fp.n_stripes} passes"),
        ))

    return plan, reports
