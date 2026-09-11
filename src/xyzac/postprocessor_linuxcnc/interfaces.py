"""Post-processeur LinuxCNC. VOLONTAIREMENT NON IMPLEMENTE au jalon M2.

Etat des prerequis, mis a jour apres M2 — la raison du verrou a change, et il
importe de ne pas laisser une justification perimee en place :

  ADR-001 §6 conditionne la generation de G-code a ce que les quatre portes
  soient implementees ET testees.

  - collision_engine      IMPLEMENTE (poses + balayage + organes machine)
  - kinematics_solver     IMPLEMENTE
  - simulation_engine     IMPLEMENTE (``TrajectoryValidator``, 4 verifications)
  - safety_state_machine  IMPLEMENTE

Les quatre portes existent donc reellement depuis M2, et la porte de simulation
verifie desormais quelque chose. Ce qui reste bloquant n'est plus la chaine de
securite mais **ce qui la nourrit** :

  1. Aucune machine reelle n'a ete calibree : ``pivot_a``, ``pivot_c``, les
     courses et les jeux du modele sont des valeurs PROVISOIRES inventees pour
     le digital twin. Generer du G-code depuis un modele non calibre produirait
     un programme geometriquement coherent et physiquement faux.
  2. ``strategy_planner`` et ``subtractive_slicer`` n'existent pas : il n'y a
     pas de gamme, seulement des passes d'essai construites a la main.
  3. La detection de gouge FINE reste bornee par la resolution du nuage de
     points (voir ``verify_gouge_exact`` pour le verificateur exact, qui ne
     couvre encore qu'un echantillon).
  4. Les vitesses et avances ne sont pas qualifiees (``recipe_profiles``).

La signature exige la machine d'etat et le hash du setup. Ce n'est pas
decoratif : cela rend impossible d'appeler le post-processeur « juste pour
voir » depuis un notebook.
"""

from __future__ import annotations

from ..safety_state_machine.machine import SafetyStateMachine


def post_process(plan, safety: SafetyStateMachine, current_setup_hash: str) -> str:
    """Genere le G-code LinuxCNC d'une gamme approuvee."""
    # La porte est verifiee AVANT toute autre chose, y compris avant de regarder
    # le plan : si l'etat n'autorise pas la generation, rien d'autre n'a de sens.
    safety.require_postprocess(current_setup_hash)
    raise NotImplementedError(
        "postprocessor_linuxcnc non implemente au jalon M2. Les quatre portes de "
        "securite existent et fonctionnent, mais la machine n'est pas calibree "
        "(parametres cinematiques provisoires) et aucune gamme n'est planifiee. "
        "Voir le docstring du module pour l'etat detaille des prerequis."
    )
