# Requirements Document

## Introduction

A Monte Carlo robustness analysis script for the wildlife protection optimization system. The script takes a base input JSON (e.g., `hexdynamic/robust/base.json`), runs N simulation trials where resource constraints are randomly sampled from defined uniform distributions, executes the DSSA optimizer for each trial, and produces a robustness analysis chart summarizing the distribution of optimization outcomes across all trials.

## Glossary

- **Base_Config**: The input JSON file that defines the map, terrain, species, coverage parameters, and DSSA configuration. Resource constraint values in this file serve as reference/nominal values.
- **Trial**: A single Monte Carlo simulation run with one randomly sampled set of resource constraints.
- **Constraint_Sample**: A set of resource counts drawn from the defined uniform distributions for a single trial.
- **Fitness**: The scalar objective value returned by the DSSA optimizer for a given deployment solution.
- **Protection_Benefit**: The total protection benefit metric computed by the pipeline for a given deployment solution.
- **Robustness_Analysis**: The statistical summary and visualization of fitness and protection benefit distributions across all Monte Carlo trials.
- **Monte_Carlo_Script**: The Python script (`monte_carlo_robust.py`) that orchestrates the simulation.
- **Distribution_Config**: The per-parameter sampling distributions, defaulting to: patrol Uniform(15,25), drones Uniform(2,6), cameras Uniform(8,15), base_camps Uniform(3,7).
- **Worker**: A subprocess spawned by `ProcessPoolExecutor` to execute one or more trials in parallel.
- **Worker_Count**: The number of parallel worker processes, controlled by `--workers` (default: `os.cpu_count()`).

## Requirements

### Requirement 1: Input Handling

**User Story:** As a researcher, I want to provide a base JSON config file to the script, so that the map, terrain, and DSSA settings are reused across all trials without modification.

#### Acceptance Criteria

1. WHEN the Monte_Carlo_Script is invoked with a path to a Base_Config JSON file, THE Monte_Carlo_Script SHALL load and parse the file as the base configuration for all trials.
2. IF the provided file path does not exist or is not valid JSON, THEN THE Monte_Carlo_Script SHALL print a descriptive error message and exit with a non-zero status code.
3. THE Monte_Carlo_Script SHALL accept a `--num-trials` argument (default: 100) specifying the number of Monte Carlo trials to run.
4. THE Monte_Carlo_Script SHALL accept an `--output-dir` argument (default: `./robust_results`) specifying where trial outputs and the final chart are saved.
5. THE Monte_Carlo_Script SHALL accept an optional `--seed` argument to set the random seed for reproducibility.
6. THE Monte_Carlo_Script SHALL accept an optional `--workers` argument (default: `os.cpu_count()`) specifying the number of parallel worker processes.

### Requirement 2: Parameter Sampling

**User Story:** As a researcher, I want resource constraints to be randomly sampled per trial, so that I can evaluate how the optimizer performs across a realistic range of resource availability scenarios.

#### Acceptance Criteria

1. WHEN generating a Constraint_Sample for each trial, THE Monte_Carlo_Script SHALL sample `total_patrol` from Uniform(15, 25) as an integer.
2. WHEN generating a Constraint_Sample for each trial, THE Monte_Carlo_Script SHALL sample `total_drones` from Uniform(2, 6) as an integer.
3. WHEN generating a Constraint_Sample for each trial, THE Monte_Carlo_Script SHALL sample `total_cameras` from Uniform(8, 15) as an integer.
4. WHEN generating a Constraint_Sample for each trial, THE Monte_Carlo_Script SHALL sample `total_camps` from Uniform(3, 7) as an integer.
5. THE Monte_Carlo_Script SHALL override only the `constraints` fields in the Base_Config with the sampled values; all other fields (map, terrain, DSSA config, coverage params) SHALL remain unchanged.
6. WHERE a `--seed` argument is provided, THE Monte_Carlo_Script SHALL initialize the random number generator with that seed before sampling begins, ensuring reproducible trial sequences.

### Requirement 3: Trial Execution

**User Story:** As a researcher, I want each trial to run the full optimization pipeline, so that the results reflect realistic optimizer behavior under each sampled resource scenario.

#### Acceptance Criteria

1. WHEN executing a trial, THE Monte_Carlo_Script SHALL invoke the existing `run_pipeline` function from `protection_pipeline.py` with the trial's modified config.
2. WHEN a trial completes successfully, THE Monte_Carlo_Script SHALL record the `best_fitness` and `total_protection_benefit` from the pipeline output.
3. WHEN a trial raises an exception, THE Monte_Carlo_Script SHALL log the error, record the trial as failed, and continue to the next trial without halting the simulation.
4. THE Monte_Carlo_Script SHALL print progress to stdout indicating the current trial number and total trials (e.g., `[Trial 5/100]`).
5. THE Monte_Carlo_Script SHALL record the sampled constraint values alongside the fitness and benefit for each trial.

### Requirement 4: Results Persistence

**User Story:** As a researcher, I want trial results saved to disk, so that I can inspect individual runs and re-generate charts without re-running the simulation.

#### Acceptance Criteria

1. WHEN all trials complete, THE Monte_Carlo_Script SHALL save a summary JSON file (`results_summary.json`) in the `--output-dir` containing all trial records (trial index, sampled constraints, fitness, protection benefit, and success/failure status).
2. THE Monte_Carlo_Script SHALL create the `--output-dir` directory if it does not already exist.

### Requirement 5: Robustness Analysis Chart

**User Story:** As a researcher, I want a robustness analysis chart generated automatically, so that I can visually assess the stability and distribution of optimizer performance across resource scenarios.

#### Acceptance Criteria

1. WHEN all trials complete, THE Monte_Carlo_Script SHALL generate and save a robustness analysis chart as `robustness_analysis.png` in the `--output-dir`.
2. THE Robustness_Analysis chart SHALL include a histogram or box plot of the `best_fitness` distribution across all successful trials.
3. THE Robustness_Analysis chart SHALL include a histogram or box plot of the `total_protection_benefit` distribution across all successful trials.
4. THE Robustness_Analysis chart SHALL display summary statistics (mean, standard deviation, min, max) for both fitness and protection benefit.
5. THE Robustness_Analysis chart SHALL include scatter plots or line plots showing how fitness and protection benefit vary with each sampled resource parameter (patrol, drones, cameras, camps).
6. WHEN fewer than 2 successful trials exist, THE Monte_Carlo_Script SHALL skip chart generation and print a warning message instead.

### Requirement 7: Per-Unit Resource Efficiency Analysis

**User Story:** As a researcher, I want to see per-unit resource efficiency metrics alongside the raw stability results, so that I can compare optimizer performance independent of resource scale.

#### Acceptance Criteria

1. WHEN computing trial results, THE Monte_Carlo_Script SHALL compute `resource_efficiency` for each successful trial as `total_protection_benefit / weighted_total_resource`, where `weighted_total_resource = w_patrol * total_patrol + w_drone * total_drones + w_camera * total_cameras + w_camp * total_camps`, and the weights are defined per Requirement 7.1.
2. THE Monte_Carlo_Script SHALL store `resource_efficiency` and `weighted_total_resource` in each successful trial record.
3. THE Robustness_Analysis chart SHALL include a histogram of the `resource_efficiency` distribution across all successful trials, annotated with mean, standard deviation, min, and max.
4. THE Robustness_Analysis chart SHALL include scatter plots showing how `resource_efficiency` varies with each sampled resource parameter (patrol, drones, cameras, camps).
5. THE Monte_Carlo_Script SHALL save a separate efficiency analysis chart as `efficiency_analysis.png` in the `--output-dir` containing the efficiency histogram and the four efficiency-vs-resource scatter plots.
6. WHEN fewer than 2 successful trials exist, THE Monte_Carlo_Script SHALL skip efficiency chart generation and print a warning message instead.

#### Requirement 7.1: Resource Weight Configuration

**User Story:** As a researcher, I want to assign different importance weights to each resource type when computing efficiency, so that the efficiency metric reflects the relative cost or strategic value of each resource rather than treating all resources equally.

**Rationale:** Different resource types have vastly different per-unit costs. A patrol ranger and a camera are not equivalent; weighting them equally would distort the efficiency metric. Weighted aggregation normalizes for cost differences.

##### Acceptance Criteria

1. THE Monte_Carlo_Script SHALL define default resource weights as follows:

   | Resource | Default Weight | Rationale |
   |----------|---------------|-----------|
   | patrol   | 0.40          | Most labor-intensive; highest per-unit cost |
   | camp     | 0.25          | Infrastructure cost; supports patrol logistics |
   | drone    | 0.20          | Equipment + maintenance cost |
   | camera   | 0.15          | Lowest per-unit cost; fixed infrastructure |

2. THE sum of all resource weights SHALL equal 1.0. IF user-provided weights do not sum to 1.0, THE Monte_Carlo_Script SHALL normalize them by dividing each weight by the sum.
3. THE Monte_Carlo_Script SHALL accept an optional `--weights` command-line argument as a comma-separated string `patrol:w,camp:w,drone:w,camera:w` (e.g., `--weights patrol:0.4,camp:0.25,drone:0.2,camera:0.15`). WHEN provided, these weights override the defaults.
4. THE Monte_Carlo_Script SHALL also read weights from the Base_Config JSON under the key `robustness_weights` (e.g., `{"patrol": 0.4, "camp": 0.25, "drone": 0.2, "camera": 0.15}`). WHEN both CLI `--weights` and JSON `robustness_weights` are provided, CLI SHALL take precedence.
5. THE Monte_Carlo_Script SHALL record the effective weights used (after normalization) in the `meta` block of `results_summary.json` for reproducibility.
6. THE efficiency analysis chart SHALL display the effective weights in a subtitle or annotation.

### Requirement 6: Parallel Trial Execution

**User Story:** As a researcher, I want trials to run in parallel across CPU cores, so that large Monte Carlo simulations complete in a fraction of the sequential time.

#### Acceptance Criteria

1. THE Monte_Carlo_Script SHALL execute trials concurrently using `concurrent.futures.ProcessPoolExecutor` with `max_workers` equal to the `--workers` value.
2. WHEN `--workers 1` is specified, THE Monte_Carlo_Script SHALL execute trials sequentially (single-process fallback), producing results identical to the non-parallel baseline.
3. THE Monte_Carlo_Script SHALL pre-generate all Constraint_Samples in the main process before dispatching workers, so that the sequence of samples is deterministic regardless of Worker_Count.
4. WHEN a worker process raises an exception, THE Monte_Carlo_Script SHALL record that trial as failed and continue collecting results from remaining workers without halting the simulation.
5. THE Monte_Carlo_Script SHALL print a progress line `[Trial X/N done]` as each future completes (completion order may differ from submission order).
6. THE Monte_Carlo_Script SHALL include `elapsed_seconds` and `trials_per_second` in the `meta` block of `results_summary.json`.
