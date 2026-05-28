import sys
import os
import unittest
import json
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grid_model import HexGridModel
from data_loader import GridData, CoverageParameters, DataLoader
from coverage_model import CoverageModel, DeploymentSolution
from coverage_model_vectorized import VectorizedCoverageModel


def _make_test_input_json(path):
    """Create a minimal valid input JSON for pipeline testing."""
    grids = []
    grid_id = 0
    for r in range(4):
        for q in range(5):
            grids.append({
                "grid_id": grid_id,
                "q": q,
                "r": r,
                "x": q,
                "y": 3 - r,
                "hex_size": 1.0,
                "terrain_type": "SparseGrass" if grid_id % 3 != 0 else "Road",
                "fire_risk": 0.3,
                "terrain_complexity": 0.2,
                "vegetation_type": "GRASSLAND",
                "species_densities": {"rhino": 0.0, "elephant": 0.0, "bird": 0.0},
            })
            grid_id += 1

    data = {
        "map_config": {
            "map_width": 5,
            "map_height": 4,
            "boundary_type": "RECTANGLE",
            "road_locations": [[x, y] for x in range(5) for y in range(4)
                               if (x + y * 5) % 3 == 0],
            "water_locations": [[1, 1], [3, 2]],
        },
        "time": {"hour_of_day": 12, "season": "DRY"},
        "use_temporal_factors": False,
        "risk_model_config": {
            "risk_weights": {
                "human_weight": 0.4,
                "environmental_weight": 0.3,
                "density_weight": 0.3,
            },
            "human_risk_weights": {
                "boundary_weight": 0.2,
                "road_weight": 0.3,
                "water_weight": 0.5,
            },
            "environmental_risk_weights": {
                "fire_weight": 0.6,
                "terrain_weight": 0.4,
            },
            "temporal_weights": {
                "daytime_factor": 1.0,
                "nighttime_factor": 1.3,
                "gamma": 0.3,
                "dry_season_factor": 1.0,
                "rainy_season_factor": 1.2,
            },
        },
        "species_config": {
            "rhino": {"weight": 0.5, "rainy_season_multiplier": 1.2, "dry_season_multiplier": 1.0},
            "elephant": {"weight": 0.3, "rainy_season_multiplier": 1.3, "dry_season_multiplier": 0.9},
            "bird": {"weight": 0.2, "rainy_season_multiplier": 1.5, "dry_season_multiplier": 0.8},
        },
        "constraints": {
            "total_patrol": 4,
            "total_camps": 2,
            "max_rangers_per_camp": 3,
            "total_cameras": 4,
            "total_drones": 2,
            "total_fence_length": 10,
            "max_cameras_per_grid": 1,
            "max_drones_per_grid": 1,
            "max_camps_per_grid": 1,
            "max_rangers_per_grid": 2,
        },
        "coverage_params": {
            "patrol_radius": 5.0,
            "drone_radius": 8.0,
            "camera_radius": 3.0,
            "fence_protection": 0.5,
            "wp": 0.3, "wd": 0.3, "wc": 0.2, "wf": 0.2,
        },
        "dssa_config": {
            "population_size": 8,
            "max_iterations": 3,
            "producer_ratio": 0.25,
            "scout_ratio": 0.25,
            "ST": 0.8,
            "R2": 0.5,
            "force_full_deployment": True,
            "fitness_workers": 1,
            "output_interval": 1,
        },
        "grids": grids,
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    return data


class TestPipelineRiskComputation(unittest.TestCase):
    """Test risk computation through the pipeline."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.input_path = os.path.join(self.tmpdir, 'input.json')
        _make_test_input_json(self.input_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_compute_risk(self):
        from protection_pipeline import load_input, compute_risk_with_riskindex
        data = load_input(self.input_path)
        risk_map, temporal_map, raw_map = compute_risk_with_riskindex(data)
        self.assertEqual(len(risk_map), 20)
        for gid, risk in risk_map.items():
            self.assertGreaterEqual(risk, 0.0)
            self.assertLessEqual(risk, 1.0)
        for gid, tf in temporal_map.items():
            self.assertGreater(tf, 0.0)

    def test_compute_risk_raw_values(self):
        from protection_pipeline import load_input, compute_risk_with_riskindex
        data = load_input(self.input_path)
        _, _, raw_map = compute_risk_with_riskindex(data)
        for gid, risk in raw_map.items():
            self.assertGreaterEqual(risk, 0.0)


class TestPipelineDataLoader(unittest.TestCase):
    """Test data loader construction from pipeline data."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.input_path = os.path.join(self.tmpdir, 'input.json')
        _make_test_input_json(self.input_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_build_data_loader(self):
        from protection_pipeline import load_input, compute_risk_with_riskindex, build_data_loader
        data = load_input(self.input_path)
        risk_map, temporal_map, raw_map = compute_risk_with_riskindex(data)
        loader = build_data_loader(data, risk_map, temporal_map)
        self.assertEqual(len(loader.grids), 20)
        self.assertIsNotNone(loader.constraints)
        self.assertIsNotNone(loader.coverage_params)
        self.assertGreater(len(loader.deployment_matrix), 0)


class TestPipelineCoverageModel(unittest.TestCase):
    """Test coverage model construction from pipeline data."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.input_path = os.path.join(self.tmpdir, 'input.json')
        _make_test_input_json(self.input_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _build_coverage_model(self, vectorized=False):
        from protection_pipeline import load_input, compute_risk_with_riskindex, build_data_loader
        from grid_model import HexGridModel
        data = load_input(self.input_path)
        risk_map, temporal_map, raw_map = compute_risk_with_riskindex(data)
        loader = build_data_loader(data, risk_map, temporal_map)
        grid_model = HexGridModel(loader.grids)
        model_class = VectorizedCoverageModel if vectorized else CoverageModel
        return model_class(
            grid_model, loader.coverage_params,
            loader.deployment_matrix, loader.visibility_params,
            loader.coverage_effectiveness
        )

    def test_loop_model_created(self):
        cm = self._build_coverage_model(vectorized=False)
        self.assertIsInstance(cm, CoverageModel)

    def test_vectorized_model_created(self):
        cm = self._build_coverage_model(vectorized=True)
        self.assertIsInstance(cm, VectorizedCoverageModel)


class TestPipelineFullRun(unittest.TestCase):
    """Integration test: run the full pipeline end-to-end."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.input_path = os.path.join(self.tmpdir, 'input.json')
        self.output_path = os.path.join(self.tmpdir, 'output.json')
        _make_test_input_json(self.input_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_full_pipeline(self):
        from protection_pipeline import run_pipeline
        run_pipeline(
            input_path=self.input_path,
            output_path=self.output_path,
            vectorized=False,
            allow_partial_deployment=False,
            max_iterations=3,
            use_gpu=False,
        )
        self.assertTrue(os.path.exists(self.output_path))
        with open(self.output_path, 'r', encoding='utf-8') as f:
            output = json.load(f)
        self.assertIn('summary', output)
        self.assertIn('grids', output)
        self.assertIn('best_fitness', output['summary'])
        self.assertIn('total_protection_benefit', output['summary'])
        self.assertEqual(len(output['grids']), 20)

    def test_full_pipeline_vectorized(self):
        from protection_pipeline import run_pipeline
        run_pipeline(
            input_path=self.input_path,
            output_path=self.output_path,
            vectorized=True,
            allow_partial_deployment=False,
            max_iterations=3,
            use_gpu=False,
        )
        self.assertTrue(os.path.exists(self.output_path))
        with open(self.output_path, 'r', encoding='utf-8') as f:
            output = json.load(f)
        self.assertIn('best_fitness', output['summary'])

    def test_pipeline_output_grids_have_required_fields(self):
        from protection_pipeline import run_pipeline
        run_pipeline(
            input_path=self.input_path,
            output_path=self.output_path,
            vectorized=False,
            max_iterations=2,
            use_gpu=False,
        )
        with open(self.output_path, 'r', encoding='utf-8') as f:
            output = json.load(f)
        for grid in output['grids']:
            self.assertIn('grid_id', grid)
            self.assertIn('q', grid)
            self.assertIn('r', grid)
            self.assertIn('terrain_type', grid)
            self.assertIn('risk_normalized', grid)
            self.assertIn('protection_benefit_raw', grid)
            self.assertIn('deployment', grid)
            dep = grid['deployment']
            self.assertIn('patrol_rangers', dep)
            self.assertIn('camp', dep)
            self.assertIn('drone', dep)
            self.assertIn('camera', dep)

    def test_pipeline_fitness_positive(self):
        from protection_pipeline import run_pipeline
        run_pipeline(
            input_path=self.input_path,
            output_path=self.output_path,
            vectorized=False,
            max_iterations=5,
            use_gpu=False,
        )
        with open(self.output_path, 'r', encoding='utf-8') as f:
            output = json.load(f)
        self.assertGreater(output['summary']['best_fitness'], 0.0)
        self.assertGreater(output['summary']['total_protection_benefit'], 0.0)


class TestPipelineWarmStart(unittest.TestCase):
    """Integration test: warm-start from a previous output."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.input_path = os.path.join(self.tmpdir, 'input.json')
        self.output_path1 = os.path.join(self.tmpdir, 'output1.json')
        self.output_path2 = os.path.join(self.tmpdir, 'output2.json')
        _make_test_input_json(self.input_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_warm_start(self):
        from protection_pipeline import run_pipeline
        run_pipeline(
            input_path=self.input_path,
            output_path=self.output_path1,
            vectorized=False,
            max_iterations=3,
            use_gpu=False,
        )
        run_pipeline(
            input_path=self.input_path,
            output_path=self.output_path2,
            vectorized=False,
            max_iterations=3,
            warm_start_path=self.output_path1,
            use_gpu=False,
        )
        self.assertTrue(os.path.exists(self.output_path2))


class TestPipelineFreezeResources(unittest.TestCase):
    """Integration test: frozen resources mode."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.input_path = os.path.join(self.tmpdir, 'input.json')
        self.output_path = os.path.join(self.tmpdir, 'output.json')
        _make_test_input_json(self.input_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_freeze_patrol(self):
        from protection_pipeline import run_pipeline
        run_pipeline(
            input_path=self.input_path,
            output_path=self.output_path,
            vectorized=False,
            freeze_resources='patrol',
            max_iterations=3,
            use_gpu=False,
        )
        self.assertTrue(os.path.exists(self.output_path))


class TestPipelinePartialDeployment(unittest.TestCase):
    """Integration test: partial deployment mode."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.input_path = os.path.join(self.tmpdir, 'input.json')
        self.output_path = os.path.join(self.tmpdir, 'output.json')
        _make_test_input_json(self.input_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_partial_deployment(self):
        from protection_pipeline import run_pipeline
        run_pipeline(
            input_path=self.input_path,
            output_path=self.output_path,
            vectorized=False,
            allow_partial_deployment=True,
            max_iterations=3,
            use_gpu=False,
        )
        self.assertTrue(os.path.exists(self.output_path))


class TestPipelineWithTemporalFactors(unittest.TestCase):
    """Integration test: time-aware fitness."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.input_path = os.path.join(self.tmpdir, 'input.json')
        self.output_path = os.path.join(self.tmpdir, 'output.json')
        data = _make_test_input_json(self.input_path)
        data['use_temporal_factors'] = True
        data['time'] = {'hour_of_day': 22, 'season': 'RAINY'}
        with open(self.input_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_temporal_pipeline(self):
        from protection_pipeline import run_pipeline
        run_pipeline(
            input_path=self.input_path,
            output_path=self.output_path,
            vectorized=False,
            max_iterations=3,
            use_gpu=False,
        )
        with open(self.output_path, 'r', encoding='utf-8') as f:
            output = json.load(f)
        self.assertIn('total_risk_weighted', output['summary'])


class TestEvaluateSolution(unittest.TestCase):
    """Integration test: evaluate an existing solution."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.input_path = os.path.join(self.tmpdir, 'input.json')
        self.output_path = os.path.join(self.tmpdir, 'output.json')
        _make_test_input_json(self.input_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_evaluate_solution(self):
        from protection_pipeline import run_pipeline
        from evaluate_solution import build_coverage_model, load_solution_from_output
        run_pipeline(
            input_path=self.input_path,
            output_path=self.output_path,
            vectorized=False,
            max_iterations=3,
            use_gpu=False,
        )
        cm, gm, data = build_coverage_model(self.input_path, vectorized=False)
        sol = load_solution_from_output(self.output_path)
        pb = cm.calculate_protection_benefit(sol)
        total = sum(pb.values())
        self.assertGreater(total, 0.0)


if __name__ == '__main__':
    unittest.main()
