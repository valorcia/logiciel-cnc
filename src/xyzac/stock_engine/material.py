"""Suivi de la matiere restante. Leve l'hypothese « brut intact » du jalon M1.

Le probleme que cela resout, mesure sur le corpus : avec un brut intact, usiner
une face enterree sous 2 mm de surepaisseur fait declarer la TIGE en collision,
puisqu'elle occupe l'espace que les passes precedentes ont deja vide. Le
solveur rejetait donc des orientations parfaitement saines — 5 points
accessibles sur 20 sur le cas C08.

Representation retenue : grille voxel booleenne de la matiere restante.

Pourquoi le voxel plutot que le dexel : un champ de dexels est indexe par une
direction, et notre outil change d'orientation en permanence. Un dexel Z serait
faux des qu'on bascule le berceau. Le voxel est isotrope, donc indifferent a
l'orientation — c'est exactement la propriete qu'il nous faut en 5 axes.

Cout memoire : a 1 mm de pas, un brut de 100 x 100 x 80 mm tient dans 800 Ko.
A 0,5 mm, 6,4 Mo. Les deux passent sur Raspberry Pi 5.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..geometry_core.voxelize import VoxelGrid, solid_mask
from .stock import Stock


@dataclass
class MaterialState:
    """Etat de la matiere restante a un instant de la gamme."""

    grid: VoxelGrid
    remaining: np.ndarray       # (nx, ny, nz) bool — matiere encore presente
    protected: np.ndarray       # (nx, ny, nz) bool — piece finale + surepaisseur

    @property
    def remaining_volume_mm3(self) -> float:
        return float(self.remaining.sum()) * self.grid.voxel_volume

    @property
    def protected_volume_mm3(self) -> float:
        return float(self.protected.sum()) * self.grid.voxel_volume

    def describe(self) -> str:
        return (f"Matiere : {self.remaining_volume_mm3:.0f} mm3 restants "
                f"(dont {self.protected_volume_mm3:.0f} mm3 de piece protegee), "
                f"grille {self.grid.shape} a {self.grid.pitch} mm")

    # -- construction ------------------------------------------------------

    @staticmethod
    def from_setup(stock: Stock, part_verts: np.ndarray, part_tris: np.ndarray,
                   *, pitch: float = 1.0, finish_allowance: float | None = None
                   ) -> "MaterialState":
        """Brut INTACT, avec la piece finale marquee comme protegee."""
        bb = stock.bbox
        grid = VoxelGrid.covering(bb.lo, bb.hi, pitch, margin=pitch)
        centers = grid.centers()

        remaining = stock.contains(centers).reshape(grid.shape)
        part = solid_mask(part_verts, part_tris, grid)

        allow = stock.finish_allowance_mm if finish_allowance is None else finish_allowance
        if allow > 0.0:
            part = _dilate(part, int(np.ceil(allow / grid.pitch)))

        # La piece est aussi de la matiere : un brut qui ne contiendrait pas la
        # piece signalerait un montage incoherent, pas une piece a usiner.
        return MaterialState(grid=grid, remaining=remaining | part, protected=part)

    # -- enlevement --------------------------------------------------------

    def remove_tool_sweep(self, tcps: np.ndarray, axes: np.ndarray, tool,
                          *, only_cutting: bool = True) -> int:
        """Enleve la matiere balayee par l'outil. Retourne le nombre de voxels.

        La matiere PROTEGEE n'est jamais enlevee, meme si l'outil la traverse
        dans le modele : si c'etait le cas, ce serait une gouge, et le role de
        ce module est de suivre la matiere, pas de masquer un defaut. Le nombre
        de voxels proteges touches est donc une information utile, pas un
        detail — il est retourne par ``count_gouged_voxels``.
        """
        tcps = np.asarray(tcps, float).reshape(-1, 3)
        axes = np.asarray(axes, float).reshape(-1, 3)
        axes = axes / np.linalg.norm(axes, axis=1, keepdims=True)

        segs = [s for s in tool.segments
                if (not only_cutting) or s.role.value in ("cutting", "flute")]
        if not segs:
            return 0

        centers = self.grid.centers()
        live = np.flatnonzero(self.remaining.ravel())
        if live.size == 0:
            return 0
        pts = centers[live]

        # Rayon du voxel : on enleve un voxel des que son CENTRE entre dans
        # l'outil. Ne pas compenser sous-estimerait l'enlevement d'un demi-pas.
        vr = 0.5 * self.grid.pitch * np.sqrt(3.0)
        removed = np.zeros(len(pts), dtype=bool)

        for i in range(len(tcps)):
            v = pts - tcps[i]
            z = v @ axes[i]
            r = np.sqrt(np.maximum(np.sum(v * v, axis=1) - z * z, 0.0))
            for s in segs:
                if s.z_end < 0:
                    continue
                inside = (z >= s.z_start - vr) & (z <= s.z_end + vr)
                if not np.any(inside):
                    continue
                t = np.clip((z - s.z_start) / max(s.length, 1e-12), 0.0, 1.0)
                r_env = s.r_start + t * (s.r_end - s.r_start)
                removed |= inside & (r <= r_env + vr)

        flat = self.remaining.ravel()
        prot = self.protected.ravel()
        to_clear = live[removed & ~prot[live]]
        flat[to_clear] = False
        self.remaining = flat.reshape(self.grid.shape)
        return int(to_clear.size)

    def count_gouged_voxels(self, tcps: np.ndarray, axes: np.ndarray, tool) -> int:
        """Voxels PROTEGES qu'une passe traverserait. Non nul = gouge."""
        probe = MaterialState(self.grid, self.protected.copy(), np.zeros_like(self.protected))
        return probe.remove_tool_sweep(tcps, axes, tool, only_cutting=True)

    def carve_to_finished(self) -> int:
        """Enleve TOUT ce qui n'est pas la piece protegee.

        Modelise l'etat « ebauche terminee, il ne reste que la surepaisseur ».
        C'est l'hypothese realiste pour calculer l'accessibilite d'une passe de
        FINITION, et elle est explicitement optimiste : elle suppose qu'une
        ebauche a reellement degage la zone. Elle ne doit pas servir a valider
        une gamme complete, seulement a etudier une passe de finition.
        """
        before = int(self.remaining.sum())
        self.remaining = self.protected.copy()
        return before - int(self.remaining.sum())

    # -- lecture -----------------------------------------------------------

    def boundary_points(self) -> tuple[np.ndarray, float]:
        """Centres des voxels de PEAU + rayon d'inflation conservatif.

        Un voxel est en peau s'il contient de la matiere et touche un voxel
        vide. Le rayon retourne est le demi-diagonal du voxel : c'est ce qui
        garantit que la matiere reelle est entierement couverte par les boules
        centrees sur les centres, donc que le test reste un majorant.
        """
        m = self.remaining
        interior = np.ones_like(m)
        for ax in range(3):
            interior &= _shift(m, ax, 1) & _shift(m, ax, -1)
        skin = m & ~interior
        idx = np.argwhere(skin)
        pts = self.grid.origin + (idx + 0.5) * self.grid.pitch
        return pts, float(0.5 * self.grid.pitch * np.sqrt(3.0))


def _shift(a: np.ndarray, axis: int, k: int) -> np.ndarray:
    """Decalage avec bord considere VIDE : la peau inclut donc le bord de
    grille, ce qui est correct — au-dela, on ne sait pas, et l'ignorer
    creerait un trou dans l'enveloppe des obstacles."""
    out = np.zeros_like(a)
    sl_dst = [slice(None)] * 3
    sl_src = [slice(None)] * 3
    if k > 0:
        sl_dst[axis] = slice(k, None)
        sl_src[axis] = slice(None, -k)
    elif k < 0:
        sl_dst[axis] = slice(None, k)
        sl_src[axis] = slice(-k, None)
    else:
        return a.copy()
    out[tuple(sl_dst)] = a[tuple(sl_src)]
    return out


def _dilate(mask: np.ndarray, n: int) -> np.ndarray:
    """Dilatation par ``n`` voxels (voisinage 6-connexe repete).

    Sert a materialiser la surepaisseur de finition sans calculer d'offset
    B-Rep, operation lente et fragile sur une geometrie quelconque.
    """
    if n <= 0:
        return mask
    out = mask.copy()
    for _ in range(n):
        nxt = out.copy()
        for ax in range(3):
            nxt |= _shift(out, ax, 1) | _shift(out, ax, -1)
        out = nxt
    return out
