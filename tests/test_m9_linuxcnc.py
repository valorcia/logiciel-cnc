"""Configuration LinuxCNC et remise d'un programme (jalon M9).

**Ce que ces tests NE peuvent pas verifier, et il faut le dire d'abord.**
LinuxCNC n'est pas installable dans l'environnement de developpement de ce
projet : absent des depots Ubuntu, son propre depot inaccessible. Aucun test
ici ne fait donc tourner l'interpreteur de LinuxCNC ni ne charge la
configuration produite. Le seul verdict qui compte viendra d'une commande sur
la machine de l'utilisateur — ``verification_command()`` la donne.

Ce que ces tests verifient : que la configuration est DERIVEE du modele et non
saisie, qu'elle annonce ce qu'elle ne sait pas, et que les conditions de depot
d'un programme sont celles que le projet s'est fixees.
"""

import hashlib

import pytest

from xyzac.assembly_calibration import (
    CalibrationRecord,
    calibrate_on_twin,
    record_from_report,
)
from xyzac.linuxcnc_gateway import (
    KINEMATICS_MODULE,
    DepositRefused,
    Target,
    build_config,
    deposit_program,
    start_cycle,
    verification_command,
)
from xyzac.machine_model import MachineGeometry, default_xyzac_kit
from xyzac.machine_model.geometry import AxisLocationError
from xyzac.safety_state_machine import SafetyStateMachine, SafetyViolation


@pytest.fixture(scope="module")
def machine():
    return default_xyzac_kit()


@pytest.fixture(scope="module")
def calibre(machine):
    truth = MachineGeometry(
        machine_id=machine.machine_id, measured=True,
        a_axis=AxisLocationError(offset_mm=[0.10, -0.20, 0.30]),
        c_axis=AxisLocationError(offset_mm=[-0.15, 0.05, 0.0]))
    report, meas = calibrate_on_twin(machine, truth, probe_noise_mm=0.002)
    return record_from_report(machine.machine_id, meas, report)


def _approved(setup_hash: str) -> SafetyStateMachine:
    m = SafetyStateMachine(setup_hash=setup_hash)
    m.define_setup(setup_hash)
    m.pass_collision(True)
    m.pass_kinematics(True)
    m.pass_simulation(True)
    m.approve("test")
    return m


# ------------------------------------------------ la config est derivee

def test_travel_limits_come_from_the_model_not_from_typing(machine):
    """Retaper les courses dans un INI garantirait qu'un jour les deux
    divergent. Elles sont donc lues dans le modele."""
    cfg = build_config(machine)
    for section, lo, hi in (("AXIS_X", machine.x.min_mm, machine.x.max_mm),
                            ("AXIS_Z", machine.z.min_mm, machine.z.max_mm),
                            ("AXIS_A", machine.a.min_deg, machine.a.max_deg)):
        bloc = cfg.ini.split(f"[{section}]")[1].split("[")[0]
        assert f"MIN_LIMIT = {lo}" in bloc, (section, bloc)
        assert f"MAX_LIMIT = {hi}" in bloc, (section, bloc)


def test_the_kinematics_module_is_the_xyzac_one(machine):
    """``trivkins`` ignorerait les pivots, donc produirait une piece fausse sur
    toute pose inclinee — sans qu'aucune erreur ne soit signalee."""
    cfg = build_config(machine)
    assert f"KINEMATICS = {KINEMATICS_MODULE}" in cfg.ini
    assert "trivkins" not in cfg.ini
    assert "COORDINATES = X Y Z A C" in cfg.ini


def test_measured_pivots_reach_the_hal_file(machine, calibre):
    """Le lien concret entre la calibration et le controleur.

    Sans lui, M7 mesurerait des pivots que personne n'emploie.
    """
    nominal = build_config(machine)
    mesure = build_config(machine, calibre)

    assert nominal.hal != mesure.hal, "la calibration ne change rien au HAL"
    ligne = [l for l in mesure.hal.splitlines() if "x-offset" in l][0]
    valeur = float(ligne.split()[-1])
    attendu = machine.pivot_c[0] + calibre.geometry.c_axis.offset_mm[0]
    assert valeur == pytest.approx(attendu, abs=1e-6)


def test_an_uncalibrated_config_says_it_is_provisional(machine):
    """Une configuration deduite d'un modele non mesure doit le dire : sinon
    elle a l'air aussi fiable qu'une configuration calibree."""
    cfg = build_config(machine)
    joint = " ".join(cfg.provisional)
    assert "NOMINALE" in joint or "nominal" in joint.lower()
    assert any("jeu" in p.lower() or "backlash" in p.lower()
               for p in cfg.provisional), cfg.provisional
    assert "PROVISOIRE" in cfg.describe()


def test_a_calibrated_config_is_never_called_uncalibrated(machine, calibre):
    """Regression de la famille repetee du projet : une phrase de categorie
    ecrite d'avance qui cesse d'etre vraie quand l'etat change.

    L'en-tete de la section PROVISOIRE disait « deduit d'un modele non
    calibre ». Sur une machine dont la geometrie EST mesuree mais dont la
    piece d'epreuve manque, la section reste non vide — a bon droit — et
    l'en-tete devenait faux : elle annoncait un modele non calibre au-dessus
    d'un pivot mesure. Un operateur qui lit cela peut conclure que sa
    calibration n'a pas ete prise en compte, et la refaire.
    """
    cfg = build_config(machine, calibre)
    assert cfg.provisional, "la qualification manque, la section doit exister"
    texte = cfg.describe()
    assert "non calibre" not in texte.lower()
    # et la raison reelle du caractere provisoire doit, elle, etre nommee
    assert "NON QUALIFIEE" in texte
    # le cas non mesure continue de nommer le sien
    assert "NOMINALE" in build_config(machine).describe()


def test_the_config_never_claims_to_be_validated(machine, calibre):
    """LinuxCNC n'a pas tourne : la configuration ne peut pas se dire validee."""
    for cfg in (build_config(machine), build_config(machine, calibre)):
        assert "n'a PAS ete validee" in cfg.describe()
        assert cfg.to_verify, "il y a toujours au moins le signe des offsets"


def test_the_dangerous_point_is_named_as_such(machine, calibre):
    """Un nom de broche errone fait echouer le demarrage — bruyamment.

    Un SIGNE errone ne fait rien echouer : il fait usiner faux. La
    configuration doit donc nommer le signe comme le point a verifier, et
    renvoyer a l'etape qui l'etablit — celle qui exige de REGARDER la machine.
    """
    cfg = build_config(machine, calibre)
    joint = " ".join(cfg.to_verify)
    assert "SIGNE" in joint
    assert "AXIS_DIRECTION" in joint
    assert "halcmd show pin" in joint, "le moyen de verifier les noms doit etre donne"


def test_homing_is_left_unset_on_purpose(machine):
    """Renseigner une prise d'origine au hasard ferait partir un axe dans la
    mauvaise direction au premier cycle."""
    cfg = build_config(machine)
    assert "HOME_OFFSET" not in cfg.ini
    assert "HOME_SEARCH_VEL" not in cfg.ini
    assert "WIRING_TEST" in cfg.ini


def test_the_tool_table_is_empty_and_says_why(machine):
    """Une jauge saisie a la main decale toute la gamme en Z."""
    cfg = build_config(machine)
    assert "MESUREES" in cfg.tool_table
    lignes = [l for l in cfg.tool_table.splitlines()
              if l.strip() and not l.startswith("#")]
    assert not lignes, lignes


def test_files_are_written_where_expected(machine, calibre, tmp_path):
    cfg = build_config(machine, calibre)
    ecrits = cfg.write(tmp_path / "config-xyzac")
    assert set(ecrits) == {"xyzac.ini", "xyzac.hal", "postgui.hal", "tool.tbl"}
    for p in ecrits.values():
        assert p.exists() and p.read_text(encoding="utf-8")
    assert "linuxcnc" in verification_command("config-xyzac")
    assert "halcmd show pin" in verification_command()


# --------------------------------------------- conditions de depot

def test_deposit_refuses_without_approval(machine, calibre, tmp_path):
    """La porte de securite passe AVANT tout le reste."""
    sm = SafetyStateMachine(setup_hash="h")
    sm.define_setup("h")
    with pytest.raises(SafetyViolation):
        deposit_program("G21\nM30\n", tmp_path, target=Target.SIMULATION,
                        safety=sm, setup_hash="h", calibration=calibre)


def test_deposit_refuses_an_unmeasured_machine(machine, tmp_path):
    """Des pivots provisoires se retrouvent tels quels sur la piece."""
    vierge = CalibrationRecord(machine_id="x",
                               geometry=MachineGeometry.nominal("x"))
    with pytest.raises(DepositRefused, match="NON MESUREE"):
        deposit_program("G21\nM30\n", tmp_path, target=Target.SIMULATION,
                        safety=_approved("h"), setup_hash="h",
                        calibration=vierge)


def test_hardware_deposit_needs_a_qualified_machine(machine, calibre, tmp_path):
    """La seule condition que le logiciel ne peut pas satisfaire seul.

    Personne ne devrait pouvoir lancer une production depuis un logiciel qui
    n'a jamais vu une piece sortir de cette machine.
    """
    assert not calibre.qualified
    with pytest.raises(DepositRefused, match="non qualifiee"):
        deposit_program("G21\nM30\n", tmp_path, target=Target.HARDWARE,
                        safety=_approved("h"), setup_hash="h",
                        calibration=calibre)

    # Mais la simulation, elle, doit rester ouverte : c'est le chemin vers la
    # qualification, et le fermer la rendrait inatteignable.
    rec = deposit_program("G21\nM30\n", tmp_path, target=Target.SIMULATION,
                          safety=_approved("h"), setup_hash="h",
                          calibration=calibre)
    assert rec.path.exists()
    assert any("SIMULATION" in w for w in rec.warnings)


def test_the_deposited_file_carries_its_own_provenance(machine, calibre, tmp_path):
    """Un fichier recupere sans son journal doit pouvoir etre rattache."""
    gcode = "G21 G90\nG1 X10 F100\nM30\n"
    rec = deposit_program(gcode, tmp_path, target=Target.SIMULATION,
                          safety=_approved("abc123"), setup_hash="abc123",
                          calibration=calibre, journal=tmp_path / "journal.tsv")
    contenu = rec.path.read_text(encoding="utf-8")
    assert "abc123" in contenu
    assert calibre.calibration_hash() in contenu
    assert rec.gcode_sha256 == hashlib.sha256(gcode.encode()).hexdigest()
    assert rec.gcode_sha256 in contenu
    assert gcode in contenu, "le programme lui-meme doit etre intact"
    assert (tmp_path / "journal.tsv").read_text().count("\n") == 1


def test_no_cycle_is_ever_started(tmp_path):
    """Decision, pas manque : deposer un fichier garde un humain dans la boucle
    au dernier moment, celui ou l'on regarde la machine avant qu'elle bouge."""
    with pytest.raises(NotImplementedError, match="ne le sera pas ici"):
        start_cycle()


def test_deposit_says_no_cycle_was_started(machine, calibre, tmp_path):
    rec = deposit_program("G21\nM30\n", tmp_path, target=Target.SIMULATION,
                          safety=_approved("h"), setup_hash="h",
                          calibration=calibre)
    assert "Aucun cycle n'a ete demarre" in rec.describe()


def test_the_legacy_gateway_still_refuses_to_connect():
    """Aucune connexion vers un controleur : ce qui traverse la frontiere est
    un fichier, pas un appel de fonction (licence GPLv2 et securite)."""
    from xyzac.linuxcnc_gateway import LinuxCncGateway

    g = LinuxCncGateway()
    with pytest.raises(NotImplementedError):
        g.connect()
    assert g.estop_is_hardware() is True


def test_no_module_imports_the_linuxcnc_python_binding():
    """LinuxCNC est GPLv2 : un ``import linuxcnc`` dans notre processus poserait
    la question de l'oeuvre derivee pour toute l'application."""
    import ast
    from pathlib import Path

    import xyzac

    root = Path(xyzac.__file__).parent
    fautifs = []
    for f in sorted(root.rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            noms = []
            if isinstance(node, ast.Import):
                noms = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                noms = [node.module or ""]
            for n in noms:
                if n.split(".")[0] in {"linuxcnc", "hal", "emc"}:
                    fautifs.append(f"{f.relative_to(root)}:{node.lineno} -> {n}")
    assert not fautifs, fautifs
