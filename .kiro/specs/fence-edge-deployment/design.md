# Design Document: Fence Edge Deployment Enhancement

## Overview

This document describes the design for enhancing fence deployment to support multiple fences per edge grid and improved visualization of deployed fence edges.

## Architecture

The changes affect three main components:

1. **Grid Model** (`grid_model.py`) - Add boundary edge identification logic
2. **Coverage Model** (`coverage_model.py`) - Update fence protection calculation for multi-fence edges
3. **Visualization** (`visualize_output.py`) - Add bold line rendering for deployed fence edges

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Grid Model    │────▶│ Coverage Model  │────▶│  Visualization  │
│                 │     │                 │     │                 │
│ get_boundary_   │     │ calculate_fence │     │ draw_fence_     │
│ edges()         │     │ _protection()   │     │ edges()         │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## Components and Interfaces

### 1. Grid Model Enhancement

**File:** `hexdynamic/grid_model.py`

#### New Method: `get_boundary_edges_for_grid(grid_id)`

Returns a list of boundary edges for a specific grid. Each edge is represented as a tuple `(grid_id, direction)` where direction indicates which side of the hexagon faces outward.

```python
def get_boundary_edges_for_grid(self, grid_id: int) -> List[Tuple[int, int]]:
    """
    Get boundary edges for a specific grid.
    
    A boundary edge is an edge that faces outside the protected area.
    For hexagonal grids, this means the neighbor in that direction doesn't exist.
    
    Returns:
        List of (grid_id, direction) tuples where direction is 0-5
        representing the 6 hexagonal directions.
    """
```

#### Modified Method: `get_fencing_edges()`

Update to return boundary edges with proper edge keys for fence deployment.

### 2. Data Model Enhancement

**File:** `hexdynamic/data_loader.py`

#### New Constraint: `max_fences_per_grid`

Add a new constraint parameter to `ResourceConstraints`:

```python
max_fences_per_grid: int = 6  # Default: one per hexagonal side
```

#### Modified: `initialize_deployment_matrix()`

Update fence deployment matrix to support values 0-6 instead of 0-1:

```python
# For fence, the value represents the maximum number of fences
# that can be deployed on that grid (one per boundary edge)
self.deployment_matrix['fence'][grid.grid_id] = num_boundary_edges
```

### 3. Coverage Model Enhancement

**File:** `hexdynamic/coverage_model.py`

#### Modified: `calculate_fence_protection()`

Update to handle multiple fences per grid:

```python
def calculate_fence_protection(self, solution: DeploymentSolution) -> Dict[int, float]:
    """
    Calculate fence protection for each grid.
    
    Each fence on a boundary edge provides protection to the grid.
    Multiple fences on the same grid provide cumulative protection.
    """
```

#### Modified: `repair_solution()`

Update fence repair logic to handle multi-fence edges:

```python
# Limit fences per grid to max_fences_per_grid
# Ensure total fence length doesn't exceed constraint
```

### 4. Visualization Enhancement

**File:** `hexdynamic/visualize_output.py`

#### New Function: `draw_deployed_fence_edges()`

Draw deployed fence edges with bold lines:

```python
def draw_deployed_fence_edges(ax, grids, out, hex_size):
    """
    Draw deployed fence edges as bold lines on the map.
    
    Each fence edge is drawn as a thick line segment between
    the two grid centers or from grid center to boundary.
    """
```

## Data Models

### Fence Edge Representation

Current format (in output JSON):
```json
{
  "fence_edges": [
    {"grid_id_1": 1, "grid_id_2": 2},
    ...
  ]
}
```

New format (supports multiple fences per edge):
```json
{
  "fence_edges": [
    {"grid_id": 5, "direction": 0, "edge_key": "5-None"},
    {"grid_id": 5, "direction": 2, "edge_key": "5-None"},
    ...
  ]
}
```

For edges between two grids:
```json
{
  "fence_edges": [
    {"grid_id_1": 1, "grid_id_2": 2},
    ...
  ]
}
```

### Boundary Edge Data Structure

```python
@dataclass
class BoundaryEdge:
    grid_id: int          # The edge grid
    direction: int        # 0-5, hexagonal direction
    edge_key: Tuple[int, Optional[int]]  # (grid_id, neighbor_id) or (grid_id, None)
```

## Correctness Properties

*Property is a characteristic or behavior that should hold true across all valid executions of a system - essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Boundary Edge Count Consistency

*For any* edge grid, the number of boundary edges SHALL equal the number of hexagonal directions where no neighbor exists in the grid set.

**Validates: Requirements 2.1, 2.2, 2.3**

Rationale: A hexagonal grid has 6 directions. For an edge grid, some neighbors don't exist. The boundary edge count must match the count of missing neighbors.

### Property 2: Fence Deployment Limit Per Grid

*For any* grid, the number of deployed fences SHALL NOT exceed the number of boundary edges for that grid, and SHALL NOT exceed `max_fences_per_grid` (default 6).

**Validates: Requirements 1.1, 1.2, 1.4**

Rationale: Each fence must be placed on a valid boundary edge. The deployment matrix value for fence represents the maximum allowed fences.

### Property 3: Total Fence Length Constraint

*For any* deployment solution, the total number of deployed fences (sum of all fence counts) SHALL NOT exceed the `total_fence_length` constraint.

**Validates: Requirements 1.3**

Rationale: Each boundary edge fence counts separately toward the total fence budget.

### Property 4: Deployment Matrix Value Range

*For any* grid in the deployment matrix, the fence value SHALL be an integer in the range [0, num_boundary_edges], where num_boundary_edges ≤ 6.

**Validates: Requirements 1.4**

Rationale: The deployment matrix must support multi-value (0-6) format for fence deployments.

### Property 5: Default Configuration

*For any* configuration without `max_fences_per_grid` specified, THE System SHALL use the default value of 6.

**Validates: Requirements 4.1**

Rationale: Backward compatibility requires sensible defaults.

### Property 6: Backward Compatibility

*For any* input using binary (0/1) fence deployment format, THE System SHALL correctly interpret and process it as multi-value format.

**Validates: Requirements 4.2, 4.3**

Rationale: Existing configurations must continue to work without modification.

## Error Handling

### Invalid Fence Deployment

- **Condition**: Attempting to deploy a fence on a non-boundary edge
- **Response**: Raise `ValueError` with message indicating invalid edge
- **Recovery**: Skip invalid deployment and continue with valid ones

### Exceeding Fence Limit

- **Condition**: Total fence count exceeds `total_fence_length` constraint
- **Response**: Truncate to maximum allowed, prioritizing high-risk areas
- **Logging**: Warning message with details of truncation

### Missing Boundary Data

- **Condition**: `boundary_xy` not provided in input
- **Response**: Fall back to rectangular boundary detection
- **Logging**: Info message indicating fallback mode

## Testing Strategy

### Unit Tests

1. **Test boundary edge identification**
   - Test with various grid shapes (rectangular, irregular)
   - Test corner grids (should have 2-3 boundary edges)
   - Test interior grids (should have 0 boundary edges)

2. **Test multi-fence deployment**
   - Test deploying 1-6 fences on a single grid
   - Test fence count constraint enforcement
   - Test deployment matrix values

3. **Test fence protection calculation**
   - Verify protection increases with more fences
   - Verify protection is capped at maximum

### Property-Based Tests

1. **Property 1**: Boundary edge count consistency
   - Generate random grid configurations
   - Verify boundary edge count matches missing neighbor count

2. **Property 2**: Fence deployment limit
   - Generate random deployment solutions
   - Verify no grid exceeds its boundary edge count

3. **Property 3**: Total fence length constraint
   - Generate random solutions
   - Verify total fence count doesn't exceed constraint

### Integration Tests

1. **End-to-end deployment flow**
   - Run full optimization with new fence model
   - Verify output JSON format
   - Verify visualization renders correctly

2. **Backward compatibility**
   - Test with existing input files
   - Verify output matches expected format
