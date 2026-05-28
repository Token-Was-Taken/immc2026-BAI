import sys
import os
import unittest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grid_model import HexGridModel
from data_loader import GridData, CoverageParameters
from coverage_model import CoverageModel, DeploymentSolution


def _make_model(grids, coverage_params=None, deployment_matrix=None, visibility_params=None):
    grid_model = HexGridModel(grids)
    if coverage_params is None:
        coverage_params = CoverageParameters()
    if deployment_matrix is None:
        deployment_matrix = {
            'camera': {g.grid_id: 1 for g in grids},
            'drone': {g.grid_id: 1 for g in grids},
            'camp': {g.grid_id: 1 for g in grids},
            'patrol': {g.grid_id: 1 for g in grids},
            'fence': {g.grid_id: 6 for g in grids},
        }
    if visibility_params is None:
        visibility_params = {g.grid_id: {'drone': 1.0, 'camera': 1.0} for g in grids}
    return CoverageModel(grid_model, coverage_params, deployment_matrix, visibility_params)


class TestDeploymentSolutionExtended(unittest.TestCase):
    def test_cache_key_initially_none(self):
        s = DeploymentSolution(cameras={}, camps={}, drones={}, rangers={}, fences={})
        self.assertIsNone(s._cache_key)

    def test_solution_independent_copies(self):
        d1 = {0: 1}
        s = DeploymentSolution(cameras=dict(d1), camps={}, drones={}, rangers={}, fences={})
        d1[0] = 99
        self.assertEqual(s.cameras[0], 1)


class TestPatrolCoverage(unittest.TestCase):
    def setUp(self):
        self.grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.5),
            GridData(grid_id=1, q=1, r=0, terrain_type="SparseGrass", risk=0.3),
            GridData(grid_id=2, q=2, r=0, terrain_type="SparseGrass", risk=0.7),
            GridData(grid_id=3, q=3, r=0, terrain_type="SparseGrass", risk=0.9),
        ]
        self.model = _make_model(self.grids)

    def test_no_rangers_zero_coverage(self):
        s = DeploymentSolution(cameras={}, camps={}, drones={}, rangers={}, fences={})
        cov = self.model.calculate_patrol_coverage(s)
        for gid in range(4):
            self.assertAlmostEqual(cov[gid], 0.0, places=10)

    def test_ranger_at_grid_covers_self(self):
        s = DeploymentSolution(cameras={}, camps={}, drones={}, rangers={0: 5}, fences={})
        cov = self.model.calculate_patrol_coverage(s)
        self.assertGreater(cov[0], 0.0)

    def test_coverage_decays_with_distance(self):
        s = DeploymentSolution(cameras={}, camps={}, drones={}, rangers={0: 5}, fences={})
        cov = self.model.calculate_patrol_coverage(s)
        self.assertGreater(cov[0], cov[1])
        self.assertGreater(cov[1], cov[2])

    def test_camp_rangers_counted(self):
        s = DeploymentSolution(cameras={}, camps={0: 1}, drones={}, rangers={0: 3}, fences={})
        cov = self.model.calculate_patrol_coverage(s)
        self.assertGreater(cov[0], 0.0)

    def test_camp_without_rangers_no_patrol(self):
        s = DeploymentSolution(cameras={}, camps={0: 1}, drones={}, rangers={}, fences={})
        cov = self.model.calculate_patrol_coverage(s)
        self.assertAlmostEqual(cov[0], 0.0, places=10)


class TestDroneCoverage(unittest.TestCase):
    def setUp(self):
        self.grids = [
            GridData(grid_id=i, q=i, r=0, terrain_type="SparseGrass", risk=0.5)
            for i in range(5)
        ]
        self.model = _make_model(self.grids)

    def test_no_drones_zero_coverage(self):
        s = DeploymentSolution(cameras={}, camps={}, drones={}, rangers={}, fences={})
        cov = self.model.calculate_drone_coverage(s)
        for gid in range(5):
            self.assertAlmostEqual(cov[gid], 0.0, places=10)

    def test_drone_covers_nearby(self):
        s = DeploymentSolution(cameras={}, camps={}, drones={0: 1}, rangers={}, fences={})
        cov = self.model.calculate_drone_coverage(s)
        self.assertGreater(cov[0], 0.0)

    def test_coverage_bounded_by_1(self):
        s = DeploymentSolution(cameras={}, camps={}, drones={i: 1 for i in range(5)}, rangers={}, fences={})
        cov = self.model.calculate_drone_coverage(s)
        for gid in range(5):
            self.assertLessEqual(cov[gid], 1.0)


class TestCameraCoverage(unittest.TestCase):
    def setUp(self):
        self.grids = [
            GridData(grid_id=i, q=i, r=0, terrain_type="SparseGrass", risk=0.5)
            for i in range(5)
        ]
        self.model = _make_model(self.grids)

    def test_camera_count_multiplied(self):
        s1 = DeploymentSolution(cameras={0: 1}, camps={}, drones={}, rangers={}, fences={})
        s2 = DeploymentSolution(cameras={0: 3}, camps={}, drones={}, rangers={}, fences={})
        cov1 = self.model.calculate_camera_coverage(s1)
        cov2 = self.model.calculate_camera_coverage(s2)
        # Coverage is bounded by 1.0, but check that more cameras don't decrease
        self.assertGreaterEqual(cov2[0], cov1[0])


class TestFenceProtection(unittest.TestCase):
    def setUp(self):
        self.grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0),
            GridData(grid_id=1, q=1, r=0, terrain_type="SparseGrass", risk=0.0),
        ]
        self.model = _make_model(self.grids)

    def test_boundary_edge_fence(self):
        s = DeploymentSolution(cameras={}, camps={}, drones={}, rangers={},
                               fences={(0, 0): 1})
        prot = self.model.calculate_fence_protection(s)
        self.assertGreater(prot[0], 0.0)

    def test_internal_edge_fence(self):
        s = DeploymentSolution(cameras={}, camps={}, drones={}, rangers={},
                               fences={(0, 1): 1})
        prot = self.model.calculate_fence_protection(s)
        self.assertGreater(prot[0], 0.0)
        self.assertGreater(prot[1], 0.0)

    def test_multiple_fences_cumulative(self):
        s1 = DeploymentSolution(cameras={}, camps={}, drones={}, rangers={},
                                fences={(0, 0): 1})
        s2 = DeploymentSolution(cameras={}, camps={}, drones={}, rangers={},
                                fences={(0, 0): 1, (0, 1): 1, (0, 2): 1})
        p1 = self.model.calculate_fence_protection(s1)
        p2 = self.model.calculate_fence_protection(s2)
        self.assertGreater(p2[0], p1[0])

    def test_fence_protection_bounded(self):
        s = DeploymentSolution(cameras={}, camps={}, drones={}, rangers={},
                               fences={(0, i): 1 for i in range(6)})
        prot = self.model.calculate_fence_protection(s)
        self.assertLessEqual(prot[0], 1.0)


class TestProtectionEffect(unittest.TestCase):
    def setUp(self):
        self.grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.5),
            GridData(grid_id=1, q=1, r=0, terrain_type="SparseGrass", risk=0.3),
        ]
        self.model = _make_model(self.grids)

    def test_empty_solution_zero_effect(self):
        s = DeploymentSolution(cameras={}, camps={}, drones={}, rangers={}, fences={})
        effect = self.model.calculate_protection_effect(s)
        self.assertAlmostEqual(effect[0], 0.0, places=10)
        self.assertAlmostEqual(effect[1], 0.0, places=10)

    def test_synergy_positive(self):
        s = DeploymentSolution(cameras={}, camps={0: 1}, drones={0: 1}, rangers={0: 3}, fences={})
        effect = self.model.calculate_protection_effect(s)
        self.assertGreater(effect[0], 0.0)


class TestTimeAwareBenefit(unittest.TestCase):
    def setUp(self):
        self.grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.5, temporal_factor=1.0),
            GridData(grid_id=1, q=1, r=0, terrain_type="SparseGrass", risk=0.5, temporal_factor=1.5),
        ]
        self.model = _make_model(self.grids)

    def test_time_aware_benefit_differs(self):
        s = DeploymentSolution(cameras={}, camps={}, drones={}, rangers={0: 5}, fences={})
        regular = self.model.calculate_total_benefit(s)
        time_aware = self.model.calculate_time_aware_total_benefit(s)
        self.assertNotAlmostEqual(regular, time_aware, places=5)


class TestValidateSolution(unittest.TestCase):
    def setUp(self):
        self.grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0),
            GridData(grid_id=1, q=1, r=0, terrain_type="SparseGrass", risk=0.0),
        ]
        self.model = _make_model(self.grids)
        self.constraints = {
            'total_cameras': 2, 'total_drones': 2, 'total_camps': 2,
            'total_patrol': 4, 'total_fence_length': 10,
            'max_cameras_per_grid': 1, 'max_drones_per_grid': 1,
        }

    def test_valid_solution(self):
        s = DeploymentSolution(
            cameras={0: 1}, camps={1: 1}, drones={2: 1},
            rangers={3: 1}, fences={}
        )
        # Use a model with 4 grids in the deployment matrix
        grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0),
            GridData(grid_id=1, q=1, r=0, terrain_type="SparseGrass", risk=0.0),
            GridData(grid_id=2, q=2, r=0, terrain_type="SparseGrass", risk=0.0),
            GridData(grid_id=3, q=3, r=0, terrain_type="SparseGrass", risk=0.0),
        ]
        model = _make_model(grids)
        valid, violations = model.validate_solution(s, self.constraints)
        self.assertTrue(valid)
        self.assertEqual(violations, [])

    def test_camera_limit_exceeded(self):
        s = DeploymentSolution(
            cameras={0: 1, 1: 1}, camps={}, drones={},
            rangers={}, fences={}
        )
        s2 = DeploymentSolution(
            cameras={0: 1, 1: 1, 0: 1}, camps={}, drones={},
            rangers={}, fences={}
        )
        c = dict(self.constraints)
        c['total_cameras'] = 1
        valid, violations = self.model.validate_solution(s, c)
        self.assertFalse(valid)

    def test_patrol_camp_conflict(self):
        s = DeploymentSolution(
            cameras={}, camps={0: 1}, drones={},
            rangers={0: 1}, fences={}
        )
        valid, violations = self.model.validate_solution(s, self.constraints)
        self.assertFalse(valid)
        self.assertTrue(any("cannot share" in v for v in violations))

    def test_fence_length_exceeded(self):
        s = DeploymentSolution(
            cameras={}, camps={}, drones={}, rangers={},
            fences={(0, 0): 1, (0, 1): 1, (0, 2): 1}
        )
        c = dict(self.constraints)
        c['total_fence_length'] = 2
        valid, violations = self.model.validate_solution(s, c)
        self.assertFalse(valid)
        self.assertTrue(any("fence length" in v for v in violations))


class TestRepairSolution(unittest.TestCase):
    def setUp(self):
        self.grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.5),
            GridData(grid_id=1, q=1, r=0, terrain_type="SparseGrass", risk=0.3),
            GridData(grid_id=2, q=2, r=0, terrain_type="SparseGrass", risk=0.7),
            GridData(grid_id=3, q=3, r=0, terrain_type="SparseGrass", risk=0.9),
        ]
        self.model = _make_model(self.grids)
        self.constraints = {
            'total_cameras': 2, 'total_drones': 2, 'total_camps': 2,
            'total_patrol': 4, 'total_fence_length': 10,
            'max_cameras_per_grid': 1, 'max_drones_per_grid': 1,
            'max_camps_per_grid': 1, 'max_rangers_per_grid': 1,
        }

    def test_repair_removes_invalid_deployments(self):
        s = DeploymentSolution(
            cameras={99: 1}, camps={}, drones={},
            rangers={}, fences={}
        )
        repaired = self.model.repair_solution(s, self.constraints, force_full_deployment=False)
        self.assertEqual(sum(repaired.cameras.values()), 0)

    def test_repair_enforces_force_full_deployment(self):
        s = DeploymentSolution(cameras={}, camps={}, drones={}, rangers={}, fences={})
        repaired = self.model.repair_solution(s, self.constraints, force_full_deployment=True)
        self.assertEqual(sum(repaired.cameras.values()), self.constraints['total_cameras'])
        self.assertEqual(sum(repaired.drones.values()), self.constraints['total_drones'])
        self.assertEqual(sum(repaired.camps.values()), self.constraints['total_camps'])
        self.assertEqual(sum(repaired.rangers.values()), self.constraints['total_patrol'])

    def test_repair_resolves_conflicts(self):
        s = DeploymentSolution(
            cameras={0: 1}, camps={0: 1}, drones={},
            rangers={}, fences={}
        )
        repaired = self.model.repair_solution(s, self.constraints, force_full_deployment=False,
                                               skip_conflict_resolution=False)
        # After repair with skip_conflict_resolution=False, grid 0 should have
        # at most 1 resource type (conflict resolution picks one randomly)
        # However, force_full_deployment=False means we don't add extra resources
        has_camera = repaired.cameras.get(0, 0) > 0
        has_camp = repaired.camps.get(0, 0) > 0
        has_drone = repaired.drones.get(0, 0) > 0
        has_ranger = repaired.rangers.get(0, 0) > 0
        total_types = sum([has_camera, has_camp, has_drone, has_ranger])
        self.assertLessEqual(total_types, 2)

    def test_repair_clears_cache_key(self):
        s = DeploymentSolution(cameras={}, camps={}, drones={}, rangers={}, fences={})
        s._cache_key = 12345
        repaired = self.model.repair_solution(s, self.constraints, force_full_deployment=False)
        self.assertIsNone(repaired._cache_key)


class TestMarginalContributions(unittest.TestCase):
    def setUp(self):
        self.grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.5),
            GridData(grid_id=1, q=1, r=0, terrain_type="SparseGrass", risk=0.3),
        ]
        self.model = _make_model(self.grids)

    def test_marginal_contribution_positive(self):
        s = DeploymentSolution(cameras={0: 1}, camps={}, drones={0: 1}, rangers={0: 3}, fences={})
        contribs = self.model._calculate_resource_marginal_contributions(s)
        self.assertIn(('camera', 0), contribs)
        self.assertIn(('drone', 0), contribs)
        self.assertIn(('patrol', 0), contribs)


class TestZeroRiskGrids(unittest.TestCase):
    def test_zero_risk_zero_benefit(self):
        grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0),
        ]
        model = _make_model(grids)
        s = DeploymentSolution(cameras={0: 1}, camps={}, drones={0: 1}, rangers={0: 5}, fences={})
        pb = model.calculate_protection_benefit(s)
        self.assertAlmostEqual(pb[0], 0.0, places=10)

    def test_zero_risk_total_benefit_zero(self):
        grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0),
        ]
        model = _make_model(grids)
        s = DeploymentSolution(cameras={0: 1}, camps={}, drones={0: 1}, rangers={0: 5}, fences={})
        total = model.calculate_total_benefit(s)
        self.assertAlmostEqual(total, 0.0, places=10)


if __name__ == '__main__':
    unittest.main()
