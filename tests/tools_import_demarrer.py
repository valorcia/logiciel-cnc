"""Passerelle d'import : ``tools/`` n'est pas un paquet installe.

Un fichier a part plutot qu'un bricolage de ``sys.path`` dans le test : la
manipulation resterait alors en vigueur pour tous les tests suivants du
fichier, ce qui est le genre d'effet de bord qu'on ne remarque qu'en le
cherchant.
"""

import importlib.util
from pathlib import Path

_chemin = Path(__file__).resolve().parents[1] / "tools" / "demarrer_atelier.py"
_spec = importlib.util.spec_from_file_location("_demarrer_atelier", _chemin)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

module = _module
VERSIONS_SURES = _module.VERSIONS_SURES
RACINE = _module.RACINE
