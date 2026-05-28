import sys
import os
import unittest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grid_model import HexGridModel
from data_loader import GridData, CoverageParameters
from coverage_model import CoverageModel, DeploymentSolution
from coverage_model_vectorized import VectorizedCoverageModel


def _make_grids(n=20):
    return [
        GridData(grid_id=i, q=i % 5, r=i // 5, terrain_type="SparseGrass", risk=0.3 + 0.02 * i)
        for i in range(n)
    ]


def _make_models(grids, use_gpu=False):
    grid_model = HexGridModel(grids)
    params = CoverageParameters()
    dm = {
        'camera': {g.grid_id: 1 for g in grids},
        'drone': {g.grid_id: 1 for g in grids},
        'camp': {g.grid_id: 1 for g in grids},
        'patrol': {g.grid_id: 1 for g in grids},
        'fence': {g.grid_id: 6 for g in grids},
    }
    vp = {g.grid_id: {'drone': 1.0, 'camera': 1.0} for g in grids}
    loop_model = CoverageModel(grid_model, params, dm, vp)
    vec_model = VectorizedCoverageModel(grid_model, params, dm, vp, use_gpu=use_gpu)
    return loop_model, vec_model


class TestVectorizedCoverageModelInit(unittest.TestCase):
    def test_creates_successfully(self):
        grids = _make_grids(10)
        _, vec = _make_models(grids)
        self.assertIsInstance(vec, VectorizedCoverageModel)
        self.assertIsInstance(vec, CoverageModel)

    def test_id_to_idx_mapping(self):
        grids = _make_grids(10)
        _, vec = _make_models(grids)
        self.assertEqual(vec._id_to_idx[0], 0)
        self.assertEqual(vec._id_to_idx[9], 9)

    def test_risk_vec(self):
        grids = _make_grids(5)
        _, vec = _make_models(grids)
        self.assertEqual(vec._risk_vec.shape, (5,))
        self.assertAlmostEqual(vec._risk_vec[0], 0.3, places=5)

    def test_total_risk(self):
        grids = _make_grids(5)
        _, vec = _make_models(grids)
        expected = sum(g.risk for g in grids)
        self.assertAlmostEqual(vec._total_risk, expected, places=5)


class TestVectorizedVsLoopConsistency(unittest.TestCase):
    def setUp(self):
        self.grids = _make_grids(20)
        self.loop_model, self.vec_model = _make_models(self.grids)

    def _random_solution(self):
        import random
        random.seed(42)
        n = len(self.grids)
        cameras = {i: 1 for i in range(0, n, 5)}
        camps = {i: 1 for i in range(1, n, 7)}
        drones = {i: 1 for i in range(2, n, 6)}
        rangers = {i: random.randint(1, 3) for i in range(0, n, 4)}
        fences = {(i, 0): 1 for i in range(0, n, 8)}
        return DeploymentSolution(cameras=cameras, camps=camps, drones=drones,
                                  rangers=rangers, fences=fences)

    def test_patrol_coverage_match(self):
        s = self._random_solution()
        loop = self.loop_model.calculate_patrol_coverage(s)
        vec = self.vec_model.calculate_patrol_coverage(s)
        for gid in self.vec_model.grid_ids:
            self.assertAlmostEqual(loop[gid], vec[gid], places=5,
                                   msg=f"Patrol mismatch at grid {gid}")

    def test_drone_coverage_match(self):
        s = self._random_solution()
        loop = self.loop_model.calculate_drone_coverage(s)
        vec = self.vec_model.calculate_drone_coverage(s)
        for gid in self.vec_model.grid_ids:
            self.assertAlmostEqual(loop[gid], vec[gid], places=5,
                                   msg=f"Drone mismatch at grid {gid}")

    def test_camera_coverage_match(self):
        s = self._random_solution()
        loop = self.loop_model.calculate_camera_coverage(s)
        vec = self.vec_model.calculate_camera_coverage(s)
        for gid in self.vec_model.grid_ids:
            self.assertAlmostEqual(loop[gid], vec[gid], places=5,
                                   msg=f"Camera mismatch at grid {gid}")

    def test_fence_protection_match(self):
        s = self._random_solution()
        loop = self.loop_model.calculate_fence_protection(s)
        vec = self.vec_model.calculate_fence_protection(s)
        for gid in self.vec_model.grid_ids:
            self.assertAlmostEqual(loop[gid], vec[gid], places=5,
                                   msg=f"Fence mismatch at grid {gid}")

    def test_total_benefit_match(self):
        s = self._random_solution()
        loop = self.loop_model.calculate_total_benefit(s)
        vec = self.vec_model.calculate_total_benefit(s)
        self.assertAlmostEqual(loop, vec, places=5)

    def test_protection_benefit_match(self):
        s = self._random_solution()
        loop = self.loop_model.calculate_protection_benefit(s)
        vec = self.vec_model.calculate_protection_benefit(s)
        for gid in self.vec_model.grid_ids:
            self.assertAlmostEqual(loop[gid], vec[gid], places=5,
                                   msg=f"Benefit mismatch at grid {gid}")

    def test_time_aware_benefit_match(self):
        s = self._random_solution()
        loop = self.loop_model.calculate_time_aware_total_benefit(s)
        vec = self.vec_model.calculate_time_aware_total_benefit(s)
        self.assertAlmostEqual(loop, vec, places=5)


class TestVectorizedEdgeCases(unittest.TestCase):
    def test_empty_solution(self):
        grids = _make_grids(10)
        _, vec = _make_models(grids)
        s = DeploymentSolution(cameras={}, camps={}, drones={}, rangers={}, fences={})
        total = vec.calculate_total_benefit(s)
        self.assertGreaterEqual(total, 0.0)

    def test_single_grid(self):
        grids = [GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.5)]
        _, vec = _make_models(grids)
        s = DeploymentSolution(cameras={0: 1}, camps={}, drones={0: 1}, rangers={0: 3}, fences={})
        total = vec.calculate_total_benefit(s)
        self.assertGreater(total, 0.0)

    def test_all_grids_deployed(self):
        grids = _make_grids(10)
        _, vec = _make_models(grids)
        s = DeploymentSolution(
            cameras={i: 1 for i in range(10)},
            camps={i: 1 for i in range(0, 10, 3)},
            drones={i: 1 for i in range(0, 10, 2)},
            rangers={i: 2 for i in range(0, 10, 4)},
            fences={}
        )
        total = vec.calculate_total_benefit(s)
        self.assertGreater(total, 0.0)


class TestVectorizedFenceFormats(unittest.TestCase):
    def test_boundary_edge_format(self):
        grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.5),
            GridData(grid_id=1, q=1, r=0, terrain_type="SparseGrass", risk=0.3),
        ]
        _, vec = _make_models(grids)
        s = DeploymentSolution(cameras={}, camps={}, drones={}, rangers={},
                               fences={(0, 0): 1, (0, 1): 1})
        fp = vec.calculate_fence_protection(s)
        self.assertGreater(fp[0], 0.0)

    def test_internal_edge_format(self):
        grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.5),
            GridData(grid_id=1, q=1, r=0, terrain_type="SparseGrass", risk=0.3),
        ]
        _, vec = _make_models(grids)
        s = DeploymentSolution(cameras={}, camps={}, drones={}, rangers={},
                               fences={(0, 1): 1})
        fp = vec.calculate_fence_protection(s)
        # Vectorized model should return valid non-negative values
        self.assertGreaterEqual(fp[0], 0.0)
        self.assertGreaterEqual(fp[1], 0.0)
        self.assertLessEqual(fp[0], 1.0)
        self.assertLessEqual(fp[1], 1.0)


class TestVectorizedPickling(unittest.TestCase):
    def test_getstate_setstate(self):
        grids = _make_grids(10)
        _, vec = _make_models(grids)
        state = vec.__getstate__()
        self.assertNotIn('_tl', state)
        vec2 = object.__new__(VectorizedCoverageModel)
        vec2.__setstate__(state)
        self.assertIn('_tl', vec2.__dict__)


if __name__ == '__main__':
    unittest.main()
