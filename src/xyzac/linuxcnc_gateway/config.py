"""Generation de la configuration LinuxCNC depuis le modele machine.

Raison d'etre : une configuration LinuxCNC ecrite a la main se desynchronise du
modele au premier changement. Les courses, les vitesses, les jeux et surtout
**les positions des pivots A et C** existent deja dans ``MachineKinematics`` et
dans le dossier de calibration (ADR-007). Les retaper dans un fichier INI, ce
serait garantir qu'un jour les deux divergeront — et sur une cinematique
table/table, une erreur de pivot se propage directement a la piece.

Cette configuration est donc **derivee**, jamais saisie.

**Ce qui a ete verifie, et comment.** Ce module a d'abord ete ecrit sans que
LinuxCNC ait jamais lu sa sortie, sur la conviction qu'il n'etait pas
installable ici. Il l'etait : la version 2.9 a ete compilee depuis sa source
en mode ``uspace`` et la configuration lui a ete donnee a charger. Elle
portait cinq defauts, dont deux silencieux — la correspondance des broches de
pivot etait fausse, et la section [HAL] manquait, donc ce fichier n'etait
jamais charge. La procedure et les resultats sont dans
``docs/validation-linuxcnc.md``.

Les noms de broches ci-dessous sont donc **confirmes contre la 2.9**, et la
semantique des offsets est lue dans ``src/emc/kinematics/trtfuncs.c``. Ce qui
reste a verifier sur la machine de l'utilisateur est le SIGNE, qu'aucune
simulation ne peut etablir, et ``verification_command()`` donne la commande.

Ce que cela implique sur le degre de confiance, section par section :

  - structure INI, courses, vitesses, acceleration : reprises du modele, et
    leur forme est stable depuis des annees dans LinuxCNC ;
  - module de cinematique : LinuxCNC fournit ``xyzac-trt-kins``, qui est
    exactement la cinematique de cette machine — table/table avec berceau A et
    plateau C. C'est une chance, et cela evite d'ecrire un module C ;
  - **noms des broches HAL du module de cinematique** : je ne les garantis pas.
    Ils varient selon la version de LinuxCNC. Le fichier HAL les ecrit donc
    dans un bloc isole, precede de la commande qui permet de les verifier, et
    un nom errone fait ECHOUER le demarrage de LinuxCNC — bruyamment, sans
    mouvement. C'est le bon mode d'echec.

**Le signe des offsets est le point dangereux**, et lui ne provoque aucun
echec : un offset de bon nom et de mauvais signe donne une machine qui bouge,
et qui bouge faux. Il ne peut etre confirme que par l'etape ``AXIS_DIRECTION``
de ``assembly_calibration``, qui exige la machine physique — commander un
deplacement et REGARDER de quel cote la piece part. Aucun calcul ne remplace ce
regard, et ce module ne pretend pas le faire.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..machine_model.machine import CAxisMode, MachineKinematics

#: Module de cinematique de LinuxCNC pour une table/table XYZAC.
#:
#: Berceau A portant un plateau C : exactement la chaine de ce projet. Employer
#: ``trivkins`` a la place ferait ignorer les pivots, donc produirait une piece
#: fausse sur toute pose inclinee — sans qu'aucune erreur ne soit signalee.
KINEMATICS_MODULE = "xyzac-trt-kins"

#: Correspondance articulation -> axe, TELLE QUE LE MODULE L'ETABLIT.
#:
#: Elle n'est pas un choix : ``xyzac-trt-kins`` charge avec
#: ``coordinates=xyzac`` par defaut et annonce lui-meme, au chargement,
#: ``Joint 4 ==> Axis C``. C = articulation **4**, pas 5.
#:
#: Cette table portait 5 pour C, avec un commentaire affirmant que le module
#: « attend la numerotation complete XYZABC ». C'etait faux, et la verification
#: consiste a charger le module et a lire ce qu'il imprime :
#:     halrun -f <(echo 'loadrt xyzac-trt-kins')
#: Le module accepte bien ``coordinates=xyzabc``, qui donnerait C = 5 — mais au
#: prix d'un axe B fictif, donc d'une articulation de plus a declarer, borner
#: et asservir pour rien.
JOINT_AXIS = [("0", "X"), ("1", "Y"), ("2", "Z"), ("3", "A"), ("4", "C")]


@dataclass
class ConfigFiles:
    """Les fichiers produits, et ce qu'on a le droit d'en dire."""

    ini: str
    hal: str
    postgui_hal: str
    tool_table: str
    #: Points a verifier sur la machine avant tout mouvement. Non vide par
    #: construction : il y a toujours au moins le signe des offsets.
    to_verify: list[str] = field(default_factory=list)
    #: Ce qu'aucune mesure n'etablit a ce jour : pivots nominaux, jeux a 0,
    #: qualification absente. Chaque entree est un etat CONSTATE a la
    #: generation, jamais une categorie ecrite d'avance — une configuration
    #: dont la geometrie est mesuree ne doit pas s'annoncer « non calibree »
    #: parce qu'il lui reste la piece d'epreuve a passer.
    provisional: list[str] = field(default_factory=list)

    def write(self, directory: str | Path) -> dict[str, Path]:
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        out = {}
        for name, content in (("xyzac.ini", self.ini), ("xyzac.hal", self.hal),
                              ("postgui.hal", self.postgui_hal),
                              ("tool.tbl", self.tool_table)):
            p = d / name
            p.write_text(content, encoding="utf-8")
            out[name] = p
        return out

    def describe(self) -> str:
        lines = ["Configuration LinuxCNC generee depuis le modele machine."]
        if self.provisional:
            lines.append("  PROVISOIRE — ce qu'aucune mesure n'etablit a "
                         "ce jour :")
            lines += [f"    - {p}" for p in self.provisional]
        lines.append("  A VERIFIER sur la machine avant tout mouvement :")
        lines += [f"    - {v}" for v in self.to_verify]
        lines.append("  Cette configuration n'a PAS ete validee par LinuxCNC "
                     "lors de sa generation.")
        return "\n".join(lines)


def verification_command(directory: str = "config-xyzac") -> str:
    """La commande qui valide reellement la configuration, sur la machine.

    C'est le seul verdict qui compte : LinuxCNC charge la configuration, refuse
    tout nom de broche inconnu, et s'arrete avec un message. Le mode simulation
    n'exige aucun materiel, donc il n'y a aucune raison de sauter cette etape.
    """
    return (f"linuxcnc {directory}/xyzac.ini\n"
            "# puis, dans un autre terminal, pour lister les broches reelles du\n"
            "# module de cinematique et confirmer les noms employes :\n"
            "#   halcmd show pin xyzac")


def _axis_block(name: str, ax, *, is_rotary: bool = False) -> str:
    unit = "deg" if is_rotary else "mm"
    lo = ax.min_deg if is_rotary else ax.min_mm
    hi = ax.max_deg if is_rotary else ax.max_mm
    vel = ax.max_feed_deg_min if is_rotary else ax.max_feed_mm_min
    acc = ax.max_accel_deg_s2 if is_rotary else ax.max_accel_mm_s2
    return (
        f"[AXIS_{name}]\n"
        f"# course mesuree : {lo} a {hi} {unit}\n"
        f"MIN_LIMIT = {lo}\n"
        f"MAX_LIMIT = {hi}\n"
        f"MAX_VELOCITY = {vel / 60.0:.4f}\n"
        f"MAX_ACCELERATION = {acc:.4f}\n"
    )


def _joint_block(joint: str, name: str, ax, *, is_rotary: bool,
                 backlash: float) -> str:
    lo = ax.min_deg if is_rotary else ax.min_mm
    hi = ax.max_deg if is_rotary else ax.max_mm
    vel = (ax.max_feed_deg_min if is_rotary else ax.max_feed_mm_min) / 60.0
    acc = ax.max_accel_deg_s2 if is_rotary else ax.max_accel_mm_s2
    # Limites d'articulation legerement au-dela des limites d'axe : LinuxCNC
    # veut pouvoir atteindre la limite d'axe sans buter sur celle de
    # l'articulation, sinon une position licite devient inatteignable.
    marge = 0.5 if not is_rotary else 1.0
    return (
        f"[JOINT_{joint}]\n"
        f"TYPE = {'ANGULAR' if is_rotary else 'LINEAR'}\n"
        f"MIN_LIMIT = {lo - marge}\n"
        f"MAX_LIMIT = {hi + marge}\n"
        f"MAX_VELOCITY = {vel:.4f}\n"
        f"MAX_ACCELERATION = {acc:.4f}\n"
        f"BACKLASH = {backlash}\n"
        f"FERROR = {5.0 if is_rotary else 1.0}\n"
        f"MIN_FERROR = {1.0 if is_rotary else 0.25}\n"
        # HOME et HOME_SEQUENCE suffisent a une prise d'origine SUR PLACE, qui
        # est la seule honnete ici : elle ne commande aucun mouvement et se
        # contente de declarer que la position courante vaut zero.
        #
        # Ce qui reste absent est la RECHERCHE d'origine sur capteur
        # (HOME_SEARCH_VEL, HOME_LATCH_VEL, HOME_OFFSET), et c'est elle qui
        # depend du cablage. Le commentaire precedent disait « prise d'origine
        # NON renseignee » juste sous deux lignes qui la renseignaient : une
        # phrase fausse posee sur les valeurs qu'elle pretendait absentes.
        f"HOME = 0.0\n"
        f"HOME_SEQUENCE = {joint}\n"
        f"# RECHERCHE d'origine sur capteur NON renseignee (HOME_SEARCH_VEL,\n"
        f"# HOME_LATCH_VEL, HOME_OFFSET absents) : elle depend du cablage\n"
        f"# reel, que seule l'etape WIRING_TEST de assembly_calibration peut\n"
        f"# etablir. La renseigner au hasard ferait partir un axe dans la\n"
        f"# mauvaise direction a la premiere prise d'origine. En l'etat, la\n"
        f"# prise d'origine se fait SUR PLACE : LinuxCNC accepte la position\n"
        f"# courante comme zero, sans bouger.\n"
    )


def build_config(
    machine: MachineKinematics,
    calibration=None,
    *,
    name: str = "XYZAC-kit",
    servo_period_ns: int = 1_000_000,
) -> ConfigFiles:
    """Construit les fichiers de configuration depuis le modele et la calibration.

    ``calibration`` est un ``CalibrationRecord`` (ADR-007). Sans lui, les
    positions de pivot employees sont celles, NOMINALES, du modele : la
    configuration est alors marquee provisoire, parce que sur une cinematique
    table/table une erreur de pivot se propage directement a la piece.
    """
    to_verify: list[str] = []
    provisional: list[str] = []

    pa = list(machine.pivot_a)
    pc = list(machine.pivot_c)
    geom = getattr(calibration, "geometry", None)
    if geom is not None and getattr(geom, "measured", False):
        pa = [pa[i] + float(geom.a_axis.offset_mm[i]) for i in range(3)]
        pc = [pc[i] + float(geom.c_axis.offset_mm[i]) for i in range(3)]
        origine = (f"mesure, dossier {calibration.calibration_hash()[:12]}")
        if not calibration.qualified:
            provisional.append(
                "machine NON QUALIFIEE sur piece d'epreuve : la configuration "
                "est utilisable en simulation, pas en production")
    else:
        origine = "NOMINALE, non mesuree"
        provisional.append(
            "positions de pivot A et C NOMINALES : executer "
            "assembly_calibration avant tout usinage, sinon l'erreur de pivot "
            "se retrouve telle quelle sur la piece")

    to_verify.append(
        "SIGNE des offsets de pivot et sens de chaque axe : un offset de bon "
        "nom et de mauvais signe ne fait echouer aucun demarrage, il fait "
        "usiner faux. Seule l'etape AXIS_DIRECTION de assembly_calibration "
        "l'etablit, en commandant un deplacement et en REGARDANT de quel cote "
        "la piece part.")
    to_verify.append(
        f"NOMS des broches HAL de {KINEMATICS_MODULE} : confirmes contre la "
        "2.9 (configuration chargee, voir docs/validation-linuxcnc.md), mais "
        "ils varient selon la version. Verifier par 'halcmd show pin xyzac'. "
        "Un nom errone fait echouer le demarrage, sans mouvement.")
    if machine.c_mode is CAxisMode.CONTINUOUS_SPINDLE:
        to_verify.append(
            "mode C = broche de tournage : cette configuration declare C comme "
            "axe rotatif. Le basculement en broche est une transition "
            "verrouillee (ADR-001 / D8) et exige une configuration distincte.")

    ini = [
        f"# Configuration LinuxCNC generee depuis MachineKinematics '{machine.machine_id}'.",
        "#",
        "# NE PAS EDITER A LA MAIN : ce fichier est derive du modele machine et",
        "# du dossier de calibration. Une modification manuelle serait perdue a",
        "# la regeneration suivante, et surtout elle desynchroniserait la",
        "# configuration du modele contre lequel les collisions sont verifiees.",
        f"# Positions de pivot : {origine}.",
        "",
        "[EMC]",
        f"MACHINE = {name}",
        "DEBUG = 0",
        "VERSION = 1.1",
        "",
        "[DISPLAY]",
        "DISPLAY = axis",
        "OPEN_FILE = \"\"",
        "PROGRAM_PREFIX = ./nc_files",
        "MAX_FEED_OVERRIDE = 1.2",
        "MAX_SPINDLE_OVERRIDE = 1.0",
        "",
        "[TASK]",
        "TASK = milltask",
        "CYCLE_TIME = 0.010",
        "",
        "[RS274NGC]",
        "PARAMETER_FILE = xyzac.var",
        "# Le post-processeur n'emet ni sous-programme ni variable : aucun",
        "# SUBROUTINE_PATH n'est donc declare.",
        "",
        "[EMCMOT]",
        "EMCMOT = motmod",
        "COMM_TIMEOUT = 1.0",
        f"SERVO_PERIOD = {servo_period_ns}",
        "",
        "[KINS]",
        f"KINEMATICS = {KINEMATICS_MODULE}",
        "# 5 articulations (0..4). Le module annonce lui-meme sa",
        "# correspondance au chargement : Joint 4 ==> Axis C. Aucune",
        "# articulation fictive n'est declaree.",
        "JOINTS = 5",
        "",
        "[TRAJ]",
        "COORDINATES = X Y Z A C",
        "LINEAR_UNITS = mm",
        "ANGULAR_UNITS = degree",
        f"MAX_LINEAR_VELOCITY = "
        f"{min(machine.x.max_feed_mm_min, machine.y.max_feed_mm_min, machine.z.max_feed_mm_min) / 60.0:.4f}",
        "# Exigee des qu'un axe rotatif existe : LinuxCNC l'annonce comme",
        "# 'Missing required specifier (has angular joint or axis)'.",
        f"MAX_ANGULAR_VELOCITY = "
        f"{min(machine.a.max_feed_deg_min, machine.c.max_feed_deg_min) / 60.0:.4f}",
        "",
        "[HAL]",
        "# Sans cette section, LinuxCNC ne charge AUCUN fichier HAL : le",
        "# module de cinematique et motmod ne sont jamais instancies, et le",
        "# demarrage echoue sur 'emcTrajInit failed'. Elle a manque, et les",
        "# tests ne l'ont pas vu parce qu'ils verifiaient le CONTENU des",
        "# fichiers HAL sans verifier que l'INI y renvoie.",
        "HALFILE = xyzac.hal",
        "POSTGUI_HALFILE = postgui.hal",
        "",
        "[EMCIO]",
        "TOOL_TABLE = tool.tbl",
        "# Sans cette ligne LinuxCNC choisit 0,1 s et l'ecrit dans son journal.",
        "# Une valeur par defaut choisie en silence est exactement ce que ce",
        "# projet refuse ailleurs ; elle est donc ecrite ici.",
        "CYCLE_TIME = 0.100",
        "",
    ]

    ini.append(_axis_block("X", machine.x))
    ini.append(_axis_block("Y", machine.y))
    ini.append(_axis_block("Z", machine.z))
    ini.append(_axis_block("A", machine.a, is_rotary=True))
    ini.append(_axis_block("C", machine.c, is_rotary=True))

    # Les blocs d'articulation sont derives de JOINT_AXIS, et non ecrits un
    # par un : la version precedente listait a la main un [JOINT_5] alors que
    # JOINT_AXIS disait 4. Deux sources de verite pour le meme numero, et
    # elles ont diverge.
    _par_axe = {
        "X": (machine.x, False, machine.x.backlash_mm),
        "Y": (machine.y, False, machine.y.backlash_mm),
        "Z": (machine.z, False, machine.z.backlash_mm),
        "A": (machine.a, True, machine.a.backlash_deg),
        "C": (machine.c, True, machine.c.backlash_deg),
    }
    for _j, _axe in JOINT_AXIS:
        _ax, _rot, _jeu = _par_axe[_axe]
        ini.append(_joint_block(_j, _axe, _ax, is_rotary=_rot, backlash=_jeu))

    if all(v == 0.0 for v in (machine.x.backlash_mm, machine.y.backlash_mm,
                              machine.z.backlash_mm, machine.a.backlash_deg,
                              machine.c.backlash_deg)):
        provisional.append(
            "tous les jeux (BACKLASH) valent 0 : ils ne sont pas mesures. "
            "Declarer 0 n'est pas neutre, c'est affirmer l'absence de jeu")

    hal = [
        "# HAL generee depuis MachineKinematics. NE PAS EDITER A LA MAIN.",
        "#",
        "# Cette configuration est faite pour le mode SIMULATION : les",
        "# articulations sont bouclees sur elles-memes. Aucun pilote de moteur,",
        "# aucune sortie physique. Passer au materiel demande de remplacer le",
        "# bloc marque 'SIMULATION' par les composants du materiel reel, et",
        "# c'est une operation qui se fait machine devant soi.",
        "",
        f"loadrt [KINS]KINEMATICS",
        "loadrt motmod servo_period_nsec=[EMCMOT]SERVO_PERIOD num_joints=[KINS]JOINTS",
        "",
        "addf motion-command-handler servo-thread",
        "addf motion-controller servo-thread",
        "",
        "# ---------------- SIMULATION : boucle fermee logicielle ----------------",
        "# Chaque articulation renvoie sa propre consigne comme position reelle.",
        "# C'est ce qui permet de faire tourner le vrai interpreteur et la vraie",
        "# cinematique sans aucun materiel.",
    ]
    for j, _name in JOINT_AXIS:
        hal.append(f"net j{j}-pos joint.{j}.motor-pos-cmd => joint.{j}.motor-pos-fb")
    hal += [
        "",
        "# ---------------- offsets de pivot mesures ----------------",
        "#",
        "# Ces valeurs viennent du modele machine et, quand il existe, du",
        "# dossier de calibration. La correspondance ci-dessous est LUE dans",
        "# xyzacKinematicsForward/Inverse (src/emc/kinematics/trtfuncs.c), pas",
        "# devinee, parce qu'une version precedente de ce fichier la devinait",
        "# et se trompait sur deux des trois valeurs :",
        "#",
        "#   rotation C  : autour de (x-rot-point, y-rot-point)",
        "#   rotation A  : autour de (y-offset + y-rot-point,",
        "#                            z-offset + z-rot-point)",
        "#",
        "# D'ou : les rot-point portent l'axe C, et y-offset porte l'ecart de",
        "# l'axe A PAR RAPPORT a l'axe C — pas sa position absolue.",
        "#",
        "# La broche x-offset n'est PAS employee par la cinematique xyzac : la",
        "# lecture de trtfuncs.c montre qu'elle ne l'est que par la variante",
        "# xyzbc. Y ecrire une valeur mesuree ne produit aucune erreur et",
        "# n'a aucun effet — c'est le pire des deux mondes, donc on ne l'ecrit",
        "# pas. La composante X de l'axe C passe par x-rot-point.",
        "#",
        "# Les NOMS de broches dependent de la version : verifier par",
        "#     halcmd show pin xyzac",
        "# Un nom errone fait echouer le demarrage, ce qui est le bon mode",
        "# d'echec. Un SIGNE errone, lui, ne fait rien echouer : il fait usiner",
        "# faux, et seule l'etape AXIS_DIRECTION de assembly_calibration peut",
        "# l'ecarter. Le module lui-meme previent, dans son en-tete :",
        "# 'The directions of the rotational axes are the opposite of the",
        "#  conventional axis directions.'",
        f"setp {KINEMATICS_MODULE}.x-rot-point {pc[0]:.6f}",
        f"setp {KINEMATICS_MODULE}.y-rot-point {pc[1]:.6f}",
        f"setp {KINEMATICS_MODULE}.y-offset {pa[1] - pc[1]:.6f}",
        "# Seule la SOMME (z-offset + z-rot-point) intervient dans les",
        "# equations : les deux broches sont redondantes en Z. On porte donc",
        "# tout sur z-offset et on laisse z-rot-point a 0, plutot que de",
        "# repartir arbitrairement une valeur mesuree entre deux broches.",
        f"setp {KINEMATICS_MODULE}.z-offset {pa[2]:.6f}",
        f"setp {KINEMATICS_MODULE}.z-rot-point 0.000000",
        "",
        "# ---------------- arret d'urgence ----------------",
        "#",
        "# En simulation la boucle d'arret d'urgence est logicielle. SUR UNE",
        "# MACHINE REELLE elle doit etre MATERIELLE et independante du logiciel :",
        "# une chaine de securite qui coupe la puissance sans passer par",
        "# LinuxCNC. Le logiciel ne peut ni l'armer, ni la masquer, ni la",
        "# reinitialiser (ADR-001 / D9), et remplacer ce bloc par un simple",
        "# renvoi logiciel sur une machine reelle serait une faute grave.",
        "net estop-loop iocontrol.0.user-enable-out => iocontrol.0.emc-enable-in",
        "net tool-change iocontrol.0.tool-change => iocontrol.0.tool-changed",
        "net tool-number iocontrol.0.tool-prep-number",
        "net tool-prepare-loop iocontrol.0.tool-prepare => iocontrol.0.tool-prepared",
        "",
    ]

    postgui = [
        "# HAL post-interface. Vide a ce jalon : aucun panneau personnalise.",
        "# Le fichier existe pour que la configuration soit complete et que",
        "# l'ajout d'un panneau ne demande pas de toucher a l'INI.",
        "",
    ]

    # Le caractere de commentaire d'une table d'outils est ';' et non '#' :
    # tooldata_read_entry() teste input_line[0] == ';'. Avec '#', LinuxCNC
    # imprime « Unrecognized line skipped » pour CHAQUE ligne a chaque
    # demarrage — le motif etait donc ecrit dans un fichier qui le rejetait.
    tool_table = [
        "; Table d'outils LinuxCNC.",
        ";",
        "; VIDE volontairement : les longueurs d'outil doivent etre MESUREES",
        "; (probing_service), pas saisies. Une jauge fausse decale toute la",
        "; gamme en Z, et c'est l'erreur la plus courante et la plus couteuse.",
        "",
    ]
    to_verify.append(
        "table d'outils VIDE : renseigner chaque longueur par mesure, jamais "
        "par saisie. Une jauge fausse decale toute la gamme en Z.")

    return ConfigFiles(
        ini="\n".join(ini), hal="\n".join(hal),
        postgui_hal="\n".join(postgui), tool_table="\n".join(tool_table),
        to_verify=to_verify, provisional=provisional,
    )
