# Requirements Document: Fence Edge Deployment Enhancement

## Introduction

This document describes the requirements for enhancing the fence deployment mechanism in the wildlife protection system. Currently, fence deployment is limited to one fence per edge grid. The new requirement allows deploying multiple fences on a single edge grid, one for each boundary edge. Additionally, the visualization needs to display deployed fence edges with bold highlighting.

## Glossary

- **Edge Direction**: The direction of the side of grid is one of 0, 1, 2, 3, 4, 5 (clockwise from left, corresponding to the hexagonal side of west, north-west, north-east, east, south-east, south-west). Edge directions are used to identify the edges of an grid.
- **Boundary Grid**: A grid cell located at the boundary of the protected area, identified by having fewer than 6 neighbors
- **Boundary Edge**: A side of an boundary grid that faces outside the protected area (no neighboring grid on that side)
- **Fence Edge**: The side with fence deployed. Only the **boundary edges** are eligible for fence deployment.
- **Internal Edge**: A side of an boundary grid that is between two adjacent grids within the protected area (NOT a valid fence location)

## Requirements

### Requirement 1: Multi-Fence Edge Deployment

**User Story:** As a wildlife protection planner, I want to deploy multiple fences on a single boundary grid, so that I can protect all boundary edges of that grid. One boundary grid can have up to 6 boundary edges.

#### Acceptance Criteria

1. WHEN an boundary grid has multiple boundary edges, THE System SHALL allow deploying one fence per boundary edge
2. THE maximum number of fences per grid SHALL default to 6 (one per hexagonal side)
3. WHEN deploying fences on an boundary grid, THE System SHALL count each boundary edge fence separately toward the total fence length constraint
4. THE deployment matrix decides whether a boundary grid can deploy fences. A value of 0 means no fence deployment, and a value of 1 means one fence deployment.
5. The output json file SHALL include the fence edge number in the deployment section for each grid. 
6. The output json file SHALL include a list of fence edge directions for each boundary grid feasible for fence deployment. This list SHALL be used to display the fence edges on the map.

### Requirement 2: Boundary Edge Identification

**User Story:** As a system developer, I want to identify which edges of an edge grid are boundary edges, so that I can determine valid fence deployment locations.

#### Acceptance Criteria

1. WHEN identifying boundary edges for a grid, THE System SHALL return all sides that face outside the protected area
2. FOR EACH boundary edge, THE System SHALL use the edge direction (0-5) to identify the boundary edge of the grid
3. THE System SHALL distinguish between internal edges (between two grids) and boundary edges (facing outside)

### Requirement 3: Fence Edge Visualization

**User Story:** As a wildlife protection planner, I want to see deployed fence edges highlighted on the map, so that I can visually verify the fence deployment plan.

#### Acceptance Criteria

1. WHEN visualizing a deployment map, THE System SHALL draw deployed fence edges with bold lines
2. THE fence edge line width SHALL be noticeably thicker than regular grid edges
3. THE fence edge color SHALL be distinct from other map elements
4. WHEN a grid has multiple deployed fences, THE System SHALL display each fence edge separately
5. THE System SHALL ONLY draw boundary edges as fence edges, NOT internal edges between grids

### Requirement 4: Backward Compatibility

**User Story:** As a system administrator, I want existing configurations to continue working, so that I don't need to update all existing input files.

#### Acceptance Criteria

1. WHEN an input file does not specify max\_fences\_per\_grid, THE System SHALL use the default value of 6
2. THE System SHALL maintain compatibility with existing output JSON format for fence\_edges

### Requirement 5: Remove Redundant Fence Indicators

**User Story:** As a wildlife protection planner, I want a clean visualization without redundant indicators, so that the map is easier to read.

#### Acceptance Criteria

1. WHEN fence edges are displayed with bold lines, THE System SHALL NOT also display pentagon markers inside grid cells to indicate fence deployment
2. THE bold fence edge lines alone SHALL be sufficient to indicate fence deployment locations