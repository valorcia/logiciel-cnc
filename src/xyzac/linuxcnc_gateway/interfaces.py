"""Passerelle LinuxCNC : LA SEULE frontiere d'execution du projet.

Deux contraintes independantes imposent la meme architecture, ce qui est un bon
signe :

  - **Securite** (ADR-001 / D9) : un seul point de passage vers le mouvement
    reel, auditable, et aucun autre module n'ouvre de port machine.
  - **Licence** (ADR-001 / D10) : LinuxCNC est GPLv2. Un ``import linuxcnc``
    dans notre processus poserait la question de l'oeuvre derivee pour toute
    l'application. On communique donc par PROCESSUS SEPARE et protocole texte
    (``linuxcncrsh``, socket, depot de fichiers G-code) : ce qui traverse la
    frontiere, ce sont des donnees, pas des appels de fonction.

NON IMPLEMENTE au jalon M1, et ne doit pas l'etre avant que les portes amont
soient effectives.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class GatewayState(str, Enum):
    DISCONNECTED = "deconnecte"
    CONNECTED = "connecte"
    ESTOP = "arret_urgence"
    RUNNING = "en_cours"


@dataclass
class MachineStatus:
    state: GatewayState
    position_mm: tuple[float, float, float]
    a_deg: float
    c_deg: float
    spindle_rpm: float
    estop_active: bool
    homed: bool


class LinuxCncGateway:
    """Client hors-processus. Ne fait AUCUN import du module Python GPL de LinuxCNC."""

    def __init__(self, host: str = "127.0.0.1", port: int = 5007):
        self.host, self.port = host, port
        self.state = GatewayState.DISCONNECTED

    def connect(self) -> None:
        raise NotImplementedError(
            "linuxcnc_gateway non implemente au jalon M1 (ADR-001 §6). "
            "Aucune connexion vers un controleur reel n'est autorisee tant que "
            "les portes de securite ne sont pas implementees et testees."
        )

    def status(self) -> MachineStatus:
        raise NotImplementedError("linuxcnc_gateway non implemente au jalon M1")

    def send_program(self, gcode: str, approval_token: str) -> None:
        """L'``approval_token`` est emis par ``safety_state_machine`` et lie au
        hash du setup. Sans lui, aucun programme n'est accepte."""
        raise NotImplementedError("linuxcnc_gateway non implemente au jalon M1")

    def estop_is_hardware(self) -> bool:
        """L'arret d'urgence et les interlocks critiques sont MATERIELS et
        independants du logiciel. Cette methode retourne toujours True : elle
        documente le fait que le logiciel ne peut ni les armer, ni les masquer,
        ni les reinitialiser, et ne doit jamais en dependre pour sa surete."""
        return True
