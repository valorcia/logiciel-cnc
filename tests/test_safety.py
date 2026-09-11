"""Frontiere de securite : ce que le logiciel doit rendre IMPOSSIBLE.

Ces tests ne verifient pas une fonctionnalite, ils verifient une interdiction.
Un echec ici est un defaut de securite, pas une regression fonctionnelle.
"""

import numpy as np
import pytest

from xyzac.machine_model import Fixture, FixtureKind, Setup, default_xyzac_kit
from xyzac.safety_state_machine import SafetyState, SafetyStateMachine, SafetyViolation
from xyzac.stock_engine import stock_from_part
from xyzac.geometry_core.types import AABB
from xyzac.tool_model import build_endmill


@pytest.fixture
def setup():
    bb = AABB(np.array([0.0, 0, 0]), np.array([50.0, 40, 30]))
    return Setup(setup_id="S", machine=default_xyzac_kit(),
                 part_step_path="x.step", stock=stock_from_part(bb),
                 tools=[build_endmill("EM6", 6.0, 20.0, stickout=45.0)])


def test_gates_cannot_be_skipped():
    m = SafetyStateMachine(setup_hash="h")
    m.define_setup("h")
    with pytest.raises(SafetyViolation, match="transition interdite"):
        m.approve("loic")
    m.pass_collision(True)
    with pytest.raises(SafetyViolation):
        m.approve("loic")
    m.pass_kinematics(True)
    with pytest.raises(SafetyViolation):
        m.approve("loic")


def test_approval_requires_a_named_operator():
    m = SafetyStateMachine(setup_hash="h")
    m.define_setup("h"); m.pass_collision(True); m.pass_kinematics(True); m.pass_simulation(True)
    with pytest.raises(SafetyViolation, match="operateur"):
        m.approve("   ")


def test_failed_gate_leads_to_fault_not_approval():
    m = SafetyStateMachine(setup_hash="h")
    m.define_setup("h")
    m.pass_collision(False, "12 collisions")
    assert m.state is SafetyState.FAULT
    with pytest.raises(SafetyViolation):
        m.pass_kinematics(True)


def _approved(h="h"):
    m = SafetyStateMachine(setup_hash=h)
    m.define_setup(h); m.pass_collision(True); m.pass_kinematics(True)
    m.pass_simulation(True); m.approve("loic")
    return m


def test_setup_change_invalidates_approval():
    """Exigence centrale : une modification de setup invalide l'approbation."""
    m = _approved()
    assert m.may_postprocess("h")
    assert not m.may_postprocess("autre_hash")
    assert m.state is SafetyState.INVALIDATED


def test_postprocessor_refuses_without_approval(setup):
    from xyzac.postprocessor_linuxcnc import post_process
    m = SafetyStateMachine(setup_hash=setup.setup_hash())
    m.define_setup(setup.setup_hash())
    with pytest.raises(SafetyViolation, match="generation refusee"):
        post_process(plan=None, safety=m, current_setup_hash=setup.setup_hash())


def test_postprocessor_is_not_implemented_even_when_approved(setup):
    """Meme approuve, aucun G-code ne sort. ADR-001 §6.

    Le motif du verrou a change entre M1 et M2 — les portes existent
    desormais — mais le verrou lui-meme tient. Le test porte donc sur le
    comportement (rien ne sort), pas sur le libelle du message.
    """
    from xyzac.postprocessor_linuxcnc import post_process
    h = setup.setup_hash()
    with pytest.raises(NotImplementedError, match="non implemente"):
        post_process(plan=None, safety=_approved(h), current_setup_hash=h)


def test_gateway_refuses_to_connect_at_this_milestone():
    from xyzac.linuxcnc_gateway import LinuxCncGateway
    g = LinuxCncGateway()
    with pytest.raises(NotImplementedError, match="portes de securite"):
        g.connect()
    assert g.estop_is_hardware() is True


def test_estop_is_declared_hardware_and_independent():
    m = SafetyStateMachine(setup_hash="h")
    assert m.hardware_estop_is_independent is True


# ------------------------------------------------------- hash du setup

def test_cosmetic_change_does_not_invalidate(setup):
    h = setup.setup_hash()
    setup.notes = "commentaire ajoute par l'operateur"
    assert setup.setup_hash() == h, "un commentaire ne doit pas invalider une approbation"


@pytest.mark.parametrize("mutate", [
    lambda s: setattr(s.work_offset, "origin_mm", [0.1, 0.0, 0.0]),
    lambda s: setattr(s.stock, "finish_allowance_mm", 0.5),
    lambda s: s.fixtures.append(Fixture(name="m", kind=FixtureKind.CLAMP,
                                        lo=[0, 0, 0], hi=[1, 1, 1])),
    lambda s: setattr(s.tools[0], "gauge_length", 100.0),
    lambda s: setattr(s.machine, "pivot_a", [0.0, 0.0, -41.0]),
])
def test_geometric_change_invalidates(setup, mutate):
    """Chacune de ces modifications change ce que l'outil va rencontrer.
    Aucune ne doit pouvoir passer inapercue."""
    h = setup.setup_hash()
    mutate(setup)
    assert setup.setup_hash() != h


def test_no_module_besides_gateway_imports_a_machine_transport():
    """La frontiere de securite est aussi une frontiere de DEPENDANCES.

    Aucun module de calcul ne doit pouvoir ouvrir un port machine, meme par
    accident. On le verifie sur le source plutot que de l'enoncer dans un
    document, ou personne ne le relit.
    """
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "xyzac"
    banned = ("import socket", "import telnetlib", "import serial", "import linuxcnc")
    offenders = []
    for f in root.rglob("*.py"):
        if "linuxcnc_gateway" in f.parts:
            continue
        text = f.read_text(encoding="utf-8")
        for b in banned:
            if b in text:
                offenders.append(f"{f.relative_to(root)} : {b}")
    assert not offenders, f"transport machine hors de la passerelle : {offenders}"
