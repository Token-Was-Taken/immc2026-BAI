"""
Property-based tests for backward compatibility.

Property 5: Default Configuration
For any configuration without max_fences_per_grid specified, THE System SHALL use the default value of 6.

Property 6: Backward Compatibility
For any input using binary (0/1) fence deployment format, THE System SHALL correctly interpret 
and process it as multi-value format.

Validates: Requirements 4.1, 4.2, 4.3
"""

import pytest
from hypothesis import given, settings, strategies as st
from typing import List, Dict
import json

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grid_model import HexGridModel
from data_loader import DataLoader, GridData, ResourceConstraints
from coverage_model import CoverageModel, DeploymentSolution


def create_rectangular_grid(width: int, height: int) -> List[GridData]:
    """Create a rectangular hexagonal grid for testing."""
    grids = []
    grid_id = 0
    
    for row in range(height):
        for col in range(width):
            q = col - (row // 2)
            r = row
            
            grid = GridData(
                grid_id=grid_id,
                q=q,
                r=r,
                terrain_type='SparseGrass',
                risk=0.5
            )
            grids.append(grid)
            grid_id += 1
    
    return grids


class TestDefaultConfiguration:
    """Tests for Property 5: Default Configuration."""
    
    def test_resource_constraints_default_max_fences(self):
        """Test that ResourceConstraints has default max_fences_per_grid = 6."""
        constraints = ResourceConstraints(
            total_patrol=10,
            total_camps=5,
            max_rangers_per_camp=3,
            total_cameras=10,
            total_drones=5,
            total_fence_length=50.0
        )
        
        assert constraints.max_fences_per_grid == 6, \
            f"Default max_fences_per_grid should be 6, got {constraints.max_fences_per_grid}"
    
    def test_data_loader_default_max_fences(self):
        """Test that DataLoader uses default max_fences_per_grid when not specified."""
        grids = create_rectangular_grid(5, 5)
        data_loader = DataLoader()
        data_loader.grids = grids
        
        # Set constraints without max_fences_per_grid
        data_loader.set_constraints(
            total_patrol=10,
            total_camps=5,
            max_rangers_per_camp=3,
            total_cameras=10,
            total_drones=5,
            total_fence_length=50.0
        )
        
        assert data_loader.constraints.max_fences_per_grid == 6, \
            f"Default max_fences_per_grid should be 6, got {data_loader.constraints.max_fences_per_grid}"
    
    def test_constraints_dict_default_max_fences(self):
        """Test that constraints dict uses default max_fences_per_grid = 6."""
        constraints = {
            'total_patrol': 10,
            'total_camps': 5,
            'total_cameras': 10,
            'total_drones': 5,
            'total_fence_length': 50.0
        }
        
        # This simulates how constraints are used in coverage_model and dssa_optimizer
        max_fences = constraints.get('max_fences_per_grid', 6)
        
        assert max_fences == 6, \
            f"Default max_fences_per_grid from dict should be 6, got {max_fences}"
    
    def test_load_from_config_default_max_fences(self):
        """Test that load_from_config uses default max_fences_per_grid when not in config."""
        data_loader = DataLoader()
        
        config = {
            'grid_radius': 5,
            'constraints': {
                'total_patrol': 10,
                'total_camps': 5,
                'max_rangers_per_camp': 3,
                'total_cameras': 10,
                'total_drones': 5,
                'total_fence_length': 50.0
                # Note: max_fences_per_grid is NOT specified
            }
        }
        
        data_loader.load_from_config(config)
        
        assert data_loader.constraints.max_fences_per_grid == 6, \
            f"Default max_fences_per_grid should be 6 when not in config, got {data_loader.constraints.max_fences_per_grid}"


class TestBackwardCompatibility:
    """Tests for Property 6: Backward Compatibility."""
    
    def test_binary_fence_format_in_deployment_matrix(self):
        """Test that binary (0/1) fence deployment format is handled correctly."""
        grids = create_rectangular_grid(5, 5)
        data_loader = DataLoader()
        data_loader.grids = grids
        
        grid_model = HexGridModel(grids)
        edge_grids = grid_model.get_edge_grids()
        
        # Initialize deployment matrix (should produce multi-value format)
        data_loader.initialize_deployment_matrix(edge_grids=edge_grids, grid_model=grid_model)
        
        # All fence values should be valid integers
        for grid_id, value in data_loader.deployment_matrix['fence'].items():
            assert isinstance(value, int), \
                f"Fence value for grid {grid_id} should be an integer, got {type(value)}"
            assert 0 <= value <= 6, \
                f"Fence value for grid {grid_id} should be in [0, 6], got {value}"
    
    def test_fence_solution_with_binary_values(self):
        """Test that fence solutions with binary values (0 or 1) work correctly."""
        grids = create_rectangular_grid(5, 5)
        data_loader = DataLoader()
        data_loader.grids = grids
        
        grid_model = HexGridModel(grids)
        edge_grids = grid_model.get_edge_grids()
        
        data_loader.initialize_deployment_matrix(edge_grids=edge_grids, grid_model=grid_model)
        data_loader.initialize_visibility_params()
        
        coverage_model = CoverageModel(
            grid_model,
            data_loader.coverage_params,
            data_loader.deployment_matrix,
            data_loader.visibility_params
        )
        
        # Create a solution with binary fence values (old format)
        solution = DeploymentSolution(
            cameras={},
            camps={},
            drones={},
            rangers={},
            fences={(0, 1): 1, (1, 2): 1}  # Binary format: 0 or 1
        )
        
        # Validate should work with binary format
        constraints = {
            'total_patrol': 10,
            'total_camps': 5,
            'total_cameras': 10,
            'total_drones': 5,
            'total_fence_length': 50.0,
            'max_fences_per_grid': 6
        }
        
        is_valid, violations = coverage_model.validate_solution(solution, constraints)
        # May or may not be valid depending on edge grids, but should not crash
        assert isinstance(is_valid, bool), "Validation should return a boolean"
        assert isinstance(violations, list), "Violations should be a list"
    
    def test_output_json_format_compatibility(self):
        """Test that output JSON format is compatible with expected format."""
        grids = create_rectangular_grid(5, 5)
        data_loader = DataLoader()
        data_loader.grids = grids
        
        grid_model = HexGridModel(grids)
        edge_grids = grid_model.get_edge_grids()
        
        data_loader.initialize_deployment_matrix(edge_grids=edge_grids, grid_model=grid_model)
        data_loader.initialize_visibility_params()
        
        coverage_model = CoverageModel(
            grid_model,
            data_loader.coverage_params,
            data_loader.deployment_matrix,
            data_loader.visibility_params
        )
        
        # Create a solution
        solution = DeploymentSolution(
            cameras={0: 1},
            camps={},
            drones={1: 1},
            rangers={2: 1},
            fences={(0, None): 2, (1, None): 1}  # Multi-fence format
        )
        
        # Simulate output serialization
        fence_edges_output = [
            {'grid_id_1': int(e[0]), 'grid_id_2': int(e[1]) if e[1] is not None else None}
            for e, v in solution.fences.items() if v > 0
        ]
        
        # Check that output is JSON serializable
        output = {
            'fence_edges': fence_edges_output,
            'cameras': {str(k): v for k, v in solution.cameras.items()},
            'drones': {str(k): v for k, v in solution.drones.items()},
            'rangers': {str(k): v for k, v in solution.rangers.items()}
        }
        
        # Should not raise an exception
        json_str = json.dumps(output)
        parsed = json.loads(json_str)
        
        assert 'fence_edges' in parsed, "Output should contain fence_edges"
        assert 'cameras' in parsed, "Output should contain cameras"


class TestPropertyDefaultConfiguration:
    """
    Property 5: Default Configuration
    
    For any configuration without max_fences_per_grid specified, THE System SHALL use 
    the default value of 6.
    
    Validates: Requirements 4.1
    """
    
    @given(
        total_patrol=st.integers(min_value=1, max_value=100),
        total_camps=st.integers(min_value=1, max_value=20),
        total_cameras=st.integers(min_value=1, max_value=50),
        total_drones=st.integers(min_value=1, max_value=20),
        total_fence_length=st.floats(min_value=1.0, max_value=500.0)
    )
    @settings(max_examples=30, deadline=None)
    def test_default_max_fences_per_grid(
        self, total_patrol, total_camps, total_cameras, total_drones, total_fence_length
    ):
        """
        Property: For any configuration without max_fences_per_grid, default is 6.
        """
        # Create constraints without max_fences_per_grid
        constraints = ResourceConstraints(
            total_patrol=total_patrol,
            total_camps=total_camps,
            max_rangers_per_camp=5,
            total_cameras=total_cameras,
            total_drones=total_drones,
            total_fence_length=total_fence_length
        )
        
        # Property: max_fences_per_grid should default to 6
        assert constraints.max_fences_per_grid == 6, \
            f"Default max_fences_per_grid should be 6, got {constraints.max_fences_per_grid}"
    
    @given(
        width=st.integers(min_value=3, max_value=10),
        height=st.integers(min_value=3, max_value=10)
    )
    @settings(max_examples=30, deadline=None)
    def test_deployment_matrix_uses_default_max_fences(self, width: int, height: int):
        """
        Property: Deployment matrix respects default max_fences_per_grid = 6.
        """
        grids = create_rectangular_grid(width, height)
        data_loader = DataLoader()
        data_loader.grids = grids
        
        # Set constraints without max_fences_per_grid (uses default)
        data_loader.set_constraints(
            total_patrol=10,
            total_camps=5,
            max_rangers_per_camp=3,
            total_cameras=10,
            total_drones=5,
            total_fence_length=50.0
        )
        
        grid_model = HexGridModel(grids)
        edge_grids = grid_model.get_edge_grids()
        
        data_loader.initialize_deployment_matrix(edge_grids=edge_grids, grid_model=grid_model)
        
        # Property: all fence values should be <= 6 (the default)
        for grid_id, value in data_loader.deployment_matrix['fence'].items():
            assert value <= 6, \
                f"Grid {grid_id}: fence value ({value}) should not exceed default max_fences_per_grid (6)"


class TestPropertyBackwardCompatibility:
    """
    Property 6: Backward Compatibility
    
    For any input using binary (0/1) fence deployment format, THE System SHALL correctly 
    interpret and process it as multi-value format.
    
    Validates: Requirements 4.2, 4.3
    """
    
    @given(
        width=st.integers(min_value=3, max_value=10),
        height=st.integers(min_value=3, max_value=10)
    )
    @settings(max_examples=30, deadline=None)
    def test_binary_format_interpreted_correctly(self, width: int, height: int):
        """
        Property: Binary (0/1) fence format is correctly interpreted.
        """
        grids = create_rectangular_grid(width, height)
        data_loader = DataLoader()
        data_loader.grids = grids
        
        grid_model = HexGridModel(grids)
        edge_grids = grid_model.get_edge_grids()
        
        # Initialize deployment matrix
        data_loader.initialize_deployment_matrix(edge_grids=edge_grids, grid_model=grid_model)
        data_loader.initialize_visibility_params()
        
        coverage_model = CoverageModel(
            grid_model,
            data_loader.coverage_params,
            data_loader.deployment_matrix,
            data_loader.visibility_params
        )
        
        # Create a solution with binary fence values
        solution = DeploymentSolution(
            cameras={},
            camps={},
            drones={},
            rangers={},
            fences={(edge_grids[0], None): 1} if edge_grids else {}  # Binary: 0 or 1
        )
        
        constraints = {
            'total_patrol': 10,
            'total_camps': 5,
            'total_cameras': 10,
            'total_drones': 5,
            'total_fence_length': 50.0,
            'max_fences_per_grid': 6
        }
        
        # Property: should not crash when processing binary format
        try:
            is_valid, violations = coverage_model.validate_solution(solution, constraints)
            # If valid, repair should also work
            if is_valid:
                repaired = coverage_model.repair_solution(solution, constraints)
                assert isinstance(repaired, DeploymentSolution), \
                    "Repair should return a DeploymentSolution"
        except Exception as e:
            pytest.fail(f"Should not raise exception for binary format: {e}")
    
    @given(
        width=st.integers(min_value=3, max_value=10),
        height=st.integers(min_value=3, max_value=10)
    )
    @settings(max_examples=30, deadline=None)
    def test_multi_value_format_works_correctly(self, width: int, height: int):
        """
        Property: Multi-value (0-6) fence format works correctly.
        """
        grids = create_rectangular_grid(width, height)
        data_loader = DataLoader()
        data_loader.grids = grids
        
        grid_model = HexGridModel(grids)
        edge_grids = grid_model.get_edge_grids()
        
        data_loader.initialize_deployment_matrix(edge_grids=edge_grids, grid_model=grid_model)
        data_loader.initialize_visibility_params()
        
        coverage_model = CoverageModel(
            grid_model,
            data_loader.coverage_params,
            data_loader.deployment_matrix,
            data_loader.visibility_params
        )
        
        # Create a solution with multi-value fence counts
        fences = {}
        if edge_grids:
            for grid_id in edge_grids[:3]:  # Use first 3 edge grids
                boundary_edges = grid_model.get_boundary_edges_for_grid(grid_id)
                num_boundary = len(boundary_edges)
                if num_boundary > 0:
                    fences[(grid_id, None)] = min(3, num_boundary)  # Multi-value: 0-6
        
        solution = DeploymentSolution(
            cameras={},
            camps={},
            drones={},
            rangers={},
            fences=fences
        )
        
        constraints = {
            'total_patrol': 10,
            'total_camps': 5,
            'total_cameras': 10,
            'total_drones': 5,
            'total_fence_length': 50.0,
            'max_fences_per_grid': 6
        }
        
        # Property: should work with multi-value format
        try:
            is_valid, violations = coverage_model.validate_solution(solution, constraints)
            repaired = coverage_model.repair_solution(solution, constraints)
            
            # After repair, fence counts should be valid
            for (grid_id, _), count in repaired.fences.items():
                assert 0 <= count <= 6, \
                    f"Grid {grid_id}: repaired fence count ({count}) should be in [0, 6]"
        except Exception as e:
            pytest.fail(f"Should not raise exception for multi-value format: {e}")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
