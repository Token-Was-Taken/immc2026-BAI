# Design Document: Sobol Sensitivity Analysis

## Overview

The `sobol_sensitivity.py` script lives in the project root alongside `sensitivity_analysis.py` and `monte_carlo_robust.py`. It uses the `SALib` library for Saltelli sampling and Sobol index computation. Each model evaluation calls `run_pipeline` from `hexdynamic/protection_pipeline.py`. The script supports parallel execution via `ProcessPoolExecutor` and produces JSON outputs plus matplotlib visualizations.

## Architecture

```
sobol_sensitivity.py
│
├── parse_args()              # CLI argument parsing
├── load_base_config()        # Load and validate base JSON
├── parse_param_defs()        # Parse parameter definitions from JSON
├── generate_samples()        # Generate Saltelli samples via SALib
├── evaluate_model()          # Run one pipeline evaluation
├── run_analysis()            # Orchestrate all evaluations
│   └── _parallel_worker()    # Top-level picklable worker function
├── compute_sobol_indices()   # Compute indices via SALib
├── save_results()            # Write JSON outputs
└── plot_sensitivity()        # Generate visualization
```

The script is self-contained in a single file. It imports `run_pipeline` from `hexdynamic.protection_pipeline` and uses `SALib` for sampling and analysis.

### Parallelism Strategy

Each model evaluation is CPU-bound and independent. The design mirrors `monte_carlo_robust.py`:

1. **Pre-generate all samples in main process** — Saltelli samples are generated once before dispatching workers, ensuring deterministic sequences regardless of `--workers`.

2. **Top-level picklable worker** — `_parallel_worker(args_tuple)` unpacks `(base_config, params_dict, eval_idx, output_dir)` and calls `evaluate_model`.

3. **Sequential fallback** — When `workers == 1`, evaluations run sequentially via a plain `for` loop.

4. **Progress reporting** — Prints `[Eval X/N done]` as each evaluation completes.

5. **Exception isolation** — Failed evaluations return NaN and are handled gracefully by SALib.

## Components and Interfaces

### CLI Interface

```
python sobol_sensitivity.py <base_config.json> [options]

positional:
  base_config         Path to base input JSON

optional:
  --params FILE|JSON  Parameter definitions (file path or JSON string)
  --num-samples N     Base number of Saltelli samples (default: 512)
  --output-dir DIR    Directory for outputs (default: ./sobol_results)
  --seed SEED         Random seed for reproducibility
  --workers W         Number of parallel workers (default: os.cpu_count())
  --no-visualize      Skip chart generation (JSON outputs only)
```

### Parameter Definition Schema

```json
[
  {"name": "total_patrol", "min": 10, "max": 30},
  {"name": "total_drones", "min": 1, "max": 8},
  {"name": "total_cameras", "min": 5, "max": 20},
  {"name": "total_camps", "min": 2, "max": 10}
]
```

### `generate_samples(param_defs, num_samples, seed) -> tuple`

Uses `SALib.analyze.sobol.analyze` and `SALib.sample.saltoni.sample`:

1. Constructs the SALib problem dict:
   ```python
   problem = {
       "num_vars": len(param_defs),
       "names": [p["name"] for p in param_defs],
       "bounds": [[p["min"], p["max"]] for p in param_defs]
   }
   ```

2. Generates Saltelli samples:
   ```python
   from SALib.sample import saltelli
   param_values = saltelli.sample(problem, num_samples, seed=seed)
   ```

3. Returns `(problem, param_values)` where `param_values.shape == (N*(2k+2), k)`.

### `evaluate_model(base_config, params_dict, eval_idx, output_dir) -> dict`

1. Deep-copies `base_config`.
2. Updates `config["constraints"]` with values from `params_dict`.
3. Writes input to `{output_dir}/eval_{eval_idx:05d}_input.json`.
4. Calls `run_pipeline(input_path, output_path, vectorized=False)`.
5. Reads output, extracts `best_fitness` and `total_protection_benefit`.
6. Returns evaluation record:
   ```python
   {
       "eval_idx": eval_idx,
       "success": True,
       "params": params_dict,
       "best_fitness": ...,
       "total_protection_benefit": ...,
       "error": None
   }
   ```
7. On exception, returns record with `success: False` and `best_fitness: NaN`.

### `run_analysis(base_config, param_defs, num_samples, output_dir, seed, workers) -> tuple`

1. Calls `generate_samples()` to get `(problem, param_values)`.
2. Pre-generates all params_dict objects.
3. If `workers == 1`: runs evaluations sequentially.
4. Otherwise: dispatches to `ProcessPoolExecutor`.
5. Collects results, extracts output arrays for SALib.
6. Returns `(problem, param_values, output_arrays, eval_records)`.

### `compute_sobol_indices(problem, output_array, num_bootstrap=1000) -> dict`

1. Calls `SALib.analyze.sobol.analyze(problem, output_array, num_resamples=num_bootstrap)`.
2. Extracts `Si["S1"]` (first-order), `Si["ST"]` (total-order), `Si["S1_conf"]`, `Si["ST_conf"]`.
3. Computes convergence flags: `converged = (conf_width < 0.2)`.
4. Returns structured dict:
   ```python
   {
       "first_order": [{"name": ..., "value": ..., "conf_low": ..., "conf_high": ..., "converged": ...}, ...],
       "total_order": [{"name": ..., "value": ..., "conf_low": ..., "conf_high": ..., "converged": ...}, ...],
       "convergence_summary": {...}
   }
   ```

### `save_results(problem, param_values, output_arrays, eval_records, sobol_indices, output_dir, meta)`

Writes three JSON files:

1. `evaluations.json` — Raw evaluation records.
2. `sobol_indices.json` — Sobol indices with confidence intervals.
3. `analysis_config.json` — Problem definition and metadata.

### `plot_sensitivity(sobol_indices, param_names, output_dir)`

Generates three figures:

1. `sobol_indices.png` — Bar chart with S1 and ST side by side, error bars for confidence intervals.
2. `parameter_ranking.png` — Horizontal bar chart of parameters sorted by ST descending.
3. `scatter_matrix.png` — Pairwise scatter plots of parameters vs outputs (if sample size permits).

## Data Models

### Input: Base Config JSON (existing format)

Same as Monte Carlo robustness analysis — only `constraints` fields are overridden.

### Output: `sobol_indices.json`

```json
{
  "meta": {
    "base_config": "hexdynamic/robust/base.json",
    "num_samples": 512,
    "total_evaluations": 4108,
    "seed": 42,
    "workers": 8,
    "successful_evaluations": 4050,
    "failed_evaluations": 58,
    "elapsed_seconds": 1842.5,
    "evaluations_per_second": 2.23
  },
  "problem": {
    "num_vars": 4,
    "names": ["total_patrol", "total_drones", "total_cameras", "total_camps"],
    "bounds": [[10, 30], [1, 8], [5, 20], [2, 10]]
  },
  "first_order": [
    {"name": "total_patrol", "value": 0.42, "conf_low": 0.38, "conf_high": 0.46, "converged": true},
    {"name": "total_drones", "value": 0.15, "conf_low": 0.12, "conf_high": 0.18, "converged": true},
    {"name": "total_cameras", "value": 0.08, "conf_low": 0.05, "conf_high": 0.11, "converged": true},
    {"name": "total_camps", "value": 0.05, "conf_low": 0.02, "conf_high": 0.08, "converged": true}
  ],
  "total_order": [
    {"name": "total_patrol", "value": 0.52, "conf_low": 0.47, "conf_high": 0.57, "converged": true},
    {"name": "total_drones", "value": 0.22, "conf_low": 0.18, "conf_high": 0.26, "converged": true},
    {"name": "total_cameras", "value": 0.14, "conf_low": 0.10, "conf_high": 0.18, "converged": true},
    {"name": "total_camps", "value": 0.10, "conf_low": 0.06, "conf_high": 0.14, "converged": true}
  ],
  "convergence_summary": {
    "all_converged": true,
    "max_conf_width": 0.10,
    "parameters_not_converged": []
  }
}
```

### Output: `evaluations.json`

```json
{
  "meta": {...},
  "evaluations": [
    {
      "eval_idx": 0,
      "success": true,
      "params": {"total_patrol": 15, "total_drones": 3, "total_cameras": 10, "total_camps": 5},
      "best_fitness": 0.423,
      "total_protection_benefit": 12.7,
      "error": null
    },
    ...
  ]
}
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*


Property 1: Sample count formula
*For any* valid parameter definition with k parameters and sample size N, the generated sample array must have exactly N × (2k + 2) rows and k columns.
**Validates: Requirements 3.1, 1.4**

Property 2: Samples within bounds
*For any* generated sample and parameter definition, each parameter value must be within its defined [min, max] bounds after scaling.
**Validates: Requirements 3.3**

Property 3: Integer conversion
*For any* generated sample for integer-constrained parameters, all values must be integers.
**Validates: Requirements 3.4**

Property 4: Seed reproducibility
*For any* fixed seed, running the sample generation twice must produce identical sample sequences.
**Validates: Requirements 3.5, 1.6**

Property 5: Sobol indices in valid range
*For any* computed Sobol index (first-order or total-order), the value must be in the range [0, 1].
**Validates: Requirements 5.1, 5.2**

Property 6: First-order sum constraint
*For any* set of computed first-order Sobol indices, the sum must be less than or equal to 1.
**Validates: Requirements 5.4**

Property 7: Total-order >= first-order
*For any* parameter, the total-order index must be greater than or equal to the first-order index (total-order includes interactions).
**Validates: Requirements 5.1, 5.2**

Property 8: Confidence interval validity
*For any* computed confidence interval [low, high], the bounds must satisfy: 0 <= low <= value <= high <= 1.
**Validates: Requirements 5.3**

Property 9: Base config immutability
*For any* model evaluation, the base config dict must remain unchanged after the evaluation completes.
**Validates: Requirements 4.1**

Property 10: Failed evaluation handling
*For any* sequence of evaluations where some fail, the total number of records must equal the number of samples, with failed evaluations having NaN outputs.
**Validates: Requirements 4.3**

Property 11: Parallel-sequential equivalence
*For any* seed and sample size, the sample sequences generated with workers=1 must be identical to those generated with workers>1.
**Validates: Requirements 8.2, 8.3**

Property 12: Output file completeness
*For any* completed analysis, the output directory must contain `evaluations.json`, `sobol_indices.json`, and `analysis_config.json`.
**Validates: Requirements 6.1, 6.2, 6.4**

Property 13: Convergence flag correctness
*For any* parameter with confidence interval width > 0.2, the convergence flag must be False.
**Validates: Requirements 9.2**

Property 14: Parameter bounds validation
*For any* parameter definition where min >= max, the script must exit with an error without generating samples.
**Validates: Requirements 2.4**

Property 15: Default parameters used when not specified
*For any* invocation without `--params`, the script must use the four default parameter definitions.
**Validates: Requirements 2.5, 2.6**

## Error Handling

- Invalid file path: print error, exit with code 1
- Invalid JSON: print error with details, exit with code 1
- Invalid parameter bounds (min >= max): print error, exit with code 1
- Model evaluation exception: log error, record NaN, continue
- Fewer than 10 successful evaluations: skip visualization, print warning
- All evaluations fail: still compute indices (will be NaN), print warning

## Testing Strategy

Unit tests use `pytest` and are placed in `hexdynamic/tests/test_sobol_sensitivity.py`.

Property-based tests use `hypothesis` (already in the repo).

**Unit tests** cover:
- `parse_param_defs` with valid and invalid inputs
- `generate_samples` returns correct shape
- Sample values are within bounds
- Sobol indices are in valid range
- Output file structure validation

**Property-based tests** (hypothesis):

Each property test runs minimum 100 examples.

- Property 1: `@given(st.integers(2, 10), st.integers(100, 1000))` — for any k parameters and N samples, sample array shape is N×(2k+2) × k
- Property 2: `@given(st.lists(st.tuples(st.floats(-100, 100), st.floats(-100, 100)), min_size=1))` — for any bounds, all samples are within bounds
- Property 3: `@given(...)` — for integer parameters, all values are integers
- Property 4: `@given(st.integers(0, 2**31))` — same seed produces identical samples
- Property 5: `@given(st.lists(st.floats(0, 1), min_size=2))` — all indices in [0, 1]
- Property 6: `@given(st.lists(st.floats(0, 1), min_size=2))` — sum of first-order <= 1
- Property 7: `@given(st.lists(st.tuples(st.floats(0, 1), st.floats(0, 1)), min_size=1))` — total-order >= first-order
- Property 8: `@given(...)` — confidence interval bounds are valid
- Property 9: `@given(...)` — base config unchanged after evaluation (mock pipeline)
- Property 10: `@given(st.lists(st.booleans(), min_size=10))` — failed evaluations produce NaN records
- Property 11: `@given(st.integers(0, 2**31), st.integers(1, 10))` — parallel and sequential produce same samples
- Property 12: `@given(...)` — output files exist after analysis
- Property 13: `@given(st.floats(0.1, 0.5))` — convergence flag set correctly based on CI width
- Property 14: `@given(st.floats(-100, 100), st.floats(-100, 100))` — invalid bounds cause exit
- Property 15: `@given(...)` — default parameters used when not specified

Tag format: `# Feature: sobol-sensitivity-analysis, Property N: <property_text>`
