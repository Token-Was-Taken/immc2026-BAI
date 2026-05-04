# Implementation Plan: Sobol Sensitivity Analysis

## Overview

Implement a global sensitivity analysis script using Sobol indices. The script will use SALib for Saltelli sampling and Sobol index computation, integrate with the existing protection pipeline, and produce JSON outputs plus visualizations.

## Tasks

- [x] 1. Set up project structure and dependencies
  - Create `sobol_sensitivity.py` in project root
  - Add SALib to project dependencies
  - Set up imports and module structure
  - _Requirements: 1.1, 3.2_

- [ ] 2. Implement CLI argument parsing
  - [ ] 2.1 Implement argument parser with all required options
    - `--params`, `--num-samples`, `--output-dir`, `--seed`, `--workers`, `--no-visualize`
    - _Requirements: 1.3, 1.4, 1.5, 1.6, 1.7_

- [ ] 2.2 Write unit tests for CLI parsing
  - Test default values
  - Test parameter definition parsing
  - _Requirements: 1.3, 1.4, 1.5, 1.6, 1.7_

- [ ] 3. Implement parameter definition handling
  - [ ] 3.1 Implement `parse_param_defs()` function
    - Support JSON file path and JSON string
    - Validate parameter bounds (min < max)
    - Define default parameters
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

- [ ] 3.2 Write property tests for parameter parsing
  - **Property 14: Parameter bounds validation**
  - **Property 15: Default parameters used when not specified**
  - **Validates: Requirements 2.4, 2.5, 2.6**

- [ ] 4. Implement Saltelli sampling
  - [ ] 4.1 Implement `generate_samples()` function
    - Use SALib `saltelli.sample()`
    - Scale to parameter bounds
    - Convert to integers for resource counts
    - _Requirements: 3.1, 3.3, 3.4_

- [ ] 4.2 Write property tests for sample generation
  - **Property 1: Sample count formula**
  - **Property 2: Samples within bounds**
  - **Property 3: Integer conversion**
  - **Property 4: Seed reproducibility**
  - **Validates: Requirements 3.1, 3.3, 3.4, 3.5**

- [ ] 5. Implement model evaluation
  - [ ] 5.1 Implement `evaluate_model()` function
    - Deep-copy base config
    - Update constraints with sampled values
    - Call `run_pipeline`
    - Extract fitness and benefit
    - Handle exceptions gracefully
    - _Requirements: 4.1, 4.2, 4.3, 4.5_

- [ ] 5.2 Write property tests for model evaluation
  - **Property 9: Base config immutability**
  - **Property 10: Failed evaluation handling**
  - **Validates: Requirements 4.1, 4.3**

- [ ] 6. Implement parallel execution orchestration
  - [ ] 6.1 Implement `run_analysis()` function
    - Pre-generate all samples
    - Use ProcessPoolExecutor for parallel execution
    - Implement sequential fallback for workers=1
    - Collect results
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [ ] 6.2 Write property tests for parallel execution
  - **Property 11: Parallel-sequential equivalence**
  - **Validates: Requirements 8.2, 8.3**

- [ ] 7. Implement Sobol index computation
  - [ ] 7.1 Implement `compute_sobol_indices()` function
    - Use SALib `sobol.analyze()`
    - Compute first-order and total-order indices
    - Compute bootstrap confidence intervals
    - Handle NaN values
    - _Requirements: 5.1, 5.2, 5.3, 5.5_

- [ ] 7.2 Write property tests for Sobol indices
  - **Property 5: Sobol indices in valid range**
  - **Property 6: First-order sum constraint**
  - **Property 7: Total-order >= first-order**
  - **Property 8: Confidence interval validity**
  - **Validates: Requirements 5.1, 5.2, 5.3, 5.4**

- [ ] 8. Implement convergence diagnostics
  - [ ] 8.1 Add convergence checking to `compute_sobol_indices()`
    - Compute CI width
    - Flag parameters with CI width > 0.2
    - Include convergence summary
    - _Requirements: 9.1, 9.2, 9.4_

- [ ] 8.2 Write property tests for convergence

  - **Property 13: Convergence flag correctness**
  - **Validates: Requirements 9.2**

- [ ] 9. Implement results persistence
  - [ ] 9.1 Implement `save_results()` function
    - Save `evaluations.json`
    - Save `sobol_indices.json`
    - Save `analysis_config.json`
    - Create output directory
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [ ] 9.2 Write property tests for output files

  - **Property 12: Output file completeness**
  - **Validates: Requirements 6.1, 6.2, 6.4_

- [ ] 10. Implement visualization
  - [ ] 10.1 Implement `plot_sensitivity()` function
    - Generate bar chart with S1 and ST
    - Generate parameter ranking plot
    - Generate scatter matrix
    - Handle edge case of few evaluations
    - _Requirements: 7.1, 7.3, 7.4, 7.5_

- [ ] 10.2 Write unit tests for visualization

  - Test file generation
  - Test edge case handling
  - _Requirements: 7.1, 7.3, 7.4, 7.5_

- [ ] 11. Checkpoint - Ensure all tests pass
  - Run full test suite
  - Verify all property tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. Integration testing and documentation
  - [ ] 12.1 Run end-to-end test with sample data
    - Use small sample size for quick validation
    - Verify output structure
    - _Requirements: All_

- [ ] 12.2 Add usage documentation
  - Add docstrings to all functions
  - Update README if needed
  - _Requirements: All_

- [ ] 13. Final checkpoint - Ensure all tests pass
  - Run full test suite
  - Verify integration test passes
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties
- Unit tests validate specific examples and edge cases
- The script uses SALib library for Sobol analysis (add to dependencies)
