"""L'ordre des passes : ce qui reste du transport une fois les liaisons basses.

Le chiffre qui a motive ce module
----------------------------------
``liaisons`` a ramene le transport du corpus de 20 a 15 metres en abaissant
chaque liaison a la hauteur la plus basse qui degage. Sur une poche compacte
c'est spectaculaire — C03 passe de 37 a 87 % de chemin coupant. Sur le DOME de
C10, le gain est de 4 %.

C10 dit pourquoi, et il dit ce qu'il faut faire. Ses 117 liaisons, pour un seul
creux, vont d'une region a l'autre par-dessus le dome lui-meme, qui est de la
matiere protegee. Aucune hauteur plus basse n'existe : le calcul de hauteur
n'avait rien a trouver. Ce qui coûte la n'est pas la hauteur d'une liaison,
c'est le NOMBRE de liaisons et leur longueur — donc l'ordre dans lequel on
visite les regions.

Ce que ce module reordonne, et ce qu'il ne touche pas
-----------------------------------------------------
Il reordonne les passes A L'INTERIEUR d'une couche, et rien d'autre. L'ordre
des couches est une contrainte physique — on ne peut pas usiner la couche 5
avant la 4 — et le melanger a une question de trajet serait confondre une
regle avec une preference.

Le point de depart de chaque couche est la FIN de la precedente : c'est
gratuit, et cela raccourcit aussi la liaison entre deux couches.

Retourner une passe : seulement en zigzag
------------------------------------------
Parcourir une passe dans l'autre sens raccourcit souvent le trajet. Mais le
sens de parcours est le sens de COUPE, et le balayage ``unidirectionnel``
existe precisement pour le garder constant — l'avalant et l'opposition n'usent
pas l'outil de la meme facon, et quelqu'un qui a choisi ce mode l'a choisi.

Ce module ne retourne donc une passe que si le balayage est deja ``zigzag``,
ou l'alternance est dans le contrat. Le dire plutot que de retourner partout
est la difference entre un raccourci et une trahison du reglage.

La methode, et ce qu'elle vaut
-------------------------------
Plus proche voisin, puis 2-opt. C'est le couple classique du probleme du
voyageur de commerce, et il n'est pas optimal : il ne pretend pas l'etre. Sur
des dizaines de passes par couche, l'optimum exact coûterait des heures pour
quelques pour cent — et ces quelques pour cent se perdraient dans les
approximations de tout le reste de cette chaine.

Ce qui est garanti, en revanche : le resultat n'est JAMAIS pire que l'ordre
d'origine. Celui-ci est evalue en premier, et on ne le quitte que pour plus
court.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: Nombre maximal de balayages 2-opt par couche.
#:
#: Chaque balayage est en O(n^2) sur les passes de la couche. Vingt suffisent
#: a converger sur tout ce que le corpus presente ; au-dela le gain se compte
#: en millimetres.
PASSES_2OPT = 20

#: En deça de ce nombre de passes, l'ordre n'a rien a optimiser.
MINIMUM = 3


@dataclass(frozen=True)
class GainOrdre:
    """Ce que le reordonnancement a change, en mm de liaison a vol d'oiseau."""

    n_couches: int
    n_passes: int
    avant_mm: float
    apres_mm: float

    @property
    def gain_mm(self) -> float:
        return max(0.0, self.avant_mm - self.apres_mm)

    @property
    def gain(self) -> float:
        return self.gain_mm / self.avant_mm if self.avant_mm > 0.0 else 0.0

    def describe(self) -> str:
        return (f"{self.n_passes} passes sur {self.n_couches} couches, "
                f"liaisons {self.avant_mm:.0f} -> {self.apres_mm:.0f} mm "
                f"({self.gain * 100:.0f} % de trajet en moins)")


def _bouts(polylignes: list) -> tuple[np.ndarray, np.ndarray]:
    """Premier et dernier point de chaque passe."""
    debuts = np.array([np.asarray(p, dtype=np.float64)[0] for p in polylignes])
    fins = np.array([np.asarray(p, dtype=np.float64)[-1] for p in polylignes])
    return debuts, fins


def _cout(tour: list[tuple[int, bool]], debuts, fins, depart) -> float:
    """Longueur totale des sauts, a vol d'oiseau.

    A vol d'oiseau et non la vraie liaison en trois morceaux : la hauteur de
    celle-ci depend de la matiere, donc de l'ordre, donc d'elle-meme. La
    distance entre les bouts en est le terme dominant et le seul qui ne
    dependent pas du reste.
    """
    total = 0.0
    ou = depart
    for i, retourne in tour:
        a = fins[i] if retourne else debuts[i]
        b = debuts[i] if retourne else fins[i]
        if ou is not None:
            total += float(np.linalg.norm(a - ou))
        ou = b
    return total


def _plus_proche_voisin(debuts, fins, depart, retournable: bool
                        ) -> list[tuple[int, bool]]:
    """Premier ordre : a chaque etape, la passe dont un bout est le plus pres."""
    n = len(debuts)
    reste = set(range(n))
    tour: list[tuple[int, bool]] = []
    ou = depart
    while reste:
        if ou is None:
            i = min(reste)
            tour.append((i, False))
            reste.discard(i)
            ou = fins[i]
            continue
        meilleur, cout = None, np.inf
        for i in reste:
            d0 = float(np.linalg.norm(debuts[i] - ou))
            if d0 < cout:
                meilleur, cout = (i, False), d0
            if retournable:
                d1 = float(np.linalg.norm(fins[i] - ou))
                if d1 < cout:
                    meilleur, cout = (i, True), d1
        tour.append(meilleur)
        reste.discard(meilleur[0])
        ou = debuts[meilleur[0]] if meilleur[1] else fins[meilleur[0]]
    return tour


def _deux_opt(tour, debuts, fins, depart, retournable: bool,
              n_passes: int = PASSES_2OPT) -> list[tuple[int, bool]]:
    """2-opt : on renverse un morceau du tour tant que cela raccourcit.

    Renverser un morceau RETOURNE aussi chaque passe qu'il contient : parcourir
    un bout de chemin a l'envers, c'est entrer dans chaque passe par son autre
    bout. L'oublier donnerait un cout calcule sur un tour qui n'est pas celui
    qu'on emettrait — et le gain annonce serait faux.

    Quand le retournement est interdit (balayage unidirectionnel), on se
    contente de deplacer des passes sans changer leur sens : c'est moins
    efficace, et c'est le prix d'un sens de coupe constant.
    """
    n = len(tour)
    meilleur = list(tour)
    cout = _cout(meilleur, debuts, fins, depart)
    for _ in range(n_passes):
        ameliore = False
        for i in range(n - 1):
            for j in range(i + 1, n):
                if retournable:
                    bout = [(k, not r) for k, r in meilleur[i:j + 1]][::-1]
                else:
                    # Sans retournement, un 2-opt classique produirait des
                    # passes a l'envers : on essaie seulement de DEPLACER la
                    # passe j juste avant i.
                    if j == i + 1:
                        continue
                    bout = [meilleur[j]] + meilleur[i:j]
                essai = meilleur[:i] + bout + meilleur[j + 1:]
                c = _cout(essai, debuts, fins, depart)
                if c < cout - 1e-9:
                    meilleur, cout, ameliore = essai, c, True
        if not ameliore:
            break
    return meilleur


def ordonner(resultat, *, retournable: bool | None = None,
             n_passes: int = PASSES_2OPT) -> GainOrdre:
    """Reordonne les passes de chaque couche, EN PLACE, et rend ce que ça gagne.

    ``retournable`` autorise a parcourir une passe dans l'autre sens. Par
    defaut il suit le balayage du tranchage : vrai en zigzag, ou l'alternance
    est deja dans le contrat, faux en unidirectionnel, ou le sens de coupe est
    precisement ce qu'on a choisi de garder constant.

    Rendu : la longueur des sauts a vol d'oiseau, avant et apres. Ce n'est pas
    la longueur des vraies liaisons — celle-la depend de la hauteur, donc de la
    matiere, donc de l'ordre lui-meme — mais c'est le terme qu'on optimise.
    """
    from .slicer import BALAYAGE_ALTERNE

    if retournable is None:
        retournable = getattr(resultat, "balayage", BALAYAGE_ALTERNE) == \
            BALAYAGE_ALTERNE

    avant = apres = 0.0
    n_passes_total = 0
    ou_avant = ou_apres = None
    for couche in resultat.layers:
        polys = list(couche.polylines)
        n_passes_total += len(polys)
        if not polys:
            continue
        debuts, fins = _bouts(polys)
        ordre_initial = [(i, False) for i in range(len(polys))]
        avant += _cout(ordre_initial, debuts, fins, ou_avant)
        ou_avant = fins[-1]

        if len(polys) < MINIMUM:
            apres += _cout(ordre_initial, debuts, fins, ou_apres)
            ou_apres = fins[-1]
            continue

        tour = _plus_proche_voisin(debuts, fins, ou_apres, retournable)
        tour = _deux_opt(tour, debuts, fins, ou_apres, retournable, n_passes)
        # L'ordre d'origine est evalue lui aussi : on ne le quitte que pour
        # plus court. C'est ce qui garantit que ce module ne peut pas rendre
        # un parcours pire.
        if _cout(ordre_initial, debuts, fins, ou_apres) <= _cout(
                tour, debuts, fins, ou_apres):
            tour = ordre_initial
        couche.polylines = [np.asarray(polys[i])[::-1] if r
                            else np.asarray(polys[i]) for i, r in tour]
        d2, f2 = _bouts(couche.polylines)
        apres += _cout([(i, False) for i in range(len(tour))], d2, f2, ou_apres)
        ou_apres = f2[-1]

    return GainOrdre(len(resultat.layers), n_passes_total, avant, apres)
