import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_loader import (
    GridData, ResourceConstraints, CoverageParameters,
    DataLoader, DEFAULT_COVERAGE_EFFECTIVENESS,
)


class TestGridData(unittest.TestCase):
    def test_creation_defaults(self):
        g = GridData(grid_id=0, q=1, r=2, terrain_type="SparseGrass", risk=0.5)
        self.assertEqual(g.grid_id, 0)
        self.assertEqual(g.q, 1)
        self.assertEqual(g.r, 2)
        self.assertEqual(g.terrain_type, "SparseGrass")
        self.assertEqual(g.risk, 0.5)
        self.assertEqual(g.temporal_factor, 1.0)
        self.assertIsNone(g.species_densities)

    def test_creation_with_temporal_factor(self):
        g = GridData(grid_id=0, q=0, r=0, terrain_type="Road", risk=0.1, temporal_factor=1.3)
        self.assertEqual(g.temporal_factor, 1.3)

    def test_creation_with_species(self):
        sd = {"rhino": 0.8, "elephant": 0.3}
        g = GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.5, species_densities=sd)
        self.assertEqual(g.species_densities, sd)


class TestResourceConstraints(unittest.TestCase):
    def test_defaults(self):
        c = ResourceConstraints(
            total_patrol=10, total_camps=5, max_rangers_per_camp=3,
            total_cameras=8, total_drones=2, total_fence_length=50.0,
        )
        self.assertEqual(c.max_cameras_per_grid, 1)
        self.assertEqual(c.max_drones_per_grid, 1)
        self.assertEqual(c.max_camps_per_grid, 1)
        self.assertEqual(c.max_rangers_per_grid, 1)
        self.assertEqual(c.max_fences_per_grid, 6)

    def test_custom_max_per_grid(self):
        c = ResourceConstraints(
            total_patrol=10, total_camps=5, max_rangers_per_camp=3,
            total_cameras=8, total_drones=2, total_fence_length=50.0,
            max_cameras_per_grid=3, max_drones_per_grid=2,
            max_camps_per_grid=2, max_rangers_per_grid=5,
            max_fences_per_grid=4,
        )
        self.assertEqual(c.max_cameras_per_grid, 3)
        self.assertEqual(c.max_rangers_per_grid, 5)


class TestCoverageParameters(unittest.TestCase):
    def test_defaults(self):
        p = CoverageParameters()
        self.assertEqual(p.patrol_radius, 5.0)
        self.assertEqual(p.drone_radius, 8.0)
        self.assertEqual(p.camera_radius, 3.0)
        self.assertEqual(p.fence_protection, 0.5)
        self.assertEqual(p.wp, 0.3)
        self.assertEqual(p.wd, 0.3)
        self.assertEqual(p.wc, 0.2)
        self.assertEqual(p.wf, 0.2)
        self.assertEqual(p.alpha_pd, 0.4)
        self.assertEqual(p.alpha_pc, 0.15)

    def test_custom(self):
        p = CoverageParameters(patrol_radius=10.0, wp=0.5, alpha_pd=0.6)
        self.assertEqual(p.patrol_radius, 10.0)
        self.assertEqual(p.wp, 0.5)
        self.assertEqual(p.alpha_pd, 0.6)
        self.assertEqual(p.drone_radius, 8.0)


class TestDataLoader(unittest.TestCase):
    def setUp(self):
        self.loader = DataLoader()

    def test_init(self):
        self.assertEqual(self.loader.grids, [])
        self.assertEqual(self.loader.deployment_matrix, {})
        self.assertIsNone(self.loader.constraints)
        self.assertIsNone(self.loader.coverage_params)

    def test_generate_hexagonal_grid(self):
        grids = self.loader.generate_hexagonal_grid()
        self.assertEqual(len(grids), 120)
        self.assertEqual(grids[0].grid_id, 0)
        self.assertEqual(grids[-1].grid_id, 119)
        for g in grids:
            self.assertEqual(g.terrain_type, "SparseGrass")
            self.assertEqual(g.risk, 0.0)

    def test_generate_rectangular_hex_grid(self):
        grids = self.loader.generate_rectangular_hex_grid(width=5, height=4)
        self.assertEqual(len(grids), 20)
        ids = [g.grid_id for g in grids]
        self.assertEqual(ids, list(range(20)))

    def test_set_terrain_types(self):
        self.loader.generate_hexagonal_grid()
        terrain_map = {0: "Road", 5: "WaterHole", 10: "DenseGrass"}
        self.loader.set_terrain_types(terrain_map)
        self.assertEqual(self.loader.grids[0].terrain_type, "Road")
        self.assertEqual(self.loader.grids[5].terrain_type, "WaterHole")
        self.assertEqual(self.loader.grids[10].terrain_type, "DenseGrass")
        self.assertEqual(self.loader.grids[1].terrain_type, "SparseGrass")

    def test_set_risk_values(self):
        self.loader.generate_hexagonal_grid()
        risk_map = {0: 0.9, 1: 0.1}
        self.loader.set_risk_values(risk_map)
        self.assertEqual(self.loader.grids[0].risk, 0.9)
        self.assertEqual(self.loader.grids[1].risk, 0.1)
        self.assertEqual(self.loader.grids[2].risk, 0.0)

    def test_initialize_deployment_matrix_all_terrains(self):
        grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0),
            GridData(grid_id=1, q=1, r=0, terrain_type="DenseGrass", risk=0.0),
            GridData(grid_id=2, q=2, r=0, terrain_type="WaterHole", risk=0.0),
            GridData(grid_id=3, q=3, r=0, terrain_type="SaltMarsh", risk=0.0),
            GridData(grid_id=4, q=4, r=0, terrain_type="Road", risk=0.0),
        ]
        self.loader.grids = grids
        self.loader.initialize_deployment_matrix()

        dm = self.loader.deployment_matrix
        self.assertEqual(dm['patrol'][0], 1)   # SparseGrass
        self.assertEqual(dm['patrol'][1], 0)   # DenseGrass
        self.assertEqual(dm['patrol'][2], 0)   # WaterHole
        self.assertEqual(dm['patrol'][3], 0)   # SaltMarsh
        self.assertEqual(dm['patrol'][4], 1)   # Road

        self.assertEqual(dm['drone'][0], 1)
        self.assertEqual(dm['drone'][1], 1)
        self.assertEqual(dm['drone'][2], 1)
        self.assertEqual(dm['drone'][3], 1)
        self.assertEqual(dm['drone'][4], 1)

        self.assertEqual(dm['camera'][0], 1)
        self.assertEqual(dm['camera'][1], 0)
        self.assertEqual(dm['camera'][2], 0)
        self.assertEqual(dm['camera'][3], 0)
        self.assertEqual(dm['camera'][4], 1)

        self.assertEqual(dm['camp'][0], 0)
        self.assertEqual(dm['camp'][4], 1)

    def test_deployment_matrix_species_density_constraint(self):
        grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="Road", risk=0.0,
                     species_densities={"rhino": 0.5}),
            GridData(grid_id=1, q=1, r=0, terrain_type="Road", risk=0.0,
                     species_densities={"rhino": 0.0}),
        ]
        self.loader.grids = grids
        self.loader.initialize_deployment_matrix()
        self.assertEqual(self.loader.deployment_matrix['patrol'][0], 0)
        self.assertEqual(self.loader.deployment_matrix['patrol'][1], 1)
        self.assertEqual(self.loader.deployment_matrix['camp'][0], 0)
        self.assertEqual(self.loader.deployment_matrix['camp'][1], 1)

    def test_deployment_matrix_fence_with_edge_grids(self):
        grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0),
            GridData(grid_id=1, q=1, r=0, terrain_type="SparseGrass", risk=0.0),
        ]
        self.loader.grids = grids
        self.loader.initialize_deployment_matrix(edge_grids=[0])
        self.assertEqual(self.loader.deployment_matrix['fence'][0], 1)
        self.assertEqual(self.loader.deployment_matrix['fence'][1], 0)

    def test_initialize_visibility_params(self):
        grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0),
            GridData(grid_id=1, q=1, r=0, terrain_type="DenseGrass", risk=0.0),
        ]
        self.loader.grids = grids
        self.loader.initialize_visibility_params()
        self.assertEqual(self.loader.visibility_params[0]['drone'], 1.0)
        self.assertEqual(self.loader.visibility_params[0]['camera'], 1.0)
        self.assertEqual(self.loader.visibility_params[1]['drone'], 0.7)
        self.assertEqual(self.loader.visibility_params[1]['camera'], 0.5)

    def test_initialize_coverage_effectiveness_default(self):
        grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0),
            GridData(grid_id=1, q=1, r=0, terrain_type="DenseGrass", risk=0.0),
        ]
        self.loader.grids = grids
        self.loader.initialize_coverage_effectiveness()
        self.assertEqual(self.loader.coverage_effectiveness[0].get('patrol', 1.0), 1.0)
        self.assertEqual(self.loader.coverage_effectiveness[1].get('patrol'), 0.3)

    def test_initialize_coverage_effectiveness_with_overrides(self):
        grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0),
        ]
        self.loader.grids = grids
        overrides = {"SparseGrass": {"patrol": 0.5}}
        self.loader.initialize_coverage_effectiveness(overrides)
        self.assertEqual(self.loader.coverage_effectiveness[0]['patrol'], 0.5)

    def test_set_constraints(self):
        self.loader.set_constraints(
            total_patrol=20, total_camps=5, max_rangers_per_camp=3,
            total_cameras=10, total_drones=4, total_fence_length=100.0,
        )
        c = self.loader.constraints
        self.assertEqual(c.total_patrol, 20)
        self.assertEqual(c.total_camps, 5)
        self.assertEqual(c.total_fence_length, 100.0)

    def test_set_coverage_parameters(self):
        self.loader.set_coverage_parameters(patrol_radius=7.0, wp=0.4)
        p = self.loader.coverage_params
        self.assertEqual(p.patrol_radius, 7.0)
        self.assertEqual(p.wp, 0.4)
        self.assertEqual(p.drone_radius, 8.0)

    def test_get_grid_by_id(self):
        self.loader.generate_hexagonal_grid()
        g = self.loader.get_grid_by_id(5)
        self.assertIsNotNone(g)
        self.assertEqual(g.grid_id, 5)
        self.assertIsNone(self.loader.get_grid_by_id(999))

    def test_get_all_grid_ids(self):
        self.loader.generate_hexagonal_grid()
        ids = self.loader.get_all_grid_ids()
        self.assertEqual(len(ids), 120)
        self.assertEqual(ids[0], 0)
        self.assertEqual(ids[-1], 119)

    def test_get_terrain_distribution(self):
        self.loader.generate_hexagonal_grid()
        self.loader.set_terrain_types({0: "Road", 1: "Road", 2: "WaterHole"})
        dist = self.loader.get_terrain_distribution()
        self.assertEqual(dist["Road"], 2)
        self.assertEqual(dist["WaterHole"], 1)
        self.assertEqual(dist["SparseGrass"], 117)

    def test_load_from_config_minimal(self):
        config = {
            "grid_radius": 3,
            "constraints": {
                "total_patrol": 10,
                "total_camps": 3,
                "max_rangers_per_camp": 3,
                "total_cameras": 5,
                "total_drones": 2,
                "total_fence_length": 30.0,
            },
            "coverage_params": {
                "patrol_radius": 6.0,
            },
        }
        self.loader.load_from_config(config)
        self.assertGreater(len(self.loader.grids), 0)
        self.assertIsNotNone(self.loader.constraints)
        self.assertIsNotNone(self.loader.coverage_params)

    def test_load_from_config_full(self):
        config = {
            "grid_radius": 3,
            "terrain_map": {0: "Road"},
            "risk_map": {0: 0.9},
            "constraints": {
                "total_patrol": 30,
                "total_camps": 8,
                "max_rangers_per_camp": 4,
                "total_cameras": 15,
                "total_drones": 5,
                "total_fence_length": 80.0,
            },
            "coverage_params": {
                "patrol_radius": 6.0,
                "wp": 0.4,
            },
        }
        self.loader.load_from_config(config)
        self.assertEqual(self.loader.constraints.total_patrol, 30)
        self.assertEqual(self.loader.coverage_params.patrol_radius, 6.0)
        self.assertEqual(self.loader.grids[0].terrain_type, "Road")
        self.assertEqual(self.loader.grids[0].risk, 0.9)


class TestDefaultCoverageEffectiveness(unittest.TestCase):
    def test_dense_grass_reduced(self):
        self.assertIn("DenseGrass", DEFAULT_COVERAGE_EFFECTIVENESS)
        self.assertEqual(DEFAULT_COVERAGE_EFFECTIVENESS["DenseGrass"]["patrol"], 0.3)
        self.assertEqual(DEFAULT_COVERAGE_EFFECTIVENESS["DenseGrass"]["camp"], 0.3)


if __name__ == '__main__':
    unittest.main()
