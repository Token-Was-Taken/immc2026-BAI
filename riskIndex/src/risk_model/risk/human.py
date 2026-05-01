"""
Human risk calculator module.
"""

import math
from dataclasses import dataclass
from typing import Tuple, Optional

from ..core.grid import Grid


@dataclass
class HumanRiskWeights:
    """
    Weights for human risk calculation.

    Attributes:
        boundary_weight: Weight for proximity to boundary
        road_weight: Weight for proximity to road
        water_weight: Weight for proximity to water source
    """
    boundary_weight: float = 0.2
    road_weight: float = 0.3
    water_weight: float = 0.5

    def __post_init__(self):
        """Validate weights sum to 1."""
        total = self.boundary_weight + self.road_weight + self.water_weight
        if not math.isclose(total, 1.0, rel_tol=1e-9):
            raise ValueError(
                f"Weights must sum to 1, got {total} "
                f"(boundary={self.boundary_weight}, road={self.road_weight}, "
                f"water={self.water_weight})"
            )


class HumanRiskCalculator:
    """
    Calculates human risk based on proximity to boundaries, roads, and water sources.
    """

    def __init__(self, weights: Optional[HumanRiskWeights] = None):
        """
        Initialize the human risk calculator.

        Args:
            weights: Weight configuration for human risk factors
        """
        self.weights = weights or HumanRiskWeights()

    def calculate(
        self,
        grid: Grid,
        poaching_probability: float = 1.0
    ) -> float:
        """
        Calculate human risk for a grid cell.

        Args:
            grid: Grid cell to calculate risk for
            poaching_probability: Time-based poaching probability factor [0, 1]

        Returns:
            Human risk value [0, 1]
        """
        if not (0.0 <= poaching_probability <= 1.0):
            raise ValueError(
                f"Poaching probability must be between 0 and 1, got {poaching_probability}"
            )

        boundary_prox, road_prox, water_prox = grid.proximity_score

        base_risk = (
            self.weights.boundary_weight * boundary_prox +
            self.weights.road_weight * road_prox +
            self.weights.water_weight * water_prox
        )

        return base_risk * poaching_probability

    def calculate_component_breakdown(self, grid: Grid) -> Tuple[float, float, float]:
        """
        Calculate the individual components of human risk.

        Args:
            grid: Grid cell to analyze

        Returns:
            Tuple of (boundary_risk, road_risk, water_risk)
        """
        boundary_prox, road_prox, water_prox = grid.proximity_score

        return (
            self.weights.boundary_weight * boundary_prox,
            self.weights.road_weight * road_prox,
            self.weights.water_weight * water_prox
        )
