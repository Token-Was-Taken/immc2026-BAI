import numpy as np
from typing import Dict, List, Tuple, Callable, Optional
from dataclasses import dataclass, asdict
import random
import json
import os
import threading
import concurrent.futures
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
    save_iteration_visualization: bool = False  # 是否保存每轮迭代的 deployment map 可视化

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
                 force_full_deployment: bool = True, frozen_resources: List[str] = None,
                 input_grids: List[Dict] = None, raw_risk_map: Dict = None):
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

        # 保存构建输出 JSON 所需的参数
        self.input_grids = input_grids
        self.raw_risk_map = raw_risk_map

        # Thread pool for parallel fitness evaluation
        self._fitness_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=min(16, self.config.population_size),
            thread_name_prefix='fitness'
        )

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
        """Evaluate fitness for multiple solutions in parallel using thread pool."""
        futures = [self._fitness_executor.submit(self.evaluate_fitness, sol)
                   for sol in solutions]
        return [f.result() for f in concurrent.futures.as_completed(futures)]

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
        # Further amplify alpha if stagnation persists for extended periods
        if self.stagnation_count > self.config.stagnation_threshold:
            # Base boost + additional amplification for persistent stagnation
            # stagnation_count - stagnation_threshold gives how many iterations beyond threshold
            extra_amplification = max(0, (self.stagnation_count - self.config.stagnation_threshold) // 10)
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
        """Update producer positions with dynamic exploration range.

        Args:
            iteration: Current iteration index
            alpha: Current exploration range bound
        """
        num_producers = int(self.config.population_size * self.config.producer_ratio)
        producers = self.population[:num_producers]

        escape_count = 0  # 统计警戒更新次数

        new_solutions = []
        old_solutions = []
        indices = []

        for i, solution in enumerate(producers):
            R2 = random.uniform(0, 1)

            if R2 < self.config.ST:
                if i == 0:
                    current_vector = self._solution_to_vector(solution)
                    best_vector = self._solution_to_vector(self.best_solution)
                    new_vector = current_vector + np.random.uniform(0, 1, current_vector.shape) * (best_vector - current_vector)
                else:
                    current_vector = self._solution_to_vector(solution)
                    new_vector = current_vector + np.random.uniform(-self.config.exploitation_alpha, self.config.exploitation_alpha, current_vector.shape)
            else:
                escape_count += 1
                current_vector = self._solution_to_vector(solution)
                new_vector = current_vector + np.random.uniform(-alpha, alpha, current_vector.shape)

            new_solution = self.coverage_model.repair_solution(
                self._vector_to_solution(new_vector),
                self.constraints,
                self.force_full_deployment
            )
            new_solution = self._apply_frozen_resources(new_solution)

            new_solutions.append(new_solution)
            old_solutions.append(solution)
            indices.append(i)

        all_solutions = new_solutions + old_solutions
        all_fitnesses = self._evaluate_fitness_parallel(all_solutions)
        new_fitnesses = all_fitnesses[:len(new_solutions)]
        old_fitnesses = all_fitnesses[len(new_solutions):]

        for i, new_fit, old_fit in zip(indices, new_fitnesses, old_fitnesses):
            if new_fit > old_fit:
                self.population[i] = new_solutions[i]

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

        new_solutions = []
        old_solutions = []
        indices = []

        for i, solution in enumerate(followers):
            R2 = random.uniform(0, 1)

            if R2 < self.config.ST:
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
                escape_count += 1
                current_vector = self._solution_to_vector(solution)
                new_vector = current_vector + np.random.uniform(-alpha, alpha, current_vector.shape)

            new_solution = self.coverage_model.repair_solution(
                self._vector_to_solution(new_vector),
                self.constraints,
                self.force_full_deployment
            )
            new_solution = self._apply_frozen_resources(new_solution)

            new_solutions.append(new_solution)
            old_solutions.append(solution)
            indices.append(num_producers + i)

        all_solutions = new_solutions + old_solutions
        all_fitnesses = self._evaluate_fitness_parallel(all_solutions)
        new_fitnesses = all_fitnesses[:len(new_solutions)]
        old_fitnesses = all_fitnesses[len(new_solutions):]

        for i, new_fit, old_fit in zip(indices, new_fitnesses, old_fitnesses):
            if new_fit > old_fit:
                self.population[i] = new_solutions[i - num_producers]

        return escape_count

    def _update_scouts(self):
        num_scouts = int(self.config.population_size * self.config.scout_ratio)
        start_idx = self.config.population_size - num_scouts

        for i in range(start_idx, self.config.population_size):
            solution = self.population[i]
            if self.evaluate_fitness(solution) < self.config.ST * self.best_fitness:
                self.population[i] = self._initialize_solution()

    def _update_best_solution(self):
        fitnesses = self._evaluate_fitness_parallel(self.population)
        for solution, fitness in zip(self.population, fitnesses):
            if fitness > self.best_fitness:
                self.best_fitness = fitness
                self.best_solution = solution

    def optimize(self, callback: Callable[[int, float, DeploymentSolution], None] = None) -> Tuple[DeploymentSolution, float, List[float]]:
        import time

        self.initialize_population()
        
        # 保存初始解决方案（用于冻结资源）
        self.initial_solution = self._initialize_solution()

        fitnesses = self._evaluate_fitness_parallel(self.population)
        for solution, fitness in zip(self.population, fitnesses):
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
                self._async_plot_iteration_deployment(iteration, self.best_solution)
            
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
            if self.stagnation_count > self.config.stagnation_threshold:
                extra_amp = max(0, (self.stagnation_count - self.config.stagnation_threshold) // 10)
                stagnation_annotation = f" [STAGNATION_BOOST×{1.0 + 0.5 * extra_amp:.1f}]"
            else:
                stagnation_annotation = ""
            
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

        self._fitness_executor.shutdown(wait=True)

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

    def _build_output_for_solution(self, solution: DeploymentSolution) -> Dict[str, any]:
        """构建完整的输出 JSON 结构（类似 protection_pipeline.py 中的逻辑）
        """
        import numpy as np
        
        pb_per_grid = self.coverage_model.calculate_protection_benefit(solution)
        total_risk = sum(self.grid_model.get_grid_risk(gid) for gid in self.grid_model.get_all_grid_ids())

        total_risk_weighted = 0.0
        for gid in self.grid_model.get_all_grid_ids():
            normalized_risk = self.grid_model.get_grid_risk(gid)
            temporal_factor = self.grid_model.get_grid_temporal_factor(gid)
            total_risk_weighted += normalized_risk * temporal_factor

        total_protection_benefit = sum(pb_per_grid.values())
        avg_protection_benefit = float(np.mean(list(pb_per_grid.values())))

        risk_vals = [self.grid_model.get_grid_risk(gid) for gid in self.grid_model.get_all_grid_ids()]
        risk_min, risk_max = min(risk_vals), max(risk_vals)

        protection_effect = self.coverage_model.calculate_protection_effect(solution)

        rr_per_grid = {
            gid: self.grid_model.get_grid_risk(gid) * np.exp(-protection_effect[gid])
            for gid in self.grid_model.get_all_grid_ids()
        }

        def norm_unified_risk(v):
            return float((v - risk_min) / (risk_max - risk_min)) if risk_max != risk_min else float(v)

        pb_vals = list(pb_per_grid.values())
        pb_min, pb_max = min(pb_vals), max(pb_vals)

        def norm_pb(v):
            return float((v - pb_min) / (pb_max - pb_min)) if pb_max != pb_min else float(v)

        input_grid_map = {g['grid_id']: g for g in (self.input_grids or [])} if self.input_grids else {}
        grid_results = []
        
        if self.input_grids:
            for grid in self.input_grids:
                gid = grid['grid_id']
                src = grid
                entry = {
                    'grid_id': gid,
                    'q': grid.get('q', 0),
                    'r': grid.get('r', 0),
                    'x': grid.get('x', 0),
                    'y': grid.get('y', 0),
                    'terrain_type': grid.get('terrain_type', 'SparseGrass'),
                    'risk_normalized': round(norm_unified_risk(self.grid_model.get_grid_risk(gid)), 6),
                    'raw_risk': round(float(self.raw_risk_map.get(gid, 0.0)) if self.raw_risk_map else 0.0, 6),
                    'protection_benefit_raw': round(float(pb_per_grid.get(gid, 0.0)), 6),
                    'protection_benefit_normalized': round(norm_pb(pb_per_grid.get(gid, 0.0)), 6),
                    'residual_risk_normalized': round(norm_unified_risk(rr_per_grid.get(gid, 0.0)), 6),
                    'deployment': {
                        'patrol_rangers': int(solution.rangers.get(gid, 0)),
                        'camp': int(solution.camps.get(gid, 0)),
                        'drone': int(solution.drones.get(gid, 0)),
                        'camera': int(solution.cameras.get(gid, 0))
                    }
                }
                
                grid_fence_edges = [(e[0], e[1]) for e, v in solution.fences.items() if v > 0 and e[0] == gid and isinstance(e[1], int)]
                if grid_fence_edges:
                    entry['fences'] = {
                        'fence_count': len(grid_fence_edges),
                        'boundary_edge_list': [direction for _, direction in grid_fence_edges]
                    }
                
                if 'hex_size' in grid:
                    entry['hex_size'] = grid['hex_size']
                grid_results.append(entry)
        
        all_gids = self.grid_model.get_all_grid_ids()
        norm_risk_vals = [self.grid_model.get_grid_risk(gid) for gid in all_gids]
        raw_risk_vals = [float(self.raw_risk_map.get(gid, 0.0)) if self.raw_risk_map else 0.0 for gid in all_gids]
        residual_vals = [norm_unified_risk(rr_per_grid[gid]) for gid in all_gids]
        total_residual = sum(rr_per_grid[gid] for gid in all_gids)

        output = {
            'summary': {
                'total_grids': self.grid_model.get_grid_count(),
                'total_risk': round(float(total_risk), 6),
                'total_risk_weighted': round(float(total_risk_weighted), 6),
                'best_fitness': round(float(self.evaluate_fitness(solution)), 6),
                'total_protection_benefit': round(float(total_protection_benefit), 6),
                'average_protection_benefit': round(float(avg_protection_benefit), 6),
                'risk_min': round(min(norm_risk_vals), 6),
                'risk_max': round(max(norm_risk_vals), 6),
                'risk_mean': round(float(np.mean(norm_risk_vals)), 6),
                'raw_risk_min': round(min(raw_risk_vals), 6),
                'raw_risk_max': round(max(raw_risk_vals), 6),
                'raw_risk_mean': round(float(np.mean(raw_risk_vals)), 6),
                'residual_risk_min': round(min(residual_vals), 6),
                'residual_risk_max': round(max(residual_vals), 6),
                'residual_risk_mean': round(float(np.mean(residual_vals)), 6),
                'total_residual_risk': round(float(total_residual), 6),
                'fitness_history': [round(float(f), 6) for f in self.fitness_history],
                'resources_deployed': {
                    'total_cameras': int(sum(solution.cameras.values())),
                    'total_drones': int(sum(solution.drones.values())),
                    'total_camps': int(sum(solution.camps.values())),
                    'total_rangers': int(sum(solution.rangers.values())),
                    'fence_segments': sum(1 for v in solution.fences.values() if v > 0)
                }
            },
            'visualization_config': {
                'show_grid_ids': False
            },
            'grids': grid_results
        }
        
        return output

    def _async_plot_iteration_deployment(self, iteration: int, solution: DeploymentSolution):
        """异步绘制当前迭代的最优 deployment map"""
        if not (self.output_dir and self.config.save_iteration_visualization):
            return
        if not (self.input_grids):
            return

        def _plot():
            try:
                import sys
                import os
                from visualize_output import plot_terrain_deployment_map

                iter_dir = os.path.join(self.output_dir, f"iteration_{iteration:04d}")
                os.makedirs(iter_dir, exist_ok=True)

                out = self._build_output_for_solution(solution)

                hex_size = self.input_grids[0].get('hex_size', 10) if len(self.input_grids) > 0 else 10

                x_coords = [g.get('x', 0) for g in self.input_grids] if self.input_grids else []
                y_coords = [g.get('y', 0) for g in self.input_grids] if self.input_grids else []
                boundary_xy = (
                    (min(x_coords) - hex_size, min(y_coords) - hex_size),
                    (max(x_coords) + hex_size, max(y_coords) + hex_size)) if x_coords and y_coords else None

                if boundary_xy and out['grids']:
                    plot_terrain_deployment_map(out, hex_size, boundary_xy, 
                                                os.path.join(iter_dir, "deployment_map.png"))

            except Exception as e:
                print(f"Warning: Failed to plot iteration {iteration} deployment: {e}")
                import traceback
                traceback.print_exc()

        thread = threading.Thread(target=_plot, daemon=True)
        thread.start()
