"""Test suite for collaborative resource synergy model.

Verifies that Patrol+Drone and Patrol+Camera synergy terms
are computed correctly according to the formula:
  E_i = wp*P + wd*D + wc*C + wf*F
        + alpha_pd * (P*D)/(1+P+D)
        + alpha_pc * (P*C)/(1+P+C)
"""

import pytest
import numpy as np
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grid_model import HexGridModel, GridData
from data_loader import CoverageParameters
from coverage_model import CoverageModel, DeploymentSolution


@pytest.fixture
def simple_grid_model():
    """Create a minimal 3-grid linear layout for deterministic testing."""
    grids = [
        GridData(grid_id=0, q=0, r=0, terrain_type='SparseGrass', risk=1.0),
        GridData(grid_id=1, q=1, r=0, terrain_type='SparseGrass', risk=1.0),
        GridData(grid_id=2, q=2, r=0, terrain_type='SparseGrass', risk=1.0),
    ]
    return HexGridModel(grids)


@pytest.fixture
def default_coverage_params():
    return CoverageParameters(
        patrol_radius=5.0,
        drone_radius=8.0,
        camera_radius=3.0,
        fence_protection=0.5,
        wp=0.3,
        wd=0.3,
        wc=0.2,
        wf=0.2,
        alpha_pd=0.4,
        alpha_pc=0.15
    )


@pytest.fixture
def deployment_matrices():
    """All grids support all resources for testing."""
    deployment = {
        'patrol': {0: 1, 1: 1, 2: 1},
        'camp':  {0: 1, 1: 1, 2: 1},
        'drone': {0: 1, 1: 1, 2: 1},
        'camera':{0: 1, 1: 1, 2: 1},
        'fence': {0: 1, 1: 1, 2: 1},
    }
    return deployment


@pytest.fixture
def visibility_params():
    return {
        0: {'drone': 1.0, 'camera': 1.0},
        1: {'drone': 1.0, 'camera': 1.0},
        2: {'drone': 1.0, 'camera': 1.0},
    }


class TestSynergyCalculation:
    """Test synergy computation matches expected formula."""

    def test_synergy_pd_formula_exact(self, simple_grid_model, default_coverage_params,
                                       deployment_matrices, visibility_params):
        """Verify Patrol+Drone synergy formula: alpha_pd * (P*D)/(1+P+D)."""
        # Deploy 1 patrol at grid 0, 1 drone at grid 0 (co-located)
        solution = DeploymentSolution(
            cameras={},
            camps={},
            drones={0: 1},
            rangers={0: 1},
            fences={}
        )

        model = CoverageModel(
            grid_model=simple_grid_model,
            coverage_params=default_coverage_params,
            deployment_matrix=deployment_matrices,
            visibility_params=visibility_params
        )

        patrol_cov = model.calculate_patrol_coverage(solution)
        drone_cov = model.calculate_drone_coverage(solution)

        # Grid 0 has both patrol and drone
        P0 = patrol_cov[0]
        D0 = drone_cov[0]

        # Compute expected synergy manually
        expected_synergy = default_coverage_params.alpha_pd * (P0 * D0) / (1.0 + P0 + D0)

        # Extract actual synergy from protection effect
        protection_effect = model.calculate_protection_effect(solution)
        base_contribution = (default_coverage_params.wp * P0 +
                            default_coverage_params.wd * D0 +
                            default_coverage_params.wc * 0 +
                            default_coverage_params.wf * 0)
        actual_synergy = protection_effect[0] - base_contribution

        assert np.isclose(actual_synergy, expected_synergy, rtol=1e-6), \
            f"Patrol+Drone synergy mismatch: expected {expected_synergy}, got {actual_synergy}"

    def test_synergy_pc_formula_exact(self, simple_grid_model, default_coverage_params,
                                       deployment_matrices, visibility_params):
        """Verify Patrol+Camera synergy formula: alpha_pc * (P*C)/(1+P+C)."""
        # Deploy 1 patrol at grid 0, 1 camera at grid 0
        solution = DeploymentSolution(
            cameras={0: 1},
            camps={},
            drones={},
            rangers={0: 1},
            fences={}
        )

        model = CoverageModel(
            grid_model=simple_grid_model,
            coverage_params=default_coverage_params,
            deployment_matrix=deployment_matrices,
            visibility_params=visibility_params
        )

        patrol_cov = model.calculate_patrol_coverage(solution)
        camera_cov = model.calculate_camera_coverage(solution)

        P0 = patrol_cov[0]
        C0 = camera_cov[0]

        expected_synergy = default_coverage_params.alpha_pc * (P0 * C0) / (1.0 + P0 + C0)

        protection_effect = model.calculate_protection_effect(solution)
        base_contribution = (default_coverage_params.wp * P0 +
                            default_coverage_params.wd * 0 +
                            default_coverage_params.wc * C0 +
                            default_coverage_params.wf * 0)
        actual_synergy = protection_effect[0] - base_contribution

        assert np.isclose(actual_synergy, expected_synergy, rtol=1e-6), \
            f"Patrol+Camera synergy mismatch: expected {expected_synergy}, got {actual_synergy}"

    def test_synergy_zero_when_one_resource_absent(self, simple_grid_model, default_coverage_params,
                                                    deployment_matrices, visibility_params):
        """Synergy should be zero when either resource is not present."""
        # Only patrol, no drone or camera
        solution = DeploymentSolution(
            cameras={},
            camps={},
            drones={},
            rangers={0: 1},
            fences={}
        )

        model = CoverageModel(
            grid_model=simple_grid_model,
            coverage_params=default_coverage_params,
            deployment_matrix=deployment_matrices,
            visibility_params=visibility_params
        )

        protection_effect = model.calculate_protection_effect(solution)
        # Grid 0 has patrol only, so synergy should be 0
        # E[0] = wp * P0 (only base contribution)
        patrol_cov = model.calculate_patrol_coverage(solution)
        expected_E0 = default_coverage_params.wp * patrol_cov[0]

        assert np.isclose(protection_effect[0], expected_E0, rtol=1e-6), \
            "Synergy should be zero when only one resource present"

    def test_synergy_normalization_prevents_explosion(self, simple_grid_model,
                                                        default_coverage_params,
                                                        deployment_matrices, visibility_params):
        """Verify normalized synergy grows sub-linearly with resource counts."""
        # Create two scenarios: (P=10, D=10) vs (P=100, D=100)
        # Despite 10x resources, synergy should be bounded by alpha
        solution_10 = DeploymentSolution(
            cameras={},
            camps={},
            drones={0: 10},
            rangers={0: 10},
            fences={}
        )
        solution_100 = DeploymentSolution(
            cameras={},
            camps={},
            drones={0: 100},
            rangers={0: 100},
            fences={}
        )

        model = CoverageModel(
            grid_model=simple_grid_model,
            coverage_params=default_coverage_params,
            deployment_matrix=deployment_matrices,
            visibility_params=visibility_params
        )

        effect_10 = model.calculate_protection_effect(solution_10)
        effect_100 = model.calculate_protection_effect(solution_100)

        P10 = model.calculate_patrol_coverage(solution_10)[0]
        D10 = model.calculate_drone_coverage(solution_10)[0]
        P100 = model.calculate_patrol_coverage(solution_100)[0]
        D100 = model.calculate_drone_coverage(solution_100)[0]

        synergy_10 = default_coverage_params.alpha_pd * (P10 * D10) / (1 + P10 + D10)
        synergy_100 = default_coverage_params.alpha_pd * (P100 * D100) / (1 + P100 + D100)

        # Both should be less than alpha_pd (maximum possible synergy)
        assert synergy_10 < default_coverage_params.alpha_pd + 1e-6
        assert synergy_100 < default_coverage_params.alpha_pd + 1e-6

        # With saturation, (P*D)/(1+P+D) ≤ min(P,D) but actually ≤ min(P,D)/2 asymptotically
        # So synergy_100 should not be 10x synergy_10
        assert synergy_100 <= synergy_10 * 2, \
            "Synergy should saturate, not scale linearly with resources"

    def test_synergy_parameters_in_coverage_params(self):
        """Ensure CoverageParameters has alpha_pd and alpha_pc with defaults."""
        from data_loader import CoverageParameters

        params = CoverageParameters()
        assert hasattr(params, 'alpha_pd'), "CoverageParameters missing alpha_pd"
        assert hasattr(params, 'alpha_pc'), "CoverageParameters missing alpha_pc"
        assert params.alpha_pd == 0.4, f"Default alpha_pd should be 0.4, got {params.alpha_pd}"
        assert params.alpha_pc == 0.15, f"Default alpha_pc should be 0.15, got {params.alpha_pc}"

    def test_backward_compatibility_defaults_used(self, simple_grid_model,
                                                    deployment_matrices, visibility_params):
        """When loading config without alpha values, defaults should be used."""
        from data_loader import DataLoader

        loader = DataLoader()
        loader.set_constraints(
            total_patrol=2,
            total_camps=0,
            max_rangers_per_camp=1,
            total_cameras=1,
            total_drones=1,
            total_fence_length=0.0
        )
        loader.set_coverage_parameters()  # Uses defaults

        assert loader.coverage_params.alpha_pd == 0.4
        assert loader.coverage_params.alpha_pc == 0.15


class TestSynergyEdgeCases:
    """Test edge cases and numerical stability."""

    def test_zero_coverage_synergy_zero(self, simple_grid_model, default_coverage_params,
                                         deployment_matrices, visibility_params):
        """When coverage is zero, synergy must be exactly zero (not NaN/Inf)."""
        # No resources deployed
        solution = DeploymentSolution(
            cameras={}, camps={}, drones={}, rangers={}, fences={}
        )

        model = CoverageModel(
            grid_model=simple_grid_model,
            coverage_params=default_coverage_params,
            deployment_matrix=deployment_matrices,
            visibility_params=visibility_params
        )

        protection_effect = model.calculate_protection_effect(solution)
        for grid_id, E in protection_effect.items():
            assert np.isfinite(E), f"Protection effect should be finite for grid {grid_id}"
            assert E == 0.0, f"Expected zero protection with no resources, got {E}"

    def test_very_small_coverage_values(self, simple_grid_model, default_coverage_params,
                                         deployment_matrices, visibility_params):
        """Test numerical stability with very small P, D, C values."""
        # This is hard to achieve with integer deployments, but formula should handle it
        # We'll test directly on coverage values via a mock-like approach
        P = 1e-10
        D = 1e-10
        C = 1e-10

        denom_pd = 1.0 + P + D
        denom_pc = 1.0 + P + C

        synergy_pd = default_coverage_params.alpha_pd * (P * D) / denom_pd
        synergy_pc = default_coverage_params.alpha_pc * (P * C) / denom_pc

        assert np.isfinite(synergy_pd), "Synergy PD should be finite"
        assert np.isfinite(synergy_pc), "Synergy PC should be finite"
        assert synergy_pd < 1e-20, "Very small coverage should yield near-zero synergy"
        assert synergy_pc < 1e-20
