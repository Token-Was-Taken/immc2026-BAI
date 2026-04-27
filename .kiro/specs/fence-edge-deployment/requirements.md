# Requirements Document: Fence Edge Deployment Enhancement

## Introduction

This document describes the requirements for enhancing the fence deployment mechanism in the wildlife protection system. Currently, fence deployment is limited to one fence per edge grid. The new requirement allows deploying multiple fences on a single edge grid, one for each boundary edge. Additionally, the visualization needs to display deployed fence edges with bold highlighting.

## Glossary

- **Edge Grid**: A grid cell located at the boundary of the protected area, identified by having fewer than 6 neighbors or being on the rectangular map boundary
- **Boundary Edge**: An edge of a hexagonal grid that faces outside the protected area (no neighboring grid on that side)
- **Fence Edge**: A pair of grid IDs representing a potential fence deployment location between two adjacent grids
- **Fencing Edge**: An edge where at least one endpoint is an edge grid, eligible for fence deployment

## Requirements

### Requirement 1: Multi-Fence Edge Deployment

**User Story:** As a wildlife protection planner, I want to deploy multiple fences on a single edge grid, so that I can protect all boundary edges of that grid.

#### Acceptance Criteria

1. WHEN an edge grid has multiple boundary edges, THE System SHALL allow deploying one fence per boundary edge
2. THE maximum number of fences per grid SHALL default to 6 (one per hexagonal side)
3. WHEN deploying fences on an edge grid, THE System SHALL count each boundary edge fence separately toward the total fence length constraint
4. THE deployment matrix for fence SHALL support values from 0 to 6 (instead of 0 or 1)

### Requirement 2: Boundary Edge Identification

**User Story:** As a system developer, I want to identify which edges of an edge grid are boundary edges, so that I can determine valid fence deployment locations.

#### Acceptance Criteria

1. WHEN identifying boundary edges for a grid, THE System SHALL return all edges that face outside the protected area
2. FOR EACH boundary edge, THE System SHALL provide the edge key (grid_id_1, grid_id_2) where one grid exists and the other does not
3. THE System SHALL distinguish between internal edges (between two grids) and boundary edges (facing outside)

### Requirement 3: Fence Edge Visualization

**User Story:** As a wildlife protection planner, I want to see deployed fence edges highlighted on the map, so that I can visually verify the fence deployment plan.

#### Acceptance Criteria

1. WHEN visualizing a deployment map, THE System SHALL draw deployed fence edges with bold lines
2. THE fence edge line width SHALL be noticeably thicker than regular grid edges
3. THE fence edge color SHALL be distinct from other map elements
4. WHEN a grid has multiple deployed fences, THE System SHALL display each fence edge separately

### Requirement 4: Backward Compatibility

**User Story:** As a system administrator, I want existing configurations to continue working, so that I don't need to update all existing input files.

#### Acceptance Criteria

1. WHEN an input file does not specify max_fences_per_grid, THE System SHALL use the default value of 6
2. WHEN existing code uses the fence deployment matrix, THE System SHALL handle both binary (0/1) and multi-value (0-6) formats
3. THE System SHALL maintain compatibility with existing output JSON format for fence_edges
