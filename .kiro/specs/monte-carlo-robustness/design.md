# Design Document: Monte Carlo Robustness Analysis

## Overview

The `monte_carlo_robust.py` script lives in `hexdynamic/` alongside the existing pipeline scripts. It reuses `run_pipeline` from `protection_pipeline.py` directly — no subprocess calls, no new abstractions. Each trial deep-copies the base config, overwrites the four constraint fields with sampled integers, writes a temporary input JSON, calls `run_pipeline`, reads the output JSON for metrics, then cleans up. After all trials, it writes `results_summary.json` and renders a multi-panel matplotlib figure.

## Architecture

```
monte_carlo_robust.py
│
├── parse_args()              # CLI argument parsing
├── load_base_config()        # Load and validate base JSON
├── sample_constraints()      # Draw one Constraint_Sample
├── run_trial()               # Execute one trial via run_pipeline
├── run_monte_carlo()         # Orchestrate N trials, collect results
│   └── _parallel_worker()   # Top-level picklable worker function
├── save_summary()            # Write results_summary.json
└── plot_robustness()         # Generate robustness_analysis.png
```

The script is self-contained in a single file. It imports `run_pipeline` from `protection_pipeline` (same directory), so it must be run from `hexdynamic/` or with that directory on `sys.path`.

### Parallelism Strategy

Each trial is CPU-bound and fully independent (separate input/output JSON files, no shared mutable state). The natural fit is `concurrent.futures.ProcessPoolExecutor`.

**Key design decisions:**

1. **Pre-generate all samples in main process** — The main process calls `sample_constraints` N times before dispatching any workers. This guarantees the constraint sequence is identical regardless of `--workers`, preserving the seed-reproducibility property.

2. **Top-level picklable worker** — `ProcessPoolExecutor` requires the submitted callable to be picklable. A module-level `_parallel_worker(args_tuple)` function unpacks `(base_config, constraints, trial_idx, output_dir)` and calls `run_trial`. Lambda or nested functions are not picklable on Windows (spawn start method).

3. **`--workers 1` sequential fallback** — When `max_workers=1`, `ProcessPoolExecutor` still spawns one subprocess. For true sequential execution (useful for debugging and testing), `run_monte_carlo` detects `workers == 1` and falls back to a plain `for` loop calling `run_trial` directly.

4. **Progress reporting** — Results are collected via `as_completed()`, so progress lines are printed as each future finishes (not necessarily in submission order). The trial index is embedded in the record for correct ordering in the final summary.

5. **Exception isolation** — Each worker wraps `run_trial` in a try/except. If the worker itself crashes (e.g., import error), the `Future.exception()` is caught in the main process and a failed record is synthesised.

## Components and Interfaces

### CLI Interface

```
python monte_carlo_robust.py <base_config.json> [options]

positional:
  base_config         Path to base input JSON

optional:
  --num-trials N      Number of Monte Carlo trials (default: 100)
  --output-dir DIR    Directory for outputs (default: ./robust_results)
  --seed SEED         Random seed for reproducibility
  --workers W         Number of parallel worker processes (default: os.cpu_count())
  --no-visualize      Skip chart generation (summary JSON only)
```

### `sample_constraints(rng) -> dict`

Draws one set of integer resource counts using the fixed distributions:

| Parameter      | Distribution     | Type |
|----------------|------------------|------|
| total_patrol   | Uniform(15, 25)  | int  |
| total_drones   | Uniform(2, 6)    | int  |
| total_cameras  | Uniform(8, 15)   | int  |
| total_camps    | Uniform(3, 7)    | int  |

Uses `rng.randint(low, high+1)` (numpy RNG) so the endpoints are inclusive.

### `run_monte_carlo(base_config, num_trials, output_dir, seed, workers) -> list`

1. Pre-generates all N `Constraint_Sample` dicts in the main process using the seeded RNG.
2. If `workers == 1`: runs trials sequentially via a plain `for` loop (debug/test mode).
3. Otherwise: submits all trials to `ProcessPoolExecutor(max_workers=workers)` using `_parallel_worker`.
4. Collects results via `concurrent.futures.as_completed()`; prints `[Trial X/N done]` per completion.
5. Catches `Future.exception()` and synthesises a failed record if a worker process crashes.
6. Returns the list of records sorted by `trial` index.

### `run_trial(base_config, constraints_sample, trial_idx, output_dir) -> dict`
2. Overwrites `config["constraints"]` fields with `constraints_sample` values (other constraint fields like `max_rangers_per_camp`, `total_fence_length` are preserved from base)
3. Writes trial input to `{output_dir}/trial_{trial_idx:04d}_input.json` (kept for reproducibility)
4. Calls `run_pipeline(input_path, output_path, vectorized=False)`
5. Reads `output_path`, extracts `summary.best_fitness` and `summary.total_protection_benefit`
6. Returns a trial record dict; on exception, returns a record with `success: false` and the error message

### Trial Record Schema

```json
{
  "trial": 0,
  "success": true,
  "constraints": {
    "total_patrol": 18,
    "total_drones": 4,
    "total_cameras": 11,
    "total_camps": 5
  },
  "best_fitness": 0.423,
  "total_protection_benefit": 12.7,
  "error": null
}
```

### `plot_robustness(results, output_dir)`

Generates a single figure with 3 rows × 2 columns (6 subplots):

- Row 1: Histogram of `best_fitness` | Histogram of `total_protection_benefit`
- Row 2: Scatter `total_patrol` vs fitness | Scatter `total_drones` vs fitness
- Row 3: Scatter `total_cameras` vs fitness | Scatter `total_camps` vs fitness

Each histogram annotates mean ± std, min, max in the plot title or as a text box. Scatter plots include a linear trend line (numpy polyfit degree 1). Figure saved as `robustness_analysis.png` at 150 dpi.

## Data Models

### Input: Base Config JSON (existing format)

Relevant fields consumed/overridden:

```json
{
  "constraints": {
    "total_patrol": 20,
    "total_camps": 0,
    "max_rangers_per_camp": 5,
    "total_cameras": 10,
    "total_drones": 3,
    "total_fence_length": 50
  },
  "dssa_config": { ... },
  "coverage_params": { ... },
  "grids": [ ... ]
}
```

Only `total_patrol`, `total_camps`, `total_cameras`, `total_drones` are overridden per trial.

### Output: `results_summary.json`

```json
{
  "meta": {
    "base_config": "robust/base.json",
    "num_trials": 100,
    "seed": 42,
    "workers": 8,
    "successful_trials": 97,
    "failed_trials": 3,
    "elapsed_seconds": 142.7,
    "trials_per_second": 0.68
  },
  "trials": [ ... ]
}
```

## Correctness Properties

A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.

Property 1: Sampled constraints are within bounds
*For any* trial, the sampled constraint values must satisfy: `15 <= total_patrol <= 25`, `2 <= total_drones <= 6`, `8 <= total_cameras <= 15`, `3 <= total_camps <= 7`.
**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

Property 2: Base config fields are not mutated
*For any* trial execution, the base config dict passed to `run_trial` must be identical before and after the call (only the deep-copied trial config is modified).
**Validates: Requirements 2.5**

Property 3: Seed reproducibility
*For any* fixed seed, running the full Monte Carlo simulation twice must produce identical sequences of sampled constraint values.
**Validates: Requirements 2.6**

Property 4: Trial record completeness
*For any* successful trial record, the record must contain non-null values for `trial`, `success`, `constraints`, `best_fitness`, and `total_protection_benefit`.
**Validates: Requirements 3.2, 3.5**

Property 5: Failed trials do not halt simulation
*For any* sequence of N trials where some raise exceptions, the total number of records returned must equal N (failed trials produce records with `success: false`).
**Validates: Requirements 3.3**

Property 6: Parallel results match sequential results
*For any* base config, seed, and num_trials, running `run_monte_carlo` with `workers=1` (sequential) must produce the same ordered list of constraint samples as running with `workers > 1` (parallel). The fitness values may differ due to optimizer non-determinism, but the constraint sequences must be identical.
**Validates: Requirements 6.2, 6.3**

## Error Handling

- Missing/invalid base config: print error, `sys.exit(1)`
- Trial exception: catch, log `[Trial X/N] FAILED: <error>`, record `success: false`, continue
- Fewer than 2 successful trials at chart time: print warning, skip `plot_robustness`
- Output dir creation: `os.makedirs(output_dir, exist_ok=True)`

## Testing Strategy

Unit tests use `pytest` and are placed in `hexdynamic/tests/test_monte_carlo_robust.py`.

Property-based tests use `hypothesis` (already present in the repo — `.hypothesis/` directory exists).

**Unit tests** cover:
- `sample_constraints` returns values within bounds for a fixed seed
- `load_base_config` raises on missing file and invalid JSON
- Trial record schema validation for both success and failure cases
- `plot_robustness` skips gracefully when fewer than 2 successful trials

**Property-based tests** (hypothesis):

Each property test runs minimum 100 examples.

- Property 1: `@given(st.integers(0, 2**31))` — for any seed, `sample_constraints` returns values within all four bounds
- Property 2: `@given(...)` — for any sampled constraints dict, the base config dict is unchanged after `run_trial` (mock `run_pipeline`)
- Property 3: `@given(st.integers(0, 2**31))` — two RNGs with the same seed produce identical constraint sequences
- Property 4: `@given(...)` — for any successful trial record dict, all required fields are present and non-null
- Property 5: `@given(st.lists(...))` — for any list of trial outcomes (some failing), result list length equals input length
- Property 6: `@given(st.integers(0, 2**31), st.integers(1, 10))` — for any seed and num_trials, sequential and parallel runs produce identical constraint sequences (mock `run_trial` to return constraints only)

Tag format: `# Feature: monte-carlo-robustness, Property N: <property_text>`
