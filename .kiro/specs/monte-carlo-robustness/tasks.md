# Implementation Plan: Monte Carlo Robustness Analysis

## Overview

Implement `hexdynamic/monte_carlo_robust.py` as a standalone script that runs N Monte Carlo trials of the DSSA optimizer with randomly sampled resource constraints, then generates a robustness analysis chart.

## Tasks

- [x] 1. Implement core sampling and config utilities
  - Create `hexdynamic/monte_carlo_robust.py`
  - Implement `parse_args()` with positional `base_config`, `--num-trials` (default 100), `--output-dir` (default `./robust_results`), `--seed`, `--no-visualize`
  - Implement `load_base_config(path)` — loads JSON, raises `SystemExit` with message on missing file or invalid JSON
  - Implement `sample_constraints(rng)` — draws `total_patrol` from Uniform(15,25), `total_drones` from Uniform(2,6), `total_cameras` from Uniform(8,15), `total_camps` from Uniform(3,7) as integers using `rng.integers`
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4_

- [x] 1.1 Write property test for constraint sampling bounds
  - **Property 1: Sampled constraints are within bounds**
  - **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
  - Create `hexdynamic/tests/test_monte_carlo_robust.py`
  - Use `@given(st.integers(0, 2**31))` to test that for any seed, all four sampled values are within their respective ranges
  - `# Feature: monte-carlo-robustness, Property 1: Sampled constraints are within bounds`

- [x] 1.2 Write property test for seed reproducibility
  - **Property 3: Seed reproducibility**
  - **Validates: Requirements 2.6**
  - Use `@given(st.integers(0, 2**31), st.integers(1, 20))` to test that two RNGs with the same seed produce identical sequences of N samples
  - `# Feature: monte-carlo-robustness, Property 3: Seed reproducibility`

- [x] 2. Implement trial execution
  - Implement `run_trial(base_config, constraints_sample, trial_idx, output_dir)`:
    - Deep-copy `base_config` using `copy.deepcopy`
    - Override only `total_patrol`, `total_drones`, `total_cameras`, `total_camps` in `config["constraints"]`
    - Write trial input JSON to `{output_dir}/trial_{trial_idx:04d}_input.json`
    - Call `run_pipeline(input_path, output_path)` where `output_path = {output_dir}/trial_{trial_idx:04d}_output.json`
    - Read output JSON, extract `summary.best_fitness` and `summary.total_protection_benefit`
    - Return trial record dict with `trial`, `success`, `constraints`, `best_fitness`, `total_protection_benefit`, `error`
    - Wrap in try/except — on failure set `success: false`, record error message, return record
  - _Requirements: 2.5, 3.1, 3.2, 3.3, 3.5_

- [x] 2.1 Write property test for base config immutability
  - **Property 2: Base config fields are not mutated**
  - **Validates: Requirements 2.5**
  - Mock `run_pipeline` to avoid actual optimization; use `@given` with a generated config dict and constraints sample
  - Verify base config is identical before and after `run_trial`
  - `# Feature: monte-carlo-robustness, Property 2: Base config fields are not mutated`

- [x] 2.2 Write property test for trial record completeness
  - **Property 4: Trial record completeness**
  - **Validates: Requirements 3.2, 3.5**
  - Mock `run_pipeline` to return a valid output JSON; use `@given` with sampled constraints
  - Verify all required fields (`trial`, `success`, `constraints`, `best_fitness`, `total_protection_benefit`) are present and non-null in successful records
  - `# Feature: monte-carlo-robustness, Property 4: Trial record completeness`

- [x] 2.3 Write property test for failed trial fault tolerance
  - **Property 5: Failed trials do not halt simulation**
  - **Validates: Requirements 3.3**
  - Use `@given(st.lists(st.booleans(), min_size=1, max_size=20))` to generate a list of success/failure flags
  - Mock `run_trial` to raise on failure flags; verify `run_monte_carlo` returns exactly N records
  - `# Feature: monte-carlo-robustness, Property 5: Failed trials do not halt simulation`

- [x] 3. Implement orchestration and persistence
  - Implement `run_monte_carlo(base_config, num_trials, output_dir, seed)`:
    - Initialize numpy RNG with seed (or random seed if None)
    - Loop N trials, call `run_trial`, print `[Trial X/N]` progress, collect records
    - Return list of trial records
  - Implement `save_summary(results, meta, output_dir)`:
    - Write `{output_dir}/results_summary.json` with `meta` (base_config path, num_trials, seed, successful/failed counts) and `trials` list
  - _Requirements: 3.4, 4.1, 4.2_

- [x] 4. Checkpoint — Ensure sampling, trial execution, and persistence work end-to-end
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement robustness analysis chart
  - Implement `plot_robustness(results, output_dir)`:
    - Filter to successful trials only; skip with warning if fewer than 2
    - Create 3×2 matplotlib figure (figsize ~(14, 12))
    - Row 1: histogram of `best_fitness` with mean/std/min/max annotation | histogram of `total_protection_benefit` with same
    - Row 2: scatter `total_patrol` vs `best_fitness` with linear trend line | scatter `total_drones` vs `best_fitness` with trend line
    - Row 3: scatter `total_cameras` vs `best_fitness` with trend line | scatter `total_camps` vs `best_fitness` with trend line
    - Save as `{output_dir}/robustness_analysis.png` at 150 dpi
  - Wire everything together in `main()`: parse args → load config → run MC → save summary → plot
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

- [x] 6. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Add `--workers` CLI argument and parallel execution infrastructure
  - Add `--workers` argument to `parse_args()` (default: `os.cpu_count()`)
  - Add module-level `_parallel_worker(args_tuple)` function that unpacks `(base_config, constraints, trial_idx, output_dir)` and calls `run_trial` — must be top-level for `ProcessPoolExecutor` pickling on Windows
  - Update `run_monte_carlo` signature to accept `workers` parameter
  - _Requirements: 1.6, 6.1, 6.2_

- [x] 8. Implement parallel orchestration in `run_monte_carlo`
  - Pre-generate all N `Constraint_Sample` dicts in the main process before dispatching workers (preserves seed determinism)
  - If `workers == 1`: run sequentially via plain `for` loop (no subprocess overhead, identical to current behavior)
  - Otherwise: submit all trials to `ProcessPoolExecutor(max_workers=workers)` using `_parallel_worker`
  - Collect results via `concurrent.futures.as_completed()`; print `[Trial X/N done]` per completion
  - Catch `Future.exception()` and synthesise a failed record if a worker process crashes
  - Return records sorted by `trial` index
  - _Requirements: 6.1, 6.3, 6.4, 6.5_

- [x] 8.1 Write property test for parallel vs sequential constraint sequence equivalence
  - **Property 6: Parallel results match sequential results**
  - **Validates: Requirements 6.2, 6.3**
  - Use `@given(st.integers(0, 2**31), st.integers(1, 10))` — for any seed and num_trials, sequential (`workers=1`) and parallel (`workers=2`) runs produce identical ordered constraint sequences
  - Mock `run_trial` to return the constraints dict as the record (avoid actual pipeline execution)
  - `# Feature: monte-carlo-robustness, Property 6: Parallel results match sequential results`

- [x] 9. Add timing metadata to `save_summary`
  - Pass `elapsed_seconds` (wall-clock time of `run_monte_carlo`) and `workers` to `save_summary`
  - Include `elapsed_seconds`, `trials_per_second`, and `workers` in the `meta` block of `results_summary.json`
  - Update `main()` to measure wall-clock time around `run_monte_carlo` and pass it to `save_summary`
  - _Requirements: 6.6_

- [x] 10. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Trial input/output JSONs are kept in `--output-dir` for reproducibility and debugging
- The script must be run from `hexdynamic/` (or with it on `sys.path`) since it imports `protection_pipeline`
- `total_fence_length`, `max_rangers_per_camp`, and other constraint fields are preserved from the base config across all trials
