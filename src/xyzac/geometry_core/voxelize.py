"""Voxelisation d'un solide par lancer de rayons verticaux.

Necessaire au suivi de matiere enlevee : sans savoir ce qui reste du brut, le
solveur considere le brut INTACT et declare la tige en collision des qu'on
usine une face enterree sous quelques millimetres de matiere — c'est-a-dire
dans presque tous les cas reels.

**Pourquoi ne pas utiliser trimesh.contains** : il exige ``rtree`` (dependance
supplementaire) et surtout un maillage *combinatoirement* etanche. La
tessellation OCCT concatene les sommets face par face, donc duplique les
sommets sur les coutures : le maillage est geometriquement ferme mais pas
combinatoirement etanche, et les tests bases sur la topologie le rejettent.

Le lancer de rayons, lui, ne raisonne que sur la GEOMETRIE : on compte les
traversees le long d'une droite et on remplit par parite. Les sommets dupliques
n'y changent rien.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class VoxelGrid:
    """Grille reguliere. Les echantillons sont les CENTRES des voxels."""

    origin: np.ndarray   # coin bas de la grille
    pitch: float
    shape: tuple[int, int, int]

    @staticmethod
    def covering(lo: np.ndarray, hi: np.ndarray, pitch: float,
                 margin: float = 0.0) -> "VoxelGrid":
        lo = np.asarray(lo, float) - margin
        hi = np.asarray(hi, float) + margin
        n = np.maximum(1, np.ceil((hi - lo) / pitch).astype(int))
        return VoxelGrid(lo, float(pitch), (int(n[0]), int(n[1]), int(n[2])))

    @property
    def n_voxels(self) -> int:
        return int(np.prod(self.shape))

    @property
    def voxel_volume(self) -> float:
        return self.pitch ** 3

    def centers_xy(self) -> tuple[np.ndarray, np.ndarray]:
        x = self.origin[0] + (np.arange(self.shape[0]) + 0.5) * self.pitch
        y = self.origin[1] + (np.arange(self.shape[1]) + 0.5) * self.pitch
        return x, y

    def centers_z(self) -> np.ndarray:
        return self.origin[2] + (np.arange(self.shape[2]) + 0.5) * self.pitch

    def centers(self) -> np.ndarray:
        """(N,3) centres de tous les voxels, ordre C sur (i, j, k)."""
        x, y = self.centers_xy()
        z = self.centers_z()
        gx, gy, gz = np.meshgrid(x, y, z, indexing="ij")
        return np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1)

    def index_of(self, pts: np.ndarray) -> np.ndarray:
        """Indices (i, j, k) des voxels contenant les points. Non borne."""
        return np.floor((np.asarray(pts, float).reshape(-1, 3) - self.origin)
                        / self.pitch).astype(np.int64)


def solid_mask(verts: np.ndarray, tris: np.ndarray, grid: VoxelGrid,
               chunk: int = 512) -> np.ndarray:
    """Masque (nx, ny, nz) des voxels dont le centre est DANS le solide.

    Methode : pour chaque colonne verticale de la grille, on releve les cotes
    ``z`` des traversees du maillage, on les trie, et on remplit par parite.
    Exact pour un solide ferme, a la resolution de la grille pres.

    Les triangles quasi verticaux (projection XY d'aire nulle) sont ecartes :
    ils ne sont traverses par aucun rayon vertical et leur inclusion
    produirait des divisions par zero.
    """
    verts = np.asarray(verts, float)
    tris = np.asarray(tris, np.int64)
    p0, p1, p2 = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]

    # Aire signee de la projection XY : le denominateur barycentrique.
    d = ((p1[:, 0] - p0[:, 0]) * (p2[:, 1] - p0[:, 1])
         - (p2[:, 0] - p0[:, 0]) * (p1[:, 1] - p0[:, 1]))
    keep = np.abs(d) > 1e-12
    p0, p1, p2, d = p0[keep], p1[keep], p2[keep], d[keep]
    if len(d) == 0:
        return np.zeros(grid.shape, dtype=bool)

    x, y = grid.centers_xy()
    nx, ny, nz = grid.shape
    z_centers = grid.centers_z()
    mask = np.zeros((nx, ny, nz), dtype=bool)

    tri_xmin = np.minimum(np.minimum(p0[:, 0], p1[:, 0]), p2[:, 0])
    tri_xmax = np.maximum(np.maximum(p0[:, 0], p1[:, 0]), p2[:, 0])
    tri_ymin = np.minimum(np.minimum(p0[:, 1], p1[:, 1]), p2[:, 1])
    tri_ymax = np.maximum(np.maximum(p0[:, 1], p1[:, 1]), p2[:, 1])

    # Traitement par bandes de colonnes en X : borne la memoire a
    # O(chunk . ny . n_triangles_de_la_bande) au lieu du produit complet.
    for i0 in range(0, nx, chunk):
        i1 = min(i0 + chunk, nx)
        xs = x[i0:i1]
        band = (tri_xmax >= xs[0] - grid.pitch) & (tri_xmin <= xs[-1] + grid.pitch)
        if not np.any(band):
            continue
        b0, b1, b2, bd = p0[band], p1[band], p2[band], d[band]
        bymin, bymax = tri_ymin[band], tri_ymax[band]

        for ii, xv in enumerate(xs):
            sel = (tri_xmin[band] <= xv) & (tri_xmax[band] >= xv)
            if not np.any(sel):
                continue
            q0, q1, q2, qd = b0[sel], b1[sel], b2[sel], bd[sel]
            ymin_s, ymax_s = bymin[sel], bymax[sel]

            for jj, yv in enumerate(y):
                s2 = (ymin_s <= yv) & (ymax_s >= yv)
                if not np.any(s2):
                    continue
                r0, r1, r2, rd = q0[s2], q1[s2], q2[s2], qd[s2]
                # Coordonnees barycentriques 2D du point (xv, yv).
                w1 = ((xv - r0[:, 0]) * (r2[:, 1] - r0[:, 1])
                      - (r2[:, 0] - r0[:, 0]) * (yv - r0[:, 1])) / rd
                w2 = ((r1[:, 0] - r0[:, 0]) * (yv - r0[:, 1])
                      - (xv - r0[:, 0]) * (r1[:, 1] - r0[:, 1])) / rd
                w0 = 1.0 - w1 - w2
                hit = (w0 >= 0.0) & (w1 >= 0.0) & (w2 >= 0.0)
                if not np.any(hit):
                    continue
                zs = (w0[hit] * r0[hit, 2] + w1[hit] * r1[hit, 2] + w2[hit] * r2[hit, 2])
                zs.sort()
                # Parite : [z0, z1) dedans, [z1, z2) dehors, etc. Un nombre
                # impair de traversees signale un maillage ouvert sous ce rayon ;
                # on ignore alors la derniere, ce qui degrade proprement au lieu
                # de remplir toute la colonne.
                n_pairs = len(zs) // 2
                for k in range(n_pairs):
                    lo, hi = zs[2 * k], zs[2 * k + 1]
                    k0 = int(np.searchsorted(z_centers, lo))
                    k1 = int(np.searchsorted(z_centers, hi))
                    if k1 > k0:
                        mask[i0 + ii, jj, k0:k1] = True
    return mask
