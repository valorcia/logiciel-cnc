"""Accessibility Solver — quelles orientations d'axe outil sont admissibles ici ?

C'est le premier des deux modules qui portent le differenciateur produit. Il
repond, pour UN point de contact, a la question : quel est l'ensemble des
directions d'axe outil telles que l'outil COMPLET (bec, col, tige, porte-outil,
nez de broche) degage la piece, le brut et les bridages, tout en restant
realisable par la cinematique XYZAC ?

Le resultat n'est pas un booleen par direction mais un CHAMP :
  - admissible / rejete ;
  - **pourquoi** rejete (quel troncon, quelle contrainte) ;
  - **avec quelle marge** quand c'est admissible.

La marge est ce qui permet a l'orientation solver d'optimiser au lieu de
simplement choisir : une direction admissible a 0,05 mm pres et une direction
admissible a 8 mm pres ne se valent pas sur une machine en kit.

Pipeline en 6 etages, du moins cher au plus cher — chaque etage n'est execute
que sur ce que le precedent n'a pas tranche :

  E0  generation des candidats      (grille icospherique)
  E1  filtre geometrique local      (face arriere, angle de lead maximal)
  E2  filtre cinematique            (butees A/C, singularite)
  E3  encadrement a deux bornes     (cylindre enveloppe / troncon de coupe seul)
  E4  test exact outil complet      (par troncon, vectorise)
  E5  structuration                 (composantes connexes -> cones d'accessibilite)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

import numpy as np

from ..collision_engine.field import ObstacleClass, ObstacleField
from ..collision_engine.machine_guard import MachineGuard
from ..collision_engine.tool_collision import ToolCollisionChecker, signed_clearance_to_segment
from ..geometry_core.sphere import SphereGrid, icosphere, local_refine
from ..geometry_core.types import normalize
from ..kinematics_solver.solver import KinematicsSolver
from ..machine_model.machine import MachineKinematics
from ..tool_model.assembly import SegmentRole, ToolAssembly, tilt_axis_from_lead_tilt


class RejectReason(IntEnum):
    """Motif de rejet d'une direction candidate.

    Cette enumeration est l'ossature de la visualisation « candidates vs
    rejetees » : chaque motif a une couleur et une action corrective.
    """

    OK = 0
    BACK_FACING = 1        # d pointe dans la matiere : aucun sens
    LEAD_LIMIT = 2         # inclinaison excessive vs normale (etat de surface)
    AXIS_LIMITS = 3        # hors course A ou C
    SINGULARITY = 4        # trop proche de A = 0 : axe C mal conditionne
    COLLISION_CUTTING = 5  # l'arete de coupe gouge hors zone de prise
    COLLISION_NECK = 6     # le col touche -> allonger le col
    COLLISION_SHANK = 7    # la tige touche -> allonger la jauge
    COLLISION_HOLDER = 8   # le porte-outil touche -> jauge ou porte-outil plus fin
    COLLISION_SPINDLE = 9  # le nez de broche touche -> jauge nettement plus longue
    MACHINE_COLLISION = 10  # l'outil touche le berceau, le plateau ou un carter
    MACHINE_TRAVEL = 11     # la pose sort des courses lineaires X/Y/Z


_ROLE_TO_REASON = {
    SegmentRole.CUTTING: RejectReason.COLLISION_CUTTING,
    SegmentRole.FLUTE: RejectReason.COLLISION_CUTTING,
    SegmentRole.NECK: RejectReason.COLLISION_NECK,
    SegmentRole.SHANK: RejectReason.COLLISION_SHANK,
    SegmentRole.HOLDER: RejectReason.COLLISION_HOLDER,
    SegmentRole.SPINDLE_NOSE: RejectReason.COLLISION_SPINDLE,
}

#: Action corrective suggeree a l'UI pour chaque motif. Un rejet doit toujours
#: proposer une sortie, sinon l'utilisateur est bloque sans levier.
REMEDY = {
    RejectReason.LEAD_LIMIT: "augmenter l'angle de lead maximal, ou changer de strategie",
    RejectReason.AXIS_LIMITS: "rebrider la piece, ou la reorienter sur le plateau",
    RejectReason.SINGULARITY: "incliner la piece au montage pour eloigner A de 0",
    RejectReason.COLLISION_CUTTING: "reduire la profondeur de passe ou le diametre",
    RejectReason.COLLISION_NECK: "outil a col degage plus long",
    RejectReason.COLLISION_SHANK: "augmenter la longueur hors pince (jauge)",
    RejectReason.COLLISION_HOLDER: "porte-outil plus elance, ou jauge plus longue",
    RejectReason.COLLISION_SPINDLE: "jauge nettement plus longue, ou accessibilite impossible",
    RejectReason.MACHINE_COLLISION: "rapprocher la piece du centre du plateau, ou reduire "
                                    "l'inclinaison : l'outil touche un organe machine",
    RejectReason.MACHINE_TRAVEL: "repositionner la piece sur le plateau : la pose sort "
                                 "des courses lineaires",
}


@dataclass
class AccessibilityMap:
    """Champ d'accessibilite en un point de contact."""

    point: np.ndarray          # (3,) point de contact, repere piece
    normal: np.ndarray         # (3,) normale sortante
    grid: SphereGrid
    directions: np.ndarray     # (K,3) candidats evalues (sous-ensemble de la grille)
    grid_index: np.ndarray     # (K,) indice dans la grille complete
    feasible: np.ndarray       # (K,) bool
    margin: np.ndarray         # (K,) marge signee mm ; -inf si rejet non geometrique
    reason: np.ndarray         # (K,) RejectReason
    a_deg: np.ndarray          # (K,) branche A retenue
    c_deg: np.ndarray          # (K,) branche C retenue
    stage_counts: dict[str, int] = field(default_factory=dict)

    @property
    def n_feasible(self) -> int:
        return int(self.feasible.sum())

    @property
    def accessible(self) -> bool:
        return self.n_feasible > 0

    def best(self) -> int | None:
        """Indice de la direction admissible de meilleure marge."""
        if not self.accessible:
            return None
        m = np.where(self.feasible, self.margin, -np.inf)
        return int(np.argmax(m))

    def feasible_mask_full(self) -> np.ndarray:
        """Masque booleen sur la grille COMPLETE. Necessaire pour intersecter
        les ensembles admissibles de plusieurs points (detection du 3+2)."""
        m = np.zeros(len(self.grid), dtype=bool)
        m[self.grid_index[self.feasible]] = True
        return m

    def margin_full(self) -> np.ndarray:
        """Marges sur la grille complete ; -inf hors du domaine evalue."""
        m = np.full(len(self.grid), -np.inf)
        m[self.grid_index] = self.margin
        return m

    def cones(self) -> list[np.ndarray]:
        """Cones d'accessibilite (composantes connexes des directions admissibles)."""
        return self.grid.connected_components(self.feasible_mask_full())

    def dominant_reason(self) -> RejectReason | None:
        """Motif de rejet majoritaire. C'est ce qu'on affiche a l'utilisateur."""
        bad = self.reason[~self.feasible]
        if bad.size == 0:
            return None
        vals, counts = np.unique(bad, return_counts=True)
        return RejectReason(int(vals[int(np.argmax(counts))]))

    def summary(self) -> str:
        lines = [
            f"Accessibilite en {np.round(self.point, 2)} "
            f"(n={np.round(self.normal, 2)}) : "
            f"{self.n_feasible}/{len(self.directions)} directions admissibles"
        ]
        for r in RejectReason:
            n = int((self.reason == r).sum())
            if n:
                tag = "OK" if r is RejectReason.OK else r.name
                lines.append(f"    {tag:22s} {n:5d}"
                             + (f"   -> {REMEDY[r]}" if r in REMEDY else ""))
        b = self.best()
        if b is not None:
            lines.append(f"    meilleure : A={self.a_deg[b]:7.2f} C={self.c_deg[b]:8.2f} "
                         f"marge {self.margin[b]:.3f} mm")
        lines.append(f"    cones d'accessibilite : {len(self.cones())}")
        return "\n".join(lines)


def tcp_from_contact(
    contact: np.ndarray, normal: np.ndarray, axis: np.ndarray, tool: ToolAssembly
) -> np.ndarray:
    """Position du bec (TCP) pour un contact donne et un axe outil donne.

    Formule generale torique, valable pour les trois cas :
      - fraise a bout droit (cr = 0) ;
      - fraise a bout torique (0 < cr < R) ;
      - fraise hemispherique (cr = R).

    Le bec n'est PAS le point de contact des qu'il y a un rayon de bec ou que
    l'axe n'est pas normal a la surface. Confondre les deux decale la piece du
    rayon de l'outil — erreur silencieuse et systematique.
    """
    contact = np.asarray(contact, dtype=np.float64)
    n = normalize(normal)
    d = normalize(axis)
    R, cr = tool.radius, min(tool.corner_radius, tool.radius)

    q = contact + cr * n                      # centre du tore de bec
    perp = n - float(n @ d) * d               # composante radiale de la normale
    npn = float(np.linalg.norm(perp))
    e = perp / npn if npn > 1e-9 else np.zeros(3)
    return q - cr * d - (R - cr) * e


@dataclass
class AccessibilityConfig:
    """Reglages du solveur. Les valeurs par defaut sont volontairement prudentes."""

    subdivisions: int = 3            # 642 directions, ~8.6 deg
    max_lead_deg: float = 45.0       # inclinaison max vs normale
    min_normal_dot: float = 0.05     # rejette les directions rasantes/arriere
    safety_clearance: float = 0.5    # marge de securite ajoutee aux obstacles
    cutting_depth: float = 0.0       # hauteur de prise volontaire du troncon de coupe
    #: Encadrement a deux bornes (E3). MESURE sur la scene C06 : 2,83 s contre
    #: 1,83 s sans, pour un resultat identique (0 divergence sur 15 points). La
    #: borne superieure ne se declenche jamais des que le brut est intact,
    #: puisque le cylindre enveloppe traverse forcement le brut. Desactive par
    #: defaut : une optimisation qui ralentit est une dette, pas un acquis.
    #: Conserve parce qu'elle redevient utile en finition (brut deja enleve).
    use_two_sided_bounds: bool = False
    reject_singular: bool = True

    #: Ajout de directions « germes » motivees analytiquement, en plus de la
    #: grille uniforme.
    #:
    #: Mesure qui a impose ce mecanisme : sur une face plane usinee a la fraise
    #: a bout DROIT, l'ensemble admissible est une lamelle de quelques degres
    #: autour de la normale — incliner l'outil enfonce son talon dans le plan.
    #: Une grille icospherique de pas 8,6 deg passe donc a cote, non par manque
    #: de finesse mais par construction : aucun de ses sommets ne tombe dans la
    #: lamelle. Raffiner la grille entiere coûterait 4x par niveau pour resoudre
    #: un probleme purement local.
    #:
    #: On ajoute donc la normale exacte, la direction lead/tilt souhaitee, et un
    #: eventail fin autour d'elles.
    seed_directions: bool = True
    seed_half_angle_deg: float = 8.0
    seed_rings: int = 3
    seed_per_ring: int = 10
    seed_lead_deg: float = 0.0
    seed_tilt_deg: float = 0.0

    #: Verification des organes machine (berceau, plateau, carters) et des
    #: courses lineaires. Sans elle, une orientation degagee cote piece peut
    #: quand meme envoyer le nez de broche dans le berceau.
    check_machine: bool = True

    #: Tolerance de penetration de l'arete de coupe dans la piece (mm).
    #: ``None`` = deduite de l'inflation du champ d'obstacles, ce qui rend le
    #: fraisage de flanc possible sans faux positif. Voir ToolCollisionChecker
    #: pour la limite que cela implique sur la detection de gouge fine.
    cutting_allowance: float | None = None


class AccessibilitySolver:
    """Calcule le champ d'accessibilite d'un ou plusieurs points de contact."""

    def __init__(
        self,
        tool: ToolAssembly,
        machine: MachineKinematics,
        obstacles: ObstacleField,
        config: AccessibilityConfig | None = None,
        *,
        work_offset_mm: np.ndarray | None = None,
        mount_offset_mm: np.ndarray | None = None,
    ):
        self.tool = tool
        self.machine = machine
        self.obstacles = obstacles
        self.cfg = config or AccessibilityConfig()
        self.checker = ToolCollisionChecker(tool)
        self.work_offset = (np.zeros(3) if work_offset_mm is None
                            else np.asarray(work_offset_mm, dtype=np.float64))
        #: Position de l'origine piece sur le plateau. Sans elle, la piece est
        #: consideree encastree dans le plateau et le garde machine rejette tout.
        self.mount_offset = (np.zeros(3) if mount_offset_mm is None
                             else np.asarray(mount_offset_mm, dtype=np.float64))
        self.guard = (MachineGuard(machine, tool)
                      if (self.cfg.check_machine and machine.collision_volumes) else None)
        self.kin = KinematicsSolver(machine)
        self.grid = icosphere(self.cfg.subdivisions)

        if self.cfg.cutting_allowance is not None:
            self._cut_allow = float(self.cfg.cutting_allowance)
        else:
            part = obstacles.classes == int(ObstacleClass.PART)
            self._cut_allow = float(obstacles.inflation[part].max()) if part.any() else 0.0

    # -- E0..E2 : filtres bon marche -------------------------------------

    def _geometric_filter(self, normal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """E1 — face arriere et angle de lead. Retourne (garde, motif)."""
        cos_lead = float(np.cos(np.radians(self.cfg.max_lead_deg)))
        dots = self.grid.directions @ normalize(normal)
        reason = np.full(len(self.grid), RejectReason.OK, dtype=np.int8)
        reason[dots < self.cfg.min_normal_dot] = RejectReason.BACK_FACING
        reason[(dots >= self.cfg.min_normal_dot) & (dots < cos_lead)] = RejectReason.LEAD_LIMIT
        return reason == RejectReason.OK, reason

    def _kinematic_filter(
        self, dirs: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """E2 — butees A/C et singularite. Retourne (garde, motif, A, C).

        On garde la MEILLEURE branche realisable de chaque direction. Le choix
        definitif entre branches revient a l'orientation solver, qui seul voit
        la sequence ; ici on ne fait que constater la realisabilite.
        """
        n = len(dirs)
        keep = np.zeros(n, dtype=bool)
        reason = np.full(n, RejectReason.OK, dtype=np.int8)
        a_out = np.full(n, np.nan)
        c_out = np.full(n, np.nan)

        for i in range(n):
            branches = self.kin.ik_branches(dirs[i])
            ok = [b for b in branches if b.within_limits
                  and not (self.cfg.reject_singular and b.singular)]
            if ok:
                b = ok[0]
                keep[i] = True
                a_out[i], c_out[i] = b.a_deg, b.c_deg
            else:
                in_lim = [b for b in branches if b.within_limits]
                reason[i] = (RejectReason.SINGULARITY if in_lim else RejectReason.AXIS_LIMITS)
        return keep, reason, a_out, c_out

    # -- E3 : encadrement a deux bornes ----------------------------------

    def _two_sided_bounds(
        self, tcps: np.ndarray, dirs: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Encadre le resultat exact par deux tests a UN seul troncon.

        - **Borne superieure** : un cylindre unique de rayon ``max_radius`` et de
          longueur totale CONTIENT l'outil. S'il degage, l'outil degage. Certain.
        - **Borne inferieure** : le troncon de coupe seul est CONTENU dans
          l'outil. S'il touche un obstacle interdit, l'outil touche. Certain.

        Entre les deux, on ne sait pas et il faut le test complet. Le gain est
        reel parce que la majorite des directions tombe franchement d'un cote.

        Retourne ``(sur_decide_ok, sur_decide_collision)``.
        """
        M = len(dirs)
        sub = self.obstacles.subset_near(
            tcps.mean(axis=0), self.checker.reach + float(np.linalg.norm(tcps - tcps.mean(axis=0), axis=1).max(initial=0.0)) + 5.0
        )
        if len(sub) == 0:
            return np.ones(M, bool), np.zeros(M, bool)

        # Toutes les orientations partagent le meme point de contact en pratique,
        # mais le TCP varie legerement avec la direction : on traite le cas general.
        ok = np.zeros(M, bool)
        bad = np.zeros(M, bool)

        # La borne INFERIEURE n'est valide que sur les couples ou le test exact
        # n'accorde AUCUNE exemption. Le couple (coupe, piece) en accorde deux —
        # ``cutting_allowance`` et ``cutting_depth`` — donc l'inclure ici
        # produirait des rejets que le test exact ne confirmerait pas : ce ne
        # serait plus une borne, mais un second solveur, plus faux que le
        # premier. On la restreint aux bridages et aux organes machine, ou une
        # penetration de l'arete de coupe est toujours une collision franche.
        hard_for_cutting = ((sub.classes == int(ObstacleClass.FIXTURE))
                            | (sub.classes == int(ObstacleClass.MACHINE)))
        for i in range(M):
            v = sub.points - tcps[i]
            z = v @ dirs[i]
            r = np.sqrt(np.maximum(np.sum(v * v, axis=1) - z * z, 0.0))

            d_env = signed_clearance_to_segment(
                r, z, 0.0, self.tool.total_length, self.tool.max_radius, self.tool.max_radius
            ) - sub.inflation
            # Borne superieure : si meme le cylindre enveloppe degage TOUT
            # (brut compris), alors a fortiori l'outil reel degage.
            if float(d_env.min()) >= 0.0:
                ok[i] = True
                continue
            # Borne inferieure : le troncon de coupe seul, contre les classes
            # qu'il n'a jamais le droit de penetrer.
            seg = self.tool.segments[0]
            d_cut = signed_clearance_to_segment(
                r, z, seg.z_start, seg.z_end, seg.r_start, seg.r_end
            ) - sub.inflation
            if hard_for_cutting.any() and float(
                np.where(hard_for_cutting, d_cut, np.inf).min()
            ) < 0.0:
                bad[i] = True
        return ok, bad

    # -- pipeline complet -------------------------------------------------

    def _seed_directions(self, normal: np.ndarray) -> np.ndarray:
        """Directions germes autour de la normale et du lead/tilt souhaite."""
        cfg = self.cfg
        seeds = [normalize(normal)]
        if cfg.seed_lead_deg or cfg.seed_tilt_deg:
            # Direction d'avance inconnue a ce stade : on prend une tangente
            # arbitraire. Le germe sert a entrer dans la bonne region, pas a
            # fixer l'orientation finale — l'orientation solver, lui, connait
            # l'avance et raffinera.
            from ..geometry_core.types import orthonormal_basis
            u, _, _ = orthonormal_basis(normal)
            seeds.append(tilt_axis_from_lead_tilt(normal, u, cfg.seed_lead_deg,
                                                  cfg.seed_tilt_deg))
        fan = [local_refine(d, cfg.seed_half_angle_deg, cfg.seed_rings, cfg.seed_per_ring)
               for d in seeds]
        out = np.vstack(fan)
        # Deduplication angulaire grossiere : des germes trop proches ne font
        # que gonfler le test exact sans elargir l'exploration.
        key = np.round(out / 0.02).astype(np.int64)
        _, keep = np.unique(key, axis=0, return_index=True)
        return out[np.sort(keep)]

    def solve_point(self, contact: np.ndarray, normal: np.ndarray) -> AccessibilityMap:
        """Champ d'accessibilite complet en un point de contact."""
        contact = np.asarray(contact, dtype=np.float64)
        normal = normalize(normal)
        counts: dict[str, int] = {"E0_candidats": len(self.grid)}

        keep_geo, reason_geo = self._geometric_filter(normal)
        idx = np.flatnonzero(keep_geo)
        dirs = self.grid.directions[idx]

        if self.cfg.seed_directions:
            seeds = self._seed_directions(normal)
            cos_lead = float(np.cos(np.radians(self.cfg.max_lead_deg)))
            seeds = seeds[(seeds @ normal) >= min(cos_lead, 1.0 - 1e-12)]
            if len(seeds):
                # Chaque germe est rattache au sommet de grille le plus proche.
                # Cet indice ne sert QU'A la detection 3+2, qui cherche une
                # orientation commune a plusieurs points ; l'orientation
                # proposee y est de toute facon reverifiee exactement.
                nearest = np.argmax(seeds @ self.grid.directions.T, axis=1)
                dirs = np.vstack([dirs, seeds])
                idx = np.concatenate([idx, nearest])
                counts["E0_germes"] = int(len(seeds))

        counts["E1_apres_geometrie"] = len(idx)
        if len(idx) == 0:
            return self._empty_map(contact, normal, reason_geo, counts)
        keep_kin, reason_kin, a_deg, c_deg = self._kinematic_filter(dirs)
        counts["E2_apres_cinematique"] = int(keep_kin.sum())

        reason = np.full(len(idx), RejectReason.OK, dtype=np.int8)
        reason[~keep_kin] = reason_kin[~keep_kin]

        feasible = np.zeros(len(idx), dtype=bool)
        margin = np.full(len(idx), -np.inf)

        live = np.flatnonzero(keep_kin)
        if len(live):
            # Un TCP PAR orientation : des qu'il y a un rayon de bec ou un axe
            # non normal a la surface, le bec se deplace avec l'orientation.
            tcps = np.array([tcp_from_contact(contact, normal, dirs[i], self.tool) for i in live])

            if self.cfg.use_two_sided_bounds:
                b_ok, b_bad = self._two_sided_bounds(tcps, dirs[live])
                counts["E3_tranche_par_bornes"] = int((b_ok | b_bad).sum())
            else:
                counts["E3_tranche_par_bornes"] = 0

            # E4 : un seul appel vectorise pour TOUTES les orientations restantes.
            # Le voisinage d'obstacles est extrait une fois au lieu d'une fois
            # par direction : c'est la ou se joue le temps de calcul.
            counts["E4_tests_exacts"] = int(len(live))
            feas_v, marg_v, block_v = self.checker.check_many(
                tcps, dirs[live], self.obstacles,
                cutting_depth=self.cfg.cutting_depth,
                cutting_allowance=self._cut_allow,
            )
            feasible[live] = feas_v
            margin[live] = marg_v
            bad = np.flatnonzero(~feas_v)
            for k in bad:
                si = int(block_v[k])
                reason[live[k]] = (_ROLE_TO_REASON[self.tool.segments[si].role]
                                   if si >= 0 else RejectReason.COLLISION_CUTTING)

            # E4b — organes machine et courses lineaires.
            #
            # Teste dans le repere MACHINE, ou l'axe outil vaut toujours +Z. On
            # n'evalue que les orientations ayant survecu au test piece : une
            # orientation deja rejetee n'a pas besoin d'une seconde raison.
            if self.guard is not None:
                still = np.flatnonzero(feasible[live])
                if still.size:
                    tcps_m = np.array([
                        self.kin.part_to_machine_point(
                            tcps[k] + self.mount_offset, a_deg[live[k]], c_deg[live[k]])
                        + self.work_offset for k in still])
                    ac = np.stack([a_deg[live[still]], c_deg[live[still]]], axis=1)
                    ok_m = self.guard.check_many(tcps_m, ac)
                    counts["E4b_rejets_machine"] = int((~ok_m).sum())
                    for k, okk in zip(still, ok_m):
                        if okk:
                            continue
                        j = live[k]
                        feasible[j] = False
                        chk = self.guard.check_pose(tcps_m[list(still).index(k)],
                                                    float(a_deg[j]), float(c_deg[j]))
                        reason[j] = (RejectReason.MACHINE_TRAVEL
                                     if not chk.axis_limits_ok
                                     else RejectReason.MACHINE_COLLISION)

        reason[feasible] = RejectReason.OK
        counts["E5_admissibles"] = int(feasible.sum())

        return AccessibilityMap(
            point=contact, normal=normal, grid=self.grid,
            directions=dirs, grid_index=idx,
            feasible=feasible, margin=margin, reason=reason,
            a_deg=a_deg, c_deg=c_deg, stage_counts=counts,
        )

    def _empty_map(self, contact, normal, reason_geo, counts) -> AccessibilityMap:
        return AccessibilityMap(
            point=contact, normal=normal, grid=self.grid,
            directions=np.zeros((0, 3)), grid_index=np.zeros(0, dtype=np.int64),
            feasible=np.zeros(0, bool), margin=np.zeros(0), reason=np.zeros(0, np.int8),
            a_deg=np.zeros(0), c_deg=np.zeros(0), stage_counts=counts,
        )

    def solve_points(
        self, contacts: np.ndarray, normals: np.ndarray
    ) -> list[AccessibilityMap]:
        """Champ d'accessibilite pour une sequence de points (une trajectoire)."""
        return [self.solve_point(p, n) for p, n in zip(np.asarray(contacts), np.asarray(normals))]
