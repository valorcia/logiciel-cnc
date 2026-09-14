"""La cinematique DELTA LINEAIRE : trois chariots verticaux, une plateforme.

Ce que cette machine est, et ce qu'elle change
----------------------------------------------
Trois colonnes a 120°, un chariot sur chacune, et six bras a rotules par
paires qui joignent les chariots a une plateforme centrale. Les paires etant
des parallelogrammes, la plateforme ne TOURNE pas : elle translate. Les trois
axes cartesiens X, Y, Z sont donc realises par les trois chariots, et les deux
rotatifs A et C sont sur la TABLE, sous la broche.

La structure « trois translations + table A/C » est exactement celle que ce
projet modelise depuis le debut. Tout ce qui touche a l'ORIENTATION reste donc
valable sans changer une ligne : ``tool_axis_in_part``, les six montages
canoniques, le solveur d'accessibilite, le trancheur, le bridage, la
verification de finition.

Ce qui change est la moitie LINEAIRE, et le changement est profond.

Pourquoi les courses cessent d'etre une boite
---------------------------------------------
Sur un portique, les butees portent sur X, Y et Z eux-memes : le domaine est un
pave, donc convexe, et c'est ce qui rendait ``strategy_planner.travel`` exact
sans reserve. Ici les butees portent sur les positions de CHARIOTS ``q_i``, et
la relation entre ``(x, y, z)`` et ``q_i`` n'est pas lineaire :

    q_i = z + sqrt(L² - a_i² - b_i²)
    avec  a_i = (R - r).cos(θ_i) - x   et   b_i = (R - r).sin(θ_i) - y

``R`` etant le rayon du cercle des rotules de chariot, ``r`` celui des rotules
de plateforme, ``L`` la longueur des bras et ``θ_i`` l'angle de la colonne.

Deux consequences, et la seconde est celle qui sauve tout :

1. Le volume atteignable en cartesien n'est PAS un pave et n'est en general PAS
   convexe. La borne haute ``q_i <= q_max`` s'ecrit ``z <= q_max - s_i(x, y)``
   avec ``s_i`` concave, donc le majorant est CONVEXE : un ensemble defini par
   « z sous une fonction convexe » n'est pas convexe.

2. Mais le long d'un SEGMENT DROIT, tout se calcule exactement — voir
   ``segment_tient``. Rien n'est echantillonne, et le verdict reste exact dans
   les deux sens. C'est la propriete a laquelle ce projet tient le plus, et
   elle survit.

Ce que ce module ne fait pas
---------------------------
Il ne connait ni la RAIDEUR ni les singularites de bras. Une delta perd de la
raideur en bord de volume et quand les bras s'approchent de l'horizontale ;
sur une machine d'USINAGE, ou l'effort de coupe pousse la plateforme, c'est une
question de premiere importance — et elle demande des mesures sur la machine
assemblee, pas une formule. Elle n'est donc pas traitee ici plutot qu'estimee.

Il ne connait pas non plus les organes : colonnes, anneau superieur, bras en
mouvement. Ce sont des obstacles reels — les bras balaient un volume important
— et ils demandent les cotes du chassis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

#: Angles des trois colonnes, en degres. 0 / 120 / 240 : la disposition d'une
#: delta a trois colonnes, et celle qu'on voit sur le chassis.
ANGLES_COLONNES = (0.0, 120.0, 240.0)


@dataclass(frozen=True)
class DeltaLineaire:
    """Les cinq cotes qui decrivent une delta lineaire, et ses butees.

    HYPOTHESE EXPLICITE : les valeurs par defaut sont PROVISOIRES et servent au
    jumeau numerique. Elles doivent etre remplacees par les cotes du chassis
    reel — c'est la meme regle que pour ``default_xyzac_kit`` : une valeur
    nominale de plan n'est pas une valeur mesuree, et sur une machine en kit
    l'ecart entre les deux est la premiere source d'erreur.
    """

    #: Rayon du cercle des rotules de CHARIOT, mm.
    rayon_base_mm: float = 150.0
    #: Rayon du cercle des rotules de PLATEFORME, mm.
    rayon_plateforme_mm: float = 40.0
    #: Longueur des bras (entraxe des rotules), mm.
    longueur_bras_mm: float = 250.0
    #: Course des chariots sur leur rail, mm, dans le repere machine.
    chariot_min_mm: float = 0.0
    chariot_max_mm: float = 300.0
    #: Vitesse maximale d'un chariot, mm/min. C'est ELLE qui est butee, et non
    #: une vitesse cartesienne : voir ``strategy_planner.duree``.
    chariot_max_feed_mm_min: float = 4000.0
    angles_deg: tuple[float, ...] = ANGLES_COLONNES
    #: D'ou viennent ces cotes. Vide = non renseigne, ce qui n'est pas la meme
    #: chose que « nominal ».
    source: str = "cotes PROVISOIRES, non mesurees sur la machine"

    @property
    def ecart_rayons_mm(self) -> float:
        """``R - r`` : la seule combinaison des deux rayons qui intervient.

        Le noter evite de croire qu'il faut connaitre les deux separement pour
        calculer une position — c'est faux, et cela simplifie la mesure sur la
        machine reelle.
        """
        return float(self.rayon_base_mm - self.rayon_plateforme_mm)

    def _ab(self, p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """``a_i`` et ``b_i`` pour chaque colonne, en (N, 3)."""
        P = np.asarray(p, dtype=np.float64).reshape(-1, 3)
        th = np.radians(np.asarray(self.angles_deg, dtype=np.float64))
        d = self.ecart_rayons_mm
        a = d * np.cos(th)[None, :] - P[:, 0:1]
        b = d * np.sin(th)[None, :] - P[:, 1:2]
        return a, b

    def portee(self, p: np.ndarray) -> np.ndarray:
        """``a_i² + b_i²`` pour chaque colonne : ce que les bras doivent couvrir.

        Ne depend PAS de z, et c'est ce qui rend le volume analysable : la
        contrainte de longueur de bras est une condition purement horizontale,
        un disque de rayon ``L`` par colonne. Leur intersection — convexe — est
        l'empreinte atteignable.
        """
        a, b = self._ab(p)
        return a * a + b * b

    def chariots(self, p: np.ndarray) -> np.ndarray:
        """Position des trois chariots pour chaque point, en (N, 3).

        ``NaN`` la ou les bras ne joignent pas : c'est une absence de solution,
        et la marquer vaut mieux que de rendre un nombre qui ressemblerait a
        une position. Un appelant qui compare un NaN obtient False, donc
        « hors course », ce qui est le sens voulu.
        """
        P = np.asarray(p, dtype=np.float64).reshape(-1, 3)
        reste = self.longueur_bras_mm ** 2 - self.portee(P)
        with np.errstate(invalid="ignore"):
            s = np.sqrt(np.where(reste >= 0.0, reste, np.nan))
        # Le chariot est AU-DESSUS de la plateforme : les bras descendent. Le
        # signe + est donc le bon, et l'autre racine decrirait un montage ou
        # les bras remontent — mecaniquement impossible sur ce chassis.
        return P[:, 2:3] + s

    def atteignable(self, p: np.ndarray) -> np.ndarray:
        """Ce point est-il dans le volume de travail ? (N,) booleens."""
        q = self.chariots(p)
        ok = np.isfinite(q).all(axis=1)
        dedans = ((q >= self.chariot_min_mm) & (q <= self.chariot_max_mm))
        return ok & dedans.all(axis=1)

    def depassement(self, p: np.ndarray) -> np.ndarray:
        """De combien chaque chariot sort de sa course, en mm. (N, 3).

        Positif = dehors. ``inf`` quand les bras ne joignent pas : ce n'est pas
        un depassement de quelques millimetres mais une absence de solution, et
        les confondre ferait proposer un decalage la ou aucun ne suffirait.
        """
        q = self.chariots(p)
        hors = np.maximum(np.maximum(self.chariot_min_mm - q,
                                     q - self.chariot_max_mm), 0.0)
        return np.where(np.isfinite(q), hors, np.inf)

    # ---------------------------------------------------------- le segment

    def segment_tient(self, p0, p1, *, colonne: int | None = None) -> bool:
        """Le segment droit [p0, p1] tient-il ENTIEREMENT dans les courses ?

        EXACT, sans echantillonnage — et c'est la propriete a laquelle ce
        projet tient le plus. Elle survit a la cinematique parallele, pour deux
        raisons qui se demontrent :

        * ``a_i(t)² + b_i(t)²`` est une PARABOLE convexe en ``t`` : son maximum
          sur [0, 1] est atteint a une extremite. La contrainte de longueur de
          bras est donc exactement verifiee par les deux bouts.

        * ``q_i(t) = z(t) + sqrt(L² - a_i(t)² - b_i(t)²)`` est CONCAVE en ``t``
          — une affine plus la racine d'une concave positive. Une fonction
          concave atteint son MINIMUM a une extremite : la butee basse est donc
          elle aussi exactement verifiee par les deux bouts.

        * Son MAXIMUM, lui, peut tomber a l'interieur. Mais une concave n'a
          qu'un maximum, et il s'annule ou la derivee s'annule : une equation
          du second degre, resolue ci-dessous. Aucun echantillonnage, aucune
          reserve.

        C'est exactement ce que la geometrie d'un portique donnait gratuitement
        (un pave est convexe) et qu'il faut ici demontrer.
        """
        p0 = np.asarray(p0, dtype=np.float64).reshape(3)
        p1 = np.asarray(p1, dtype=np.float64).reshape(3)
        cols = (range(len(self.angles_deg)) if colonne is None else [colonne])
        for i in cols:
            if not self._colonne_tient(p0, p1, i):
                return False
        return True

    def _colonne_tient(self, p0: np.ndarray, p1: np.ndarray, i: int) -> bool:
        L2 = self.longueur_bras_mm ** 2
        th = math.radians(self.angles_deg[i])
        d = self.ecart_rayons_mm
        cx, cy = d * math.cos(th), d * math.sin(th)

        a0, b0 = cx - p0[0], cy - p0[1]
        a1, b1 = cx - p1[0], cy - p1[1]
        da, db = a1 - a0, b1 - b0
        dz = float(p1[2] - p0[2])

        # u(t) = L² - a(t)² - b(t)² = A - 2Bt - Ct², concave (C >= 0)
        A = L2 - a0 * a0 - b0 * b0
        B = a0 * da + b0 * db
        C = da * da + db * db

        def u(t):
            return A - 2.0 * B * t - C * t * t

        def q(t):
            v = u(t)
            if v < 0.0:
                return None
            return p0[2] + t * dz + math.sqrt(v)

        # 1) les bras joignent-ils aux deux bouts ? (u convexe -> min aux bouts)
        for t in (0.0, 1.0):
            if u(t) < 0.0:
                return False

        # 2) butee BASSE et butee HAUTE aux extremites
        for t in (0.0, 1.0):
            qt = q(t)
            if qt is None or qt < self.chariot_min_mm or qt > self.chariot_max_mm:
                return False

        # 3) le maximum INTERIEUR de q, seul cas que les bouts ne couvrent pas.
        #    q'(t) = dz - (B + Ct)/sqrt(u) = 0  ->  dz.sqrt(u) = B + Ct
        #    Eleve au carre : C(C + dz²)t² + 2B(C + dz²)t + (B² - dz².A) = 0
        if C <= 1e-15 and abs(dz) <= 1e-15:
            return True
        k = C + dz * dz
        aa = C * k
        bb = 2.0 * B * k
        cc = B * B - dz * dz * A
        racines = []
        if abs(aa) <= 1e-15:
            if abs(bb) > 1e-15:
                racines.append(-cc / bb)
        else:
            disc = bb * bb - 4.0 * aa * cc
            if disc >= 0.0:
                r = math.sqrt(disc)
                racines.extend(((-bb + r) / (2.0 * aa), (-bb - r) / (2.0 * aa)))
        for t in racines:
            if not (0.0 < t < 1.0):
                continue
            v = u(t)
            if v <= 0.0:
                continue
            # L'elevation au carre ajoute des solutions : on garde celles ou
            # les deux membres ont le meme signe, sans quoi on refuserait un
            # segment sur un extremum qui n'existe pas.
            if dz * math.sqrt(v) * (B + C * t) < 0.0:
                continue
            qt = q(t)
            if qt is not None and qt > self.chariot_max_mm:
                return False
        return True


def delta_kit_provisoire() -> DeltaLineaire:
    """La delta du kit, avec des cotes PROVISOIRES et declarees comme telles.

    Ces cinq nombres decident du volume de travail, donc de ce que la machine
    peut usiner. Les prendre pour acquis serait exactement la faute que ce
    projet refuse : ils sont ici pour que la chaine se calcule de bout en bout,
    et ils doivent etre remplaces par les cotes du chassis.
    """
    return DeltaLineaire()
