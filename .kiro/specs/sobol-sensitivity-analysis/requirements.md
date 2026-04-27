 values to integers for integer-constrained parameters (all resource counts).
5. WHERE a `--seed` argument is provided, THE Sobol_Analysis_Script SHALL initialize the Sobol sequence generator with that seed, ensuring reproducible sample sequences.

### Requirement 4: Model Evaluation

**User Story:** As a researcher, I want each parameter combination to be evaluated by running the full optimization pipeline, so that sensitivity indices reflect realistic optimizer behavior.

#### Acceptance Criteria

1. WHEN evaluating a parameter combination, THE Sobol_Analysis_Script SHALL invoke the existing `run_pipeline` function from `protection_pipeline.py` with the modified config.
2. WHEN a model evaluation completes successfully, THE Sobol_Analysis_Script SHALL record the `best_fitness` and `total_protection_benefit` from the pipeline output.
3. WHEN a model evaluation raises an exception, THE Sobol_Analysis_Script SHALL log the error, record the evaluation as failed with NaN output, and continue to the next evaluation.
4. THE Sobol_Analysis_Script SHALL print progress to stdout indicating the current evaluation number and total evaluations (e.g., `[Eval 100/4108]`).
5. THE Sobol_Analysis_Script SHALL record the parameter values alongside the output metrics for each evaluation.

### Requirement 5: Sobol Index Computation

**User Story:** As a researcher, I want the script to compute first-order and total-order Sobol indices, so that I can understand both main effects and interaction effects of each parameter.

#### Acceptance Criteria

1. WHEN all model evaluations complete, THE Sobol_Analysis_Script SHALL compute first-order Sobol indices (S_i) for each parameter using the `SALib.analyze.sobol` function.
2. WHEN all model evaluations complete, THE Sobol_Analysis_Script SHALL compute total-order Sobol indices (S_Ti) for each parameter.
3. THE Sobol_Analysis_Script SHALL compute bootstrap confidence intervals for each index using at least 1000 bootstrap resamples.
4. THE Sobol_Analysis_Script SHALL normalize indices such that the sum of first-order indices is less than or equal to 1 (equality holds when there are no interactions).
5. THE Sobol_Analysis_Script SHALL handle NaN values in the output array by excluding those evaluations from index computation with a warning.

### Requirement 6: Results Persistence

**User Story:** As a researcher, I want evaluation results and sensitivity indices saved to disk, so that I can inspect the data and reproduce the analysis.

#### Acceptance Criteria

1. WHEN all evaluations complete, THE Sobol_Analysis_Script SHALL save a raw evaluation results JSON file (`evaluations.json`) containing all parameter combinations and their outputs.
2. THE Sobol_Analysis_Script SHALL save a sensitivity indices JSON file (`sobol_indices.json`) containing first-order and total-order indices with confidence intervals for each parameter.
3. THE Sobol_Analysis_Script SHALL create the `--output-dir` directory if it does not already exist.
4. THE Sobol_Analysis_Script SHALL save the parameter definitions used in the analysis for reproducibility.

### Requirement 7: Sensitivity Visualization

**User Story:** As a researcher, I want visualizations of the sensitivity indices, so that I can quickly identify the most influential parameters.

#### Acceptance Criteria

1. WHEN all indices are computed, THE Sobol_Analysis_Script SHALL generate and save a bar chart (`sobol_indices.png`) showing first-order and total-order indices side by side for each parameter.
2. THE Sobol_Analysis_Script SHALL include error bars on the bar chart representing the 95% bootstrap confidence intervals.
3. THE Sobol_Analysis_Script SHALL generate a ranking plot showing parameters sorted by total-order index in descending order.
4. THE Sobol_Analysis_Script SHALL generate a scatter plot matrix showing pairwise relationships between parameters and outputs.
5. WHEN fewer than 10 successful evaluations exist, THE Sobol_Analysis_Script SHALL skip visualization and print a warning.

### Requirement 8: Parallel Model Evaluation

**User Story:** As a researcher, I want model evaluations to run in parallel across CPU cores, so that large Sobol analyses complete in reasonable time.

#### Acceptance Criteria

1. THE Sobol_Analysis_Script SHALL execute model evaluations concurrently using `concurrent.futures.ProcessPoolExecutor` with `max_workers` equal to the `--workers` value.
2. WHEN `--workers 1` is specified, THE Sobol_Analysis_Script SHALL execute evaluations sequentially (single-process fallback).
3. THE Sobol_Analysis_Script SHALL pre-generate all parameter combinations in the main process before dispatching workers, ensuring deterministic sample sequences regardless of worker count.
4. WHEN a worker process raises an exception, THE Sobol_Analysis_Script SHALL record that evaluation as failed (NaN) and continue without halting.
5. THE Sobol_Analysis_Script SHALL include `elapsed_seconds` and `evaluations_per_second` in the output metadata.

### Requirement 9: Convergence Diagnostics

**User Story:** As a researcher, I want convergence diagnostics for the sensitivity indices, so that I can assess whether the sample size was sufficient.

#### Acceptance Criteria

1. WHEN computing Sobol indices, THE Sobol_Analysis_Script SHALL compute the width of the 95% bootstrap confidence interval for each index.
2. THE Sobol_Analysis_Script SHALL flag parameters where the confidence interval width exceeds 0.2 as "not converged" in the output.
3. THE Sobol_Analysis_Script SHALL print a summary of convergence status at the end of the analysis.
4. THE Sobol_Analysis_Script SHALL include convergence metrics in the `sobol_indices.json` output file.
