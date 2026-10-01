"""De la decision par creux a une GAMME postable.

Ce qui manquait, et ce que ce module ne comble pas tout seul
============================================================

La chaine existait aux deux bouts et nulle part au milieu :

  - ``creux.py`` decide QUEL outil, DEPUIS QUELLE orientation, et produit un
    ``ParcoursCreux`` : des positions de bec et un couple (A, C) fixe ;
  - ``postprocessor_linuxcnc.emit`` sait ecrire un ``ProcessPlan`` compense,
    derriere les portes de securite et contre une geometrie MESUREE.

Entre les deux, rien. Un ``ParcoursCreux`` n'est pas une ``Operation``, et le
convertir n'est pas une question de recopie de champs — c'est le moment ou
trois verifications deviennent obligatoires.

**1. Le parcours lui-meme n'avait jamais ete verifie en collision.**
``decider_creux`` verifie l'orientation sur les POINTS DE BORD du creux, et le
trancheur garantit qu'on ne gouge pas la piece protegee. Aucun des deux ne dit
que l'outil, a chacune des mille positions du chemin, degage les organes de la
machine. C'est la verification que ce module impose avant qu'une operation
existe — et elle refuse, elle ne corrige pas.

**2. Le couple (A, C) doit traverser la chaine sans etre re-devine.**
``ik_best(d)`` repond a « quel (A, C) donne cet axe outil ». Ce n'est pas la
question. La question est « quel (A, C) le controle de collision a-t-il
approuve », et les deux branches de l'inverse — (a, c) et (-a, c+180) — donnent
le MEME axe outil dans le repere piece en posant la piece de deux facons
differentes dans le berceau. Tant que les butees n'en laissent qu'une, les deux
reponses coincident ; le jour ou elles en laissent deux, le post-processeur
emettrait une posture que personne n'a verifiee. L'operation porte donc son
(A, C), et l'emetteur le RELIT en controlant qu'il redonne bien l'axe demande.

C'est la quinzieme occurrence de la meme famille de defaut : une grandeur
dominee par une autre, lue comme si elle mesurait ce qu'on voulait.

**3. Aucune avance n'est inventee.** Une operation sans recette est refusee ici
comme elle l'est dans l'emetteur.

**4. Le CORPS de l'outil contre la MATIERE.** Porte-outil, tige, col, nez de
broche — contre la matiere qui est effectivement la a cet instant, et non
contre le brut initial (qui refuserait tout usinage profond) ni contre la piece
finie (qui laisserait passer un porte-outil traversant 20 mm de brut). Voir
``subtractive_slicer.corps``. Cette verification exige un etat de matiere ; sans
lui, elle n'est pas faite — et l'operation le DIT, au lieu de laisser croire.

Ce que ce module ne fait toujours pas
-------------------------------------

  - il n'ordonne pas les creux entre eux autrement que dans l'ordre recu, et
    verifie donc chaque creux contre l'etat de matiere INITIAL. C'est le cote
    prudent — il y a plus de matiere au depart qu'apres les creux precedents,
    donc le test peut refuser un peu trop — et c'est volontaire : avancer
    l'etat d'un creux a l'autre figerait un ordre que personne n'a encore
    decide ;
  - il n'emet rien. ``post_process`` reste la seule porte, et
    ``linuxcnc_gateway`` reste verrouille.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..geometry_core.types import normalize
from ..kinematics_solver.solver import KinematicsSolver
from .interfaces import Kinematic, Operation, ProcessPlan, Toolpath

#: Ecart maximal, en degres, entre l'axe outil demande et celui que le couple
#: (A, C) porte reellement. La direction est CONSTRUITE depuis (A, C), donc
#: l'ecart attendu est celui de l'arithmetique flottante ; ce seuil n'absorbe
#: pas une erreur de modele, il attrape une incoherence.
TOLERANCE_AXE_DEG = 1.0e-3


def direction_de(machine, a_deg: float, c_deg: float) -> np.ndarray:
    """L'axe outil, dans le repere piece, pour un couple (A, C) indexe.

    Une seule definition pour toute la chaine. En avoir deux — une dans le
    planificateur, une dans l'emetteur — est precisement la facon dont un
    signe finit par differer sans que personne ne le voie.
    """
    return normalize(np.asarray(machine.tool_axis_in_part(a_deg, c_deg),
                                dtype=np.float64))


@dataclass
class VerificationParcours:
    """Ce que le garde machine a dit de CHAQUE pose du chemin."""

    n_poses: int = 0
    n_hors_course: int = 0
    n_collision: int = 0
    #: Index des premieres poses fautives, pour pouvoir aller les regarder.
    premieres: list[int] = field(default_factory=list)
    a_deg: float = 0.0
    c_deg: float = 0.0

    @property
    def ok(self) -> bool:
        return self.n_poses > 0 and not self.n_hors_course and not self.n_collision

    def consigne(self) -> str:
        """Ce qui bloque, dit a l'operateur, en nommant le levier."""
        if self.n_poses == 0:
            return "parcours vide : rien a usiner."
        if self.ok:
            return (f"{self.n_poses} poses degagees a A = {self.a_deg:.1f}°, "
                    f"C = {self.c_deg:.1f}° — organes machine seulement.")
        bouts = []
        if self.n_hors_course:
            bouts.append(
                f"{self.n_hors_course} poses hors des courses linéaires "
                "(à changer : rapprocher la pièce du centre du plateau, ou "
                "la poser plus bas)")
        if self.n_collision:
            bouts.append(
                f"{self.n_collision} poses où l'outil touche un organe de la "
                "machine (à changer : réduire la longueur sortie de l'outil, "
                "ou recentrer la pièce)")
        return (f"parcours REFUSÉ sur {self.n_poses} poses : " + " ; ".join(bouts)
                + f". Premières fautives : {self.premieres}.")


def verifier_le_parcours(parcours, machine, outil, *,
                         mount_offset=None, work_offset=None,
                         maximum_signale: int = 5) -> VerificationParcours:
    """Passe le garde machine sur TOUTES les positions du chemin.

    ``decider_creux`` a verifie l'orientation sur les points de bord du creux —
    quelques dizaines de points choisis sur la peau de la matiere a sortir. Un
    parcours en compte des milliers, et il descend couche par couche jusqu'au
    fond : rien ne garantit a priori que le nez de broche degage encore au
    dernier niveau, ni qu'une liaison abaissee ne sort pas des courses.

    Le garde travaille en repere MACHINE : chaque position de bec y est donc
    transportee par la cinematique, a (A, C) fixe, avant d'etre testee.
    """
    from ..collision_engine.machine_guard import MachineGuard

    pts = np.asarray(parcours.points, dtype=np.float64).reshape(-1, 3)
    v = VerificationParcours(n_poses=len(pts), a_deg=float(parcours.a_deg),
                             c_deg=float(parcours.c_deg))
    if not len(pts):
        return v

    mount = (np.zeros(3) if mount_offset is None
             else np.asarray(mount_offset, dtype=np.float64))
    wo = (np.zeros(3) if work_offset is None
          else np.asarray(work_offset, dtype=np.float64))

    kin = KinematicsSolver(machine)
    tcps = np.array([kin.part_to_machine_point(p + mount, v.a_deg, v.c_deg) + wo
                     for p in pts])
    ac = np.repeat([[v.a_deg, v.c_deg]], len(pts), axis=0)

    garde = MachineGuard(machine, outil)
    ok, dans_courses = garde.check_many(tcps, ac, return_travel=True)

    v.n_hors_course = int((~dans_courses).sum())
    # Une pose hors course n'est pas testee en collision : la compter deux fois
    # ferait croire a deux defauts la ou il y en a un.
    v.n_collision = int((~ok & dans_courses).sum())
    v.premieres = [int(i) for i in np.flatnonzero(~ok)[:maximum_signale]]
    return v


def freiner_les_descentes(points, rapide, direction, *, epsilon_mm: float = 1.0e-9):
    """Une DESCENTE n'est jamais en rapide tant qu'elle n'est pas prouvee degagee.

    ``abaisser_les_liaisons`` remplace chaque liaison par quatre sommets :
    monter, traverser, redescendre. Ce qui est demontre est le COULOIR
    HORIZONTAL — la hauteur retenue degage l'outil au-dessus de toute la
    matiere du couloir. La descente finale, elle, quitte cette hauteur pour
    rejoindre le debut de la passe suivante, c'est-a-dire une position ou il y
    a de la matiere par definition : c'est la qu'on va couper.

    Emettre cette descente en G0 serait un rapide vers le point de contact.
    Le module d'emission le refuse deja pour le premier point d'une operation,
    avec cette phrase : « le defaut prudent est l'avance travail partout ». La
    meme regle vaut ici, et elle vaut pour la meme raison.

    La montee, elle, reste en rapide : remonter le long de l'axe outil depuis
    une position que l'outil occupait deja ne peut rencontrer que le vide qu'il
    vient de laisser.

    Rend le nouveau tableau de drapeaux et le nombre de deplacements ramenes en
    avance travail — un chiffre a dire, pas a taire : c'est du temps de cycle
    perdu, en echange d'une descente qui ne casse pas l'outil.
    """
    P = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    R = np.asarray(rapide, dtype=bool).reshape(-1).copy()
    if len(P) < 2:
        return R, 0
    d = normalize(np.asarray(direction, dtype=np.float64))
    h = P @ d
    descend = np.zeros(len(P), dtype=bool)
    descend[1:] = h[1:] < h[:-1] - epsilon_mm
    a_freiner = R & descend
    R[a_freiner] = False
    return R, int(a_freiner.sum())


def operation_du_creux(parcours, outil, recette, machine, *,
                       op_id: str, notes: str = "",
                       corps=None) -> Operation:
    """Un ``ParcoursCreux`` devient une ``Operation`` indexee 3+2.

    L'axe outil est CONSTANT sur toute l'operation — c'est la definition du
    3+2 — et il est reconstruit depuis (A, C) plutot que recopie d'une normale
    de surface : ce que l'outil doit tenir, c'est l'orientation que le controle
    de collision a approuvee, pas la normale du point sous le bec.

    La recette est obligatoire. Une operation sans avance serait refusee par
    l'emetteur, et la refuser ici evite de batir une gamme entiere pour
    l'apprendre a la derniere ligne.
    """
    pts = np.asarray(parcours.points, dtype=np.float64).reshape(-1, 3)
    if not len(pts):
        raise ValueError(f"{op_id} : parcours vide, il n'y a pas d'operation.")
    if recette is None or not getattr(recette, "feed_mm_min", 0.0) > 0.0:
        raise ValueError(
            f"{op_id} : aucune recette de coupe. Une avance inventee est "
            "exactement ce que ce projet refuse ; passer le resultat de "
            "recipe_profiles.build_recipe.")

    d = direction_de(machine, parcours.a_deg, parcours.c_deg)
    rapide, n_freinees = freiner_les_descentes(pts, parcours.rapide, d)
    chemin = Toolpath(
        points=pts,
        normals=np.repeat(d.reshape(1, 3), len(pts), axis=0),
        is_rapid=rapide,
        label=f"creux {parcours.index}",
    )
    if n_freinees:
        notes = (f"{n_freinees} descentes de liaison ramenées en avance travail "
                 "(leur dégagement n'est pas démontré). " + notes).strip()
    # Ce que le corps de l'outil a subi est dit DANS le fichier, a cote de
    # l'operation. Une verification faite et tue ne protege personne ; une
    # verification non faite et tue est pire.
    if corps is not None:
        notes = (notes + " " + corps.consigne()).strip()
    return Operation(
        op_id=op_id,
        kinematic=Kinematic.MILLING_3PLUS2,
        tool=outil,
        toolpath=chemin,
        spindle_rpm=float(recette.spindle_rpm),
        feed_mm_min=float(recette.feed_mm_min),
        notes=notes,
        ac_impose=(float(parcours.a_deg), float(parcours.c_deg)),
    )


def gamme_des_creux(setup, elements, *, plan_id: str, material=None,
                    mount_offset=None, work_offset=None) -> tuple[ProcessPlan, list]:
    """Assemble la gamme, en REFUSANT tout creux dont le chemin ne degage pas.

    ``elements`` est une suite de ``(parcours, outil, recette)``.

    Deux gardes, et ils ne repondent pas a la meme question :

      - le garde MACHINE, sur toutes les poses : l'outil touche-t-il le
        berceau, une joue, un carter, ou sort-il des courses ;
      - le garde MATIERE (``material`` fourni) : le CORPS de l'outil touche-t-il
        la matiere encore presente a cet instant.

    Sans ``material``, le second n'est pas fait — et chaque operation le dit
    dans le fichier produit, au lieu de laisser croire qu'il l'a ete.

    Rend la gamme ET la liste des verifications, y compris celles qui ont
    echoue : une gamme amputee sans dire de quoi laisserait croire que les
    creux manquants n'existaient pas.
    """
    from ..subtractive_slicer.corps import verifier_le_corps

    if material is None:
        raise ValueError(
            "gamme_des_creux : aucun etat de matiere. Sans lui, le CORPS de "
            "l'outil — porte-outil, tige, nez de broche — ne peut pas etre "
            "verifie contre la piece, et poster un programme dont une des "
            "quatre verifications n'a pas eu lieu reviendrait a la presenter "
            "comme faite. Passer l'etat du debut de l'operation.")
    machine = setup.machine
    # Les decalages viennent du MONTAGE par defaut, et non de zero.
    #
    # L'emetteur ajoute ``setup.mount_offset`` et l'origine piece a chaque
    # pose. Verifier a zero et emettre decale reviendrait a verifier une autre
    # machine que celle qu'on poste — le genre d'ecart qui ne se voit nulle
    # part jusqu'au jour ou il se voit sur la piece.
    if mount_offset is None:
        mount_offset = setup.mount_offset
    if work_offset is None:
        work_offset = setup.work_offset.origin_mm
    ops, verifs = [], []
    for i, (parcours, outil, recette) in enumerate(elements):
        v = verifier_le_parcours(parcours, machine, outil,
                                 mount_offset=mount_offset, work_offset=work_offset)
        corps = verifier_le_corps(
            parcours.points, parcours.rapide, material, outil,
            direction_de(machine, parcours.a_deg, parcours.c_deg))
        verifs.append((parcours.index, v, corps))
        if not v.ok or not corps.ok:
            continue
        ops.append(operation_du_creux(
            parcours, outil, recette, machine,
            op_id=f"creux-{parcours.index}",
            notes=v.consigne(), corps=corps))
    return ProcessPlan(plan_id=plan_id, setup=setup, operations=ops), verifs
