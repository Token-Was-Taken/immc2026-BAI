import numpy as np
from typing import Dict, List, Tuple
from dataclasses import dataclass
from grid_model import HexGridModel
from data_loader import CoverageParameters


@dataclass
class DeploymentSolution:
    cameras: Dict[int, int]
    camps: Dict[int, int]
    drones: Dict[int, int]
    rangers: Dict[int, int]
    fences: Dict[Tuple[int, int], int]


class CoverageModel:
    def __init__(self, grid_model: HexGridModel, coverage_params: CoverageParameters,
                 deployment_matrix: Dict[str, Dict[int, int]],
                 visibility_params: Dict[int, Dict[str, float]],
                 coverage_effectiveness: Dict[int, Dict[str, float]] = None):
        self.grid_model = grid_model
        self.params = coverage_params
        self.deployment_matrix = deployment_matrix
        self.visibility_params = visibility_params
        # coverage_effectiveness[grid_id][resource] = multiplier (default 1.0)
        self.coverage_effectiveness = coverage_effectiveness or {}
        self.grid_ids = grid_model.get_all_grid_ids()

    def _effectiveness(self, grid_id: int, resource: str) -> float:
        return self.coverage_effectiveness.get(grid_id, {}).get(resource, 1.0)

    def calculate_patrol_coverage(self, solution: DeploymentSolution) -> Dict[int, float]:
        patrol_coverage = {}

        for grid_id in self.grid_ids:
            eff = self._effectiveness(grid_id, 'patrol')
            patrol_intensity = 0.0

            for camp_id, camp_value in solution.camps.items():
                if camp_value == 1:
                    rangers = solution.rangers.get(camp_id, 0)
                    distance = self.grid_model.get_distance(grid_id, camp_id)
                    patrol_intensity += rangers * np.exp(-distance / self.params.patrol_radius)

            for ranger_id, ranger_count in solution.rangers.items():
                if ranger_count > 0 and ranger_id not in solution.camps:
                    distance = self.grid_model.get_distance(grid_id, ranger_id)
                    patrol_intensity += ranger_count * np.exp(-distance / self.params.patrol_radius)

            patrol_coverage[grid_id] = eff * (1 - np.exp(-patrol_intensity))

        return patrol_coverage

    def calculate_drone_coverage(self, solution: DeploymentSolution) -> Dict[int, float]:
        drone_coverage = {}

        for grid_id in self.grid_ids:
            eff = self._effectiveness(grid_id, 'drone')
            visibility = self.visibility_params[grid_id]['drone']
            effective_radius = self.params.drone_radius * visibility

            coverage = 0.0
            for drone_id, drone_value in solution.drones.items():
                if drone_value == 1:
                    distance = self.grid_model.get_distance(grid_id, drone_id)
                    if distance <= effective_radius * 2:
                        coverage += np.exp(-distance / effective_radius)

            drone_coverage[grid_id] = eff * min(1.0, coverage)

        return drone_coverage

    def calculate_camera_coverage(self, solution: DeploymentSolution) -> Dict[int, float]:
        camera_coverage = {}

        for grid_id in self.grid_ids:
            eff = self._effectiveness(grid_id, 'camera')
            visibility = self.visibility_params[grid_id]['camera']
            effective_radius = self.params.camera_radius * visibility

            coverage = 0.0
            for cam_id, cam_count in solution.cameras.items():
                if cam_count > 0:
                    distance = self.grid_model.get_distance(grid_id, cam_id)
                    if distance <= effective_radius * 2:
                        coverage += cam_count * np.exp(-distance / effective_radius)

            camera_coverage[grid_id] = eff * min(1.0, coverage)

        return camera_coverage

    def calculate_fence_protection(self, solution: DeploymentSolution) -> Dict[int, float]:
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

    def calculate_protection_effect(self, solution: DeploymentSolution) -> Dict[int, float]:
        patrol_cov = self.calculate_patrol_coverage(solution)
        drone_cov = self.calculate_drone_coverage(solution)
        camera_cov = self.calculate_camera_coverage(solution)
        fence_prot = self.calculate_fence_protection(solution)

        protection_effect = {}

        for grid_id in self.grid_ids:
            E_i = (self.params.wp * patrol_cov[grid_id] +
                   self.params.wd * drone_cov[grid_id] +
                   self.params.wc * camera_cov[grid_id] +
                   self.params.wf * fence_prot[grid_id])

            protection_effect[grid_id] = E_i

        return protection_effect

    def calculate_protection_benefit(self, solution: DeploymentSolution) -> Dict[int, float]:
        protection_effect = self.calculate_protection_effect(solution)
        protection_benefit = {}

        for grid_id in self.grid_ids:
            risk = self.grid_model.get_grid_risk(grid_id)
            E_i = protection_effect[grid_id]
            protection_benefit[grid_id] = risk * (1 - np.exp(-E_i))

        return protection_benefit

    def calculate_total_benefit(self, solution: DeploymentSolution) -> float:
        protection_benefit = self.calculate_protection_benefit(solution)
        total_risk = 0.0
        for grid_id in self.grid_ids:
            total_risk += self.grid_model.get_grid_risk(grid_id)

        total_benefit = sum(protection_benefit.values())
        if total_risk > 0:
            total_benefit = total_benefit / total_risk

        return total_benefit

    def calculate_time_aware_total_benefit(self, solution: DeploymentSolution) -> float:
        """
        Calculate fitness using time-weighted risk.
        
        This applies temporal factors (diurnal and seasonal) to normalized risk,
        so resource allocation reflects temporal risk differences.
        
        Formula:
            fitness = total_protection_benefit / total_risk_weighted
            where total_risk_weighted = Σ [R_i × T_t × S_t]
        
        Result: Resources are allocated to reflect temporal risk differences.
        For example, if night risk is 1.3x day risk, night areas get more resources.
        """
        protection_benefit = self.calculate_protection_benefit(solution)
        total_risk_weighted = 0.0
        for grid_id in self.grid_ids:
            normalized_risk = self.grid_model.get_grid_risk(grid_id)
            temporal_factor = self.grid_model.get_grid_temporal_factor(grid_id)
            total_risk_weighted += normalized_risk * temporal_factor

        total_benefit = sum(protection_benefit.values())
        if total_risk_weighted > 0:
            total_benefit = total_benefit / total_risk_weighted

        return total_benefit

    def validate_solution(self, solution: DeploymentSolution,
                          constraints: Dict[str, any]) -> Tuple[bool, List[str]]:
        violations = []

        total_cameras = sum(solution.cameras.values())
        if total_cameras > constraints['total_cameras']:
            violations.append(f"Camera limit exceeded: {total_cameras} > {constraints['total_cameras']}")

        total_drones = sum(solution.drones.values())
        if total_drones > constraints['total_drones']:
            violations.append(f"Drone limit exceeded: {total_drones} > {constraints['total_drones']}")

        total_camps = sum(solution.camps.values())
        if total_camps > constraints['total_camps']:
            violations.append(f"Camp limit exceeded: {total_camps} > {constraints['total_camps']}")

        total_rangers = sum(solution.rangers.values())
        if total_rangers > constraints['total_patrol']:
            violations.append(f"Patrol limit exceeded: {total_rangers} > {constraints['total_patrol']}")

        for grid_id in self.grid_ids:
            has_camp = solution.camps.get(grid_id, 0) > 0
            has_ranger = solution.rangers.get(grid_id, 0) > 0
            if has_camp and has_ranger:
                violations.append(f"Patrol and camp cannot share the same grid: {grid_id}")

        # Check single resource type per grid
        for grid_id in self.grid_ids:
            count = sum([
                solution.camps.get(grid_id, 0) > 0,
                solution.rangers.get(grid_id, 0) > 0,
                solution.cameras.get(grid_id, 0) > 0,
                solution.drones.get(grid_id, 0) > 0,
            ])
            if count > 1:
                violations.append(f"Multiple resource types on same grid: {grid_id}")

        for grid_id in self.grid_ids:
            cam_count = solution.cameras.get(grid_id, 0)
            max_cam = constraints.get('max_cameras_per_grid', 1)
            if cam_count > self.deployment_matrix['camera'][grid_id] * max_cam:
                violations.append(f"Camera deployment infeasible at grid {grid_id}")

            if solution.camps.get(grid_id, 0) > self.deployment_matrix['camp'][grid_id]:
                violations.append(f"Camp deployment infeasible at grid {grid_id}")

            if solution.drones.get(grid_id, 0) > self.deployment_matrix['drone'][grid_id]:
                violations.append(f"Drone deployment infeasible at grid {grid_id}")

        for edge_key, fence_count in solution.fences.items():
            if fence_count <= 0:
                continue
            gid1, gid2 = edge_key
            if (self.deployment_matrix['fence'].get(gid1, 0) != 1 or
                    self.deployment_matrix['fence'].get(gid2, 0) != 1):
                violations.append(f"Fence deployment infeasible at edge {edge_key}")

        return (len(violations) == 0, violations)

    def repair_solution(self, solution: DeploymentSolution,
                       constraints: Dict[str, any],
                       force_full_deployment: bool = True) -> DeploymentSolution:
        cleaned_cameras = {k: v for k, v in solution.cameras.items()
                           if v > 0 and self.deployment_matrix['camera'].get(k, 0) == 1}
        cleaned_camps = {k: v for k, v in solution.camps.items()
                         if v > 0 and self.deployment_matrix['camp'].get(k, 0) == 1}
        cleaned_drones = {k: v for k, v in solution.drones.items()
                          if v > 0 and self.deployment_matrix['drone'].get(k, 0) == 1}
        cleaned_rangers = {k: v for k, v in solution.rangers.items()
                           if v > 0 and self.deployment_matrix['patrol'].get(k, 0) == 1}
        cleaned_fences = {k: v for k, v in solution.fences.items() if v > 0}

        repaired = DeploymentSolution(
            cameras=cleaned_cameras,
            camps=cleaned_camps,
            drones=cleaned_drones,
            rangers=cleaned_rangers,
            fences=cleaned_fences
        )

        for grid_id in self.grid_ids:
            if repaired.cameras.get(grid_id, 0) > self.deployment_matrix['camera'][grid_id]:
                repaired.cameras.pop(grid_id, None)

            if repaired.camps.get(grid_id, 0) > self.deployment_matrix['camp'][grid_id]:
                repaired.camps.pop(grid_id, None)
                repaired.rangers.pop(grid_id, None)

            if repaired.drones.get(grid_id, 0) > self.deployment_matrix['drone'][grid_id]:
                repaired.drones.pop(grid_id, None)

        # Ensure patrol and camp cannot be in the same grid
        for grid_id in list(repaired.rangers.keys()):
            if grid_id in repaired.camps:
                repaired.rangers.pop(grid_id, None)

        # Ensure only one resource type per grid (camera, drone, camp, patrol are mutually exclusive)
        # Priority: patrol > drone > camera > camp
        for grid_id in self.grid_ids:
            types_present = []
            if repaired.rangers.get(grid_id, 0) > 0:
                types_present.append('patrol')
            if repaired.drones.get(grid_id, 0) > 0:
                types_present.append('drone')
            if repaired.cameras.get(grid_id, 0) > 0:
                types_present.append('camera')
            if repaired.camps.get(grid_id, 0) > 0:
                types_present.append('camp')

            if len(types_present) > 1:
                keep = types_present[0]  # highest priority wins
                if keep != 'patrol':
                    repaired.rangers.pop(grid_id, None)
                if keep != 'drone':
                    repaired.drones.pop(grid_id, None)
                if keep != 'camera':
                    repaired.cameras.pop(grid_id, None)
                if keep != 'camp':
                    repaired.camps.pop(grid_id, None)

        for edge_key in list(repaired.fences.keys()):
            gid1, gid2 = edge_key
            if (self.deployment_matrix['fence'].get(gid1, 0) != 1 or
                    self.deployment_matrix['fence'].get(gid2, 0) != 1):
                del repaired.fences[edge_key]

        # --- Camera: 先截单格上限，再截总量 ---
        max_cam = constraints.get('max_cameras_per_grid', 1)
        for grid_id in list(repaired.cameras.keys()):
            if repaired.cameras[grid_id] > max_cam:
                repaired.cameras[grid_id] = max_cam

        total_cameras = sum(repaired.cameras.values())
        while total_cameras > constraints['total_cameras']:
            for grid_id in list(repaired.cameras.keys()):
                repaired.cameras[grid_id] -= 1
                if repaired.cameras[grid_id] <= 0:
                    del repaired.cameras[grid_id]
                total_cameras -= 1
                if total_cameras <= constraints['total_cameras']:
                    break

        # --- Drone: 先截单格上限（max=1），再截总量 ---
        max_drone = constraints.get('max_drones_per_grid', 1)
        for grid_id in list(repaired.drones.keys()):
            if repaired.drones[grid_id] > max_drone:
                repaired.drones[grid_id] = max_drone

        total_drones = sum(repaired.drones.values())
        while total_drones > constraints['total_drones']:
            for grid_id in list(repaired.drones.keys()):
                del repaired.drones[grid_id]
                total_drones -= 1
                if total_drones <= constraints['total_drones']:
                    break

        # --- Camp: 先截单格上限（max=1），再截总量，联动清除 rangers ---
        max_camp = constraints.get('max_camps_per_grid', 1)
        for grid_id in list(repaired.camps.keys()):
            if repaired.camps[grid_id] > max_camp:
                repaired.camps[grid_id] = max_camp

        total_camps = sum(repaired.camps.values())
        while total_camps > constraints['total_camps']:
            for grid_id in list(repaired.camps.keys()):
                del repaired.camps[grid_id]
                repaired.rangers.pop(grid_id, None)
                total_camps -= 1
                if total_camps <= constraints['total_camps']:
                    break

        # 先按单格上限截断
        max_ranger = constraints.get('max_rangers_per_grid', 1)
        for grid_id in list(repaired.rangers.keys()):
            if self.deployment_matrix['patrol'].get(grid_id, 0) == 0:
                del repaired.rangers[grid_id]
            elif repaired.rangers[grid_id] > max_ranger:
                repaired.rangers[grid_id] = max_ranger

        # 再按总量截断
        total_rangers = sum(repaired.rangers.values())
        while total_rangers > constraints['total_patrol']:
            for grid_id in list(repaired.rangers.keys()):
                repaired.rangers[grid_id] -= 1
                if repaired.rangers[grid_id] <= 0:
                    del repaired.rangers[grid_id]
                total_rangers -= 1
                if total_rangers <= constraints['total_patrol']:
                    break

        # 重新计算，补充不足的部分（不超过可用格子数）
        total_rangers = sum(repaired.rangers.values())
        if constraints['total_patrol'] > 0 and total_rangers < constraints['total_patrol']:
            remaining_rangers = constraints['total_patrol'] - total_rangers
            for grid_id in self.grid_ids:
                if remaining_rangers <= 0:
                    break
                if (grid_id not in repaired.camps and
                        grid_id not in repaired.rangers and
                        self.deployment_matrix['patrol'][grid_id] == 1):
                    repaired.rangers[grid_id] = 1
                    remaining_rangers -= 1

        # 如果启用强制部署模式，补充所有未达到上限的资源
        if force_full_deployment:
            import random
            
            # 补充摄像头
            total_cameras = sum(repaired.cameras.values())
            if total_cameras < constraints['total_cameras']:
                available_grids = [gid for gid in self.grid_ids 
                                  if self.deployment_matrix['camera'][gid] == 1]
                random.shuffle(available_grids)
                max_cam = constraints.get('max_cameras_per_grid', 1)
                
                for grid_id in available_grids:
                    if total_cameras >= constraints['total_cameras']:
                        break
                    current = repaired.cameras.get(grid_id, 0)
                    can_add = min(max_cam - current, constraints['total_cameras'] - total_cameras)
                    if can_add > 0:
                        repaired.cameras[grid_id] = current + can_add
                        total_cameras += can_add
            
            # 补充无人机
            total_drones = sum(repaired.drones.values())
            if total_drones < constraints['total_drones']:
                available_grids = [gid for gid in self.grid_ids 
                                  if self.deployment_matrix['drone'][gid] == 1
                                  and gid not in repaired.drones]
                random.shuffle(available_grids)
                max_drone = constraints.get('max_drones_per_grid', 1)
                
                for grid_id in available_grids:
                    if total_drones >= constraints['total_drones']:
                        break
                    repaired.drones[grid_id] = 1
                    total_drones += 1
            
            # 补充营地
            total_camps = sum(repaired.camps.values())
            if total_camps < constraints['total_camps']:
                available_grids = [gid for gid in self.grid_ids 
                                  if self.deployment_matrix['camp'][gid] == 1
                                  and gid not in repaired.camps]
                random.shuffle(available_grids)
                max_camp = constraints.get('max_camps_per_grid', 1)
                
                for grid_id in available_grids:
                    if total_camps >= constraints['total_camps']:
                        break
                    repaired.camps[grid_id] = 1
                    total_camps += 1
            
            # 补充巡逻人员（如果之前没有补充完）
            total_rangers = sum(repaired.rangers.values())
            if total_rangers < constraints['total_patrol']:
                available_grids = [gid for gid in self.grid_ids
                                  if self.deployment_matrix['patrol'][gid] == 1
                                  and gid not in repaired.camps
                                  and gid not in repaired.rangers]
                random.shuffle(available_grids)

                for grid_id in available_grids:
                    if total_rangers >= constraints['total_patrol']:
                        break
                    repaired.rangers[grid_id] = 1
                    total_rangers += 1

        return repaired
