"""
Property-based tests for deployment matrix values.

Property 4: Deployment Matrix Value Range
For any grid in the deployment matrix, the fence value SHALL be an integer 
in the range [0, num_boundary_edges], where num_boundary_edges ≤ 6.

Validates: Requirements 1.4
"""

import pytest
from hypothesis import given, settings, strategies as st
from typing import List

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grid_model import HexGridModel
from data_loader import DataLoader, GridData, ResourceConstraints


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


class TestDeploymentMatrixValues:
    """Tests for deployment matrix value range property."""
    
    def test_fence_value_non_negative(self):
        """Test that fence values are non-negative."""
        grids = create_rectangular_grid(5, 5)
        data_loader = DataLoader()
        data_loader.grids = grids
        
        grid_model = HexGridModel(grids)
        edge_grids = grid_model.get_edge_grids()
        
        data_loader.initialize_deployment_matrix(edge_grids=edge_grids, grid_model=grid_model)
        
        for grid_id, value in data_loader.deployment_matrix['fence'].items():
            assert value >= 0, f"Fence value for grid {grid_id} should be non-negative, got {value}"
    
    def test_fence_value_at_most_six(self):
        """Test that fence values are at most 6."""
        grids = create_rectangular_grid(5, 5)
        data_loader = DataLoader()
        data_loader.grids = grids
        
        grid_model = HexGridModel(grids)
        edge_grids = grid_model.get_edge_grids()
        
        data_loader.initialize_deployment_matrix(edge_grids=edge_grids, grid_model=grid_model)
        
        for grid_id, value in data_loader.deployment_matrix['fence'].items():
            assert value <= 6, f"Fence value for grid {grid_id} should be at most 6, got {value}"
    
    def test_fence_value_equals_boundary_edge_count(self):
        """Test that fence value equals boundary edge count for edge grids."""
        grids = create_rectangular_grid(5, 5)
        data_loader = DataLoader()
        data_loader.grids = grids
        
        grid_model = HexGridModel(grids)
        edge_grids = grid_model.get_edge_grids()
        
        data_loader.initialize_deployment_matrix(edge_grids=edge_grids, grid_model=grid_model)
        
        for grid_id in edge_grids:
            boundary_edges = grid_model.get_boundary_edges_for_grid(grid_id)
            expected_value = len(boundary_edges)
            actual_value = data_loader.deployment_matrix['fence'][grid_id]
            
            assert actual_value == expected_value, \
                f"Grid {grid_id}: fence value ({actual_value}) should equal boundary edge count ({expected_value})"
    
    def test_interior_grid_fence_value_zero(self):
        """Test that interior grids have fence value 0."""
        grids = create_rectangular_grid(10, 10)
        data_loader = DataLoader()
        data_loader.grids = grids
        
        grid_model = HexGridModel(grids)
        edge_grids = grid_model.get_edge_grids()
        
        data_loader.initialize_deployment_matrix(edge_grids=edge_grids, grid_model=grid_model)
        
        # Find interior grids
        all_grids = set(grid_model.get_all_grid_ids())
        interior_grids = all_grids - set(edge_grids)
        
        for grid_id in interior_grids:
            value = data_loader.deployment_matrix['fence'][grid_id]
            assert value == 0, f"Interior grid {grid_id} should have fence value 0, got {value}"
    
    def test_fence_value_respects_max_fences_per_grid(self):
        """Test that fence values respect max_fences_per_grid constraint."""
        grids = create_rectangular_grid(5, 5)
        data_loader = DataLoader()
        data_loader.grids = grids
        
        # Set a constraint with max_fences_per_grid = 3
        data_loader.constraints = ResourceConstraints(
            total_patrol=10,
            total_camps=5,
            max_rangers_per_camp=3,
            total_cameras=10,
            total_drones=5,
            total_fence_length=50.0,
            max_fences_per_grid=3
        )
        
        grid_model = HexGridModel(grids)
        edge_grids = grid_model.get_edge_grids()
        
        data_loader.initialize_deployment_matrix(edge_grids=edge_grids, grid_model=grid_model)
        
        for grid_id, value in data_loader.deployment_matrix['fence'].items():
            assert value <= 3, \
                f"Grid {grid_id}: fence value ({value}) should not exceed max_fences_per_grid (3)"


class TestPropertyDeploymentMatrixValueRange:
    """
    Property 4: Deployment Matrix Value Range
    
    For any grid in the deployment matrix, the fence value SHALL be an integer 
    in the range [0, num_boundary_edges], where num_boundary_edges ≤ 6.
    
    Validates: Requirements 1.4
    """
    
    @given(
        width=st.integers(min_value=3, max_value=15),
        height=st.integers(min_value=3, max_value=15)
    )
    @settings(max_examples=50, deadline=None)
    def test_fence_value_in_valid_range(self, width: int, height: int):
        """
        Property: For any grid, fence value is in [0, num_boundary_edges].
        """
        grids = create_rectangular_grid(width, height)
        data_loader = DataLoader()
        data_loader.grids = grids
        
        grid_model = HexGridModel(grids)
        edge_grids = grid_model.get_edge_grids()
        
        data_loader.initialize_deployment_matrix(edge_grids=edge_grids, grid_model=grid_model)
        
        for grid_id in grid_model.get_all_grid_ids():
            boundary_edges = grid_model.get_boundary_edges_for_grid(grid_id)
            num_boundary_edges = len(boundary_edges)
            fence_value = data_loader.deployment_matrix['fence'][grid_id]
            
            # Property: fence value should be in [0, num_boundary_edges]
            assert 0 <= fence_value <= num_boundary_edges, \
                f"Grid {grid_id}: fence value ({fence_value}) should be in [0, {num_boundary_edges}]"
    
    @given(
        width=st.integers(min_value=3, max_value=15),
        height=st.integers(min_value=3, max_value=15),
        max_fences=st.integers(min_value=1, max_value=6)
    )
    @settings(max_examples=50, deadline=None)
    def test_fence_value_respects_constraint(self, width: int, height: int, max_fences: int):
        """
        Property: Fence value respects max_fences_per_grid constraint.
        """
        grids = create_rectangular_grid(width, height)
        data_loader = DataLoader()
        data_loader.grids = grids
        
        # Set constraint
        data_loader.constraints = ResourceConstraints(
            total_patrol=10,
            total_camps=5,
            max_rangers_per_camp=3,
            total_cameras=10,
            total_drones=5,
            total_fence_length=50.0,
            max_fences_per_grid=max_fences
        )
        
        grid_model = HexGridModel(grids)
        edge_grids = grid_model.get_edge_grids()
        
        data_loader.initialize_deployment_matrix(edge_grids=edge_grids, grid_model=grid_model)
        
        for grid_id, value in data_loader.deployment_matrix['fence'].items():
            # Property: fence value should not exceed max_fences_per_grid
            assert value <= max_fences, \
                f"Grid {grid_id}: fence value ({value}) should not exceed max_fences_per_grid ({max_fences})"
    
    @given(
        width=st.integers(min_value=3, max_value=15),
        height=st.integers(min_value=3, max_value=15)
    )
    @settings(max_examples=50, deadline=None)
    def test_fence_value_is_integer(self, width: int, height: int):
        """
        Property: Fence value is always an integer.
        """
        grids = create_rectangular_grid(width, height)
        data_loader = DataLoader()
        data_loader.grids = grids
        
        grid_model = HexGridModel(grids)
        edge_grids = grid_model.get_edge_grids()
        
        data_loader.initialize_deployment_matrix(edge_grids=edge_grids, grid_model=grid_model)
        
        for grid_id, value in data_loader.deployment_matrix['fence'].items():
            assert isinstance(value, int), \
                f"Grid {grid_id}: fence value should be an integer, got {type(value)}"
    
    @given(
        width=st.integers(min_value=3, max_value=15),
        height=st.integers(min_value=3, max_value=15)
    )
    @settings(max_examples=50, deadline=None)
    def test_all_grids_have_fence_entry(self, width: int, height: int):
        """
        Property: Every grid has an entry in the fence deployment matrix.
        """
        grids = create_rectangular_grid(width, height)
        data_loader = DataLoader()
        data_loader.grids = grids
        
        grid_model = HexGridModel(grids)
        edge_grids = grid_model.get_edge_grids()
        
        data_loader.initialize_deployment_matrix(edge_grids=edge_grids, grid_model=grid_model)
        
        all_grid_ids = set(grid_model.get_all_grid_ids())
        fence_grid_ids = set(data_loader.deployment_matrix['fence'].keys())
        
        assert all_grid_ids == fence_grid_ids, \
            "All grids should have an entry in the fence deployment matrix"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
