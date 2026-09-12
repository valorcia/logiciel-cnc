"""Collision sur le BALAYAGE entre deux poses.

Manque bloquant identifie au jalon M1 : on verifiait les positions, pas les
transitions. Or entre deux points de contact la machine interpole, et l'outil
traverse un volume que ni la pose de depart ni la pose d'arrivee ne decrit.
C'est exactement la ou se produisent les collisions les plus classiques :
deux poses saines, un chemin qui ne l'est pas.

**Le point delicat, et la raison pour laquelle un echantillonnage naif ne
suffit pas** : sur une machine table/table, interpoler lineairement en (X, Y, Z,
A, C) — ce que fait le controleur — ne produit PAS une interpolation lineaire du
point de contact dans le repere piece. Une rotation A de 30 deg deplace un point
situe a 80 mm du pivot de plus de 40 mm. Echantillonner « quelques points entre
les deux » laisserait passer des collisions franches.

On subdivise donc sur une BORNE PROUVEE du deplacement, et non sur un nombre
d'echantillons arbitraire.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..geometry_core.types import unwrap_towards
from ..kinematics_solver.solver import KinematicsSolver
from ..machine_model.machine import MachineKinematics
from ..tool_model.assembly import ToolAssembly
from .field import ObstacleField
from .tool_collision import CollisionReport, ToolCollisionChecker


@dataclass
class SweepReport:
    """Verdict sur un segment de trajectoire."""

    ok: bool
    n_samples: int
    worst_margin: float
    first_failure_t: float | None = None
    detail: CollisionReport | None = None

    def reason(self) -> str:
        if self.ok:
            return (f"balayage degage sur {self.n_samples} poses "
                    f"(marge min {self.worst_margin:.3f} mm)")
        return (f"collision de balayage a t={self.first_failure_t:.3f} : "
                f"{self.detail.reason() if self.detail else '?'}")


class SweepChecker:
    """Verifie le mouvement CONTINU entre deux poses par sous-division prouvee."""

    def __init__(self, machine: MachineKinematics, tool: ToolAssembly,
                 *, max_step_mm: float = 0.5, max_samples: int = 256):
        self.m = machine
        self.tool = tool
        self.kin = KinematicsSolver(machine)
        self.checker = ToolCollisionChecker(tool)
        #: Deplacement maximal tolere pour un point quelconque de l'outil entre
        #: deux poses echantillonnees. C'est le parametre de surete du test :
        #: toute collision d'une profondeur superieure a cette valeur est
        #: necessairement detectee.
        self.max_step_mm = float(max_step_mm)
        self.max_samples = int(max_samples)

    # -- borne de deplacement ---------------------------------------------

    def displacement_bound(self, tcp0, axis0, tcp1, axis1) -> float:
        """Majorant du deplacement d'un point QUELCONQUE de l'outil.

        Un point de l'outil se situe a au plus ``reach`` du TCP. Son deplacement
        entre deux poses est donc borne par la translation du TCP plus l'arc
        decrit par la rotation de l'axe :

            |Dp| <= |Dtcp| + reach . angle(axis0, axis1)

        Majorant strict : c'est ce qui rend la subdivision sure plutot que
        plausible.
        """
        dt = float(np.linalg.norm(np.asarray(tcp1) - np.asarray(tcp0)))
        a0 = np.asarray(axis0, float) / np.linalg.norm(axis0)
        a1 = np.asarray(axis1, float) / np.linalg.norm(axis1)
        ang = float(np.arctan2(float(np.linalg.norm(np.cross(a0, a1))), float(a0 @ a1)))
        return dt + self.checker.reach * ang

    def n_subdivisions(self, tcp0, axis0, tcp1, axis1) -> int:
        bound = self.displacement_bound(tcp0, axis0, tcp1, axis1)
        n = int(np.ceil(bound / self.max_step_mm))
        return int(np.clip(n, 1, self.max_samples))

    # -- interpolation ----------------------------------------------------

    def interpolate(self, tcp0, axis0, a0_deg, c0_deg, tcp1, axis1, a1_deg, c1_deg, n: int):
        """Poses intermediaires selon l'interpolation REELLE du controleur.

        LinuxCNC interpole lineairement en coordonnees d'AXES, pas en
        orientation d'outil. On reproduit donc une rampe lineaire sur (A, C)
        — apres deroulage de C — et on en deduit l'axe outil par cinematique
        directe, plutot que d'interpoler les directions sur la sphere. Les deux
        ne coincident pas, et c'est le mouvement de la machine qui fait foi.
        """
        t = np.linspace(0.0, 1.0, n + 1)
        c1u = np.degrees(unwrap_towards(np.radians(c1_deg), np.radians(c0_deg)))
        a_seq = a0_deg + t * (a1_deg - a0_deg)
        c_seq = c0_deg + t * (c1u - c0_deg)
        tcps = np.asarray(tcp0)[None, :] + t[:, None] * (np.asarray(tcp1) - np.asarray(tcp0))
        axes = np.array([self.m.tool_axis_in_part(a, c) for a, c in zip(a_seq, c_seq)])
        return tcps, axes, a_seq, c_seq

    # -- verification ------------------------------------------------------

    def check_segment(
        self,
        tcp0, axis0, a0_deg, c0_deg,
        tcp1, axis1, a1_deg, c1_deg,
        obstacles: ObstacleField,
        *,
        cutting_depth: float = 0.0,
        cutting_allowance: float = 0.0,
    ) -> SweepReport:
        """Verifie le mouvement continu entre deux poses."""
        n = self.n_subdivisions(tcp0, axis0, tcp1, axis1)
        tcps, axes, _, _ = self.interpolate(tcp0, axis0, a0_deg, c0_deg,
                                            tcp1, axis1, a1_deg, c1_deg, n)

        # Le volume balaye est allonge : on extrait le voisinage par CAPSULE et
        # non par sphere, sans quoi un long deplacement ramenerait tout le nuage.
        radius = self.checker.reach + float(obstacles.inflation.max(initial=0.0))
        sub = obstacles.subset_capsule(tcps[0], tcps[-1], radius)
        if len(sub) == 0:
            return SweepReport(True, len(tcps), np.inf)

        feas, margin, _ = self.checker.check_many(
            tcps, axes, sub, cutting_depth=cutting_depth,
            cutting_allowance=cutting_allowance)

        if bool(np.all(feas)):
            return SweepReport(True, len(tcps), float(np.min(margin)))

        k = int(np.argmax(~feas))
        rep = self.checker.check(tcps[k], axes[k], sub, cutting_depth=cutting_depth,
                                 cutting_allowance=cutting_allowance)
        return SweepReport(False, len(tcps), float(np.min(margin)),
                           first_failure_t=float(k) / max(n, 1), detail=rep)

    def check_path(
        self, tcps: np.ndarray, axes: np.ndarray, a_seq: np.ndarray, c_seq: np.ndarray,
        obstacles: ObstacleField, *, chunk: int = 96, **kw,
    ) -> list[SweepReport]:
        """Verifie tous les segments d'une trajectoire. Un rapport par segment.

        **Traitement par lots.** Une premiere version appelait ``check_segment``
        segment par segment. Chaque appel reextrait son voisinage d'obstacles,
        travail proportionnel a la taille du nuage et repete des centaines de
        fois pour une poignee de poses a chaque tour : la validation d'une
        ebauche ne se terminait pas en un temps utile.

        On interpole donc tous les segments d'abord, puis on teste les poses par
        paquets. L'extraction de voisinage est amortie sur ~400 poses au lieu de
        ~12, et la taille des paquets borne la memoire des tableaux (N x M).
        """
        n_seg = len(tcps) - 1
        if n_seg <= 0:
            return []

        all_tcps: list[np.ndarray] = []
        all_axes: list[np.ndarray] = []
        owner: list[np.ndarray] = []
        counts = np.zeros(n_seg, dtype=np.int64)

        for i in range(n_seg):
            n = self.n_subdivisions(tcps[i], axes[i], tcps[i + 1], axes[i + 1])
            t_i, a_i, _, _ = self.interpolate(
                tcps[i], axes[i], float(a_seq[i]), float(c_seq[i]),
                tcps[i + 1], axes[i + 1], float(a_seq[i + 1]), float(c_seq[i + 1]), n)
            all_tcps.append(t_i)
            all_axes.append(a_i)
            owner.append(np.full(len(t_i), i, dtype=np.int64))
            counts[i] = len(t_i)

        T = np.vstack(all_tcps)
        A = np.vstack(all_axes)
        own = np.concatenate(owner)

        feas = np.ones(len(T), dtype=bool)
        marg = np.full(len(T), np.inf)
        radius = self.checker.reach + float(obstacles.inflation.max(initial=0.0))

        # Blocs de poses CONSECUTIVES : elles sont spatialement compactes, ce
        # qui preserve l'effet des pre-filtres de ``check_many`` (voir
        # ``check_path_poses``).
        for s0 in range(0, len(T), chunk):
            s1 = min(s0 + chunk, len(T))
            sub = obstacles.subset_capsule(T[s0:s1].min(axis=0) - radius,
                                           T[s0:s1].max(axis=0) + radius, radius)
            if len(sub) == 0:
                continue
            f, m, _ = self.checker.check_many(T[s0:s1], A[s0:s1], sub, **kw)
            feas[s0:s1], marg[s0:s1] = f, m

        out: list[SweepReport] = []
        for i in range(n_seg):
            sel = own == i
            ok = bool(feas[sel].all())
            mm = marg[sel]
            worst = float(np.min(mm)) if np.isfinite(mm).any() else np.inf
            if ok:
                out.append(SweepReport(True, int(counts[i]), worst))
                continue
            k = int(np.argmax(~feas[sel]))
            idx = np.flatnonzero(sel)[k]
            rep = self.checker.check(T[idx], A[idx], obstacles, **kw)
            out.append(SweepReport(False, int(counts[i]), worst,
                                   first_failure_t=float(k) / max(counts[i] - 1, 1),
                                   detail=rep))
        return out
