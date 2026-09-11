"""Post-processeur LinuxCNC. VOLONTAIREMENT NON IMPLEMENTE au jalon M1.

Ce n'est pas une lacune : c'est la decision ADR-001 §6. Tant que
``collision_engine``, ``kinematics_solver``, ``simulation_engine`` et
``safety_state_machine`` ne sont pas tous implementes ET couverts par des tests,
aucun G-code destine a une machine reelle ne doit pouvoir sortir de ce depot.

La signature ci-dessous exige la machine d'etat et le hash du setup. Ce n'est
pas decoratif : c'est ce qui rend impossible d'appeler le post-processeur
« juste pour voir » depuis un notebook.
"""

from __future__ import annotations

from ..safety_state_machine.machine import SafetyStateMachine


def post_process(plan, safety: SafetyStateMachine, current_setup_hash: str) -> str:
    """Genere le G-code LinuxCNC d'une gamme approuvee."""
    # La porte est verifiee AVANT toute autre chose, y compris avant de regarder
    # le plan : si l'etat n'autorise pas la generation, rien d'autre n'a de sens.
    safety.require_postprocess(current_setup_hash)
    raise NotImplementedError(
        "postprocessor_linuxcnc non implemente au jalon M1 (ADR-001 §6). "
        "Les portes de securite existent mais simulation_engine ne valide pas "
        "encore les trajectoires : generer du G-code maintenant reviendrait a "
        "faire confiance a une porte qui ne verifie rien."
    )
