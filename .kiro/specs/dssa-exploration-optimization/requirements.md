# Requirements Document

## Introduction

The DSSA (Dynamic Sparrow Search Algorithm) optimizer currently uses a fixed exploration range of `[-2, 2]` for all random perturbations during both producer and follower escape/exploration updates. The `exploration_strategy.md` document identifies that this static range is suboptimal: too large a range wastes iterations on invalid regions, while too small a range traps the algorithm in local optima. This feature introduces a dynamic, adaptive exploration range strategy that adjusts the perturbation magnitude based on iteration progress, solution quality, and the nature of the discrete deployment problem.

## Glossary

- **DSSA_Optimizer**: The `DSSAOptimizer` class in `hexdynamic/dssa_optimizer.py` that runs the sparrow search optimization.
- **Exploration_Range**: The scalar bound `α` used in `np.random.uniform(-α, α, ...)` during escape/exploration updates.
- **Exploitation_Mode**: The update path taken when `R2 < ST`; moves toward the best known solution.
- **Exploration_Mode**: The update path taken when `R2 >= ST`; applies a random perturbation to escape local optima.
- **Producer**: A top-`producer_ratio` fraction of the population responsible for finding new food sources.
- **Follower**: The middle fraction of the population that follows producers.
- **Scout**: The bottom `scout_ratio` fraction of the population that reinitializes when fitness is poor.
- **DSSAConfig**: The configuration dataclass `DSSAConfig` that controls optimizer hyperparameters.
- **Fitness**: The scalar value returned by `evaluate_fitness()`, representing normalized protection benefit.
- **Stagnation**: A condition where the best fitness does not improve for a configurable number of consecutive iterations.

## Requirements

### Requirement 1: Dynamic Exploration Range Scheduling

**User Story:** As a researcher running DSSA optimization, I want the exploration range to automatically decrease over time, so that the algorithm explores broadly early on and refines solutions precisely in later iterations.

#### Acceptance Criteria

1. WHEN the optimizer is initialized, THE DSSA_Optimizer SHALL set the exploration range to a configurable `initial_alpha` value (default 3.0).
2. WHEN an iteration falls within the first 30% of `max_iterations`, THE DSSA_Optimizer SHALL use an exploration range of `initial_alpha`.
3. WHEN an iteration falls between 30% and 70% of `max_iterations`, THE DSSA_Optimizer SHALL use an exploration range of `mid_alpha` (default 2.0).
4. WHEN an iteration falls in the last 30% of `max_iterations`, THE DSSA_Optimizer SHALL use an exploration range of `final_alpha` (default 1.0).
5. THE DSSAConfig SHALL expose `initial_alpha`, `mid_alpha`, and `final_alpha` as configurable float parameters with the defaults above.

### Requirement 2: Stagnation-Based Exploration Boost

**User Story:** As a researcher, I want the optimizer to automatically widen its exploration range when it gets stuck, so that it can escape local optima without manual intervention.

#### Acceptance Criteria

1. THE DSSA_Optimizer SHALL track the number of consecutive iterations in which `best_fitness` does not improve by more than a configurable `stagnation_tolerance` (default 1e-6).
2. WHEN the stagnation counter exceeds a configurable `stagnation_threshold` (default 10 iterations), THE DSSA_Optimizer SHALL temporarily increase the current exploration range by a configurable `stagnation_boost` multiplier (default 1.5×).
3. WHEN the best fitness improves after a stagnation boost, THE DSSA_Optimizer SHALL reset the stagnation counter to zero and restore the scheduled exploration range.
4. THE DSSAConfig SHALL expose `stagnation_threshold`, `stagnation_tolerance`, and `stagnation_boost` as configurable parameters.

### Requirement 3: Exploitation Range Separation

**User Story:** As a researcher, I want the small-step exploitation perturbation (currently `[-1, 1]`) to also be configurable and separate from the exploration range, so that fine-tuning behavior can be adjusted independently.

#### Acceptance Criteria

1. THE DSSAConfig SHALL expose an `exploitation_alpha` parameter (default 1.0) that controls the perturbation range used in exploitation-mode producer updates (currently hardcoded as `np.random.uniform(-1, 1, ...)`).
2. WHEN a producer is updated in exploitation mode (non-best producer path), THE DSSA_Optimizer SHALL use `exploitation_alpha` as the perturbation bound instead of the hardcoded value `1`.

### Requirement 4: Exploration Range Logging

**User Story:** As a researcher, I want to see the active exploration range in the iteration log, so that I can verify the schedule is working as expected.

#### Acceptance Criteria

1. WHEN printing iteration progress, THE DSSA_Optimizer SHALL include the current effective exploration range `α` in the output line.
2. WHEN a stagnation boost is active, THE DSSA_Optimizer SHALL annotate the log line with `[STAGNATION_BOOST]` in addition to the existing `[ESCAPE=N]` annotation.

### Requirement 5: Backward Compatibility

**User Story:** As an existing user of the DSSA optimizer, I want the new parameters to have sensible defaults so that existing code that does not pass the new config fields continues to work without modification.

#### Acceptance Criteria

1. IF a caller creates a `DSSAConfig` without specifying any of the new parameters, THEN THE DSSA_Optimizer SHALL behave with the new default values and produce valid optimization results.
2. THE DSSAConfig SHALL remain a Python dataclass with all new fields having default values, so that existing instantiations without keyword arguments are unaffected.
