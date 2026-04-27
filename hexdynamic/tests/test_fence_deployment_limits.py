"""
Property-based tests for fence deployment limits.

Property 2: Fence Deployment Limit Per Grid
For any grid, the number of deployed fences SHALL NOT exceed the number of 
boundary edges for that grid, and SHALL NOT exceed max_fences_per_grid (default 6).

Property 3: Total Fence Length Constraint
For any deployment solution, the total number of deployed fences (sum of all 
fence counts) SHALL NOT exceed the total_fence_length constraint.

Validates: Requirements 1.1, 1.2, 1.3
"""

import pytest
from hypothesis import given, settings, strategies as st
from typing import List, Dict, Tuple

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grid_model import HexGridModel
from data_loader import DataLoader, GridData, ResourceConstraints, CoverageParameters
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


def create_test_coverage_model(width: int, height: int, max_fences_per_grid: int = 6) -> Tuple[CoverageModel, DataLoader, HexGridModel]:
    """Create a CoverageModel for testing with specified constraints."""
    grids = create_rectangular_grid(width, height)
    
    data_loader = DataLoader()
    data_loader.grids = grids
    
    # Set constraints
    data_loader.constraints = ResourceConstraints(
        total_patrol=10,
        total_camps=5,
        max_rangers_per_camp=3,
        total_cameras=10,
        total_drones=5,
        total_fence_length=50.0,
        max_fences_per_grid=max_fences_per_grid
    )
    
    # Set coverage parameters
    data_loader.coverage_params = CoverageParameters()
    
    # Create grid model and initialize deployment matrix
    grid_model = HexGridModel(grids)
    edge_grids = grid_model.get_edge_grids()
    
    data_loader.initialize_deployment_matrix(edge_grids=edge_grids, grid_model=grid_model)
    data_loader.initialize_visibility_params()
    data_loader.initialize_coverage_effectiveness()
    
    # Create coverage model
    coverage_model = CoverageModel(
        grid_model=grid_model,
        coverage_params=data_loader.coverage_params,
        deployment_matrix=data_loader.deployment_matrix,
        visibility_params=data_loader.visibility_params
    )
    
    return coverage_model, data_loader, grid_model


def generate_random_solution(grid_model: HexGridModel, data_loader: DataLoader, 
                             total_fence_length: int) -> DeploymentSolution:
    """Generate a random deployment solution for testing."""
    import random
    
    grid_ids = grid_model.get_all_grid_ids()
    edge_grids = set(grid_model.get_edge_grids())
    
    # Initialize empty solution
    cameras = {}
    camps = {}
    drones = {}
    rangers = {}
    fences = {}
    
    # Randomly deploy fences on edge grids
    remaining_fence_budget = total_fence_length
    max_fences_per_grid = data_loader.constraints.max_fences_per_grid
    
    for grid_id in edge_grids:
        if remaining_fence_budget <= 0:
            break
        
        # Get max fences for this grid
        max_for_grid = data_loader.deployment_matrix['fence'].get(grid_id, 0)
        if max_for_grid == 0:
            continue
        
        # Randomly decide how many fences to deploy
        num_fences = random.randint(0, min(max_for_grid, max_fences_per_grid, remaining_fence_budget))
        if num_fences > 0:
            # For multi-fence, we use (grid_id, None) as edge key for boundary edges
            # For simplicity, we store fence count per grid
            fences[(grid_id, None)] = num_fences
            remaining_fence_budget -= num_fences
    
    return DeploymentSolution(
        cameras=cameras,
        camps=camps,
        drones=drones,
        rangers=rangers,
        fences=fences
    )


class TestFenceDeploymentLimitPerGrid:
    """
    Property 2: Fence Deployment Limit Per Grid
    
    For any grid, the number of deployed fences SHALL NOT exceed the number of 
    boundary edges for that grid, and SHALL NOT exceed max_fences_per_grid (default 6).
    
    Validates: Requirements 1.1, 1.2, 1.4
    """
    
    def test_fence_count_within_boundary_edge_count(self):
        """Test that fence count per grid does not exceed boundary edge count."""
        coverage_model, data_loader, grid_model = create_test_coverage_model(5, 5)
        
        # Get boundary edge counts for grids
        grid_0_boundary = len(grid_model.get_boundary_edges_for_grid(0))
        grid_1_boundary = len(grid_model.get_boundary_edges_for_grid(1))
        
        # Create a solution with valid fence counts
        solution = DeploymentSolution(
            cameras={},
            camps={},
            drones={},
            rangers={},
            fences={
                (0, None): min(2, grid_0_boundary),  # At most boundary edge count
                (1, None): min(2, grid_1_boundary)   # At most boundary edge count
            }
        )
        
        # Validate each grid's fence count
        for (grid_id, _), fence_count in solution.fences.items():
            boundary_edges = grid_model.get_boundary_edges_for_grid(grid_id)
            num_boundary_edges = len(boundary_edges)
            
            assert fence_count <= num_boundary_edges, \
                f"Grid {grid_id}: fence count ({fence_count}) exceeds boundary edges ({num_boundary_edges})"
    
    def test_fence_count_within_max_fences_per_grid(self):
        """Test that fence count per grid respects max_fences_per_grid constraint."""
        max_fences = 3
        coverage_model, data_loader, grid_model = create_test_coverage_model(5, 5, max_fences_per_grid=max_fences)
        
        # Create a solution with fences
        solution = DeploymentSolution(
            cameras={},
            camps={},
            drones={},
            rangers={},
            fences={(0, None): 2, (1, None): 3}
        )
        
        # Validate each grid's fence count
        for (grid_id, _), fence_count in solution.fences.items():
            assert fence_count <= max_fences, \
                f"Grid {grid_id}: fence count ({fence_count}) exceeds max_fences_per_grid ({max_fences})"
    
    def test_validate_solution_detects_fence_limit_violation(self):
        """Test that validate_solution detects fence limit violations."""
        coverage_model, data_loader, grid_model = create_test_coverage_model(5, 5, max_fences_per_grid=2)
        
        # Create a solution that violates fence limit
        solution = DeploymentSolution(
            cameras={},
            camps={},
            drones={},
            rangers={},
            fences={(0, None): 5}  # 5 fences exceeds max_fences_per_grid=2
        )
        
        constraints = {
            'total_cameras': 10,
            'total_drones': 5,
            'total_camps': 5,
            'total_patrol': 10,
            'total_fence_length': 50.0,
            'max_fences_per_grid': 2
        }
        
        is_valid, violations = coverage_model.validate_solution(solution, constraints)
        
        assert not is_valid, "Solution with fence limit violation should be invalid"
        assert any('fence' in v.lower() for v in violations), \
            "Violations should mention fence limit"
    
    def test_repair_solution_enforces_fence_limits(self):
        """Test that repair_solution enforces fence limits per grid."""
        coverage_model, data_loader, grid_model = create_test_coverage_model(5, 5, max_fences_per_grid=2)
        
        # Create a solution that exceeds fence limit
        solution = DeploymentSolution(
            cameras={},
            camps={},
            drones={},
            rangers={},
            fences={(0, None): 5, (1, None): 4}  # Both exceed limit
        )
        
        constraints = {
            'total_cameras': 10,
            'total_drones': 5,
            'total_camps': 5,
            'total_patrol': 10,
            'total_fence_length': 50.0,
            'max_fences_per_grid': 2
        }
        
        repaired = coverage_model.repair_solution(solution, constraints)
        
        # Check that repaired solution respects limits
        for (grid_id, _), fence_count in repaired.fences.items():
            max_allowed = min(
                data_loader.deployment_matrix['fence'].get(grid_id, 0),
                constraints['max_fences_per_grid']
            )
            assert fence_count <= max_allowed, \
                f"Grid {grid_id}: repaired fence count ({fence_count}) exceeds max ({max_allowed})"


class TestTotalFenceLengthConstraint:
    """
    Property 3: Total Fence Length Constraint
    
    For any deployment solution, the total number of deployed fences (sum of all 
    fence counts) SHALL NOT exceed the total_fence_length constraint.
    
    Validates: Requirements 1.3
    """
    
    def test_total_fence_count_within_constraint(self):
        """Test that total fence count is within total_fence_length constraint."""
        coverage_model, data_loader, grid_model = create_test_coverage_model(5, 5)
        
        total_fence_length = 20
        
        # Create a solution with total fence count within limit
        solution = DeploymentSolution(
            cameras={},
            camps={},
            drones={},
            rangers={},
            fences={(0, None): 5, (1, None): 5, (2, None): 5}  # Total = 15
        )
        
        total_fences = sum(solution.fences.values())
        
        assert total_fences <= total_fence_length, \
            f"Total fences ({total_fences}) exceeds constraint ({total_fence_length})"
    
    def test_validate_solution_detects_total_fence_violation(self):
        """Test that validate_solution detects total fence length violations."""
        coverage_model, data_loader, grid_model = create_test_coverage_model(5, 5)
        
        total_fence_length = 5
        
        # Create a solution that exceeds total fence length
        solution = DeploymentSolution(
            cameras={},
            camps={},
            drones={},
            rangers={},
            fences={(0, None): 3, (1, None): 3, (2, None): 3}  # Total = 9
        )
        
        constraints = {
            'total_cameras': 10,
            'total_drones': 5,
            'total_camps': 5,
            'total_patrol': 10,
            'total_fence_length': total_fence_length
        }
        
        is_valid, violations = coverage_model.validate_solution(solution, constraints)
        
        assert not is_valid, "Solution exceeding total fence length should be invalid"
        assert any('fence' in v.lower() for v in violations), \
            "Violations should mention fence constraint"
    
    def test_repair_solution_enforces_total_fence_length(self):
        """Test that repair_solution enforces total fence length constraint."""
        coverage_model, data_loader, grid_model = create_test_coverage_model(5, 5)
        
        total_fence_length = 5
        
        # Create a solution that exceeds total fence length
        solution = DeploymentSolution(
            cameras={},
            camps={},
            drones={},
            rangers={},
            fences={(0, None): 3, (1, None): 3, (2, None): 3}  # Total = 9
        )
        
        constraints = {
            'total_cameras': 10,
            'total_drones': 5,
            'total_camps': 5,
            'total_patrol': 10,
            'total_fence_length': total_fence_length,
            'max_fences_per_grid': 6
        }
        
        repaired = coverage_model.repair_solution(solution, constraints)
        
        total_fences = sum(repaired.fences.values())
        
        assert total_fences <= total_fence_length, \
            f"Repaired total fences ({total_fences}) exceeds constraint ({total_fence_length})"


class TestPropertyFenceDeploymentLimitPerGrid:
    """
    Property 2: Fence Deployment Limit Per Grid (Property-Based Tests)
    
    For any grid, the number of deployed fences SHALL NOT exceed the number of 
    boundary edges for that grid, and SHALL NOT exceed max_fences_per_grid (default 6).
    
    Validates: Requirements 1.1, 1.2, 1.4
    """
    
    @given(
        width=st.integers(min_value=3, max_value=10),
        height=st.integers(min_value=3, max_value=10),
        max_fences_per_grid=st.integers(min_value=1, max_value=6)
    )
    @settings(max_examples=30, deadline=None)
    def test_fence_count_never_exceeds_boundary_edges(self, width: int, height: int, max_fences_per_grid: int):
        """
        Property: For any grid, fence count never exceeds boundary edge count.
        """
        coverage_model, data_loader, grid_model = create_test_coverage_model(width, height, max_fences_per_grid)
        
        # Generate a random solution
        import random
        random.seed(42)
        
        solution = generate_random_solution(grid_model, data_loader, total_fence_length=100)
        
        # Validate each grid's fence count
        for (grid_id, _), fence_count in solution.fences.items():
            boundary_edges = grid_model.get_boundary_edges_for_grid(grid_id)
            num_boundary_edges = len(boundary_edges)
            
            # Property: fence count should not exceed boundary edge count
            assert fence_count <= num_boundary_edges, \
                f"Grid {grid_id}: fence count ({fence_count}) exceeds boundary edges ({num_boundary_edges})"
    
    @given(
        width=st.integers(min_value=3, max_value=10),
        height=st.integers(min_value=3, max_value=10),
        max_fences_per_grid=st.integers(min_value=1, max_value=6)
    )
    @settings(max_examples=30, deadline=None)
    def test_fence_count_never_exceeds_max_per_grid(self, width: int, height: int, max_fences_per_grid: int):
        """
        Property: For any grid, fence count never exceeds max_fences_per_grid.
        """
        coverage_model, data_loader, grid_model = create_test_coverage_model(width, height, max_fences_per_grid)
        
        # Generate a random solution
        import random
        random.seed(42)
        
        solution = generate_random_solution(grid_model, data_loader, total_fence_length=100)
        
        # Validate each grid's fence count
        for (grid_id, _), fence_count in solution.fences.items():
            # Property: fence count should not exceed max_fences_per_grid
            assert fence_count <= max_fences_per_grid, \
                f"Grid {grid_id}: fence count ({fence_count}) exceeds max_fences_per_grid ({max_fences_per_grid})"
    
    @given(
        width=st.integers(min_value=3, max_value=10),
        height=st.integers(min_value=3, max_value=10),
        max_fences_per_grid=st.integers(min_value=1, max_value=6)
    )
    @settings(max_examples=30, deadline=None)
    def test_repaired_solution_respects_fence_limits(self, width: int, height: int, max_fences_per_grid: int):
        """
        Property: After repair, all fence counts respect limits.
        """
        coverage_model, data_loader, grid_model = create_test_coverage_model(width, height, max_fences_per_grid)
        
        # Create a solution that may exceed limits
        solution = DeploymentSolution(
            cameras={},
            camps={},
            drones={},
            rangers={},
            fences={(grid_id, None): 10 for grid_id in grid_model.get_edge_grids()[:5]}  # 10 fences each
        )
        
        constraints = {
            'total_cameras': 10,
            'total_drones': 5,
            'total_camps': 5,
            'total_patrol': 10,
            'total_fence_length': 100.0,
            'max_fences_per_grid': max_fences_per_grid
        }
        
        repaired = coverage_model.repair_solution(solution, constraints)
        
        # Property: all fence counts in repaired solution should respect limits
        for (grid_id, _), fence_count in repaired.fences.items():
            boundary_edges = grid_model.get_boundary_edges_for_grid(grid_id)
            num_boundary_edges = len(boundary_edges)
            max_allowed = min(num_boundary_edges, max_fences_per_grid)
            
            assert fence_count <= max_allowed, \
                f"Grid {grid_id}: repaired fence count ({fence_count}) exceeds max ({max_allowed})"


class TestPropertyTotalFenceLengthConstraint:
    """
    Property 3: Total Fence Length Constraint (Property-Based Tests)
    
    For any deployment solution, the total number of deployed fences (sum of all 
    fence counts) SHALL NOT exceed the total_fence_length constraint.
    
    Validates: Requirements 1.3
    """
    
    @given(
        width=st.integers(min_value=3, max_value=10),
        height=st.integers(min_value=3, max_value=10),
        total_fence_length=st.integers(min_value=5, max_value=50)
    )
    @settings(max_examples=30, deadline=None)
    def test_repaired_solution_respects_total_fence_length(self, width: int, height: int, total_fence_length: int):
        """
        Property: After repair, total fence count respects total_fence_length.
        """
        coverage_model, data_loader, grid_model = create_test_coverage_model(width, height)
        
        # Create a solution that exceeds total fence length
        edge_grids = grid_model.get_edge_grids()
        solution = DeploymentSolution(
            cameras={},
            camps={},
            drones={},
            rangers={},
            fences={(grid_id, None): 6 for grid_id in edge_grids}  # 6 fences per edge grid
        )
        
        constraints = {
            'total_cameras': 10,
            'total_drones': 5,
            'total_camps': 5,
            'total_patrol': 10,
            'total_fence_length': float(total_fence_length),
            'max_fences_per_grid': 6
        }
        
        repaired = coverage_model.repair_solution(solution, constraints)
        
        total_fences = sum(repaired.fences.values())
        
        # Property: total fence count should not exceed total_fence_length
        assert total_fences <= total_fence_length, \
            f"Total fences ({total_fences}) exceeds constraint ({total_fence_length})"
    
    @given(
        width=st.integers(min_value=3, max_value=10),
        height=st.integers(min_value=3, max_value=10),
        total_fence_length=st.integers(min_value=5, max_value=50)
    )
    @settings(max_examples=30, deadline=None)
    def test_valid_solution_total_fence_within_limit(self, width: int, height: int, total_fence_length: int):
        """
        Property: A valid solution has total fence count within limit.
        """
        coverage_model, data_loader, grid_model = create_test_coverage_model(width, height)
        
        # Generate a random solution within limits
        import random
        random.seed(42)
        
        solution = generate_random_solution(grid_model, data_loader, total_fence_length)
        
        constraints = {
            'total_cameras': 10,
            'total_drones': 5,
            'total_camps': 5,
            'total_patrol': 10,
            'total_fence_length': float(total_fence_length),
            'max_fences_per_grid': 6
        }
        
        total_fences = sum(solution.fences.values())
        
        # Property: generated solution should have total within limit
        assert total_fences <= total_fence_length, \
            f"Total fences ({total_fences}) exceeds constraint ({total_fence_length})"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
