import numpy as np
from typing import Dict, List, Tuple, Callable, Optional
from dataclasses import dataclass, asdict
import random
import json
import os
import threading
from coverage_model import CoverageModel, DeploymentSolution


@dataclass
class DSSAConfig:
    population_size: int = 50
    max_iterations: int = 100
    producer_ratio: float = 0.2
    scout_ratio: float = 0.2
    ST: float = 0.8
    R2: float = 0.5  # 已弃用：R2现在在每次迭代中随机生成，此参数保留用于向后兼容
    use_time_aware_fitness: bool = False  # 启用时间感知的适应度计算
    output_dir: Optional[str] = None  # 输出目录，每轮迭代的JSON文件保存到这个目录
    force_full_deployment: Optional[bool] = None

    # --- Exploration range scheduling ---
    initial_alpha: float = 3.0       # exploration range in early phase (iter < 30%)
    mid_alpha: float = 2.0           # exploration range in mid phase (30%–70%)
    final_alpha: float = 1.0         # exploration range in late phase (iter >= 70%)
    exploitation_alpha: float = 1.0  # perturbation bound for exploitation-mode producers

    # --- Stagnation detection and boost ---
    stagnation_threshold: int = 10   # consecutive non-improving iters before boost
    stagnation_tolerance: float = 1e-6  # minimum improvement to reset counter
    stagnation_boost: float = 1.5    # multiplier applied to alpha during stagnation


class DSSAOptimizer:
    def __init__(self, coverage_model: CoverageModel, constraints: Dict[str, any],
                 config: DSSAConfig = None, fixed_fences: Dict[Tuple[int, int], int] = None,
                 force_full_deployment: bool = True, frozen_resources: List[str] = None):
        self.coverage_model = coverage_model
        self.constraints = constraints
        self.config = config or DSSAConfig()
        self.grid_model = coverage_model.grid_model
        self.grid_ids = self.grid_model.get_all_grid_ids()
        self.fencing_edges = self.grid_model.get_fencing_edges()
        self.fixed_fences = fixed_fences or {}
        self.force_full_deployment = force_full_deployment  # 新增：是否强制部署所有资源
        self.frozen_resources = frozen_resources or []  # 新增：冻结的资源列表

        self.population = []
        self.fitness_history = []
        self.best_solution = None
        self.best_fitness = float('-inf')
        self.initial_solution = None  # 新增：保存初始解决方案，用于冻结资源

        # Stagnation tracking state
        self.stagnation_count = 0
        self.prev_best_fitness = float('-inf')

        self.output_dir = self.config.output_dir
        self._output_lock = threading.Lock()

    def _initialize_solution(self) -> DeploymentSolution:
        """初始化解决方案
        
        如果 force_full_deployment=True，强制部署所有资源到上限
        否则使用原来的逻辑（可能部分部署）
        
        支持多围栏部署：每个边缘格子可以在其边界边上部署多个围栏
        """
        cameras = {}
        camps = {}
        drones = {}
        rangers = {}
        fences = dict(self.fixed_fences)  # Start with fixed fences

        grid_ids_shuffled = self.grid_ids.copy()
        random.shuffle(grid_ids_shuffled)

        if self.force_full_deployment:
            # 强制部署模式：确保所有资源都部署到上限
            
            # 1. 部署所有摄像头
            max_cam = self.constraints.get('max_cameras_per_grid', 1)
            cam_target = self.constraints['total_cameras']
            cam_deployed = 0
            
            for grid_id in grid_ids_shuffled:
                if cam_deployed >= cam_target:
                    break
                if self.coverage_model.deployment_matrix['camera'][grid_id] == 1:
                    count = min(max_cam, cam_target - cam_deployed)
                    cameras[grid_id] = count
                    cam_deployed += count
            
            # 如果还没部署完，继续尝试（可能需要多次遍历）
            attempt = 0
            while cam_deployed < cam_target and attempt < 3:
                for grid_id in grid_ids_shuffled:
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
            
            for grid_id in grid_ids_shuffled:
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
            
            for grid_id in grid_ids_shuffled:
                if camp_deployed >= camp_target:
                    break
                if self.coverage_model.deployment_matrix['camp'][grid_id] == 1:
                    count = min(max_camp, camp_target - camp_deployed)
                    camps[grid_id] = count
                    camp_deployed += count

            # 4. 部署所有巡逻人员（避免与营地冲突）
            ranger_target = self.constraints['total_patrol']
            ranger_deployed = 0
            
            for grid_id in grid_ids_shuffled:
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
            for grid_id in grid_ids_shuffled:
                if cam_deployed >= self.constraints['total_cameras']:
                    break
                if self.coverage_model.deployment_matrix['camera'][grid_id] == 1:
                    count = min(max_cam, self.constraints['total_cameras'] - cam_deployed)
                    cameras[grid_id] = count
                    cam_deployed += count

            drones_to_deploy = min(self.constraints['total_drones'], len(grid_ids_shuffled))
            for i in range(drones_to_deploy):
                grid_id = grid_ids_shuffled[(i + cam_deployed) % len(grid_ids_shuffled)]
                if self.coverage_model.deployment_matrix['drone'][grid_id] == 1:
                    drones[grid_id] = 1

            camps_to_deploy = min(self.constraints['total_camps'], len(grid_ids_shuffled))
            for i in range(camps_to_deploy):
                grid_id = grid_ids_shuffled[(i + cam_deployed + drones_to_deploy) % len(grid_ids_shuffled)]
                if self.coverage_model.deployment_matrix['camp'][grid_id] == 1:
                    camps[grid_id] = 1

            if self.constraints['total_patrol'] > 0 and sum(rangers.values()) < self.constraints['total_patrol']:
                remaining_rangers = self.constraints['total_patrol'] - sum(rangers.values())
                for grid_id in grid_ids_shuffled:
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
        return self.coverage_model.repair_solution(solution, self.constraints, self.force_full_deployment)

    def _initialize_fences(self) -> Dict[Tuple[int, int], int]:
        """初始化围栏部署，支持多围栏边缘部署
        
        遍历所有边缘格子，在其边界边上部署围栏。
        每个边缘格子可以部署多个围栏（每个边界边一个）。
        
        Returns:
            Dict[Tuple[int, int], int]: 围栏部署字典
            - 内部边: (grid_id_1, grid_id_2) -> count (通常为1)
            - 边界边: (grid_id, None) -> count (0到边界边数量)
        """
        fences = dict(self.fixed_fences)  # Start with fixed fences
        total_fence_length = self.constraints.get('total_fence_length', float('inf'))
        max_fences_per_grid = self.constraints.get('max_fences_per_grid', 6)
        
        # Get all fencing edges (both internal and boundary)
        fencing_edges = self.fencing_edges
        
        # Shuffle for random deployment order
        random.shuffle(fencing_edges)
        
        fences_deployed = sum(fences.values())
        
        # FIX: Only deploy fences on boundary edges (edge_type == 2.0)
        # Internal edges between grids are NOT valid fence locations
        for edge in fencing_edges:
            if fences_deployed >= total_fence_length:
                break
            
            grid_id_1, grid_id_2, edge_type = edge
            
            # Only process boundary edges (edge_type == 2.0)
            # Skip internal edges (edge_type == 1.0) - they are not valid fence locations
            if edge_type != 2.0:
                continue
            
            # Boundary edge (grid_id_2 is None)
            # Deploy fences on boundary edges
            boundary_edges = self.grid_model.get_boundary_edges_for_grid(grid_id_1)
            num_boundary_edges = len(boundary_edges)
            
            # Determine how many fences to deploy on this grid
            max_for_grid = min(
                num_boundary_edges,
                max_fences_per_grid,
                self.coverage_model.deployment_matrix['fence'].get(grid_id_1, 0)
            )
            
            # Deploy as many fences as allowed, up to the remaining budget
            remaining_budget = total_fence_length - fences_deployed
            fences_to_deploy = min(max_for_grid, remaining_budget)
            
            if fences_to_deploy > 0:
                edge_key = (grid_id_1, None)
                # Don't overwrite fixed fences
                if edge_key not in self.fixed_fences:
                    fences[edge_key] = fences_to_deploy
                    fences_deployed += fences_to_deploy
        
        return fences

    def initialize_population(self):
        self.population = []
        for _ in range(self.config.population_size):
            self.population.append(self._initialize_solution())

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

    def evaluate_fitness(self, solution: DeploymentSolution) -> float:
        is_valid, violations = self.coverage_model.validate_solution(solution, self.constraints)
        if not is_valid:
            return -len(violations) * 1000
        
        # Use time-aware fitness if configured
        if self.config.use_time_aware_fitness:
            return self.coverage_model.calculate_time_aware_total_benefit(solution)
        else:
            return self.coverage_model.calculate_total_benefit(solution)

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
        if self.stagnation_count > self.config.stagnation_threshold:
            return scheduled * self.config.stagnation_boost
        
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
            # Check boundary edge fences: (grid_id, None)
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
            
            if fence_count <= 0:
                continue
            
            # Check if this grid can have fences (is an edge grid)
            if self.coverage_model.deployment_matrix['fence'].get(grid_id, 0) == 0:
                continue
            
            # Get boundary edges for this grid
            boundary_edges = self.grid_model.get_boundary_edges_for_grid(grid_id)
            num_boundary_edges = len(boundary_edges)
            
            if num_boundary_edges > 0:
                # Limit fence count
                actual_count = min(fence_count, num_boundary_edges, max_fences_per_grid)
                edge_key = (grid_id, None)
                # Don't overwrite fixed fences
                if edge_key not in self.fixed_fences:
                    fences[edge_key] = actual_count

        return DeploymentSolution(
            cameras=cameras,
            camps=camps,
            drones=drones,
            rangers=rangers,
            fences=fences
        )

    def _update_producers(self, iteration: int, alpha: float):
        """Update producer positions with dynamic exploration range.
        
        Args:
            iteration: Current iteration index
            alpha: Current exploration range bound
        """
        num_producers = int(self.config.population_size * self.config.producer_ratio)
        producers = self.population[:num_producers]
        
        escape_count = 0  # 统计警戒更新次数

        for i, solution in enumerate(producers):
            # R2 在每次迭代中随机生成 [0, 1]
            R2 = random.uniform(0, 1)
            
            if R2 < self.config.ST:
                # 正常更新（开发 / exploitation）
                if i == 0:
                    current_vector = self._solution_to_vector(solution)
                    best_vector = self._solution_to_vector(self.best_solution)
                    new_vector = current_vector + np.random.uniform(0, 1, current_vector.shape) * (best_vector - current_vector)
                else:
                    current_vector = self._solution_to_vector(solution)
                    new_vector = current_vector + np.random.uniform(-self.config.exploitation_alpha, self.config.exploitation_alpha, current_vector.shape)
            else:
                # 警戒更新（探索 / exploration）
                escape_count += 1
                current_vector = self._solution_to_vector(solution)
                # 使用更大的随机扰动进行探索
                new_vector = current_vector + np.random.uniform(-alpha, alpha, current_vector.shape)

            new_solution = self.coverage_model.repair_solution(
                self._vector_to_solution(new_vector),
                self.constraints,
                self.force_full_deployment
            )
            
            # 应用冻结资源
            new_solution = self._apply_frozen_resources(new_solution)

            if self.evaluate_fitness(new_solution) > self.evaluate_fitness(solution):
                self.population[i] = new_solution
        
        return escape_count

    def _update_followers(self, alpha: float):
        """Update follower positions with dynamic exploration range.
        
        Args:
            alpha: Current exploration range bound
        """
        num_producers = int(self.config.population_size * self.config.producer_ratio)
        num_followers = int(self.config.population_size * (1 - self.config.producer_ratio))
        followers = self.population[num_producers:num_producers + num_followers]
        
        escape_count = 0  # 统计警戒更新次数

        for i, solution in enumerate(followers):
            # R2 在每次迭代中随机生成 [0, 1]
            R2 = random.uniform(0, 1)
            
            if R2 < self.config.ST:
                # 正常更新（开发 / exploitation）
                if i > self.config.population_size / 2:
                    current_vector = self._solution_to_vector(solution)
                    best_vector = self._solution_to_vector(self.best_solution)
                    new_vector = np.abs(best_vector - current_vector) * np.random.uniform(0, 1, current_vector.shape)
                else:
                    idx = random.randint(0, num_producers - 1)
                    producer = self.population[idx]
                    current_vector = self._solution_to_vector(solution)
                    producer_vector = self._solution_to_vector(producer)
                    new_vector = current_vector + np.random.uniform(0, 1, current_vector.shape) * (producer_vector - current_vector)
            else:
                # 警戒更新（探索 / exploration）
                escape_count += 1
                current_vector = self._solution_to_vector(solution)
                # 使用更大的随机扰动进行探索
                new_vector = current_vector + np.random.uniform(-alpha, alpha, current_vector.shape)

            new_solution = self.coverage_model.repair_solution(
                self._vector_to_solution(new_vector),
                self.constraints,
                self.force_full_deployment
            )
            
            # 应用冻结资源
            new_solution = self._apply_frozen_resources(new_solution)

            if self.evaluate_fitness(new_solution) > self.evaluate_fitness(solution):
                self.population[num_producers + i] = new_solution
        
        return escape_count

    def _update_scouts(self):
        num_scouts = int(self.config.population_size * self.config.scout_ratio)
        start_idx = self.config.population_size - num_scouts

        for i in range(start_idx, self.config.population_size):
            solution = self.population[i]
            if self.evaluate_fitness(solution) < self.config.ST * self.best_fitness:
                self.population[i] = self._initialize_solution()

    def _update_best_solution(self):
        for solution in self.population:
            fitness = self.evaluate_fitness(solution)
            if fitness > self.best_fitness:
                self.best_fitness = fitness
                self.best_solution = solution

    def optimize(self, callback: Callable[[int, float, DeploymentSolution], None] = None) -> Tuple[DeploymentSolution, float, List[float]]:
        import time

        self.initialize_population()
        
        # 保存初始解决方案（用于冻结资源）
        self.initial_solution = self._initialize_solution()

        for solution in self.population:
            fitness = self.evaluate_fitness(solution)
            if fitness > self.best_fitness:
                self.best_fitness = fitness
                self.best_solution = solution

        self.fitness_history = [self.best_fitness]

        total_start = time.time()
        iter_times = []

        num_producers = int(self.config.population_size * self.config.producer_ratio)
        num_scouts = int(self.config.population_size * self.config.scout_ratio)

        for iteration in range(self.config.max_iterations):
            iter_start = time.time()

            # Get the effective exploration alpha for this iteration
            effective_alpha = self._get_exploration_alpha(iteration)
            
            escape_producers = self._update_producers(iteration, effective_alpha)
            escape_followers = self._update_followers(effective_alpha)
            self._update_scouts()
            self._update_best_solution()

            # Update stagnation tracking state
            if self.best_fitness - self.prev_best_fitness > self.config.stagnation_tolerance:
                self.stagnation_count = 0
            else:
                self.stagnation_count += 1
            self.prev_best_fitness = self.best_fitness

            if self.output_dir:
                producers = self.population[:num_producers]
                followers = self.population[num_producers:num_producers + (self.config.population_size - num_producers - num_scouts)]
                scouts = self.population[self.config.population_size - num_scouts:]
                self._async_output_iteration_results(iteration, producers, followers, scouts)
            
            # 计算total benefit
            pb_per_grid = self.coverage_model.calculate_protection_benefit(self.best_solution)
            total_benefit = sum(pb_per_grid.values())

            iter_elapsed = time.time() - iter_start
            iter_times.append(iter_elapsed)
            self.fitness_history.append(self.best_fitness)

            if callback:
                callback(iteration, self.best_fitness, self.best_solution)

            avg_iter = sum(iter_times) / len(iter_times)
            
            # 打印迭代信息
            escape_total = escape_producers + escape_followers
            
            # Build log line with alpha and stagnation boost annotation
            stagnation_annotation = " [STAGNATION_BOOST]" if self.stagnation_count > self.config.stagnation_threshold else ""
            
            if escape_total > 0:
                print(f"Iter {iteration+1:>4}/{self.config.max_iterations}"
                      f"  fitness={self.best_fitness:.6f}"
                      f"  benefit={total_benefit:.6f}"
                      f"  α={effective_alpha:.2f}"
                      f"  [ESCAPE={escape_total}]{stagnation_annotation}"
                      f"  iter={iter_elapsed*1000:.1f}ms"
                      f"  avg={avg_iter*1000:.1f}ms")
            else:
                print(f"Iter {iteration+1:>4}/{self.config.max_iterations}"
                      f"  fitness={self.best_fitness:.6f}"
                      f"  benefit={total_benefit:.6f}"
                      f"  α={effective_alpha:.2f}{stagnation_annotation}"
                      f"  iter={iter_elapsed*1000:.1f}ms"
                      f"  avg={avg_iter*1000:.1f}ms")

        total_elapsed = time.time() - total_start
        pb_per_grid = self.coverage_model.calculate_protection_benefit(self.best_solution)
        final_total_benefit = sum(pb_per_grid.values())
        
        print(f"\nOptimization completed."
              f"  Best Fitness = {self.best_fitness:.6f}"
              f"  Total Benefit = {final_total_benefit:.6f}"
              f"  Total = {total_elapsed:.2f}s"
              f"  Avg/iter = {total_elapsed/self.config.max_iterations*1000:.1f}ms")

        return self.best_solution, self.best_fitness, self.fitness_history

    def get_solution_statistics(self, solution: DeploymentSolution) -> Dict[str, any]:
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

    def _serialize_solution(self, solution: DeploymentSolution) -> Dict[str, any]:
        pb_per_grid = self.coverage_model.calculate_protection_benefit(solution)
        total_benefit = sum(pb_per_grid.values())
        
        return {
            'cameras': {str(k): v for k, v in solution.cameras.items()},
            'camps': {str(k): v for k, v in solution.camps.items()},
            'drones': {str(k): v for k, v in solution.drones.items()},
            'rangers': {str(k): v for k, v in solution.rangers.items()},
            'fences': {f"{k[0]}-{k[1]}": v for k, v in solution.fences.items()},
            'fitness': self.evaluate_fitness(solution),
            'total_protection_benefit': total_benefit,
            'protection_benefit_per_grid': {str(k): round(v, 6) for k, v in pb_per_grid.items()},
            'statistics': self.get_solution_statistics(solution)
        }

    def _async_output_iteration_results(self, iteration: int, producers: List[DeploymentSolution],
                                     followers: List[DeploymentSolution], scouts: List[DeploymentSolution]):
        if not self.output_dir:
            return

        def _write_files():
            try:
                iter_dir = os.path.join(self.output_dir, f"iteration_{iteration:04d}")
                os.makedirs(iter_dir, exist_ok=True)

                producers_data = [self._serialize_solution(s) for s in producers]
                with open(os.path.join(iter_dir, "producers.json"), 'w', encoding='utf-8') as f:
                    json.dump(producers_data, f, indent=2, ensure_ascii=False)

                followers_data = [self._serialize_solution(s) for s in followers]
                with open(os.path.join(iter_dir, "followers.json"), 'w', encoding='utf-8') as f:
                    json.dump(followers_data, f, indent=2, ensure_ascii=False)

                scouts_data = [self._serialize_solution(s) for s in scouts]
                with open(os.path.join(iter_dir, "scouts.json"), 'w', encoding='utf-8') as f:
                    json.dump(scouts_data, f, indent=2, ensure_ascii=False)

            except Exception as e:
                print(f"Warning: Failed to write iteration output: {e}")

        thread = threading.Thread(target=_write_files, daemon=True)
        thread.start()
