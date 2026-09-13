"""Atelier : l'interface de l'utilisateur, par opposition au banc de debug.

Le banc de debug montre ce que le moteur CALCULE. L'atelier montre ce que
l'utilisateur DOIT FAIRE. Ce ne sont pas deux presentations du meme ecran :
l'un sert a trouver un defaut, l'autre a decider.
"""

from .session import Reglages, Session, Surface

__all__ = ["Reglages", "Session", "Surface"]
