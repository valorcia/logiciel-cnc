"""Combien de temps une gamme prend, et pourquoi ce chiffre est un PLANCHER.

Ce que ce module rend, et ce qu'il ne rend pas
---------------------------------------------
Il rend le temps que prendrait la gamme si chaque axe atteignait
instantanement son avance et la tenait jusqu'au sommet suivant. C'est donc un
**minorant**, jamais une estimation, et encore moins une promesse. Ce qui
manque, nomme :

- **les accelerations**. Une trajectoire d'ebauche en zigzag change de sens a
  chaque rangee, et une machine qui decelere puis reaccelere a chaque
  inversion passe une part reelle de son temps hors avance nominale. Sur un
  kit, dont les accelerations dependent de l'assemblage de l'acheteur, ce
  chiffre ne peut pas etre pose ici ;
- **l'anticipation** (lookahead) et le ralentissement dans les angles ;
- **les changements d'outil**, la mise en vitesse de broche, les temporisations
  d'arrosage ;
- **le palpage** et les reprises entre montages.

Un chiffre qui manque ces postes est donc systematiquement OPTIMISTE, et il
doit s'annoncer comme tel : « au moins 14 min », jamais « environ 14 min ».
C'est la meme regle que pour ±0,02 mm — un objectif de qualification, pas un
acquis.

D'ou viennent les avances
-------------------------
L'avance de COUPE vient de ``recipe_profiles.build_recipe``, c'est-a-dire de
la matiere declaree, de l'outil et de la machine, deja bridee par les courses
d'avance des axes et deja reduite de moitie faute de qualification (ADR-007).
Elle n'est pas inventee ici, et ce module ne sait pas en fabriquer une.

L'avance de RAPIDE est celle des axes, et elle depend de la DIRECTION : un
mouvement diagonal est limite par le premier axe qui sature, donc par
``min_i (V_i / |d_i|)``. Prendre la plus petite des trois avances maximales
serait pessimiste sur un mouvement selon un seul axe, et prendre la plus
grande serait faux. Le calcul se fait donc segment par segment, dans le repere
MACHINE — c'est la que les axes existent.

La meme hypothese de machine
----------------------------
``min_i (V_i / |d_i|)`` suppose trois axes lineaires INDEPENDANTS, chacun avec
sa vitesse maximale. Sur une cinematique PARALLELE (delta, tripode), la vitesse
de chaque chariot est une fonction non lineaire de la position ET de la
direction : le meme deplacement cartesien coûte des vitesses de chariot
differentes selon l'endroit du volume ou il a lieu. La formule ci-dessous
serait alors fausse, et pas seulement imprecise.

Pourquoi le repere machine
--------------------------
Les longueurs, elles, sont les memes dans les deux reperes : une operation
indexee garde A et C constants, et une rotation conserve les distances. Mais
les DIRECTIONS changent, et ce sont elles qui decident quel axe sature. Un
deplacement selon X de la piece, a A = -90° et C = -90°, est un deplacement
selon Y de la machine — avec une autre avance maximale.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def _texte_duree(secondes: float) -> str:
    """Une duree lisible par quelqu'un qui attend devant la machine.

    Pas de « 8 640 s » ni de « 2.4 h » : des heures et des minutes, et des
    secondes seulement quand il n'y a pas de minutes — sinon le chiffre precis
    laisse croire a une precision que ce calcul n'a pas.
    """
    s = max(0.0, float(secondes))
    if s < 60.0:
        return f"{s:.0f} s"
    minutes = int(round(s / 60.0))
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d} min"


@dataclass(frozen=True)
class Duree:
    """Le temps plancher d'une trajectoire, decompose par poste.

    Le decoupage n'est pas decoratif : sur une gamme d'ebauche, savoir que la
    moitie du temps part en deplacements rapides est ce qui fait changer le
    sens de balayage ou le plan de degagement. Un total seul ne dit pas quoi
    faire.
    """

    longueur_coupe_mm: float
    longueur_rapide_mm: float
    coupe_s: float
    rapide_s: float
    rotation_s: float
    n_reindexations: int
    avance_coupe_mm_min: float
    #: Ce qui a limite l'avance de coupe, tel que la recette le rapporte.
    bridages: tuple[str, ...] = ()
    #: Postes NON modelises, nommes. Calcule et non ecrit : une liste ecrite
    #: survivrait a la disparition de ce qu'elle decrit.
    manques: tuple[str, ...] = ()

    @property
    def total_s(self) -> float:
        return self.coupe_s + self.rapide_s + self.rotation_s

    @property
    def part_en_coupe(self) -> float:
        """Fraction du temps passee a couper. Le reste est du transport."""
        t = self.total_s
        return 0.0 if t <= 0.0 else self.coupe_s / t

    def texte(self) -> str:
        return _texte_duree(self.total_s)

    def consigne(self) -> str:
        """Le chiffre et sa reserve, dans la meme phrase.

        La reserve n'est pas une note de bas de page : un temps annonce sans
        elle sera lu comme un temps, et quelqu'un organisera sa journee
        dessus.
        """
        bouts = [f"Au moins {self.texte()} de cycle — "
                 f"{_texte_duree(self.coupe_s)} en coupe, "
                 f"{_texte_duree(self.rapide_s)} en déplacements rapides"]
        if self.n_reindexations:
            bouts[0] += (f", {_texte_duree(self.rotation_s)} de rotation pour "
                         f"{self.n_reindexations} réindexation(s)")
        bouts[0] += "."
        bouts.append(f"AU MOINS : ce calcul suppose chaque axe à son avance "
                     f"dès le premier millimètre.")
        if self.manques:
            bouts.append("Ne sont pas comptés : " + ", ".join(self.manques)
                         + ".")
        bouts.append(f"Avance de coupe {self.avance_coupe_mm_min:.0f} mm/min"
                     + (" (bridée par " + ", ".join(self.bridages) + ")"
                        if self.bridages else "") + ".")
        return " ".join(bouts)

    def describe(self) -> str:
        return (f"{self.texte()} au moins : coupe {self.coupe_s:.0f} s sur "
                f"{self.longueur_coupe_mm:.0f} mm a "
                f"{self.avance_coupe_mm_min:.0f} mm/min, rapide "
                f"{self.rapide_s:.0f} s sur {self.longueur_rapide_mm:.0f} mm, "
                f"rotation {self.rotation_s:.0f} s "
                f"({self.n_reindexations} reindexations), "
                f"{self.part_en_coupe * 100:.0f} % du temps en coupe")


#: Postes qu'aucun calcul de ce module ne couvre, dans l'ordre ou ils pesent.
#:
#: Ecrits ici et non dans la phrase : une phrase qui enumere des manques doit
#: pouvoir se raccourcir quand un manque disparait, et cela demande une liste.
MANQUES = (
    "les accélérations et le ralentissement dans les angles",
    "les changements d'outil et la mise en vitesse de broche",
    "le palpage et les reprises entre montages",
)


def avance_rapide_mm_min(machine, directions: np.ndarray) -> np.ndarray:
    """Avance rapide praticable pour chaque direction, dans le repere MACHINE.

    ``min_i (V_i / |d_i|)`` : le premier axe qui sature impose la vitesse du
    vecteur. Un axe immobile (``d_i = 0``) ne limite rien — d'ou le masque,
    sans lequel une division par zero donnerait un infini qui se propagerait
    en NaN a la premiere multiplication.
    """
    V = np.array([machine.x.max_feed_mm_min, machine.y.max_feed_mm_min,
                  machine.z.max_feed_mm_min], dtype=np.float64)
    d = np.abs(np.asarray(directions, dtype=np.float64).reshape(-1, 3))
    with np.errstate(divide="ignore", invalid="ignore"):
        lim = np.where(d > 1e-12, V[None, :] / np.maximum(d, 1e-12), np.inf)
    f = lim.min(axis=1)
    # Un segment de longueur nulle n'a pas de direction : il ne prend pas de
    # temps non plus, et sa vitesse n'a donc pas a etre definie.
    return np.where(np.isfinite(f), f, float(V.min()))


def duree_trajectoire(machine, points_piece: np.ndarray, is_rapid,
                      mount_offset_mm, a_deg: float, c_deg: float, *,
                      avance_coupe_mm_min: float) -> tuple[float, float, float, float]:
    """``(longueur_coupe, longueur_rapide, temps_coupe, temps_rapide)``.

    Les points sont dans le repere PIECE ; ils sont transportes dans le repere
    MACHINE parce que c'est la que les avances maximales des axes ont un sens.
    """
    from ..kinematics_solver.solver import KinematicsSolver

    P = np.asarray(points_piece, dtype=np.float64).reshape(-1, 3)
    if len(P) < 2:
        return 0.0, 0.0, 0.0, 0.0
    kin = KinematicsSolver(machine)
    off = np.asarray(mount_offset_mm, dtype=np.float64).reshape(3)
    M = np.array([kin.part_to_machine_point(p + off, a_deg, c_deg) for p in P])

    seg = np.diff(M, axis=0)
    L = np.linalg.norm(seg, axis=1)
    # Un segment est RAPIDE si son point d'arrivee l'est : c'est la convention
    # du trancheur (``is_rapid[i]`` qualifie le mouvement QUI MENE au point i).
    r = (np.zeros(len(L), dtype=bool) if is_rapid is None
         else np.asarray(is_rapid, dtype=bool)[1:])

    dirs = np.zeros_like(seg)
    nz = L > 1e-12
    dirs[nz] = seg[nz] / L[nz, None]
    f_rapide = avance_rapide_mm_min(machine, dirs)

    l_coupe = float(L[~r].sum())
    l_rapide = float(L[r].sum())
    fc = max(float(avance_coupe_mm_min), 1e-6)
    t_coupe = l_coupe / fc * 60.0
    t_rapide = float((L[r] / np.maximum(f_rapide[r], 1e-6)).sum()) * 60.0
    return l_coupe, l_rapide, t_coupe, t_rapide


def duree_rotation_s(machine, a_de: float, c_de: float,
                     a_vers: float, c_vers: float) -> float:
    """Temps d'une reindexation, A et C tournant ENSEMBLE.

    Le maximum des deux et non leur somme : sur cette machine les deux axes
    rotatifs se commandent dans le meme bloc et partent ensemble. Les
    additionner surestimerait — ce qui, pour un minorant declare, serait une
    incoherence.
    """
    va = max(float(machine.a.max_feed_deg_min or 0.0), 1e-6)
    vc = max(float(machine.c.max_feed_deg_min or 0.0), 1e-6)
    return max(abs(a_vers - a_de) / va, abs(c_vers - c_de) / vc) * 60.0


def duree_plan(machine, operations, courses, mount_offset_mm, *,
               avance_coupe_mm_min: float,
               bridages: tuple[str, ...] = ()) -> Duree:
    """Le temps plancher d'une gamme complete, reindexations comprises.

    ``operations`` et ``courses`` viennent du ``PlanReport`` : les secondes
    portent les couples (A, C) retenus, et c'est d'eux que se deduisent les
    reindexations — le nombre d'operations ne suffit pas, deux operations
    consecutives pouvant partager la meme indexation.
    """
    l_c = l_r = t_c = t_r = 0.0
    t_rot = 0.0
    n_reindex = 0
    pose = None
    for op, course in zip(operations, courses):
        a, c = float(course.a_deg), float(course.c_deg)
        if pose is None:
            # La premiere mise en position part du home : elle est comptee
            # comme une reindexation, parce qu'elle prend du temps elle aussi.
            t_rot += duree_rotation_s(machine, 0.0, 0.0, a, c)
            n_reindex += 1
        elif (a, c) != pose:
            t_rot += duree_rotation_s(machine, pose[0], pose[1], a, c)
            n_reindex += 1
        pose = (a, c)
        lc, lr, tc, tr = duree_trajectoire(
            machine, op.toolpath.points, op.toolpath.is_rapid,
            mount_offset_mm, a, c, avance_coupe_mm_min=avance_coupe_mm_min)
        l_c += lc
        l_r += lr
        t_c += tc
        t_r += tr
    return Duree(longueur_coupe_mm=l_c, longueur_rapide_mm=l_r,
                 coupe_s=t_c, rapide_s=t_r, rotation_s=t_rot,
                 n_reindexations=n_reindex,
                 avance_coupe_mm_min=float(avance_coupe_mm_min),
                 bridages=tuple(bridages), manques=MANQUES)
