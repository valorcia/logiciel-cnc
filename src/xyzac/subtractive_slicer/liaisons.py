"""Abaisser les liaisons : le plus gros levier de temps du projet.

Le chiffre qui a motive ce module
----------------------------------
Sur une gamme complete, 24 a 29 % seulement du temps se passe a COUPER. Le
reste — 140 838 mm de rapides et 1 197 degagements — est du transport. Sur un
creux pris seul, la part coupante va de 27 % a 100 % selon la forme : bonne sur
une poche compacte, mauvaise des que le creux est plat et large.

D'ou vient ce transport
-----------------------
``continuous_path`` relie deux passes en montant jusqu'au PLAN DE DEGAGEMENT,
c'est-a-dire au-dessus de toute la matiere. C'est la strategie la plus sûre
qui soit, et elle a ete adoptee pour une bonne raison : la version d'avant
reliait les extremites en ligne droite, et cette droite traversait la matiere
entre deux rangees.

Mais elle est sûre PARTOUT, y compris la ou il n'y a plus rien. Mesure sur la
poche de C02 : 566 mm de rapides pour 1 338 mm de coupe, et ces 566 mm sont
essentiellement onze aller-retours au plan de degagement entre douze couches —
alors que l'outil reste dans la meme poche, deja videe au-dessus de lui.

Ce que ce module fait, et ce qu'il ne suppose pas
-------------------------------------------------
Il ne devine pas et il n'essaie pas non plus : il CALCULE la hauteur, en une
fois, pour l'outil COMPLET — bec, goujure, col, tige, porte-outil, nez de
broche.

Le raisonnement tient en une ligne par tronçon d'outil. Le tronçon ``i``
occupe, quand le bec est a la hauteur ``h``, la tranche ``[h + z0_i,
h + z1_i]`` a moins de ``r_i`` de l'axe. Si la matiere presente dans ce
couloir-la monte au plus jusqu'a ``M_i``, alors ``h > M_i - z0_i`` suffit a
l'en sortir. La hauteur cherchee est donc

    h = max_i (M_i - z0_i) + marge

et un seul balayage des voxels par liaison la donne, au lieu d'une dizaine
d'essais successifs. Mesure de ce que cela change : 9,1 s la premiere version,
par essais ; 0,2 s celle-ci.

Le plan de degagement reste le plafond : ce module ne peut pas rendre une
liaison pire que celle qu'il remplace.

Le test porte sur la matiere TELLE QU'ELLE EST A CET INSTANT du parcours : on
enleve au fur et a mesure ce que les passes precedentes ont pris. C'est ce qui
permet de descendre dans une poche qu'on vient de vider, et c'est aussi ce qui
interdit de descendre dans une poche qu'on n'a pas encore ouverte.

Ce qui est GARANTI, et ce qui ne l'est pas
-------------------------------------------
Une liaison est faite de trois morceaux, et un seul change ici :

  - la MONTEE, verticale, a l'aplomb du dernier point coupe. L'outil remonte
    dans le trou qu'il vient de faire ;
  - la TRAVERSEE, horizontale, a la hauteur calculee. **C'est elle que ce
    module prouve libre**, et c'est elle qui etait auparavant faite au plan de
    degagement ;
  - la PLONGEE, verticale, jusqu'au premier point de la passe suivante. Elle
    entre dans la matiere par definition — c'est une plongee — et elle est
    identique a celle d'avant, en plus courte.

Cette distinction n'est pas une commodite d'ecriture : la premiere
verification ecrite pour ce module testait la liaison ENTIERE et declarait
cinq liaisons sur onze « en faute » sur la poche de C02. Elles ne l'etaient
pas : elle reprochait a la plongee d'entrer dans la matiere qu'elle allait
couper. Un test qui interdit a une plongee de plonger ne verifie rien.

Le sens de l'erreur
-------------------
Trois reserves, toutes dans le sens prudent :

  - l'outil est teste ENTIER, et non sur son seul tronçon coupant. Une liaison
    est un deplacement rapide : c'est le porte-outil qui va toucher, pas
    l'arete de coupe ;
  - un voxel compte comme touche des que son CENTRE entre dans l'outil augmente
    d'une demi-diagonale de voxel — la meme convention que l'enlevement de
    matiere, pour que les deux ne divergent pas ;
  - la matiere qui surplombe la liaison la fait MONTER, meme si l'outil
    passerait dessous. ``M_i`` est le plus haut point de matiere du couloir,
    sans regarder si la tranche du tronçon l'evite par le dessous. Sur une
    contre-depouille, la liaison sera donc plus haute que necessaire.

Ce que ce module NE fait PAS : il ne change pas l'ORDRE des passes. Un ordre
mieux choisi raccourcirait encore le transport, et c'est un autre chantier.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np

#: Garde ajoutee a la hauteur calculee, en mm.
#:
#: S'ajoute a la demi-diagonale du voxel, qui est deja comptee : celle-ci dit
#: « ce voxel est touche des que son centre entre dans l'outil », et
#: celle-la est la marge de l'usineur par-dessus.
GARDE_MM = 0.5


@dataclass(frozen=True)
class GainLiaisons:
    """Ce que l'abaissement a change, en mm et en nombre."""

    n_liaisons: int
    n_abaissees: int
    avant_mm: float
    apres_mm: float

    @property
    def gain_mm(self) -> float:
        return max(0.0, self.avant_mm - self.apres_mm)

    @property
    def gain(self) -> float:
        return self.gain_mm / self.avant_mm if self.avant_mm > 0.0 else 0.0

    def describe(self) -> str:
        return (f"{self.n_abaissees}/{self.n_liaisons} liaisons abaissees, "
                f"{self.avant_mm:.0f} -> {self.apres_mm:.0f} mm "
                f"({self.gain * 100:.0f} % de transport en moins)")


def _runs(masque: np.ndarray) -> list[tuple[int, int]]:
    """Plages maximales de ``True``, en (debut, fin exclue)."""
    out, i, n = [], 0, len(masque)
    while i < n:
        if masque[i]:
            j = i
            while j < n and masque[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def _longueur(p: np.ndarray) -> float:
    if len(p) < 2:
        return 0.0
    return float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum())


def _base(d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Deux vecteurs unitaires perpendiculaires a ``d`` et entre eux."""
    a = np.array([1.0, 0.0, 0.0]) if abs(d[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = np.cross(d, a)
    e1 /= np.linalg.norm(e1)
    return e1, np.cross(d, e1)


def _distance_au_segment(P2: np.ndarray, A2: np.ndarray,
                         B2: np.ndarray) -> np.ndarray:
    """Distance 2D de chaque point au segment [A2, B2]."""
    ab = B2 - A2
    n2 = float(ab @ ab)
    if n2 < 1e-18:
        return np.linalg.norm(P2 - A2, axis=1)
    t = np.clip(((P2 - A2) @ ab) / n2, 0.0, 1.0)
    return np.linalg.norm(P2 - (A2 + t[:, None] * ab), axis=1)


def hauteur_libre(etat, a: np.ndarray, b: np.ndarray, direction: np.ndarray,
                  outil, *, garde_mm: float = GARDE_MM) -> float:
    """Hauteur de bec la plus BASSE a laquelle la liaison a -> b ne touche rien.

    Exprimee comme le reste du module dans la coordonnee ``p . d``, ou ``d``
    est l'axe de l'outil. Voir l'en-tete pour le raisonnement — un maximum par
    tronçon d'outil, et non une suite d'essais.

    Le couloir est celui du segment HORIZONTAL de la liaison, dilate du rayon
    du tronçon. Les montees et descentes se font aux deux extremites, donc
    dedans : le couloir les couvre sans calcul supplementaire.
    """
    d = np.asarray(direction, dtype=np.float64)
    d = d / np.linalg.norm(d)
    e1, e2 = _base(d)
    vr = 0.5 * float(etat.grid.pitch) * np.sqrt(3.0)

    segs = list(outil.segments)
    if not segs:
        return max(float(a @ d), float(b @ d)) + garde_mm
    r_max = max(max(sg.r_start, sg.r_end) for sg in segs)

    # Les voxels candidats : ceux d'une boite autour du segment, elargie du
    # plus gros rayon de l'outil. Le reste de la grille ne peut pas etre
    # touche, et l'ecarter d'abord est ce qui fait tenir le calcul en
    # millisecondes plutot qu'en secondes.
    grille = etat.grid
    pas = float(grille.pitch)
    origine = np.asarray(grille.origin, dtype=np.float64)
    lo = np.minimum(a, b) - (r_max + vr + pas)
    hi = np.maximum(a, b) + (r_max + vr + pas)
    # La boite doit monter jusqu'en haut de la grille : la matiere qui compte
    # est AU-DESSUS de la liaison, pas a son niveau.
    haut_grille = origine + np.asarray(grille.shape, dtype=np.float64) * pas
    hi = np.where(d > 0, haut_grille, hi)
    lo = np.where(d < 0, origine, lo)
    i0 = np.maximum(0, np.floor((lo - origine) / pas).astype(np.int64))
    i1 = np.minimum(grille.shape,
                    np.ceil((hi - origine) / pas).astype(np.int64) + 1)
    if np.any(i1 <= i0):
        return max(float(a @ d), float(b @ d)) + garde_mm

    sous = etat.remaining[i0[0]:i1[0], i0[1]:i1[1], i0[2]:i1[2]]
    if not sous.any():
        return max(float(a @ d), float(b @ d)) + garde_mm
    loc = np.argwhere(sous)
    pts = origine + (loc + i0 + 0.5) * pas

    A2 = np.array([a @ e1, a @ e2])
    B2 = np.array([b @ e1, b @ e2])
    P2 = np.column_stack([pts @ e1, pts @ e2])
    dist = _distance_au_segment(P2, A2, B2)
    z = pts @ d

    h = max(float(a @ d), float(b @ d))
    for sg in segs:
        r = max(sg.r_start, sg.r_end) + vr
        dedans = dist <= r
        if not dedans.any():
            continue
        # M_i : le plus haut point de matiere du couloir de ce tronçon.
        # ``h > M_i - z_start`` sort le tronçon de la matiere.
        h = max(h, float(z[dedans].max()) + vr - float(sg.z_start))
    return h + garde_mm


def touche(etat, poses: np.ndarray, direction: np.ndarray, outil) -> bool:
    """L'outil COMPLET rencontre-t-il de la matiere sur ces poses ?

    Le meme calcul que l'enlevement de matiere, mais en lecture : on copie
    l'etat dans une sonde ou TOUT est enlevable, on y passe l'outil, et on
    regarde s'il a pris quelque chose. Reutiliser ce calcul plutot que d'en
    ecrire un second garantit que les deux repondent la meme chose — deux
    tests geometriques differents pour la meme question divergeraient, et
    celui qu'on croirait serait celui qui autorise.

    ``only_cutting=False`` : une liaison est un deplacement rapide, et c'est
    le porte-outil qui touche en premier, pas l'arete de coupe.
    """
    from ..stock_engine.material import MaterialState

    if len(poses) == 0:
        return False
    sonde = MaterialState(etat.grid, etat.remaining.copy(),
                          np.zeros_like(etat.protected))
    axes = np.tile(np.asarray(direction, dtype=np.float64), (len(poses), 1))
    return sonde.remove_tool_sweep(poses, axes, outil, only_cutting=False) > 0


def _echantillonner(sommets: np.ndarray, pas: float) -> np.ndarray:
    """Polyligne densifiee a un pas plus fin que la grille.

    Sans cela un voxel pourrait se glisser entre deux poses et la liaison
    serait declaree libre alors qu'elle traverse la matiere.
    """
    bouts = [sommets[:1]]
    for a, b in zip(sommets[:-1], sommets[1:]):
        n = max(2, int(np.ceil(float(np.linalg.norm(b - a)) / pas)) + 1)
        bouts.append(a + (b - a) * np.linspace(0.0, 1.0, n)[1:, None])
    return np.vstack(bouts)


def abaisser_les_liaisons(points, rapide, material, outil, direction, *,
                          clearance_z: float | None = None,
                          garde_mm: float = GARDE_MM
                          ) -> tuple[np.ndarray, np.ndarray, GainLiaisons]:
    """Remplace chaque liaison par la plus BASSE qui ne touche rien.

    ``points`` et ``rapide`` sortent de ``continuous_path``. Le resultat a la
    meme forme : des positions du bout de l'outil dans le repere PIECE, et un
    drapeau par point.

    La matiere est suivie au fur et a mesure : chaque passe de coupe est
    retiree d'une copie avant que la liaison suivante ne soit essayee. C'est ce
    qui permet de descendre dans une poche qu'on vient de vider — et ce qui
    interdit de descendre dans une poche qu'on n'a pas encore ouverte.
    """
    P = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    R = np.asarray(rapide, dtype=bool)
    d = np.asarray(direction, dtype=np.float64)
    d = d / np.linalg.norm(d)
    liaisons = _runs(R)
    avant = sum(_longueur(P[a:b]) for a, b in liaisons)
    if not len(liaisons):
        return P, R, GainLiaisons(0, 0, 0.0, 0.0)

    etat = copy.deepcopy(material)
    pas = float(material.grid.pitch) * 0.5
    # Hauteur du plan de degagement, PROJETEE sur l'axe outil : c'est la
    # coordonnee que les liaisons actuelles atteignent.
    if clearance_z is None:
        clearance_z = float(max(P @ d)) if len(P) else 0.0

    morceaux: list[np.ndarray] = []
    drapeaux: list[np.ndarray] = []
    n_abaissees = 0
    curseur = 0
    for deb, fin in liaisons:
        # La coupe qui precede : on l'emet telle quelle, et on l'enleve de la
        # matiere avant d'essayer la liaison qui la suit.
        coupe = P[curseur:deb]
        if len(coupe):
            morceaux.append(coupe)
            drapeaux.append(np.zeros(len(coupe), dtype=bool))
            axes = np.tile(d, (len(coupe), 1))
            etat.remove_tool_sweep(coupe, axes, outil)
        curseur = fin

        a = P[deb - 1] if deb > 0 else P[deb]
        b = P[fin] if fin < len(P) else P[fin - 1]
        # Le plan de degagement reste le PLAFOND : ce module ne peut pas
        # rendre une liaison pire que celle qu'il remplace.
        h = min(hauteur_libre(etat, a, b, d, outil, garde_mm=garde_mm),
                max(clearance_z, max(float(a @ d), float(b @ d)) + garde_mm))
        remplacee = np.array([a, a + d * (h - a @ d), b + d * (h - b @ d), b])
        if _longueur(remplacee) < _longueur(P[deb:fin]) - 1e-6:
            n_abaissees += 1
        else:
            remplacee = P[deb:fin]
        # Les sommets, pas un echantillonnage dense : une liaison est une
        # droite dans le vide, et la densifier gonflerait le programme sans
        # rien apporter. C'est le choix deja fait par ``continuous_path``.
        morceaux.append(remplacee)
        drapeaux.append(np.ones(len(remplacee), dtype=bool))

    reste = P[curseur:]
    if len(reste):
        morceaux.append(reste)
        drapeaux.append(np.zeros(len(reste), dtype=bool))

    Q = np.vstack(morceaux) if morceaux else P
    F = np.concatenate(drapeaux) if drapeaux else R
    apres = sum(_longueur(Q[a:b]) for a, b in _runs(F))
    return Q, F, GainLiaisons(len(liaisons), n_abaissees, avant, apres)
