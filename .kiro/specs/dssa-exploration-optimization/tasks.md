# Implementation Plan: DSSA Exploration Optimization

## Overview

Implement adaptive exploration range scheduling in the DSSA optimizer. All changes are in `hexdynamic/dssa_optimizer.py`. Tests go in `hexdynamic/tests/test_exploration_alpha.py`.

## Tasks

- [x] 1. Extend DSSAConfig with new fields
  - Add `initial_alpha`, `mid_alpha`, `final_alpha`, `exploitation_alpha`, `stagnation_threshold`, `stagnation_tolerance`, `stagnation_boost` to the `DSSAConfig` dataclass with documented defaults
  - _Requirements: 1.5, 2.4, 3.1, 5.1, 5.2_

- [x] 1.1 Write example test for DSSAConfig defaults
  - Instantiate `DSSAConfig()` with no arguments and assert all new fields equal their documented defaults
  - **Property 5: DSSAConfig default values**
  - **Validates: Requirements 1.5, 2.4, 3.1, 5.1, 5.2**

- [x] 2. Implement `_get_exploration_alpha` method
  - Add `_get_exploration_alpha(self, iteration: int) -> float` to `DSSAOptimizer`
  - Implement 3-phase schedule: `< 0.3` → `initial_alpha`, `0.3–0.7` → `mid_alpha`, `>= 0.7` → `final_alpha`
  - Apply `stagnation_boost` multiplier when `self.stagnation_count > self.config.stagnation_threshold`
  - Handle `max_iterations = 1` edge case with `max(..., 1)`
  - _Requirements: 1.2, 1.3, 1.4, 2.2_

- [x] 2.1 Write property test for phase schedule correctness
  - Use `hypothesis` to generate random `(iteration, max_iterations, initial_alpha, mid_alpha, final_alpha)` tuples
  - Assert the returned alpha matches the expected phase value when stagnation_count = 0
  - **Property 1: Phase schedule correctness**
  - **Validates: Requirements 1.2, 1.3, 1.4**
  - `# Feature: dssa-exploration-optimization, Property 1: phase schedule correctness`

- [x] 2.2 Write property test for stagnation boost activation
  - Use `hypothesis` to generate stagnation counts above `stagnation_threshold`
  - Assert `_get_exploration_alpha` returns `scheduled_alpha * stagnation_boost`
  - **Property 2: Stagnation boost activation**
  - **Validates: Requirements 2.2**
  - `# Feature: dssa-exploration-optimization, Property 2: stagnation boost activation`

- [x] 3. Add stagnation tracking state and update logic
  - Initialize `self.stagnation_count = 0` and `self.prev_best_fitness = float('-inf')` in `__init__`
  - After `_update_best_solution()` in the `optimize` loop, compare `best_fitness` to `prev_best_fitness` using `stagnation_tolerance` and increment or reset `stagnation_count`
  - _Requirements: 2.1, 2.3_

- [x] 3.1 Write property test for stagnation counter reset
  - Use `hypothesis` to generate lists of fitness values with at least one improvement
  - Simulate the counter update logic and assert the counter is zero after an improvement
  - **Property 3: Stagnation counter reset**
  - **Validates: Requirements 2.3**
  - `# Feature: dssa-exploration-optimization, Property 3: stagnation counter reset`

- [-] 4. Wire alpha into `_update_producers` and `_update_followers`
  - Change `_update_producers(self, iteration: int)` signature to `_update_producers(self, iteration: int, alpha: float)`
  - Replace `np.random.uniform(-2, 2, ...)` with `np.random.uniform(-alpha, alpha, ...)`
  - Replace `np.random.uniform(-1, 1, ...)` with `np.random.uniform(-self.config.exploitation_alpha, self.config.exploitation_alpha, ...)`
  - Change `_update_followers(self)` signature to `_update_followers(self, alpha: float)`
  - Replace `np.random.uniform(-2, 2, ...)` with `np.random.uniform(-alpha, alpha, ...)`
  - Update the `optimize` loop to call `_get_exploration_alpha(iteration)` and pass the result to both methods
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 3.2_

- [x] 4.1 Write property test for exploitation alpha separation
  - Use `hypothesis` to generate `exploitation_alpha` values
  - Verify that the perturbation vector elements are bounded within `[-exploitation_alpha, exploitation_alpha]`
  - **Property 4: Exploitation alpha separation**
  - **Validates: Requirements 3.2**
  - `# Feature: dssa-exploration-optimization, Property 4: exploitation alpha separation`

- [x] 5. Update iteration log output
  - In the `optimize` loop print statement, append `α={effective_alpha:.2f}` to the log line
  - When `stagnation_count > stagnation_threshold`, append `[STAGNATION_BOOST]` to the log line
  - _Requirements: 4.1, 4.2_

- [x] 6. Add `hypothesis` to requirements and checkpoint
  - Add `hypothesis` to `hexdynamic/requirements.txt`
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- All new `DSSAConfig` fields have defaults, so no existing call sites need updating
- The only breaking change risk is the `_update_producers`/`_update_followers` signature — both are private methods called only from `optimize`, so no external callers are affected
