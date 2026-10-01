"""L'ordre des creux entre eux : ce qui coûte, et dans quel ordre de grandeur.

Ce que l'ordre des creux decide, et ce qu'il ne decide pas
===========================================================

``subtractive_slicer.ordre`` reordonne les passes A L'INTERIEUR d'une couche.
Il restait la question du dessus : dans quel ordre vider les creux d'une piece.
Trois choses en dependent, et elles ne sont pas du meme ordre de grandeur.

**1. Les changements d'outil.** Ce kit n'a pas de changeur : le porte-outil est
une pince ER16, et changer d'outil est une INTERVENTION DE L'OPERATEUR. On
arrete, on desserre, on remonte, on rejauge. Cela ne se compare pas a des
millimetres de transport, et la fiche porte desormais la cote qui le dit
(``changeur_outil_automatique``), pour que l'hypothese soit visible et
corrigible plutot que enfouie ici.

**2. Les re-indexations (A, C).** Changer l'orientation fait tourner le
plateau et basculer le berceau. C'est un mouvement machine, et c'est aussi une
reprise de jeu sur deux axes rotatifs dont la fiche declare le jeu — a zero,
pour l'instant, parce que personne ne l'a mesure.

**3. Le transport.** La distance a vol d'oiseau entre la fin d'un creux et le
debut du suivant.

Pourquoi un ordre LEXICOGRAPHIQUE, et pas une somme ponderee
-------------------------------------------------------------

Ponderer exigerait un taux de change entre « une intervention d'operateur »,
« une rotation de plateau » et « un millimetre de transport ». Ce taux
demanderait un modele de temps, donc les vitesses d'avance et de rapide — qui
sont, dans la fiche, des cotes DE PLAN. Habiller une estimation en optimum
serait exactement ce que ce projet refuse ailleurs.

L'ordre est donc strictement lexicographique :

  1. grouper par OUTIL — et le minimum de changements d'outil, pour k outils,
     vaut k-1 ; tout groupement l'atteint, donc ce terme est optimal, pas
     heuristique ;
  2. a l'interieur d'un groupe d'outil, grouper par ORIENTATION — meme
     raisonnement, meme optimalite ;
  3. a l'interieur d'un groupe d'orientation, raccourcir le TRANSPORT par
     plus-proche-voisin puis 2-opt, en reutilisant les fonctions deja ecrites
     et eprouvees de ``subtractive_slicer.ordre``.

**Le transport peut AUGMENTER, et c'est assume.** Grouper par outil peut
eloigner deux creux voisins qui n'utilisent pas le meme. C'est le prix de
l'echelon superieur, il est mesure et rendu — pas tu.

Les gros outils d'abord — mais c'est une preference, pas une contrainte
-----------------------------------------------------------------------

Les groupes d'outil sont parcourus par diametre DECROISSANT : un creux large se
vide a la grosse fraise, un creux etroit a la petite. Le nombre de changements
ne depend pas de l'ordre des groupes, donc cette regle ne coûte jamais une
intervention.

Elle peut en revanche coûter du TRAJET, et avec un outil par creux l'ordre des
groupes ne change pas qui coupe quoi. C'est donc une preference, et la garantie
ci-dessous la cede quand elle ne paie rien.

La garantie, au niveau de la SEQUENCE
--------------------------------------

Le 2-opt garantit de ne pas rallonger a l'interieur d'un sous-groupe. Cela ne
dit rien de l'ordre DES sous-groupes, et c'est par la que la premiere version
de ce module degradait : sur C05 — deux creux, un seul outil, deux
orientations — elle les intervertissait et faisait passer le transport de 36 a
61 mm pour zero changement d'outil economise, en annoncant « c'est le prix du
groupement par outil ». Une explication fausse est pire qu'une absence
d'explication : elle empeche de voir le defaut qu'elle recouvre.

Si aucun terme superieur n'a progresse, l'ordre RECU est au moins aussi bon :
on le garde. Un reordonnancement qui degrade sans contrepartie n'est pas un
compromis, c'est un defaut.

Ce qu'un creux ne retourne jamais
----------------------------------

Une passe de couche peut etre parcourue dans les deux sens (voir ``ordre``).
Un CREUX, non : son chemin descend couche par couche, et le prendre a l'envers
remonterait du fond vers la surface. Le 2-opt travaille donc ici sans
retournement.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..subtractive_slicer.ordre import (PASSES_2OPT, _bouts, _cout, _deux_opt,
                                        _plus_proche_voisin)

#: Deux orientations plus proches que cela sont la MEME : on ne re-indexe pas
#: pour un demi-degre, et la machine ne saurait pas le faire.
MEME_ORIENTATION_DEG = 0.5

#: Deux outils dont les rayons different de moins de cela sont le meme outil.
MEME_OUTIL_MM = 1.0e-6


@dataclass
class GainOrdreCreux:
    """Ce que le reordonnancement a change, terme par terme.

    Les trois termes sont rendus separement et AVANT/APRES. Les resumer en un
    seul chiffre supposerait le taux de change que ce module refuse justement
    de se donner.
    """

    n_creux: int = 0
    ordre: list[int] = field(default_factory=list)
    outils_avant: int = 0
    outils_apres: int = 0
    indexations_avant: int = 0
    indexations_apres: int = 0
    transport_avant_mm: float = 0.0
    transport_apres_mm: float = 0.0

    @property
    def transport_pire(self) -> bool:
        """Le transport a-t-il AUGMENTE ? C'est permis, et cela se dit."""
        return self.transport_apres_mm > self.transport_avant_mm + 1e-6

    def resume(self) -> str:
        if self.n_creux < 2:
            return f"{self.n_creux} creux : aucun ordre à décider."
        bouts = [
            f"changements d'outil {self.outils_avant} → {self.outils_apres}",
            f"ré-indexations {self.indexations_avant} → {self.indexations_apres}",
            f"transport {self.transport_avant_mm:.0f} → "
            f"{self.transport_apres_mm:.0f} mm",
        ]
        s = f"{self.n_creux} creux réordonnés : " + ", ".join(bouts) + "."
        if self.transport_pire:
            # Nommer le terme qui a REELLEMENT progresse.
            #
            # La premiere version disait « c'est le prix du groupement par
            # outil » dans tous les cas. Sur C05, qui n'a qu'un seul outil,
            # elle invoquait donc une economie de zero changement d'outil pour
            # justifier 25 mm de trajet en plus. Une explication fausse est
            # pire qu'une absence d'explication : elle empeche de voir le
            # defaut qu'elle recouvre.
            gagne = []
            if self.outils_apres < self.outils_avant:
                gagne.append(f"{self.outils_avant - self.outils_apres} "
                             "changement(s) d'outil — une intervention de "
                             "l'opérateur à chaque fois")
            if self.indexations_apres < self.indexations_avant:
                gagne.append(f"{self.indexations_avant - self.indexations_apres} "
                             "ré-indexation(s) du berceau")
            s += (" Le transport augmente : c'est le prix de "
                  + " et ".join(gagne) + ".") if gagne else ""
        return s


def _cle_outil(outil) -> float:
    """Ce qui distingue deux outils pour cette question : leur rayon."""
    return round(max(s.r_max for s in outil.segments
                     if s.role.value == "cutting") / MEME_OUTIL_MM) * MEME_OUTIL_MM


def _cle_orientation(parcours) -> tuple[float, float]:
    pas = MEME_ORIENTATION_DEG
    return (round(float(parcours.a_deg) / pas) * pas,
            round(float(parcours.c_deg) / pas) * pas)


def _compter(ordre, cles_outil, cles_orient) -> tuple[int, int]:
    """Changements d'outil et re-indexations d'une sequence donnee."""
    o = i = 0
    for a, b in zip(ordre[:-1], ordre[1:]):
        if cles_outil[a] != cles_outil[b]:
            o += 1
        if cles_orient[a] != cles_orient[b]:
            i += 1
    return o, i


def _transport(ordre, debuts, fins) -> float:
    """Somme des sauts entre creux, a vol d'oiseau.

    A vol d'oiseau et non la vraie liaison : sa hauteur depend de la matiere,
    donc de l'ordre, donc d'elle-meme. Meme choix que dans ``ordre``, et pour
    la meme raison.
    """
    return sum(float(np.linalg.norm(debuts[b] - fins[a]))
               for a, b in zip(ordre[:-1], ordre[1:]))


def ordonner_les_creux(elements, *, n_passes: int = PASSES_2OPT) -> GainOrdreCreux:
    """L'ordre dans lequel vider les creux. ``elements`` : (parcours, outil, _).

    Rend les INDICES dans l'ordre retenu, et ce que chaque terme a coûté ou
    gagne. Ne touche a rien d'autre : c'est l'appelant qui applique l'ordre,
    et c'est lui qui verifie ensuite dans ce meme ordre.
    """
    g = GainOrdreCreux(n_creux=len(elements))
    if len(elements) < 2:
        g.ordre = list(range(len(elements)))
        return g

    parcours = [e[0] for e in elements]
    outils = [e[1] for e in elements]
    # Un creux SANS parcours n'a ni debut ni fin : il n'a donc pas de place
    # dans un ordre, et lui en donner une laisserait croire qu'il va se faire.
    # Le dire ici plutot que de laisser ``_bouts`` lever un IndexError sur un
    # tableau vide — c'est ce que faisait la premiere version, et le defaut
    # n'est apparu qu'en ouvrant l'ecran des creux sur une piece qui en porte.
    vides = [i for i, pa in enumerate(parcours)
             if len(np.asarray(pa.points).reshape(-1, 3)) == 0]
    if vides:
        raise ValueError(
            "ordonner_les_creux : les creux "
            + ", ".join(str(parcours[i].index) for i in vides)
            + " n'ont aucun parcours. Les écarter AVANT d'ordonner : un rang "
              "sur un creux qui ne sera pas usiné est une fausse valeur.")
    cles_outil = [_cle_outil(o) for o in outils]
    cles_orient = [_cle_orientation(p) for p in parcours]
    chemins = [np.asarray(p.points, dtype=np.float64).reshape(-1, 3)
               for p in parcours]
    debuts, fins = _bouts(chemins)

    origine = list(range(len(elements)))
    g.outils_avant, g.indexations_avant = _compter(origine, cles_outil, cles_orient)
    g.transport_avant_mm = _transport(origine, debuts, fins)

    # --- 1. groupes d'outil, du plus GROS au plus petit
    final: list[int] = []
    ou = None                      # position courante : la fin du creux precedent
    angle = None                   # orientation courante
    for cle in sorted(set(cles_outil), reverse=True):
        du_groupe = [i for i in origine if cles_outil[i] == cle]

        # --- 2. sous-groupes d'orientation, au plus proche en ANGLE
        restants = {}
        for i in du_groupe:
            restants.setdefault(cles_orient[i], []).append(i)
        while restants:
            if angle is None:
                # **Pas ``min(restants)``.** Trier des couples d'angles revient
                # a choisir le premier sous-groupe sur un ordre lexicographique
                # de nombres, c'est-a-dire sur rien. Sur C05 — deux creux, un
                # seul outil, deux orientations — cela suffisait a les
                # intervertir et a rallonger le transport de 36 a 61 mm pour
                # aucun gain.
                #
                # A defaut d'orientation courante, l'ordre RECU est le
                # depart naturel : on commence par le sous-groupe du creux
                # arrive en premier.
                suivant = min(restants, key=lambda k: min(restants[k]))
            else:
                suivant = min(restants, key=lambda k: (abs(k[0] - angle[0])
                                                       + abs(k[1] - angle[1])))
            bloc = restants.pop(suivant)
            angle = suivant

            # --- 3. transport a l'interieur du sous-groupe
            if len(bloc) > 1:
                sous_debuts = debuts[bloc]
                sous_fins = fins[bloc]
                tour = _plus_proche_voisin(sous_debuts, sous_fins, ou,
                                           retournable=False)
                tour = _deux_opt(tour, sous_debuts, sous_fins, ou,
                                 retournable=False, n_passes=n_passes)
                # L'ordre RECU du sous-groupe est un candidat comme un autre :
                # on ne le quitte que pour plus court. Sans cela, le module
                # pourrait rendre pire que ce qu'on lui a donne.
                tel_quel = [(k, False) for k in range(len(bloc))]
                if _cout(tel_quel, sous_debuts, sous_fins, ou) <= _cout(
                        tour, sous_debuts, sous_fins, ou) + 1e-9:
                    tour = tel_quel
                bloc = [bloc[k] for k, _ in tour]

            final.extend(bloc)
            ou = fins[bloc[-1]]

    g.ordre = final
    g.outils_apres, g.indexations_apres = _compter(final, cles_outil, cles_orient)
    g.transport_apres_mm = _transport(final, debuts, fins)

    # **La garantie, au niveau de la SEQUENCE et pas du sous-groupe.**
    #
    # Le 2-opt garantit de ne pas rallonger a l'interieur d'un sous-groupe.
    # Cela ne dit rien de l'ordre DES sous-groupes, et c'est par la que la
    # premiere version rallongeait le trajet sans rien economiser. Si aucun
    # terme superieur n'a progresse, l'ordre recu est au moins aussi bon : on
    # le garde. Un reordonnancement qui degrade sans contrepartie n'est pas un
    # compromis, c'est un defaut.
    if (g.outils_apres >= g.outils_avant
            and g.indexations_apres >= g.indexations_avant
            and g.transport_apres_mm > g.transport_avant_mm + 1e-9):
        g.ordre = origine
        g.outils_apres, g.indexations_apres = g.outils_avant, g.indexations_avant
        g.transport_apres_mm = g.transport_avant_mm
    return g
