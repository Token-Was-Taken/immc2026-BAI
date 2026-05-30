"""
Protection Pipeline

Input: map-grid JSON compatible with the risk model.
Flow: compute normalized risk with riskIndex -> optimize deployment with DSSA -> write JSON output.
"""

import json
import sys
import os
import numpy as np
from typing import Dict, Tuple

_RISK_SRC = os.path.join(os.path.dirname(__file__), '..', 'riskIndex', 'src')
_RISK_DIR = os.path.join(os.path.dirname(__file__), '..', 'riskIndex')

if os.path.isdir(os.path.abspath(_RISK_SRC)):
    sys.path.insert(0, os.path.abspath(_RISK_SRC))
if os.path.isdir(os.path.abspath(_RISK_DIR)):
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

from data_loader import DataLoader, GridData
from grid_model import HexGridModel
from coverage_model import CoverageModel
from coverage_model_vectorized import VectorizedCoverageModel
from dssa_optimizer import DSSAOptimizer, DSSAConfig
from coverage_model import DeploymentSolution


def load_input(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    validate_input_schema(data, path)
    return data


def validate_input_schema(data: dict, path: str = "<input>"):
    """Validate that input JSON contains all required keys with clear error messages."""
    required_top = ['grids', 'constraints', 'map_config']
    missing = [k for k in required_top if k not in data]
    if missing:
        raise ValueError(f"Input JSON '{path}' is missing required top-level keys: {missing}")

    if not isinstance(data['grids'], list) or len(data['grids']) == 0:
        raise ValueError(f"Input JSON '{path}': 'grids' must be a non-empty list")

    required_grid_keys = ['grid_id', 'q', 'r', 'terrain_type']
    for i, grid in enumerate(data['grids'][:5]):
        grid_missing = [k for k in required_grid_keys if k not in grid]
        if grid_missing:
            raise ValueError(f"Input JSON '{path}': grid[{i}] is missing keys: {grid_missing}")

    required_constraints = ['total_patrol', 'total_camps', 'total_cameras', 'total_drones']
    c = data['constraints']
    c_missing = [k for k in required_constraints if k not in c]
    if c_missing:
        raise ValueError(f"Input JSON '{path}': 'constraints' is missing keys: {c_missing}")


def load_warm_start_solution(output_json_path: str) -> DeploymentSolution:
    with open(output_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    cameras = {}
    camps = {}
    drones = {}
    rangers = {}
    fences = {}

    for grid in data.get('grids', []):
        gid = grid['grid_id']
        dep = grid.get('deployment', {})
        if dep.get('camera', 0) > 0:
            cameras[gid] = dep['camera']
        if dep.get('drone', 0) > 0:
            drones[gid] = dep['drone']
        if dep.get('camp', 0) > 0:
            camps[gid] = dep['camp']
        if dep.get('patrol_rangers', 0) > 0:
            rangers[gid] = dep['patrol_rangers']
        fence_info = grid.get('fences', {})
        if fence_info and fence_info.get('fence_count', 0) > 0:
            for direction in fence_info.get('boundary_edge_list', []):
                fences[(gid, direction)] = 1

    return DeploymentSolution(
        cameras=cameras,
        camps=camps,
        drones=drones,
        rangers=rangers,
        fences=fences
    )


def build_species_config(species_cfg: dict) -> dict:
    result = {}
    for name, cfg in species_cfg.items():
        result[name] = Species(
            name=name,
            weight=float(cfg.get('weight', 0.3)),
            rainy_season_multiplier=float(cfg.get('rainy_season_multiplier', 1.0)),
            dry_season_multiplier=float(cfg.get('dry_season_multiplier', 1.0))
        )
    return result


def compute_risk_with_riskindex(data: dict) -> Tuple[Dict[int, float], Dict[int, float], Dict[int, float]]:
    """
    Compute normalized risk, raw risk and temporal factors.

    Returns:
        Tuple of (risk_map, temporal_factor_map, raw_risk_map)
        - risk_map: normalized risk values [0, 1]
        - temporal_factor_map: T_t × S_t (diurnal × seasonal factors)
        - raw_risk_map: raw (unnormalized) risk values
    """
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
        species_cfg = build_species_config(data['species_config'])
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
        try:
            fire_risk = float(g.get('fire_risk', 0.0))
        except (ValueError, TypeError):
            raise ValueError(f"Grid {gid}: 'fire_risk' must be numeric, got '{g.get('fire_risk')}'")
        try:
            terrain_complexity = float(g.get('terrain_complexity', 0.0))
        except (ValueError, TypeError):
            raise ValueError(f"Grid {gid}: 'terrain_complexity' must be numeric, got '{g.get('terrain_complexity')}'")
        grid_input = GridInputData(
            grid_id=str(gid),
            x=g.get('x', 0),
            y=g.get('y', 0),
            fire_risk=fire_risk,
            terrain_complexity=terrain_complexity,
            vegetation_type=g.get('vegetation_type', 'GRASSLAND'),
            species_densities=g.get('species_densities', {})
        )
        grid_obj, env_obj, density_obj = convert_grid_input(grid_input, distance_calc)
        grid_data_list.append((grid_obj, env_obj, density_obj))
        id_order.append(gid)

    use_temporal = data.get('use_temporal_factors', False)
    results = model.calculate_batch(grid_data_list, time_context, use_temporal_factors=use_temporal)
    
    risk_map = {id_order[i]: float(r.normalized_risk) for i, r in enumerate(results)}
    raw_risk_map = {id_order[i]: float(r.raw_risk) for i, r in enumerate(results)}

    # Extract temporal factors from components
    temporal_factor_map = {}
    for i, r in enumerate(results):
        gid = id_order[i]
        if r.components:
            temporal_factor = r.components.temporal_factor
        else:
            temporal_factor = 1.0
        temporal_factor_map[gid] = temporal_factor

    return risk_map, temporal_factor_map, raw_risk_map


def build_data_loader(data: dict, risk_map: Dict[int, float], temporal_factor_map: Dict[int, float] = None) -> DataLoader:
    """Build data loader with temporal factors for time-aware fitness."""
    if temporal_factor_map is None:
        temporal_factor_map = {gid: 1.0 for gid in risk_map.keys()}
    
    loader = DataLoader()
    loader.grids = [
        GridData(
            grid_id=g['grid_id'],
            q=g['q'],
            r=g['r'],
            terrain_type=g.get('terrain_type', 'SparseGrass'),
            risk=risk_map.get(g['grid_id'], 0.0),
            temporal_factor=temporal_factor_map.get(g['grid_id'], 1.0),
            species_densities=g.get('species_densities', {})
        )
        for g in data['grids']
    ]

    cp = data.get('coverage_params', {})
    loader.set_coverage_parameters(
        patrol_radius=cp.get('patrol_radius', 5.0),
        drone_radius=cp.get('drone_radius', 8.0),
        camera_radius=cp.get('camera_radius', 3.0),
        fence_protection=cp.get('fence_protection', 0.5),
        wp=cp.get('wp', 0.3),
        wd=cp.get('wd', 0.3),
        wc=cp.get('wc', 0.2),
        wf=cp.get('wf', 0.2),
        alpha_pd=cp.get('alpha_pd', 0.4),
        alpha_pc=cp.get('alpha_pc', 0.15)
    )

    c = data['constraints']
    loader.set_constraints(
        total_patrol=c['total_patrol'],
        total_camps=c['total_camps'],
        max_rangers_per_camp=c['max_rangers_per_camp'],
        total_cameras=c['total_cameras'],
        total_drones=c['total_drones'],
        total_fence_length=float(c['total_fence_length']),
        max_cameras_per_grid=c.get('max_cameras_per_grid', 1),
        max_drones_per_grid=c.get('max_drones_per_grid', 1),
        max_camps_per_grid=c.get('max_camps_per_grid', 1),
        max_rangers_per_grid=c.get('max_rangers_per_grid', 1),
        max_fences_per_grid=c.get('max_fences_per_grid', 6)
    )

    temp_grid_model = HexGridModel(loader.grids)
    edge_grids = temp_grid_model.get_edge_grids()
    del temp_grid_model
    loader.initialize_deployment_matrix(edge_grids=edge_grids)
    loader.initialize_visibility_params()
    loader.initialize_coverage_effectiveness(data.get('coverage_effectiveness'))
    return loader


def run_pipeline(input_path: str, output_path: str, vectorized: bool = False, allow_partial_deployment: bool = False, freeze_resources: str = None, dssa_config=None, out_dir=None, warm_start_path: str = None, max_iterations: int = None, use_gpu: bool = True, only_output_on_best_change: bool = True):
    print(f"[1/4] Read input: {input_path}")
    data = load_input(input_path)

    print("[2/4] Compute normalized risk with riskIndex...")
    risk_map, temporal_factor_map, raw_risk_map = compute_risk_with_riskindex(data)

    print("[3/4] Build optimization model and run DSSA...")
    loader = build_data_loader(data, risk_map, temporal_factor_map)

    if vectorized:
        grid_model = HexGridModel(loader.grids)
        print("      [VECTOR] 使用向量化覆盖模型 (Vectorized Coverage Model)")
        if use_gpu:
            print("      [GPU] GPU 加速已启用 (OpenCL)")
    else:
        grid_model = HexGridModel(loader.grids)
    model_class = VectorizedCoverageModel if vectorized else CoverageModel
    coverage_model = model_class(
        grid_model,
        loader.coverage_params,
        loader.deployment_matrix,
        loader.visibility_params,
        loader.coverage_effectiveness,
        use_gpu=use_gpu,
    ) if vectorized else model_class(
        grid_model,
        loader.coverage_params,
        loader.deployment_matrix,
        loader.visibility_params,
        loader.coverage_effectiveness
    )

    constraints = {
        'total_patrol': loader.constraints.total_patrol,
        'total_camps': loader.constraints.total_camps,
        'max_rangers_per_camp': loader.constraints.max_rangers_per_camp,
        'total_cameras': loader.constraints.total_cameras,
        'total_drones': loader.constraints.total_drones,
        'total_fence_length': loader.constraints.total_fence_length,
        'max_cameras_per_grid': loader.constraints.max_cameras_per_grid,
        'max_drones_per_grid': loader.constraints.max_drones_per_grid,
        'max_camps_per_grid': loader.constraints.max_camps_per_grid,
        'max_fences_per_grid': loader.constraints.max_fences_per_grid,
    }

    fixed_fences = {}

    dc = data.get('dssa_config', {})
    # 如果 CLI 提供了 out_dir，则使用 CLI 提供的
    # 否则优先使用 JSON 中的配置，或者使用默认值
    output_dir = out_dir if out_dir is not None else dc.get('output_dir')
    if output_dir and not os.path.isabs(output_dir):
        # 如果是相对路径，基于当前工作目录解析
        output_dir = os.path.abspath(output_dir)
    if dssa_config is None:
        dssa_config = DSSAConfig(
            population_size=dc.get('population_size', 50),
            max_iterations=max_iterations if max_iterations is not None else dc.get('max_iterations', 200),
            producer_ratio=dc.get('producer_ratio', 0.2),
            scout_ratio=dc.get('scout_ratio', 0.2),
            ST=dc.get('ST', 0.8),
            R2=dc.get('R2', 0.5),
            use_time_aware_fitness=dc.get('use_time_aware_fitness', False),
            output_dir=output_dir,
            force_full_deployment=dc.get('force_full_deployment', True),
            use_risk_priority=dc.get('use_risk_priority', False),
            high_risk_percentage=dc.get('high_risk_percentage', 0.3),
            high_risk_perturbation_priority=dc.get('high_risk_perturbation_priority', 0.7),
            use_marginal_contribution_repair=dc.get('use_marginal_contribution_repair', False),
            skip_conflict_resolution=dc.get('skip_conflict_resolution', False),
            fitness_workers=dc.get('fitness_workers', 16),
            output_interval=dc.get('output_interval', 1),
            only_output_on_best_change=only_output_on_best_change,
        )
    if dssa_config.output_dir is None:
        dssa_config.output_dir = output_dir
    if dssa_config.force_full_deployment is None:
        dssa_config.force_full_deployment = dc.get('force_full_deployment', True)
    if dssa_config.use_risk_priority is None:
        dssa_config.use_risk_priority = dc.get('use_risk_priority', False)
    if dssa_config.high_risk_percentage is None:
        dssa_config.high_risk_percentage = dc.get('high_risk_percentage', 0.3)
    if dssa_config.high_risk_perturbation_priority is None:
        dssa_config.high_risk_perturbation_priority = dc.get('high_risk_perturbation_priority', 0.7)
    if max_iterations is not None:
        dssa_config.max_iterations = max_iterations

    # 部署模式优先级：CLI --allow-partial-deployment > JSON dssa_config.force_full_deployment > 默认 True
    if allow_partial_deployment:
        force_full_deployment = False
    else:
        force_full_deployment = dssa_config.force_full_deployment if dssa_config.force_full_deployment is not None else True
    if force_full_deployment:
        print("      [FORCE] 强制部署模式：所有资源将被部署到上限")
    else:
        print("      [PARTIAL] 部分部署模式：允许优化器根据收益选择资源")
    
    # 时间感知适应度模式
    if dssa_config.use_time_aware_fitness:
        print("      [TIME-AWARE] 时间感知模式：资源分配将反映时间因子的影响")
    
    # 风险优先部署模式
    if dssa_config.use_risk_priority:
        print(f"      [RISK-PRIORITY] 风险优先模式：优先将资源部署到高风险网格")
        print(f"        - 高风险网格占比：{dssa_config.high_risk_percentage*100:.0f}%")
    
    # 解析冻结资源列表
    frozen_resources_list = []
    if freeze_resources:
        frozen_resources_list = [r.strip() for r in freeze_resources.split(',')]
        if frozen_resources_list:
            print(f"      [FROZEN] 冻结资源模式：{', '.join(frozen_resources_list)} 将保持不变")
    
    warm_start_solution = None
    if warm_start_path:
        try:
            warm_start_solution = load_warm_start_solution(warm_start_path)
            print(f"      [WARM-START] 从 {warm_start_path} 加载热启动解")
            with open(warm_start_path, 'r', encoding='utf-8') as f:
                ws_data = json.load(f)
            ws_orig_fitness = ws_data.get('summary', {}).get('best_fitness', None)
            ws_cam = sum(warm_start_solution.cameras.values())
            ws_drone = sum(warm_start_solution.drones.values())
            ws_camp = sum(warm_start_solution.camps.values())
            ws_ranger = sum(warm_start_solution.rangers.values())
            ws_fence = sum(1 for v in warm_start_solution.fences.values() if v > 0)
            print(f"      [WARM-START] 资源: cam={ws_cam}/{constraints['total_cameras']}"
                  f" drone={ws_drone}/{constraints['total_drones']}"
                  f" camp={ws_camp}/{constraints['total_camps']}"
                  f" ranger={ws_ranger}/{constraints['total_patrol']}"
                  f" fence={ws_fence}/{int(constraints['total_fence_length'])}")
            ws_current_fitness = coverage_model.calculate_total_benefit(warm_start_solution)
            ws_current_benefit = sum(coverage_model.calculate_protection_benefit(warm_start_solution).values())
            ws_current_total_risk = coverage_model._total_risk if hasattr(coverage_model, '_total_risk') else 0
            ws_stored_benefit = ws_data.get('summary', {}).get('total_protection_benefit', None)
            ws_stored_total_risk = ws_data.get('summary', {}).get('total_risk', None)
            ws_regular_fitness = ws_current_benefit / ws_current_total_risk if ws_current_total_risk > 0 else 0
            ws_time_fitness = coverage_model.calculate_time_aware_total_benefit(warm_start_solution)
            using_time_aware = dssa_config.use_time_aware_fitness
            ws_model_fitness = ws_time_fitness if using_time_aware else ws_current_fitness
            print(f"      [WARM-START] 原始 best_fitness={ws_orig_fitness}  "
                  f"当前模型({['普通','时间感知'][using_time_aware]})={ws_model_fitness:.6f}"
                  f"{'  *** 差异 ***' if ws_orig_fitness and abs(ws_orig_fitness - ws_model_fitness) > 1e-6 else ''}")
            print(f"      [WARM-START]   stored benefit={ws_stored_benefit} risk={ws_stored_total_risk}"
                  f"  |  current benefit={ws_current_benefit:.6f} risk={ws_current_total_risk:.6f}"
                  f"  ratio={ws_regular_fitness:.6f}  时间感知={ws_time_fitness:.6f}")
        except (IOError, OSError, json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"      [WARM-START] 加载热启动解失败: {e}，将使用冷启动")

    # 提取 boundary_locations
    boundary_locations = None
    map_config = data.get('map_config', {})
    if map_config and 'boundary_locations' in map_config:
        bl = map_config['boundary_locations']
        if bl:
            boundary_locations = []
            for item in bl:
                if isinstance(item, dict):
                    boundary_locations.append((item['x'], item['y']))
                else:
                    boundary_locations.append(tuple(item))
    
    optimizer = DSSAOptimizer(coverage_model, constraints, dssa_config, 
                             fixed_fences=fixed_fences,
                             force_full_deployment=force_full_deployment,
                             frozen_resources=frozen_resources_list,
                             input_grids=data.get('grids', []),
                             raw_risk_map=raw_risk_map,
                             boundary_locations=boundary_locations,
                             warm_start_solution=warm_start_solution)
    best_solution, best_fitness, fitness_history = optimizer.optimize()

    # 打印资源部署总结
    print("\n" + "=" * 70)
    print("资源部署总结 (Resource Deployment Summary)")
    print("=" * 70)
    
    deployed_cameras = sum(best_solution.cameras.values())
    deployed_drones = sum(best_solution.drones.values())
    deployed_camps = sum(best_solution.camps.values())
    deployed_rangers = sum(best_solution.rangers.values())
    deployed_fences = sum(1 for v in best_solution.fences.values() if v == 1)
    
    print(f"\n[CAMERA] 摄像头 (Cameras):")
    print(f"   部署数量: {deployed_cameras} / {constraints['total_cameras']}")
    print(f"   部署位置: {len(best_solution.cameras)} 个网格")
    if best_solution.cameras:
        camera_grids = sorted(best_solution.cameras.items(), key=lambda x: x[1], reverse=True)[:5]
        print(f"   主要部署: ", end="")
        print(", ".join([f"Grid {gid}({count}个)" for gid, count in camera_grids]))
    
    print(f"\n[DRONE] 无人机 (Drones):")
    print(f"   部署数量: {deployed_drones} / {constraints['total_drones']}")
    print(f"   部署位置: {len(best_solution.drones)} 个网格")
    if best_solution.drones:
        drone_grids = sorted(best_solution.drones.keys())[:10]
        print(f"   部署网格: {', '.join([f'Grid {gid}' for gid in drone_grids])}")
    
    print(f"\n[CAMP] 营地 (Camps):")
    print(f"   部署数量: {deployed_camps} / {constraints['total_camps']}")
    if best_solution.camps:
        camp_grids = sorted(best_solution.camps.keys())
        print(f"   部署网格: {', '.join([f'Grid {gid}' for gid in camp_grids])}")
    
    print(f"\n[RANGER] 巡逻人员 (Rangers):")
    print(f"   部署数量: {deployed_rangers} / {constraints['total_patrol']}")
    print(f"   部署位置: {len(best_solution.rangers)} 个网格")
    if best_solution.rangers:
        ranger_grids = sorted(best_solution.rangers.items(), key=lambda x: x[1], reverse=True)[:10]
        print(f"   主要部署: ", end="")
        print(", ".join([f"Grid {gid}({count}人)" for gid, count in ranger_grids]))
    
    print(f"\n[FENCE] 围栏 (Fences):")
    print(f"   部署段数: {deployed_fences}")
    if deployed_fences > 0:
        fence_edges_list = [(e[0], e[1]) for e, v in best_solution.fences.items() if v == 1]
        sample_fences = fence_edges_list[:5]
        print(f"   示例边: ", end="")
        print(", ".join([f"({gid1}-{gid2})" for gid1, gid2 in sample_fences]))
    
    print(f"\n[STATS] 部署统计:")
    
    # 摄像头利用率
    if constraints['total_cameras'] > 0:
        camera_util = deployed_cameras / constraints['total_cameras'] * 100
        print(f"   摄像头利用率: {camera_util:.1f}%")
    else:
        print(f"   摄像头利用率: N/A (未配置摄像头资源)")
    
    # 无人机利用率
    if constraints['total_drones'] > 0:
        drone_util = deployed_drones / constraints['total_drones'] * 100
        print(f"   无人机利用率: {drone_util:.1f}%")
    else:
        print(f"   无人机利用率: N/A (未配置无人机资源)")
    
    # 营地利用率
    if constraints['total_camps'] > 0:
        camp_util = deployed_camps / constraints['total_camps'] * 100
        print(f"   营地利用率: {camp_util:.1f}%")
    else:
        print(f"   营地利用率: N/A (未配置营地资源)")
    
    # 巡逻人员利用率
    if constraints['total_patrol'] > 0:
        ranger_util = deployed_rangers / constraints['total_patrol'] * 100
        print(f"   巡逻人员利用率: {ranger_util:.1f}%")
    else:
        print(f"   巡逻人员利用率: N/A (未配置巡逻人员资源)")
    
    print("\n" + "=" * 70 + "\n")

    print("[4/4] Compute metrics and write output...")
    pb_per_grid = coverage_model.calculate_protection_benefit(best_solution)
    total_risk = sum(grid_model.get_grid_risk(gid) for gid in grid_model.get_all_grid_ids())
    
    # 计算时间加权的总风险（如果启用时间感知模式）
    total_risk_weighted = 0.0
    for gid in grid_model.get_all_grid_ids():
        normalized_risk = grid_model.get_grid_risk(gid)
        temporal_factor = grid_model.get_grid_temporal_factor(gid)
        total_risk_weighted += normalized_risk * temporal_factor
    
    total_protection_benefit = sum(pb_per_grid.values())
    avg_protection_benefit = float(np.mean(list(pb_per_grid.values())))

    # 获取所有网格的原始风险值（已归一化）
    risk_vals = [grid_model.get_grid_risk(gid) for gid in grid_model.get_all_grid_ids()]
    risk_min, risk_max = min(risk_vals), max(risk_vals)

    # 计算保护效果（缓存结果以避免重复计算）
    protection_effect = coverage_model.calculate_protection_effect(best_solution)
    
    # 计算剩余风险（原始值）
    rr_per_grid = {
        gid: grid_model.get_grid_risk(gid) * np.exp(-protection_effect[gid])
        for gid in grid_model.get_all_grid_ids()
    }
    
    # 使用统一的归一化范围（基于部署前风险范围）
    # 这样部署前后的热力图可以直接对比
    def norm_unified_risk(v):
        return float((v - risk_min) / (risk_max - risk_min)) if risk_max != risk_min else float(v)

    # 归一化保护收益
    pb_vals = list(pb_per_grid.values())
    pb_min, pb_max = min(pb_vals), max(pb_vals)

    def norm_pb(v):
        return float((v - pb_min) / (pb_max - pb_min)) if pb_max != pb_min else float(v)

    input_grid_map = {g['grid_id']: g for g in data['grids']}
    grid_results = []
    for grid in loader.grids:
        gid = grid.grid_id
        src = input_grid_map.get(gid, {})
        entry = {
            'grid_id': gid,
            'q': grid.q,
            'r': grid.r,
            'x': src.get('x', 0),
            'y': src.get('y', 0),
            'terrain_type': grid.terrain_type,
            'risk_normalized': round(norm_unified_risk(grid_model.get_grid_risk(gid)), 6),
            'raw_risk': round(float(raw_risk_map.get(gid, 0.0)), 6),
            'protection_benefit_raw': round(float(pb_per_grid[gid]), 6),
            'protection_benefit_normalized': round(norm_pb(pb_per_grid[gid]), 6),
            'residual_risk_normalized': round(norm_unified_risk(rr_per_grid[gid]), 6),
            'deployment': {
                'patrol_rangers': int(best_solution.rangers.get(gid, 0)),
                'camp': int(best_solution.camps.get(gid, 0)),
                'drone': int(best_solution.drones.get(gid, 0)),
                'camera': int(best_solution.cameras.get(gid, 0))
            }
        }
        
        # Add fence information for grids with boundary fences (Requirement 1.5, 6)
        # Fences are stored as (grid_id, direction) where direction is 0-5
        grid_fence_edges = [(e[0], e[1]) for e, v in best_solution.fences.items() if v > 0 and e[0] == gid and isinstance(e[1], int)]
        if grid_fence_edges:
            entry['fences'] = {
                'fence_count': len(grid_fence_edges),
                'boundary_edge_list': [direction for _, direction in grid_fence_edges]
            }

        if 'hex_size' in src:
            entry['hex_size'] = src['hex_size']
        grid_results.append(entry)

    # 计算 summary 统计量
    all_gids = grid_model.get_all_grid_ids()
    norm_risk_vals  = [grid_model.get_grid_risk(gid) for gid in all_gids]
    raw_risk_vals   = [float(raw_risk_map.get(gid, 0.0)) for gid in all_gids]
    residual_vals   = [norm_unified_risk(rr_per_grid[gid]) for gid in all_gids]
    total_residual  = sum(rr_per_grid[gid] for gid in all_gids)

    output = {
        'summary': {
            'total_grids': grid_model.get_grid_count(),
            'total_risk': round(float(total_risk), 6),
            'total_risk_weighted': round(float(total_risk_weighted), 6),
            'best_fitness': round(float(best_fitness), 6),
            'total_protection_benefit': round(float(total_protection_benefit), 6),
            'average_protection_benefit': round(float(avg_protection_benefit), 6),
            # 部署前归一化风险统计
            'risk_min':  round(min(norm_risk_vals), 6),
            'risk_max':  round(max(norm_risk_vals), 6),
            'risk_mean': round(float(np.mean(norm_risk_vals)), 6),
            # 部署前原始风险统计
            'raw_risk_min':  round(min(raw_risk_vals), 6),
            'raw_risk_max':  round(max(raw_risk_vals), 6),
            'raw_risk_mean': round(float(np.mean(raw_risk_vals)), 6),
            # 部署后剩余风险统计
            'residual_risk_min':  round(min(residual_vals), 6),
            'residual_risk_max':  round(max(residual_vals), 6),
            'residual_risk_mean': round(float(np.mean(residual_vals)), 6),
            'total_residual_risk': round(float(total_residual), 6),
            'fitness_history': [round(float(f), 6) for f in fitness_history],
            'resources_deployed': {
                'total_cameras': int(sum(best_solution.cameras.values())),
                'total_drones': int(sum(best_solution.drones.values())),
                'total_camps': int(sum(best_solution.camps.values())),
                'total_rangers': int(sum(best_solution.rangers.values())),
                'fence_segments': sum(1 for v in best_solution.fences.values() if v > 0)
            }
        },
        'visualization_config': {
            'show_grid_ids': False
        },
        'grids': grid_results
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n[OK] 优化完成！结果已保存到: {output_path}")
    print(f"\n最终指标:")
    print(f"  最佳适应度 (Best Fitness)              : {best_fitness:.6f}")
    print(f"  总保护收益 (Total Protection Benefit)  : {total_protection_benefit:.6f}")
    print(f"  平均保护收益 (Average Protection Benefit): {avg_protection_benefit:.6f}")
    print(f"  总风险 (Total Risk)                    : {total_risk:.6f}")
    print(f"  网格总数 (Total Grids)                 : {grid_model.get_grid_count()}")
    print()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description="Protection Pipeline: risk calculation + DSSA deployment optimization",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog="""
Examples:
  python protection_pipeline.py input.json output.json
  python protection_pipeline.py input.json output.json --vectorized
  python protection_pipeline.py input.json output.json --allow-partial-deployment

Deployment Modes:
  Default (Force Full Deployment): All resources will be deployed to their limits
  --allow-partial-deployment: Allow optimizer to choose which resources to deploy based on marginal benefit

Vectorized Mode:
  Use --vectorized flag for large maps (>1000 grids)
  Performance improvement: ~3-5x faster
  Recommended for production use with large datasets
        """
    )
    parser.add_argument("input", help="Input JSON path")
    parser.add_argument("output", help="Output JSON path")
    parser.add_argument(
        "--vectorized",
        action="store_true",
        default=False,
        help="Use NumPy-vectorized coverage model (recommended for maps with >1000 grids, ~3-5x faster)"
    )
    parser.add_argument(
        "--allow-partial-deployment",
        action="store_true",
        default=False,
        help="Allow partial deployment of resources based on marginal benefit (default: force full deployment)"
    )
    parser.add_argument(
        "--freeze-resources",
        type=str,
        default=None,
        help="Comma-separated list of resources to freeze (e.g., 'patrol,camera,drone'). Frozen resources will not be optimized."
    )
    parser.add_argument(
        "--warm-start",
        type=str,
        default=None,
        help="Path to a previous output JSON to use as warm-start solution for the optimizer"
    )
    parser.add_argument(
        "--no-gpu",
        action="store_true",
        default=False,
        help="Disable GPU acceleration (force CPU computation)"
    )
    args = parser.parse_args()
    run_pipeline(args.input, args.output, vectorized=args.vectorized, allow_partial_deployment=args.allow_partial_deployment, freeze_resources=args.freeze_resources, warm_start_path=args.warm_start, use_gpu=not args.no_gpu)
