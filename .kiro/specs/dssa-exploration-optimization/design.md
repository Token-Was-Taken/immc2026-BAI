# Design Document: DSSA Exploration Optimization

## Overview

The current DSSA optimizer uses a hardcoded `np.random.uniform(-2, 2, ...)` perturbation for all exploration-mode updates, regardless of iteration progress or solution quality. The `exploration_strategy.md` document establishes that this is suboptimal: a fixed range that is too large wastes iterations on infeasible regions, while one that is too small traps the algorithm in local optima.

This design introduces:
1. A **3-phase linear schedule** that reduces the exploration range as iterations progress.
2. A **stagnation detector** that temporarily boosts the range when the best fitness plateaus.
3. A **configurable exploitation alpha** to decouple fine-tuning from exploration.
4. **Iteration logging** of the active alpha value.

All changes are backward-compatible via Python dataclass defaults.

## Architecture

The change is entirely contained within two files:

```
hexdynamic/
  dssa_optimizer.py   ← primary change: DSSAConfig + DSSAOptimizer
```

No changes are needed to `coverage_model.py`, `grid_model.py`, or any pipeline files.

```mermaid
flowchart TD
    A[optimize loop: iteration t] --> B[_get_exploration_alpha(t)]
    B --> C{phase?}
    C -- early --> D[initial_alpha]
    C -- mid --> E[mid_alpha]
    C -- late --> F[final_alpha]
    D & E & F --> G[scheduled_alpha]
    G --> H{stagnation_count > threshold?}
    H -- yes --> I[effective_alpha = scheduled_alpha × stagnation_boost]
    H -- no --> J[effective_alpha = scheduled_alpha]
    I & J --> K[_update_producers(t, effective_alpha)]
    K --> L[_update_followers(effective_alpha)]
    L --> M[_update_scouts]
    M --> N[_update_best_solution]
    N --> O{fitness improved?}
    O -- yes --> P[reset stagnation_count = 0]
    O -- no --> Q[stagnation_count += 1]
```

## Components and Interfaces

### DSSAConfig (modified)

New fields added to the existing dataclass:

```python
@dataclass
class DSSAConfig:
    # --- existing fields (unchanged) ---
    population_size: int = 50
    max_iterations: int = 100
    producer_ratio: float = 0.2
    scout_ratio: float = 0.2
    ST: float = 0.8
    R2: float = 0.5          # deprecated, kept for compatibility
    use_time_aware_fitness: bool = False
    enable_iteration_output: bool = False
    iteration_output_dir: str = "./output/iterations"

    # --- new fields ---
    initial_alpha: float = 3.0       # exploration range in early phase (iter < 30%)
    mid_alpha: float = 2.0           # exploration range in mid phase (30%–70%)
    final_alpha: float = 1.0         # exploration range in late phase (iter >= 70%)
    exploitation_alpha: float = 1.0  # perturbation bound for exploitation-mode producers

    stagnation_threshold: int = 10   # consecutive non-improving iters before boost
    stagnation_tolerance: float = 1e-6  # minimum improvement to reset counter
    stagnation_boost: float = 1.5    # multiplier applied to alpha during stagnation
```

### DSSAOptimizer (modified)

New instance state:

```python
self.stagnation_count: int = 0
self.prev_best_fitness: float = float('-inf')
```

New private method:

```python
def _get_exploration_alpha(self, iteration: int) -> float:
    """Return the effective exploration alpha for this iteration,
    applying the 3-phase schedule and any active stagnation boost."""
    progress = iteration / max(self.config.max_iterations - 1, 1)

    if progress < 0.3:
        scheduled = self.config.initial_alpha
    elif progress < 0.7:
        scheduled = self.config.mid_alpha
    else:
        scheduled = self.config.final_alpha

    if self.stagnation_count > self.config.stagnation_threshold:
        return scheduled * self.config.stagnation_boost

    return scheduled
```

Modified methods (signature changes shown):

- `_update_producers(self, iteration: int, alpha: float)` — replaces hardcoded `-2,2` and `-1,1`
- `_update_followers(self, alpha: float)` — replaces hardcoded `-2,2`
- `optimize(...)` — calls `_get_exploration_alpha`, updates stagnation state, passes alpha down

### Stagnation Tracking (inside `optimize`)

```python
# after _update_best_solution():
if self.best_fitness - self.prev_best_fitness > self.config.stagnation_tolerance:
    self.stagnation_count = 0
else:
    self.stagnation_count += 1
self.prev_best_fitness = self.best_fitness
```

## Data Models

No new data structures. All new state lives on the `DSSAOptimizer` instance:

| Field | Type | Purpose |
|---|---|---|
| `stagnation_count` | `int` | Consecutive non-improving iterations |
| `prev_best_fitness` | `float` | Fitness at previous iteration for delta comparison |

`DSSAConfig` gains 7 new `float`/`int` fields, all with defaults (see above).

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

Property 1: Phase schedule correctness
*For any* valid `DSSAConfig` and any iteration index `t` in `[0, max_iterations)`, `_get_exploration_alpha(t)` (with stagnation_count = 0) should return `initial_alpha` when `t/max_iterations < 0.3`, `mid_alpha` when `0.3 <= t/max_iterations < 0.7`, and `final_alpha` otherwise.
**Validates: Requirements 1.2, 1.3, 1.4**

Property 2: Stagnation boost activation
*For any* `DSSAConfig` and any stagnation count strictly greater than `stagnation_threshold`, `_get_exploration_alpha(t)` should return a value equal to the scheduled alpha multiplied by `stagnation_boost`.
**Validates: Requirements 2.2**

Property 3: Stagnation counter reset
*For any* sequence of fitness values where at least one improvement exceeds `stagnation_tolerance`, the stagnation counter should be zero immediately after that improvement is processed.
**Validates: Requirements 2.3**

Property 4: Exploitation alpha separation
*For any* `exploitation_alpha` value, the perturbation applied in exploitation-mode producer updates should be bounded within `[-exploitation_alpha, exploitation_alpha]`.
**Validates: Requirements 3.2**

Property 5: DSSAConfig default values
*For* a `DSSAConfig()` instantiated with no arguments, all new fields should equal their documented defaults (`initial_alpha=3.0`, `mid_alpha=2.0`, `final_alpha=1.0`, `exploitation_alpha=1.0`, `stagnation_threshold=10`, `stagnation_tolerance=1e-6`, `stagnation_boost=1.5`).
**Validates: Requirements 1.5, 2.4, 3.1, 5.1, 5.2**

## Error Handling

- If `initial_alpha`, `mid_alpha`, or `final_alpha` are non-positive, the optimizer will still run but perturbations will be zero or negative-range — no explicit validation is added (out of scope; callers are responsible for sensible config).
- `stagnation_threshold = 0` means every iteration triggers a boost; this is valid but unusual. No guard needed.
- Division by zero in `_get_exploration_alpha` when `max_iterations = 1` is handled by `max(..., 1)`.

## Testing Strategy

**Framework**: `pytest` with `hypothesis` for property-based tests (already available in the Python ecosystem; add `hypothesis` to `hexdynamic/requirements.txt`).

**Unit tests** (`hexdynamic/tests/test_exploration_alpha.py`):
- Verify `DSSAConfig()` default values (Property 5)
- Verify phase boundaries at exact 30% and 70% thresholds
- Verify stagnation counter increments and resets with a mock fitness sequence

**Property-based tests** (same file, using `hypothesis`):
- Property 1: `@given(st.integers(0, 999), st.floats(1.0, 5.0), ...)` — schedule correctness across all iteration indices and alpha values
- Property 2: `@given(st.integers(...))` — stagnation boost for any count above threshold
- Property 3: `@given(st.lists(st.floats(...)))` — counter reset after any improving fitness sequence
- Property 4: `@given(st.floats(0.1, 10.0))` — exploitation perturbation bounded by exploitation_alpha

Each property test runs a minimum of 100 examples (hypothesis default).

Tag format: `# Feature: dssa-exploration-optimization, Property N: <text>`
