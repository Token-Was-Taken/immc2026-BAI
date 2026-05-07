import numpy as np
import random
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
        """
        Calculate fence protection for each grid.

        Each fence on a boundary edge provides protection to the grid.
        Multiple fences on the same grid provide cumulative protection.

        Supports both:
        - Internal edges: (grid_id_1, grid_id_2) with count 1
        - Boundary edges: (grid_id, direction) with count 1 each, direction is 0-5
        """
        fence_protection = {}

        for grid_id in self.grid_ids:
            eff = self._effectiveness(grid_id, 'fence')
            protection = 0.0
            neighbors = self.grid_model.get_neighbors(grid_id)

            # Check internal edges (between two grids)
            for neighbor_id in neighbors:
                edge_key = tuple(sorted((grid_id, neighbor_id)))
                if edge_key in solution.fences:
                    fence_count = solution.fences[edge_key]
                    protection += fence_count * self.params.fence_protection

            # Check boundary edges (grid_id, direction) - each direction stored separately
            for direction in range(6):
                boundary_edge_key = (grid_id, direction)
                if boundary_edge_key in solution.fences:
                    fence_count = solution.fences[boundary_edge_key]
                    protection += fence_count * self.params.fence_protection

            fence_protection[grid_id] = eff * min(1.0, protection)

        return fence_protection

    def calculate_protection_effect(self, solution: DeploymentSolution) -> Dict[int, float]:
        patrol_cov = self.calculate_patrol_coverage(solution)
        drone_cov = self.calculate_drone_coverage(solution)
        camera_cov = self.calculate_camera_coverage(solution)
        fence_prot = self.calculate_fence_protection(solution)

        protection_effect = {}

        for grid_id in self.grid_ids:
            P = patrol_cov[grid_id]
            D = drone_cov[grid_id]
            C = camera_cov[grid_id]
            F = fence_prot[grid_id]

            # Base contributions
            base = (self.params.wp * P +
                    self.params.wd * D +
                    self.params.wc * C +
                    self.params.wf * F)

            # Synergy terms (normalized to prevent explosive growth)
            synergy_pd = self.params.alpha_pd * (P * D) / (1.0 + P + D) if (P > 0 or D > 0) else 0.0
            synergy_pc = self.params.alpha_pc * (P * C) / (1.0 + P + C) if (P > 0 or C > 0) else 0.0

            E_i = base + synergy_pd + synergy_pc

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

            # Handle boundary edges (gid2 is an int 0-5) - fence on specific direction
            if isinstance(gid2, int) and gid2 in range(6):
                max_fences = self.deployment_matrix['fence'].get(gid1, 0)
                if max_fences == 0:
                    violations.append(f"Fence deployment infeasible at grid {gid1} (not an edge grid)")
            elif gid2 is None:
                # Legacy format: (gid1, None) - treat as needing validation
                max_fences = self.deployment_matrix['fence'].get(gid1, 0)
                if max_fences == 0:
                    violations.append(f"Fence deployment infeasible at grid {gid1} (not an edge grid)")
            else:
                # Internal edge - check both endpoints
                if (self.deployment_matrix['fence'].get(gid1, 0) != 1 or
                        self.deployment_matrix['fence'].get(gid2, 0) != 1):
                    violations.append(f"Fence deployment infeasible at edge {edge_key}")

        # Check total fence length constraint
        total_fences = sum(solution.fences.values())
        total_fence_length = constraints.get('total_fence_length', float('inf'))
        if total_fences > total_fence_length:
            violations.append(
                f"Total fence length exceeded: {total_fences} > {total_fence_length}"
            )

        return (len(violations) == 0, violations)

    def _calculate_resource_marginal_contributions(
            self, solution: DeploymentSolution) -> Dict[Tuple[str, int], float]:
        total_benefit = self.calculate_total_benefit(solution)
        contributions = {}

        for gid in list(solution.cameras.keys()):
            test = DeploymentSolution(
                cameras={k: v for k, v in solution.cameras.items() if k != gid},
                camps=dict(solution.camps),
                drones=dict(solution.drones),
                rangers=dict(solution.rangers),
                fences=dict(solution.fences)
            )
            contributions[('camera', gid)] = total_benefit - self.calculate_total_benefit(test)

        for gid in list(solution.drones.keys()):
            test = DeploymentSolution(
                cameras=dict(solution.cameras),
                camps=dict(solution.camps),
                drones={k: v for k, v in solution.drones.items() if k != gid},
                rangers=dict(solution.rangers),
                fences=dict(solution.fences)
            )
            contributions[('drone', gid)] = total_benefit - self.calculate_total_benefit(test)

        for gid in list(solution.camps.keys()):
            test_rangers = dict(solution.rangers)
            if gid in test_rangers:
                del test_rangers[gid]
            test = DeploymentSolution(
                cameras=dict(solution.cameras),
                camps={k: v for k, v in solution.camps.items() if k != gid},
                drones=dict(solution.drones),
                rangers=test_rangers,
                fences=dict(solution.fences)
            )
            contributions[('camp', gid)] = total_benefit - self.calculate_total_benefit(test)

        for gid in list(solution.rangers.keys()):
            if gid in solution.camps:
                continue
            test = DeploymentSolution(
                cameras=dict(solution.cameras),
                camps=dict(solution.camps),
                drones=dict(solution.drones),
                rangers={k: v for k, v in solution.rangers.items() if k != gid},
                fences=dict(solution.fences)
            )
            contributions[('patrol', gid)] = total_benefit - self.calculate_total_benefit(test)

        return contributions

    def repair_solution(self, solution: DeploymentSolution,
                       constraints: Dict[str, any],
                       force_full_deployment: bool = True,
                       use_marginal_contribution: bool = False,
                       skip_conflict_resolution: bool = False) -> DeploymentSolution:
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

        for grid_id in list(repaired.rangers.keys()):
            if grid_id in repaired.camps:
                repaired.rangers.pop(grid_id, None)

        if not skip_conflict_resolution:
            conflict_grids = []
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
                    conflict_grids.append(grid_id)

            if conflict_grids:
                if use_marginal_contribution:
                    contributions = self._calculate_resource_marginal_contributions(repaired)
                    for grid_id in conflict_grids:
                        best_type = None
                        best_contrib = float('-inf')
                        for rtype in ['patrol', 'drone', 'camera', 'camp']:
                            contrib = contributions.get((rtype, grid_id), 0.0)
                            if contrib > best_contrib:
                                best_contrib = contrib
                                best_type = rtype
                        for rtype in ['patrol', 'drone', 'camera', 'camp']:
                            if rtype != best_type:
                                if rtype == 'patrol':
                                    repaired.rangers.pop(grid_id, None)
                                elif rtype == 'drone':
                                    repaired.drones.pop(grid_id, None)
                                elif rtype == 'camera':
                                    repaired.cameras.pop(grid_id, None)
                                elif rtype == 'camp':
                                    repaired.camps.pop(grid_id, None)
                else:
                    for grid_id in conflict_grids:
                        types_present = []
                        if repaired.rangers.get(grid_id, 0) > 0:
                            types_present.append('patrol')
                        if repaired.drones.get(grid_id, 0) > 0:
                            types_present.append('drone')
                        if repaired.cameras.get(grid_id, 0) > 0:
                            types_present.append('camera')
                        if repaired.camps.get(grid_id, 0) > 0:
                            types_present.append('camp')
                        keep_type = random.choice(types_present)
                        for rtype in types_present:
                            if rtype != keep_type:
                                if rtype == 'patrol':
                                    repaired.rangers.pop(grid_id, None)
                                elif rtype == 'drone':
                                    repaired.drones.pop(grid_id, None)
                                elif rtype == 'camera':
                                    repaired.cameras.pop(grid_id, None)
                                elif rtype == 'camp':
                                    repaired.camps.pop(grid_id, None)

        # --- Fence: Handle multi-fence edges ---
        for edge_key in list(repaired.fences.keys()):
            gid1, gid2 = edge_key

            if isinstance(gid2, int) and gid2 in range(6):
                max_fences = self.deployment_matrix['fence'].get(gid1, 0)
                if max_fences == 0:
                    del repaired.fences[edge_key]
            elif gid2 is None:
                max_fences = self.deployment_matrix['fence'].get(gid1, 0)
                if max_fences == 0:
                    del repaired.fences[edge_key]
            else:
                if (self.deployment_matrix['fence'].get(gid1, 0) != 1 or
                        self.deployment_matrix['fence'].get(gid2, 0) != 1):
                    del repaired.fences[edge_key]

        total_possible = 0
        for grid_id in self.grid_ids:
            if self.deployment_matrix['fence'].get(grid_id, 0) > 0:
                boundary_edges = self.grid_model.get_boundary_edges_for_grid(grid_id)
                total_possible += len(boundary_edges)

        total_fence_length = constraints.get('total_fence_length', float('inf'))
        total_fences = sum(repaired.fences.values())

        if total_possible > total_fence_length:
            while total_fences > total_fence_length:
                fence_counts = [(k, v) for k, v in repaired.fences.items() if v > 0]
                if not fence_counts:
                    break
                fence_counts.sort(key=lambda x: x[1], reverse=True)
                for edge_key, count in fence_counts:
                    if total_fences <= total_fence_length:
                        break
                    if repaired.fences.get(edge_key, 0) > 0:
                        repaired.fences[edge_key] -= 1
                        total_fences -= 1
                        if repaired.fences[edge_key] <= 0:
                            del repaired.fences[edge_key]

        # --- Camera: 先截单格上限，再移除超量 ---
        max_cam = constraints.get('max_cameras_per_grid', 1)
        for grid_id in list(repaired.cameras.keys()):
            if repaired.cameras[grid_id] > max_cam:
                repaired.cameras[grid_id] = max_cam

        total_cameras = sum(repaired.cameras.values())
        if total_cameras > constraints['total_cameras']:
            if use_marginal_contribution:
                contributions = self._calculate_resource_marginal_contributions(repaired)
                cam_contribs = [(gid, contributions.get(('camera', gid), 0.0))
                               for gid in list(repaired.cameras.keys())]
                cam_contribs.sort(key=lambda x: x[1])
                for gid, _ in cam_contribs:
                    if total_cameras <= constraints['total_cameras']:
                        break
                    if repaired.cameras.get(gid, 0) > 0:
                        repaired.cameras[gid] -= 1
                        total_cameras -= 1
                        if repaired.cameras[gid] <= 0:
                            del repaired.cameras[gid]
            else:
                cam_list = list(repaired.cameras.keys())
                random.shuffle(cam_list)
                for gid in cam_list:
                    if total_cameras <= constraints['total_cameras']:
                        break
                    if repaired.cameras.get(gid, 0) > 0:
                        repaired.cameras[gid] -= 1
                        total_cameras -= 1
                        if repaired.cameras[gid] <= 0:
                            del repaired.cameras[gid]

        # --- Drone: 先截单格上限，再移除超量 ---
        max_drone = constraints.get('max_drones_per_grid', 1)
        for grid_id in list(repaired.drones.keys()):
            if repaired.drones[grid_id] > max_drone:
                repaired.drones[grid_id] = max_drone

        total_drones = sum(repaired.drones.values())
        if total_drones > constraints['total_drones']:
            if use_marginal_contribution:
                contributions = self._calculate_resource_marginal_contributions(repaired)
                drone_contribs = [(gid, contributions.get(('drone', gid), 0.0))
                                 for gid in list(repaired.drones.keys())]
                drone_contribs.sort(key=lambda x: x[1])
                for gid, _ in drone_contribs:
                    if total_drones <= constraints['total_drones']:
                        break
                    if gid in repaired.drones:
                        del repaired.drones[gid]
                        total_drones -= 1
            else:
                drone_list = list(repaired.drones.keys())
                random.shuffle(drone_list)
                for gid in drone_list:
                    if total_drones <= constraints['total_drones']:
                        break
                    if gid in repaired.drones:
                        del repaired.drones[gid]
                        total_drones -= 1

        # --- Camp: 先截单格上限，再移除超量，联动清除 rangers ---
        max_camp = constraints.get('max_camps_per_grid', 1)
        for grid_id in list(repaired.camps.keys()):
            if repaired.camps[grid_id] > max_camp:
                repaired.camps[grid_id] = max_camp

        total_camps = sum(repaired.camps.values())
        if total_camps > constraints['total_camps']:
            if use_marginal_contribution:
                contributions = self._calculate_resource_marginal_contributions(repaired)
                camp_contribs = [(gid, contributions.get(('camp', gid), 0.0))
                                for gid in list(repaired.camps.keys())]
                camp_contribs.sort(key=lambda x: x[1])
                for gid, _ in camp_contribs:
                    if total_camps <= constraints['total_camps']:
                        break
                    if gid in repaired.camps:
                        del repaired.camps[gid]
                        repaired.rangers.pop(gid, None)
                        total_camps -= 1
            else:
                camp_list = list(repaired.camps.keys())
                random.shuffle(camp_list)
                for gid in camp_list:
                    if total_camps <= constraints['total_camps']:
                        break
                    if gid in repaired.camps:
                        del repaired.camps[gid]
                        repaired.rangers.pop(gid, None)
                        total_camps -= 1

        # --- Patrol: 先截单格上限，再移除超量 ---
        max_ranger = constraints.get('max_rangers_per_grid', 1)
        for grid_id in list(repaired.rangers.keys()):
            if self.deployment_matrix['patrol'].get(grid_id, 0) == 0:
                del repaired.rangers[grid_id]
            elif repaired.rangers[grid_id] > max_ranger:
                repaired.rangers[grid_id] = max_ranger

        total_rangers = sum(repaired.rangers.values())
        if total_rangers > constraints['total_patrol']:
            if use_marginal_contribution:
                contributions = self._calculate_resource_marginal_contributions(repaired)
                ranger_contribs = [(gid, contributions.get(('patrol', gid), 0.0))
                                  for gid in list(repaired.rangers.keys())]
                ranger_contribs.sort(key=lambda x: x[1])
                for gid, _ in ranger_contribs:
                    if total_rangers <= constraints['total_patrol']:
                        break
                    if gid in repaired.rangers:
                        repaired.rangers[gid] -= 1
                        total_rangers -= 1
                        if repaired.rangers[gid] <= 0:
                            del repaired.rangers[gid]
            else:
                ranger_list = list(repaired.rangers.keys())
                random.shuffle(ranger_list)
                for gid in ranger_list:
                    if total_rangers <= constraints['total_patrol']:
                        break
                    if gid in repaired.rangers:
                        repaired.rangers[gid] -= 1
                        total_rangers -= 1
                        if repaired.rangers[gid] <= 0:
                            del repaired.rangers[gid]

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

            total_cameras = sum(repaired.cameras.values())
            if total_cameras < constraints['total_cameras']:
                max_cam = constraints.get('max_cameras_per_grid', 1)

                for grid_id in list(repaired.cameras.keys()):
                    if total_cameras >= constraints['total_cameras']:
                        break
                    current = repaired.cameras.get(grid_id, 0)
                    can_add = min(max_cam - current, constraints['total_cameras'] - total_cameras)
                    if can_add > 0:
                        repaired.cameras[grid_id] = current + can_add
                        total_cameras += can_add

                if total_cameras < constraints['total_cameras']:
                    available_grids = [gid for gid in self.grid_ids
                                      if self.deployment_matrix['camera'][gid] == 1
                                      and gid not in repaired.cameras]
                    random.shuffle(available_grids)

                    for grid_id in available_grids:
                        if total_cameras >= constraints['total_cameras']:
                            break
                        can_add = min(max_cam, constraints['total_cameras'] - total_cameras)
                        if can_add > 0:
                            repaired.cameras[grid_id] = can_add
                            total_cameras += can_add

            # 补充无人机（保留已有部署，只添加缺失的）
            total_drones = sum(repaired.drones.values())
            if total_drones < constraints['total_drones']:
                available_grids = [gid for gid in self.grid_ids
                                  if self.deployment_matrix['drone'][gid] == 1
                                  and gid not in repaired.drones]
                random.shuffle(available_grids)

                for grid_id in available_grids:
                    if total_drones >= constraints['total_drones']:
                        break
                    repaired.drones[grid_id] = 1
                    total_drones += 1

            # 补充营地（保留已有部署，只添加缺失的）
            total_camps = sum(repaired.camps.values())
            if total_camps < constraints['total_camps']:
                available_grids = [gid for gid in self.grid_ids
                                  if self.deployment_matrix['camp'][gid] == 1
                                  and gid not in repaired.camps]
                random.shuffle(available_grids)

                for grid_id in available_grids:
                    if total_camps >= constraints['total_camps']:
                        break
                    repaired.camps[grid_id] = 1
                    total_camps += 1

            # 补充巡逻人员（保留已有部署，只添加缺失的）
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
