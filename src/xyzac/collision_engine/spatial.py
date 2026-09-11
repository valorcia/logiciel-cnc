"""Index spatial pour l'extraction de voisinage d'obstacles.

Mesure du jalon M1 : le solveur passait 122 ms par point de contact, et le
goulot n'etait ni la boucle ni le nombre d'orientations mais le **nombre
d'obstacles N**. Chaque point de contact rebalayait les 13 000 points du nuage
pour n'en garder que quelques centaines.

Une grille de hachage uniforme repond a la vraie question : « quels obstacles
sont dans cette sphere ? » en ne visitant que les cellules qui l'intersectent.
Le cout passe de O(N) a O(cellules visitees + points retournes).

Pourquoi une grille et pas un KD-tree : les obstacles sont des points de surface
a densite quasi uniforme (c'est nous qui les echantillonnons a pas borne), ce
qui est exactement le cas ou la grille bat l'arbre — construction lineaire,
requete sans descente, et aucune dependance supplementaire.
"""

from __future__ import annotations

import numpy as np


class UniformGrid:
    """Grille de hachage uniforme sur un nuage de points.

    La taille de cellule est le seul reglage. Trop petite, on visite trop de
    cellules ; trop grande, on retourne trop de points. On la prend egale au
    rayon de requete typique, ce qui borne a 27 le nombre de cellules visitees
    pour une sphere de ce rayon.
    """

    __slots__ = ("points", "cell_size", "_origin", "_dims", "_starts", "_order")

    def __init__(self, points: np.ndarray, cell_size: float):
        pts = np.ascontiguousarray(points, dtype=np.float64).reshape(-1, 3)
        self.points = pts
        self.cell_size = float(max(cell_size, 1e-6))

        if len(pts) == 0:
            self._origin = np.zeros(3)
            self._dims = np.ones(3, dtype=np.int64)
            self._starts = np.zeros(2, dtype=np.int64)
            self._order = np.zeros(0, dtype=np.int64)
            return

        self._origin = pts.min(axis=0)
        span = pts.max(axis=0) - self._origin
        self._dims = np.maximum(1, np.ceil(span / self.cell_size).astype(np.int64) + 1)

        cell = self._cell_of(pts)
        flat = self._flatten(cell)

        # Tri par cellule + tableau d'offsets : structure « CSR » classique.
        # Aucune liste Python, aucun dict : tout reste en memoire contigue, ce
        # qui compte sur Pi 5 ou la bande passante memoire est la ressource rare.
        self._order = np.argsort(flat, kind="stable")
        sorted_flat = flat[self._order]
        n_cells = int(np.prod(self._dims))
        counts = np.bincount(sorted_flat, minlength=n_cells)
        self._starts = np.zeros(n_cells + 1, dtype=np.int64)
        np.cumsum(counts, out=self._starts[1:])

    def _cell_of(self, pts: np.ndarray) -> np.ndarray:
        c = np.floor((pts - self._origin) / self.cell_size).astype(np.int64)
        return np.clip(c, 0, self._dims - 1)

    def _flatten(self, cell: np.ndarray) -> np.ndarray:
        return (cell[..., 0] * self._dims[1] * self._dims[2]
                + cell[..., 1] * self._dims[2] + cell[..., 2])

    def query_ball(self, center: np.ndarray, radius: float) -> np.ndarray:
        """Indices des points a distance <= radius du centre.

        Le filtrage exact par distance est conserve : la grille ne sert qu'a
        reduire l'ensemble candidat. Une grille qui retournerait des points hors
        rayon casserait la garantie conservative en amont, qui suppose un
        voisinage exact.
        """
        if len(self.points) == 0:
            return np.zeros(0, dtype=np.int64)

        center = np.asarray(center, dtype=np.float64)
        lo = np.clip(np.floor((center - radius - self._origin) / self.cell_size),
                     0, self._dims - 1).astype(np.int64)
        hi = np.clip(np.floor((center + radius - self._origin) / self.cell_size),
                     0, self._dims - 1).astype(np.int64)

        gx, gy, gz = (np.arange(lo[i], hi[i] + 1) for i in range(3))
        cells = np.stack(np.meshgrid(gx, gy, gz, indexing="ij"), axis=-1).reshape(-1, 3)
        flat = self._flatten(cells)

        s, e = self._starts[flat], self._starts[flat + 1]
        n = e - s
        keep = n > 0
        if not np.any(keep):
            return np.zeros(0, dtype=np.int64)
        s, n = s[keep], n[keep]

        # Concatenation vectorisee des plages [s, s+n) sans boucle Python.
        total = int(n.sum())
        starts_rep = np.repeat(s, n)
        offsets = np.arange(total) - np.repeat(np.cumsum(n) - n, n)
        cand = self._order[starts_rep + offsets]

        d2 = np.sum((self.points[cand] - center) ** 2, axis=1)
        return cand[d2 <= radius * radius]

    def query_capsule(self, p0: np.ndarray, p1: np.ndarray, radius: float) -> np.ndarray:
        """Indices des points a distance <= radius du SEGMENT [p0, p1].

        Requete du test de balayage : l'outil se deplace d'une pose a l'autre et
        balaie un volume allonge. Une sphere englobante ce volume retournerait
        beaucoup trop de points des que le deplacement est long.
        """
        if len(self.points) == 0:
            return np.zeros(0, dtype=np.int64)

        p0 = np.asarray(p0, dtype=np.float64)
        p1 = np.asarray(p1, dtype=np.float64)
        mid = 0.5 * (p0 + p1)
        half = 0.5 * float(np.linalg.norm(p1 - p0))

        cand = self.query_ball(mid, half + radius)
        if len(cand) == 0:
            return cand

        v = p1 - p0
        L2 = float(v @ v)
        w = self.points[cand] - p0
        t = np.clip((w @ v) / L2, 0.0, 1.0) if L2 > 1e-18 else np.zeros(len(cand))
        closest = p0 + t[:, None] * v
        d2 = np.sum((self.points[cand] - closest) ** 2, axis=1)
        return cand[d2 <= radius * radius]
