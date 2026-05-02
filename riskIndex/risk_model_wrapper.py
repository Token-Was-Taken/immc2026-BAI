#!/usr/bin/env python3
"""
Risk Model Wrapper Script.

This script provides a formal wrapper for the risk model that:
1. Reads input data from data files (JSON/CSV)
2. Reads configuration from config files (JSON)
3. Calculates composite risk
4. Performs normalization
5. Saves results to output files

Usage:
    python risk_model_wrapper.py --data data.json --config config.json --output results.json
"""

import sys
import os
import json
import argparse
import math
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Tuple

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from risk_model.core import (
    Grid,
    SpeciesDensity,
    Season,
    Environment,
    VegetationType,
    TimeContext,
)
from risk_model.risk import (
    RiskModel,
    GridRiskResult,
)
from risk_model.config import (
    RiskWeights,
    WeightManager,
    ModelConfig,
)
from risk_model.risk import (
    HumanRiskWeights,
    EnvironmentalRiskWeights,
)


# ============================================================================
# Data File Format Definitions
# ============================================================================

@dataclass
class GridInputData:
    """Input data for a single grid cell."""
    grid_id: str
    x: int  # Column index (0-based, from left to right)
    y: int  # Row index (0-based, from bottom to top)
    fire_risk: float
    terrain_complexity: float
    vegetation_type: str  # "GRASSLAND", "FOREST", "SHRUB"
    species_densities: Dict[str, float]  # species_name -> density


@dataclass
class TimeInputData:
    """Input data for time context."""
    hour_of_day: int
    season: str  # "DRY", "RAINY"


@dataclass
class MapConfig:
    """Map configuration for automatic distance calculation."""
    map_width: int  # Number of columns
    map_height: int  # Number of rows
    boundary_type: str  # "RECTANGLE"
    road_locations: List[Tuple[int, int]]  # List of (x, y) grid coordinates
    water_locations: List[Tuple[int, int]]  # List of (x, y) grid coordinates
    boundary_locations: Optional[List[Tuple[int, int]]] = None  # 不规则边界格子坐标，None 时用矩形边界


@dataclass
class ModelInputData:
    """Complete input data for the model."""
    map_config: MapConfig
    grids: List[GridInputData]
    time: TimeInputData


@dataclass
class ModelConfigData:
    """Configuration data for the model."""
    risk_weights: Optional[Dict[str, float]] = None
    human_risk_weights: Optional[Dict[str, float]] = None
    environmental_risk_weights: Optional[Dict[str, float]] = None
    temporal_weights: Optional[Dict[str, float]] = None


# ============================================================================
# Distance Calculator
# ============================================================================

class DistanceCalculator:
    """Calculate distances using grid coordinates."""

    def __init__(self, map_config: MapConfig):
        self.map_width = map_config.map_width
        self.map_height = map_config.map_height
        self.boundary_type = map_config.boundary_type
        self.road_locations = map_config.road_locations
        self.water_locations = map_config.water_locations
        self.boundary_locations = map_config.boundary_locations  # 不规则边界格子坐标

    def euclidean_distance(self, x1: int, y1: int, x2: int, y2: int) -> float:
        """Calculate Euclidean distance between two grid cells."""
        return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

    def calculate_distance_to_boundary(self, x: int, y: int) -> float:
        """
        Calculate distance to nearest boundary.
        若提供了 boundary_locations，使用最近边界格子的欧氏距离；
        否则按 boundary_type 计算（RECTANGLE 用矩形边界，其他返回 0.5）。
        """
        if self.boundary_locations:
            return self.calculate_distance_to_feature(x, y, self.boundary_locations)

        if self.boundary_type == "RECTANGLE":
            dist_left = x
            dist_right = (self.map_width - 1) - x
            dist_bottom = y
            dist_top = (self.map_height - 1) - y

            min_dist_grid = min(dist_left, dist_right, dist_bottom, dist_top)

            max_possible_dist = max(self.map_width, self.map_height) / 2
            normalized_dist = min_dist_grid / max_possible_dist if max_possible_dist > 0 else 0.0

            return 1.0 - min(normalized_dist, 1.0)
        else:
            return 0.5

    def calculate_distance_to_feature(self, x: int, y: int, feature_locations: List[Tuple[int, int]]) -> float:
        """Calculate normalized distance to nearest feature (road or water)."""
        if not feature_locations:
            return 0.0  # No feature means 0 risk from this feature

        min_dist = float('inf')
        for (fx, fy) in feature_locations:
            dist = self.euclidean_distance(x, y, fx, fy)
            if dist < min_dist:
                min_dist = dist

        # Normalize to [0, 1]
        max_possible_dist = math.sqrt(self.map_width ** 2 + self.map_height ** 2)
        normalized_dist = min_dist / max_possible_dist if max_possible_dist > 0 else 0.0

        # Invert: closer to feature = higher risk (0 = far, 1 = at feature)
        return 1.0 - min(normalized_dist, 1.0)

    def calculate_distances(self, x: int, y: int) -> Tuple[float, float, float]:
        """Calculate all three distances for a grid cell."""
        dist_boundary = self.calculate_distance_to_boundary(x, y)
        dist_road = self.calculate_distance_to_feature(x, y, self.road_locations)
        dist_water = self.calculate_distance_to_feature(x, y, self.water_locations)
        return dist_boundary, dist_road, dist_water


# ============================================================================
# Data Loading Functions
# ============================================================================

def load_data_from_json(filepath: str) -> ModelInputData:
    """
    Load input data from a JSON file.

    Expected JSON format:
    {
        "map_config": {
            "map_width": 10,
            "map_height": 10,
            "boundary_type": "RECTANGLE",
            "road_locations": [[2, 3], [5, 7]],
            "water_locations": [[1, 1], [8, 5]]
        },
        "grids": [
            {
                "grid_id": "A01",
                "x": 0,
                "y": 0,
                "fire_risk": 0.5,
                "terrain_complexity": 0.3,
                "vegetation_type": "GRASSLAND",
                "species_densities": {
                    "rhino": 0.7,
                    "elephant": 0.5,
                    "bird": 0.8
                }
            }
        ],
        "time": {
            "hour_of_day": 22,
            "season": "RAINY"
        }
    }

    Coordinate system:
    - Origin at bottom-left grid cell center
    - x: column index, increases to the right
    - y: row index, increases upward

    Args:
        filepath: Path to JSON file

    Returns:
        ModelInputData object
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Load map config
    map_config_data = data.get("map_config", {})
    map_config = MapConfig(
        map_width=map_config_data.get("map_width", 10),
        map_height=map_config_data.get("map_height", 10),
        boundary_type=map_config_data.get("boundary_type", "RECTANGLE"),
        road_locations=[tuple(loc) for loc in map_config_data.get("road_locations", [])],
        water_locations=[tuple(loc) for loc in map_config_data.get("water_locations", [])]
    )

    # Load grids
    grids_data = data.get("grids", [])
    grids = []
    for g in grids_data:
        grids.append(GridInputData(
            grid_id=g.get("grid_id", ""),
            x=g.get("x", 0),
            y=g.get("y", 0),
            fire_risk=g.get("fire_risk", 0.0),
            terrain_complexity=g.get("terrain_complexity", 0.0),
            vegetation_type=g.get("vegetation_type", "GRASSLAND"),
            species_densities=g.get("species_densities", {})
        ))

    # Load time
    time_data = data.get("time", {})
    time = TimeInputData(
        hour_of_day=time_data.get("hour_of_day", 12),
        season=time_data.get("season", "DRY")
    )

    return ModelInputData(map_config=map_config, grids=grids, time=time)


def load_config_from_json(filepath: str) -> ModelConfigData:
    """
    Load configuration from a JSON file.

    Expected JSON format:
    {
        "risk_weights": {
            "human_weight": 0.4,
            "environmental_weight": 0.3,
            "density_weight": 0.3
        },
        "human_risk_weights": {
            "boundary_weight": 0.4,
            "road_weight": 0.35,
            "water_weight": 0.25
        },
        "environmental_risk_weights": {
            "fire_weight": 0.6,
            "terrain_weight": 0.4
        }
    }

    All fields are optional - defaults will be used for missing fields.

    Args:
        filepath: Path to JSON file

    Returns:
        ModelConfigData object
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    return ModelConfigData(
        risk_weights=data.get("risk_weights"),
        human_risk_weights=data.get("human_risk_weights"),
        environmental_risk_weights=data.get("environmental_risk_weights")
    )


# ============================================================================
# Data Conversion Functions
# ============================================================================

def convert_grid_input(
    grid_data: GridInputData,
    distance_calculator: DistanceCalculator
) -> Tuple[Grid, Environment, SpeciesDensity]:
    """
    Convert GridInputData to model input objects.

    Args:
        grid_data: Grid input data
        distance_calculator: Calculator for automatic distance computation

    Returns:
        Tuple of (Grid, Environment, SpeciesDensity)
    """
    # Calculate distances automatically from coordinates
    dist_boundary, dist_road, dist_water = distance_calculator.calculate_distances(
        grid_data.x, grid_data.y
    )

    # Create Grid object
    grid = Grid(
        grid_id=grid_data.grid_id,
        x=float(grid_data.x),
        y=float(grid_data.y),
        distance_to_boundary=dist_boundary,
        distance_to_road=dist_road,
        distance_to_water=dist_water
    )

    # Create Environment object
    veg_type_map = {
        "GRASSLAND": VegetationType.GRASSLAND,
        "FOREST": VegetationType.FOREST,
        "SHRUB": VegetationType.SHRUB
    }
    veg_type = veg_type_map.get(grid_data.vegetation_type, VegetationType.GRASSLAND)

    environment = Environment(
        fire_risk=grid_data.fire_risk,
        terrain_complexity=grid_data.terrain_complexity,
        vegetation_type=veg_type
    )

    # Create SpeciesDensity object
    density = SpeciesDensity(densities=grid_data.species_densities)

    return grid, environment, density


def convert_time_input(time_data: TimeInputData) -> TimeContext:
    """
    Convert TimeInputData to TimeContext.

    Args:
        time_data: Time input data

    Returns:
        TimeContext object
    """
    season_map = {
        "DRY": Season.DRY,
        "RAINY": Season.RAINY
    }
    season = season_map.get(time_data.season, Season.DRY)

    return TimeContext(
        hour_of_day=time_data.hour_of_day,
        season=season
    )


def create_model_from_config(config_data: ModelConfigData) -> RiskModel:
    """
    Create RiskModel from configuration data.

    Args:
        config_data: Model configuration data

    Returns:
        RiskModel instance
    """
    from risk_model.risk import (
        CompositeRiskCalculator,
        HumanRiskCalculator,
        EnvironmentalRiskCalculator,
    )
    from risk_model.risk.temporal import (
        DiurnalFactorCalculator,
        SeasonalFactorCalculator,
        TemporalFactorCalculator,
        DiurnalMode,
    )

    weight_manager = WeightManager()

    if config_data.risk_weights:
        weight_manager.set_risk_weights(
            human_weight=config_data.risk_weights.get("human_weight"),
            environmental_weight=config_data.risk_weights.get("environmental_weight"),
            density_weight=config_data.risk_weights.get("density_weight")
        )

    human_weights = None
    if config_data.human_risk_weights:
        human_weights = HumanRiskWeights(
            boundary_weight=config_data.human_risk_weights.get("boundary_weight", 0.2),
            road_weight=config_data.human_risk_weights.get("road_weight", 0.3),
            water_weight=config_data.human_risk_weights.get("water_weight", 0.5)
        )
    human_calc = HumanRiskCalculator(weights=human_weights)

    env_weights = None
    if config_data.environmental_risk_weights:
        env_weights = EnvironmentalRiskWeights(
            fire_weight=config_data.environmental_risk_weights.get("fire_weight", 0.6),
            terrain_weight=config_data.environmental_risk_weights.get("terrain_weight", 0.4)
        )
    env_calc = EnvironmentalRiskCalculator(weights=env_weights)

    temporal_calc = None
    if config_data.temporal_weights:
        tw = config_data.temporal_weights
        diurnal_calc = DiurnalFactorCalculator(
            daytime_factor=tw.get("daytime_factor", 1.0),
            nighttime_factor=tw.get("nighttime_factor", 1.3),
            gamma=tw.get("gamma", 0.3)
        )
        seasonal_calc = SeasonalFactorCalculator(
            dry_season_factor=tw.get("dry_season_factor", 1.0),
            rainy_season_factor=tw.get("rainy_season_factor", 1.2)
        )
        temporal_calc = TemporalFactorCalculator(
            diurnal_calculator=diurnal_calc,
            seasonal_calculator=seasonal_calc
        )

    composite_calc = CompositeRiskCalculator(
        weight_manager=weight_manager,
        human_calculator=human_calc,
        environmental_calculator=env_calc,
        temporal_calculator=temporal_calc
    )

    return RiskModel(composite_calculator=composite_calc)


# ============================================================================
# Result Saving Functions
# ============================================================================

def save_results_to_json(
    results: List[GridRiskResult],
    output_filepath: str,
    grid_coordinates: Optional[List[Tuple[int, int]]] = None
) -> None:
    """
    Save risk calculation results to a JSON file.

    Args:
        results: List of GridRiskResult objects
        output_filepath: Path to output JSON file
        grid_coordinates: Optional list of (x, y) coordinates for each grid
    """
    output_data = {
        "results": []
    }

    for idx, result in enumerate(results):
        result_dict = {
            "grid_id": result.grid_id,
            "raw_risk": result.raw_risk,
            "normalized_risk": result.normalized_risk
        }

        # Add coordinates if available
        if grid_coordinates and idx < len(grid_coordinates):
            result_dict["x"], result_dict["y"] = grid_coordinates[idx]

        if result.components:
            result_dict["components"] = {
                "human_risk": result.components.human_risk,
                "environmental_risk": result.components.environmental_risk,
                "density_value": result.components.density_value,
                "diurnal_factor": result.components.diurnal_factor,
                "seasonal_factor": result.components.seasonal_factor,
                "temporal_factor": result.components.temporal_factor
            }

        output_data["results"].append(result_dict)

    with open(output_filepath, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2)


# ============================================================================
# Main Wrapper Function
# ============================================================================

def run_risk_model(
    data_file: str,
    config_file: Optional[str] = None,
    output_file: Optional[str] = None,
    use_temporal_factors: bool = False
) -> List[GridRiskResult]:
    """
    Run the risk model with data from files.

    Args:
        data_file: Path to input data JSON file
        config_file: Optional path to config JSON file
        output_file: Optional path to output JSON file
        use_temporal_factors: Whether to apply diurnal/seasonal/temporal factors (default: False)

    Returns:
        List of GridRiskResult objects
    """
    print("="*70)
    print("  RISK MODEL WRAPPER")
    print("="*70)

    # Step 1: Load input data
    print(f"\n[1/6] Loading input data from: {data_file}")
    input_data = load_data_from_json(data_file)
    print(f"  Loaded {len(input_data.grids)} grid cells")
    print(f"  Map size: {input_data.map_config.map_width} x {input_data.map_config.map_height}")
    print(f"  Roads: {len(input_data.map_config.road_locations)} locations")
    print(f"  Water sources: {len(input_data.map_config.water_locations)} locations")
    print(f"  Time: {input_data.time.hour_of_day:02d}:00, {input_data.time.season} season")
    print(f"  Temporal factors: {'ENABLED' if use_temporal_factors else 'DISABLED (default)'}")

    # Step 2: Create distance calculator
    print(f"\n[2/6] Creating distance calculator")
    distance_calculator = DistanceCalculator(input_data.map_config)
    print("  Distance calculator created")

    # Step 3: Load configuration
    model_config = ModelConfigData()
    if config_file:
        print(f"\n[3/6] Loading configuration from: {config_file}")
        model_config = load_config_from_json(config_file)
        print("  Configuration loaded")
    else:
        print(f"\n[3/6] Using default configuration")

    # Step 4: Create risk model
    print(f"\n[4/6] Creating risk model")
    model = create_model_from_config(model_config)
    print("  Model created")

    # Step 5: Convert input data
    print(f"\n[5/6] Converting input data")
    grid_data_list = []
    grid_coordinates = []
    for grid_input in input_data.grids:
        grid, env, density = convert_grid_input(grid_input, distance_calculator)
        grid_data_list.append((grid, env, density))
        grid_coordinates.append((grid_input.x, grid_input.y))
    time_context = convert_time_input(input_data.time)
    print(f"  Converted {len(grid_data_list)} grid cells")

    # Step 6: Calculate risk
    print(f"\n[6/6] Calculating risk")
    results = model.calculate_batch(
        grid_data_list,
        time_context,
        use_temporal_factors=use_temporal_factors
    )
    print(f"  Calculated risk for {len(results)} grid cells")

    # Save results if output file specified
    if output_file:
        print(f"\nSaving results to: {output_file}")
        save_results_to_json(results, output_file, grid_coordinates)
        print("  Results saved")

    # Print summary
    print("\n" + "="*70)
    print("  SUMMARY")
    print("="*70)

    if results:
        norm_risks = [r.normalized_risk for r in results if r.normalized_risk is not None]
        if norm_risks:
            print(f"  Min normalized risk: {min(norm_risks):.4f}")
            print(f"  Max normalized risk: {max(norm_risks):.4f}")
            print(f"  Avg normalized risk: {sum(norm_risks)/len(norm_risks):.4f}")

            high_risk = sum(1 for r in norm_risks if r > 0.7)
            print(f"  High risk cells (>0.7): {high_risk}/{len(norm_risks)}")

    print("="*70)

    return results


# ============================================================================
# Command Line Interface
# ============================================================================

def main():
    """Main function for command line usage."""
    parser = argparse.ArgumentParser(
        description="Risk Model Wrapper - Calculate composite risk with normalization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example data.json format:
{
    "map_config": {
        "map_width": 10,
        "map_height": 10,
        "boundary_type": "RECTANGLE",
        "road_locations": [[2, 3], [5, 7]],
        "water_locations": [[1, 1], [8, 5]]
    },
    "grids": [
        {
            "grid_id": "A01",
            "x": 0,
            "y": 0,
            "fire_risk": 0.5,
            "terrain_complexity": 0.3,
            "vegetation_type": "GRASSLAND",
            "species_densities": {
                "rhino": 0.7,
                "elephant": 0.5,
                "bird": 0.8
            }
        }
    ],
    "time": {
        "hour_of_day": 22,
        "season": "RAINY"
    }
}

Coordinate system:
- Origin at bottom-left grid cell center
- x: column index (0-based), increases to the right
- y: row index (0-based), increases upward

Example config.json format (all fields optional):
{
    "risk_weights": {
        "human_weight": 0.4,
        "environmental_weight": 0.3,
        "density_weight": 0.3
    },
    "human_risk_weights": {
        "boundary_weight": 0.4,
        "road_weight": 0.35,
        "water_weight": 0.25
    },
    "environmental_risk_weights": {
        "fire_weight": 0.6,
        "terrain_weight": 0.4
    }
}
        """
    )

    parser.add_argument(
        "--data", "-d",
        required=True,
        help="Path to input data JSON file"
    )
    parser.add_argument(
        "--config", "-c",
        help="Path to configuration JSON file (optional, uses defaults if not provided)"
    )
    parser.add_argument(
        "--output", "-o",
        help="Path to output results JSON file (optional)"
    )
    parser.add_argument(
        "--use-temporal",
        action="store_true",
        help="Enable diurnal/seasonal/temporal factors (default: disabled)"
    )
    parser.add_argument(
        "--no-temporal",
        action="store_true",
        help="Disable diurnal/seasonal/temporal factors (default)"
    )

    args = parser.parse_args()

    # Determine if temporal factors should be used
    use_temporal_factors = args.use_temporal and not args.no_temporal

    try:
        run_risk_model(
            data_file=args.data,
            config_file=args.config,
            output_file=args.output,
            use_temporal_factors=use_temporal_factors
        )
        return 0
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
