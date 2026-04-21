import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from grid_model import HexGridModel
from data_loader import CoverageParameters
from coverage_model import DeploymentSolution


@dataclass
class TimeDynamicSolution:
    cameras: Dict[int, int]
    camps: Dict[int, int]
    drones: Dict[int, List[Tuple[int, int]]]
    rangers: Dict[int, List[Tuple[int, int]]]
    fences: Dict[Tuple[int, int], int]


class DynamicCoverageModel:
    def __init__(self, grid_model: HexGridModel, coverage_params: CoverageParameters,
                 deployment_matrix: Dict[str, Dict[int, int]],
                 visibility_params: Dict[int, Dict[str, float]],
                 coverage_effectiveness: Dict[int, Dict[str, float]] = None):
        self.grid_model = grid_model
        self.params = coverage_params
        self.deployment_matrix = deployment_matrix
        self.visibility_params = visibility_params
        self.coverage_effectiveness = coverage_effectiveness or {}
        self.grid_ids = grid_model.get_all_grid_ids()

    def _effectiveness(self, grid_id: int, resource: str) -> float:
        return self.coverage_effectiveness.get(grid_id, {}).get(resource, 1.0)

    def get_patrol_position(self, ranger_id: int, time: int, solution: TimeDynamicSolution) -> Optional[int]:
        if ranger_id not in solution.rangers:
            return None
        positions = solution.rangers[ranger_id]
        if not positions:
            return None
        closest_pos = min(positions, key=lambda x: abs(x[0] - time))
        return closest_pos[1]

    def get_drone_position(self, drone_id: int, time: int, solution: TimeDynamicSolution) -> Optional[int]:
        if drone_id not in solution.drones:
            return None
        positions = solution.drones[drone_id]
        if not positions:
            return None
        closest_pos = min(positions, key=lambda x: abs(x[0] - time))
        return closest_pos[1]

    def calculate_patrol_coverage(self, solution: TimeDynamicSolution, time: int) -> Dict[int, float]:
        patrol_coverage = {}

        for grid_id in self.grid_ids:
            eff = self._effectiveness(grid_id, 'patrol')
            patrol_intensity = 0.0
            camp_positions = {positions[0][1] for positions in solution.rangers.values() if positions}

            for camp_id, camp_value in solution.camps.items():
                if camp_value == 1 and camp_id in camp_positions:
                    distance = self.grid_model.get_distance(grid_id, camp_id)
                    patrol_intensity += np.exp(-distance / self.params.patrol_radius)

            for ranger_id in solution.rangers:
                pos = self.get_patrol_position(ranger_id, time, solution)
                if pos is not None:
                    distance = self.grid_model.get_distance(grid_id, pos)
                    patrol_intensity += np.exp(-distance / self.params.patrol_radius)

            patrol_coverage[grid_id] = eff * (1 - np.exp(-patrol_intensity))

        return patrol_coverage

    def calculate_drone_coverage(self, solution: TimeDynamicSolution, time: int) -> Dict[int, float]:
        drone_coverage = {}

        for grid_id in self.grid_ids:
            eff = self._effectiveness(grid_id, 'drone')
            visibility = self.visibility_params[grid_id]['drone']
            effective_radius = self.params.drone_radius * visibility

            coverage = 0.0
            for drone_id in solution.drones:
                pos = self.get_drone_position(drone_id, time, solution)
                if pos is not None:
                    distance = self.grid_model.get_distance(grid_id, pos)
                    if distance <= effective_radius * 2:
                        coverage += np.exp(-distance / effective_radius)

            drone_coverage[grid_id] = eff * min(1.0, coverage)

        return drone_coverage

    def calculate_camera_coverage(self, solution: TimeDynamicSolution, time: int) -> Dict[int, float]:
        camera_coverage = {}

        for grid_id in self.grid_ids:
            eff = self._effectiveness(grid_id, 'camera')
            visibility = self.visibility_params[grid_id]['camera']
            effective_radius = self.params.camera_radius * visibility

            coverage = 0.0
            for cam_id, cam_value in solution.cameras.items():
                if cam_value > 0:
                    distance = self.grid_model.get_distance(grid_id, cam_id)
                    if distance <= effective_radius * 2:
                        coverage += cam_value * np.exp(-distance / effective_radius)

            camera_coverage[grid_id] = eff * min(1.0, coverage)

        return camera_coverage

    def calculate_fence_protection(self, solution: TimeDynamicSolution, time: int) -> Dict[int, float]:
        fence_protection = {}

        for grid_id in self.grid_ids:
            eff = self._effectiveness(grid_id, 'fence')
            protection = 0.0
            neighbors = self.grid_model.get_neighbors(grid_id)

            for neighbor_id in neighbors:
                edge_key = tuple(sorted((grid_id, neighbor_id)))
                if edge_key in solution.fences and solution.fences[edge_key] == 1:
                    protection += self.params.fence_protection

            fence_protection[grid_id] = eff * min(1.0, protection)

        return fence_protection

    def calculate_protection_effect(self, solution: TimeDynamicSolution, time: int) -> Dict[int, float]:
        patrol_cov = self.calculate_patrol_coverage(solution, time)
        drone_cov = self.calculate_drone_coverage(solution, time)
        camera_cov = self.calculate_camera_coverage(solution, time)
        fence_prot = self.calculate_fence_protection(solution, time)

        protection_effect = {}
        for grid_id in self.grid_ids:
            protection_effect[grid_id] = (
                self.params.wp * patrol_cov[grid_id] +
                self.params.wd * drone_cov[grid_id] +
                self.params.wc * camera_cov[grid_id] +
                self.params.wf * fence_prot[grid_id]
            )
        return protection_effect

    def calculate_protection_benefit(self, solution: TimeDynamicSolution, time: int) -> Dict[int, float]:
        protection_effect = self.calculate_protection_effect(solution, time)
        protection_benefit = {}

        for grid_id in self.grid_ids:
            risk = self.grid_model.get_grid_risk(grid_id)
            E_i = protection_effect[grid_id]
            protection_benefit[grid_id] = risk * (1 - np.exp(-E_i))

        return protection_benefit

    def calculate_total_benefit(self, solution: TimeDynamicSolution, time: int) -> float:
        protection_benefit = self.calculate_protection_benefit(solution, time)
        total_risk = 0.0
        for grid_id in self.grid_ids:
            total_risk += self.grid_model.get_grid_risk(grid_id)

        total_benefit = sum(protection_benefit.values())
        if total_risk > 0:
            total_benefit = total_benefit / total_risk
        return total_benefit

    def simulate_protection_over_time(self, solution: TimeDynamicSolution, time_steps: int) -> List[float]:
        return [self.calculate_total_benefit(solution, t) for t in range(1, time_steps + 1)]

    def estimate_minimum_staffing(self, base_solution: DeploymentSolution, time_steps: int,
                                 target_protection: float, max_patrol: int = 20) -> int:
        def convert_to_dynamic_solution(patrol_count: int) -> TimeDynamicSolution:
            rangers_time_series = {}
            for i in range(patrol_count):
                positions = []
                for t in range(1, time_steps + 1):
                    pos = np.random.choice(self.grid_ids)
                    positions.append((t, pos))
                rangers_time_series[i] = positions

            drones_time_series = {}
            for drone_id in base_solution.drones:
                positions = []
                for t in range(1, time_steps + 1):
                    if t % 4 < 3:
                        pos = np.random.choice(self.grid_ids)
                    else:
                        pos = drone_id
                    positions.append((t, pos))
                drones_time_series[drone_id] = positions

            return TimeDynamicSolution(
                cameras=base_solution.cameras,
                camps=base_solution.camps,
                drones=drones_time_series,
                rangers=rangers_time_series,
                fences=base_solution.fences
            )

        for patrol_count in range(1, max_patrol + 1):
            dynamic_solution = convert_to_dynamic_solution(patrol_count)
            avg_protection = np.mean(self.simulate_protection_over_time(dynamic_solution, time_steps))
            if avg_protection >= target_protection:
                return patrol_count

        return max_patrol

    def generate_patrol_routes(self, patrol_count: int, time_steps: int) -> Dict[int, List[Tuple[int, int]]]:
        routes = {}
        for i in range(patrol_count):
            route = []
            current_pos = np.random.choice(self.grid_ids)
            for t in range(1, time_steps + 1):
                neighbors = self.grid_model.get_neighbors(current_pos)
                if neighbors:
                    current_pos = np.random.choice(neighbors + [current_pos])
                route.append((t, current_pos))
            routes[i] = route
        return routes

    def generate_drone_schedules(self, drone_count: int, time_steps: int) -> Dict[int, List[Tuple[int, int]]]:
        schedules = {}
        for i in range(drone_count):
            schedule = []
            base_pos = np.random.choice(self.grid_ids)
            for t in range(1, time_steps + 1):
                if t % 4 < 3:
                    flight_pos = np.random.choice(self.grid_ids)
                    schedule.append((t, flight_pos))
                else:
                    schedule.append((t, base_pos))
            schedules[i] = schedule
        return schedules
