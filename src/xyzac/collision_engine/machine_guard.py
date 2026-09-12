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
        #: Champ d'obstacles par organe, dans SON repere : statique, donc
        #: construit une fois et partage par toutes les orientations.
        self._field_cache: dict[str, ObstacleField] = {}

    # -- transport : on deplace le TCP, pas la machine --------------------

    def _rot(self, a_deg: float, c_deg: float):
        a, c = np.radians(a_deg), np.radians(c_deg)
        ca, sa, cc, sc = np.cos(a), np.sin(a), np.cos(c), np.sin(c)
        rx = np.array([[1, 0, 0], [0, ca, -sa], [0, sa, ca]])
        rz = np.array([[cc, -sc, 0], [sc, cc, 0], [0, 0, 1]])
        return rx, rz

    def _points_in_machine_frame(self, a_deg: float, c_deg: float) -> np.ndarray:
        """Organes machine exprimes dans le repere MACHINE pour un couple (A, C).

        Conserve pour le diagnostic d'une pose isolee et pour le rendu. Le
        chemin de calcul en volume passe par ``_pose_in_volume_frame``, qui
        deplace le TCP au lieu des organes.
        """
        if not self._vols:
            return np.zeros((0, 3))
        rx, rz = self._rot(a_deg, c_deg)
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

    def _pose_in_volume_frame(self, frame: str, tcp_machine: np.ndarray,
                              a_deg: float, c_deg: float):
        """Transporte une pose (TCP, axe) du repere MACHINE vers celui d'un organe.

        **Inversion du probleme, et c'est ce qui rend le garde utilisable.** La
        premiere version transportait les ORGANES vers le repere machine : une
        transformation de plusieurs milliers de points, refaite pour chaque
        couple (A, C) candidat. Sur un point de contact offrant 106 orientations,
        cela representait 150 ms sur 199 — les trois quarts du temps de calcul
        de l'accessibilite.

        Or le rapport est de un a plusieurs milliers : on transporte le TCP et
        l'axe, soit deux vecteurs, et les organes restent ou ils sont. Le nuage
        devient alors STATIQUE pour un organe donne, donc partageable entre
        toutes les orientations candidates — un seul appel vectorise au lieu de
        cent.

        Dans le repere machine l'axe outil vaut +Z ; dans le repere d'un organe
        mobile, il devient l'image de +Z par la rotation inverse.
        """
        rx, rz = self._rot(a_deg, c_deg)
        pa = np.asarray(self.m.pivot_a, float)
        pc = np.asarray(self.m.pivot_c, float)
        z = np.array([0.0, 0.0, 1.0])
        tcp = np.asarray(tcp_machine, float)

        if frame == "machine":
            return tcp, z
        if frame == "cradle_A":
            return rx.T @ (tcp - pa) + pa, rx.T @ z
        if frame == "table_C":
            q = rx.T @ (tcp - pa) + pa
            return rz.T @ (q - pc) + pc, rz.T @ (rx.T @ z)
        raise ValueError(f"repere de volume machine inconnu : {frame}")

    def _field_for(self, frame: str, pts: np.ndarray) -> ObstacleField:
        cache = self._field_cache.get(frame)
        if cache is None:
            cache = ObstacleField(pts, np.full(len(pts), ObstacleClass.MACHINE),
                                  np.full(len(pts), self.spacing + self.clearance))
            self._field_cache[frame] = cache
        return cache

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

    def check_many(self, tcps_machine: np.ndarray, ac: np.ndarray,
                   *, return_travel: bool = False):
        """Masque de validite pour M poses. ``ac`` est (M, 2) en degres.

        Un appel de collision par ORGANE, et non par couple (A, C) : le nuage
        d'un organe est statique dans son propre repere, donc partageable entre
        toutes les poses. Voir ``_pose_in_volume_frame``.

        ``return_travel=True`` rend en plus le masque des poses DANS les courses
        lineaires. C'est l'information qui distingue « hors course » de
        « collision organe », et elle est de toute facon calculee ici : la
        rendre evite a l'appelant de re-tester pose par pose pour retrouver une
        cause que cette fonction connaissait deja. Le solveur d'accessibilite le
        faisait, au prix de 105 appels scalaires par point de contact.
        """
        tcps_machine = np.asarray(tcps_machine, float).reshape(-1, 3)
        ac = np.asarray(ac, float).reshape(-1, 2)

        within = (self.m.x.contains(tcps_machine[:, 0])
                  & self.m.y.contains(tcps_machine[:, 1])
                  & self.m.z.contains(tcps_machine[:, 2]))
        ok = within.copy()
        if not self._vols or not ok.any():
            return (ok, within) if return_travel else ok

        live = np.flatnonzero(ok)
        for frame, pts in self._vols:
            if len(pts) == 0:
                continue
            field_ = self._field_for(frame, pts)
            tcps_v = np.empty((len(live), 3))
            axes_v = np.empty((len(live), 3))
            for k, i in enumerate(live):
                tcps_v[k], axes_v[k] = self._pose_in_volume_frame(
                    frame, tcps_machine[i], float(ac[i, 0]), float(ac[i, 1]))
            feas, _, _ = self.checker.check_many(tcps_v, axes_v, field_)
            ok[live] &= feas
            live = np.flatnonzero(ok)
            if live.size == 0:
                break
        return (ok, within) if return_travel else ok
