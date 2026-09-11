"""Collision avec les organes de la MACHINE : berceau, plateau, carters.

Manque identifie au jalon M1 : le champ d'obstacles ne contenait que la piece,
le brut et les bridages. Or sur une cinematique table/table, une orientation
parfaitement degagee cote piece peut envoyer le nez de broche dans le berceau
ou l'outil sous le plateau. Ne pas le tester, c'est laisser passer precisement
les collisions les plus coûteuses.

**L'idee qui rend ce test bon marche** : dans le repere MACHINE, l'axe de
l'outil est invariablement ``+Z``. Il est donc inutile de transporter les
organes machine dans le repere piece pour chaque orientation candidate — il
suffit de transporter le TCP dans le repere machine, ou l'outil est toujours
droit et les organes presque toujours statiques.

Seuls les volumes portes par le berceau A et par le plateau C bougent, et ils
bougent d'une rotation connue.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from ..machine_model.machine import CollisionVolume, MachineKinematics
from ..tool_model.assembly import SegmentRole, ToolAssembly
from .field import ObstacleClass, ObstacleField
from .tool_collision import CollisionReport, ToolCollisionChecker


@dataclass
class MachineCheck:
    """Verdict machine d'une pose. Distingue les trois causes possibles."""

    ok: bool
    axis_limits_ok: bool
    collision: CollisionReport | None
    tcp_machine: np.ndarray
    detail: str = ""

    def reason(self) -> str:
        if self.ok:
            return "pose machine valide"
        if not self.axis_limits_ok:
            return f"hors course lineaire : {self.detail}"
        return f"collision organe machine : {self.collision.reason() if self.collision else '?'}"


def _sample_volume(cv: CollisionVolume, spacing: float) -> np.ndarray:
    """Echantillonne la peau d'un volume de collision machine."""
    if cv.kind == "box":
        from ..stock_engine.stock import _box_samples
        return _box_samples(np.array(cv.lo, float), np.array(cv.hi, float), spacing)[0]
    from ..stock_engine.stock import _cylinder_samples
    return _cylinder_samples(np.array(cv.base, float), np.array(cv.axis, float),
                             float(cv.radius), float(cv.height), spacing)[0]


@lru_cache(maxsize=16)
def _volume_cache(machine_id: str, spacing: float, payload: tuple) -> tuple:
    """Points de chaque volume, dans SON repere porteur. Calcule une fois."""
    out = []
    for frame, cv_json in payload:
        cv = CollisionVolume.model_validate_json(cv_json)
        out.append((frame, _sample_volume(cv, spacing)))
    return tuple(out)


class MachineGuard:
    """Teste une pose contre les courses lineaires et les organes machine."""

    def __init__(self, machine: MachineKinematics, tool: ToolAssembly,
                 *, spacing: float = 5.0, clearance: float = 2.0):
        self.m = machine
        self.tool = tool
        self.spacing = spacing
        self.clearance = clearance
        self.checker = ToolCollisionChecker(tool)
        payload = tuple((cv.frame, cv.model_dump_json()) for cv in machine.collision_volumes)
        self._vols = _volume_cache(machine.machine_id, spacing, payload)

    # -- transport des organes vers le repere machine ---------------------

    def _points_in_machine_frame(self, a_deg: float, c_deg: float) -> np.ndarray:
        """Organes machine exprimes dans le repere MACHINE pour un couple (A, C).

        - ``machine``  : statique, rien a faire ;
        - ``cradle_A`` : subit Rx(A) autour du pivot A ;
        - ``table_C``  : subit Rx(A)·Rz(C), il est porte par le berceau.
        """
        if not self._vols:
            return np.zeros((0, 3))

        a, c = np.radians(a_deg), np.radians(c_deg)
        ca, sa, cc, sc = np.cos(a), np.sin(a), np.cos(c), np.sin(c)
        rx = np.array([[1, 0, 0], [0, ca, -sa], [0, sa, ca]])
        rz = np.array([[cc, -sc, 0], [sc, cc, 0], [0, 0, 1]])
        pa = np.asarray(self.m.pivot_a, float)
        pc = np.asarray(self.m.pivot_c, float)

        chunks = []
        for frame, pts in self._vols:
            if frame == "machine":
                chunks.append(pts)
            elif frame == "cradle_A":
                chunks.append((pts - pa) @ rx.T + pa)
            elif frame == "table_C":
                q = (pts - pc) @ rz.T + pc
                chunks.append((q - pa) @ rx.T + pa)
            else:
                raise ValueError(f"repere de volume machine inconnu : {frame}")
        return np.vstack(chunks)

    # -- verification -----------------------------------------------------

    def check_pose(self, tcp_machine: np.ndarray, a_deg: float, c_deg: float) -> MachineCheck:
        """Verifie une pose dont le TCP est DEJA exprime en repere machine."""
        tcp_machine = np.asarray(tcp_machine, dtype=np.float64)

        within = (bool(self.m.x.contains(tcp_machine[0]))
                  and bool(self.m.y.contains(tcp_machine[1]))
                  and bool(self.m.z.contains(tcp_machine[2])))
        if not within:
            names = []
            for i, ax in enumerate((self.m.x, self.m.y, self.m.z)):
                if not ax.contains(tcp_machine[i]):
                    names.append(f"{ax.name}={tcp_machine[i]:.1f} hors [{ax.min_mm}, {ax.max_mm}]")
            return MachineCheck(False, False, None, tcp_machine, "; ".join(names))

        pts = self._points_in_machine_frame(a_deg, c_deg)
        if len(pts) == 0:
            return MachineCheck(True, True, None, tcp_machine)

        field_ = ObstacleField(
            pts, np.full(len(pts), ObstacleClass.MACHINE),
            np.full(len(pts), self.spacing + self.clearance))
        # Dans le repere machine l'axe outil vaut toujours +Z : c'est la
        # definition meme d'une broche a axe fixe.
        rep = self.checker.check(tcp_machine, np.array([0.0, 0.0, 1.0]), field_)
        return MachineCheck(not rep.collided, True, rep, tcp_machine)

    def check_many(self, tcps_machine: np.ndarray, ac: np.ndarray) -> np.ndarray:
        """Masque de validite pour M poses. ``ac`` est (M, 2) en degres.

        Les organes machine ne dependent que de (A, C) : on regroupe donc les
        poses partageant le meme couple, ce qui evite de retransporter le
        berceau pour chaque point d'une passe indexee — cas le plus frequent,
        puisqu'un segment 3+2 a par construction un (A, C) unique.
        """
        tcps_machine = np.asarray(tcps_machine, float).reshape(-1, 3)
        ac = np.asarray(ac, float).reshape(-1, 2)
        ok = np.zeros(len(tcps_machine), dtype=bool)

        key = np.round(ac, 6)
        uniq, inverse = np.unique(key, axis=0, return_inverse=True)
        for g, (a, c) in enumerate(uniq):
            rows = np.flatnonzero(inverse == g)
            pts = self._points_in_machine_frame(float(a), float(c))
            if len(pts) == 0:
                ok[rows] = True
                continue
            field_ = ObstacleField(pts, np.full(len(pts), ObstacleClass.MACHINE),
                                   np.full(len(pts), self.spacing + self.clearance))
            axes = np.tile([0.0, 0.0, 1.0], (len(rows), 1))
            feas, _, _ = self.checker.check_many(tcps_machine[rows], axes, field_)
            lin = (self.m.x.contains(tcps_machine[rows, 0])
                   & self.m.y.contains(tcps_machine[rows, 1])
                   & self.m.z.contains(tcps_machine[rows, 2]))
            ok[rows] = feas & lin
        return ok
