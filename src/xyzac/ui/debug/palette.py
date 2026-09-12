"""Code couleur UNIQUE du banc de debug.

Une couleur qui veut dire deux choses selon l'onglet ne sert a rien. Ce module
est donc la seule source : tout element visuel du banc prend sa couleur ici, et
nulle part ailleurs.

Convention, fixee une fois :

    VERT    orientation ou mouvement VALIDE
    ROUGE   collision
    ORANGE  proche d'une collision, ou proche d'une limite de course
    BLEU    trajectoire outil
    GRIS    brut (transparent)
    AMBRE   piece finale (couleur distincte et lisible)

Les teintes exactes sont choisies pour rester distinguables en cas de daltonisme
rouge-vert : le vert tire vers le cyan et le rouge vers le magenta, de sorte que
les deux se separent aussi en luminance.
"""

from __future__ import annotations

#: Etats de validite. Voir la convention ci-dessus.
VALID = "#2ca05a"          # vert
COLLISION = "#d1344b"      # rouge
WARNING = "#e08a1e"        # orange
PATH = "#2f7fd1"           # bleu
NEUTRAL = "#8a8f98"        # gris

#: Elements de scene.
PART = "#d9a441"           # piece finale : ambre
STOCK = "#9aa0a8"          # brut : gris
MATERIAL = "#b8bec7"       # matiere restante
FIXTURE = "#6b5b8a"        # bridage
MACHINE = "#5a6470"        # organes machine
BACKGROUND = "#1c2026"     # fond de la vue 3D
GRID = "#39404a"

#: Troncons d'outil, par role. Voir ``tool_model.SegmentRole``.
#:
#: Le degrade va du clair (arete de coupe, ce qui doit toucher) au sombre (nez
#: de broche, ce qui ne doit jamais toucher) : la gravite d'un contact se lit
#: donc directement sur la teinte.
TOOL_ROLE = {
    "cutting": "#f2e6c9",
    "flute": "#d8c9a3",
    "neck": "#b9a87e",
    "shank": "#8f8464",
    "holder": "#5f5a49",
    "spindle_nose": "#3e3b33",
}

#: Opacites par defaut. Le brut doit laisser voir la piece a l'interieur.
OPACITY = {
    "part": 1.0,
    "stock": 0.18,
    "material": 0.35,
    "fixture": 0.55,
    "machine": 0.30,
    "tool": 1.0,
}


def role_color(role: str) -> str:
    """Couleur d'un role de troncon, gris neutre si le role est inconnu."""
    return TOOL_ROLE.get(str(role), NEUTRAL)
