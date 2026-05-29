"""
coverage_model_vectorized.py

CoverageModel 的向量化实现，用 NumPy 矩阵运算替代 Python 循环。
适合网格数量较大（千级以上）的场景，可显著降低 evaluate_fitness 的耗时。

与原始 CoverageModel 接口完全兼容，通过 protection_pipeline.py 的
--vectorized 参数启用。

内存策略：
  - 优先使用预计算的 float32 距离矩阵（查表 O(1)），适合 N ≤ ~27K
  - 若预计算失败（OOM 或超阈值），自动回退到按需距离计算
"""

import numpy as np
import threading
from typing import Dict, List, Tuple

from grid_model import HexGridModel
from data_loader import CoverageParameters
from coverage_model import CoverageModel, DeploymentSolution
from gpu_ops import gpu_available, hex_distances as gpu_hex_distances


class VectorizedCoverageModel(CoverageModel):
    """
    向量化覆盖模型。

    初始化时预计算以下向量，避免在每次 evaluate_fitness 时重复构建：
      - risk_vec    : (N,)   各网格风险值
      - deploy_*    : (N,)   各资源的部署可行性掩码
      - visibility_drone/camera : (N,) 可见度向量
      - _dist       : (N,N)  float32 距离矩阵（若内存允许），否则按需计算
    """

    def __init__(self, grid_model: HexGridModel, coverage_params: CoverageParameters,
                 deployment_matrix: Dict[str, Dict[int, int]],
                 visibility_params: Dict[int, Dict[str, float]],
                 coverage_effectiveness: Dict[int, Dict[str, float]] = None,
                 use_gpu: bool = True):
        super().__init__(grid_model, coverage_params, deployment_matrix, visibility_params, coverage_effectiveness)

        self._use_gpu = use_gpu and gpu_available()

        self._id_to_idx: Dict[int, int] = {gid: i for i, gid in enumerate(self.grid_ids)}
        N = len(self.grid_ids)

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

        self._risk_vec = np.array(
            [grid_model.get_grid_risk(gid) for gid in self.grid_ids], dtype=np.float64
        )
        self._total_risk = float(self._risk_vec.sum())

        self._deploy_patrol = np.array(
            [deployment_matrix['patrol'][gid] for gid in self.grid_ids], dtype=np.float64
        )
        self._deploy_drone = np.array(
            [deployment_matrix['drone'][gid] for gid in self.grid_ids], dtype=np.float64
        )
        self._deploy_camera = np.array(
            [deployment_matrix['camera'][gid] for gid in self.grid_ids], dtype=np.float64
        )
        self._deploy_fence = np.array(
            [deployment_matrix['fence'][gid] for gid in self.grid_ids], dtype=np.float64
        )

        eff = coverage_effectiveness or {}
        self._eff_patrol = np.array(
            [eff.get(gid, {}).get('patrol', 1.0) for gid in self.grid_ids], dtype=np.float64
        )
        self._eff_drone = np.array(
            [eff.get(gid, {}).get('drone', 1.0) for gid in self.grid_ids], dtype=np.float64
        )
        self._eff_camera = np.array(
            [eff.get(gid, {}).get('camera', 1.0) for gid in self.grid_ids], dtype=np.float64
        )
        self._eff_fence = np.array(
            [eff.get(gid, {}).get('fence', 1.0) for gid in self.grid_ids], dtype=np.float64
        )

        self._vis_drone = np.array(
            [visibility_params[gid]['drone'] for gid in self.grid_ids], dtype=np.float64
        )
        self._vis_camera = np.array(
            [visibility_params[gid]['camera'] for gid in self.grid_ids], dtype=np.float64
        )

        self._temporal_vec = np.array(
            [grid_model.get_grid_temporal_factor(gid) for gid in self.grid_ids], dtype=np.float64
        )

        self._tl = threading.local()
        
        # Cache for coverage arrays to avoid redundant computation
        self._cached_solution_id = None
        self._cached_coverage = None

    def __getstate__(self):
        """Strip unpicklable _tl (threading.local) before serialization."""
        state = self.__dict__.copy()
        state.pop('_tl', None)
        return state

    def __setstate__(self, state):
        """Reinitialize _tl after deserialization (fresh per-process)."""
        self.__dict__.update(state)
        self._tl = threading.local()

    def _compute_dists_to(self, target_indices: np.ndarray) -> np.ndarray:
        if self._use_gpu:
            return gpu_hex_distances(self._qs, self._rs, self._qr, target_indices)

        if self._use_precomputed:
            return self._dist[:, target_indices]

        K = len(target_indices)
        N = len(self._qs)

        tl = self._tl
        if not hasattr(tl, 'buffers'):
            tl.buffers = {}
        cache_key = K
        if cache_key in tl.buffers:
            out = tl.buffers[cache_key]
        else:
            out = np.empty((N, K), dtype=np.float32)
            tl.buffers[cache_key] = out

        t_qs = self._qs[target_indices]
        t_rs = self._rs[target_indices]
        t_qr = self._qr[target_indices]

        chunk = 2048
        for start in range(0, N, chunk):
            end = min(start + chunk, N)
            dq = np.abs(self._qs[start:end, None] - t_qs[None, :])
            dr = np.abs(self._rs[start:end, None] - t_rs[None, :])
            ds = np.abs(self._qr[start:end, None] - t_qr[None, :])
            out[start:end, :] = ((dq + dr + ds) >> 1)
        return out

    # ------------------------------------------------------------------
    # 内部辅助：把解转换为 NumPy 索引数组
    # ------------------------------------------------------------------

    def _ranger_vec(self, solution: DeploymentSolution) -> np.ndarray:
        """返回 (N,) 巡逻强度向量（含营地人员 + 直接部署人员）"""
        vec = np.zeros(len(self.grid_ids), dtype=np.float64)
        for gid, cnt in solution.rangers.items():
            if cnt > 0:
                idx = self._id_to_idx.get(gid)
                if idx is not None:
                    vec[idx] += cnt
        return vec

    def _resource_indices(self, resource_dict: Dict[int, int]) -> np.ndarray:
        """返回部署了该资源的格子在 grid_ids 中的索引数组"""
        return np.array(
            [self._id_to_idx[gid] for gid, v in resource_dict.items()
             if v > 0 and gid in self._id_to_idx],
            dtype=np.int64
        )

    def _fence_vec(self, solution: DeploymentSolution) -> np.ndarray:
        """返回 (N,) 围栏段数向量：fence_vec[i] = 格子 i 相邻的围栏段数
        
        支持两种 fence 格式：
        - 内部边：(grid_id1, grid_id2) - 两个网格之间的边
        - 边界边：(grid_id, direction) - 单个网格的特定方向（0-5）
        """
        N = len(self.grid_ids)
        fence_counts = np.zeros(N, dtype=np.float64)
        
        for (gid1, gid2), v in solution.fences.items():
            if v <= 0:
                continue
                
            # 检查是否为边界边格式：(grid_id, direction)，其中 direction 是 0-5 的整数
            if isinstance(gid2, int) and gid2 in range(6):
                # 边界边格式：只给 gid1 对应的网格增加 fence count
                i = self._id_to_idx.get(gid1)
                if i is not None:
                    fence_counts[i] += v
            else:
                # 内部边格式：给两个网格都增加 fence count
                i = self._id_to_idx.get(gid1)
                j = self._id_to_idx.get(gid2)
                if i is not None:
                    fence_counts[i] += v
                if j is not None:
                    fence_counts[j] += v
        
        return fence_counts

    # ------------------------------------------------------------------
    # 向量化覆盖计算
    # ------------------------------------------------------------------

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

        eff_radius = self.params.drone_radius * self._vis_drone
        dists = self._compute_dists_to(drone_idx)
        eff_r = eff_radius[:, None]
        within = dists <= eff_r * 2
        coverage = (np.exp(-dists / np.where(eff_r > 0, eff_r, 1.0)) * within).sum(axis=1)
        coverage = np.minimum(1.0, coverage) * self._eff_drone

        return {gid: float(coverage[i]) for i, gid in enumerate(self.grid_ids)}

    def calculate_camera_coverage(self, solution: DeploymentSolution) -> Dict[int, float]:
        cam_vec = np.zeros(len(self.grid_ids), dtype=np.float64)
        for gid, cnt in solution.cameras.items():
            if cnt > 0:
                idx = self._id_to_idx.get(gid)
                if idx is not None:
                    cam_vec[idx] = cnt
        active = np.where(cam_vec > 0)[0]

        if len(active) == 0:
            return {gid: 0.0 for gid in self.grid_ids}

        eff_radius = self.params.camera_radius * self._vis_camera
        dists = self._compute_dists_to(active)
        weights = cam_vec[active]
        eff_r = eff_radius[:, None]
        within = dists <= eff_r * 2
        coverage = (np.exp(-dists / np.where(eff_r > 0, eff_r, 1.0)) * within * weights).sum(axis=1)
        coverage = np.minimum(1.0, coverage) * self._eff_camera

        return {gid: float(coverage[i]) for i, gid in enumerate(self.grid_ids)}

    def calculate_fence_protection(self, solution: DeploymentSolution) -> Dict[int, float]:
        fence_counts = self._fence_vec(solution)
        protection = np.minimum(1.0, fence_counts * self.params.fence_protection) * self._eff_fence

        return {gid: float(protection[i]) for i, gid in enumerate(self.grid_ids)}

    def calculate_total_benefit(self, solution: DeploymentSolution) -> float:
        pc, dc, cc, fp = self._get_cached_coverage_arrays(solution)

        E = (self.params.wp * pc + self.params.wd * dc +
             self.params.wc * cc + self.params.wf * fp)

        denom_pd = 1.0 + pc + dc
        synergy_pd = self.params.alpha_pd * (pc * dc) / denom_pd

        denom_pc = 1.0 + pc + cc
        synergy_pc = self.params.alpha_pc * (pc * cc) / denom_pc

        E = E + synergy_pd + synergy_pc

        benefit = self._risk_vec * (1.0 - np.exp(-E))
        total = float(benefit.sum())

        if self._total_risk > 0:
            total /= self._total_risk

        return total

    def calculate_protection_benefit(self, solution: DeploymentSolution) -> Dict[int, float]:
        pc, dc, cc, fp = self._get_cached_coverage_arrays(solution)

        E = (self.params.wp * pc + self.params.wd * dc +
             self.params.wc * cc + self.params.wf * fp)

        denom_pd = 1.0 + pc + dc
        synergy_pd = self.params.alpha_pd * (pc * dc) / denom_pd

        denom_pc = 1.0 + pc + cc
        synergy_pc = self.params.alpha_pc * (pc * cc) / denom_pc

        E = E + synergy_pd + synergy_pc

        benefit = self._risk_vec * (1.0 - np.exp(-E))

        return {gid: float(benefit[i]) for i, gid in enumerate(self.grid_ids)}

    def calculate_time_aware_total_benefit(self, solution: DeploymentSolution) -> float:
        pc, dc, cc, fp = self._calculate_coverage_arrays(solution)

        E = (self.params.wp * pc + self.params.wd * dc +
             self.params.wc * cc + self.params.wf * fp)

        denom_pd = 1.0 + pc + dc
        synergy_pd = self.params.alpha_pd * (pc * dc) / denom_pd

        denom_pc = 1.0 + pc + cc
        synergy_pc = self.params.alpha_pc * (pc * cc) / denom_pc

        E = E + synergy_pd + synergy_pc

        temporal_vec = self._temporal_vec
        risk_weighted = self._risk_vec * temporal_vec
        total_risk_weighted = float(risk_weighted.sum())

        benefit = risk_weighted * (1.0 - np.exp(-E))
        total = float(benefit.sum())

        if total_risk_weighted > 0:
            total /= total_risk_weighted

        return total

    def _get_cached_coverage_arrays(self, solution: DeploymentSolution) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Get coverage arrays with caching to avoid redundant computation."""
        sid = id(solution)
        if sid == self._cached_solution_id and self._cached_coverage is not None:
            return self._cached_coverage
        result = self._calculate_coverage_arrays(solution)
        self._cached_solution_id = sid
        self._cached_coverage = result
        return result

    def _calculate_coverage_arrays(self, solution: DeploymentSolution) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        N = len(self.grid_ids)

        ranger_vec = self._ranger_vec(solution)
        active_p = np.where(ranger_vec > 0)[0]
        if len(active_p) > 0:
            dists_p = self._compute_dists_to(active_p)
            weights_p = ranger_vec[active_p]
            intensity = (np.exp(-dists_p / self.params.patrol_radius) * weights_p).sum(axis=1)
            pc = (1.0 - np.exp(-intensity)) * self._eff_patrol
        else:
            pc = np.zeros(N, dtype=np.float64)

        drone_idx = self._resource_indices(solution.drones)
        if len(drone_idx) > 0:
            eff_radius_d = self.params.drone_radius * self._vis_drone
            dists_d = self._compute_dists_to(drone_idx)
            eff_r_d = eff_radius_d[:, None]
            within_d = dists_d <= eff_r_d * 2
            dc = (np.exp(-dists_d / np.where(eff_r_d > 0, eff_r_d, 1.0)) * within_d).sum(axis=1)
            dc = np.minimum(1.0, dc) * self._eff_drone
        else:
            dc = np.zeros(N, dtype=np.float64)

        cam_vec = np.zeros(N, dtype=np.float64)
        for gid, cnt in solution.cameras.items():
            if cnt > 0:
                idx = self._id_to_idx.get(gid)
                if idx is not None:
                    cam_vec[idx] = cnt
        active_c = np.where(cam_vec > 0)[0]
        if len(active_c) > 0:
            eff_radius_c = self.params.camera_radius * self._vis_camera
            dists_c = self._compute_dists_to(active_c)
            weights_c = cam_vec[active_c]
            eff_r_c = eff_radius_c[:, None]
            within_c = dists_c <= eff_r_c * 2
            cc = (np.exp(-dists_c / np.where(eff_r_c > 0, eff_r_c, 1.0)) * within_c * weights_c).sum(axis=1)
            cc = np.minimum(1.0, cc) * self._eff_camera
        else:
            cc = np.zeros(N, dtype=np.float64)

        fence_counts = self._fence_vec(solution)
        fp = np.minimum(1.0, fence_counts * self.params.fence_protection) * self._eff_fence

        return pc, dc, cc, fp
