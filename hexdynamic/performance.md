# DSSA 性能优化分析报告

**日期:** 2026-05-28
**分析范围:** `dssa_optimizer.py`, `coverage_model.py`, `coverage_model_vectorized.py`
**测试基准:** N=200-2000 grids, P=50 population, I=200 iterations

---

## 执行摘要

DSSA 优化器存在 **7 个主要性能瓶颈**，涵盖算法复杂度、冗余计算、过度内存分配和并行化机会。最核心的问题是：(1) 旧个体适应度重复计算，(2) 日志输出触发完整覆盖计算，(3) O(P²) 多样性计算。

**预估总优化潜力：2-8x 加速**

| 优化组合 | 每次迭代耗时 | 200 次迭代总耗时 | 加速比 |
|----------|-------------|-----------------|--------|
| 当前基线 (非向量化) | ~57ms | ~11.4s | 1x |
| P0+P1 优化 | ~29ms | ~5.8s | 2x |
| P0+P1+P2+向量化+线程池 | ~7ms | ~1.4s | 8x |

---

## P0: 高优先级优化

### OPT-001: 消除旧个体适应度重复计算

**瓶颈位置:** `dssa_optimizer.py:1320` (`_update_producers`), `dssa_optimizer.py:1451` (`_update_followers`)

**问题分析:**

每次迭代中，`_update_producers` 和 `_update_followers` 各执行两批并行任务：
1. 提交新解生成 + 评估任务到进程池
2. 重新评估当前种群个体的适应度（旧适应度）

旧适应度值自上次评估后未变化，完全可以缓存复用。

**当前代码:**
```python
# dssa_optimizer.py:1320 (_update_producers)
old_fitnesses = self._evaluate_fitness_parallel(producers)

# dssa_optimizer.py:1451 (_update_followers)
old_fitnesses = self._evaluate_fitness_parallel(followers)
```

**优化方案:**

在 `DSSAOptimizer` 中维护 `population_fitness` 数组，跟踪每个个体最近一次评估的适应度值。在 `_update_producers` 和 `_update_followers` 中直接使用缓存值，跳过第二批并行评估。

```python
# 新增: __init__ 中初始化
self.population_fitness = [float('-inf')] * self.config.population_size

# _update_producers 中替换:
# 删除 old_fitnesses = self._evaluate_fitness_parallel(producers)
# 改为:
old_fitnesses = [self.population_fitness[i] for i in indices]

# 每次个体被替换时更新 fitness:
self.population_fitness[i] = new_fit
```

**预期收益:** 减少 ~40-60% 进程间通信开销，每次迭代省 ~10-20ms
**风险:** MEDIUM — 需在 `_inject_random_solutions` 等修改种群的地方同步失效 fitness 缓存
**工作量:** LOW (~50 行代码)

---

### OPT-002: 移除日志用 protection_benefit 重复调用

**瓶颈位置:** `dssa_optimizer.py:1657`

**问题分析:**

每次迭代调用 `calculate_protection_benefit(self.best_solution)` 仅为打印 `total_benefit` 日志。这触发完整的覆盖计算流水线：`calculate_protection_effect` → 4 个覆盖函数 → 逐网格循环。

**当前代码:**
```python
# dssa_optimizer.py:1657
pb_per_grid = self.coverage_model.calculate_protection_benefit(self.best_solution)
total_benefit = sum(pb_per_grid.values())
```

**优化方案:**

方案 A — 直接用 fitness 值推算：
```python
# fitness = total_benefit / total_risk
# 因此 total_benefit = fitness * total_risk
total_benefit = self.best_fitness * self.grid_model._total_risk
```

方案 B — 仅在 best_fitness 变化时计算：
```python
if self.best_fitness != self._last_logged_fitness:
    pb_per_grid = self.coverage_model.calculate_protection_benefit(self.best_solution)
    total_benefit = sum(pb_per_grid.values())
    self._last_logged_fitness = self.best_fitness
```

**预期收益:** 消除每次迭代的 O(N×K) 计算，省 ~8ms/iter
**风险:** LOW — 纯日志改动
**工作量:** LOW (~10 行代码)

---

## P1: 中优先级优化

### OPT-003: 缓存 total_risk 常量

**瓶颈位置:** `coverage_model.py:175-180`

**问题分析:**

`calculate_total_benefit` 每次调用都通过 Python 循环重新计算 `total_risk`，但该值仅依赖网格模型，是常量。

**当前代码:**
```python
# coverage_model.py:175-180
def calculate_total_benefit(self, solution):
    protection_benefit = self.calculate_protection_benefit(solution)
    total_risk = 0.0
    for grid_id in self.grid_ids:
        total_risk += self.grid_model.get_grid_risk(grid_id)  # O(N) 逐次计算
    total_benefit = sum(protection_benefit.values())
    if total_risk > 0:
        total_benefit = total_benefit / total_risk
    return total_benefit
```

**优化方案:**

在 `CoverageModel.__init__` 中预计算并缓存：
```python
# __init__ 中添加:
self._total_risk = sum(self.grid_model.get_grid_risk(gid) for gid in self.grid_ids)

# calculate_total_benefit 中替换:
def calculate_total_benefit(self, solution):
    protection_benefit = self.calculate_protection_benefit(solution)
    total_benefit = sum(protection_benefit.values())
    if self._total_risk > 0:
        total_benefit = total_benefit / self._total_risk
    return total_benefit
```

**预期收益:** O(N) → O(1)，每次调用省 ~0.1ms，累计 10000+ 次调用省 ~1s
**风险:** LOW — 纯常量提升
**工作量:** LOW (~10 行代码)

---

### OPT-004: 减少 repair_solution 调用频率

**瓶颈位置:** `dssa_optimizer.py:303,350,389` (worker 函数中的 repair 调用)

**问题分析:**

`repair_solution` 在每次扰动/开发/跟随/侦察操作后都被调用。当 `force_full_deployment=True` 时，它扫描所有 N 个网格为每种资源类型寻找可用位置，复杂度 O(4N)。

对于 swap 操作（交换两个网格的资源），交换前后资源总量不变，repair 中的 `force_full_deployment` 填充逻辑是多余的。

**当前代码:**
```python
# dssa_optimizer.py:292 (_worker_discrete_perturb)
def _worker_discrete_perturb(solution):
    r = random.random()
    if r < _worker_swap_prob:
        result = _worker_discrete_swap(solution)
    elif r < _worker_swap_prob + _worker_migrate_prob:
        result = _worker_discrete_migrate(solution)
    else:
        result = _worker_discrete_reshuffle(result)
    return _worker_repair(result)  # 每次都调用完整 repair
```

**优化方案:**

根据操作类型跳过不必要的 repair 步骤：
```python
def _worker_discrete_perturb(solution):
    r = random.random()
    if r < _worker_swap_prob:
        result = _worker_discrete_swap(solution)
        # swap 是容量保持操作，只需验证冲突，跳过 force_full_deployment
        return _worker_repair(result, skip_force_full=True)
    elif r < _worker_swap_prob + _worker_migrate_prob:
        result = _worker_discrete_migrate(solution)
        return _worker_repair(result)
    else:
        result = _worker_discrete_reshuffle(solution)
        return _worker_repair(result)
```

同时在 `repair_solution` 中添加 `skip_force_full` 参数：
```python
def repair_solution(self, solution, constraints, force_full_deployment=True,
                    skip_force_full=False, ...):
    # ... 冲突解决逻辑 ...
    if force_full_deployment and not skip_force_full:
        # ... force full deployment 逻辑 ...
```

**预期收益:** 减少 15-25% repair 耗时，每次迭代省 ~2-3ms
**风险:** MEDIUM — 需确保 skip 后仍满足约束
**工作量:** MEDIUM (~80 行代码)

---

## P2: 中低优先级优化

### OPT-005: 用 Python hash 替换 MD5 哈希

**瓶颈位置:** `dssa_optimizer.py:16-29` (`_deterministic_hash`)

**问题分析:**

`_deterministic_hash` 对每次适应度评估都执行：排序 4 个字典 → 构建字符串 → MD5 计算 → 十六进制解析。对于进程内缓存，Python 的 `hash(tuple(...))` 已足够（缓存最大 10000 条，碰撞概率极低）。

**当前代码:**
```python
def _deterministic_hash(solution: DeploymentSolution) -> int:
    key_data = (
        tuple(sorted(solution.cameras.items())),
        tuple(sorted(solution.camps.items())),
        tuple(sorted(solution.drones.items())),
        tuple(sorted(solution.rangers.items())),
        tuple(sorted(solution.fences.items())),
    )
    return int(hashlib.md5(str(key_data).encode()).hexdigest(), 16) % (2**31)
```

**优化方案:**

```python
def _fast_cache_key(solution: DeploymentSolution) -> int:
    """进程内缓存键，使用 Python 内置 hash（单进程内确定性足够）"""
    return hash((
        tuple(sorted(solution.cameras.items())),
        tuple(sorted(solution.camps.items())),
        tuple(sorted(solution.drones.items())),
        tuple(sorted(solution.rangers.items())),
        tuple(sorted(solution.fences.items())),
    ))
```

**预期收益:** 哈希计算加速 15-25%
**风险:** LOW — 缓存仅在单进程内使用，hash 碰撞对 10000 条缓存可忽略
**工作量:** LOW (~5 行代码)

---

### OPT-006: 向量化模式下改用 ThreadPoolExecutor

**瓶颈位置:** `dssa_optimizer.py:699-713` (ProcessPoolExecutor 创建)

**问题分析:**

当前使用 `ProcessPoolExecutor`，每次任务需：序列化解 → pickle → 跨进程序列化 → 反序列化 → 评估 → 结果 pickle 回主进程。对于 `VectorizedCoverageModel`，NumPy 数组操作会释放 GIL，使用线程池可完全消除 pickle 开销。

**当前代码:**
```python
self._fitness_executor = concurrent.futures.ProcessPoolExecutor(
    max_workers=min(self.config.fitness_workers, self.config.population_size),
    initializer=_worker_initializer,
    initargs=(...),
)
```

**优化方案:**

根据是否使用向量化模型自动选择执行器：
```python
if vectorized:
    self._fitness_executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=min(self.config.fitness_workers, self.config.population_size)
    )
else:
    self._fitness_executor = concurrent.futures.ProcessPoolExecutor(
        max_workers=min(self.config.fitness_workers, self.config.population_size),
        initializer=_worker_initializer,
        initargs=(...),
    )
```

同时修改 worker 函数，线程模式下直接使用主线程的 coverage_model（无需序列化）。

**预期收益:** 消除 pickle 开销，向量化模式下 2-3x 加速
**风险:** HIGH — 需确保线程安全，coverage_model 的 numpy 操作确实释放 GIL
**工作量:** HIGH (~200 行代码)

---

### OPT-007: 预计算 deployable_grids 列表

**瓶颈位置:** `dssa_optimizer.py:1980-1983`

**问题分析:**

`_get_deployable_grids` 每次调用都遍历所有网格检查部署矩阵，但部署矩阵在整个优化过程中不变。

**当前代码:**
```python
def _get_deployable_grids(self, resource_type):
    return [gid for gid in self.grid_ids
            if self.coverage_model.deployment_matrix[resource_type].get(gid, 0) == 1]
```

**优化方案:**

在 `__init__` 中预计算：
```python
# __init__ 中:
self._deployable_grids = {
    rt: [gid for gid in self.grid_ids
         if self.coverage_model.deployment_matrix[rt].get(gid, 0) == 1]
    for rt in ['camera', 'drone', 'camp', 'patrol', 'fence']
}

# 使用时:
def _get_deployable_grids(self, resource_type):
    return self._deployable_grids[resource_type]
```

**预期收益:** O(N) → O(1) 查找
**风险:** LOW — 部署矩阵不变
**工作量:** LOW (~15 行代码)

---

## P3: 低优先级优化

### OPT-008: 多样性计算改用采样

**瓶颈位置:** `dssa_optimizer.py:2204-2248` (`_calculate_diversity`)

**问题分析:**

当前计算所有 P(P-1)/2 对个体的对称差，复杂度 O(P²×K)。对于 P=50，每 5 次迭代执行一次。

**当前代码:**
```python
for i in range(len(sets)):
    for j in range(i + 1, len(sets)):
        diff = len(sets[i].symmetric_difference(sets[j]))
        total_dist += diff / n_positions
        n_pairs += 1
```

**优化方案:**

采样 100 对随机个体代替全部配对：
```python
import random
sample_pairs = min(100, len(sets) * (len(sets) - 1) // 2)
n_pairs = 0
total_dist = 0.0
for _ in range(sample_pairs):
    i, j = random.sample(range(len(sets)), 2)
    diff = len(sets[i].symmetric_difference(sets[j]))
    total_dist += diff / n_positions
    n_pairs += 1
```

**预期收益:** O(P²×K) → O(100×K)
**风险:** LOW — 多样性是启发式指标，近似值可接受
**工作量:** LOW (~15 行代码)

---

### OPT-009: 向量化 coverage 数组缓存去重

**瓶颈位置:** `coverage_model_vectorized.py:263-301`

**问题分析:**

`calculate_total_benefit` 和 `calculate_protection_benefit` 都调用 `_calculate_coverage_arrays`，执行完全相同的前半部分计算。在优化循环中，这两个方法可能在同一迭代内被依次调用。

**当前代码:**
```python
def calculate_total_benefit(self, solution):
    pc, dc, cc, fp = self._calculate_coverage_arrays(solution)  # 完整计算
    # ... 计算 benefit ...

def calculate_protection_benefit(self, solution):
    pc, dc, cc, fp = self._calculate_coverage_arrays(solution)  # 重复计算
    # ... 计算 benefit (仅最后一步不同) ...
```

**优化方案:**

缓存最近一次的 coverage 数组：
```python
def __init__(self, ...):
    # ... 现有初始化 ...
    self._cached_solution_id = None
    self._cached_coverage = None

def _get_coverage_arrays(self, solution):
    sid = id(solution)
    if sid == self._cached_solution_id and self._cached_coverage is not None:
        return self._cached_coverage
    result = self._calculate_coverage_arrays(solution)
    self._cached_solution_id = sid
    self._cached_coverage = result
    return result
```

**预期收益:** 消除重复 coverage 计算，省 ~2-5ms/次
**风险:** LOW — solution 对象引用不变时缓存有效
**工作量:** LOW (~20 行代码)

---

### OPT-010: 减少 JSON 快照频率

**瓶颈位置:** `dssa_optimizer.py:1639-1655`

**问题分析:**

每次迭代都调用 `_snapshot_solution` 创建 best_solution 的 5 个字典副本，即使 best_solution 未变化。

**优化方案:**

仅在 best_solution 变化时快照：
```python
if self.output_dir:
    # 仅在 best_solution 变化时创建快照
    if not hasattr(self, '_last_snapshot_best') or \
       self._last_snapshot_best is not self.best_solution:
        snap = _snapshot_solution(self.best_solution)
        self._last_snapshot_best = snap
    else:
        snap = self._last_snapshot_best
    # ... buffer append ...
```

**预期收益:** 减少不必要的 dict 复制
**风险:** LOW
**工作量:** LOW (~10 行代码)

---

## 实施路线图

### 阶段 1: 快速见效 (1-2 小时)
- [ ] OPT-001: 消除旧适应度重复计算
- [ ] OPT-002: 移除日志 protection_benefit 调用
- [ ] OPT-003: 缓存 total_risk

### 阶段 2: 中等收益 (2-4 小时)
- [ ] OPT-004: 减少 repair 调用频率
- [ ] OPT-005: 用 Python hash 替换 MD5
- [ ] OPT-007: 预计算 deployable_grids
- [ ] OPT-009: coverage 数组缓存

### 阶段 3: 架构优化 (4-8 小时)
- [ ] OPT-006: 向量化模式 ThreadPoolExecutor
- [ ] OPT-008: 多样性采样
- [ ] OPT-010: JSON 快照优化

---

## 验证方法

每个优化实施后，运行以下验证：

```bash
# 1. 单元测试
python -m pytest tests/ -v

# 2. 性能基准 (对比优化前后)
python -c "
import time
from protection_pipeline import run_pipeline
start = time.time()
run_pipeline('inputs/base.json', '/tmp/bench_output.json', max_iterations=20, use_gpu=False)
elapsed = time.time() - start
print(f'20 iterations: {elapsed:.2f}s ({elapsed/20*1000:.1f}ms/iter)')
"

# 3. 结果一致性检查 (优化前后 best_fitness 差异 < 1e-6)
```
