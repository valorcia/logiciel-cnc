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
#: Action corrective par motif, ACCENTUEE : ces phrases sont lues par
#: l'operateur telles quelles — dans le banc de debogage, et depuis
#: ``strategy_planner.creux``, au bout d'une phrase qui, elle, est accentuee.
#: Un texte a moitie accentue dans une meme phrase se lit comme un bout de
#: code qui aurait fui jusqu'a l'ecran.
REMEDY = {
    RejectReason.LEAD_LIMIT: "augmenter l'angle de lead maximal, ou changer de stratégie",
    RejectReason.AXIS_LIMITS: "rebrider la pièce, ou la réorienter sur le plateau",
    RejectReason.SINGULARITY: "incliner la pièce au montage pour éloigner A de 0",
    RejectReason.COLLISION_CUTTING: "réduire la profondeur de passe ou le diamètre",
    RejectReason.COLLISION_NECK: "outil à col dégagé plus long",
    RejectReason.COLLISION_SHANK: "augmenter la longueur hors pince (jauge)",
    RejectReason.COLLISION_HOLDER: "porte-outil plus élancé, ou jauge plus longue",
    RejectReason.COLLISION_SPINDLE: "jauge nettement plus longue, ou accessibilité impossible",
    # Ces deux-la portaient leur propre cause en fin de phrase (« : l'outil
    # touche un organe machine »). Partout ou ils sont lus, le motif est deja
    # nomme juste avant — la phrase se terminait donc en se repetant.
    RejectReason.MACHINE_COLLISION: "rapprocher la pièce du centre du plateau, "
                                    "ou réduire l'inclinaison",
    RejectReason.MACHINE_TRAVEL: "repositionner la pièce sur le plateau",
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
class DirectionVerdict:
    """Ce qu'une orientation donne sur une passe COMPLETE.

    A ne pas confondre avec ``AccessibilityMap``, qui decrit toutes les
    orientations en UN point. Ici c'est l'inverse : une orientation, tous les
    points. Les deux sont necessaires — l'un pour decouvrir, l'autre pour
    conclure.
    """

    direction: np.ndarray
    a_deg: float | None
    c_deg: float | None
    ok: np.ndarray                 # (N,) bool
    margin: np.ndarray             # (N,) mm, -inf si non teste
    reason: np.ndarray             # (N,) RejectReason
    block: int
    #: Marge des tronçons NON COUPANTS (col, tige, porte-outil, nez de broche),
    #: calculee seulement sur demande. C'est la seule marge qui veuille dire
    #: quelque chose : voir ``min_margin`` ci-dessous.
    clearance: np.ndarray | None = None

    @property
    def n_points(self) -> int:
        return int(len(self.ok))

    @property
    def clears_all(self) -> bool:
        """Vrai seulement si l'orientation degage en CHAQUE point."""
        return bool(self.ok.all()) and self.n_points > 0

    @property
    def clear_fraction(self) -> float:
        return float(self.ok.mean()) if self.n_points else 0.0

    def min_margin(self) -> float:
        """Marge minimale TOUS TRONÇONS CONFONDUS. A lire avec prudence.

        Elle vaut presque toujours ~0, et ce n'est pas un resultat serre : le
        tronçon COUPANT est tangent a la surface **par construction**, puisque
        c'est lui qui coupe. Le minimum sur tous les tronçons est donc domine
        par une distance nulle voulue.

        C'est exactement le defaut qui rendait le certificat de gouge du jalon
        M6 vide de contenu, et il se reproduit ici : une grandeur plausible,
        stable, et qui ne mesure pas ce qu'on croit. ``min_clearance`` est la
        marge qui repond a la question « le porte-outil est-il passe loin ? ».
        """
        m = self.margin[self.ok]
        m = m[np.isfinite(m)]
        return float(m.min()) if m.size else float("inf")

    def min_clearance(self) -> float | None:
        """Marge minimale des tronçons NON COUPANTS, sur les points degages.

        ``None`` si elle n'a pas ete demandee (``with_clearance=False``).
        """
        if self.clearance is None:
            return None
        m = self.clearance[self.ok]
        m = m[np.isfinite(m)]
        return float(m.min()) if m.size else float("inf")

    def first_failure(self) -> int | None:
        bad = np.flatnonzero(~self.ok)
        return int(bad[0]) if bad.size else None

    def reason_counts(self) -> dict[str, int]:
        """Motifs de blocage, pour nommer ce qui s'oppose a l'indexation."""
        out: dict[str, int] = {}
        for r in np.unique(self.reason[~self.ok]):
            out[RejectReason(int(r)).name] = int((self.reason[~self.ok] == r).sum())
        return out

    def describe(self) -> str:
        if self.a_deg is None:
            return (f"orientation hors courses : aucun couple (A, C) ne la "
                    f"realise ({self.n_points} points non testes)")
        head = (f"A={self.a_deg:.2f} C={self.c_deg:.2f} : degage en "
                f"{int(self.ok.sum())}/{self.n_points} points "
                f"({self.clear_fraction * 100:.1f} %)")
        if self.clears_all:
            deg = self.min_clearance()
            m = (f"degagement hors coupe min {deg:.3f} mm" if deg is not None
                 else "degagement hors coupe NON CALCULE")
            return head + f", {m} — PASSE ENTIERE"
        return (head + f", premier echec au point {self.first_failure()}, "
                f"motifs {self.reason_counts()}")


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

    #: Ordre des deux tests exacts : garde machine AVANT test piece.
    #:
    #: La faisabilite est le ET de deux masques independants, donc elle ne
    #: depend pas de l'ordre — un test le verifie. Ce qui depend de l'ordre,
    #: c'est la completude du DIAGNOSTIC : le test place en second n'est evalue
    #: que sur les candidats ayant survecu au premier, donc les autres n'ont pas
    #: de marge geometrique a afficher.
    #:
    #: Mesure qui impose ce defaut : sur une calotte, le test piece coûte 58 %
    #: du temps et ne rejette que 2 candidats sur 114, tandis que la garde
    #: machine en rejette 105. L'ordre inverse fait donc porter le test cher sur
    #: 7 candidats au lieu de 114.
    #:
    #: Effet sur la CAUSE rapportee, pour un candidat bloque par les deux : la
    #: machine gagne. C'est deliberement le bon sens de la priorite — allonger
    #: la jauge ne rend pas atteignable une orientation hors du volume machine,
    #: alors que la contrainte machine, elle, ne se contourne que par une
    #: reindexation ou un repositionnement de la piece sur le plateau.
    #:
    #: Mettre a ``False`` pour obtenir le champ de marges complet, ce dont la
    #: visualisation des orientations rejetees a besoin.
    guard_first: bool = True

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

            # E4 / E4b : les DEUX tests exacts, chacun vectorise sur tous les
            # candidats qu'on lui soumet.
            #
            # E4  : outil complet contre piece, brut, bridages.
            # E4b : outil complet contre les organes machine, plus les courses
            #       lineaires. Teste dans le repere MACHINE, ou l'axe outil vaut
            #       invariablement +Z.
            #
            # La faisabilite est le ET des deux masques, donc l'ordre ne la
            # change pas. L'ordre change le COÛT, et beaucoup : voir
            # ``AccessibilityConfig.guard_first``.
            counts["E4_tests_exacts"] = 0
            counts["E4b_rejets_machine"] = 0

            def _part_stage(sel: np.ndarray) -> np.ndarray:
                """Test piece sur les positions ``sel`` de ``live``. Rend le masque."""
                counts["E4_tests_exacts"] += int(len(sel))
                feas_v, marg_v, block_v = self.checker.check_many(
                    tcps[sel], dirs[live[sel]], self.obstacles,
                    cutting_depth=self.cfg.cutting_depth,
                    cutting_allowance=self._cut_allow,
                )
                margin[live[sel]] = marg_v
                for k in np.flatnonzero(~feas_v):
                    si = int(block_v[k])
                    reason[live[sel[k]]] = (
                        _ROLE_TO_REASON[self.tool.segments[si].role]
                        if si >= 0 else RejectReason.COLLISION_CUTTING)
                return feas_v

            def _machine_stage(sel: np.ndarray) -> np.ndarray:
                """Garde machine sur les positions ``sel`` de ``live``."""
                if self.guard is None or sel.size == 0:
                    return np.ones(len(sel), dtype=bool)
                tcps_m = np.array([
                    self.kin.part_to_machine_point(
                        tcps[k] + self.mount_offset, a_deg[live[k]], c_deg[live[k]])
                    + self.work_offset for k in sel])
                ac = np.stack([a_deg[live[sel]], c_deg[live[sel]]], axis=1)
                ok_m, within_m = self.guard.check_many(tcps_m, ac, return_travel=True)
                counts["E4b_rejets_machine"] += int((~ok_m).sum())

                # La cause vient du masque de courses rendu par le garde, et non
                # d'un second test pose par pose. C'est la meme information,
                # calculee une seule fois : sur une calotte le garde rejette 105
                # orientations sur 112, et les re-tester une par une coûtait
                # 57 % du temps total du solveur.
                bad_m = np.flatnonzero(~ok_m)
                if bad_m.size:
                    reason[live[sel[bad_m]]] = np.where(
                        within_m[bad_m],
                        RejectReason.MACHINE_COLLISION,
                        RejectReason.MACHINE_TRAVEL)
                return ok_m

            stages = ([_machine_stage, _part_stage] if self.cfg.guard_first
                      else [_part_stage, _machine_stage])
            sel = np.arange(len(live))
            for stage in stages:
                if sel.size == 0:
                    break
                sel = sel[stage(sel)]
            feasible[live[sel]] = True

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


    # -- verification d'UNE orientation ------------------------------------

    #: Taille de bloc de la verification. Ce n'est pas un reglage de confort :
    #: le prefiltre d'obstacles de ``check_many`` se rabat sur une sphere de
    #: rayon ``portee + etendue du bloc``, donc un bloc large rend le prefiltre
    #: inoperant. Mesure sur la face plane du dome C10, meme verdict a toutes
    #: les tailles (2 630 points degages sur 3 000) mais :
    #:
    #:     bloc   8 : 1,92 ms/pt      bloc 128 : 11,79 ms/pt
    #:     bloc  16 : 1,60 ms/pt      bloc 256 : 25,93 ms/pt
    #:     bloc  32 : 1,84 ms/pt      bloc 512 : 29,65 ms/pt
    #:
    #: Un bloc de 256 annule tout le gain — c'est la valeur qu'avait le premier
    #: prototype, et elle le rendait aussi lent que le champ complet. La taille
    #: de bloc change le COÛT et jamais le verdict ; un test le verifie.
    VERIFY_BLOCK = 16

    def _non_cutting_checker(self):
        """Verificateur portant l'outil PRIVE de son tronçon coupant.

        Construit une fois et garde : c'est ce qui permet de mesurer le
        degagement du porte-outil sans le confondre avec la tangence voulue de
        l'arete de coupe.
        """
        if getattr(self, "_nc_checker", None) is None:
            from ..collision_engine.exact_gouge import NON_CUTTING_ROLES
            segs = [g for g in self.tool.segments if g.role in NON_CUTTING_ROLES]
            if not segs:
                self._nc_checker = False      # rien a mesurer
            else:
                nc = self.tool.model_copy(update={"segments": segs})
                self._nc_checker = ToolCollisionChecker(nc)
        return self._nc_checker or None

    def verify_direction(
        self, contacts: np.ndarray, normals: np.ndarray, direction: np.ndarray,
        *, block: int | None = None, allow_singular: bool = True,
        with_clearance: bool = False,
    ) -> "DirectionVerdict":
        """UNE orientation, TOUS les points. Verdict complet, pas un echantillon.

        Pourquoi cette fonction existe. ``solve_point`` explore l'ensemble
        admissible : 642 directions filtrees puis testees. C'est ce qu'il faut
        pour DECOUVRIR les orientations possibles, et cela coûte 65 ms par
        point — soit prés de trois heures pour les 159 899 points d'une gamme de
        finition du dome C10. Le plan restait donc une maquette : un prefixe
        contigu, dont le mode annonce n'etait que le mode de ce prefixe.

        Mais une fois un candidat connu, la question change : il ne s'agit plus
        d'explorer, il s'agit de VERIFIER. Une orientation en un point coûte un
        seul test exact au lieu de cent, et le test est vectorise sur les
        points. La verification d'une orientation sur la gamme complete coûte
        alors ~4 min au lieu de ~3 h.

        Ce que cela change dans le raisonnement du moteur : la decision
        3+2/simultane sort de l'INTERSECTION des ensembles admissibles, et une
        intersection ne peut que retrecir quand on ajoute des points. Un
        candidat trouve sur un sous-echantillon est donc une HYPOTHESE, jamais
        une conclusion — mais elle se verifie sur la passe entiere, et le
        verdict qui en sort porte sur la passe entiere.

        Ce que cela ne change pas : la trajectoire SIMULTANEE. Elle demande le
        champ admissible complet en chaque point, et reste hors de portee.
        Cette fonction rend donc decidable le 3+2 — positivement comme
        negativement — et rien de plus.

        ``allow_singular`` vaut True parce qu'en 3+2 le plateau C est bloque :
        A = 0 est alors une POSITION utilisable, et la singularite est un
        probleme de MOUVEMENT (ADR-001 / D6). Le refuser ici ecarterait
        l'orientation verticale, qui est la plus utile de toutes.
        """
        contacts = np.asarray(contacts, dtype=np.float64).reshape(-1, 3)
        normals = np.asarray(normals, dtype=np.float64).reshape(-1, 3)
        if len(contacts) != len(normals):
            raise ValueError(
                f"verify_direction : {len(contacts)} points pour "
                f"{len(normals)} normales")
        d = normalize(np.asarray(direction, dtype=np.float64))
        n = normals / np.linalg.norm(normals, axis=1, keepdims=True)
        blk = int(block or self.VERIFY_BLOCK)
        if blk < 1:
            raise ValueError("verify_direction : bloc >= 1")

        reason = np.full(len(contacts), RejectReason.OK, dtype=np.int8)
        margin = np.full(len(contacts), -np.inf)
        ok = np.zeros(len(contacts), dtype=bool)

        # E1 — filtre geometrique, par point : l'inclinaison admissible depend
        # de la normale locale, donc une meme direction est licite en un point
        # et illicite en un autre.
        cos_lead = float(np.cos(np.radians(self.cfg.max_lead_deg)))
        geo = (n @ d) >= min(cos_lead, 1.0)
        reason[~geo] = RejectReason.LEAD_LIMIT

        # E2 — cinematique, UNE FOIS : la direction est la meme partout, donc
        # le couple (A, C) l'est aussi.
        sols = self.kin.ik_branches(d)
        # ``AxisSolution.feasible`` vaut ``within_limits and not singular`` :
        # s'en servir ici rendrait ``allow_singular`` inoperant, et ecarterait
        # silencieusement l'orientation verticale. On teste donc les deux
        # conditions separement.
        usable = [t for t in sols
                  if t.within_limits and (allow_singular or not t.singular)]
        if not usable:
            reason[geo] = RejectReason.AXIS_LIMITS
            return DirectionVerdict(direction=d, a_deg=None, c_deg=None,
                                    ok=ok, margin=margin, reason=reason,
                                    block=blk)
        clearance = (np.full(len(contacts), -np.inf) if with_clearance else None)
        sol = max(usable, key=lambda t: abs(np.sin(np.radians(t.a_deg))))
        a_deg, c_deg = float(sol.a_deg), float(sol.c_deg)

        tcps = self._tcps_for_direction(contacts, n, d)
        idx = np.flatnonzero(geo)
        for s0 in range(0, len(idx), blk):
            sel = idx[s0:s0 + blk]
            axes = np.repeat(d[None, :], len(sel), axis=0)
            feas, marg, block_v = self.checker.check_many(
                tcps[sel], axes, self.obstacles,
                cutting_depth=self.cfg.cutting_depth,
                cutting_allowance=self._cut_allow)
            margin[sel] = marg
            if clearance is not None:
                nc = self._non_cutting_checker()
                if nc is not None:
                    _, cmarg, _ = nc.check_many(
                        tcps[sel], axes, self.obstacles,
                        cutting_depth=self.cfg.cutting_depth,
                        cutting_allowance=0.0)
                    clearance[sel] = cmarg
            for k in np.flatnonzero(~feas):
                si = int(block_v[k])
                reason[sel[k]] = (_ROLE_TO_REASON[self.tool.segments[si].role]
                                  if si >= 0 else RejectReason.COLLISION_CUTTING)
            keep = sel[feas]
            if keep.size and self.guard is not None:
                tm = np.array([
                    self.kin.part_to_machine_point(tcps[k] + self.mount_offset,
                                                   a_deg, c_deg) + self.work_offset
                    for k in keep])
                ac = np.tile([a_deg, c_deg], (len(keep), 1))
                gok, within = self.guard.check_many(tm, ac, return_travel=True)
                bad = np.flatnonzero(~gok)
                if bad.size:
                    reason[keep[bad]] = np.where(
                        within[bad], RejectReason.MACHINE_COLLISION,
                        RejectReason.MACHINE_TRAVEL)
                keep = keep[gok]
            ok[keep] = True
        return DirectionVerdict(direction=d, a_deg=a_deg, c_deg=c_deg,
                                ok=ok, margin=margin, reason=reason, block=blk,
                                clearance=clearance)

    def _tcps_for_direction(self, contacts: np.ndarray, normals: np.ndarray,
                            d: np.ndarray) -> np.ndarray:
        """``tcp_from_contact`` vectorise sur les points, a direction fixe.

        Meme formule torique, terme pour terme. Un test compare les deux sur
        des cas varies : une reecriture vectorisee est exactement le genre
        d'endroit ou un signe se perd sans que rien ne le signale.
        """
        R = self.tool.radius
        cr = min(self.tool.corner_radius, self.tool.radius)
        q = contacts + cr * normals
        perp = normals - (normals @ d)[:, None] * d[None, :]
        npn = np.linalg.norm(perp, axis=1, keepdims=True)
        e = np.where(npn > 1e-9, perp / np.maximum(npn, 1e-12), 0.0)
        return q - cr * d[None, :] - (R - cr) * e

    # -- resolution adaptative --------------------------------------------

    def solve_points_adaptive(
        self, contacts: np.ndarray, normals: np.ndarray, *,
        stride: int = 8, candidate_margin_deg: float = 20.0,
        max_candidates: int = 24,
    ) -> list[AccessibilityMap]:
        """Champ d'accessibilite sur une trajectoire, a coût reduit.

        Le coût d'un point vient de l'EXPLORATION : 642 directions filtrees puis
        testees une a une. Or le long d'une passe, deux points voisins ont des
        normales proches et des ensembles admissibles qui se recouvrent
        largement — reexplorer toute la sphere revient a redecouvrir la meme
        reponse.

        On resout donc completement un point sur ``stride``, et entre deux
        ancres on procede par **balayage avant** : les candidats d'un point sont
        ceux retenus au point PRECEDENT, plus les meilleurs de l'ancre suivante,
        plus un eventail local.

        **Pourquoi un balayage avant et non une interpolation entre ancres.**
        La premiere version prenait les meilleures directions des deux ancres
        encadrantes, chacune classee par marge. Elle produisait des plans
        INFAISABLES a stride 2 et 4, alors que chaque point avait des solutions
        et que le calcul complet trouvait une orientation constante.

        La raison : le classement par marge n'a aucune raison de retenir la
        meme direction en deux points voisins. Des que l'orientation commune
        disparait de l'un des ensembles, la contrainte de vitesse rotative — a
        peine 10 deg pour un pas de 0,7 mm — interdit d'en rejoindre une autre.
        Un elagage independant point par point casse donc la sequence.

        Inclure l'ensemble retenu au point precedent garantit que le choix fait
        en amont reste DISPONIBLE en aval s'il est toujours admissible. La
        continuite des ensembles candidats devient une propriete de
        construction, et non un heureux hasard de classement.

        Le test exact reste exact ; ce qui est perdu, c'est l'EXHAUSTIVITE. Le
        resultat est un SOUS-ENSEMBLE de l'ensemble admissible reel :
        conservatif, comme tout le reste du moteur. ``stride`` arbitre donc
        entre coût et richesse du choix offert a l'orientation solver, jamais
        entre coût et surete.
        """
        contacts = np.asarray(contacts, dtype=np.float64).reshape(-1, 3)
        normals = np.asarray(normals, dtype=np.float64).reshape(-1, 3)
        n = len(contacts)
        if n == 0:
            return []
        stride = max(1, int(stride))

        anchors = sorted(set(list(range(0, n, stride)) + [n - 1]))
        anchor_set = set(anchors)
        anchor_maps: dict[int, AccessibilityMap] = {
            i: self.solve_point(contacts[i], normals[i]) for i in anchors}

        # Directions admissibles en TOUTES les ancres : elles sont injectees dans
        # chaque ensemble candidat, et c'est ce qui rend la methode robuste.
        #
        # Diagnostic qui a impose ce mecanisme. Sur une face plane usinee a
        # l'hemispherique, l'orientation retenue est proche de la verticale,
        # donc A ~ 5 deg : tout pres de la singularite, ou le gain dC/d(axe)
        # vaut 10,8. Les directions voisines sur la grille correspondent alors a
        # des C repartis sur tout le cercle (-108, +108, +72, -180...), et la
        # contrainte de vitesse rotative — 10 deg pour un pas de 0,7 mm —
        # interdit de passer de l'une a l'autre.
        #
        # La passe n'est donc realisable QUE par une orientation commune a tous
        # ses points. Le calcul complet y parvenait en gardant 106 candidats ;
        # tout elagage qui la retire d'un seul point rend la sequence
        # infaisable, ce qui produisait des resultats erratiques selon le stride
        # (faisable a 8 et 32, infaisable a 2, 4 et 16).
        #
        # Garantir sa presence partout est donc la seule correction valable :
        # la faisabilite ne doit pas dependre de la chance du classement.
        common = np.ones(len(self.grid), dtype=bool)
        worst = np.full(len(self.grid), np.inf)
        for mp in anchor_maps.values():
            common &= mp.feasible_mask_full()
            worst = np.minimum(worst, mp.margin_full())

        # Plafonnee, et par le bon critere : la PIRE marge sur l'ensemble des
        # ancres. C'est exactement le critere qu'emploie la detection 3+2 pour
        # choisir l'orientation d'un segment indexe — une orientation commune
        # doit degager en TOUT point, pas en moyenne. Retenir les meilleures a
        # ce critere garde donc celle que le solveur choisira de toute façon.
        #
        # Sans plafond, l'intersection compte presque autant de directions que
        # l'exploration complete et le gain disparait (x1,1 mesure).
        idx_common = np.flatnonzero(common)
        if idx_common.size > max_candidates:
            idx_common = idx_common[np.argsort(-worst[idx_common])][:max_candidates]
        common_dirs = self.grid.directions[idx_common]

        cos_margin = float(np.cos(np.radians(candidate_margin_deg)))
        out: list[AccessibilityMap] = []
        prev: AccessibilityMap | None = None

        for i in range(n):
            if i in anchor_set:
                prev = anchor_maps[i]
                out.append(prev)
                continue

            pool: list[np.ndarray] = []
            if prev is not None and prev.n_feasible:
                idx = np.flatnonzero(prev.feasible)
                order = idx[np.argsort(-prev.margin[idx])]
                pool.append(prev.directions[order[:max_candidates]])

            nxt = min([a for a in anchors if a > i], default=None)
            if nxt is not None and anchor_maps[nxt].n_feasible:
                m2 = anchor_maps[nxt]
                idx = np.flatnonzero(m2.feasible)
                order = idx[np.argsort(-m2.margin[idx])]
                pool.append(m2.directions[order[: max(2, max_candidates // 3)]])

            if len(common_dirs):
                pool.append(common_dirs)

            if not pool:
                prev = self.solve_point(contacts[i], normals[i])
                out.append(prev)
                continue

            cand = np.vstack(pool)
            # Eventail local : sans lui la solution ne pourrait jamais deriver
            # le long de la passe et resterait collee a celle de l'ancre.
            close = np.flatnonzero(
                (self.grid.directions @ cand.T).max(axis=1) >= cos_margin)
            if close.size:
                step = max(1, close.size // max(1, max_candidates // 2))
                cand = np.vstack([cand, self.grid.directions[close[::step]]])

            prev = self._solve_point_on(contacts[i], normals[i], cand)
            out.append(prev)

        return out

    def _solve_point_on(self, contact: np.ndarray, normal: np.ndarray,
                        directions: np.ndarray) -> AccessibilityMap:
        """Evalue un ENSEMBLE DONNE de directions en un point de contact.

        Meme pipeline que ``solve_point`` a partir de l'etage E1, mais sans
        generation de candidats : c'est l'appelant qui fournit la liste.
        """
        contact = np.asarray(contact, dtype=np.float64)
        normal = normalize(normal)
        dirs = np.asarray(directions, dtype=np.float64).reshape(-1, 3)
        dirs = dirs / np.linalg.norm(dirs, axis=1, keepdims=True)

        key = np.round(dirs / 0.01).astype(np.int64)
        _, keep = np.unique(key, axis=0, return_index=True)
        dirs = dirs[np.sort(keep)]

        cos_lead = float(np.cos(np.radians(self.cfg.max_lead_deg)))
        dots = dirs @ normal
        ok_geo = dots >= min(cos_lead, 1.0)
        dirs = dirs[ok_geo]
        counts = {"E0_candidats": int(len(directions)), "E1_apres_geometrie": int(len(dirs))}

        if len(dirs) == 0:
            return self._empty_map(contact, normal, np.zeros(0, np.int8), counts)

        nearest = np.argmax(dirs @ self.grid.directions.T, axis=1)
        keep_kin, reason_kin, a_deg, c_deg = self._kinematic_filter(dirs)
        counts["E2_apres_cinematique"] = int(keep_kin.sum())

        reason = np.full(len(dirs), RejectReason.OK, dtype=np.int8)
        reason[~keep_kin] = reason_kin[~keep_kin]
        feasible = np.zeros(len(dirs), dtype=bool)
        margin = np.full(len(dirs), -np.inf)

        live = np.flatnonzero(keep_kin)
        if len(live):
            tcps = np.array([tcp_from_contact(contact, normal, dirs[i], self.tool)
                             for i in live])
            counts["E4_tests_exacts"] = int(len(live))
            feas_v, marg_v, block_v = self.checker.check_many(
                tcps, dirs[live], self.obstacles,
                cutting_depth=self.cfg.cutting_depth,
                cutting_allowance=self._cut_allow)
            feasible[live] = feas_v
            margin[live] = marg_v
            for k in np.flatnonzero(~feas_v):
                si = int(block_v[k])
                reason[live[k]] = (_ROLE_TO_REASON[self.tool.segments[si].role]
                                   if si >= 0 else RejectReason.COLLISION_CUTTING)

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
                        if not okk:
                            feasible[live[k]] = False
                            reason[live[k]] = RejectReason.MACHINE_COLLISION

        reason[feasible] = RejectReason.OK
        counts["E5_admissibles"] = int(feasible.sum())
        return AccessibilityMap(
            point=contact, normal=normal, grid=self.grid,
            directions=dirs, grid_index=nearest,
            feasible=feasible, margin=margin, reason=reason,
            a_deg=a_deg, c_deg=c_deg, stage_counts=counts,
        )
