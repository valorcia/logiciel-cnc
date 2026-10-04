"""La cinematique de la machine ENTIERE : delta lineaire + table A/C.

Ce que ce module est, et ce qu'il n'est pas
===========================================

Il n'execute aucun mouvement. Il est la **reference numerique** de ce que le
module de cinematique de LinuxCNC devra calculer le jour ou il existera, et il
sert des aujourd'hui a une chose precise : empecher le generateur de
configuration d'ecrire un fichier qui decrit une AUTRE machine.

Le defaut qu'il met au jour
---------------------------

``linuxcnc_gateway.config`` ecrit ``KINEMATICS = xyzac-trt-kins``. Ce module de
LinuxCNC est exactement la cinematique d'une table/table XYZAC **a portique** :
ses articulations 0, 1, 2 SONT X, Y et Z. Sur un portique, c'est juste.

Sur la delta de ce kit, les articulations 0, 1, 2 sont les trois **chariots**.
Leur course est celle des colonnes — 0 a 300 mm, toutes trois identiques — et
non les demi-courses cartesiennes. Charger la configuration actuelle sur la
machine reelle reviendrait a commander les chariots comme s'ils etaient X, Y
et Z : chaque deplacement serait geometriquement faux, et aucune erreur ne
serait signalee.

La chaine, et pourquoi elle se compose exactement
--------------------------------------------------

La partie ROTATIVE de la machine est inchangee : une table A/C sous une broche
qui ne fait que translater. C'est elle que ``xyzacKinematicsInverse`` traite,
et son resultat est la position CARTESIENNE que la broche doit occuper dans le
repere machine.

La delta n'intervient qu'apres, pour realiser cette position :

    (x, y, z, A, C)  --[inverse TRT]-->  (xm, ym, zm, A, C)
                     --[inverse delta]-> (q0, q1, q2, A, C)

Les deux etages sont independants et se composent sans terme croise, parce que
la plateforme de la delta **translate** sans tourner (paires de bras en
parallelogramme, ADR-012). Un module C n'aurait donc qu'a appeler l'inverse TRT
existant puis la formule des chariots — c'est la seule raison pour laquelle ce
chantier est modeste, et elle merite d'etre verifiee plutot que supposee : les
tests comparent l'etage TRT a la fonction COMPILEE de LinuxCNC
(``tools/verify_kinematics_linuxcnc.py --etage source``).

Ce que ce module ne traite pas
-------------------------------

  - la **raideur** et les singularites de bras, qui demandent des mesures ;
  - les **organes** de la delta — colonnes, anneau, bras balayes — qui ne sont
    aucun volume de collision a ce jour ;
  - le **signe** des axes sur la machine reelle, qu'aucun calcul n'etablit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

#: Tolerance de l'aller-retour direct/inverse, en mm. C'est le residu de
#: l'arithmetique flottante sur une chaine de cosinus et d'une racine carree,
#: pas une marge de modele : la depasser signalerait une incoherence, pas une
#: imprecision.
TOLERANCE_ALLER_RETOUR_MM = 1.0e-9


#: Position angulaire des colonnes que ``lineardeltakins`` de LinuxCNC IMPOSE.
#:
#: Son en-tete le dit : « Tower 0 is at (0,R). (note: this is not at zero
#: radians!) ». Les trois colonnes sont donc a 90, 210 et 330 degres, et le
#: module n'expose que deux broches HAL — ``R`` et ``L``. L'orientation n'est
#: PAS reglable.
ANGLES_LINEARDELTAKINS = (90.0, 210.0, 330.0)

#: Tolerance angulaire sous laquelle deux dispositions sont la meme.
TOLERANCE_COLONNE_DEG = 1.0e-6


def accord_avec_lineardeltakins(delta) -> str:
    """Le module standard de LinuxCNC peut-il decrire ce chassis ?

    **Le defaut que cette fonction rend visible, et il vaut 20 mm.** Ce projet
    place ses colonnes a 0 / 120 / 240 degres ; ``lineardeltakins`` les place a
    90 / 210 / 330 et n'offre aucun reglage. Sur les cotes du kit — R = 110,
    L = 250 — les deux calculs de chariot different de **jusqu'a 20 mm**, et
    aucun des deux ne se plaint : chacun est juste pour SA disposition.

    Mesure, et non estimation : ``tools/delta_bench.c`` compile la cinematique
    de LinuxCNC depuis sa source et l'appelle. Avec les colonnes a 90/210/330,
    les deux s'accordent a 2,8e-14 mm.

    Laquelle a raison est une question PHYSIQUE — ou sont les colonnes sur le
    chassis — a laquelle seule la machine repond. La fiche porte desormais la
    cote ``delta_colonne_0_deg`` pour que la reponse soit ecrite quelque part
    plutot que supposee des deux cotes a la fois.

    Rend la chaine vide quand l'accord est possible, et le motif sinon.
    """
    angles = tuple(float(a) % 360.0 for a in delta.angles_deg)
    attendu = tuple(float(a) % 360.0 for a in ANGLES_LINEARDELTAKINS)
    if all(abs(((a - b + 180.0) % 360.0) - 180.0) <= TOLERANCE_COLONNE_DEG
           for a, b in zip(sorted(angles), sorted(attendu))):
        return ""
    return (f"colonnes a {', '.join(f'{a:.0f}' for a in angles)} degres ; "
            f"lineardeltakins impose "
            f"{', '.join(f'{a:.0f}' for a in attendu)} et n'offre aucun "
            "reglage. L'ecart atteint 20 mm sur les cotes du kit, sans qu'aucun "
            "controle ne s'en apercoive")


def inverse_trt(pos, a_deg: float, c_deg: float, *,
                x_rp: float, y_rp: float, z_rp: float,
                dy: float, dz: float, dt: float = 0.0) -> np.ndarray:
    """``xyzacKinematicsInverse`` de LinuxCNC, terme pour terme.

    Recopiee dans l'ordre de la source (``src/emc/kinematics/trtfuncs.c``) pour
    qu'une relecture cote a cote soit possible. Sa fidelite n'est pas supposee :
    ``tools/verify_kinematics_linuxcnc.py --etage source`` compile la fonction
    de LinuxCNC et compare les nombres — 7,1e-15 mm d'ecart sur 56 poses.

    Les noms des parametres sont ceux des broches HAL du module, et non des
    noms inventes ici : c'est par leur correspondance que ce projet s'est deja
    trompe une fois.
    """
    a = math.radians(a_deg)
    c = math.radians(c_deg)
    dz = dz + dt
    px, py, pz = (float(v) for v in pos)
    x = (+ math.cos(c) * (px - x_rp)
         - math.sin(c) * (py - y_rp)
         + x_rp)
    y = (+ math.sin(c) * math.cos(a) * (px - x_rp)
         + math.cos(c) * math.cos(a) * (py - y_rp)
         - math.sin(a) * (pz - z_rp)
         - math.cos(a) * dy
         + math.sin(a) * dz
         + dy
         + y_rp)
    z = (+ math.sin(c) * math.sin(a) * (px - x_rp)
         + math.cos(c) * math.sin(a) * (py - y_rp)
         + math.cos(a) * (pz - z_rp)
         - math.sin(a) * dy
         - math.cos(a) * dz
         + dz
         + z_rp)
    return np.array([x, y, z], dtype=np.float64)


def direct_trt(xyz, a_deg: float, c_deg: float, *,
               x_rp: float, y_rp: float, z_rp: float,
               dy: float, dz: float, dt: float = 0.0) -> np.ndarray:
    """L'inverse de ``inverse_trt`` : du repere machine vers la piece.

    Ecrite comme la composition des rotations lues dans la source, et non
    recopiee d'une seconde fonction : l'aller-retour est ce qui la verifie, et
    un test l'exige a 1e-9 mm sur tout le domaine.
    """
    a = math.radians(a_deg)
    c = math.radians(c_deg)
    dz = dz + dt
    xm, ym, zm = (float(v) for v in xyz)

    # On retire les termes constants, puis on applique la rotation inverse :
    # Rz(c).Rx(a) a l'aller, donc Rx(-a).Rz(-c) au retour.
    u = np.array([xm - x_rp,
                  ym - y_rp - dy + math.cos(a) * dy - math.sin(a) * dz,
                  zm - z_rp - dz + math.sin(a) * dy + math.cos(a) * dz],
                 dtype=np.float64)
    ca, sa, cc, sc = math.cos(a), math.sin(a), math.cos(c), math.sin(c)
    rx_t = np.array([[1.0, 0.0, 0.0], [0.0, ca, sa], [0.0, -sa, ca]])
    rz_t = np.array([[cc, sc, 0.0], [-sc, cc, 0.0], [0.0, 0.0, 1.0]])
    v = rz_t @ (rx_t @ u)
    return v + np.array([x_rp, y_rp, z_rp], dtype=np.float64)


def correspondance_hal(machine) -> dict:
    """Les offsets que ``config.py`` ecrit dans le HAL, depuis le modele.

    Une seule definition pour le generateur de configuration, la verification
    et ce module. En avoir deux est la facon dont elles finissent par ne plus
    dire la meme chose — et c'est precisement sur cette correspondance que ce
    projet s'est deja trompe.
    """
    pa = np.asarray(machine.pivot_a, dtype=np.float64)
    pc = np.asarray(machine.pivot_c, dtype=np.float64)
    return dict(x_rp=float(pc[0]), y_rp=float(pc[1]), z_rp=0.0,
                dy=float(pa[1] - pc[1]), dz=float(pa[2]))


@dataclass(frozen=True)
class Articulations:
    """Ce que les moteurs recoivent : trois chariots et deux rotatifs."""

    q: np.ndarray            #: (3,) positions de chariot, en mm
    a_deg: float
    c_deg: float

    @property
    def joignable(self) -> bool:
        """Les bras joignent-ils ? ``NaN`` = aucune solution, pas une position."""
        return bool(np.all(np.isfinite(self.q)))

    def __str__(self) -> str:
        if not self.joignable:
            return "hors d'atteinte : les bras ne joignent pas"
        return (f"chariots [{self.q[0]:.3f}, {self.q[1]:.3f}, {self.q[2]:.3f}] mm, "
                f"A = {self.a_deg:.3f}°, C = {self.c_deg:.3f}°")


def inverse(machine, pos, a_deg: float, c_deg: float) -> Articulations:
    """De la pose PIECE aux cinq articulations de la machine.

    ``machine`` doit porter un ``delta`` : sans lui, les trois premieres
    articulations SONT les trois axes cartesiens, et composer n'aurait pas de
    sens. On refuse plutot que de rendre la position cartesienne sous un nom
    qui promet des chariots.
    """
    delta = getattr(machine, "delta", None)
    if delta is None:
        raise ValueError(
            "inverse : cette machine n'a pas de structure delta. Ses trois "
            "premieres articulations sont deja X, Y et Z — employer "
            "``inverse_trt`` seul.")
    xyz = inverse_trt(pos, a_deg, c_deg, **correspondance_hal(machine))
    q = np.asarray(delta.chariots(xyz.reshape(1, 3)), dtype=np.float64)[0]
    return Articulations(q=q, a_deg=float(a_deg), c_deg=float(c_deg))


def direct(machine, articulations: Articulations) -> np.ndarray:
    """Des cinq articulations a la pose PIECE. L'exact retour de ``inverse``.

    La partie delta se renverse analytiquement : les trois chariots donnent la
    plateforme par intersection de trois spheres, et ``DeltaLineaire`` ne la
    fournit pas — elle n'en avait pas besoin pour DECIDER. Elle est donc
    resolue ici, et l'aller-retour est ce qui la verifie.
    """
    delta = getattr(machine, "delta", None)
    if delta is None:
        raise ValueError("direct : cette machine n'a pas de structure delta.")
    xyz = plateforme_depuis_chariots(delta, articulations.q)
    return direct_trt(xyz, articulations.a_deg, articulations.c_deg,
                      **correspondance_hal(machine))


def plateforme_depuis_chariots(delta, q) -> np.ndarray:
    """La position de plateforme qui donne ces trois chariots.

    Intersection de trois spheres de rayon ``L`` centrees sur les rotules de
    chariot. En soustrayant deux a deux les equations, les termes quadratiques
    s'annulent et il reste **deux equations lineaires** en (x, y) une fois z
    elimine — mais z n'est pas elimine gratuitement, car il apparait au carre.

    La methode retenue evite ce piege : on resout d'abord (x, y) en fonction de
    z (lineaire), puis on reporte dans une sphere, ce qui donne une equation du
    second degre en z. La racine retenue est celle **sous** les chariots : les
    bras descendent, et l'autre racine decrirait un montage ou ils remontent.
    C'est le meme choix de signe que ``DeltaLineaire.chariots``, et il doit
    l'etre — sinon l'aller-retour ne se refermerait pas.
    """
    q = np.asarray(q, dtype=np.float64).reshape(3)
    th = np.radians(np.asarray(delta.angles_deg, dtype=np.float64))
    d = float(delta.ecart_rayons_mm)
    L = float(delta.longueur_bras_mm)
    cx, cy = d * np.cos(th), d * np.sin(th)

    # (x - cx_i)^2 + (y - cy_i)^2 + (z - q_i)^2 = L^2
    # Difference des lignes i et 0 : les carres de x, y, z disparaissent.
    #   -2(cx_i - cx_0) x - 2(cy_i - cy_0) y - 2(q_i - q_0) z
    #     = (cx_0^2 + cy_0^2 + q_0^2) - (cx_i^2 + cy_i^2 + q_i^2)
    k = cx * cx + cy * cy + q * q
    A = np.empty((2, 2))
    e = np.empty(2)
    f = np.empty(2)
    for j, i in enumerate((1, 2)):
        A[j] = (-2.0 * (cx[i] - cx[0]), -2.0 * (cy[i] - cy[0]))
        e[j] = k[0] - k[i]
        f[j] = 2.0 * (q[i] - q[0])
    # (x, y) = A^-1 (e + f z) = u + v z
    Ainv = np.linalg.inv(A)
    u = Ainv @ e
    v = Ainv @ f

    # Report dans la sphere 0 : equation du second degre en z.
    ax, ay = u[0] - cx[0], u[1] - cy[0]
    aa = v[0] * v[0] + v[1] * v[1] + 1.0
    bb = 2.0 * (ax * v[0] + ay * v[1] - q[0])
    cc = ax * ax + ay * ay + q[0] * q[0] - L * L
    disc = bb * bb - 4.0 * aa * cc
    if disc < 0.0:
        return np.full(3, np.nan)
    r = math.sqrt(disc)
    z = min((-bb + r) / (2.0 * aa), (-bb - r) / (2.0 * aa))
    return np.array([u[0] + v[0] * z, u[1] + v[1] * z, z], dtype=np.float64)


def courses_chariots(machine) -> tuple[float, float]:
    """Les butees que les articulations 0, 1 et 2 portent REELLEMENT.

    Toutes trois identiques : ce sont les memes colonnes. Les demi-courses
    cartesiennes du modele ne sont PAS ces butees — elles decrivent le volume
    atteignable, qui n'est meme pas un pave sur une delta.
    """
    delta = machine.delta
    return float(delta.chariot_min_mm), float(delta.chariot_max_mm)
