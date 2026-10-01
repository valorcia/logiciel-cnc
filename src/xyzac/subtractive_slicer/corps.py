"""Le CORPS de l'outil contre la MATIERE, le long du chemin.

Le dernier trou de verification du chemin, et le plus difficile a poser
======================================================================

Trois gardes existaient deja, et aucun ne repondait a cette question :

  - ``decider_creux`` verifie une orientation sur quelques dizaines de points
    de BORD du creux, contre la piece finie et le brut initial ;
  - le trancheur garantit qu'on ne gouge pas la matiere PROTEGEE ;
  - ``gamme.verifier_le_parcours`` passe toutes les poses au garde MACHINE.

Reste : le porte-outil, la tige, le col, le nez de broche — contre la matiere
qui est effectivement la a cet instant.

**Pourquoi « a cet instant » n'est pas une precaution de style.** Une poche se
vide couche par couche. A la couche 8, le porte-outil est a l'endroit meme ou
se trouvait du brut avant la couche 1. Verifier contre le brut INITIAL
refuserait tout usinage profond ; verifier contre la piece FINIE autoriserait
un porte-outil qui traverse 20 mm de brut encore present. Les deux reponses
sont fausses, et dans les deux sens.

La matiere est donc suivie au fur et a mesure, exactement comme
``abaisser_les_liaisons`` le fait deja pour choisir la hauteur d'un saut :
chaque passe coupante est retiree d'une copie avant que la suite ne soit
testee. Reutiliser cette discipline-la plutot que d'en ecrire une autre est ce
qui garantit que les deux repondent la meme chose.

**Qui a le droit d'etre dans la matiere.** L'arete de coupe, evidemment : c'est
son travail. Et le corps de goujure, qui voyage dans le canal que l'arete vient
d'ouvrir — il est coaxial et au meme diametre nominal, donc la ou le bec est
passe, il passe. C'est ``ROLES_DANS_LA_COUPE``, et c'est la MEME constante que
celle qui decide ce que l'enlevement de matiere retire. En avoir deux est la
facon dont elles finissent par ne plus dire la meme chose.

**Grossier d'abord, precis seulement si besoin.** Un balayage par tronçon de
chemin suffit a repondre « propre ou pas ». Localiser la faute — quelle pose,
quel organe — coûte un balayage par pose, et n'a d'interet que s'il y a une
faute. Le cas normal reste donc au prix du cas normal.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

import numpy as np

from ..stock_engine.material import ROLES_DANS_LA_COUPE, MaterialState

#: Nom lisible de chaque organe, pour une phrase qu'un operateur peut suivre.
NOM_ORGANE = {
    "neck": "le col de l'outil",
    "shank": "la tige de l'outil",
    "holder": "le porte-outil",
    "spindle_nose": "le nez de broche",
    "flute": "le corps de goujure",
    "cutting": "l'arête de coupe",
}

#: Ce qu'on change quand un organe touche. Un refus qui ne dit pas quoi faire
#: n'est qu'un refus.
REMEDE = {
    "neck": "allonger le col, ou prendre un outil à col réduit",
    "shank": "sortir l'outil davantage de la pince, ou réduire la profondeur",
    "holder": "sortir l'outil davantage de la pince, ou prendre un porte-outil "
              "plus élancé",
    "spindle_nose": "sortir l'outil davantage, ou basculer le berceau pour "
                    "attaquer de plus loin",
}


@dataclass
class DefautCorps:
    """Une faute, localisee : ou, quel organe, et combien de matiere."""

    pose: int
    organe: str
    point: tuple[float, float, float]
    n_voxels: int

    def __str__(self) -> str:
        nom = NOM_ORGANE.get(self.organe, self.organe)
        return (f"pose {self.pose} : {nom} entre dans {self.n_voxels} voxels "
                f"de matière, en ({self.point[0]:.1f}, {self.point[1]:.1f}, "
                f"{self.point[2]:.1f})")


@dataclass
class VerificationCorps:
    """Ce que le corps de l'outil a rencontre sur tout le chemin."""

    n_poses: int = 0
    n_poses_testees: int = 0
    n_troncons: int = 0
    #: Tronçons que le test grossier a signales et qu'il a fallu reprendre
    #: pose par pose. Un chiffre a regarder : s'il monte, le filtre grossier
    #: ne filtre plus grand-chose.
    n_fins: int = 0
    defauts: list[DefautCorps] = field(default_factory=list)
    #: Vrai si la verification a pu etre faite. Faux = on ne sait pas, et le
    #: dire est le seul choix honnete.
    faite: bool = True

    @property
    def ok(self) -> bool:
        return self.faite and not self.defauts

    def consigne(self) -> str:
        if not self.faite:
            return ("corps de l'outil NON VÉRIFIÉ contre la pièce : aucun état "
                    "de matière fourni.")
        if self.ok:
            # ``n_fins`` est dit quand il n'est pas nul : il signale les
            # tronçons que le test grossier a cru fautifs et que la marche
            # chronologique a innocentes. C'est exactement la ou le suivi de
            # matiere a servi — et si ce nombre devient grand, le filtre
            # grossier ne filtre plus grand-chose.
            repris = (f", dont {self.n_fins} repris pose par pose"
                      if self.n_fins else "")
            return (f"corps de l'outil dégagé sur {self.n_poses_testees} "
                    f"positions intermédiaires ({self.n_poses} poses, "
                    f"{self.n_troncons} tronçons{repris}), matière suivie au "
                    "fur et à mesure.")
        organes = sorted({d.organe for d in self.defauts})
        remedes = " ; ".join(REMEDE.get(o, "") for o in organes if REMEDE.get(o))
        return (f"parcours REFUSÉ : {len(self.defauts)} position(s) où le corps "
                f"de l'outil entre dans la matière — "
                + " / ".join(NOM_ORGANE.get(o, o) for o in organes)
                + (f". À changer : {remedes}." if remedes else ".")
                + " Première : " + str(self.defauts[0]))


def roles_du_corps(outil) -> frozenset[str]:
    """Les tronçons qui n'ont PAS le droit de toucher la matiere."""
    return frozenset(s.role.value for s in outil.segments
                     if s.role.value not in ROLES_DANS_LA_COUPE)


def _sonde(etat: MaterialState) -> MaterialState:
    """Copie ou TOUT est enlevable : on veut savoir ce que l'outil toucherait.

    La protection sert a interdire d'enlever la piece ; ici on ne retire rien
    pour de bon, on mesure un contact. Laisser la protection en place rendrait
    la piece finie invisible au test — c'est-a-dire exactement la matiere qu'il
    est le plus grave de percuter.
    """
    return MaterialState(etat.grid, etat.remaining.copy(),
                         np.zeros_like(etat.protected))


def _densifier(sommets: np.ndarray, pas: float):
    """Polyligne densifiee plus finement que la grille.

    Sans cela, un porte-outil pourrait traverser un mur entre deux poses et le
    tronçon serait declare libre. Meme raison que dans ``liaisons``, et meme
    pas.

    Rend AUSSI, pour chaque echantillon, l'indice du sommet d'origine dont il
    descend. Sans cette correspondance, une faute serait signalee a un rang qui
    n'existe pas dans le parcours de l'utilisateur — un numero de pose plus
    grand que le nombre de poses, ce qui etait le cas dans la premiere version
    de ce module.
    """
    S = np.asarray(sommets, dtype=np.float64).reshape(-1, 3)
    if len(S) < 2:
        return S, np.zeros(len(S), dtype=np.int64)
    bouts, source = [S[:1]], [np.zeros(1, dtype=np.int64)]
    for k, (a, b) in enumerate(zip(S[:-1], S[1:])):
        n = max(2, int(np.ceil(float(np.linalg.norm(b - a)) / pas)) + 1)
        bouts.append(a + (b - a) * np.linspace(0.0, 1.0, n)[1:, None])
        source.append(np.full(n - 1, k + 1, dtype=np.int64))
    return np.vstack(bouts), np.concatenate(source)


def _troncons(rapide: np.ndarray):
    """Decoupe le chemin en tronçons homogenes : coupe, liaison, coupe..."""
    R = np.asarray(rapide, dtype=bool).reshape(-1)
    if not len(R):
        return []
    bords = np.flatnonzero(np.diff(R)) + 1
    debuts = np.concatenate([[0], bords])
    fins = np.concatenate([bords, [len(R)]])
    return [(int(a), int(b), bool(R[a])) for a, b in zip(debuts, fins)]


def _marche_fine(etat: MaterialState, poses: np.ndarray, source: np.ndarray,
                 d: np.ndarray, outil, roles: frozenset[str], decalage: int,
                 est_rapide: bool, maximum: int) -> list[DefautCorps]:
    """Pose par pose, DANS L'ORDRE, en avancant la matiere a chaque pas.

    **C'est ici qu'est la reponse exacte, et le test grossier n'est qu'un
    filtre.** Un tronçon de coupe continu enleve de la matiere au fur et a
    mesure qu'il avance : tester tout le tronçon contre l'etat de son DEBUT
    reproche au porte-outil une matiere que l'outil a deja sortie quelques
    millimetres plus tot. C'est le sens prudent, donc un bon filtre — mais un
    mauvais verdict, qui refuserait tout puits creuse d'une seule traite.

    La sonde est un tampon reutilise : on y recopie l'etat courant au lieu
    d'allouer une grille par pose. Sur un parcours de quelques milliers de
    poses, c'est la difference entre quelques dixiemes de seconde et plusieurs
    secondes de ramasse-miettes.
    """
    defauts: list[DefautCorps] = []
    sonde = _sonde(etat)
    for i, p in enumerate(poses):
        np.copyto(sonde.remaining, etat.remaining)
        pose = p.reshape(1, 3)
        axe = d.reshape(1, 3)
        if sonde.remove_tool_sweep(pose, axe, outil, roles=roles) > 0:
            # On ne renomme l'organe qu'ici : c'est le seul endroit ou la
            # question « lequel » se pose vraiment.
            for role in sorted(roles):
                np.copyto(sonde.remaining, etat.remaining)
                n = sonde.remove_tool_sweep(pose, axe, outil,
                                            roles=frozenset({role}))
                if n > 0:
                    rang = decalage + int(source[i])
                    # Plusieurs echantillons intermediaires retombent sur la
                    # meme pose du parcours : la signaler trois fois donnerait
                    # l'impression de trois fautes la ou il y en a une.
                    if not defauts or defauts[-1].pose != rang:
                        defauts.append(DefautCorps(
                            pose=rang, organe=role,
                            point=(float(p[0]), float(p[1]), float(p[2])),
                            n_voxels=int(n)))
                    break
            if len(defauts) >= maximum:
                return defauts
        if not est_rapide:
            etat.remove_tool_sweep(pose, axe, outil)
    return defauts


def verifier_le_corps(points, rapide, material, outil, direction, *,
                      pas_mm: float | None = None,
                      maximum: int = 3,
                      rendre_etat: bool = False):
    """Le corps de l'outil touche-t-il la matiere, quelque part sur le chemin ?

    ``material`` est l'etat au DEBUT de l'operation. Il n'est pas modifie :
    le suivi se fait sur une copie.

    ``maximum`` borne le nombre de fautes localisees. Au-dela on sait deja que
    le parcours est refuse, et continuer a bisecter coûterait sans rien dire de
    plus.

    ``rendre_etat`` rend EN PLUS la matiere telle que ce parcours la laisse.
    C'est ce qui permet d'enchainer les creux dans l'ordre decide : le suivant
    est alors verifie contre ce que le precedent a reellement sorti, et non
    contre le brut du debut. L'etat rendu n'a de sens que si le parcours est
    accepte — un parcours refuse s'arrete a sa faute, et l'etat qu'il rend est
    celui d'un usinage qu'on ne fera pas.
    """
    P = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    R = np.asarray(rapide, dtype=bool).reshape(-1)
    v = VerificationCorps(n_poses=len(P))
    if material is None:
        v.faite = False
        return (v, None) if rendre_etat else v
    if len(P) < 1:
        return (v, copy.deepcopy(material)) if rendre_etat else v

    d = np.asarray(direction, dtype=np.float64)
    d = d / np.linalg.norm(d)
    roles = roles_du_corps(outil)
    etat = copy.deepcopy(material)
    if not roles:
        return (v, etat) if rendre_etat else v

    pas = float(material.grid.pitch) * 0.5 if pas_mm is None else float(pas_mm)

    for deb, fin, est_rapide in _troncons(R):
        # Un tronçon commence a la derniere pose du precedent : sans ce
        # recouvrement, le deplacement qui les relie ne serait teste par
        # personne.
        base = max(0, deb - 1)
        sommets = P[base:fin]
        if len(sommets) == 0:
            continue
        v.n_troncons += 1
        poses, source = _densifier(sommets, pas)
        v.n_poses_testees += len(poses)
        axes = np.tile(d, (len(poses), 1))

        # Grossier d'abord : un seul balayage pour tout le tronçon, contre
        # l'etat de son debut. Il majore — il voit plus de matiere qu'il n'y en
        # a reellement a la fin du tronçon — donc « rien » signifie vraiment
        # rien, et le cas normal reste au prix du cas normal.
        sonde = _sonde(etat)
        if sonde.remove_tool_sweep(poses, axes, outil, roles=roles) > 0:
            # Quelque chose a ete vu : il faut maintenant la reponse EXACTE,
            # c'est-a-dire chronologique. Elle avance la matiere pose par pose,
            # et peut tres bien conclure que tout va bien.
            v.n_fins += 1
            v.defauts.extend(_marche_fine(
                etat, poses, source, d, outil, roles, base, est_rapide,
                maximum - len(v.defauts)))
            if len(v.defauts) >= maximum:
                return (v, etat) if rendre_etat else v
        elif not est_rapide:
            etat.remove_tool_sweep(P[deb:fin], np.tile(d, (fin - deb, 1)), outil)

    return (v, etat) if rendre_etat else v
