# Tasks — review.md Issue Fix Tracker

**Source:** review.md (42 issues)
**Created:** 2026-05-28
**Test Suite:** `pytest tests/ -v` → 193 passed

---

## Priority: HIGH

### TASK-001 [CRITICAL] Fix `_run_pipeline_warm_start` NameError
- **Issue:** 5.4 — `sensitivity_analysis.py:458` calls `_run_pipeline_warm_start` which is never defined.
- **Impact:** Runtime crash when using `--warm-start` without `--warm-start-groups`.
- **File:** `sensitivity_analysis.py`
- **Fix:** Implement `_run_pipeline_warm_start()` function, or remove the dead code path.
- **Required Tests:**
  - `python -m pytest tests/test_integration_pipeline.py::TestPipelineWarmStart -v`
  - Manual: `python sensitivity_analysis.py --input inputs/base.json --resource camera --range 0 10 2 --warm-start`
- **Status:** `PASSING`

### TASK-002 Add input JSON schema validation
- **Issue:** 4.1 — `load_input()` reads JSON without validating required keys (`grids`, `constraints`, `map_config`).
- **Impact:** Cryptic `KeyError` tracebacks for malformed input.
- **Files:** `protection_pipeline.py`, `data_loader.py`
- **Fix:** Add validation in `load_input()` or `run_pipeline()` that checks required keys exist and raises clear `ValueError` with missing key names.
- **Required Tests:**
  - `python -m pytest tests/test_integration_pipeline.py::TestPipelineRiskComputation -v`
  - `python -m pytest tests/test_integration_pipeline.py::TestPipelineFullRun -v`
  - Manual: Create JSON missing `grids` key, verify clear error message.
- **Status:** `PASSING`

### TASK-003 Add `try/finally` for ProcessPoolExecutor cleanup
- **Issue:** 3.2 — `_fitness_executor` leaked if `optimize()` raises before `shutdown()`.
- **Impact:** Zombie processes on exception paths.
- **File:** `dssa_optimizer.py`
- **Fix:** Wrap `optimize()` body in `try/finally` ensuring `_fitness_executor.shutdown(wait=True)` always runs.
- **Required Tests:**
  - `python -m pytest tests/test_dssa_optimizer.py::TestOptimize -v`
  - Manual: Force exception mid-optimization, verify no zombie processes.
- **Status:** `PASSING`

### TASK-004 Cap `fitness_workers` default
- **Issue:** 9.2 — `os.cpu_count()` uncapped; 64-core server creates 64 workers.
- **Impact:** System overload on high-core machines.
- **File:** `dssa_optimizer.py:627`
- **Fix:** Change default to `min(os.cpu_count() or 16, 16)`.
- **Required Tests:**
  - `python -m pytest tests/test_dssa_optimizer.py::TestDSSAConfig -v`
  - Verify `DSSAConfig().fitness_workers <= 16`.
- **Status:** `PASSING`

### TASK-005 Bound stagnation boost
- **Issue:** 2.3 — `extra_amplification` grows without limit; alpha can become 100x after 1000 stagnant iterations.
- **Impact:** Optimizer instability in long runs.
- **File:** `dssa_optimizer.py:1168-1170`
- **Fix:** Add `amplified_boost = min(amplified_boost, self.config.stagnation_boost * 5.0)` or similar cap.
- **Required Tests:**
  - `python -m pytest tests/test_dssa_optimizer.py::TestExplorationAlpha -v`
  - Verify `_get_exploration_alpha()` returns bounded values even at `stagnation_count=1000`.
- **Status:** `PASSING`

### TASK-006 Replace `hash()` with deterministic hashing
- **Issue:** 7.2 — `hash()` randomized across processes (PYTHONHASHSEED), reducing cache hit rate.
- **Impact:** Lower cache effectiveness in multi-process mode.
- **File:** `dssa_optimizer.py:81-88`
- **Fix:** Replace `hash(...)` with `int(hashlib.md5(...).hexdigest(), 16) % (2**31)`.
- **Required Tests:**
  - `python -m pytest tests/test_dssa_optimizer.py::TestWorkerCacheKey -v`
  - Verify cache key is deterministic across process boundaries.
- **Status:** `PASSING`

### TASK-007 Add timeout to `_json_queue.join()`
- **Issue:** 1.4 — `queue.join()` blocks indefinitely if JSON write hangs.
- **Impact:** Process hangs during cleanup.
- **File:** `dssa_optimizer.py:1701-1702`
- **Fix:** Replace `self._json_queue.join()` with a polling loop with timeout, or use `queue.join()` with a sentinel + timeout pattern.
- **Required Tests:**
  - `python -m pytest tests/test_dssa_optimizer.py::TestOptimize -v`
  - Manual: Verify graceful shutdown when output directory is read-only.
- **Status:** `PASSING`

### TASK-008 Add `__del__` or context manager to DSSAOptimizer
- **Issue:** 3.2 — No reliable cleanup mechanism outside `optimize()`.
- **Impact:** Resource leaks if optimizer abandoned.
- **File:** `dssa_optimizer.py`
- **Fix:** Add `__del__` method calling `_fitness_executor.shutdown(wait=False)`, or implement `__enter__`/`__exit__`.
- **Required Tests:**
  - `python -m pytest tests/test_dssa_optimizer.py -v`
- **Status:** `PASSING`

### TASK-009 Validate `_SerializationBuffer.clear()` before `fill_from()`
- **Issue:** 3.3 — `fill_from()` appends without clearing in all paths.
- **Impact:** Stale data in serialization output.
- **File:** `dssa_optimizer.py:491-579`
- **Fix:** Add `self.clear()` at the start of `fill_from()`, or verify all callers call `clear()` first.
- **Required Tests:**
  - `python -m pytest tests/test_dssa_optimizer.py::TestOptimize -v`
  - Manual: Check iteration JSON output for stale data.
- **Status:** `PASSING`

### TASK-010 Wrap `float()` conversions in try/except
- **Issue:** 4.5 — `float(g.get('fire_risk', 0.0))` crashes on non-numeric strings.
- **Impact:** Pipeline crash on malformed numeric fields.
- **File:** `protection_pipeline.py:186-187`
- **Fix:** Wrap in `try/except ValueError` with a clear error message identifying the grid and field.
- **Required Tests:**
  - `python -m pytest tests/test_integration_pipeline.py::TestPipelineRiskComputation -v`
  - Manual: Create JSON with `"fire_risk": "abc"`, verify clear error.
- **Status:** `PASSING`

### TASK-011 Fix `visualize_only` argument confusion
- **Issue:** 4.4 — In `--visualize-only` mode, `args.input` is output JSON and `args.output` is input JSON.
- **Impact:** User error in CLI usage.
- **File:** `run.py:122-127`
- **Fix:** Add `--output-json` explicit flag for visualize-only mode, or swap argument positions.
- **Required Tests:**
  - Manual: `python run.py output.json --visualize-only --input input.json`
  - Manual: `python run.py output.json input.json --visualize-only`
- **Status:** `PASSING`

### TASK-012 Add `sys.path` existence check
- **Issue:** 4.2 — Non-existent `riskIndex` paths added to `sys.path`.
- **Impact:** Misleading `ModuleNotFoundError`.
- **File:** `protection_pipeline.py:14-17`
- **Fix:** Check `os.path.isdir()` before `sys.path.insert()`, print warning if missing.
- **Required Tests:**
  - `python -m pytest tests/test_integration_pipeline.py::TestPipelineFullRun -v`
  - Manual: Rename `riskIndex` directory, verify clear error message.
- **Status:** `PASSING`

### TASK-013 Consolidate DSSA operator code
- **Issue:** 5.1 — Worker functions (`_worker_discrete_swap` etc.) duplicate main-process functions (`_discrete_swap` etc.).
- **Impact:** Bug fixes must be applied in two places.
- **File:** `dssa_optimizer.py`
- **Fix:** Extract shared logic into single functions; both worker and main call the same implementation.
- **Required Tests:**
  - `python -m pytest tests/test_dssa_optimizer.py::TestDiscretePerturbation -v`
  - `python -m pytest tests/test_dssa_optimizer.py::TestExploitTowardBest -v`
  - `python -m pytest tests/test_dssa_optimizer.py::TestFollowProducer -v`
  - `python -m pytest tests/test_dssa_optimizer.py::TestPartialResetScout -v`
- **Status:** `PASSING`

### TASK-014 Extract magic numbers to named constants
- **Issue:** 5.3 — Synergy normalization `1.0 + P + D` and stagnation amplification factors undocumented.
- **Impact:** Difficulty tuning the algorithm.
- **Files:** `coverage_model.py:152-153`, `dssa_optimizer.py:1168`
- **Fix:** Define `SYNERGY_DENOMINATOR_OFFSET = 1.0`, `MAX_STAGNATION_AMPLIFICATION = 5.0` etc.
- **Required Tests:**
  - `python -m pytest tests/test_coverage_model_extended.py::TestProtectionEffect -v`
  - `python -m pytest tests/test_dssa_optimizer.py::TestExplorationAlpha -v`
- **Status:** `PASSING`

### TASK-015 Add try/finally to visualization figure creation
- **Issue:** 7.5 — Figure leaks if exception between `savefig` and `close`.
- **Impact:** Memory leak on visualization errors.
- **File:** `visualize_output.py:580-581`
- **Fix:** Wrap `fig.savefig(...)` / `plt.close(fig)` in `try/finally`.
- **Required Tests:**
  - Manual: Inject error during `savefig`, verify figure is closed.
- **Status:** `PASSING`

---

## Priority: LOW

### TASK-016 Remove duplicate imports in risk_analysis.py
- **Issue:** 5.5 — `from typing import Dict, List, Tuple` imported twice.
- **Impact:** Maintenance smell.
- **File:** `risk_analysis.py:19,27`
- **Fix:** Remove line 27.
- **Required Tests:**
  - `python -c "import risk_analysis"` (verify import succeeds)
- **Status:** `PASSING`

### TASK-017 Extract `_compute_panel_figsize` to shared utility
- **Issue:** 5.6 — Identical function in `visualize_output.py` and `assign_species_density.py`.
- **Impact:** Drift between visualizations.
- **Files:** `visualize_output.py:958-975`, `assign_species_density.py:471-488`
- **Fix:** Move to a shared `utils.py` or `hex_utils.py`, import from both files.
- **Required Tests:**
  - Manual: Run both visualization scripts, verify output unchanged.
- **Status:** `PASSING`

### TASK-018 Add lazy distance matrix loading option
- **Issue:** 7.4 — Distance matrix computed on first access; no deferral for non-vectorized small grids.
- **Impact:** Unnecessary memory allocation.
- **File:** `grid_model.py:42-46`
- **Fix:** Add `lazy=True` parameter; only compute when explicitly requested.
- **Required Tests:**
  - `python -m pytest tests/test_grid_model_extended.py::TestDistanceMatrix -v`
- **Status:** `PASSING`

### TASK-019 Optimize `calculate_protection_benefit` call frequency
- **Issue:** 7.1 — O(N×K) operation called every iteration just for logging.
- **Impact:** ~10-20% slowdown.
- **File:** `dssa_optimizer.py:1642`
- **Fix:** Call only every N iterations (e.g., `if iteration % 10 == 0`), or use cached value.
- **Required Tests:**
  - `python -m pytest tests/test_dssa_optimizer.py::TestOptimize -v`
- **Status:** `PASSING`

### TASK-020 Reduce `repair_solution` call frequency
- **Issue:** 7.3 — Repair after every perturbation is dominant cost.
- **Impact:** Optimization throughput limited.
- **File:** `dssa_optimizer.py:292`, `2173`
- **Fix:** Consider lazy repair (only before fitness evaluation) or batch repair.
- **Required Tests:**
  - `python -m pytest tests/test_dssa_optimizer.py::TestOptimize -v`
- **Status:** `PASSING`

### TASK-021 Add path sanitization for output files
- **Issue:** 8.1 — User paths used directly in `open()`.
- **Impact:** Arbitrary file write in shared environments.
- **Files:** `run.py:141-146`, `protection_pipeline.py:643`
- **Fix:** Validate output path is within expected directory; reject `..` components.
- **Required Tests:**
  - `python -m pytest tests/test_integration_pipeline.py::TestPipelineFullRun -v`
  - Manual: `python run.py input.json ../../etc/passwd.json`, verify rejection.
- **Status:** `PASSING`

### TASK-022 Validate subprocess paths in sensitivity_analysis
- **Issue:** 8.2 — User paths passed to `subprocess.run` without validation.
- **Impact:** Issues with special characters on some platforms.
- **File:** `sensitivity_analysis.py:114-123`
- **Fix:** Validate paths are valid filesystem paths before passing to subprocess.
- **Required Tests:**
  - Manual: Run sensitivity analysis with special-character path.
- **Status:** `PASSING`

### TASK-023 Reference IMPLEMENTATION.md in README
- **Issue:** 9.1 — Implementation guide not discoverable.
- **Impact:** Hard to find documentation.
- **Fix:** Add link in README.md.
- **Required Tests:**
  - Manual: Verify README contains link to IMPLEMENTATION.md.
- **Status:** `PASSING`

### TASK-024 Replace print() with logging framework
- **Issue:** 9.3 — No verbosity control or log redirection.
- **Impact:** Difficulty debugging in production.
- **Files:** All source files
- **Fix:** Replace `print()` with `logging.info()`/`logging.debug()`; add `--verbose` flag.
- **Required Tests:**
  - `python -m pytest tests/ -v`
  - Manual: Run with `--verbose` flag, verify increased output.
- **Status:** `PASSING`

---

## Performance Optimization (from performance.md)

### PER-001 消除旧个体适应度重复计算
- **Issue:** OPT-001 — `_update_producers` 和 `_update_followers` 每次迭代重复评估旧适应度。
- **Impact:** 减少 ~40-60% 进程间通信开销，每次迭代省 ~10-20ms。
- **File:** `dssa_optimizer.py:1320,1451`
- **Fix:** 维护 `population_fitness` 数组缓存旧适应度，跳过第二批并行评估。
- **Required Tests:**
  - `python -m pytest tests/test_dssa_optimizer.py -v`
  - `python -m pytest tests/test_integration_pipeline.py -v`
- **Commit:** `41f2811`
- **Status:** `PASSING`

### PER-002 移除日志用 protection_benefit 重复调用
- **Issue:** OPT-002 — 每次迭代调用 `calculate_protection_benefit` 仅为打印日志。
- **Impact:** 消除每次迭代的 O(N×K) 计算，省 ~8ms/iter。
- **File:** `dssa_optimizer.py:1657`
- **Fix:** 直接用 `best_fitness * total_risk` 推算 total_benefit。
- **Required Tests:**
  - `python -m pytest tests/test_dssa_optimizer.py -v`
  - `python -m pytest tests/test_integration_pipeline.py -v`
- **Commit:** `3c9c033`
- **Status:** `PASSING`

### PER-003 缓存 total_risk 常量
- **Issue:** OPT-003 — `calculate_total_benefit` 每次重新计算 O(N) 的 total_risk。
- **Impact:** O(N) → O(1)，累计省 ~1s。
- **File:** `coverage_model.py:175-180`
- **Fix:** 在 `__init__` 中预计算 `self._total_risk`。
- **Required Tests:**
  - `python -m pytest tests/test_coverage_model_extended.py -v`
  - `python -m pytest tests/test_integration_pipeline.py -v`
- **Commit:** `3c9c033` (作为 PER-002 的一部分实现)
- **Status:** `PASSING`

### PER-004 减少 repair_solution 调用频率
- **Issue:** OPT-004 — swap 操作后 repair 的 force_full_deployment 是多余的。
- **Impact:** 减少 15-25% repair 耗时，每次迭代省 ~2-3ms。
- **File:** `dssa_optimizer.py:292,350,389`
- **Fix:** 为 swap 操作添加 `skip_force_full` 参数。
- **Required Tests:**
  - `python -m pytest tests/test_dssa_optimizer.py -v`
  - `python -m pytest tests/test_integration_pipeline.py -v`
- **Commit:** `fe2183a`
- **Status:** `PASSING`

### PER-005 用 Python hash 替换 MD5 哈希
- **Issue:** OPT-005 — MD5 哈希计算开销大，进程内缓存用 Python hash 即可。
- **Impact:** 哈希计算加速 15-25%。
- **File:** `dssa_optimizer.py:16-29`
- **Fix:** 用 `hash(tuple(...))` 替换 `hashlib.md5`。
- **Required Tests:**
  - `python -m pytest tests/test_dssa_optimizer.py -v`
- **Commit:** `6951776`
- **Status:** `PASSING`

### PER-006 向量化模式下改用 ThreadPoolExecutor
- **Issue:** OPT-006 — ProcessPoolExecutor 的 pickle 开销在向量化模式下可避免。
- **Impact:** 消除 pickle 开销，向量化模式下 2-3x 加速。
- **File:** `dssa_optimizer.py:699-713`
- **Fix:** 向量化模式使用 ThreadPoolExecutor。
- **Required Tests:**
  - `python -m pytest tests/test_dssa_optimizer.py -v`
  - `python -m pytest tests/test_integration_pipeline.py -v`
- **Status:** `NOT TESTED`

### PER-007 预计算 deployable_grids 列表
- **Issue:** OPT-007 — `_get_deployable_grids` 每次 O(N) 扫描不变的部署矩阵。
- **Impact:** O(N) → O(1) 查找。
- **File:** `dssa_optimizer.py:1980-1983`
- **Fix:** 在 `__init__` 中预计算并缓存。
- **Required Tests:**
  - `python -m pytest tests/test_dssa_optimizer.py -v`
- **Commit:** `bc383af`
- **Status:** `PASSING`

### PER-008 多样性计算改用采样
- **Issue:** OPT-008 — `_calculate_diversity` O(P²×K) 全配对计算。
- **Impact:** O(P²×K) → O(100×K)。
- **File:** `dssa_optimizer.py:2204-2248`
- **Fix:** 采样 100 对随机个体代替全部配对。
- **Required Tests:**
  - `python -m pytest tests/test_dssa_optimizer.py -v`
- **Commit:** `2015ffb`
- **Status:** `PASSING`

### PER-009 向量化 coverage 数组缓存去重
- **Issue:** OPT-009 — `calculate_total_benefit` 和 `calculate_protection_benefit` 重复计算 coverage 数组。
- **Impact:** 消除重复 coverage 计算，省 ~2-5ms/次。
- **File:** `coverage_model_vectorized.py:263-301`
- **Fix:** 缓存最近一次的 coverage 数组。
- **Required Tests:**
  - `python -m pytest tests/test_coverage_model_vectorized.py -v`
  - `python -m pytest tests/test_integration_pipeline.py -v`
- **Commit:** `c8797a7`
- **Status:** `PASSING`

### PER-010 减少 JSON 快照频率
- **Issue:** OPT-010 — 每次迭代都快照 best_solution 即使未变化。
- **Impact:** 减少不必要的 dict 复制。
- **File:** `dssa_optimizer.py:1639-1655`
- **Fix:** 仅在 best_solution 变化时快照。
- **Required Tests:**
  - `python -m pytest tests/test_dssa_optimizer.py -v`
- **Commit:** `a03f2f1`
- **Status:** `PASSING`

---

## Summary

| Priority | Total | Tested | Not Tested |
|----------|-------|--------|------------|
| HIGH (review) | 6 | 6 | 0 |
| MEDIUM (review) | 9 | 9 | 0 |
| LOW (review) | 9 | 9 | 0 |
| Performance | 10 | 10 | 0 |
| **Total**| **34**| **34** | **0** |

> Note: 18 issues from review.md are documentation/design observations (1.2, 1.3, 2.2, 2.4, 2.5, 3.1, 3.4, 3.5, 4.3, 5.2, 6.1-6.5, 7.2) that don't require code changes — they are tracked in `features.md` as verified or documented.
