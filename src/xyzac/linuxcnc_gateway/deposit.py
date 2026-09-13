"""Remise d'un programme a LinuxCNC : depot de fichier, sous conditions.

C'est la seule frontiere d'execution du projet, et elle est deliberement
etroite.

**Ce module ne demarre pas de cycle, et c'est un choix, pas un manque.**
Ecrire un programme dans le repertoire que LinuxCNC lit, puis laisser
l'operateur l'ouvrir et appuyer sur depart cycle, garde un humain dans la
boucle au dernier moment — celui ou l'on regarde la machine avant qu'elle
bouge. Un demarrage a distance depuis ce logiciel supprimerait precisement ce
regard, pour gagner un geste. Le rapport entre ce qu'on gagne et ce qu'on perd
n'est pas favorable, donc ``linuxcncrsh`` n'est pas employe pour lancer quoi
que ce soit.

Deux contraintes independantes imposent par ailleurs la meme architecture, ce
qui est un bon signe :

  - **securite** (ADR-001 / D9) : un seul point de passage, auditable, et aucun
    autre module n'ouvre de port machine ;
  - **licence** (ADR-001 / D10) : LinuxCNC est GPLv2. Un ``import linuxcnc``
    dans notre processus poserait la question de l'oeuvre derivee pour toute
    l'application. Ce qui traverse la frontiere est donc un FICHIER, pas un
    appel de fonction.

Les conditions de depot ne sont pas negociables et ne sont pas des reglages :
elles reprennent une a une les regles posees au premier jalon, et chacune a
son motif ecrit dans le refus.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from .. import production_gate


class Target(str, Enum):
    """Destination d'un programme. Les conditions ne sont pas les memes."""

    SIMULATION = "simulation"
    HARDWARE = "materiel"


class DepositRefused(RuntimeError):
    """Depot refuse. Le message dit toujours QUOI faire, pas seulement non."""


@dataclass
class DepositRecord:
    """Trace d'un depot. Sert de piece justificative, pas de confort."""

    path: Path
    target: str
    setup_hash: str
    calibration_hash: str
    gcode_sha256: str
    when: str
    qualified: bool
    warnings: list[str] = field(default_factory=list)

    def describe(self) -> str:
        lines = [
            f"Programme depose : {self.path}",
            f"  destination   : {self.target}",
            f"  setup         : {self.setup_hash[:16]}",
            f"  calibration   : {self.calibration_hash[:16]}",
            f"  empreinte     : {self.gcode_sha256[:16]}",
            f"  horodatage    : {self.when}",
            f"  machine qualifiee : {'oui' if self.qualified else 'NON'}",
        ]
        for w in self.warnings:
            lines.append(f"  AVERTISSEMENT : {w}")
        lines.append("  Aucun cycle n'a ete demarre : c'est a l'operateur "
                     "d'ouvrir le programme et de lancer, machine devant lui.")
        return "\n".join(lines)


def deposit_program(
    gcode: str,
    directory: str | Path,
    *,
    target: Target | str,
    safety,
    setup_hash: str,
    calibration,
    filename: str = "",
    journal: str | Path | None = None,
) -> DepositRecord:
    """Depose un programme la ou LinuxCNC le lira. Ne lance rien.

    Conditions, verifiees dans cet ordre parce que l'ordre porte du sens :

    1. **porte de securite** : le programme doit venir d'une gamme approuvee
       sous le setup courant. Si l'etat ne l'autorise pas, rien d'autre n'a
       d'importance ;
    2. **geometrie mesuree** : les pivots A et C ne peuvent pas etre
       provisoires. Sur une cinematique table/table, l'erreur de pivot se
       propage directement a la piece ;
    3. **concordance des dossiers** : la calibration deposee doit etre celle
       sous laquelle l'approbation a ete donnee. Approuver sous l'une et
       deposer sous l'autre annule le sens de l'approbation ;
    4. **destination materielle** : elle exige en plus une machine QUALIFIEE
       sur piece d'epreuve mesuree. C'est la seule condition que le logiciel ne
       peut pas satisfaire seul, et c'est voulu : personne ne devrait pouvoir
       lancer une production depuis un logiciel qui n'a jamais vu une piece
       sortir de cette machine.

    Le depot en simulation, lui, est ouvert des que 1 a 3 sont remplies : y
    mettre les memes exigences qu'au materiel empecherait de verifier la
    chaine, ce qui rendrait la qualification impossible a atteindre.
    """
    tgt = target.value if isinstance(target, Target) else str(target)
    if tgt not in (Target.SIMULATION.value, Target.HARDWARE.value):
        raise ValueError(f"destination inconnue : {tgt!r}")

    # 1. porte de securite, avant tout le reste
    safety.require_postprocess(setup_hash)

    # 2 a 4 : les memes conditions que celles que l'atelier AFFICHE.
    #
    # Elles sont evaluees par ``production_gate`` et non re-ecrites ici. Ecrites
    # deux fois, elles auraient fini par diverger, et la copie divergente aurait
    # ete celle qu'on lit a l'ecran — donc celle sur laquelle quelqu'un se
    # serait fie. La porte de securite (1) reste au-dessus : elle porte sur
    # l'etat courant, pas sur un dossier.
    for exigence in production_gate.exigences(
            approbation=True, calibration=calibration, destination=tgt):
        if exigence.cle != "approbation" and exigence.bloque:
            raise DepositRefused(exigence.refus)

    ch = calibration.calibration_hash()

    warnings: list[str] = []
    qualified = bool(getattr(calibration, "qualified", False))
    if tgt == Target.SIMULATION.value:
        warnings.append(
            "destination SIMULATION : ce programme n'est pas destine a une "
            "machine. Le deposer dans la configuration d'une machine reelle "
            "serait un contournement de la condition de qualification.")
    if not qualified:
        warnings.append(
            "machine NON QUALIFIEE : aucune tolerance ne peut etre annoncee "
            "sur les pieces produites.")

    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(gcode.encode("utf-8")).hexdigest()
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    name = filename or f"prog_{setup_hash[:8]}_{digest[:8]}.ngc"
    path = d / name

    # L'empreinte du programme est ecrite DANS le programme : un fichier
    # recupere sans son journal doit pouvoir etre rattache a son depot.
    entete = (f"(DEPOSE {when} destination {tgt})\n"
              f"(setup {setup_hash})\n"
              f"(calibration {ch})\n"
              f"(empreinte du contenu {digest})\n")
    path.write_text(entete + gcode, encoding="utf-8")

    rec = DepositRecord(path=path, target=tgt, setup_hash=setup_hash,
                        calibration_hash=ch, gcode_sha256=digest, when=when,
                        qualified=qualified, warnings=warnings)

    if journal is not None:
        jp = Path(journal)
        jp.parent.mkdir(parents=True, exist_ok=True)
        with jp.open("a", encoding="utf-8") as fh:
            fh.write(f"{when}\t{tgt}\t{setup_hash[:16]}\t{ch[:16]}\t"
                     f"{digest[:16]}\t{path.name}\n")
    return rec


def start_cycle(*args, **kw):
    """DELIBEREMENT non implemente : demarrer un cycle depuis ce logiciel.

    Ce n'est pas un manque a combler plus tard, c'est une decision.

    Deposer un fichier puis laisser l'operateur l'ouvrir et appuyer sur depart
    cycle garde un humain dans la boucle au dernier moment — celui ou l'on
    regarde la machine avant qu'elle bouge. Un demarrage a distance supprime ce
    regard pour economiser un geste, et sur une machine 5 axes en kit dont le
    bridage vient d'etre refait a la main, ce regard est la derniere barriere
    qui ne depende d'aucun calcul.

    La regle du projet dit que l'IA ne pilote jamais les moteurs. Un
    declenchement de cycle est un pilotage, meme s'il passe par LinuxCNC.
    """
    raise NotImplementedError(
        "demarrage de cycle non implemente, et il ne le sera pas ici : le "
        "programme est depose, l'operateur l'ouvre et le lance, machine devant "
        "lui. Voir le docstring pour le motif.")
