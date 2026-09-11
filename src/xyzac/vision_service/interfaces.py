"""Vision : OBSERVATIONS uniquement, jamais de commandes.

Regle de securite (ADR-001 / D9) : la sortie de ce module entre dans
``probing_service`` et ``assembly_calibration`` comme une MESURE A VALIDER.
Elle n'atteint jamais un axe. Aucune fonction d'ici ne retourne une consigne.

Contrainte de licence (ADR-001 / D10, docs/audit) : **Ultralytics YOLO est
AGPL-3.0**, et l'editeur soutient qu'un usage commercial requiert une licence
Enterprise. Comme le logiciel est distribue avec un kit vendu, et que l'UI est
servie en reseau local (ce qui active precisement la clause reseau de l'AGPL),
le backend livre n'est PAS Ultralytics. Le detecteur est une interface ; un
backend Ultralytics reste possible en plugin tiers hors depot, installe
volontairement par l'utilisateur final, auquel cas l'obligation lui incombe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass
class Detection:
    """Une observation. Notez l'absence de tout champ de commande."""

    label: str
    confidence: float
    bbox_px: tuple[float, float, float, float]
    #: Pose estimee en repere machine, si la calibration camera le permet.
    pose_mm: np.ndarray | None = None
    #: Incertitude estimee. Une mesure sans incertitude n'est pas une mesure.
    uncertainty_mm: float | None = None


class Detector(Protocol):
    """Backend de detection interchangeable.

    Implementations prevues :
      - ``OnnxDetector``   : ONNX Runtime + modele sous licence permissive (defaut) ;
      - ``HailoDetector``  : accelerateur IA du Pi 5 ;
      - ``OpenCvDetector`` : traitement classique (contours, damier), sans reseau.
    """

    name: str
    license: str

    def detect(self, image: np.ndarray) -> list[Detection]: ...


class OpenCvDetector:
    """Detecteur classique OpenCV (Apache-2.0). Aucun reseau de neurones.

    Volontairement le premier backend a implementer : pour la detection de
    damier de calibration, de bridage et de presence de piece, un traitement
    deterministe est plus fiable, plus explicable et plus facile a qualifier
    qu'un reseau — et il n'a aucun probleme de licence.
    """

    name = "opencv-classique"
    license = "Apache-2.0"

    def detect(self, image: np.ndarray) -> list[Detection]:
        raise NotImplementedError("vision_service non implemente au jalon M1")
