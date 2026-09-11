"""Orientation Solver — choisir la SEQUENCE A/C, pas une orientation isolee.

Second module du differenciateur. L'accessibility solver dit ce qui est
possible en chaque point ; celui-ci choisit ce qu'on fait, sur toute la
trajectoire, d'un seul tenant.

Pourquoi une sequence et pas un choix point par point (ADR-001 / D6) :

  - chaque direction admet DEUX couples (A, C) ; le bon depend du point d'avant ;
  - deux points voisins peuvent avoir des ensembles admissibles voisins mais des
    optima locaux opposes, ce qui produit un retournement de plateau de 180 deg
    en pleine matiere ;
  - la singularite A -> 0 rend le cout non local : l'eviter demande parfois de
    degrader plusieurs points en amont.

Methode :
  1. **Viterbi** sur les orientations discretisees : optimum GLOBAL sur
     l'ensemble discret, et surtout deterministe (deux executions sur le meme
     STEP donnent le meme G-code, propriete non negociable pour une machine).
  2. **Segmentation 3+2** par intersection des ensembles admissibles : le
     simultane n'apparait que la ou aucune orientation fixe n'existe.
  3. **Raffinement continu** local autour de la solution DP.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..accessibility_solver.solver import AccessibilityMap
from ..geometry_core.sphere import local_refine
from ..geometry_core.types import normalize, unwrap_towards
from ..kinematics_solver.solver import KinematicsSolver
from ..machine_model.machine import MachineKinematics
from ..tool_model.assembly import ToolAssembly


@dataclass
class OrientationWeights:
    """Ponderation des criteres. Chaque poids a une justification physique.

    Ce ne sont pas des reglages esthetiques : ils arbitrent entre etat de
    surface, temps de cycle, usure et risque. Ils sont exposes en mode expert
    uniquement, avec leur unite et leur effet.
    """

    clearance: float = 1.0     # preferer les orientations largement degagees
    singularity: float = 8.0   # fuir A -> 0 : cout eleve, c'est un risque dynamique
    lead_pref: float = 0.6     # rester proche du lead/tilt technologique souhaite
    smooth_a: float = 0.35     # continuite de l'axe A
    smooth_c: float = 0.35     # continuite de l'axe C
    accel: float = 0.8         # penaliser les changements de courbure (a-coups)
    rotary_travel: float = 0.05  # course rotative cumulee : temps et usure
    branch_switch: float = 6.0   # changer de branche IK en pleine passe : tres coûteux
    tilt_stability: float = 0.4  # preferer un axe outil eloigne du rasant

    #: Marge (mm) au-dela de laquelle une marge supplementaire n'apporte plus rien.
    clearance_saturation: float = 5.0


@dataclass
class OrientationSegment:
    """Segment homogene de la trajectoire : indexe (3+2) ou simultane."""

    start: int
    end: int                  # inclus
    mode: str                 # "3+2" | "simultane"
    a_deg: float | None = None  # defini seulement si mode == "3+2"
    c_deg: float | None = None
    reason: str = ""

    def __len__(self) -> int:
        return self.end - self.start + 1


@dataclass
class OrientationPlan:
    """Resultat complet : sequence A/C + diagnostic."""

    directions: np.ndarray       # (P,3) axe outil retenu par point
    a_deg: np.ndarray            # (P,)
    c_deg: np.ndarray            # (P,) deroule (continu)
    margin: np.ndarray           # (P,) marge de degagement retenue
    segments: list[OrientationSegment] = field(default_factory=list)
    total_cost: float = 0.0
    feasible: bool = True
    failures: list[int] = field(default_factory=list)  # indices sans solution

    @property
    def n_points(self) -> int:
        return int(self.a_deg.shape[0])

    @property
    def indexed_fraction(self) -> float:
        """Part des points couverts en 3+2. Indicateur produit majeur :
        plus il est haut, plus la gamme est rapide et rigide."""
        if not self.segments:
            return 0.0
        n = sum(len(s) for s in self.segments if s.mode == "3+2")
        return n / max(self.n_points, 1)

    def rotary_travel(self) -> tuple[float, float]:
        return (float(np.abs(np.diff(self.a_deg)).sum()),
                float(np.abs(np.diff(self.c_deg)).sum()))

    def summary(self) -> str:
        ta, tc = self.rotary_travel()
        lines = [
            f"Plan d'orientation : {self.n_points} points, "
            f"{'REALISABLE' if self.feasible else 'INCOMPLET'}",
            f"  segments      : {len(self.segments)} "
            f"({sum(1 for s in self.segments if s.mode == '3+2')} en 3+2, "
            f"{sum(1 for s in self.segments if s.mode == 'simultane')} en simultane)",
            f"  couverture 3+2: {self.indexed_fraction * 100:.1f} %",
            f"  course A      : {ta:.1f} deg     course C : {tc:.1f} deg",
            f"  A             : [{self.a_deg.min():.2f}, {self.a_deg.max():.2f}] deg",
            f"  C             : [{self.c_deg.min():.2f}, {self.c_deg.max():.2f}] deg",
            f"  marge min     : {self.margin.min():.3f} mm",
            f"  cout total    : {self.total_cost:.3f}",
        ]
        if self.failures:
            lines.append(f"  points SANS solution : {len(self.failures)} "
                         f"(premiers : {self.failures[:8]})")
        for s in self.segments[:12]:
            loc = f" A={s.a_deg:7.2f} C={s.c_deg:8.2f}" if s.mode == "3+2" else ""
            lines.append(f"    [{s.start:4d}..{s.end:4d}] {s.mode:10s}{loc}  {s.reason}")
        if len(self.segments) > 12:
            lines.append(f"    ... {len(self.segments) - 12} segments de plus")
        return "\n".join(lines)


class OrientationSolver:
    """Optimise la sequence A/C sur une trajectoire donnee."""

    def __init__(
        self,
        machine: MachineKinematics,
        tool: ToolAssembly,
        weights: OrientationWeights | None = None,
        *,
        candidates_per_point: int = 24,
        preferred_lead_deg: float = 10.0,
        preferred_tilt_deg: float = 0.0,
    ):
        self.m = machine
        self.tool = tool
        self.w = weights or OrientationWeights()
        self.kin = KinematicsSolver(machine)
        self.k = int(candidates_per_point)
        self.lead = preferred_lead_deg
        self.tilt = preferred_tilt_deg

    # -- couts ------------------------------------------------------------

    def node_cost(
        self, amap: AccessibilityMap, j: int, feed_dir: np.ndarray | None
    ) -> float:
        """Cout intrinseque d'une orientation en un point, hors continuite."""
        w = self.w
        d = amap.directions[j]
        margin = float(amap.margin[j])
        a = float(amap.a_deg[j])

        # Degagement : une marge saturee n'apporte plus rien, mais une marge
        # faible doit peser lourd. D'ou la saturation plutot qu'un terme lineaire.
        sat = w.clearance_saturation
        c_clear = w.clearance * (1.0 - min(max(margin, 0.0), sat) / sat)

        c_sing = w.singularity * self.kin.singularity_severity(a)

        # Preference technologique : lead/tilt souhaite par rapport a la normale.
        if feed_dir is not None:
            from ..tool_model.assembly import tilt_axis_from_lead_tilt

            try:
                d_pref = tilt_axis_from_lead_tilt(amap.normal, feed_dir, self.lead, self.tilt)
                dev = math.degrees(math.acos(float(np.clip(d @ d_pref, -1, 1))))
            except Exception:
                dev = math.degrees(math.acos(float(np.clip(d @ amap.normal, -1, 1))))
        else:
            dev = math.degrees(math.acos(float(np.clip(d @ amap.normal, -1, 1))))
        c_lead = w.lead_pref * (dev / 90.0)

        # Stabilite : un axe outil trop rasant charge l'outil en flexion.
        cos_n = float(np.clip(d @ amap.normal, -1, 1))
        c_tilt = w.tilt_stability * (1.0 - cos_n)

        return c_clear + c_sing + c_lead + c_tilt

    def transition_cost(
        self, a0: float, c0: float, b0: int, a1: float, c1: float, b1: int,
        step_mm: float,
    ) -> float:
        """Cout de passage d'une orientation a la suivante. ``inf`` si infaisable."""
        w = self.w
        c1u = math.degrees(unwrap_towards(math.radians(c1), math.radians(c0)))
        da, dc = a1 - a0, c1u - c0

        if self.kin.violates_rotary_rate(a0, c0, a1, c1u, step_mm):
            return math.inf  # contrainte dure : l'avance au point de contact exploserait

        cost = w.smooth_a * (da / 10.0) ** 2 + w.smooth_c * (dc / 10.0) ** 2
        cost += w.rotary_travel * (abs(da) + abs(dc)) / 10.0
        if b0 != b1:
            cost += w.branch_switch
        return cost

    # -- Viterbi ----------------------------------------------------------

    def _candidates(self, amap: AccessibilityMap, feed_dir) -> list[tuple]:
        """Les K meilleures orientations admissibles d'un point.

        On elague par cout intrinseque et non par marge seule : garder les 24
        directions de plus grande marge concentrerait tous les candidats dans un
        meme coin de la sphere, ce qui priverait la DP de toute latitude pour
        assurer la continuite.
        """
        idx = np.flatnonzero(amap.feasible)
        if idx.size == 0:
            return []
        costs = np.array([self.node_cost(amap, int(j), feed_dir) for j in idx])
        order = idx[np.argsort(costs)]
        keep = order[: self.k]

        out = []
        for j in keep:
            j = int(j)
            a, c = float(amap.a_deg[j]), float(amap.c_deg[j])
            branch = 0 if a >= 0 else 1
            out.append((j, a, c, branch, float(self.node_cost(amap, j, feed_dir)),
                        float(amap.margin[j]), amap.directions[j]))
        return out

    def solve(
        self,
        amaps: list[AccessibilityMap],
        path_points: np.ndarray | None = None,
        feed_dirs: np.ndarray | None = None,
    ) -> OrientationPlan:
        """Sequence A/C optimale sur l'ensemble discretise (Viterbi)."""
        P = len(amaps)
        if P == 0:
            raise ValueError("OrientationSolver.solve : trajectoire vide")

        steps = self._step_lengths(amaps, path_points)
        cand = [self._candidates(amaps[i], None if feed_dirs is None else feed_dirs[i])
                for i in range(P)]

        failures = [i for i, c in enumerate(cand) if not c]
        if failures:
            # Une trajectoire dont certains points sont inaccessibles n'est pas
            # "presque bonne" : on le dit, et on resout ce qui est resoluble
            # pour que l'UI puisse montrer OU ca bloque.
            return self._partial_plan(amaps, cand, failures, steps)

        # Aller : cout minimal cumule.
        n0 = len(cand[0])
        dp = np.array([c[4] for c in cand[0]], dtype=np.float64)
        back: list[np.ndarray] = [np.full(n0, -1, dtype=np.int64)]

        for i in range(1, P):
            ni, nprev = len(cand[i]), len(cand[i - 1])
            cur = np.full(ni, np.inf)
            bk = np.full(ni, -1, dtype=np.int64)
            for t in range(ni):
                _, a1, c1, b1, nc, _, _ = cand[i][t]
                best, best_s = np.inf, -1
                for s in range(nprev):
                    if not np.isfinite(dp[s]):
                        continue
                    _, a0, c0, b0, _, _, _ = cand[i - 1][s]
                    tc = self.transition_cost(a0, c0, b0, a1, c1, b1, steps[i])
                    if not np.isfinite(tc):
                        continue
                    v = dp[s] + tc
                    if v < best:
                        best, best_s = v, s
                if best_s >= 0:
                    cur[t], bk[t] = best + nc, best_s
            if not np.any(np.isfinite(cur)):
                # Aucune transition admissible : la contrainte de vitesse
                # rotative isole ce point. C'est un vrai blocage, pas un detail.
                return self._partial_plan(amaps, cand, [i], steps,
                                          note="transition rotative impossible")
            dp, _ = cur, back.append(bk)

        # Retour : reconstruction du chemin optimal.
        t = int(np.argmin(dp))
        total = float(dp[t])
        path = [t]
        for i in range(P - 1, 0, -1):
            t = int(back[i][t])
            path.append(t)
        path.reverse()

        dirs = np.array([cand[i][path[i]][6] for i in range(P)])
        a = np.array([cand[i][path[i]][1] for i in range(P)])
        c = np.array([cand[i][path[i]][2] for i in range(P)])
        mg = np.array([cand[i][path[i]][5] for i in range(P)])
        a, c = self.kin.unwrap_sequence(a, c)

        plan = OrientationPlan(directions=dirs, a_deg=a, c_deg=c, margin=mg,
                               total_cost=total, feasible=True)
        plan.segments = self.segment_3plus2(amaps, plan)
        return plan

    def _step_lengths(self, amaps, path_points) -> np.ndarray:
        if path_points is not None:
            p = np.asarray(path_points).reshape(-1, 3)
        else:
            p = np.array([m.point for m in amaps])
        steps = np.ones(len(amaps))
        if len(p) > 1:
            steps[1:] = np.maximum(np.linalg.norm(np.diff(p, axis=0), axis=1), 1e-3)
        return steps

    def _partial_plan(self, amaps, cand, failures, steps, note="") -> OrientationPlan:
        P = len(amaps)
        dirs = np.tile(np.array([0.0, 0.0, 1.0]), (P, 1))
        a = np.zeros(P); c = np.zeros(P); mg = np.full(P, -np.inf)
        for i, cl in enumerate(cand):
            if cl:
                j, ai, ci, _, _, mi, di = cl[0]
                dirs[i], a[i], c[i], mg[i] = di, ai, ci, mi
        return OrientationPlan(directions=dirs, a_deg=a, c_deg=c, margin=mg,
                               feasible=False, failures=failures,
                               segments=[OrientationSegment(0, P - 1, "simultane",
                                                            reason=note or "points inaccessibles")])

    # -- segmentation 3+2 --------------------------------------------------

    def segment_3plus2(
        self, amaps: list[AccessibilityMap], plan: OrientationPlan,
        min_run: int = 3,
    ) -> list[OrientationSegment]:
        """Decoupe la trajectoire en segments indexes et simultanes.

        Regle (ADR-001 / D7) : on balaie en maintenant l'INTERSECTION des
        ensembles de directions admissibles. Tant qu'elle est non vide, une
        orientation unique couvre tous les points parcourus -> 3+2. Des qu'elle
        se vide, le segment se ferme.

        Le simultane n'est donc jamais un choix : c'est ce qui reste quand la
        geometrie interdit toute orientation commune. Et le point de bascule est
        affichable, donc explicable a l'utilisateur.
        """
        P = len(amaps)
        segments: list[OrientationSegment] = []
        i = 0
        while i < P:
            inter = amaps[i].feasible_mask_full()
            margin_acc = amaps[i].margin_full().copy()
            j = i
            while j + 1 < P:
                nxt = amaps[j + 1].feasible_mask_full()
                new_inter = inter & nxt
                if not new_inter.any():
                    break
                inter = new_inter
                # La marge d'un segment indexe est la PIRE marge sur le segment :
                # une orientation doit degager en tout point, pas en moyenne.
                margin_acc = np.minimum(margin_acc, amaps[j + 1].margin_full())
                j += 1

            run = j - i + 1
            if run >= min_run and inter.any():
                cand_idx = np.flatnonzero(inter)
                scores = margin_acc[cand_idx] - self.w.singularity * np.array([
                    self.kin.singularity_severity(
                        math.degrees(math.acos(np.clip(amaps[i].grid.directions[t][2], -1, 1)))
                    ) for t in cand_idx
                ])
                best = cand_idx[int(np.argmax(scores))]
                d = amaps[i].grid.directions[best]
                sol = self.kin.ik_best(d)
                if sol is not None:
                    segments.append(OrientationSegment(
                        i, j, "3+2", a_deg=sol.a_deg, c_deg=sol.c_deg,
                        reason=f"orientation commune a {run} points "
                               f"(marge min {margin_acc[best]:.2f} mm)"))
                    i = j + 1
                    continue

            # Pas d'orientation commune exploitable : simultane sur la longueur
            # ou l'intersection reste vide des le depart.
            k = i
            while k < P:
                if k + 1 < P and (amaps[k].feasible_mask_full()
                                  & amaps[k + 1].feasible_mask_full()).any():
                    if k > i:
                        break
                k += 1
            k = max(k, i + 1)
            segments.append(OrientationSegment(
                i, min(k, P) - 1, "simultane",
                reason="aucune orientation commune : intersection vide"))
            i = k
        return segments

    # -- raffinement continu ----------------------------------------------

    def refine(
        self, plan: OrientationPlan, amaps: list[AccessibilityMap],
        collision_check, half_angle_deg: float = 6.0, iterations: int = 2,
    ) -> OrientationPlan:
        """Lissage continu local autour de la solution DP.

        La DP donne l'optimum sur la grille ; la grille a un pas fini (~8.6 deg
        au niveau 3). Le raffinement va chercher ce qui se trouve entre les
        noeuds, sans jamais quitter la region admissible : chaque candidat
        raffine est REVERIFIE par ``collision_check``. Un raffinement qui ferait
        confiance a l'interpolation reintroduirait le risque que toute
        l'architecture cherche a eliminer.
        """
        P = plan.n_points
        dirs = plan.directions.copy()
        margins = plan.margin.copy()

        for _ in range(iterations):
            for i in range(P):
                prev_d = dirs[i - 1] if i > 0 else None
                next_d = dirs[i + 1] if i < P - 1 else None
                if prev_d is None and next_d is None:
                    continue
                target = normalize(
                    (prev_d if prev_d is not None else dirs[i])
                    + (next_d if next_d is not None else dirs[i])
                )
                cands = local_refine(dirs[i], half_angle_deg, n_rings=3, n_per_ring=8)
                best, best_score = dirs[i], -np.inf
                for d in cands:
                    ok, mg = collision_check(i, d)
                    if not ok:
                        continue
                    a_sol = self.kin.ik_best(d)
                    if a_sol is None:
                        continue
                    score = (min(mg, self.w.clearance_saturation)
                             - 40.0 * (1.0 - float(d @ target))
                             - self.w.singularity * self.kin.singularity_severity(a_sol.a_deg))
                    if score > best_score:
                        best, best_score, margins[i] = d, score, mg
                dirs[i] = best

        a = np.empty(P); c = np.empty(P)
        for i in range(P):
            sol = self.kin.ik_best(dirs[i])
            if sol is None:
                return plan  # raffinement abandonne : on garde la solution DP, valide
            a[i], c[i] = sol.a_deg, sol.c_deg
        a, c = self.kin.unwrap_sequence(a, c)

        out = OrientationPlan(directions=dirs, a_deg=a, c_deg=c, margin=margins,
                              total_cost=plan.total_cost, feasible=plan.feasible,
                              failures=plan.failures)
        out.segments = self.segment_3plus2(amaps, out)
        return out
