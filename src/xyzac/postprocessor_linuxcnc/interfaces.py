"""Etat du verrou de generation, et son historique.

Ce fichier ne contient plus de code : l'emetteur est dans ``emit.py`` depuis le
jalon M7. Il garde la trace de l'evolution du verrou, parce que la raison pour
laquelle on refusait quelque chose fait partie de la conception — et parce que
laisser une justification perimee en place serait plus trompeur que de ne rien
ecrire.

**M1.** ADR-001 §6 conditionne la generation a ce que les quatre portes soient
implementees ET testees. Aucune ne l'etait.

**M2.** Les quatre portes existent et sont testees : ``collision_engine``
(poses, balayage, organes machine), ``kinematics_solver`` (butees, singularite,
vitesse rotative), ``simulation_engine`` (quatre verifications),
``safety_state_machine`` (portes non contournables liees au hash du setup). Le
verrou tient, son motif se deplace.

**M3.** Une GAMME existe aussi : ``strategy_planner`` choisit les indexations,
``subtractive_slicer`` produit les trajectoires, chaque operation est validee
couche par couche contre l'etat reel de la matiere. Le motif restant est nomme
explicitement : **la machine n'est pas calibree.** ``pivot_a``, ``pivot_c``, les
courses et les jeux sont provisoires, et sur une cinematique table/table
l'erreur de pivot se propage directement a la piece.

**M7.** Le verrou avait donc deux moities, et seule la premiere etait logicielle :

  - il n'existait ni emetteur, ni modele de calibration auquel une approbation
    puisse se lier. **Levee** : ``machine_model.geometry`` porte les erreurs
    mesurees, ``kinematics_solver.compensation`` les corrige,
    ``assembly_calibration`` les mesure, et le dossier de calibration entre dans
    le hash du setup.
  - la machine n'est ni construite ni qualifiee. **Inchangee**, et elle ne peut
    pas etre levee par du logiciel.

D'ou la separation que ``emit.post_process`` fait respecter, et qui est celle
des ateliers : **poster** exige les portes franchies et une geometrie mesuree —
on poste avant de qualifier ; **envoyer** exige tout, piece d'epreuve comprise,
et c'est ``linuxcnc_gateway``, qui reste verrouille.

Prerequis secondaires, qui n'empechent pas de poster mais bornent ce qu'on peut
affirmer, et qui sont ecrits dans l'en-tete du fichier produit :

  - gouge de l'arete entre deux poses : non prouvee (ADR-006 / D52) ;
  - avances et vitesses non qualifiees (``recipe_profiles`` est une ebauche) ;
  - approche et degagement non generes (ADR-007 / D65) ;
  - performance jamais mesuree sur la cible embarquee.
"""

from __future__ import annotations

from .emit import post_process  # noqa: F401  (compatibilite d'import historique)
