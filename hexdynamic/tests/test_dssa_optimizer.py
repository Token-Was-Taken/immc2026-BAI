import sys
import os
import unittest
import random
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grid_model import HexGridModel
from data_loader import GridData, CoverageParameters
from coverage_model import CoverageModel, DeploymentSolution
from dssa_optimizer import (
    DSSAOptimizer, DSSAConfig,
    _snapshot_solution, _sol_to_dict, _dict_to_sol,
    _worker_make_cache_key,
    _worker_discrete_swap, _worker_discrete_migrate, _worker_discrete_reshuffle,
    _worker_exploit_toward_best, _worker_follow_producer,
    _worker_partial_reset_scout,
)


def _make_grids(n=20):
    return [
        GridData(grid_id=i, q=i % 5, r=i // 5, terrain_type="SparseGrass", risk=0.3 + 0.02 * i)
        for i in range(n)
    ]


def _make_coverage_model(grids):
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
    return CoverageModel(grid_model, params, dm, vp)


def _make_optimizer(grids=None, pop_size=10, max_iter=5):
    if grids is None:
        grids = _make_grids(20)
    cm = _make_coverage_model(grids)
    constraints = {
        'total_cameras': 4, 'total_drones': 4, 'total_camps': 4,
        'total_patrol': 8, 'total_fence_length': 20,
        'max_cameras_per_grid': 1, 'max_drones_per_grid': 1,
        'max_camps_per_grid': 1, 'max_rangers_per_grid': 3,
        'max_fences_per_grid': 6,
    }
    config = DSSAConfig(population_size=pop_size, max_iterations=max_iter,
                        fitness_workers=1, output_interval=1)
    return DSSAOptimizer(cm, constraints, config)


class TestSnapshotSolution(unittest.TestCase):
    def test_snapshot_creates_copy(self):
        s = DeploymentSolution(
            cameras={0: 1}, camps={1: 1}, drones={2: 1},
            rangers={3: 2}, fences={(0, 1): 1}
        )
        snap = _snapshot_solution(s)
        self.assertEqual(snap.cameras, s.cameras)
        s.cameras[0] = 99
        self.assertEqual(snap.cameras[0], 1)


class TestSolDictConversion(unittest.TestCase):
    def test_roundtrip(self):
        s = DeploymentSolution(
            cameras={0: 1, 5: 2}, camps={3: 1}, drones={1: 1},
            rangers={2: 3}, fences={(0, 1): 1}
        )
        d = _sol_to_dict(s)
        s2 = _dict_to_sol(d)
        self.assertEqual(s2.cameras, s.cameras)
        self.assertEqual(s2.camps, s.camps)
        self.assertEqual(s2.drones, s.drones)
        self.assertEqual(s2.rangers, s.rangers)
        self.assertEqual(s2.fences, s.fences)

    def test_none_solution(self):
        self.assertIsNone(_sol_to_dict(None))
        self.assertIsNone(_dict_to_sol(None))


class TestWorkerCacheKey(unittest.TestCase):
    def test_cache_key_deterministic(self):
        s = DeploymentSolution(
            cameras={0: 1}, camps={}, drones={0: 1},
            rangers={0: 3}, fences={}
        )
        k1 = _worker_make_cache_key(s)
        k2 = _worker_make_cache_key(s)
        self.assertEqual(k1, k2)

    def test_cache_key_different_solutions(self):
        s1 = DeploymentSolution(cameras={0: 1}, camps={}, drones={}, rangers={}, fences={})
        s2 = DeploymentSolution(cameras={1: 1}, camps={}, drones={}, rangers={}, fences={})
        k1 = _worker_make_cache_key(s1)
        k2 = _worker_make_cache_key(s2)
        self.assertNotEqual(k1, k2)

    def test_cache_key_cached_on_solution(self):
        s = DeploymentSolution(cameras={0: 1}, camps={}, drones={}, rangers={}, fences={})
        k = _worker_make_cache_key(s)
        self.assertEqual(s._cache_key, k)


class TestDSSAConfig(unittest.TestCase):
    def test_defaults(self):
        c = DSSAConfig()
        self.assertEqual(c.population_size, 50)
        self.assertEqual(c.max_iterations, 200)
        self.assertEqual(c.producer_ratio, 0.2)
        self.assertEqual(c.ST, 0.8)
        self.assertFalse(c.use_time_aware_fitness)
        self.assertIsNone(c.force_full_deployment)
        self.assertFalse(c.use_risk_priority)

    def test_custom(self):
        c = DSSAConfig(population_size=100, max_iterations=500, ST=0.9)
        self.assertEqual(c.population_size, 100)
        self.assertEqual(c.max_iterations, 500)
        self.assertEqual(c.ST, 0.9)


class TestDSSAOptimizerInit(unittest.TestCase):
    def test_creates_successfully(self):
        opt = _make_optimizer()
        self.assertIsNotNone(opt)
        self.assertEqual(opt.config.population_size, 10)

    def test_grid_ids_populated(self):
        opt = _make_optimizer()
        self.assertEqual(len(opt.grid_ids), 20)

    def test_fitness_executor_created(self):
        opt = _make_optimizer()
        self.assertIsNotNone(opt._fitness_executor)

    def test_best_fitness_initial(self):
        opt = _make_optimizer()
        self.assertEqual(opt.best_fitness, float('-inf'))


class TestInitializePopulation(unittest.TestCase):
    def test_population_size(self):
        opt = _make_optimizer(pop_size=15)
        opt.initialize_population()
        self.assertEqual(len(opt.population), 15)

    def test_population_solutions_valid(self):
        opt = _make_optimizer(pop_size=10)
        opt.initialize_population()
        for sol in opt.population:
            self.assertIsInstance(sol, DeploymentSolution)
            total_cam = sum(sol.cameras.values())
            self.assertGreaterEqual(total_cam, 0)


class TestInitializeSolution(unittest.TestCase):
    def test_force_full_deployment(self):
        opt = _make_optimizer()
        sol = opt._initialize_solution()
        total_cam = sum(sol.cameras.values())
        total_drone = sum(sol.drones.values())
        total_camp = sum(sol.camps.values())
        total_ranger = sum(sol.rangers.values())
        self.assertEqual(total_cam, 4)
        self.assertEqual(total_drone, 4)
        self.assertEqual(total_camp, 4)
        self.assertEqual(total_ranger, 8)


class TestDiscretePerturbation(unittest.TestCase):
    def setUp(self):
        self.opt = _make_optimizer()
        self.opt.initialize_population()
        self.sol = self.opt.population[0]

    def test_swap_returns_valid_solution(self):
        import dssa_optimizer as dssa
        dssa._worker_coverage_model = self.opt.coverage_model
        dssa._worker_constraints = self.opt.constraints
        dssa._worker_grid_ids = self.opt.grid_ids
        dssa._worker_force_full_deployment = True
        dssa._worker_use_marginal_contribution_repair = False
        dssa._worker_skip_conflict_resolution = False
        dssa._worker_swap_prob = 0.6
        dssa._worker_migrate_prob = 0.25
        dssa._worker_reshuffle_prob = 0.15
        result = _worker_discrete_swap(self.sol)
        self.assertIsInstance(result, DeploymentSolution)

    def test_migrate_returns_valid_solution(self):
        import dssa_optimizer as dssa
        dssa._worker_coverage_model = self.opt.coverage_model
        dssa._worker_constraints = self.opt.constraints
        dssa._worker_grid_ids = self.opt.grid_ids
        dssa._worker_force_full_deployment = True
        dssa._worker_use_marginal_contribution_repair = False
        dssa._worker_skip_conflict_resolution = False
        result = _worker_discrete_migrate(self.sol)
        self.assertIsInstance(result, DeploymentSolution)

    def test_reshuffle_returns_valid_solution(self):
        import dssa_optimizer as dssa
        dssa._worker_coverage_model = self.opt.coverage_model
        dssa._worker_constraints = self.opt.constraints
        dssa._worker_grid_ids = self.opt.grid_ids
        dssa._worker_force_full_deployment = True
        dssa._worker_use_marginal_contribution_repair = False
        dssa._worker_skip_conflict_resolution = False
        result = _worker_discrete_reshuffle(self.sol)
        self.assertIsInstance(result, DeploymentSolution)


class TestExploitTowardBest(unittest.TestCase):
    def test_exploit_returns_valid(self):
        opt = _make_optimizer(pop_size=10)
        opt.initialize_population()
        opt.best_solution = opt.population[0]
        import dssa_optimizer as dssa
        dssa._worker_coverage_model = opt.coverage_model
        dssa._worker_constraints = opt.constraints
        dssa._worker_grid_ids = opt.grid_ids
        dssa._worker_force_full_deployment = True
        dssa._worker_use_marginal_contribution_repair = False
        dssa._worker_skip_conflict_resolution = False
        result = _worker_exploit_toward_best(opt.population[1], opt.best_solution)
        self.assertIsInstance(result, DeploymentSolution)


class TestFollowProducer(unittest.TestCase):
    def test_follow_returns_valid(self):
        opt = _make_optimizer(pop_size=10)
        opt.initialize_population()
        import dssa_optimizer as dssa
        dssa._worker_coverage_model = opt.coverage_model
        dssa._worker_constraints = opt.constraints
        dssa._worker_grid_ids = opt.grid_ids
        dssa._worker_force_full_deployment = True
        dssa._worker_use_marginal_contribution_repair = False
        dssa._worker_skip_conflict_resolution = False
        result = _worker_follow_producer(opt.population[1], opt.population[0])
        self.assertIsInstance(result, DeploymentSolution)


class TestPartialResetScout(unittest.TestCase):
    def test_reset_returns_valid(self):
        opt = _make_optimizer(pop_size=10)
        opt.initialize_population()
        import dssa_optimizer as dssa
        dssa._worker_coverage_model = opt.coverage_model
        dssa._worker_constraints = opt.constraints
        dssa._worker_grid_ids = opt.grid_ids
        dssa._worker_force_full_deployment = True
        dssa._worker_use_marginal_contribution_repair = False
        dssa._worker_skip_conflict_resolution = False
        dssa._worker_scout_partial_reset_ratio = 0.5
        result = _worker_partial_reset_scout(opt.population[0])
        self.assertIsInstance(result, DeploymentSolution)


class TestExplorationAlpha(unittest.TestCase):
    def test_3_phase_schedule(self):
        opt = _make_optimizer()
        opt.config.max_iterations = 100
        a_early = opt._get_exploration_alpha(10)
        a_mid = opt._get_exploration_alpha(50)
        a_late = opt._get_exploration_alpha(90)
        self.assertGreater(a_early, a_mid)
        self.assertGreater(a_mid, a_late)

    def test_stagnation_boost(self):
        opt = _make_optimizer()
        opt.config.max_iterations = 100
        opt.stagnation_count = 50
        a_normal = opt._get_exploration_alpha(50)
        opt.stagnation_count = 0
        a_boosted = opt._get_exploration_alpha(50)
        self.assertGreater(a_normal, a_boosted)


class TestDiversityCalculation(unittest.TestCase):
    def test_diversity_range(self):
        opt = _make_optimizer(pop_size=10)
        opt.initialize_population()
        div = opt._calculate_diversity()
        self.assertGreaterEqual(div, 0.0)
        self.assertLessEqual(div, 1.0)

    def test_single个体_diversity_zero(self):
        opt = _make_optimizer(pop_size=1)
        opt.initialize_population()
        div = opt._calculate_diversity()
        self.assertEqual(div, 0.0)


class TestSolutionToVector(unittest.TestCase):
    def test_vector_length(self):
        opt = _make_optimizer()
        opt.initialize_population()
        sol = opt.population[0]
        vec = opt._solution_to_vector(sol)
        expected_len = len(opt.grid_ids) * 5
        self.assertEqual(len(vec), expected_len)


class TestOptimize(unittest.TestCase):
    def test_optimize_runs(self):
        opt = _make_optimizer(pop_size=8, max_iter=3)
        best_sol, best_fit, history = opt.optimize()
        self.assertIsInstance(best_sol, DeploymentSolution)
        self.assertIsInstance(float(best_fit), float)
        self.assertEqual(len(history), 4)
        opt._fitness_executor.shutdown(wait=False)

    def test_optimize_improves(self):
        opt = _make_optimizer(pop_size=8, max_iter=5)
        _, _, history = opt.optimize()
        self.assertGreaterEqual(history[-1], history[0])
        opt._fitness_executor.shutdown(wait=False)


class TestGetSolutionStatistics(unittest.TestCase):
    def test_statistics_keys(self):
        opt = _make_optimizer()
        opt.initialize_population()
        stats = opt.get_solution_statistics(opt.population[0])
        self.assertIn('total_cameras', stats)
        self.assertIn('total_drones', stats)
        self.assertIn('total_camps', stats)
        self.assertIn('total_rangers', stats)
        self.assertIn('camera_locations', stats)


if __name__ == '__main__':
    unittest.main()
