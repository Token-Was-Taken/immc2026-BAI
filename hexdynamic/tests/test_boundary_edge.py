"""
Property-based tests for boundary edge identification.

Property 1: Boundary Edge Count Consistency
For any edge grid, the number of boundary edges SHALL equal the number of 
hexagonal directions where no neighbor exists in the grid set.

Validates: Requirements 2.1, 2.2, 2.3
"""

import pytest
from hypothesis import given, settings, strategies as st
from typing import List

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grid_model import HexGridModel
from data_loader import GridData


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


def create_irregular_grid(num_grids: int, seed: int) -> List[GridData]:
    """Create an irregular grid shape for testing."""
    import random
    random.seed(seed)
    
    grids = []
    grid_set = set()
    
    # Start with a center grid
    center_q, center_r = 0, 0
    grid_set.add((center_q, center_r))
    
    # Add grids in random directions
    directions = [
        (1, 0), (1, -1), (0, -1),
        (-1, 0), (-1, 1), (0, 1)
    ]
    
    while len(grid_set) < num_grids:
        q, r = random.choice(list(grid_set))
        dq, dr = random.choice(directions)
        new_pos = (q + dq, r + dr)
        if new_pos not in grid_set:
            grid_set.add(new_pos)
    
    # Create GridData objects
    for grid_id, (q, r) in enumerate(sorted(grid_set)):
        grid = GridData(
            grid_id=grid_id,
            q=q,
            r=r,
            terrain_type='SparseGrass',
            risk=0.5
        )
        grids.append(grid)
    
    return grids


class TestBoundaryEdgeIdentification:
    """Tests for boundary edge identification methods."""
    
    def test_get_boundary_edges_for_grid_corner_grid(self):
        """Test boundary edges for a corner grid in a rectangular map."""
        grids = create_rectangular_grid(5, 5)
        model = HexGridModel(grids)
        
        # Grid at (0, 0) should have boundary edges
        # In a rectangular hexagonal grid, corner grids can have 2-4 boundary edges
        # depending on the grid shape and position
        boundary_edges = model.get_boundary_edges_for_grid(0)
        
        assert len(boundary_edges) > 0, "Corner grid should have boundary edges"
        assert len(boundary_edges) <= 6, "Corner grid should have at most 6 boundary edges"
    
    def test_get_boundary_edges_for_grid_interior_grid(self):
        """Test boundary edges for an interior grid."""
        grids = create_rectangular_grid(10, 10)
        model = HexGridModel(grids)
        
        # Find an interior grid (not on the edge)
        edge_grids = set(model.get_edge_grids())
        all_grids = set(model.get_all_grid_ids())
        interior_grids = all_grids - edge_grids
        
        if interior_grids:
            interior_grid_id = min(interior_grids)
            boundary_edges = model.get_boundary_edges_for_grid(interior_grid_id)
            
            assert len(boundary_edges) == 0, "Interior grid should have no boundary edges"
    
    def test_get_all_boundary_edges_returns_all(self):
        """Test that get_all_boundary_edges returns all boundary edges."""
        grids = create_rectangular_grid(5, 5)
        model = HexGridModel(grids)
        
        all_boundary_edges = model.get_all_boundary_edges()
        
        # Verify each edge grid has its boundary edges included
        edge_grids = model.get_edge_grids()
        edge_grids_in_result = set(edge_id for edge_id, _, _ in all_boundary_edges)
        
        for grid_id in edge_grids:
            grid_boundary = model.get_boundary_edges_for_grid(grid_id)
            if grid_boundary:  # Only if grid has boundary edges
                assert grid_id in edge_grids_in_result, \
                    f"Edge grid {grid_id} should be in boundary edges result"
    
    def test_get_fencing_edges_includes_boundary_edges(self):
        """Test that get_fencing_edges includes boundary edges."""
        grids = create_rectangular_grid(5, 5)
        model = HexGridModel(grids)
        
        fencing_edges = model.get_fencing_edges()
        
        # Check that boundary edges are included (type 2.0)
        boundary_edges_in_fencing = [e for e in fencing_edges if e[2] == 2.0]
        
        assert len(boundary_edges_in_fencing) > 0, \
            "Fencing edges should include boundary edges (type 2.0)"
    
    def test_get_fencing_edges_includes_internal_edges(self):
        """Test that get_fencing_edges includes internal edges."""
        grids = create_rectangular_grid(5, 5)
        model = HexGridModel(grids)
        
        fencing_edges = model.get_fencing_edges()
        
        # Check that internal edges are included (type 1.0)
        internal_edges_in_fencing = [e for e in fencing_edges if e[2] == 1.0]
        
        assert len(internal_edges_in_fencing) > 0, \
            "Fencing edges should include internal edges (type 1.0)"


class TestPropertyBoundaryEdgeCountConsistency:
    """
    Property 1: Boundary Edge Count Consistency
    
    For any edge grid, the number of boundary edges SHALL equal the number of 
    hexagonal directions where no neighbor exists in the grid set.
    
    Validates: Requirements 2.1, 2.2, 2.3
    """
    
    @given(
        width=st.integers(min_value=3, max_value=15),
        height=st.integers(min_value=3, max_value=15)
    )
    @settings(max_examples=50, deadline=None)
    def test_boundary_edge_count_consistency_rectangular(self, width: int, height: int):
        """
        Property: For any grid, boundary edge count equals missing neighbor count.
        Test with rectangular grids of various sizes.
        """
        grids = create_rectangular_grid(width, height)
        model = HexGridModel(grids)
        
        # Hexagonal directions
        directions = [
            (1, 0), (1, -1), (0, -1),
            (-1, 0), (-1, 1), (0, 1)
        ]
        
        for grid_id in model.get_all_grid_ids():
            grid = model.get_grid_by_id(grid_id)
            boundary_edges = model.get_boundary_edges_for_grid(grid_id)
            
            # Count missing neighbors manually
            missing_neighbors = 0
            for dq, dr in directions:
                neighbor_q = grid.q + dq
                neighbor_r = grid.r + dr
                neighbor = model._find_grid_by_coords(neighbor_q, neighbor_r)
                if neighbor is None:
                    missing_neighbors += 1
            
            # Property: boundary edge count should equal missing neighbor count
            assert len(boundary_edges) == missing_neighbors, \
                f"Grid {grid_id}: boundary edges ({len(boundary_edges)}) " \
                f"should equal missing neighbors ({missing_neighbors})"
    
    @given(
        num_grids=st.integers(min_value=10, max_value=100),
        seed=st.integers(min_value=0, max_value=10000)
    )
    @settings(max_examples=30, deadline=None)
    def test_boundary_edge_count_consistency_irregular(self, num_grids: int, seed: int):
        """
        Property: For any grid, boundary edge count equals missing neighbor count.
        Test with irregular grid shapes.
        """
        grids = create_irregular_grid(num_grids, seed)
        model = HexGridModel(grids)
        
        # Hexagonal directions
        directions = [
            (1, 0), (1, -1), (0, -1),
            (-1, 0), (-1, 1), (0, 1)
        ]
        
        for grid_id in model.get_all_grid_ids():
            grid = model.get_grid_by_id(grid_id)
            boundary_edges = model.get_boundary_edges_for_grid(grid_id)
            
            # Count missing neighbors manually
            missing_neighbors = 0
            for dq, dr in directions:
                neighbor_q = grid.q + dq
                neighbor_r = grid.r + dr
                neighbor = model._find_grid_by_coords(neighbor_q, neighbor_r)
                if neighbor is None:
                    missing_neighbors += 1
            
            # Property: boundary edge count should equal missing neighbor count
            assert len(boundary_edges) == missing_neighbors, \
                f"Grid {grid_id}: boundary edges ({len(boundary_edges)}) " \
                f"should equal missing neighbors ({missing_neighbors})"
    
    @given(
        width=st.integers(min_value=3, max_value=10),
        height=st.integers(min_value=3, max_value=10)
    )
    @settings(max_examples=30, deadline=None)
    def test_boundary_edge_direction_validity(self, width: int, height: int):
        """
        Property: All boundary edge directions are valid (0-5).
        """
        grids = create_rectangular_grid(width, height)
        model = HexGridModel(grids)
        
        for grid_id in model.get_all_grid_ids():
            boundary_edges = model.get_boundary_edges_for_grid(grid_id)
            
            for _, direction in boundary_edges:
                assert 0 <= direction <= 5, \
                    f"Direction {direction} is not valid (must be 0-5)"
    
    @given(
        width=st.integers(min_value=3, max_value=10),
        height=st.integers(min_value=3, max_value=10)
    )
    @settings(max_examples=30, deadline=None)
    def test_boundary_edge_count_at_most_six(self, width: int, height: int):
        """
        Property: No grid can have more than 6 boundary edges.
        """
        grids = create_rectangular_grid(width, height)
        model = HexGridModel(grids)
        
        for grid_id in model.get_all_grid_ids():
            boundary_edges = model.get_boundary_edges_for_grid(grid_id)
            
            assert len(boundary_edges) <= 6, \
                f"Grid {grid_id} has {len(boundary_edges)} boundary edges, " \
                f"but maximum is 6 (one per hexagonal side)"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
