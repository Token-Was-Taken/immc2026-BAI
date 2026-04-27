# Implementation Plan: Fence Edge Deployment Enhancement

## Overview

This plan implements multi-fence edge deployment and visualization enhancement. The implementation follows a bottom-up approach: first update the grid model to identify boundary edges, then update the data model and coverage model, and finally update visualization.

## Tasks

- [x] 1. Update Grid Model for Boundary Edge Identification
  - Add `get_boundary_edges_for_grid()` method to identify edges facing outside
  - Add `get_all_boundary_edges()` method to return all boundary edges
  - Update `get_fencing_edges()` to include boundary edges with proper edge keys
  - _Requirements: 2.1, 2.2, 2.3_

- [x] 1.1 Write property tests for boundary edge identification
  - **Property 1: Boundary Edge Count Consistency**
  - **Validates: Requirements 2.1, 2.2, 2.3**

- [x] 2. Update Data Model for Multi-Fence Support
  - Add `max_fences_per_grid` to `ResourceConstraints` (default: 6)
  - Update `initialize_deployment_matrix()` to set fence values based on boundary edge count
  - _Requirements: 1.2, 1.4_

- [x] 2.1 Write property tests for deployment matrix values
  - **Property 4: Deployment Matrix Value Range**
  - **Validates: Requirements 1.4**

- [x] 3. Update Coverage Model for Multi-Fence Protection
  - Modify `calculate_fence_protection()` to handle multiple fences per grid
  - Update `validate_solution()` to check fence count per grid
  - Update `repair_solution()` to enforce fence limits
  - _Requirements: 1.1, 1.3_

- [x] 3.1 Write property tests for fence deployment limits
  - **Property 2: Fence Deployment Limit Per Grid**
  - **Property 3: Total Fence Length Constraint**
  - **Validates: Requirements 1.1, 1.2, 1.3**

- [x] 4. Update DSSA Optimizer for Multi-Fence Deployment
  - Modify `_initialize_solution()` to deploy fences on boundary edges
  - Update solution vector encoding/decoding for fence counts
  - _Requirements: 1.1, 1.3_

- [x] 5. Update Visualization for Fence Edge Display
  - Add `draw_deployed_fence_edges()` function to draw bold fence edges
  - Update `plot_terrain_deployment_map()` to call new fence edge drawing
  - Set fence edge line width to 2.5x regular edge width
  - Use distinct color (#c0392b) for fence edges
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 5.1 Write unit tests for fence edge visualization
  - Test that fence edges are drawn with correct line width
  - Test that fence edge color is distinct
  - **Validates: Requirements 3.1, 3.2, 3.3**

- [x] 6. Add Backward Compatibility
  - Ensure default `max_fences_per_grid = 6` when not specified
  - Handle binary (0/1) fence deployment format in input
  - Maintain output JSON format compatibility
  - _Requirements: 4.1, 4.2, 4.3_

- [x] 6.1 Write property tests for backward compatibility
  - **Property 5: Default Configuration**
  - **Property 6: Backward Compatibility**
  - **Validates: Requirements 4.1, 4.2, 4.3**

- [x] 7. Checkpoint - Run all tests
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Integration Testing
  - Run full optimization with new fence model
  - Verify output JSON format
  - Generate visualization and verify fence edges display correctly
  - _Requirements: All_

---

## Visualization Bug Fix Tasks

The following tasks address bugs found in the visualization:

- [x] 9. Fix Fence Edge Visualization - Only Draw Boundary Edges
  - Modify `draw_deployed_fence_edges()` in `visualize_output.py`
  - Filter out internal edges (where both grid_id_1 and grid_id_2 are not None)
  - Only draw edges where grid_id_2 is None (boundary edges)
  - Add debug logging to verify only boundary edges are drawn
  - _Requirements: 3.5, Property 7_
  - Related file: `hexdynamic/visualize_output.py`

- [ ] 9.1 Write property test for boundary edge filtering
  - **Property 7: Visualization Only Shows Boundary Edges**
  - **Validates: Requirements 3.5**

- [x] 10. Remove Redundant Pentagon Markers
  - Modify `_draw_resources()` in `visualize_output.py`
  - Remove the code that draws pentagon markers for fence deployment
  - Update legend to show line instead of pentagon for fence
  - The bold fence edges are sufficient to indicate deployment
  - _Requirements: 5.1, 5.2, Property 8_
  - Related file: `hexdynamic/visualize_output.py`

- [x] 11. Additional Fixes
  - Fix optimizer to only deploy fences on boundary edges (dssa_optimizer.py)
  - Fix output format to handle boundary edges (protection_pipeline.py)
  - Fix postprocess_iteration.py to handle boundary edges
  - Update legend to show bold line for fence instead of pentagon

- [ ] 12. Checkpoint - Verify Visualization Fixes
  - Generate terrain deployment map
  - Verify bold edges only appear on boundary edges (not internal edges)
  - Verify no pentagon markers inside grid cells
  - Ask the user to review the visualization

## Notes

- Tasks 9-11 address specific bugs found in the visualization output
- Each task references specific requirements for traceability
- Property tests validate universal correctness properties
- Checkpoints ensure incremental validation