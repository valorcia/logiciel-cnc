"""Les conditions a remplir avant qu'un programme puisse partir a la machine.

**Pourquoi un module a part, et pas quelques ``if`` dans le depot.** Les memes
conditions doivent etre lues a deux endroits qui n'ont rien a voir : le depot
(``linuxcnc_gateway.deposit``), qui les fait respecter en refusant, et
l'interface de l'atelier, qui doit pouvoir dire a l'operateur CE QUI MANQUE
avant qu'il appuie. Ecrites deux fois, elles auraient diverge — et la copie qui
aurait diverge serait celle qu'on lit a l'ecran, c'est-a-dire celle sur
laquelle quelqu'un se serait fie.

Ce module ne touche aucune machine, n'ouvre aucun port, n'importe pas
``linuxcnc_gateway``. Il repond a une question et rend des donnees. C'est ce
qui permet a l'atelier de s'en servir sans franchir la frontiere d'execution :
la dependance va de la passerelle vers ces regles, jamais de l'interface vers
la passerelle.

Les conditions elles-memes viennent du premier jalon et ne sont pas des
reglages. Voir ``linuxcnc_gateway.deposit`` pour le motif de chacune.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Destinations possibles d'un programme. Les exigences n'y sont pas les memes,
#: et c'est deliberé : exiger du simulateur ce qu'on exige du materiel rendrait
#: la qualification impossible a atteindre, puisqu'on ne pourrait rien essayer.
SIMULATION = "simulation"
MATERIEL = "materiel"


@dataclass(frozen=True)
class Exigence:
    """Une condition, ce qu'elle vaut, et ce qu'il faut faire si elle manque.

    ``action`` n'est pas decoratif : une condition non remplie qui ne dit pas
    quoi faire laisse l'operateur devant un constat sans suite, ce qui est la
    seule chose qu'un refus ne doit jamais faire.
    """

    cle: str
    titre: str
    action: str
    satisfaite: bool
    bloquante: bool
    refus: str = ""

    @property
    def bloque(self) -> bool:
        return self.bloquante and not self.satisfaite


def exigences(*, approbation: bool, calibration, destination: str = MATERIEL
              ) -> list[Exigence]:
    """Les quatre conditions, evaluees dans l'ordre ou le depot les verifie.

    ``calibration`` peut valoir ``None`` : c'est le cas d'une machine qui n'a
    jamais ete calibree, et il ne doit pas produire d'exception mais quatre
    conditions non remplies. Une machine en kit qu'on vient d'assembler est
    exactement dans cet etat, et c'est l'etat qu'il faut savoir decrire.
    """
    if destination not in (SIMULATION, MATERIEL):
        raise ValueError(f"destination inconnue : {destination!r}")

    geom = getattr(calibration, "geometry", None)
    mesuree = bool(getattr(geom, "measured", False))
    complete = bool(getattr(calibration, "geometry_complete", False))
    qualifiee = bool(getattr(calibration, "qualified", False))
    bloquantes = list(getattr(calibration, "steps_blocking", []) or [])[:5]

    return [
        Exigence(
            cle="approbation",
            titre="La gamme doit être approuvée sous le montage courant",
            action="Faire valider la gamme par la machine d'état de sécurité. "
                   "Changer le montage annule l'approbation : c'est voulu, "
                   "la pièce n'est plus au même endroit.",
            satisfaite=bool(approbation), bloquante=True,
            refus="depot refuse : aucune gamme approuvee sous ce montage."),
        Exigence(
            cle="geometrie_mesuree",
            titre="Les pivots A et C doivent être MESURÉS, pas estimés",
            action="Exécuter la calibration d'assemblage. Sur une cinématique "
                   "table/table, une erreur de pivot se retrouve telle "
                   "quelle sur la pièce.",
            satisfaite=mesuree, bloquante=True,
            refus="depot refuse : geometrie machine NON MESUREE. Les pivots A "
                  "et C sont provisoires, et sur une cinematique table/table "
                  "leur erreur se retrouve telle quelle sur la piece. "
                  "Executer assembly_calibration avant de deposer."),
        Exigence(
            cle="geometrie_complete",
            titre="La calibration géométrique doit être complète",
            action=("Terminer les étapes restantes : " + ", ".join(bloquantes)
                    if bloquantes else
                    "Terminer les étapes restantes de la calibration."),
            satisfaite=mesuree and complete, bloquante=True,
            refus="depot refuse : calibration geometrique incomplete"
                  + (f" ({', '.join(bloquantes)})." if bloquantes else ".")),
        Exigence(
            cle="qualification",
            titre="La machine doit être qualifiée sur pièce d'épreuve mesurée",
            action="Usiner la pièce d'épreuve PUIS la mesurer sur un moyen "
                   "indépendant de la machine. C'est la seule condition "
                   "qu'un logiciel ne peut pas remplir seul, et c'est "
                   "voulu.",
            satisfaite=qualifiee, bloquante=(destination == MATERIEL),
            refus="depot MATERIEL refuse : machine non qualifiee. Il manque la "
                  "piece d'epreuve usinee PUIS mesuree sur un moyen "
                  "independant (assembly_calibration, etape "
                  "QUALIFICATION_PART). Deposer en simulation est en revanche "
                  "autorise, et c'est le chemin pour y arriver."),
    ]


def manquantes(**kw) -> list[Exigence]:
    """Les seules conditions qui BLOQUENT la destination demandee."""
    return [e for e in exigences(**kw) if e.bloque]


def peut_deposer(**kw) -> bool:
    return not manquantes(**kw)


#: Ce que le logiciel ne fera jamais, quel que soit l'etat des conditions.
#:
#: Ecrit ici et pas seulement dans l'interface : c'est une regle du projet, pas
#: un choix de presentation, et une regle de projet n'a pas sa place dans une
#: feuille de style.
JAMAIS = ("Ce logiciel ne démarre aucun cycle. Même toutes conditions "
          "remplies, il écrit un fichier programme ; c'est l'opérateur qui "
          "l'ouvre sur la machine et qui appuie, machine devant lui.")
