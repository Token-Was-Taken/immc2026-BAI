import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grid_model import HexGridModel
from data_loader import GridData, CoverageParameters
from coverage_model import CoverageModel, DeploymentSolution


class TestDeploymentSolution(unittest.TestCase):
    def test_empty_solution(self):
        s = DeploymentSolution(cameras={}, camps={}, drones={}, rangers={}, fences={})
        self.assertEqual(s.cameras, {})
        self.assertEqual(s.camps, {})
        self.assertEqual(s.drones, {})
        self.assertEqual(s.rangers, {})
        self.assertEqual(s.fences, {})

    def test_solution_with_data(self):
        s = DeploymentSolution(
            cameras={0: 1, 1: 2},
            camps={2: 1},
            drones={3: 1},
            rangers={4: 3},
            fences={(0, 1): 1}
        )
        self.assertEqual(s.cameras[0], 1)
        self.assertEqual(s.cameras[1], 2)
        self.assertEqual(s.camps[2], 1)
        self.assertEqual(s.drones[3], 1)
        self.assertEqual(s.rangers[4], 3)
        self.assertEqual(s.fences[(0, 1)], 1)


class TestCoverageModel(unittest.TestCase):
    def setUp(self):
        self.grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.5),
            GridData(grid_id=1, q=1, r=0, terrain_type="SparseGrass", risk=0.3),
            GridData(grid_id=2, q=0, r=1, terrain_type="DenseGrass", risk=0.7),
            GridData(grid_id=3, q=1, r=1, terrain_type="WaterHole", risk=0.9),
        ]
        self.grid_model = HexGridModel(self.grids)

        self.coverage_params = CoverageParameters(
            patrol_radius=5.0,
            drone_radius=8.0,
            camera_radius=3.0,
            fence_protection=0.5,
            wp=0.3, wd=0.3, wc=0.2, wf=0.2,
        )

        deployment_matrix = {
            'camera': {0: 1, 1: 1, 2: 1, 3: 1},
            'drone': {0: 1, 1: 1, 2: 1, 3: 1},
            'camp': {0: 1, 1: 1, 2: 1, 3: 1},
            'patrol': {0: 1, 1: 1, 2: 1, 3: 1},
            'fence': {0: 6, 1: 6, 2: 6, 3: 6},
        }

        visibility_params = {
            0: {'drone': 1.0, 'camera': 1.0},
            1: {'drone': 1.0, 'camera': 1.0},
            2: {'drone': 1.0, 'camera': 1.0},
            3: {'drone': 1.0, 'camera': 1.0},
        }

        self.model = CoverageModel(
            grid_model=self.grid_model,
            coverage_params=self.coverage_params,
            deployment_matrix=deployment_matrix,
            visibility_params=visibility_params,
        )

    def test_calculate_total_benefit_empty(self):
        s = DeploymentSolution(cameras={}, camps={}, drones={}, rangers={}, fences={})
        benefit = self.model.calculate_total_benefit(s)
        self.assertGreaterEqual(benefit, 0.0)
        self.assertLessEqual(benefit, 1.0)

    def test_calculate_total_benefit_full(self):
        s = DeploymentSolution(
            cameras={0: 1, 1: 1, 2: 1, 3: 1},
            drones={0: 1, 1: 1},
            rangers={2: 5, 3: 5},
            camps={0: 1, 1: 1},
            fences={(0, 1): 1, (1, 3): 1},
        )
        benefit = self.model.calculate_total_benefit(s)
        self.assertGreaterEqual(benefit, 0.0)
        self.assertLessEqual(benefit, 1.0)

    def test_calculate_protection_benefit(self):
        s = DeploymentSolution(
            cameras={0: 1},
            drones={1: 1},
            rangers={2: 3},
            camps={2: 1},
            fences={},
        )
        pb = self.model.calculate_protection_benefit(s)
        self.assertEqual(len(pb), 4)
        for gid in range(4):
            self.assertGreaterEqual(pb[gid], 0.0)

    def test_calculate_total_benefit(self):
        s = DeploymentSolution(
            cameras={0: 1, 1: 1},
            drones={0: 1},
            rangers={2: 5},
            camps={2: 1},
            fences={},
        )
        benefit = self.model.calculate_total_benefit(s)
        self.assertGreaterEqual(benefit, 0.0)
        self.assertLessEqual(benefit, 1.0)

    def test_calculate_patrol_coverage(self):
        s = DeploymentSolution(
            cameras={}, camps={2: 1}, drones={}, rangers={2: 5}, fences={}
        )
        coverage = self.model.calculate_patrol_coverage(s)
        self.assertEqual(len(coverage), 4)
        self.assertGreater(coverage[2], 0)

    def test_calculate_drone_coverage(self):
        s = DeploymentSolution(
            cameras={}, camps={}, drones={0: 1}, rangers={}, fences={}
        )
        coverage = self.model.calculate_drone_coverage(s)
        self.assertEqual(len(coverage), 4)

    def test_calculate_camera_coverage(self):
        s = DeploymentSolution(
            cameras={0: 1}, camps={}, drones={}, rangers={}, fences={}
        )
        coverage = self.model.calculate_camera_coverage(s)
        self.assertEqual(len(coverage), 4)

    def test_calculate_fence_protection(self):
        s = DeploymentSolution(
            cameras={}, camps={}, drones={}, rangers={}, fences={(0, 1): 1}
        )
        protection = self.model.calculate_fence_protection(s)
        self.assertEqual(len(protection), 4)

    def test_calculate_protection_effect(self):
        s = DeploymentSolution(
            cameras={0: 1},
            drones={1: 1},
            rangers={2: 3},
            camps={2: 1},
            fences={},
        )
        effect = self.model.calculate_protection_effect(s)
        self.assertEqual(len(effect), 4)
        for gid in range(4):
            self.assertGreaterEqual(effect[gid], 0.0)

    def test_benefit_monotonic(self):
        s_empty = DeploymentSolution(cameras={}, camps={}, drones={}, rangers={}, fences={})
        s_full = DeploymentSolution(
            cameras={0: 1, 1: 1, 2: 1, 3: 1},
            drones={0: 1, 1: 1},
            rangers={2: 5, 3: 5},
            camps={0: 1, 1: 1},
            fences={(0, 1): 1, (1, 3): 1},
        )
        b_empty = self.model.calculate_total_benefit(s_empty)
        b_full = self.model.calculate_total_benefit(s_full)
        self.assertGreaterEqual(b_full, b_empty)


if __name__ == '__main__':
    unittest.main()
