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


#: Couleur par motif de rejet d'orientation (``accessibility_solver.RejectReason``).
#:
#: Les familles se lisent a la teinte, le detail a la nuance :
#:
#:   vert      admissible
#:   rouges    collision d'un troncon d'outil, du plus clair (arete) au plus
#:             sombre (nez de broche) — la gravite monte avec l'assombrissement,
#:             comme pour les troncons eux-memes
#:   orange    limite de course, lineaire ou rotative
#:   violet    singularite : ni collision ni butee, mais inexploitable
#:   gris      ecarte par le filtre geometrique, avant tout calcul physique
REASON_COLOR = {
    "OK": VALID,
    "BACK_FACING": "#5a5f66",
    "LEAD_LIMIT": "#7c8189",
    "AXIS_LIMITS": WARNING,
    "MACHINE_TRAVEL": "#c9700f",
    "SINGULARITY": "#9b59d0",
    "COLLISION_CUTTING": "#f2726f",
    "COLLISION_NECK": "#e1504f",
    "COLLISION_SHANK": "#c93a42",
    "COLLISION_HOLDER": "#a52836",
    "COLLISION_SPINDLE": "#7d1b2a",
    "MACHINE_COLLISION": "#5c1220",
}

#: Familles, pour les compteurs du panneau ACCESSIBILITE.
REASON_FAMILY = {
    "OK": "admissible",
    "BACK_FACING": "geometrie",
    "LEAD_LIMIT": "geometrie",
    "AXIS_LIMITS": "cinematique",
    "MACHINE_TRAVEL": "cinematique",
    "SINGULARITY": "singularite",
    "COLLISION_CUTTING": "collision outil",
    "COLLISION_NECK": "collision outil",
    "COLLISION_SHANK": "collision outil",
    "COLLISION_HOLDER": "collision outil",
    "COLLISION_SPINDLE": "collision outil",
    "MACHINE_COLLISION": "collision machine",
}

FAMILY_COLOR = {
    "admissible": VALID,
    "geometrie": "#7c8189",
    "cinematique": WARNING,
    "singularite": "#9b59d0",
    "collision outil": COLLISION,
    "collision machine": "#5c1220",
}


def reason_color(reason_name: str) -> str:
    return REASON_COLOR.get(str(reason_name), NEUTRAL)


def reason_family(reason_name: str) -> str:
    return REASON_FAMILY.get(str(reason_name), "autre")
