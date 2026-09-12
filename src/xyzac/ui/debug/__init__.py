"""Banc de debug visuel du slicer XYZAC.

Outil de controle pour le porteur du projet : voir ce que le moteur calcule au
lieu d'en lire les journaux. Ce n'est PAS l'IHM destinee au client final.

Trois couches, separees pour une raison concrete autant que theorique :

  ``state``   ce qui est charge, et ce que le banc peut en dire. Sans Qt.
  ``scene``   la traduction en objets 3D. Sans Qt.
  ``window``  la coquille Qt. Aucune logique.

La separation vient d'une contrainte materielle : le conteneur de developpement
n'a pas d'ecran. Tout ce qui vit dans ``state`` et ``scene`` est donc testable
et teste ; ce qui vit dans ``window`` ne l'est pas, et c'est pourquoi il n'y a
rien d'autre dedans que des widgets.

**Securite** : aucun module de ce paquet n'importe ``linuxcnc_gateway``. Aucun
bouton ne peut deplacer une machine, et un test le verifie.
"""

from .palette import COLLISION, PATH, VALID, WARNING
from .state import AxisReadout, BenchState, PartInfo

__all__ = ["AxisReadout", "BenchState", "COLLISION", "PATH", "PartInfo",
           "VALID", "WARNING"]
