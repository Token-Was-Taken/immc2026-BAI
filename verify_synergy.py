#!/usr/bin/env python
"""Integration test: verify synergy computes correctly end-to-end."""
import sys
import os

# Add hexdynamic dir to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'hexdynamic'))

from data_loader import DataLoader, CoverageParameters
from grid_model import HexGridModel, GridData
from coverage_model import CoverageModel, DeploymentSolution

def main():
    # Create minimal test grid
    grids = [
        GridData(0, 0, 0, 'SparseGrass', 1.0),
        GridData(1, 1, 0, 'SparseGrass', 1.0),
    ]
    grid_model = HexGridModel(grids)

    # Params with synergy enabled
    params = CoverageParameters(
        patrol_radius=5.0, drone_radius=8.0, camera_radius=3.0,
        wp=0.3, wd=0.3, wc=0.2, wf=0.2,
        alpha_pd=0.4, alpha_pc=0.15
    )

    # All grids allow all resources
    deployment = {
        'patrol': {0:1, 1:1},
        'camp':  {0:1, 1:1},
        'drone': {0:1, 1:1},
        'camera':{0:1, 1:1},
        'fence': {0:1, 1:1},
    }

    visibility = {
        0: {'drone':1.0, 'camera':1.0},
        1: {'drone':1.0, 'camera':1.0},
    }

    # Deploy patrol+drone at grid 0
    sol = DeploymentSolution(cameras={}, camps={}, drones={0:1}, rangers={0:1}, fences={})

    model = CoverageModel(grid_model, params, deployment, visibility)

    patrol_cov = model.calculate_patrol_coverage(sol)[0]
    drone_cov = model.calculate_drone_coverage(sol)[0]

    expected_synergy = params.alpha_pd * (patrol_cov * drone_cov) / (1 + patrol_cov + drone_cov)

    prot_effect = model.calculate_protection_effect(sol)
    base = params.wp * patrol_cov + params.wd * drone_cov
    actual_synergy = prot_effect[0] - base

    print(f"Patrol coverage: {patrol_cov:.6f}")
    print(f"Drone coverage:  {drone_cov:.6f}")
    print(f"Expected synergy: {expected_synergy:.6f}")
    print(f"Actual synergy:   {actual_synergy:.6f}")
    print(f"Match: {abs(actual_synergy - expected_synergy) < 1e-6}")

    assert abs(actual_synergy - expected_synergy) < 1e-6, "Synergy mismatch!"
    print("✓ Integration test passed")

if __name__ == '__main__':
    main()
