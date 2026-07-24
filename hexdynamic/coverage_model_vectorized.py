"""
coverage_model_vectorized.py

Vectorized CoverageModel implementation using NumPy.
Designed for large maps where per-fitness Python loops are too expensive.
"""

import threading
from typing import Dict, Tuple

import numpy as np

from coverage_model import CoverageModel, DeploymentSolution
from data_loader import CoverageParameters
from gpu_ops import gpu_available, hex_distances as gpu_hex_distances
from grid_model import HexGridModel


class VectorizedCoverageModel(CoverageModel):
    def __init__(
        self,
        grid_model: HexGridModel,
        coverage_params: CoverageParameters,
        deployment_matrix: Dict[str, Dict[int, int]],
        visibility_params: Dict[int, Dict[str, float]],
        coverage_effectiveness: Dict[int, Dict[str, float]] = None,
        use_gpu: bool = True,
    ):
        super().__init__(grid_model, coverage_params, deployment_matrix, visibility_params, coverage_effectiveness)

        self._use_gpu = use_gpu and gpu_available()
        self._id_to_idx: Dict[int, int] = {gid: i for i, gid in enumerate(self.grid_ids)}

        self._grid_model = grid_model
        self._qs = np.array([g.q for g in grid_model.grids], dtype=np.int32)
        self._rs = np.array([g.r for g in grid_model.grids], dtype=np.int32)
        self._qr = self._qs + self._rs

        if grid_model.has_distance_matrix():
            self._dist = grid_model.distance_matrix
            self._use_precomputed = True
        else:
            self._dist = None
            self._use_precomputed = False

        self._risk_vec = np.array([grid_model.get_grid_risk(gid) for gid in self.grid_ids], dtype=np.float64)
        self._total_risk = float(self._risk_vec.sum())

        eff = coverage_effectiveness or {}
        self._eff_patrol = np.array([eff.get(gid, {}).get("patrol", 1.0) for gid in self.grid_ids], dtype=np.float64)
        self._eff_drone = np.array([eff.get(gid, {}).get("drone", 1.0) for gid in self.grid_ids], dtype=np.float64)
        self._eff_camera = np.array([eff.get(gid, {}).get("camera", 1.0) for gid in self.grid_ids], dtype=np.float64)
        self._eff_fence = np.array([eff.get(gid, {}).get("fence", 1.0) for gid in self.grid_ids], dtype=np.float64)

        self._vis_drone = np.array([visibility_params[gid]["drone"] for gid in self.grid_ids], dtype=np.float64)
        self._vis_camera = np.array([visibility_params[gid]["camera"] for gid in self.grid_ids], dtype=np.float64)

        self._temporal_vec = np.array(
            [grid_model.get_grid_temporal_factor(gid) for gid in self.grid_ids], dtype=np.float64
        )
        self._risk_weighted_vec = self._risk_vec * self._temporal_vec
        self._total_risk_weighted = float(self._risk_weighted_vec.sum())

        # Precompute effective radii used in every evaluation.
        self._eff_radius_drone = self.params.drone_radius * self._vis_drone
        self._eff_radius_camera = self.params.camera_radius * self._vis_camera
        self._eff_radius_drone_safe = np.where(self._eff_radius_drone > 0, self._eff_radius_drone, 1.0)
        self._eff_radius_camera_safe = np.where(self._eff_radius_camera > 0, self._eff_radius_camera, 1.0)
        self._reach_drone = self._eff_radius_drone * 2.0
        self._reach_camera = self._eff_radius_camera * 2.0

        self._tl = threading.local()

        # Cache for coverage arrays to avoid redundant computation.
        self._cached_solution_id = None
        self._cached_coverage = None

    def __getstate__(self):
        state = self.__dict__.copy()
        state.pop("_tl", None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._tl = threading.local()

    def _compute_dists_to(self, target_indices: np.ndarray) -> np.ndarray:
        if self._use_gpu:
            return gpu_hex_distances(self._qs, self._rs, self._qr, target_indices)

        if self._use_precomputed:
            return self._dist[:, target_indices]

        k = len(target_indices)
        n = len(self._qs)

        tl = self._tl
        if not hasattr(tl, "buffers"):
            tl.buffers = {}
        cache_key = k
        if cache_key in tl.buffers:
            out = tl.buffers[cache_key]
        else:
            out = np.empty((n, k), dtype=np.float32)
            tl.buffers[cache_key] = out

        t_qs = self._qs[target_indices]
        t_rs = self._rs[target_indices]
        t_qr = self._qr[target_indices]

        chunk = 2048
        for start in range(0, n, chunk):
            end = min(start + chunk, n)
            dq = np.abs(self._qs[start:end, None] - t_qs[None, :])
            dr = np.abs(self._rs[start:end, None] - t_rs[None, :])
            ds = np.abs(self._qr[start:end, None] - t_qr[None, :])
            out[start:end, :] = ((dq + dr + ds) >> 1)
        return out

    def _get_tl_buffer(self, name: str, shape: Tuple[int, ...], dtype=np.float64) -> np.ndarray:
        tl = self._tl
        if not hasattr(tl, "named_buffers"):
            tl.named_buffers = {}
        buf = tl.named_buffers.get(name)
        if buf is None or buf.shape != shape or buf.dtype != dtype:
            buf = np.empty(shape, dtype=dtype)
            tl.named_buffers[name] = buf
        return buf

    def _ranger_vec(self, solution: DeploymentSolution) -> np.ndarray:
        vec = self._get_tl_buffer("ranger_vec", (len(self.grid_ids),), dtype=np.float64)
        vec.fill(0.0)
        id_to_idx = self._id_to_idx
        for gid, cnt in solution.rangers.items():
            if cnt > 0:
                idx = id_to_idx.get(gid)
                if idx is not None:
                    vec[idx] += cnt
        return vec

    def _camera_vec(self, solution: DeploymentSolution) -> np.ndarray:
        vec = self._get_tl_buffer("camera_vec", (len(self.grid_ids),), dtype=np.float64)
        vec.fill(0.0)
        id_to_idx = self._id_to_idx
        for gid, cnt in solution.cameras.items():
            if cnt > 0:
                idx = id_to_idx.get(gid)
                if idx is not None:
                    vec[idx] += cnt
        return vec

    def _resource_indices(self, resource_dict: Dict[int, int]) -> np.ndarray:
        id_to_idx = self._id_to_idx
        indices = [id_to_idx[gid] for gid, v in resource_dict.items() if v > 0 and gid in id_to_idx]
        if not indices:
            return np.empty(0, dtype=np.int64)
        return np.asarray(indices, dtype=np.int64)

    def _fence_vec(self, solution: DeploymentSolution) -> np.ndarray:
        fence_counts = self._get_tl_buffer("fence_counts", (len(self.grid_ids),), dtype=np.float64)
        fence_counts.fill(0.0)
        id_to_idx = self._id_to_idx

        for (gid1, gid2), v in solution.fences.items():
            if v <= 0:
                continue
            if isinstance(gid2, int) and gid2 in range(6):
                i = id_to_idx.get(gid1)
                if i is not None:
                    fence_counts[i] += v
            else:
                i = id_to_idx.get(gid1)
                j = id_to_idx.get(gid2)
                if i is not None:
                    fence_counts[i] += v
                if j is not None:
                    fence_counts[j] += v
        return fence_counts

    def calculate_patrol_coverage(self, solution: DeploymentSolution) -> Dict[int, float]:
        ranger_vec = self._ranger_vec(solution)
        active = np.where(ranger_vec > 0)[0]
        if len(active) == 0:
            return {gid: 0.0 for gid in self.grid_ids}

        dists = self._compute_dists_to(active)
        weights = ranger_vec[active]
        intensity = (np.exp(-dists / self.params.patrol_radius) * weights).sum(axis=1)
        coverage = (1.0 - np.exp(-intensity)) * self._eff_patrol
        return {gid: float(coverage[i]) for i, gid in enumerate(self.grid_ids)}

    def calculate_drone_coverage(self, solution: DeploymentSolution) -> Dict[int, float]:
        drone_idx = self._resource_indices(solution.drones)
        if len(drone_idx) == 0:
            return {gid: 0.0 for gid in self.grid_ids}

        dists = self._compute_dists_to(drone_idx)
        eff_r = self._eff_radius_drone_safe[:, None]
        within = dists <= self._reach_drone[:, None]
        coverage = (np.exp(-dists / eff_r) * within).sum(axis=1)
        coverage = np.minimum(1.0, coverage) * self._eff_drone
        return {gid: float(coverage[i]) for i, gid in enumerate(self.grid_ids)}

    def calculate_camera_coverage(self, solution: DeploymentSolution) -> Dict[int, float]:
        cam_vec = self._camera_vec(solution)
        active = np.where(cam_vec > 0)[0]
        if len(active) == 0:
            return {gid: 0.0 for gid in self.grid_ids}

        dists = self._compute_dists_to(active)
        weights = cam_vec[active]
        eff_r = self._eff_radius_camera_safe[:, None]
        within = dists <= self._reach_camera[:, None]
        coverage = (np.exp(-dists / eff_r) * within * weights).sum(axis=1)
        coverage = np.minimum(1.0, coverage) * self._eff_camera
        return {gid: float(coverage[i]) for i, gid in enumerate(self.grid_ids)}

    def calculate_fence_protection(self, solution: DeploymentSolution) -> Dict[int, float]:
        fence_counts = self._fence_vec(solution)
        protection = np.minimum(1.0, fence_counts * self.params.fence_protection) * self._eff_fence
        return {gid: float(protection[i]) for i, gid in enumerate(self.grid_ids)}

    def _combine_effect(self, pc: np.ndarray, dc: np.ndarray, cc: np.ndarray, fp: np.ndarray) -> np.ndarray:
        e = self._get_tl_buffer("E", (len(self.grid_ids),), dtype=np.float64)
        np.multiply(pc, self.params.wp, out=e)
        e += self.params.wd * dc
        e += self.params.wc * cc
        e += self.params.wf * fp

        denom_pd = 1.0 + pc + dc
        denom_pc = 1.0 + pc + cc
        e += self.params.alpha_pd * (pc * dc) / denom_pd
        e += self.params.alpha_pc * (pc * cc) / denom_pc
        return e

    def calculate_total_benefit(self, solution: DeploymentSolution) -> float:
        pc, dc, cc, fp = self._get_cached_coverage_arrays(solution)
        e = self._combine_effect(pc, dc, cc, fp)

        factor = self._get_tl_buffer("benefit_factor", (len(self.grid_ids),), dtype=np.float64)
        np.negative(e, out=factor)
        np.exp(factor, out=factor)
        factor *= -1.0
        factor += 1.0
        total = float(np.dot(self._risk_weighted_vec, factor))
        if self._total_risk_weighted > 0:
            total /= self._total_risk_weighted
        return total

    def calculate_protection_benefit(self, solution: DeploymentSolution) -> Dict[int, float]:
        pc, dc, cc, fp = self._get_cached_coverage_arrays(solution)
        e = self._combine_effect(pc, dc, cc, fp)
        benefit = self._risk_weighted_vec * (1.0 - np.exp(-e))
        return {gid: float(benefit[i]) for i, gid in enumerate(self.grid_ids)}

    def calculate_time_aware_total_benefit(self, solution: DeploymentSolution) -> float:
        pc, dc, cc, fp = self._get_cached_coverage_arrays(solution)
        e = self._combine_effect(pc, dc, cc, fp)

        factor = self._get_tl_buffer("benefit_factor_time", (len(self.grid_ids),), dtype=np.float64)
        np.negative(e, out=factor)
        np.exp(factor, out=factor)
        factor *= -1.0
        factor += 1.0
        total = float(np.dot(self._risk_weighted_vec, factor))
        if self._total_risk_weighted > 0:
            total /= self._total_risk_weighted
        return total

    def _get_cached_coverage_arrays(self, solution: DeploymentSolution):
        sid = id(solution)
        if sid == self._cached_solution_id and self._cached_coverage is not None:
            return self._cached_coverage
        result = self._calculate_coverage_arrays(solution)
        self._cached_solution_id = sid
        self._cached_coverage = result
        return result

    def _calculate_coverage_arrays(self, solution: DeploymentSolution):
        n_grids = len(self.grid_ids)

        ranger_vec = self._ranger_vec(solution)
        active_p = np.where(ranger_vec > 0)[0]
        if len(active_p) > 0:
            dists_p = self._compute_dists_to(active_p)
            weights_p = ranger_vec[active_p]
            intensity = (np.exp(-dists_p / self.params.patrol_radius) * weights_p).sum(axis=1)
            pc = (1.0 - np.exp(-intensity)) * self._eff_patrol
        else:
            pc = self._get_tl_buffer("pc_zeros", (n_grids,), dtype=np.float64)
            pc.fill(0.0)

        drone_idx = self._resource_indices(solution.drones)
        if len(drone_idx) > 0:
            dists_d = self._compute_dists_to(drone_idx)
            eff_r_d = self._eff_radius_drone_safe[:, None]
            within_d = dists_d <= self._reach_drone[:, None]
            dc = (np.exp(-dists_d / eff_r_d) * within_d).sum(axis=1)
            dc = np.minimum(1.0, dc) * self._eff_drone
        else:
            dc = self._get_tl_buffer("dc_zeros", (n_grids,), dtype=np.float64)
            dc.fill(0.0)

        cam_vec = self._camera_vec(solution)
        active_c = np.where(cam_vec > 0)[0]
        if len(active_c) > 0:
            dists_c = self._compute_dists_to(active_c)
            weights_c = cam_vec[active_c]
            eff_r_c = self._eff_radius_camera_safe[:, None]
            within_c = dists_c <= self._reach_camera[:, None]
            cc = (np.exp(-dists_c / eff_r_c) * within_c * weights_c).sum(axis=1)
            cc = np.minimum(1.0, cc) * self._eff_camera
        else:
            cc = self._get_tl_buffer("cc_zeros", (n_grids,), dtype=np.float64)
            cc.fill(0.0)

        fence_counts = self._fence_vec(solution)
        fp = np.minimum(1.0, fence_counts * self.params.fence_protection) * self._eff_fence
        return pc, dc, cc, fp
