"""Post-processeur LinuxCNC. VOLONTAIREMENT NON IMPLEMENTE au jalon M3.

Etat des prerequis, revu a chaque jalon — laisser une justification perimee en
place serait plus trompeur que ne rien ecrire.

ADR-001 §6 conditionne la generation de G-code a ce que les quatre portes
soient implementees ET testees. Elles le sont depuis M2 :

  - collision_engine      poses + balayage + organes machine
  - kinematics_solver     butees, singularite, vitesse rotative
  - simulation_engine     ``TrajectoryValidator`` (4 verifications)
  - safety_state_machine  portes non contournables, liees au hash du setup

Depuis M3, une GAMME existe aussi : ``strategy_planner`` choisit les
indexations, ``subtractive_slicer`` produit les trajectoires, et chaque
operation est validee couche par couche contre l'etat reel de la matiere.

**Ce qui reste bloquant tient donc en un point, et il n'est pas logiciel :**

  La machine n'est pas calibree. ``pivot_a``, ``pivot_c``, les courses et les
  jeux de ``default_xyzac_kit`` sont des valeurs PROVISOIRES, inventees pour le
  digital twin. Sur une cinematique table/table, l'erreur de position des
  pivots se propage directement a la piece : generer du G-code depuis ce modele
  produirait un programme geometriquement coherent et physiquement faux.

  ``assembly_calibration`` definit la sequence de mesure qui leve ce verrou.
  Elle exige une machine, et ne peut pas etre remplacee par du calcul.

Prerequis secondaires, qui n'empechent pas de generer mais bornent ce qu'on
peut affirmer :
  - detection de gouge fine limitee a un sondage (``verify_gouge_exact``) ;
  - vitesses et avances non qualifiees (``recipe_profiles``) ;
  - performance jamais mesuree sur la cible embarquee.

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
        "postprocessor_linuxcnc non implemente au jalon M3. Les quatre portes de "
        "securite fonctionnent et une gamme validee existe, mais la machine n'est "
        "pas calibree : les parametres cinematiques (pivots A et C, courses, jeux) "
        "sont provisoires. Sur une cinematique table/table, l'erreur de pivot se "
        "propage directement a la piece. Voir le docstring du module."
    )
