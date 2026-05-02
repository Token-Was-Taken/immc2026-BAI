import json
import sys
import os

_RISK_SRC = os.path.join(os.path.dirname(__file__), '..', 'riskIndex', 'src')
sys.path.insert(0, os.path.abspath(_RISK_SRC))
_RISK_DIR = os.path.join(os.path.dirname(__file__), '..', 'riskIndex')
sys.path.insert(0, os.path.abspath(_RISK_DIR))

from risk_model_wrapper import (
    MapConfig, GridInputData, TimeInputData, ModelConfigData,
    DistanceCalculator, convert_grid_input, convert_time_input, create_model_from_config,
)
from risk_model.core.species import Species
from risk_model.risk.density import DensityRiskCalculator
from risk_model.risk.composite import CompositeRiskCalculator
from risk_model.risk.human import HumanRiskCalculator
from risk_model.risk.environmental import EnvironmentalRiskCalculator
from risk_model.config import WeightManager
from risk_model.risk import RiskModel, HumanRiskWeights, EnvironmentalRiskWeights

def load_and_compute(fname):
    path = os.path.join(os.path.dirname(__file__), fname)
    with open(path) as f:
        data = json.load(f)
    
    # Setup
    map_cfg_raw = data['map_config']
    boundary_locations = map_cfg_raw.get('boundary_locations')
    if boundary_locations:
        normalized = []
        for item in boundary_locations:
            if isinstance(item, dict):
                normalized.append((item['x'], item['y']))
            else:
                normalized.append(tuple(item))
        boundary_locations = normalized

    map_config = MapConfig(
        map_width=map_cfg_raw['map_width'],
        map_height=map_cfg_raw['map_height'],
        boundary_type=map_cfg_raw.get('boundary_type', 'RECTANGLE'),
        road_locations=[tuple(p) for p in map_cfg_raw.get('road_locations', [])],
        water_locations=[tuple(p) for p in map_cfg_raw.get('water_locations', [])],
        boundary_locations=boundary_locations
    )

    time_raw = data.get('time', {})
    time_input = TimeInputData(
        hour_of_day=time_raw.get('hour_of_day', 12),
        season=time_raw.get('season', 'DRY')
    )

    distance_calc = DistanceCalculator(map_config)
    time_context = convert_time_input(time_input)

    cfg_raw = data.get('risk_model_config', {})
    model_config = ModelConfigData(
        risk_weights=cfg_raw.get('risk_weights'),
        human_risk_weights=cfg_raw.get('human_risk_weights'),
        environmental_risk_weights=cfg_raw.get('environmental_risk_weights'),
        temporal_weights=cfg_raw.get('temporal_weights')
    )
    model = create_model_from_config(model_config)

    if 'species_config' in data:
        species_cfg = {}
        for name, cfg in data['species_config'].items():
            species_cfg[name] = Species(
                name=name,
                weight=float(cfg.get('weight', 0.3)),
                rainy_season_multiplier=float(cfg.get('rainy_season_multiplier', 1.0)),
                dry_season_multiplier=float(cfg.get('dry_season_multiplier', 1.0))
            )
        weight_manager = WeightManager()
        if cfg_raw.get('risk_weights'):
            weight_manager.set_risk_weights(**cfg_raw['risk_weights'])

        human_weights = None
        if cfg_raw.get('human_risk_weights'):
            human_weights = HumanRiskWeights(**cfg_raw['human_risk_weights'])

        env_weights = None
        if cfg_raw.get('environmental_risk_weights'):
            env_weights = EnvironmentalRiskWeights(**cfg_raw['environmental_risk_weights'])

        from risk_model.risk.temporal import DiurnalFactorCalculator, SeasonalFactorCalculator, TemporalFactorCalculator
        temporal_calc = None
        if cfg_raw.get('temporal_weights'):
            tw = cfg_raw['temporal_weights']
            temporal_calc = TemporalFactorCalculator(
                diurnal_calculator=DiurnalFactorCalculator(
                    daytime_factor=tw.get('daytime_factor', 1.0),
                    nighttime_factor=tw.get('nighttime_factor', 1.3),
                    gamma=tw.get('gamma', 0.3)
                ),
                seasonal_calculator=SeasonalFactorCalculator(
                    dry_season_factor=tw.get('dry_season_factor', 1.0),
                    rainy_season_factor=tw.get('rainy_season_factor', 1.2)
                )
            )

        composite_calc = CompositeRiskCalculator(
            weight_manager=weight_manager,
            human_calculator=HumanRiskCalculator(weights=human_weights),
            environmental_calculator=EnvironmentalRiskCalculator(weights=env_weights),
            density_calculator=DensityRiskCalculator(species_config=species_cfg),
            temporal_calculator=temporal_calc
        )
        model = RiskModel(composite_calculator=composite_calc)

    grid_data_list = []
    id_order = []
    for g in data['grids']:
        gid = g['grid_id']
        grid_input = GridInputData(
            grid_id=str(gid),
            x=g.get('x', 0),
            y=g.get('y', 0),
            fire_risk=float(g.get('fire_risk', 0.0)),
            terrain_complexity=float(g.get('terrain_complexity', 0.0)),
            vegetation_type=g.get('vegetation_type', 'GRASSLAND'),
            species_densities=g.get('species_densities', {})
        )
        grid_obj, env_obj, density_obj = convert_grid_input(grid_input, distance_calc)
        grid_data_list.append((grid_obj, env_obj, density_obj))
        id_order.append(gid)

    use_temporal = data.get('use_temporal_factors', False)
    results = model.calculate_batch(grid_data_list, time_context, use_temporal_factors=use_temporal)
    
    # Get raw and normalized risks
    raw_risks = [r.raw_risk for r in results]
    norm_risks = [r.normalized_risk for r in results]
    
    return {
        'hour': time_raw.get('hour_of_day'),
        'use_temporal': use_temporal,
        'raw_min': min(raw_risks),
        'raw_max': max(raw_risks),
        'raw_mean': sum(raw_risks) / len(raw_risks),
        'norm_min': min(norm_risks),
        'norm_max': max(norm_risks),
        'norm_mean': sum(norm_risks) / len(norm_risks),
    }

print("Comparing day vs night with temporal factors:")
print()

day_result = load_and_compute('input-day-rainy.json')
print(f"Day (hour={day_result['hour']}):")
print(f"  Raw risks:        min={day_result['raw_min']:.6f}  max={day_result['raw_max']:.6f}  mean={day_result['raw_mean']:.6f}")
print(f"  Normalized risks: min={day_result['norm_min']:.6f}  max={day_result['norm_max']:.6f}  mean={day_result['norm_mean']:.6f}")
print()

night_result = load_and_compute('input-night-rainy.json')
print(f"Night (hour={night_result['hour']}):")
print(f"  Raw risks:        min={night_result['raw_min']:.6f}  max={night_result['raw_max']:.6f}  mean={night_result['raw_mean']:.6f}")
print(f"  Normalized risks: min={night_result['norm_min']:.6f}  max={night_result['norm_max']:.6f}  mean={night_result['norm_mean']:.6f}")
print()

print(f"Ratio (Night raw / Day raw):")
print(f"  Min:  {night_result['raw_min'] / day_result['raw_min']:.4f}")
print(f"  Max:  {night_result['raw_max'] / day_result['raw_max']:.4f}")
print(f"  Mean: {night_result['raw_mean'] / day_result['raw_mean']:.4f}")

