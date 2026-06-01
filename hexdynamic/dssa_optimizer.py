import gc
import multiprocessing
import numpy as np
from typing import Dict, List, Tuple, Callable, Optional, Any
from dataclasses import dataclass, asdict
import random
import json
import os
import threading
import queue
import concurrent.futures
from coverage_model import CoverageModel, DeploymentSolution


def _deterministic_hash(solution: DeploymentSolution) -> int:
    """Generate a hash key for fitness cache.
    
    Uses Python's built-in hash() for speed. For in-process caching
    with max 10000 entries, collision probability is negligible.
    """
    return hash((
        tuple(sorted(solution.cameras.items())),
        tuple(sorted(solution.camps.items())),
        tuple(sorted(solution.drones.items())),
        tuple(sorted(solution.rangers.items())),
        tuple(sorted(solution.fences.items())),
    ))


def _snapshot_solution(solution: DeploymentSolution) -> DeploymentSolution:
    return DeploymentSolution(
        cameras=dict(solution.cameras),
        camps=dict(solution.camps),
        drones=dict(solution.drones),
        rangers=dict(solution.rangers),
        fences=dict(solution.fences)
    )


def _write_solutions_json(path: str, solutions: list):
    """Write solutions list to JSON file. Runs in separate process."""
    import json as _json
    buf = _SerializationBuffer()
    with open(path, 'w', encoding='utf-8') as f:
        f.write('[')
        for i, s in enumerate(solutions):
            if i > 0:
                f.write(',')
            buf.fill_from(s)
            _json.dump(buf.output, f, ensure_ascii=False)
            buf.clear()
        f.write(']')


def _write_best_json(path: str, best_solution):
    """Write best solution to JSON file. Runs in separate process."""
    import json as _json
    if best_solution is None:
        return
    buf = _SerializationBuffer()
    buf.fill_from(best_solution)
    with open(path, 'w', encoding='utf-8') as f:
        _json.dump(buf.output, f, ensure_ascii=False)


def _write_batch_iterations_main(batch: list, output_dir: str):
    """Write all iterations in batch. Runs in separate process (no GIL)."""
    import os as _os
    for item in batch:
        iter_dir = _os.path.join(output_dir, f"iteration_{item['iteration']:05d}")
        _os.makedirs(iter_dir, exist_ok=True)
        _write_solutions_json(_os.path.join(iter_dir, "producers.json"), item['producers'])
        _write_solutions_json(_os.path.join(iter_dir, "followers.json"), item['followers'])
        _write_solutions_json(_os.path.join(iter_dir, "scouts.json"), item['scouts'])
        _write_best_json(_os.path.join(iter_dir, "best.json"), item.get('best_solution'))


def _json_worker_main(q, output_dir):
    """JSON worker process main function. Runs in separate process (no GIL)."""
    while True:
        task = q.get()
        if task is None:
            return
        try:
            if 'batch' in task:
                _write_batch_iterations_main(task['batch'], output_dir)
            else:
                iter_dir = task['iter_dir']
                os.makedirs(iter_dir, exist_ok=True)
                _write_solutions_json(os.path.join(iter_dir, "producers.json"), task['producers'])
                _write_solutions_json(os.path.join(iter_dir, "followers.json"), task['followers'])
                _write_solutions_json(os.path.join(iter_dir, "scouts.json"), task['scouts'])
                _write_best_json(os.path.join(iter_dir, "best.json"), task.get('best_solution'))
        except Exception as e:
            print(f"[WARN] JSON worker error: {e}")


# ── Process-pool worker state (module-level, set by initializer per worker) ──
_worker_coverage_model = None
_worker_constraints = None
_worker_use_time_aware_fitness = False
_worker_fitness_cache = {}
_worker_fitness_cache_max_size = 10000
_worker_grid_ids = []
_worker_force_full_deployment = True
_worker_use_marginal_contribution_repair = False
_worker_skip_conflict_resolution = False
_worker_frozen_resources = []
_worker_initial_solution = None
_worker_fixed_fences = {}
_worker_swap_prob = 0.6
_worker_migrate_prob = 0.25
_worker_reshuffle_prob = 0.15
_worker_scout_partial_reset_ratio = 0.5
_worker_scout_reset_threshold = 0.95
_worker_use_risk_priority = False
_worker_grid_risks = {}  # grid_id -> risk value for risk-weighted selection


def _worker_initializer(coverage_model, constraints, use_time_aware_fitness, cache_max_size,
                        grid_ids=None, force_full_deployment=True,
                        use_marginal_contribution_repair=False, skip_conflict_resolution=False,
                        frozen_resources=None, initial_solution=None, fixed_fences=None,
                        swap_prob=0.6, migrate_prob=0.25, reshuffle_prob=0.15,
                        scout_partial_reset_ratio=0.5, scout_reset_threshold=0.95,
                        use_risk_priority=False, grid_risks=None):
    global _worker_coverage_model, _worker_constraints
    global _worker_use_time_aware_fitness, _worker_fitness_cache, _worker_fitness_cache_max_size
    global _worker_grid_ids, _worker_force_full_deployment
    global _worker_use_marginal_contribution_repair, _worker_skip_conflict_resolution
    global _worker_frozen_resources, _worker_initial_solution, _worker_fixed_fences
    global _worker_swap_prob, _worker_migrate_prob, _worker_reshuffle_prob
    global _worker_scout_partial_reset_ratio, _worker_scout_reset_threshold
    global _worker_use_risk_priority, _worker_grid_risks
    _worker_coverage_model = coverage_model
    _worker_constraints = constraints
    _worker_use_time_aware_fitness = use_time_aware_fitness
    _worker_fitness_cache = {}
    _worker_fitness_cache_max_size = cache_max_size
    _worker_grid_ids = grid_ids or []
    _worker_force_full_deployment = force_full_deployment
    _worker_use_marginal_contribution_repair = use_marginal_contribution_repair
    _worker_skip_conflict_resolution = skip_conflict_resolution
    _worker_frozen_resources = frozen_resources or []
    _worker_initial_solution = initial_solution
    _worker_fixed_fences = fixed_fences or {}
    _worker_swap_prob = swap_prob
    _worker_migrate_prob = migrate_prob
    _worker_reshuffle_prob = reshuffle_prob
    _worker_scout_partial_reset_ratio = scout_partial_reset_ratio
    _worker_scout_reset_threshold = scout_reset_threshold
    _worker_use_risk_priority = use_risk_priority
    _worker_grid_risks = grid_risks or {}


def _worker_weighted_choice(items, weights=None, alpha=3.0):
    """Risk-weighted random choice with alpha-controlled intensity.
    
    alpha controls how strongly high-risk grids are preferred:
    - alpha >= 3.0: strong risk priority (high-risk grids strongly preferred)
    - alpha = 1.0: uniform random (no risk priority)
    - 1.0 < alpha < 3.0: moderate risk priority
    """
    if not items:
        return None
    if weights is None or not _worker_use_risk_priority:
        return random.choice(items)
    
    # Scale weights by alpha intensity
    # alpha=1.0 → uniform, alpha=3.0 → strong risk priority
    intensity = max(0.0, (alpha - 1.0) / 2.0)  # 0.0 to 1.0
    scaled_weights = [1.0 + intensity * (w - 0.5) for w in weights]
    
    # Normalize weights
    total = sum(scaled_weights)
    if total <= 0:
        return random.choice(items)
    r = random.uniform(0, total)
    cumulative = 0
    for item, w in zip(items, scaled_weights):
        cumulative += w
        if r <= cumulative:
            return item
    return items[-1]


def _worker_make_cache_key(solution):
    """Generate a deterministic hash key for fitness cache (used in worker processes)."""
    if solution._cache_key is not None:
        return solution._cache_key
    key = _deterministic_hash(solution)
    solution._cache_key = key
    return key


def _worker_evaluate_fitness(sol_data):
    global _worker_coverage_model, _worker_constraints
    global _worker_use_time_aware_fitness, _worker_fitness_cache, _worker_fitness_cache_max_size

    if isinstance(sol_data, dict):
        solution = DeploymentSolution(
            cameras=sol_data['cameras'], camps=sol_data['camps'],
            drones=sol_data['drones'], rangers=sol_data['rangers'],
            fences=sol_data['fences'])
    else:
        solution = sol_data

    cache_key = _worker_make_cache_key(solution)
    if cache_key in _worker_fitness_cache:
        return _worker_fitness_cache[cache_key]

    is_valid, violations = _worker_coverage_model.validate_solution(solution, _worker_constraints)
    if not is_valid:
        fitness = -len(violations) * 1000
    elif _worker_use_time_aware_fitness:
        fitness = _worker_coverage_model.calculate_time_aware_total_benefit(solution)
    else:
        fitness = _worker_coverage_model.calculate_total_benefit(solution)

    if len(_worker_fitness_cache) < _worker_fitness_cache_max_size:
        _worker_fitness_cache[cache_key] = fitness

    return fitness


def _worker_get_deployable_grids(resource_type):
    return [gid for gid in _worker_grid_ids
            if _worker_coverage_model.deployment_matrix[resource_type].get(gid, 0) == 1]


def _worker_apply_frozen_resources(solution, initial_solution_data=None):
    if not _worker_frozen_resources:
        return solution
    init_sol = _worker_initial_solution
    if initial_solution_data is not None:
        init_sol = DeploymentSolution(
            cameras=initial_solution_data['cameras'], camps=initial_solution_data['camps'],
            drones=initial_solution_data['drones'], rangers=initial_solution_data['rangers'],
            fences=initial_solution_data['fences'])
    if not init_sol:
        return solution
    if 'patrol' in _worker_frozen_resources:
        solution.rangers = dict(init_sol.rangers)
    if 'camera' in _worker_frozen_resources:
        solution.cameras = dict(init_sol.cameras)
    if 'drone' in _worker_frozen_resources:
        solution.drones = dict(init_sol.drones)
    if 'camp' in _worker_frozen_resources:
        solution.camps = dict(init_sol.camps)
    if 'fence' in _worker_frozen_resources:
        solution.fences = dict(init_sol.fences)
    return solution


def _worker_repair(solution, skip_force_full=False):
    return _worker_coverage_model.repair_solution(
        solution, _worker_constraints, _worker_force_full_deployment,
        _worker_use_marginal_contribution_repair, _worker_skip_conflict_resolution,
        skip_force_full=skip_force_full)


def _worker_discrete_swap(solution, alpha=3.0):
    cameras = dict(solution.cameras)
    camps = dict(solution.camps)
    drones = dict(solution.drones)
    rangers = dict(solution.rangers)
    occupied = set()
    occupied.update(cameras.keys())
    occupied.update(camps.keys())
    occupied.update(drones.keys())
    occupied.update(rangers.keys())
    if len(occupied) < 2:
        return solution
    
    # Risk-weighted selection: alpha controls intensity of risk priority
    occupied_list = list(occupied)
    if _worker_use_risk_priority and _worker_grid_risks:
        weights = [_worker_grid_risks.get(gid, 0.5) for gid in occupied_list]
        grid_a = _worker_weighted_choice(occupied_list, weights, alpha)
        remaining = [g for g in occupied_list if g != grid_a]
        if not remaining:
            return solution
        weights_b = [_worker_grid_risks.get(g, 0.5) for g in remaining]
        grid_b = _worker_weighted_choice(remaining, weights_b, alpha)
    else:
        grid_a, grid_b = random.sample(occupied_list, 2)
    
    cam_a = cameras.pop(grid_a, 0)
    cam_b = cameras.pop(grid_b, 0)
    if cam_b > 0 and _worker_coverage_model.deployment_matrix['camera'].get(grid_a, 0) == 1:
        cameras[grid_a] = cam_b
    if cam_a > 0 and _worker_coverage_model.deployment_matrix['camera'].get(grid_b, 0) == 1:
        cameras[grid_b] = cam_a
    drone_a = drones.pop(grid_a, 0)
    drone_b = drones.pop(grid_b, 0)
    if drone_b > 0 and _worker_coverage_model.deployment_matrix['drone'].get(grid_a, 0) == 1:
        drones[grid_a] = drone_b
    if drone_a > 0 and _worker_coverage_model.deployment_matrix['drone'].get(grid_b, 0) == 1:
        drones[grid_b] = drone_a
    camp_a = camps.pop(grid_a, 0)
    camp_b = camps.pop(grid_b, 0)
    if camp_b > 0 and _worker_coverage_model.deployment_matrix['camp'].get(grid_a, 0) == 1:
        camps[grid_a] = camp_b
    if camp_a > 0 and _worker_coverage_model.deployment_matrix['camp'].get(grid_b, 0) == 1:
        camps[grid_b] = camp_a
    ranger_a = rangers.pop(grid_a, 0)
    ranger_b = rangers.pop(grid_b, 0)
    if ranger_b > 0 and _worker_coverage_model.deployment_matrix['patrol'].get(grid_a, 0) == 1:
        rangers[grid_a] = ranger_b
    if ranger_a > 0 and _worker_coverage_model.deployment_matrix['patrol'].get(grid_b, 0) == 1:
        rangers[grid_b] = ranger_a
    for gid in (grid_a, grid_b):
        types = []
        if rangers.get(gid, 0) > 0: types.append('ranger')
        if drones.get(gid, 0) > 0: types.append('drone')
        if cameras.get(gid, 0) > 0: types.append('camera')
        if camps.get(gid, 0) > 0: types.append('camp')
        if len(types) > 1:
            keep = random.choice(types)
            if keep != 'ranger': rangers.pop(gid, None)
            if keep != 'drone': drones.pop(gid, None)
            if keep != 'camera': cameras.pop(gid, None)
            if keep != 'camp': camps.pop(gid, None)
    return DeploymentSolution(cameras=cameras, camps=camps, drones=drones,
                              rangers=rangers, fences=solution.fences)


def _worker_discrete_migrate(solution, alpha=3.0):
    cameras = dict(solution.cameras)
    camps = dict(solution.camps)
    drones = dict(solution.drones)
    rangers = dict(solution.rangers)
    resource_sources = []
    for gid, cnt in cameras.items():
        if cnt > 0: resource_sources.append(('camera', gid))
    for gid, cnt in drones.items():
        if cnt > 0: resource_sources.append(('drone', gid))
    for gid, cnt in camps.items():
        if cnt > 0: resource_sources.append(('camp', gid))
    for gid, cnt in rangers.items():
        if cnt > 0: resource_sources.append(('ranger', gid))
    if not resource_sources:
        return solution
    
    # Risk-weighted source selection: prefer migrating FROM high-risk grids
    if _worker_use_risk_priority and _worker_grid_risks:
        src_weights = [_worker_grid_risks.get(gid, 0.5) for _, gid in resource_sources]
        res_type, src_gid = _worker_weighted_choice(resource_sources, src_weights, alpha)
    else:
        res_type, src_gid = random.choice(resource_sources)
    
    res_map = {'camera': cameras, 'drone': drones, 'camp': camps, 'ranger': rangers}
    deploy_key = {'camera': 'camera', 'drone': 'drone', 'camp': 'camp', 'ranger': 'patrol'}
    deployable = _worker_get_deployable_grids(deploy_key[res_type])
    occupied = set(cameras.keys()) | set(drones.keys()) | set(camps.keys()) | set(rangers.keys())
    targets = [gid for gid in deployable if gid not in occupied]
    if not targets:
        return solution
    
    # Risk-weighted target selection: prefer migrating TO high-risk grids
    if _worker_use_risk_priority and _worker_grid_risks:
        target_weights = [_worker_grid_risks.get(gid, 0.5) for gid in targets]
        dst_gid = _worker_weighted_choice(targets, target_weights, alpha)
    else:
        dst_gid = random.choice(targets)
    
    src_dict = res_map[res_type]
    max_per_grid = {
        'camera': _worker_constraints.get('max_cameras_per_grid', 1),
        'drone': 1, 'camp': 1,
        'ranger': _worker_constraints.get('max_rangers_per_grid', 1),
    }
    count = src_dict.pop(src_gid, 0)
    src_dict[dst_gid] = min(count, max_per_grid[res_type])
    return DeploymentSolution(cameras=cameras, camps=camps, drones=drones,
                              rangers=rangers, fences=solution.fences)


def _worker_discrete_reshuffle(solution, alpha=3.0):
    res_types = ['camera', 'drone', 'camp', 'ranger']
    chosen = random.choice(res_types)
    res_map = {'camera': dict(solution.cameras), 'drone': dict(solution.drones),
               'camp': dict(solution.camps), 'ranger': dict(solution.rangers)}
    deploy_key = {'camera': 'camera', 'drone': 'drone', 'camp': 'camp', 'ranger': 'patrol'}
    total_key = {'camera': 'total_cameras', 'drone': 'total_drones',
                 'camp': 'total_camps', 'ranger': 'total_patrol'}
    max_key = {'camera': 'max_cameras_per_grid', 'drone': 'max_drones_per_grid',
               'camp': 'max_camps_per_grid', 'ranger': 'max_rangers_per_grid'}
    total = _worker_constraints.get(total_key[chosen], 0)
    if total == 0:
        return solution
    max_per_grid = _worker_constraints.get(max_key[chosen], 1)
    deployable = _worker_get_deployable_grids(deploy_key[chosen])
    other_occupied = set()
    for rt in res_types:
        if rt != chosen:
            other_occupied.update(res_map[rt].keys())
    available = [gid for gid in deployable if gid not in other_occupied]
    if not available:
        return solution
    
    # Risk-weighted sorting: alpha controls how strongly high-risk grids are prioritized
    if _worker_use_risk_priority and _worker_grid_risks:
        intensity = max(0.0, (alpha - 1.0) / 2.0)  # 0.0 to 1.0
        # Sort by risk value with alpha-controlled intensity
        available.sort(key=lambda gid: _worker_grid_risks.get(gid, 0.5) * intensity + random.random() * (1.0 - intensity), reverse=True)
    else:
        random.shuffle(available)
    
    new_dict = {}
    deployed = 0
    for gid in available:
        if deployed >= total:
            break
        count = min(max_per_grid, total - deployed)
        new_dict[gid] = count
        deployed += count
    res_map[chosen] = new_dict
    return DeploymentSolution(cameras=res_map['camera'], camps=res_map['camp'],
                              drones=res_map['drone'], rangers=res_map['ranger'],
                              fences=solution.fences)


def _worker_discrete_perturb(solution, alpha=3.0):
    r = random.random()
    if r < _worker_swap_prob:
        result = _worker_discrete_swap(solution, alpha=alpha)
        # Swap is capacity-preserving, skip force_full_deployment in repair
        return _worker_repair(result, skip_force_full=True)
    elif r < _worker_swap_prob + _worker_migrate_prob:
        result = _worker_discrete_migrate(solution, alpha=alpha)
    else:
        result = _worker_discrete_reshuffle(solution, alpha=alpha)
    return _worker_repair(result)


def _worker_big_perturb(solution, alpha=3.0, reset_ratio=0.3):
    """Global perturbation: randomly reinitialize reset_ratio fraction of the solution.
    
    This is more aggressive than swap/migrate/reshuffle and helps escape local optima.
    reset_ratio controls what fraction of resources to reinitialize (0.1-0.5).
    """
    cameras = dict(solution.cameras)
    camps = dict(solution.camps)
    drones = dict(solution.drones)
    rangers = dict(solution.rangers)
    
    res_types = ['camera', 'drone', 'camp', 'ranger']
    res_maps = {'camera': cameras, 'drone': drones, 'camp': camps, 'ranger': rangers}
    deploy_keys = {'camera': 'camera', 'drone': 'drone', 'camp': 'camp', 'ranger': 'patrol'}
    total_keys = {'camera': 'total_cameras', 'drone': 'total_drones',
                  'camp': 'total_camps', 'ranger': 'total_patrol'}
    max_keys = {'camera': 'max_cameras_per_grid', 'drone': 'max_drones_per_grid',
                'camp': 'max_camps_per_grid', 'ranger': 'max_rangers_per_grid'}
    
    # Randomly choose which resource types to reset
    n_reset = max(1, int(len(res_types) * reset_ratio))
    types_to_reset = random.sample(res_types, n_reset)
    
    for res_type in types_to_reset:
        total = _worker_constraints.get(total_keys[res_type], 0)
        if total == 0:
            continue
        max_per_grid = _worker_constraints.get(max_keys[res_type], 1)
        deployable = _worker_get_deployable_grids(deploy_keys[res_type])
        
        # Risk-weighted selection for new positions
        if _worker_use_risk_priority and _worker_grid_risks and deployable:
            weights = [_worker_grid_risks.get(gid, 0.5) for gid in deployable]
            # Sort by weighted probability (high-risk grids first)
            indexed_weights = list(enumerate(weights))
            indexed_weights.sort(key=lambda x: x[1], reverse=True)
            available = [deployable[i] for i, _ in indexed_weights]
        else:
            available = list(deployable)
            random.shuffle(available)
        
        # Clear existing deployment for this resource type
        res_maps[res_type].clear()
        
        # Redeploy with risk priority
        deployed = 0
        for gid in available:
            if deployed >= total:
                break
            count = min(max_per_grid, total - deployed)
            res_maps[res_type][gid] = count
            deployed += count
    
    return DeploymentSolution(cameras=res_maps['camera'], camps=res_maps['camp'],
                              drones=res_maps['drone'], rangers=res_maps['ranger'],
                              fences=solution.fences)


def _worker_exploit_toward_best(solution, best_solution):
    cameras = dict(solution.cameras)
    camps = dict(solution.camps)
    drones = dict(solution.drones)
    rangers = dict(solution.rangers)
    cross_ratio = random.uniform(0.3, 0.7)
    best_cam_grids = set(best_solution.cameras.keys())
    cur_cam_grids = set(cameras.keys())
    for gid in best_cam_grids | cur_cam_grids:
        if random.random() < cross_ratio:
            best_val = best_solution.cameras.get(gid, 0)
            if best_val > 0 and _worker_coverage_model.deployment_matrix['camera'].get(gid, 0) == 1:
                cameras[gid] = best_val
            else:
                cameras.pop(gid, None)
    best_drone_grids = set(best_solution.drones.keys())
    cur_drone_grids = set(drones.keys())
    for gid in best_drone_grids | cur_drone_grids:
        if random.random() < cross_ratio:
            best_val = best_solution.drones.get(gid, 0)
            if best_val > 0 and _worker_coverage_model.deployment_matrix['drone'].get(gid, 0) == 1:
                drones[gid] = best_val
            else:
                drones.pop(gid, None)
    best_camp_grids = set(best_solution.camps.keys())
    cur_camp_grids = set(camps.keys())
    for gid in best_camp_grids | cur_camp_grids:
        if random.random() < cross_ratio:
            best_val = best_solution.camps.get(gid, 0)
            if best_val > 0 and _worker_coverage_model.deployment_matrix['camp'].get(gid, 0) == 1:
                camps[gid] = best_val
            else:
                camps.pop(gid, None)
    best_ranger_grids = set(best_solution.rangers.keys())
    cur_ranger_grids = set(rangers.keys())
    for gid in best_ranger_grids | cur_ranger_grids:
        if random.random() < cross_ratio:
            best_val = best_solution.rangers.get(gid, 0)
            if best_val > 0 and _worker_coverage_model.deployment_matrix['patrol'].get(gid, 0) == 1:
                rangers[gid] = best_val
            else:
                rangers.pop(gid, None)
    result = DeploymentSolution(cameras=cameras, camps=camps, drones=drones,
                                rangers=rangers, fences=dict(solution.fences))
    return _worker_repair(result)


def _worker_follow_producer(solution, producer):
    cameras = dict(solution.cameras)
    camps = dict(solution.camps)
    drones = dict(solution.drones)
    rangers = dict(solution.rangers)
    cross_ratio = random.uniform(0.2, 0.5)
    for gid in set(producer.cameras.keys()) | set(cameras.keys()):
        if random.random() < cross_ratio:
            prod_val = producer.cameras.get(gid, 0)
            if prod_val > 0 and _worker_coverage_model.deployment_matrix['camera'].get(gid, 0) == 1:
                cameras[gid] = prod_val
            else:
                cameras.pop(gid, None)
    for gid in set(producer.drones.keys()) | set(drones.keys()):
        if random.random() < cross_ratio:
            prod_val = producer.drones.get(gid, 0)
            if prod_val > 0 and _worker_coverage_model.deployment_matrix['drone'].get(gid, 0) == 1:
                drones[gid] = prod_val
            else:
                drones.pop(gid, None)
    for gid in set(producer.camps.keys()) | set(camps.keys()):
        if random.random() < cross_ratio:
            prod_val = producer.camps.get(gid, 0)
            if prod_val > 0 and _worker_coverage_model.deployment_matrix['camp'].get(gid, 0) == 1:
                camps[gid] = prod_val
            else:
                camps.pop(gid, None)
    for gid in set(producer.rangers.keys()) | set(rangers.keys()):
        if random.random() < cross_ratio:
            prod_val = producer.rangers.get(gid, 0)
            if prod_val > 0 and _worker_coverage_model.deployment_matrix['patrol'].get(gid, 0) == 1:
                rangers[gid] = prod_val
            else:
                rangers.pop(gid, None)
    result = DeploymentSolution(cameras=cameras, camps=camps, drones=drones,
                                rangers=rangers, fences=dict(solution.fences))
    return _worker_repair(result)


def _worker_partial_reset_scout(solution):
    res_types = ['camera', 'drone', 'camp', 'ranger']
    n_reset = max(1, int(len(res_types) * _worker_scout_partial_reset_ratio))
    types_to_reset = random.sample(res_types, n_reset)
    cameras = dict(solution.cameras)
    camps = dict(solution.camps)
    drones = dict(solution.drones)
    rangers = dict(solution.rangers)
    res_map = {'camera': cameras, 'drone': drones, 'camp': camps, 'ranger': rangers}
    deploy_key = {'camera': 'camera', 'drone': 'drone', 'camp': 'camp', 'ranger': 'patrol'}
    total_key = {'camera': 'total_cameras', 'drone': 'total_drones',
                 'camp': 'total_camps', 'ranger': 'total_patrol'}
    max_key = {'camera': 'max_cameras_per_grid', 'drone': 'max_drones_per_grid',
               'camp': 'max_camps_per_grid', 'ranger': 'max_rangers_per_grid'}
    for res_type in types_to_reset:
        total = _worker_constraints.get(total_key[res_type], 0)
        if total == 0:
            continue
        max_per_grid = _worker_constraints.get(max_key[res_type], 1)
        deployable = _worker_get_deployable_grids(deploy_key[res_type])
        other_occupied = set()
        for rt in res_types:
            if rt != res_type:
                other_occupied.update(res_map[rt].keys())
        available = [gid for gid in deployable if gid not in other_occupied]
        random.shuffle(available)
        new_dict = {}
        deployed = 0
        for gid in available:
            if deployed >= total:
                break
            count = min(max_per_grid, total - deployed)
            new_dict[gid] = count
            deployed += count
        res_map[res_type] = new_dict
    result = DeploymentSolution(cameras=res_map['camera'], camps=res_map['camp'],
                                drones=res_map['drone'], rangers=res_map['ranger'],
                                fences=dict(solution.fences))
    return _worker_repair(result)


def _worker_generate_and_evaluate(task):
    op = task['op']
    alpha = task.get('alpha', 3.0)  # Default alpha for backward compatibility
    sol_data = task.get('solution')
    if sol_data is not None:
        solution = DeploymentSolution(
            cameras=sol_data['cameras'], camps=sol_data['camps'],
            drones=sol_data['drones'], rangers=sol_data['rangers'],
            fences=sol_data['fences'])
    else:
        solution = None

    if op == 'exploit':
        best_data = task['best_solution']
        best_sol = DeploymentSolution(
            cameras=best_data['cameras'], camps=best_data['camps'],
            drones=best_data['drones'], rangers=best_data['rangers'],
            fences=best_data['fences'])
        new_sol = _worker_exploit_toward_best(solution, best_sol)
    elif op == 'perturb':
        new_sol = _worker_discrete_perturb(solution, alpha=alpha)
    elif op == 'perturb_double':
        new_sol = _worker_discrete_perturb(solution, alpha=alpha)
        new_sol = _worker_discrete_perturb(new_sol, alpha=alpha)
    elif op == 'big_perturb':
        reset_ratio = task.get('reset_ratio', 0.3)
        new_sol = _worker_big_perturb(solution, alpha=alpha, reset_ratio=reset_ratio)
        new_sol = _worker_repair(new_sol)
    elif op == 'follow':
        prod_data = task['producer']
        producer = DeploymentSolution(
            cameras=prod_data['cameras'], camps=prod_data['camps'],
            drones=prod_data['drones'], rangers=prod_data['rangers'],
            fences=prod_data['fences'])
        new_sol = _worker_follow_producer(solution, producer)
    elif op == 'scout_partial_reset':
        new_sol = _worker_partial_reset_scout(solution)
    else:
        return None

    new_sol = _worker_apply_frozen_resources(new_sol, task.get('initial_solution'))
    fitness = _worker_evaluate_fitness(new_sol)

    return {
        'cameras': dict(new_sol.cameras),
        'camps': dict(new_sol.camps),
        'drones': dict(new_sol.drones),
        'rangers': dict(new_sol.rangers),
        'fences': dict(new_sol.fences),
        'fitness': fitness,
    }


def _sol_to_dict(solution):
    if solution is None:
        return None
    return {
        'cameras': dict(solution.cameras),
        'camps': dict(solution.camps),
        'drones': dict(solution.drones),
        'rangers': dict(solution.rangers),
        'fences': dict(solution.fences),
    }


def _dict_to_sol(d):
    if d is None:
        return None
    return DeploymentSolution(
        cameras=d['cameras'], camps=d['camps'],
        drones=d['drones'], rangers=d['rangers'],
        fences=d['fences'])


class _SerializationBuffer:
    """可复用的序列化缓冲区，避免反复分配 dict/list 导致内存碎片"""
    __slots__ = ('cameras', 'camps', 'drones', 'rangers', 'fences',
                 'cam_locs', 'camp_locs', 'drone_locs', 'ranger_locs', 'fence_edges',
                 'statistics', 'output')

    def __init__(self):
        self.cameras = {}
        self.camps = {}
        self.drones = {}
        self.rangers = {}
        self.fences = {}
        self.cam_locs = []
        self.camp_locs = []
        self.drone_locs = []
        self.ranger_locs = []
        self.fence_edges = []
        self.statistics = {}
        self.output = {}

    def clear(self):
        self.cameras.clear()
        self.camps.clear()
        self.drones.clear()
        self.rangers.clear()
        self.fences.clear()
        self.cam_locs.clear()
        self.camp_locs.clear()
        self.drone_locs.clear()
        self.ranger_locs.clear()
        self.fence_edges.clear()
        self.statistics.clear()
        self.output.clear()

    def fill_from(self, solution: DeploymentSolution) -> Dict[str, Any]:
        # Clear any stale data from previous use
        self.clear()
        total_cameras = 0
        for k, v in solution.cameras.items():
            self.cameras[str(k)] = v
            total_cameras += v
            if v > 0:
                self.cam_locs.append(k)

        total_camps = 0
        for k, v in solution.camps.items():
            self.camps[str(k)] = v
            total_camps += v
            if v > 0:
                self.camp_locs.append(k)

        total_drones = 0
        for k, v in solution.drones.items():
            self.drones[str(k)] = v
            total_drones += v
            if v > 0:
                self.drone_locs.append(k)

        total_rangers = 0
        for k, v in solution.rangers.items():
            self.rangers[str(k)] = v
            total_rangers += v
            if v > 0:
                self.ranger_locs.append(k)

        total_fence_length = 0
        for k, v in solution.fences.items():
            self.fences[f"{k[0]}-{k[1]}"] = v
            total_fence_length += v
            if v > 0:
                self.fence_edges.append(k)

        self.statistics['total_cameras'] = total_cameras
        self.statistics['total_drones'] = total_drones
        self.statistics['total_camps'] = total_camps
        self.statistics['total_rangers'] = total_rangers
        self.statistics['total_fence_length'] = total_fence_length
        self.statistics['camera_locations'] = list(self.cam_locs)
        self.statistics['drone_locations'] = list(self.drone_locs)
        self.statistics['ranger_locations'] = list(self.ranger_locs)
        self.statistics['camp_locations'] = list(self.camp_locs)
        self.statistics['fence_edges'] = list(self.fence_edges)

        self.output['cameras'] = self.cameras
        self.output['camps'] = self.camps
        self.output['drones'] = self.drones
        self.output['rangers'] = self.rangers
        self.output['fences'] = self.fences
        self.output['statistics'] = self.statistics

        return self.output


@dataclass
class DSSAConfig:
    population_size: int = 50
    max_iterations: int = 200
    producer_ratio: float = 0.2
    scout_ratio: float = 0.3
    ST: float = 0.8
    R2: float = 0.5  # 已弃用：R2现在在每次迭代中随机生成，此参数保留用于向后兼容
    use_time_aware_fitness: bool = False  # 启用时间感知的适应度计算
    output_dir: Optional[str] = None  # 输出目录，每轮迭代的JSON文件保存到这个目录
    force_full_deployment: Optional[bool] = None
    
    # --- 风险优先部署配置 ---
    use_risk_priority: bool = False  # 是否启用风险优先部署
    high_risk_percentage: float = 0.3  # 高风险网格占比（0-1），默认 30%
    high_risk_perturbation_priority: float = 0.7  # 高风险网格扰动优先级（0-1），值越高越高风险网格越容易被扰动

    # --- Exploration range scheduling (legacy, kept for backward compat) ---
    initial_alpha: float = 3.0       # exploration range in early phase (iter < 30%)
    mid_alpha: float = 2.0           # exploration range in mid phase (30%–70%)
    final_alpha: float = 1.0         # exploration range in late phase (iter >= 70%)
    exploitation_alpha: float = 1.0  # perturbation bound for exploitation-mode producers

    # --- Stagnation detection and boost ---
    stagnation_threshold: int = 10   # consecutive non-improving iters before boost
    stagnation_tolerance: float = 1e-6  # minimum improvement to reset counter
    fitness_update_epsilon: float = 1e-9  # min fitness improvement to update best_solution
    stagnation_boost: float = 1.5    # multiplier applied to alpha during stagnation
    only_output_on_best_change: bool = True  # 只在 best_solution 变化时输出迭代数据

    # --- Discrete swap exploration (方案C) ---
    swap_prob: float = 0.6           # Producer 使用离散交换操作的概率（vs 连续向量扰动）
    migrate_prob: float = 0.25       # 资源迁移操作概率
    reshuffle_prob: float = 0.15     # 全局重排操作概率
    follower_explore_ratio: float = 0.5  # Follower 随机探索比例（vs 向 best/producer 靠拢）
    scout_reset_threshold: float = 0.95  # Scout 重置阈值：fitness < threshold * best_fitness 时重置
    scout_partial_reset_ratio: float = 0.5  # Scout 部分重置时，重置的资源类型比例
    diversity_min_threshold: float = 0.3  # 种群多样性最低阈值（低于此值时注入随机解）
    diversity_inject_ratio: float = 0.3  # 多样性过低时注入随机解的比例（提升探索能力）

    # --- 修复策略配置 ---
    use_marginal_contribution_repair: bool = False  # 是否使用边际贡献 leave-one-out 修复超量（默认关闭，用快速随机移除）
    skip_conflict_resolution: bool = False  # 是否跳过资源冲突解决（当部署矩阵确保无重叠时可开启）

    # --- 性能配置 ---
    fitness_cache_max_size: int = 10000  # 适应度缓存最大条目数
    fitness_workers: int = min(os.cpu_count() or 16, 16)  # Cap at 16 to prevent system overload
    output_interval: int = 1  # 批量输出间隔：每 N 轮迭代输出一次（1=每轮都输出）
    num_restarts: int = 1  # 多起点重启次数（1=单次运行，>1=多起点并行取最优）


class DSSAOptimizer:
    def __init__(self, coverage_model: CoverageModel, constraints: Dict[str, Any],
                 config: DSSAConfig = None, fixed_fences: Dict[Tuple[int, int], int] = None,
                 force_full_deployment: bool = True, frozen_resources: List[str] = None,
                 input_grids: List[Dict] = None, raw_risk_map: Dict = None,
                 boundary_locations: List[Tuple[float, float]] = None,
                 warm_start_solution: DeploymentSolution = None):
        self.coverage_model = coverage_model
        self.constraints = constraints
        self.config = config or DSSAConfig()
        self.grid_model = coverage_model.grid_model
        self.grid_ids = self.grid_model.get_all_grid_ids()
        self.fencing_edges = self.grid_model.get_fencing_edges()
        self.fixed_fences = fixed_fences or {}
        self.force_full_deployment = force_full_deployment
        self.frozen_resources = frozen_resources or []

        self.population = []
        self.population_fitness = []  # Cached fitness for each individual
        self.fitness_history = []
        self.best_solution = None
        self.best_fitness = float('-inf')
        self.initial_solution = None
        self.warm_start_solution = warm_start_solution

        # Stagnation tracking state
        self.stagnation_count = 0
        self.prev_best_fitness = float('-inf')

        self.output_dir = self.config.output_dir
        self._output_lock = threading.Lock()
        self._async_threads = []
        self._json_queue = multiprocessing.Queue()  # Use multiprocessing.Queue for process-based worker
        self._json_worker_started = False
        self._json_process = None
        self._output_buffer: List[dict] = []  # batch output: accumulates iteration data

        # 保存构建输出 JSON 所需的参数
        self.input_grids = input_grids
        self.raw_risk_map = raw_risk_map
        self.boundary_locations = boundary_locations
        
        # --- 风险优先部署：初始化高/低风险网格分组 ---
        self._high_risk_grids = []
        self._low_risk_grids = []
        self._grid_to_risk = {}  # grid_id -> normalized_risk
        
        if self.config.use_risk_priority:
            self._initialize_risk_groups()

        # Process pool for parallel fitness evaluation (avoids GIL contention)
        # Limit BLAS threads per worker to avoid memory explosion from
        # many processes each spawning their own thread pools (OpenBLAS error).
        os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
        os.environ.setdefault('MKL_NUM_THREADS', '1')
        os.environ.setdefault('OMP_NUM_THREADS', '1')
        os.environ.setdefault('NUMEXPR_NUM_THREADS', '1')
        self._fitness_executor = concurrent.futures.ProcessPoolExecutor(
            max_workers=min(self.config.fitness_workers, self.config.population_size),
            initializer=_worker_initializer,
            initargs=(self.coverage_model, self.constraints,
                      self.config.use_time_aware_fitness,
                      self.config.fitness_cache_max_size,
                      self.grid_ids, self.force_full_deployment,
                      self.config.use_marginal_contribution_repair,
                      self.config.skip_conflict_resolution,
                      self.frozen_resources, None, self.fixed_fences,
                      self.config.swap_prob, self.config.migrate_prob,
                      self.config.reshuffle_prob,
                      self.config.scout_partial_reset_ratio,
                      self.config.scout_reset_threshold,
                      self.config.use_risk_priority,
                      self._grid_to_risk),
        )

        self._fitness_cache = {}
        self._fitness_cache_max_size = self.config.fitness_cache_max_size

        # Precompute deployable grids for each resource type (deployment matrix is constant)
        self._deployable_grids = {
            rt: [gid for gid in self.grid_ids
                 if self.coverage_model.deployment_matrix[rt].get(gid, 0) == 1]
            for rt in ['camera', 'drone', 'camp', 'patrol', 'fence']
        }

    def __del__(self):
        """Cleanup resources when optimizer is garbage collected."""
        if hasattr(self, '_fitness_executor'):
            self._fitness_executor.shutdown(wait=False)

    def _initialize_solution(self) -> DeploymentSolution:
        """初始化解决方案
        
        如果 force_full_deployment=True，强制部署所有资源到上限
        否则使用原来的逻辑（可能部分部署）
        
        如果启用了风险优先部署，将优先从高风险网格部署资源
        """
        cameras = {}
        camps = {}
        drones = {}
        rangers = {}
        fences = dict(self.fixed_fences)  # Start with fixed fences

        # 获取优先级网格顺序：高风险网格在前，低风险网格在后
        grid_ids_ordered = self._get_prioritized_grid_order()

        if self.force_full_deployment:
            # 强制部署模式：确保所有资源都部署到上限
            
            # 1. 部署所有摄像头
            max_cam = self.constraints.get('max_cameras_per_grid', 1)
            cam_target = self.constraints['total_cameras']
            cam_deployed = 0
            
            for grid_id in grid_ids_ordered:
                if cam_deployed >= cam_target:
                    break
                if self.coverage_model.deployment_matrix['camera'][grid_id] == 1:
                    count = min(max_cam, cam_target - cam_deployed)
                    cameras[grid_id] = count
                    cam_deployed += count
            
            # 如果还没部署完，继续尝试（可能需要多次遍历）
            attempt = 0
            while cam_deployed < cam_target and attempt < 3:
                for grid_id in grid_ids_ordered:
                    if cam_deployed >= cam_target:
                        break
                    if self.coverage_model.deployment_matrix['camera'][grid_id] == 1:
                        current = cameras.get(grid_id, 0)
                        can_add = min(max_cam - current, cam_target - cam_deployed)
                        if can_add > 0:
                            cameras[grid_id] = current + can_add
                            cam_deployed += can_add
                attempt += 1

            # 2. 部署所有无人机
            max_drone = self.constraints.get('max_drones_per_grid', 1)
            drone_target = self.constraints['total_drones']
            drone_deployed = 0
            
            for grid_id in grid_ids_ordered:
                if drone_deployed >= drone_target:
                    break
                if self.coverage_model.deployment_matrix['drone'][grid_id] == 1:
                    count = min(max_drone, drone_target - drone_deployed)
                    drones[grid_id] = count
                    drone_deployed += count

            # 3. 部署所有营地
            max_camp = self.constraints.get('max_camps_per_grid', 1)
            camp_target = self.constraints['total_camps']
            camp_deployed = 0
            
            for grid_id in grid_ids_ordered:
                if camp_deployed >= camp_target:
                    break
                if self.coverage_model.deployment_matrix['camp'][grid_id] == 1:
                    count = min(max_camp, camp_target - camp_deployed)
                    camps[grid_id] = count
                    camp_deployed += count

            # 4. 部署所有巡逻人员（避免与营地冲突）
            ranger_target = self.constraints['total_patrol']
            ranger_deployed = 0
            
            for grid_id in grid_ids_ordered:
                if ranger_deployed >= ranger_target:
                    break
                if (grid_id not in camps and 
                    self.coverage_model.deployment_matrix['patrol'][grid_id] == 1):
                    rangers[grid_id] = rangers.get(grid_id, 0) + 1
                    ranger_deployed += 1

            # 5. 部署围栏到边界边（多围栏支持）
            fences = self._initialize_fences()
        
        else:
            # 原来的逻辑：允许部分部署
            max_cam = self.constraints.get('max_cameras_per_grid', 1)
            cam_deployed = 0
            for grid_id in grid_ids_ordered:
                if cam_deployed >= self.constraints['total_cameras']:
                    break
                if self.coverage_model.deployment_matrix['camera'][grid_id] == 1:
                    count = min(max_cam, self.constraints['total_cameras'] - cam_deployed)
                    cameras[grid_id] = count
                    cam_deployed += count

            drones_to_deploy = min(self.constraints['total_drones'], len(grid_ids_ordered))
            for i in range(drones_to_deploy):
                grid_id = grid_ids_ordered[(i + cam_deployed) % len(grid_ids_ordered)]
                if self.coverage_model.deployment_matrix['drone'][grid_id] == 1:
                    drones[grid_id] = 1

            camps_to_deploy = min(self.constraints['total_camps'], len(grid_ids_ordered))
            for i in range(camps_to_deploy):
                grid_id = grid_ids_ordered[(i + cam_deployed + drones_to_deploy) % len(grid_ids_ordered)]
                if self.coverage_model.deployment_matrix['camp'][grid_id] == 1:
                    camps[grid_id] = 1

            if self.constraints['total_patrol'] > 0 and sum(rangers.values()) < self.constraints['total_patrol']:
                remaining_rangers = self.constraints['total_patrol'] - sum(rangers.values())
                for grid_id in grid_ids_ordered:
                    if remaining_rangers <= 0:
                        break
                    if (grid_id not in cameras and
                            grid_id not in drones and
                            grid_id not in camps and
                            grid_id not in rangers and
                            self.coverage_model.deployment_matrix['patrol'][grid_id] == 1):
                        rangers[grid_id] = rangers.get(grid_id, 0) + 1
                        remaining_rangers -= 1

            # 部署围栏（部分部署模式）
            fences = self._initialize_fences()

        solution = DeploymentSolution(
            cameras=cameras,
            camps=camps,
            drones=drones,
            rangers=rangers,
            fences=fences
        )
        return self.coverage_model.repair_solution(solution, self.constraints, self.force_full_deployment, self.config.use_marginal_contribution_repair, self.config.skip_conflict_resolution)

    def _initialize_fences(self) -> Dict[Tuple[int, int], int]:
        """初始化围栏部署

        规则：
        - 如果所有可部署边界边数量 <= total_fence_length，部署所有边界边
        - 如果可部署边界边数量 > total_fence_length，只部署 total_fence_length 个

        Returns:
            Dict[Tuple[int, int], int]: 围栏部署字典
            - 边界边: (grid_id, direction) -> count (0或1，direction为0-5)
        """
        fences = dict(self.fixed_fences)
        total_fence_length = self.constraints.get('total_fence_length', float('inf'))

        # Build list of all possible fence edges (grid_id, direction)
        all_fence_edges = []
        for grid_id in self.grid_ids:
            if self.coverage_model.deployment_matrix['fence'].get(grid_id, 0) > 0:
                boundary_edges = self.grid_model.get_boundary_edges_for_grid(grid_id)
                for g_id, direction in boundary_edges:
                    edge_key = (g_id, direction)
                    if edge_key not in self.fixed_fences:
                        all_fence_edges.append(edge_key)

        total_possible = len(all_fence_edges)

        # Determine how many fences to deploy
        if total_possible <= total_fence_length:
            # Deploy all possible boundary edges
            fences_to_deploy = all_fence_edges
        else:
            # Only deploy total_fence_length boundary edges
            # Shuffle and take first total_fence_length
            random.shuffle(all_fence_edges)
            fences_to_deploy = all_fence_edges[:int(total_fence_length)]

        # Deploy fences
        for edge_key in fences_to_deploy:
            fences[edge_key] = 1

        return fences

    def initialize_population(self):
        self.population = []
        for _ in range(self.config.population_size):
            self.population.append(self._initialize_solution())

        if self.warm_start_solution is not None:
            self._inject_warm_start(self.warm_start_solution)

    def _inject_warm_start(self, warm_solution: DeploymentSolution):
        injected_count = max(1, self.config.population_size // 3)
        repaired = self._repair_warm_start(warm_solution)
        for i in range(injected_count):
            if i < len(self.population):
                if i == 0:
                    self.population[i] = repaired
                else:
                    strength = 0.5 + 0.2 * (i / injected_count)
                    perturbed = self._perturb_solution(repaired, strength=strength)
                    self.population[i] = perturbed
        print(f"      [WARM-START] 注入 {injected_count} 个热启动个体到种群")

    def _repair_warm_start(self, warm_solution: DeploymentSolution) -> DeploymentSolution:
        repaired = DeploymentSolution(
            cameras=dict(warm_solution.cameras),
            camps=dict(warm_solution.camps),
            drones=dict(warm_solution.drones),
            rangers=dict(warm_solution.rangers),
            fences=dict(warm_solution.fences)
        )
        max_cam = self.constraints.get('max_cameras_per_grid', 1)
        target_cam = self.constraints['total_cameras']
        for gid in list(repaired.cameras.keys()):
            if self.coverage_model.deployment_matrix['camera'].get(gid, 0) == 0:
                del repaired.cameras[gid]
            else:
                repaired.cameras[gid] = min(repaired.cameras[gid], max_cam)
        deployed_cam = sum(repaired.cameras.values())
        if deployed_cam > target_cam:
            sorted_gids = sorted(repaired.cameras.keys(), key=lambda g: repaired.cameras[g], reverse=True)
            for gid in sorted_gids:
                if deployed_cam <= target_cam:
                    break
                excess = min(repaired.cameras[gid], deployed_cam - target_cam)
                repaired.cameras[gid] -= excess
                deployed_cam -= excess
                if repaired.cameras[gid] <= 0:
                    del repaired.cameras[gid]

        max_drone = self.constraints.get('max_drones_per_grid', 1)
        target_drone = self.constraints['total_drones']
        for gid in list(repaired.drones.keys()):
            if self.coverage_model.deployment_matrix['drone'].get(gid, 0) == 0:
                del repaired.drones[gid]
            else:
                repaired.drones[gid] = min(repaired.drones[gid], max_drone)
        deployed_drone = sum(repaired.drones.values())
        if deployed_drone > target_drone:
            sorted_gids = sorted(repaired.drones.keys(), key=lambda g: repaired.drones[g], reverse=True)
            for gid in sorted_gids:
                if deployed_drone <= target_drone:
                    break
                excess = min(repaired.drones[gid], deployed_drone - target_drone)
                repaired.drones[gid] -= excess
                deployed_drone -= excess
                if repaired.drones[gid] <= 0:
                    del repaired.drones[gid]

        max_camp = self.constraints.get('max_camps_per_grid', 1)
        target_camp = self.constraints['total_camps']
        for gid in list(repaired.camps.keys()):
            if self.coverage_model.deployment_matrix['camp'].get(gid, 0) == 0:
                del repaired.camps[gid]
                repaired.rangers.pop(gid, None)
            else:
                repaired.camps[gid] = min(repaired.camps[gid], max_camp)
        deployed_camp = sum(repaired.camps.values())
        if deployed_camp > target_camp:
            sorted_gids = sorted(repaired.camps.keys(), key=lambda g: repaired.camps[g], reverse=True)
            for gid in sorted_gids:
                if deployed_camp <= target_camp:
                    break
                excess = min(repaired.camps[gid], deployed_camp - target_camp)
                repaired.camps[gid] -= excess
                deployed_camp -= excess
                if repaired.camps[gid] <= 0:
                    del repaired.camps[gid]

        target_ranger = self.constraints['total_patrol']
        for gid in list(repaired.rangers.keys()):
            if gid in repaired.camps:
                del repaired.rangers[gid]
            elif self.coverage_model.deployment_matrix['patrol'].get(gid, 0) == 0:
                del repaired.rangers[gid]
        deployed_ranger = sum(repaired.rangers.values())
        if deployed_ranger > target_ranger:
            sorted_gids = sorted(repaired.rangers.keys(), key=lambda g: repaired.rangers[g], reverse=True)
            for gid in sorted_gids:
                if deployed_ranger <= target_ranger:
                    break
                excess = min(repaired.rangers[gid], deployed_ranger - target_ranger)
                repaired.rangers[gid] -= excess
                deployed_ranger -= excess
                if repaired.rangers[gid] <= 0:
                    del repaired.rangers[gid]

        target_fence = int(self.constraints['total_fence_length'])
        for k in list(repaired.fences.keys()):
            gid1, gid2 = k
            if isinstance(gid2, int) and gid2 in range(6):
                if self.coverage_model.deployment_matrix['fence'].get(gid1, 0) == 0:
                    del repaired.fences[k]
            else:
                if (self.coverage_model.deployment_matrix['fence'].get(gid1, 0) == 0 or
                        self.coverage_model.deployment_matrix['fence'].get(gid2, 0) == 0):
                    del repaired.fences[k]
        deployed_fence = sum(1 for v in repaired.fences.values() if v > 0)
        if deployed_fence > target_fence:
            fence_items = [(k, v) for k, v in repaired.fences.items() if v > 0]
            random.shuffle(fence_items)
            for i in range(deployed_fence - target_fence):
                if i < len(fence_items):
                    del repaired.fences[fence_items[i][0]]

        rep_cam = sum(repaired.cameras.values())
        rep_drone = sum(repaired.drones.values())
        rep_camp = sum(repaired.camps.values())
        rep_ranger = sum(repaired.rangers.values())
        rep_fence = sum(1 for v in repaired.fences.values() if v > 0)
        orig_cam = sum(warm_solution.cameras.values())
        orig_drone = sum(warm_solution.drones.values())
        orig_camp = sum(warm_solution.camps.values())
        orig_ranger = sum(warm_solution.rangers.values())
        orig_fence = sum(1 for v in warm_solution.fences.values() if v > 0)
        changed = (rep_cam != orig_cam or rep_drone != orig_drone or
                   rep_camp != orig_camp or rep_ranger != orig_ranger or
                   rep_fence != orig_fence)
        if changed:
            print(f"      [WARM-START] 修复后资源变化:"
                  f" cam {orig_cam}->{rep_cam}"
                  f" drone {orig_drone}->{rep_drone}"
                  f" camp {orig_camp}->{rep_camp}"
                  f" ranger {orig_ranger}->{rep_ranger}"
                  f" fence {orig_fence}->{rep_fence}")

        return repaired

    def _perturb_solution(self, solution: DeploymentSolution, strength: float = 0.3) -> DeploymentSolution:
        perturbed = DeploymentSolution(
            cameras=dict(solution.cameras),
            camps=dict(solution.camps),
            drones=dict(solution.drones),
            rangers=dict(solution.rangers),
            fences=dict(solution.fences)
        )
        grid_ids_ordered = self._get_prioritized_grid_order()

        if random.random() < strength and perturbed.cameras:
            keys = list(perturbed.cameras.keys())
            src = random.choice(keys)
            dst_candidates = [g for g in grid_ids_ordered
                              if g not in perturbed.cameras
                              and self.coverage_model.deployment_matrix['camera'].get(g, 0) == 1]
            if dst_candidates:
                dst = random.choice(dst_candidates)
                perturbed.cameras[dst] = perturbed.cameras[src]
                del perturbed.cameras[src]

        if random.random() < strength and perturbed.drones:
            keys = list(perturbed.drones.keys())
            src = random.choice(keys)
            dst_candidates = [g for g in grid_ids_ordered
                              if g not in perturbed.drones
                              and self.coverage_model.deployment_matrix['drone'].get(g, 0) == 1]
            if dst_candidates:
                dst = random.choice(dst_candidates)
                perturbed.drones[dst] = perturbed.drones[src]
                del perturbed.drones[src]

        if random.random() < strength and perturbed.camps:
            keys = list(perturbed.camps.keys())
            src = random.choice(keys)
            dst_candidates = [g for g in grid_ids_ordered
                              if g not in perturbed.camps
                              and self.coverage_model.deployment_matrix['camp'].get(g, 0) == 1]
            if dst_candidates:
                dst = random.choice(dst_candidates)
                perturbed.camps[dst] = perturbed.camps[src]
                del perturbed.camps[src]

        if random.random() < strength and perturbed.rangers:
            keys = list(perturbed.rangers.keys())
            src = random.choice(keys)
            dst_candidates = [g for g in grid_ids_ordered
                              if g not in perturbed.rangers
                              and self.coverage_model.deployment_matrix['patrol'].get(g, 0) == 1]
            if dst_candidates:
                dst = random.choice(dst_candidates)
                perturbed.rangers[dst] = perturbed.rangers[src]
                del perturbed.rangers[src]

        return perturbed

    def _apply_frozen_resources(self, solution: DeploymentSolution) -> DeploymentSolution:
        """应用冻结资源：将冻结的资源替换为初始解决方案中的值"""
        if not self.frozen_resources or not self.initial_solution:
            return solution
        
        if 'patrol' in self.frozen_resources:
            solution.rangers = dict(self.initial_solution.rangers)
        if 'camera' in self.frozen_resources:
            solution.cameras = dict(self.initial_solution.cameras)
        if 'drone' in self.frozen_resources:
            solution.drones = dict(self.initial_solution.drones)
        if 'camp' in self.frozen_resources:
            solution.camps = dict(self.initial_solution.camps)
        if 'fence' in self.frozen_resources:
            solution.fences = dict(self.initial_solution.fences)
        
        return solution

    def _evaluate_fitness_parallel(self, solutions: List[DeploymentSolution]) -> List[float]:
        futures = [self._fitness_executor.submit(_worker_evaluate_fitness, _sol_to_dict(sol))
                   for sol in solutions]
        return [f.result() for f in futures]

    def evaluate_fitness(self, solution: DeploymentSolution) -> float:
        cache_key = self._make_cache_key(solution)
        if cache_key in self._fitness_cache:
            return self._fitness_cache[cache_key]

        is_valid, violations = self.coverage_model.validate_solution(solution, self.constraints)
        if not is_valid:
            fitness = -len(violations) * 1000
        elif self.config.use_time_aware_fitness:
            fitness = self.coverage_model.calculate_time_aware_total_benefit(solution)
        else:
            fitness = self.coverage_model.calculate_total_benefit(solution)

        if len(self._fitness_cache) < self._fitness_cache_max_size:
            self._fitness_cache[cache_key] = fitness
        return fitness

    def _make_cache_key(self, solution: DeploymentSolution) -> int:
        """生成适应度缓存的确定性哈希键，基于部署方案的资源分配"""
        if solution._cache_key is not None:
            return solution._cache_key
        key = _deterministic_hash(solution)
        solution._cache_key = key
        return key

    def _get_exploration_alpha(self, iteration: int) -> float:
        """Return the effective exploration alpha for this iteration.
        
        Applies a 3-phase schedule based on iteration progress and
        a stagnation boost when the optimizer is stuck.
        
        Args:
            iteration: Current iteration index (0-based)
            
        Returns:
            The effective exploration range alpha
        """
        # Calculate progress through the optimization, handling max_iterations=1 edge case
        progress = iteration / max(self.config.max_iterations - 1, 1)
        
        # 3-phase schedule
        if progress < 0.3:
            scheduled = self.config.initial_alpha
        elif progress < 0.7:
            scheduled = self.config.mid_alpha
        else:
            scheduled = self.config.final_alpha
        
        # Apply stagnation boost if threshold exceeded
        # Further amplify alpha if stagnation persists for extended periods
        if self.stagnation_count > self.config.stagnation_threshold:
            # Base boost + additional amplification for persistent stagnation
            # stagnation_count - stagnation_threshold gives how many iterations beyond threshold
            extra_amplification = max(0, (self.stagnation_count - self.config.stagnation_threshold) // 10)
            # Cap amplification to prevent unbounded growth (max 3x base boost)
            extra_amplification = min(extra_amplification, 4)
            amplified_boost = self.config.stagnation_boost * (1.0 + 0.5 * extra_amplification)
            return scheduled * amplified_boost
        
        return scheduled

    def _solution_to_vector(self, solution: DeploymentSolution) -> np.ndarray:
        """Convert solution to vector for optimization.
        
        Vector structure:
        - cameras: one value per grid (count 0-max_cameras_per_grid)
        - camps: one value per grid (0 or 1)
        - drones: one value per grid (0 or 1)
        - rangers: one value per grid (count 0-max_rangers_per_grid)
        - fences: one value per grid (count 0-max_fences_per_grid for boundary edges)
        """
        vector = []
        for grid_id in self.grid_ids:
            vector.append(solution.cameras.get(grid_id, 0))
        for grid_id in self.grid_ids:
            vector.append(solution.camps.get(grid_id, 0))
        for grid_id in self.grid_ids:
            vector.append(solution.drones.get(grid_id, 0))
        for grid_id in self.grid_ids:
            vector.append(solution.rangers.get(grid_id, 0))
        # Add fence counts per grid (for boundary edge fences)
        for grid_id in self.grid_ids:
            # Sum fences for this grid (both internal edges and boundary edges)
            fence_count = 0
            # Check boundary edge fences: (grid_id, direction) where direction is 0-5
            for direction in range(6):
                edge_key = (grid_id, direction)
                if edge_key in solution.fences:
                    fence_count += solution.fences[edge_key]
            # Check boundary edge fences: (grid_id, None) - legacy format
            fence_count += solution.fences.get((grid_id, None), 0)
            # Check internal edge fences where this grid is involved
            for neighbor_id in self.grid_model.get_neighbors(grid_id):
                edge_key = (min(grid_id, neighbor_id), max(grid_id, neighbor_id))
                if edge_key in solution.fences:
                    fence_count += solution.fences[edge_key]
            vector.append(fence_count)
        return np.array(vector)

    def _vector_to_solution(self, vector: np.ndarray) -> DeploymentSolution:
        """Convert vector back to solution.
        
        Handles fence counts from vector, creating appropriate fence edge entries.
        """
        cameras = {}
        camps = {}
        drones = {}
        rangers = {}
        fences = dict(self.fixed_fences)  # Start with fixed fences

        idx = 0
        max_cam = self.constraints.get('max_cameras_per_grid', 1)
        for grid_id in self.grid_ids:
            val = int(round(vector[idx]))
            if val > 0 and self.coverage_model.deployment_matrix['camera'][grid_id] == 1:
                cameras[grid_id] = min(val, max_cam)
            idx += 1

        for grid_id in self.grid_ids:
            if vector[idx] > 0.5 and self.coverage_model.deployment_matrix['camp'][grid_id] == 1:
                camps[grid_id] = 1
            idx += 1

        for grid_id in self.grid_ids:
            if vector[idx] > 0.5 and self.coverage_model.deployment_matrix['drone'][grid_id] == 1:
                drones[grid_id] = 1
            idx += 1

        for grid_id in self.grid_ids:
            val = int(round(vector[idx]))
            if val > 0 and self.coverage_model.deployment_matrix['patrol'][grid_id] == 1:
                max_ranger = self.constraints.get('max_rangers_per_grid', 1)
                rangers[grid_id] = min(val, max_ranger)
            idx += 1

        # Decode fence counts
        max_fences_per_grid = self.constraints.get('max_fences_per_grid', 6)
        for grid_id in self.grid_ids:
            fence_count = int(round(vector[idx]))
            idx += 1

# 围栏部署：根据向量值选择部署哪些边界边
            if self.coverage_model.deployment_matrix['fence'].get(grid_id, 0) > 0 and fence_count > 0:
                boundary_edges = self.grid_model.get_boundary_edges_for_grid(grid_id)
                # 只部署 fence_count 条边界边
                for i, (g_id, direction) in enumerate(boundary_edges):
                    if i >= fence_count:
                        break
                    edge_key = (g_id, direction)
                    if edge_key not in self.fixed_fences:
                        fences[edge_key] = 1

        return DeploymentSolution(
            cameras=cameras,
            camps=camps,
            drones=drones,
            rangers=rangers,
            fences=fences
        )

    def _update_producers(self, iteration: int, alpha: float):
        num_producers = int(self.config.population_size * self.config.producer_ratio)
        producers = self.population[:num_producers]

        escape_count = 0
        best_dict = _sol_to_dict(self.best_solution)
        init_dict = _sol_to_dict(self.initial_solution) if self.frozen_resources else None

        tasks = []
        indices = []

        # Use big_perturb when stagnation is high to escape local optima
        use_big_perturb = self.stagnation_count > self.config.stagnation_threshold * 2

        for i, solution in enumerate(producers):
            R2 = random.uniform(0, 1)
            sol_dict = _sol_to_dict(solution)

            if use_big_perturb and random.random() < 0.3:
                # 30% chance of big perturbation when stagnation is high
                reset_ratio = min(0.5, 0.2 + self.stagnation_count / 1000.0)
                tasks.append({'op': 'big_perturb', 'solution': sol_dict,
                              'initial_solution': init_dict, 'alpha': alpha,
                              'reset_ratio': reset_ratio})
            elif R2 < self.config.ST:
                if i == 0:
                    tasks.append({'op': 'exploit', 'solution': sol_dict,
                                  'best_solution': best_dict, 'initial_solution': init_dict,
                                  'alpha': alpha})
                else:
                    tasks.append({'op': 'perturb', 'solution': sol_dict,
                                  'initial_solution': init_dict, 'alpha': alpha})
            else:
                escape_count += 1
                if random.random() < 0.5:
                    tasks.append({'op': 'perturb_double', 'solution': sol_dict,
                                  'initial_solution': init_dict, 'alpha': alpha})
                else:
                    tasks.append({'op': 'perturb', 'solution': sol_dict,
                                  'initial_solution': init_dict, 'alpha': alpha})
            indices.append(i)

        futures = [self._fitness_executor.submit(_worker_generate_and_evaluate, t) for t in tasks]
        old_fitnesses = [self.population_fitness[i] for i in indices]

        for i, old_fit, future in zip(indices, old_fitnesses, futures):
            result = future.result()
            if result is None:
                continue
            new_sol = _dict_to_sol(result)
            new_fit = result['fitness']
            if new_fit > old_fit:
                self.population[i] = new_sol
                self.population_fitness[i] = new_fit
            if new_fit > self.best_fitness + self.config.fitness_update_epsilon:
                self.best_fitness = new_fit
                self.best_solution = new_sol

        return escape_count

    def _exploit_toward_best(self, solution: DeploymentSolution) -> DeploymentSolution:
        """Producer 0 的开发操作：从当前解向最优解靠拢
        
        通过离散交叉实现：随机选择一些资源部署位置，
        将当前解的部署替换为最优解的部署。
        """
        cameras = dict(solution.cameras)
        camps = dict(solution.camps)
        drones = dict(solution.drones)
        rangers = dict(solution.rangers)

        # 随机选择交叉比例（30%-70%的资源位置从 best 继承）
        cross_ratio = random.uniform(0.3, 0.7)

        # Camera 交叉
        best_cam_grids = set(self.best_solution.cameras.keys())
        cur_cam_grids = set(cameras.keys())
        all_cam_grids = best_cam_grids | cur_cam_grids
        for gid in all_cam_grids:
            if random.random() < cross_ratio:
                best_val = self.best_solution.cameras.get(gid, 0)
                if best_val > 0 and self.coverage_model.deployment_matrix['camera'].get(gid, 0) == 1:
                    cameras[gid] = best_val
                else:
                    cameras.pop(gid, None)

        # Drone 交叉
        best_drone_grids = set(self.best_solution.drones.keys())
        cur_drone_grids = set(drones.keys())
        all_drone_grids = best_drone_grids | cur_drone_grids
        for gid in all_drone_grids:
            if random.random() < cross_ratio:
                best_val = self.best_solution.drones.get(gid, 0)
                if best_val > 0 and self.coverage_model.deployment_matrix['drone'].get(gid, 0) == 1:
                    drones[gid] = best_val
                else:
                    drones.pop(gid, None)

        # Camp 交叉
        best_camp_grids = set(self.best_solution.camps.keys())
        cur_camp_grids = set(camps.keys())
        all_camp_grids = best_camp_grids | cur_camp_grids
        for gid in all_camp_grids:
            if random.random() < cross_ratio:
                best_val = self.best_solution.camps.get(gid, 0)
                if best_val > 0 and self.coverage_model.deployment_matrix['camp'].get(gid, 0) == 1:
                    camps[gid] = best_val
                else:
                    camps.pop(gid, None)

        # Ranger 交叉
        best_ranger_grids = set(self.best_solution.rangers.keys())
        cur_ranger_grids = set(rangers.keys())
        all_ranger_grids = best_ranger_grids | cur_ranger_grids
        for gid in all_ranger_grids:
            if random.random() < cross_ratio:
                best_val = self.best_solution.rangers.get(gid, 0)
                if best_val > 0 and self.coverage_model.deployment_matrix['patrol'].get(gid, 0) == 1:
                    rangers[gid] = best_val
                else:
                    rangers.pop(gid, None)

        result = DeploymentSolution(
            cameras=cameras,
            camps=camps,
            drones=drones,
            rangers=rangers,
            fences=dict(solution.fences)
        )

        return self.coverage_model.repair_solution(
            result, self.constraints, self.force_full_deployment,
            self.config.use_marginal_contribution_repair,
            self.config.skip_conflict_resolution
        )

    def _update_followers(self, alpha: float):
        num_producers = int(self.config.population_size * self.config.producer_ratio)
        num_followers = int(self.config.population_size * (1 - self.config.producer_ratio))
        followers = self.population[num_producers:num_producers + num_followers]

        escape_count = 0
        best_dict = _sol_to_dict(self.best_solution)
        init_dict = _sol_to_dict(self.initial_solution) if self.frozen_resources else None

        tasks = []
        indices = []

        for i, solution in enumerate(followers):
            R2 = random.uniform(0, 1)
            sol_dict = _sol_to_dict(solution)

            if R2 < self.config.ST:
                if random.random() < self.config.follower_explore_ratio:
                    escape_count += 1
                    tasks.append({'op': 'perturb', 'solution': sol_dict,
                                  'initial_solution': init_dict, 'alpha': alpha})
                else:
                    if i > len(followers) / 2:
                        tasks.append({'op': 'exploit', 'solution': sol_dict,
                                      'best_solution': best_dict,
                                      'initial_solution': init_dict, 'alpha': alpha})
                    else:
                        idx = random.randint(0, num_producers - 1)
                        prod_dict = _sol_to_dict(self.population[idx])
                        tasks.append({'op': 'follow', 'solution': sol_dict,
                                      'producer': prod_dict,
                                      'initial_solution': init_dict, 'alpha': alpha})
            else:
                escape_count += 1
                tasks.append({'op': 'perturb', 'solution': sol_dict,
                              'initial_solution': init_dict, 'alpha': alpha})
            indices.append(num_producers + i)

        futures = [self._fitness_executor.submit(_worker_generate_and_evaluate, t) for t in tasks]
        old_fitnesses = [self.population_fitness[idx] for idx in indices]

        for idx, old_fit, future in zip(indices, old_fitnesses, futures):
            result = future.result()
            if result is None:
                continue
            new_sol = _dict_to_sol(result)
            new_fit = result['fitness']
            if new_fit > old_fit:
                self.population[idx] = new_sol
                self.population_fitness[idx] = new_fit
            if new_fit > self.best_fitness + self.config.fitness_update_epsilon:
                self.best_fitness = new_fit
                self.best_solution = new_sol

        return escape_count

    def _follow_producer(self, solution: DeploymentSolution, producer: DeploymentSolution) -> DeploymentSolution:
        """Follower 向 Producer 靠拢的离散操作
        
        随机选择一些资源部署位置，从 Producer 继承。
        """
        cameras = dict(solution.cameras)
        camps = dict(solution.camps)
        drones = dict(solution.drones)
        rangers = dict(solution.rangers)

        cross_ratio = random.uniform(0.2, 0.5)

        # Camera
        for gid in set(producer.cameras.keys()) | set(cameras.keys()):
            if random.random() < cross_ratio:
                prod_val = producer.cameras.get(gid, 0)
                if prod_val > 0 and self.coverage_model.deployment_matrix['camera'].get(gid, 0) == 1:
                    cameras[gid] = prod_val
                else:
                    cameras.pop(gid, None)

        # Drone
        for gid in set(producer.drones.keys()) | set(drones.keys()):
            if random.random() < cross_ratio:
                prod_val = producer.drones.get(gid, 0)
                if prod_val > 0 and self.coverage_model.deployment_matrix['drone'].get(gid, 0) == 1:
                    drones[gid] = prod_val
                else:
                    drones.pop(gid, None)

        # Camp
        for gid in set(producer.camps.keys()) | set(camps.keys()):
            if random.random() < cross_ratio:
                prod_val = producer.camps.get(gid, 0)
                if prod_val > 0 and self.coverage_model.deployment_matrix['camp'].get(gid, 0) == 1:
                    camps[gid] = prod_val
                else:
                    camps.pop(gid, None)

        # Ranger
        for gid in set(producer.rangers.keys()) | set(rangers.keys()):
            if random.random() < cross_ratio:
                prod_val = producer.rangers.get(gid, 0)
                if prod_val > 0 and self.coverage_model.deployment_matrix['patrol'].get(gid, 0) == 1:
                    rangers[gid] = prod_val
                else:
                    rangers.pop(gid, None)

        result = DeploymentSolution(
            cameras=cameras,
            camps=camps,
            drones=drones,
            rangers=rangers,
            fences=dict(solution.fences)
        )

        return self.coverage_model.repair_solution(
            result, self.constraints, self.force_full_deployment,
            self.config.use_marginal_contribution_repair,
            self.config.skip_conflict_resolution
        )

    def _update_scouts(self):
        num_scouts = int(self.config.population_size * self.config.scout_ratio)
        start_idx = self.config.population_size - num_scouts

        scout_solutions = self.population[start_idx:self.config.population_size]
        scout_fitnesses = [self.population_fitness[i] for i in range(start_idx, self.config.population_size)]

        init_dict = _sol_to_dict(self.initial_solution) if self.frozen_resources else None
        tasks = []
        task_indices = []
        full_reset_indices = []

        # Adaptive threshold: becomes more aggressive as optimization progresses
        progress = getattr(self, '_iteration_progress', 0.0)
        adaptive_threshold = self.config.scout_reset_threshold - 0.1 * progress
        adaptive_threshold = max(0.7, adaptive_threshold)  # Floor at 0.7

        for i, (solution, fitness) in enumerate(zip(scout_solutions, scout_fitnesses)):
            pop_idx = start_idx + i
            if fitness > self.best_fitness + self.config.fitness_update_epsilon:
                self.best_fitness = fitness
                self.best_solution = solution
            if self.best_fitness > 0 and fitness < adaptive_threshold * self.best_fitness:
                if fitness < 0.5 * self.best_fitness:
                    full_reset_indices.append(pop_idx)
                else:
                    tasks.append({'op': 'scout_partial_reset',
                                  'solution': _sol_to_dict(solution),
                                  'initial_solution': init_dict})
                    task_indices.append(pop_idx)

        if tasks:
            futures = [self._fitness_executor.submit(_worker_generate_and_evaluate, t) for t in tasks]
            for pop_idx, future in zip(task_indices, futures):
                result = future.result()
                if result is not None:
                    self.population[pop_idx] = _dict_to_sol(result)
                    self.population_fitness[pop_idx] = result['fitness']

        for pop_idx in full_reset_indices:
            self.population[pop_idx] = self._initialize_solution()
            self.population_fitness[pop_idx] = float('-inf')

    def _update_best_solution(self):
        """更新全局最优解：评估所有个体适应度，保留最高者"""
        fitnesses = self._evaluate_fitness_parallel(self.population)
        for solution, fitness in zip(self.population, fitnesses):
            if fitness > self.best_fitness + self.config.fitness_update_epsilon:
                self.best_fitness = fitness
                self.best_solution = solution

    def optimize(self, callback: Callable[[int, float, DeploymentSolution], None] = None) -> Tuple[DeploymentSolution, float, List[float]]:
        import time

        try:
            self.initialize_population()
            
            self.initial_solution = self._initialize_solution()

            if self.warm_start_solution is not None:
                self.best_solution = self.population[0]
                is_valid, violations = self.coverage_model.validate_solution(self.population[0], self.constraints)
                if not is_valid:
                    print(f"      [WARM-START] 警告: baseline 方案无效! violations={violations[:5]}")
                self.best_fitness = self.evaluate_fitness(self.population[0])
                print(f"      [WARM-START] 用 baseline 部署初始化 best_solution: fitness={self.best_fitness:.10f}")

            fitnesses = self._evaluate_fitness_parallel(self.population)
            self.population_fitness = list(fitnesses)  # Cache initial fitness values
            for solution, fitness in zip(self.population, fitnesses):
                if fitness > self.best_fitness + self.config.fitness_update_epsilon:
                    self.best_fitness = fitness
                    self.best_solution = solution

            self.fitness_history = [self.best_fitness]

            if self.warm_start_solution is not None:
                ws_eval = self.evaluate_fitness(self.population[0])
                print(f"      [WARM-START] 种群评估后: best_fitness={self.best_fitness:.10f}"
                      f" (热启动个体#0={ws_eval:.6f})")

            total_start = time.time()
            iter_times = []

            num_producers = int(self.config.population_size * self.config.producer_ratio)
            num_scouts = int(self.config.population_size * self.config.scout_ratio)

            for iteration in range(self.config.max_iterations):
                iter_start = time.time()

                # Track iteration progress for adaptive thresholds
                self._iteration_progress = iteration / max(self.config.max_iterations - 1, 1)

                # Get the effective exploration alpha for this iteration
                effective_alpha = self._get_exploration_alpha(iteration)
                
                escape_producers = self._update_producers(iteration, effective_alpha)
                escape_followers = self._update_followers(effective_alpha)
                self._update_scouts()

                diversity_interval = 5
                if iteration % diversity_interval == 0:
                    diversity = self._calculate_diversity()
                    self._last_diversity = diversity
                else:
                    diversity = getattr(self, '_last_diversity', 1.0)
                if diversity < self.config.diversity_min_threshold:
                    self._inject_random_solutions(self.config.diversity_inject_ratio)

                # Periodic reset: every 100 iterations, reset 10% of population (except best)
                # This ensures the optimizer doesn't get permanently stuck
                if iteration > 0 and iteration % 100 == 0:
                    n_reset = max(1, int(self.config.population_size * 0.1))
                    indices_to_reset = random.sample(range(self.config.population_size), n_reset)
                    for idx in indices_to_reset:
                        if self.population[idx] is not self.best_solution:
                            self.population[idx] = self._initialize_solution()
                            self.population_fitness[idx] = float('-inf')

                # Update stagnation tracking state (diversity-aware)
                fitness_improved = self.best_fitness - self.prev_best_fitness > self.config.stagnation_tolerance
                diversity_declining = diversity < getattr(self, '_prev_diversity', diversity)
                self._prev_diversity = diversity
                
                if fitness_improved:
                    self.stagnation_count = 0  # Fitness improved → reset
                elif diversity_declining:
                    self.stagnation_count += 2  # Diversity declining → accelerate stagnation detection
                else:
                    self.stagnation_count += 1
                self.prev_best_fitness = self.best_fitness

                # Clear fitness cache when it gets too large to prevent slowdown from hash collisions
                if len(self._fitness_cache) >= self._fitness_cache_max_size * 0.9:
                    self._fitness_cache.clear()

                # JSON output: buffer iteration data, flush every output_interval iterations
                if self.output_dir:
                    # Check if best solution changed
                    best_changed = not hasattr(self, '_last_snapshot_best_id') or \
                                   self._last_snapshot_best_id != id(self.best_solution)
                    
                    # Only output if: not only_output_on_best_change OR best changed
                    should_output = not self.config.only_output_on_best_change or best_changed
                    
                    if should_output:
                        producers = self.population[:num_producers]
                        followers = self.population[num_producers:num_producers + (self.config.population_size - num_producers - num_scouts)]
                        scouts = self.population[self.config.population_size - num_scouts:]
                        # Only snapshot when best_solution changes to avoid unnecessary dict copies
                        if best_changed:
                            snap = _snapshot_solution(self.best_solution)
                            self._last_snapshot_best = snap
                            self._last_snapshot_best_id = id(self.best_solution)
                        else:
                            snap = self._last_snapshot_best
                        self._output_buffer.append({
                            'iteration': iteration,
                            'producers': list(producers),
                            'followers': list(followers),
                            'scouts': list(scouts),
                            'best_solution': snap,
                        })

                    interval = max(1, self.config.output_interval)
                    is_last = (iteration == self.config.max_iterations - 1)
                    if len(self._output_buffer) >= interval or is_last:
                        self._async_flush_output_buffer()

                # Calculate total_benefit from cached fitness and total_risk
                # fitness = total_benefit / total_risk, so total_benefit = fitness * total_risk
                if not hasattr(self, '_cached_total_risk'):
                    self._cached_total_risk = sum(self.grid_model.get_grid_risk(gid) for gid in self.grid_ids)
                total_benefit = self.best_fitness * self._cached_total_risk if self._cached_total_risk > 0 else 0.0

                iter_elapsed = time.time() - iter_start
                iter_times.append(iter_elapsed)
                self.fitness_history.append(self.best_fitness)

                if callback:
                    callback(iteration, self.best_fitness, self.best_solution)

                avg_iter = sum(iter_times) / len(iter_times)

                if iteration > 0 and iteration % 20 == 0:
                    gc.collect()
                
                # 打印迭代信息
                escape_total = escape_producers + escape_followers
                
                # Build log line with alpha and stagnation boost annotation
                if self.stagnation_count > self.config.stagnation_threshold:
                    extra_amp = max(0, (self.stagnation_count - self.config.stagnation_threshold) // 10)
                    stagnation_annotation = f" [STAGNATION_BOOST×{1.0 + 0.5 * extra_amp:.1f}]"
                else:
                    stagnation_annotation = ""
                
                if escape_total > 0:
                    print(f"Iter {iteration+1:>4}/{self.config.max_iterations}"
                          f"  fitness={self.best_fitness:.10f}"
                          f"  benefit={total_benefit:.10f}"
                          f"  div={diversity:.3f}"
                          f"  α={effective_alpha:.2f}"
                          f"  [ESCAPE={escape_total}]{stagnation_annotation}"
                          f"  iter={iter_elapsed*1000:.1f}ms"
                          f"  avg={avg_iter*1000:.1f}ms")
                else:
                    print(f"Iter {iteration+1:>4}/{self.config.max_iterations}"
                          f"  fitness={self.best_fitness:.10f}"
                          f"  benefit={total_benefit:.10f}"
                          f"  div={diversity:.3f}"
                          f"  α={effective_alpha:.2f}{stagnation_annotation}"
                          f"  iter={iter_elapsed*1000:.1f}ms"
                          f"  avg={avg_iter*1000:.1f}ms")

            total_elapsed = time.time() - total_start
            pb_per_grid = self.coverage_model.calculate_protection_benefit(self.best_solution)
            final_total_benefit = sum(pb_per_grid.values())

            print(f"\nOptimization completed."
                  f"  Best Fitness = {self.best_fitness:.10f}"
                  f"  Total Benefit = {final_total_benefit:.10f}"
                  f"  Total = {total_elapsed:.2f}s"
                  f"  Avg/iter = {total_elapsed/self.config.max_iterations*1000:.1f}ms")

            if self._output_buffer:
                self._async_flush_output_buffer()

            if self._json_worker_started:
                self._json_queue.put(None)
            print("[ASYNC] 等待异步输出任务完成...")
            if self._json_worker_started and self._json_process is not None:
                # Wait for process to finish with timeout
                self._json_process.join(timeout=30)
                if self._json_process.is_alive():
                    print(f"[ASYNC] 警告: JSON输出进程超时(30s)，继续执行")
            print("[ASYNC] 所有异步输出任务完成！")

            for thread in self._async_threads:
                if thread.is_alive():
                    thread.join(timeout=10)

            return self.best_solution, self.best_fitness, self.fitness_history
        finally:
            self._fitness_executor.shutdown(wait=True)

    def optimize_multi_start(self, num_restarts: int = None) -> Tuple[DeploymentSolution, float, List[float]]:
        """Multi-start optimization: run multiple independent optimizations and keep the best.
        
        Args:
            num_restarts: Number of independent restarts (default: config.num_restarts)
        
        Returns:
            Best solution, best fitness, and fitness history from the best run.
        """
        if num_restarts is None:
            num_restarts = self.config.num_restarts
        
        if num_restarts <= 1:
            return self.optimize()
        
        print(f"\n[MULTI-START] Running {num_restarts} independent optimizations...")
        
        best_overall_solution = None
        best_overall_fitness = float('-inf')
        best_history = []
        
        for restart in range(num_restarts):
            print(f"\n--- Restart {restart + 1}/{num_restarts} ---")
            
            # Reset optimizer state for this restart
            self.population = []
            self.population_fitness = []
            self.best_solution = None
            self.best_fitness = float('-inf')
            self.stagnation_count = 0
            self.prev_best_fitness = float('-inf')
            self._fitness_cache = {}
            
            # Run optimization
            solution, fitness, history = self.optimize()
            
            # Track best overall
            if fitness > best_overall_fitness:
                best_overall_fitness = fitness
                best_overall_solution = _snapshot_solution(solution)
                best_history = history
                print(f"  [NEW BEST] Restart {restart + 1}: fitness={fitness:.10f}")
            else:
                print(f"  [NO IMPROVEMENT] Restart {restart + 1}: fitness={fitness:.10f} (best={best_overall_fitness:.10f})")
        
        print(f"\n[MULTI-START] Completed. Best fitness across all restarts: {best_overall_fitness:.10f}")
        return best_overall_solution, best_overall_fitness, best_history

    def get_solution_statistics(self, solution: DeploymentSolution) -> Dict[str, Any]:
        return {
            'total_cameras': sum(solution.cameras.values()),
            'total_drones': sum(solution.drones.values()),
            'total_camps': sum(solution.camps.values()),
            'total_rangers': sum(solution.rangers.values()),
            'total_fence_length': sum(solution.fences.values()),
            'camera_locations': [grid_id for grid_id, count in solution.cameras.items() if count > 0],
            'drone_locations': [grid_id for grid_id, count in solution.drones.items() if count > 0],
            'ranger_locations': [grid_id for grid_id, count in solution.rangers.items() if count > 0],
            'camp_locations': [grid_id for grid_id, count in solution.camps.items() if count > 0],
            'fence_edges': [edge for edge, count in solution.fences.items() if count > 0]
        }

    def _serialize_solution(self, solution: DeploymentSolution) -> Dict[str, Any]:
        cameras_ser = {}
        total_cameras = 0
        camera_locations = []
        for k, v in solution.cameras.items():
            cameras_ser[str(k)] = v
            total_cameras += v
            if v > 0:
                camera_locations.append(k)

        camps_ser = {}
        total_camps = 0
        camp_locations = []
        for k, v in solution.camps.items():
            camps_ser[str(k)] = v
            total_camps += v
            if v > 0:
                camp_locations.append(k)

        drones_ser = {}
        total_drones = 0
        drone_locations = []
        for k, v in solution.drones.items():
            drones_ser[str(k)] = v
            total_drones += v
            if v > 0:
                drone_locations.append(k)

        rangers_ser = {}
        total_rangers = 0
        ranger_locations = []
        for k, v in solution.rangers.items():
            rangers_ser[str(k)] = v
            total_rangers += v
            if v > 0:
                ranger_locations.append(k)

        fences_ser = {}
        total_fence_length = 0
        fence_edges = []
        for k, v in solution.fences.items():
            fences_ser[f"{k[0]}-{k[1]}"] = v
            total_fence_length += v
            if v > 0:
                fence_edges.append(k)

        return {
            'cameras': cameras_ser,
            'camps': camps_ser,
            'drones': drones_ser,
            'rangers': rangers_ser,
            'fences': fences_ser,
            'statistics': {
                'total_cameras': total_cameras,
                'total_drones': total_drones,
                'total_camps': total_camps,
                'total_rangers': total_rangers,
                'total_fence_length': total_fence_length,
                'camera_locations': camera_locations,
                'drone_locations': drone_locations,
                'ranger_locations': ranger_locations,
                'camp_locations': camp_locations,
                'fence_edges': fence_edges
            }
        }

    def _ensure_json_worker(self):
        if not self._json_worker_started:
            with self._output_lock:
                if not self._json_worker_started:
                    # Use multiprocessing.Process to avoid GIL contention with main thread
                    # JSON serialization is CPU-intensive and would block the optimization loop
                    self._json_process = multiprocessing.Process(
                        target=_json_worker_main,
                        args=(self._json_queue, self.output_dir),
                        daemon=True,
                        name='json-worker'
                    )
                    self._json_process.start()
                    self._json_worker_started = True

    def _write_solutions_json(self, path: str, solutions: list):
        """Write solutions list to JSON file (fallback for single-thread mode)."""
        buf = _SerializationBuffer()
        with open(path, 'w', encoding='utf-8') as f:
            f.write('[')
            for i, s in enumerate(solutions):
                if i > 0:
                    f.write(',')
                buf.fill_from(s)
                json.dump(buf.output, f, ensure_ascii=False)
                buf.clear()
            f.write(']')

    def _write_best_json(self, path: str, best_solution=None):
        sol = best_solution if best_solution is not None else self.best_solution
        if sol is None:
            return
        buf = _SerializationBuffer()
        buf.fill_from(sol)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(buf.output, f, ensure_ascii=False)

    def _async_flush_output_buffer(self):
        """Flush all buffered iterations as a batch to the async I/O worker."""
        if not self._output_buffer:
            return
        self._ensure_json_worker()
        batch = list(self._output_buffer)
        self._output_buffer.clear()
        self._json_queue.put({'batch': batch})

    def _async_output_iteration_results(self, iteration: int, producers: List[DeploymentSolution],
                                     followers: List[DeploymentSolution], scouts: List[DeploymentSolution]):
        if not self.output_dir:
            return
        self._ensure_json_worker()
        iter_dir = os.path.join(self.output_dir, f"iteration_{iteration:05d}")
        self._json_queue.put({
            'iter_dir': iter_dir,
            'producers': list(producers),
            'followers': list(followers),
            'scouts': list(scouts)
        })

    def _initialize_risk_groups(self):
        """初始化高/低风险网格分组
        
        按照归一化风险值排序，前 high_risk_percentage 的网格为高风险网格，
        剩余的为低风险网格。
        """
        # 收集所有网格及其风险值
        grid_risk_list = []
        for grid_id in self.grid_ids:
            risk = self.grid_model.get_grid_risk(grid_id)
            self._grid_to_risk[grid_id] = risk
            grid_risk_list.append((grid_id, risk))
        
        # 按风险值从高到低排序
        grid_risk_list.sort(key=lambda x: x[1], reverse=True)
        
        # 分割为高/低风险网格
        num_high_risk = int(len(grid_risk_list) * self.config.high_risk_percentage)
        self._high_risk_grids = [grid_id for grid_id, risk in grid_risk_list[:num_high_risk]]
        self._low_risk_grids = [grid_id for grid_id, risk in grid_risk_list[num_high_risk:]]
        
        print(f"[Risk Priority] 网格分组完成：")
        print(f"  - 总网格数：{len(self.grid_ids)}")
        print(f"  - 高风险网格：{len(self._high_risk_grids)}（前 {self.config.high_risk_percentage*100:.0f}%）")
        print(f"  - 低风险网格：{len(self._low_risk_grids)}")
        if self._high_risk_grids:
            max_risk = max(self._grid_to_risk[gid] for gid in self._high_risk_grids)
            min_risk = min(self._grid_to_risk[gid] for gid in self._high_risk_grids)
            print(f"  - 高风险网格范围：[{min_risk:.4f}, {max_risk:.4f}]")
    
    def _get_prioritized_grid_order(self) -> List[int]:
        """获取优先级网格顺序：先高风险网格，再低风险网格
        
        每个分组内部随机排序，保持多样性
        """
        if not self.config.use_risk_priority:
            # 未启用风险优先：完全随机
            shuffled = self.grid_ids.copy()
            random.shuffle(shuffled)
            return shuffled
        
        # 启用风险优先：高风险网格先随机，低风险网格后随机
        high_shuffled = self._high_risk_grids.copy()
        low_shuffled = self._low_risk_grids.copy()
        random.shuffle(high_shuffled)
        random.shuffle(low_shuffled)
        return high_shuffled + low_shuffled

    # -----------------------------------------------------------------------
    # 离散交换操作（方案C核心）
    # -----------------------------------------------------------------------

    def _get_deployable_grids(self, resource_type: str) -> List[int]:
        """获取某种资源类型可部署的网格列表（预计算缓存）"""
        return self._deployable_grids.get(resource_type, [])

    def _discrete_swap(self, solution: DeploymentSolution) -> DeploymentSolution:
        """资源交换：随机选两个网格，交换它们的非围栏资源部署
        
        交换操作天然满足总量约束（交换前后总量不变），
        不需要 repair_solution 的强力修复。
        """
        cameras = dict(solution.cameras)
        camps = dict(solution.camps)
        drones = dict(solution.drones)
        rangers = dict(solution.rangers)

        # 收集所有有资源部署的网格（排除围栏，围栏保持不变）
        occupied = set()
        occupied.update(cameras.keys())
        occupied.update(camps.keys())
        occupied.update(drones.keys())
        occupied.update(rangers.keys())

        if len(occupied) < 2:
            return solution

        # 随机选两个网格
        grid_a, grid_b = random.sample(list(occupied), 2)

        # 交换 camera
        cam_a = cameras.pop(grid_a, 0)
        cam_b = cameras.pop(grid_b, 0)
        if cam_b > 0 and self.coverage_model.deployment_matrix['camera'].get(grid_a, 0) == 1:
            cameras[grid_a] = cam_b
        if cam_a > 0 and self.coverage_model.deployment_matrix['camera'].get(grid_b, 0) == 1:
            cameras[grid_b] = cam_a

        # 交换 drone
        drone_a = drones.pop(grid_a, 0)
        drone_b = drones.pop(grid_b, 0)
        if drone_b > 0 and self.coverage_model.deployment_matrix['drone'].get(grid_a, 0) == 1:
            drones[grid_a] = drone_b
        if drone_a > 0 and self.coverage_model.deployment_matrix['drone'].get(grid_b, 0) == 1:
            drones[grid_b] = drone_a

        # 交换 camp
        camp_a = camps.pop(grid_a, 0)
        camp_b = camps.pop(grid_b, 0)
        if camp_b > 0 and self.coverage_model.deployment_matrix['camp'].get(grid_a, 0) == 1:
            camps[grid_a] = camp_b
        if camp_a > 0 and self.coverage_model.deployment_matrix['camp'].get(grid_b, 0) == 1:
            camps[grid_b] = camp_a

        # 交换 ranger
        ranger_a = rangers.pop(grid_a, 0)
        ranger_b = rangers.pop(grid_b, 0)
        if ranger_b > 0 and self.coverage_model.deployment_matrix['patrol'].get(grid_a, 0) == 1:
            rangers[grid_a] = ranger_b
        if ranger_a > 0 and self.coverage_model.deployment_matrix['patrol'].get(grid_b, 0) == 1:
            rangers[grid_b] = ranger_a

        # 处理互斥约束：同一网格只能有一种资源
        for gid in (grid_a, grid_b):
            types = []
            if rangers.get(gid, 0) > 0:
                types.append('ranger')
            if drones.get(gid, 0) > 0:
                types.append('drone')
            if cameras.get(gid, 0) > 0:
                types.append('camera')
            if camps.get(gid, 0) > 0:
                types.append('camp')
            if len(types) > 1:
                keep = random.choice(types)
                if keep != 'ranger':
                    rangers.pop(gid, None)
                if keep != 'drone':
                    drones.pop(gid, None)
                if keep != 'camera':
                    cameras.pop(gid, None)
                if keep != 'camp':
                    camps.pop(gid, None)

        return DeploymentSolution(
            cameras=cameras,
            camps=camps,
            drones=drones,
            rangers=rangers,
            fences=solution.fences
        )

    def _discrete_migrate(self, solution: DeploymentSolution) -> DeploymentSolution:
        """资源迁移：随机选一个网格的资源，迁移到另一个随机网格
        
        从有资源的网格中随机选一种资源，迁移到另一个可部署该资源的空网格。
        """
        cameras = dict(solution.cameras)
        camps = dict(solution.camps)
        drones = dict(solution.drones)
        rangers = dict(solution.rangers)

        # 收集所有资源类型及其来源网格
        resource_sources = []
        for gid, cnt in cameras.items():
            if cnt > 0:
                resource_sources.append(('camera', gid))
        for gid, cnt in drones.items():
            if cnt > 0:
                resource_sources.append(('drone', gid))
        for gid, cnt in camps.items():
            if cnt > 0:
                resource_sources.append(('camp', gid))
        for gid, cnt in rangers.items():
            if cnt > 0:
                resource_sources.append(('ranger', gid))

        if not resource_sources:
            return solution

        # 随机选一种资源迁移
        res_type, src_gid = random.choice(resource_sources)
        res_map = {'camera': cameras, 'drone': drones, 'camp': camps, 'ranger': rangers}
        deploy_key = {'camera': 'camera', 'drone': 'drone', 'camp': 'camp', 'ranger': 'patrol'}

        # 找到可部署该资源的目标网格（排除已有资源的网格）
        deployable = self._get_deployable_grids(deploy_key[res_type])
        occupied = set(cameras.keys()) | set(drones.keys()) | set(camps.keys()) | set(rangers.keys())
        targets = [gid for gid in deployable if gid not in occupied]

        if not targets:
            return solution

        dst_gid = random.choice(targets)

        # 迁移资源
        src_dict = res_map[res_type]
        max_per_grid = {
            'camera': self.constraints.get('max_cameras_per_grid', 1),
            'drone': 1,
            'camp': 1,
            'ranger': self.constraints.get('max_rangers_per_grid', 1),
        }

        count = src_dict.pop(src_gid, 0)
        src_dict[dst_gid] = min(count, max_per_grid[res_type])

        return DeploymentSolution(
            cameras=cameras,
            camps=camps,
            drones=drones,
            rangers=rangers,
            fences=solution.fences
        )

    def _discrete_reshuffle(self, solution: DeploymentSolution) -> DeploymentSolution:
        """全局重排：随机选一种资源类型，重新随机分配所有该类型资源的部署位置
        
        围栏保持不变，只重排非围栏资源。
        """
        res_types = ['camera', 'drone', 'camp', 'ranger']
        chosen = random.choice(res_types)

        res_map = {'camera': dict(solution.cameras), 'drone': dict(solution.drones),
                    'camp': dict(solution.camps), 'ranger': dict(solution.rangers)}
        deploy_key = {'camera': 'camera', 'drone': 'drone', 'camp': 'camp', 'ranger': 'patrol'}
        total_key = {'camera': 'total_cameras', 'drone': 'total_drones',
                     'camp': 'total_camps', 'ranger': 'total_patrol'}
        max_key = {'camera': 'max_cameras_per_grid', 'drone': 'max_drones_per_grid',
                   'camp': 'max_camps_per_grid', 'ranger': 'max_rangers_per_grid'}

        total = self.constraints.get(total_key[chosen], 0)
        if total == 0:
            return solution

        max_per_grid = self.constraints.get(max_key[chosen], 1)
        deployable = self._get_deployable_grids(deploy_key[chosen])

        # 排除已有其他资源的网格
        other_occupied = set()
        for rt in res_types:
            if rt != chosen:
                other_occupied.update(res_map[rt].keys())

        available = [gid for gid in deployable if gid not in other_occupied]
        if not available:
            return solution

        random.shuffle(available)

        new_dict = {}
        deployed = 0
        for gid in available:
            if deployed >= total:
                break
            count = min(max_per_grid, total - deployed)
            new_dict[gid] = count
            deployed += count

        res_map[chosen] = new_dict

        return DeploymentSolution(
            cameras=res_map['camera'],
            camps=res_map['camp'],
            drones=res_map['drone'],
            rangers=res_map['ranger'],
            fences=solution.fences
        )

    def _discrete_perturb(self, solution: DeploymentSolution) -> DeploymentSolution:
        """综合离散扰动：按概率选择交换/迁移/重排操作"""
        r = random.random()
        if r < self.config.swap_prob:
            result = self._discrete_swap(solution)
        elif r < self.config.swap_prob + self.config.migrate_prob:
            result = self._discrete_migrate(solution)
        else:
            result = self._discrete_reshuffle(solution)

        return self.coverage_model.repair_solution(
            result, self.constraints, self.force_full_deployment,
            self.config.use_marginal_contribution_repair,
            self.config.skip_conflict_resolution
        )

    def _calculate_diversity(self) -> float:
        """计算种群多样性（基于资源部署位置的归一化海明距离）
        
        使用采样近似：随机选择 100 对个体计算多样性，降低 O(P²) 到 O(100×K)。
        
        返回 [0, 1] 之间的值：
        - 1.0 表示所有个体完全不同
        - 0.0 表示所有个体完全相同
        """
        if len(self.population) < 2:
            return 0.0

        def solution_to_set(sol: DeploymentSolution) -> set:
            occupied = set()
            for gid, cnt in sol.cameras.items():
                if cnt > 0:
                    occupied.add(('camera', gid))
            for gid, cnt in sol.drones.items():
                if cnt > 0:
                    occupied.add(('drone', gid))
            for gid, cnt in sol.camps.items():
                if cnt > 0:
                    occupied.add(('camp', gid))
            for gid, cnt in sol.rangers.items():
                if cnt > 0:
                    occupied.add(('ranger', gid))
            return occupied

        sets = [solution_to_set(sol) for sol in self.population]

        total_positions = set()
        for s in sets:
            total_positions.update(s)
        n_positions = len(total_positions)

        if n_positions == 0:
            return 0.0

        # Sample-based diversity: use 100 random pairs instead of all P(P-1)/2 pairs
        n_pop = len(sets)
        max_possible_pairs = n_pop * (n_pop - 1) // 2
        sample_pairs = min(100, max_possible_pairs)
        
        n_pairs = 0
        total_dist = 0.0
        for _ in range(sample_pairs):
            i, j = random.sample(range(n_pop), 2)
            diff = len(sets[i].symmetric_difference(sets[j]))
            total_dist += diff / n_positions
            n_pairs += 1

        return total_dist / n_pairs if n_pairs > 0 else 0.0

    def _inject_random_solutions(self, ratio: float):
        """注入随机解以增加种群多样性"""
        n_inject = max(1, int(self.config.population_size * ratio))
        indices = random.sample(range(self.config.population_size), min(n_inject, self.config.population_size))

        for idx in indices:
            if self.population[idx] is not self.best_solution:
                self.population[idx] = self._initialize_solution()

    def _partial_reset_scout(self, solution: DeploymentSolution) -> DeploymentSolution:
        """Scout 部分重置：随机重置部分资源类型，保留其余
        
        比 _initialize_solution() 的完全重置更温和，
        保留了一些好的基因，同时引入新的探索。
        """
        res_types = ['camera', 'drone', 'camp', 'ranger']
        n_reset = max(1, int(len(res_types) * self.config.scout_partial_reset_ratio))
        types_to_reset = random.sample(res_types, n_reset)

        cameras = dict(solution.cameras)
        camps = dict(solution.camps)
        drones = dict(solution.drones)
        rangers = dict(solution.rangers)

        res_map = {'camera': cameras, 'drone': drones, 'camp': camps, 'ranger': rangers}
        deploy_key = {'camera': 'camera', 'drone': 'drone', 'camp': 'camp', 'ranger': 'patrol'}
        total_key = {'camera': 'total_cameras', 'drone': 'total_drones',
                     'camp': 'total_camps', 'ranger': 'total_patrol'}
        max_key = {'camera': 'max_cameras_per_grid', 'drone': 'max_drones_per_grid',
                   'camp': 'max_camps_per_grid', 'ranger': 'max_rangers_per_grid'}

        for res_type in types_to_reset:
            total = self.constraints.get(total_key[res_type], 0)
            if total == 0:
                continue

            max_per_grid = self.constraints.get(max_key[res_type], 1)
            deployable = self._get_deployable_grids(deploy_key[res_type])

            # 排除已有其他资源的网格
            other_occupied = set()
            for rt in res_types:
                if rt != res_type:
                    other_occupied.update(res_map[rt].keys())

            available = [gid for gid in deployable if gid not in other_occupied]
            random.shuffle(available)

            new_dict = {}
            deployed = 0
            for gid in available:
                if deployed >= total:
                    break
                count = min(max_per_grid, total - deployed)
                new_dict[gid] = count
                deployed += count

            res_map[res_type] = new_dict

        result = DeploymentSolution(
            cameras=res_map['camera'],
            camps=res_map['camp'],
            drones=res_map['drone'],
            rangers=res_map['ranger'],
            fences=dict(solution.fences)
        )

        return self.coverage_model.repair_solution(
            result, self.constraints, self.force_full_deployment,
            self.config.use_marginal_contribution_repair,
            self.config.skip_conflict_resolution
        )
