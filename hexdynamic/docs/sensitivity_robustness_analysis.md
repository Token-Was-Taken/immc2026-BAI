# 敏感性与稳定性分析工具说明

本文档覆盖以下四个分析脚本的使用方法、算法原理和参数说明：

| 脚本 | 用途 | 分析维度 |
|------|------|---------|
| [sensitivity_batch.py](#1-sensitivity_batchpy--单资源敏感性分析) | 单资源敏感性分析 | 逐资源扫描，边际收益与饱和点 |
| [sobol_sensitivity.py](#2-sobol_sensitivitypy--sobol全局敏感性分析) | Sobol 全局敏感性分析 | 多参数方差分解，一阶/总阶指数 |
| [sobol_synergy_analysis.py](#3-sobol_synergy_analysispy--协同系数敏感性分析) | 协同系数敏感性分析 | alpha_pd/alpha_pc 交互效应 |
| [monte_carlo_robust.py](#4-monte_carlo_robustpy--蒙特卡洛鲁棒性分析) | 蒙特卡洛鲁棒性分析 | 随机采样资源约束，输出分布 |

---

## 1. sensitivity_batch.py — 单资源敏感性分析

### 1.1 概述

对巡逻人员、无人机、摄像头、营地、围栏等资源**逐个扫描**，分析每种资源数量变化对保护收益和适应度的影响。资源间串行执行，资源内可并行。

底层调用 `sensitivity_analysis.py`，支持两步法（粗扫+细扫）、热启动和缓存。

### 1.2 算法

```
for each resource (patrol, camera, drone, ...):
    for resource_value in range(min, max, step):
        修改 input JSON 中该资源的数量
        调用 run_pipeline() 获取 best_fitness 和 total_protection_benefit
    计算边际收益 = (benefit[i] - benefit[i-1]) / (value[i] - value[i-1])
    识别饱和点 = 第一个边际收益 < 最大边际收益 × 5% 的点
    生成报告图表
```

**两步法**（`--two-step`）：先以粗步长扫描全范围，定位饱和区后自动以更细步长重新扫描饱和区附近，兼顾效率与精度。

**热启动**（`--warm-start`）：按资源值递增顺序串行执行，低资源点的优化结果作为高资源点的初始解，加速收敛。

### 1.3 用法

```powershell
# 基本用法（使用默认范围扫描所有资源）
py sensitivity_batch.py -i inputs/etosha8.json -w 4 --vectorized

# 自定义范围
py sensitivity_batch.py -i inputs/etosha8.json \
    --ranges patrol:0:50:5 camera:0:400:10 drone:0:20:1 \
    -w 4 --vectorized

# 两步法（粗扫后自动细扫饱和区）
py sensitivity_batch.py -i inputs/etosha8.json \
    --ranges camera:0:400:50 \
    --two-step --workers 4 --vectorized

# 热启动 + 分组并行
py sensitivity_batch.py -i inputs/etosha8.json \
    --ranges patrol:0:50:5 \
    --warm-start --warm-start-groups 4 -w 4 --vectorized
```

### 1.4 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--input` / `-i` | str | (必填) | 基础输入 JSON 路径 |
| `--ranges` | list | 默认范围 | 资源范围，格式 `resource:min:max:step` |
| `--output` / `-o` | str | `<report_dir>/sensitivity_results/` | 中间结果目录 |
| `--report-dir` | str | `./figures/single_sensitivity` | 顶层输出目录 |
| `--workers` / `-w` | int | CPU 核数 | 资源内并行工作进程数 |
| `--vectorized` | flag | False | 使用向量化覆盖模型 |
| `--two-step` | flag | False | 启用两步法 |
| `--fine-step-ratio` | int | 5 | 细扫步长 = 粗步长 / 此值 |
| `--warm-start` | flag | False | 启用热启动 |
| `--warm-start-groups` | int | 1 | 分组并行组数（>1 时启用分组并行） |
| `--no-cache` | flag | False | 禁用缓存 |
| `--no-report` | flag | False | 跳过报告生成 |

### 1.5 默认扫描范围

| 资源 | min | max | step | 点数 |
|------|-----|-----|------|------|
| patrol | 0 | 50 | 5 | 11 |
| camera | 0 | 20 | 2 | 11 |
| drone | 0 | 10 | 1 | 11 |
| camp | 0 | 5 | 1 | 6 |
| fence | 0 | 100 | 10 | 11 |

### 1.6 输出

- `sensitivity_results/sensitivity_<resource>.json` — 每个资源的完整扫描数据
- `report_<resource>.png` — 4 图报告（保护收益、适应度、边际收益、累计增益）+ 数据表
- `batch_config.json` — 批处理配置和结果摘要

### 1.7 评估次数计算

```
总评估次数 = Σ (每种资源的扫描点数)
```

例如默认范围全部资源：11 + 11 + 11 + 6 + 11 = **50 次** run_pipeline 调用。

---

## 2. sobol_sensitivity.py — Sobol 全局敏感性分析

### 2.1 概述

使用 Sobol 全局敏感性分析方法（基于方差分解），量化多个输入参数对模型输出的影响程度。与单资源扫描不同，Sobol 分析能捕捉**参数间的交互效应**。

使用 SALib 库的 Saltelli 采样和 Sobol 指数计算。

### 2.2 算法

**Saltelli 采样**：生成 N × (2k + 2) 个参数组合，其中 k 为参数个数。

**Sobol 指数**：
- **一阶指数 (S1)**：单个参数对输出方差的独立贡献
- **总阶指数 (ST)**：单个参数及其所有交互效应的总贡献
- ST - S1 = 该参数与其他参数的交互效应

```
1. 定义参数空间 (name, min, max)
2. Saltelli 采样 → N × (2k+2) 组参数
3. 对每组参数调用 run_pipeline() 获取 best_fitness
4. SALib.analyze.sobol 计算一阶/总阶指数
5. 生成敏感性图表
```

### 2.3 用法

```powershell
# 默认参数 (patrol, drones, cameras, camps)
py sobol_sensitivity.py inputs/etosha8.json \
    --num-samples 512 --workers 4 --vectorized

# 自定义参数文件
py sobol_sensitivity.py inputs/etosha8.json \
    --params inputs/sobol-params.json \
    --num-samples 512 --workers 4 --vectorized

# 指定随机种子（可复现）
py sobol_sensitivity.py inputs/etosha8.json \
    --num-samples 256 --seed 42 --workers 4 --vectorized
```

### 2.4 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `base_config` | str | (必填) | 基础输入 JSON 路径 |
| `--params` | str | 内置默认 | 参数定义：文件路径或 JSON 字符串 |
| `--num-samples` | int | 512 | Saltelli 基础采样数 N |
| `--output-dir` | str | `./sobol_results` | 输出目录 |
| `--seed` | int | None | 随机种子（None = 随机） |
| `--workers` | int | CPU 核数 | 并行工作进程数 |
| `--vectorized` | flag | False | 使用向量化覆盖模型 |
| `--gpu` | flag | False | 启用 GPU 加速 |

### 2.5 默认参数定义

```json
[
  {"name": "total_patrol",  "min": 10, "max": 30},
  {"name": "total_drones",  "min": 1,  "max": 8},
  {"name": "total_cameras", "min": 5,  "max": 20},
  {"name": "total_camps",   "min": 2,  "max": 10}
]
```

### 2.6 自定义参数文件格式

```json
[
  {"name": "total_patrol",  "min": 8,  "max": 32},
  {"name": "total_drones",  "min": 1,  "max": 16},
  {"name": "total_cameras", "min": 2,  "max": 64}
]
```

### 2.7 评估次数计算

```
总评估次数 = N × (2k + 2)
```

| N | k=4 | k=5 |
|---|-----|-----|
| 128 | 1,280 | 1,536 |
| 256 | 2,560 | 3,072 |
| 512 | 5,120 | 6,144 |
| 1024 | 10,240 | 12,288 |

### 2.8 输出

- `sobol_indices.json` — 一阶/总阶指数及置信区间
- `sobol_first_order.png` — 一阶指数柱状图
- `sobol_total_order.png` — 总阶指数柱状图
- `evaluation_records.json` — 所有评估的参数和结果
- `eval_XXXXX_input.json` — 每次评估的输入配置

### 2.9 内存注意事项

Windows 下 `spawn` 方式启动子进程，每个 worker 独立加载 Python 运行时和模块。建议：
- `--workers 4` 适合 16GB 内存
- `--workers 8` 需要 32GB+ 内存
- 如遇 MemoryError，减少 workers 数量

---

## 3. sobol_synergy_analysis.py — 协同系数敏感性分析

### 3.1 概述

在标准 Sobol 分析基础上，将**协同系数** `alpha_pd`（巡逻+无人机协同）和 `alpha_pc`（巡逻+摄像头协同）作为输入变量参与分析，量化协同效应对保护收益的影响及其与资源数量的交互。

### 3.2 算法

与 `sobol_sensitivity.py` 相同的 Saltelli 采样 + Sobol 指数方法，区别在于参数空间包含协同系数：

```
参数空间 = {alpha_pd, alpha_pc, total_patrol, total_drones, total_cameras}
```

额外分析：
- 协同系数的独立敏感性
- 协同系数与资源数量的二阶交互效应
- 不同协同系数水平下的系统最优资源配置

### 3.3 用法

```powershell
# 默认参数 (alpha_pd, alpha_pc, patrol, drones, cameras)
py sobol_synergy_analysis.py inputs/etosha8.json \
    --num-samples 256 --workers 4 --vectorized

# 自定义参数
py sobol_synergy_analysis.py inputs/etosha8.json \
    --params inputs/sobol-params.json \
    --num-samples 256 --workers 4 --vectorized

# 指定种子
py sobol_synergy_analysis.py inputs/etosha8.json \
    --num-samples 256 --seed 42 --workers 4
```

### 3.4 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `base_config` | str | (必填) | 基础输入 JSON 路径 |
| `--params` | str | 内置默认 | 参数定义：文件路径或 JSON 字符串 |
| `--num-samples` | int | 256 | Saltelli 基础采样数 N |
| `--output-dir` | str | `./sobol_synergy_results` | 输出目录 |
| `--seed` | int | 42 | 随机种子 |
| `--workers` | int | CPU 核数 | 并行工作进程数 |
| `--vectorized` | flag | False | 使用向量化覆盖模型 |

### 3.5 默认参数定义

```json
[
  {"name": "alpha_pd",      "min": 0.0, "max": 1.0},
  {"name": "alpha_pc",      "min": 0.0, "max": 0.5},
  {"name": "total_patrol",  "min": 10,  "max": 30},
  {"name": "total_drones",  "min": 1,   "max": 8},
  {"name": "total_cameras", "min": 5,   "max": 20}
]
```

### 3.6 评估次数计算

k=5，总评估次数 = N × (2×5+2) = **N × 12**

| N | 总评估次数 |
|---|----------|
| 128 | 1,536 |
| 256 | 3,072 |
| 512 | 6,144 |

### 3.7 输出

- `sobol_synergy_indices.json` — Sobol 指数（含协同系数）
- `sobol_synergy_first_order.png` — 一阶指数图
- `sobol_synergy_total_order.png` — 总阶指数图
- `synergy_interaction_heatmap.png` — 参数交互热力图
- `evaluation_records.json` — 评估记录

### 3.8 与 sobol_sensitivity.py 的区别

| 维度 | sobol_sensitivity.py | sobol_synergy_analysis.py |
|------|---------------------|--------------------------|
| 参数 | 资源数量（patrol, drones, cameras, camps） | 资源数量 + 协同系数（alpha_pd, alpha_pc） |
| 关注点 | 哪种资源对输出影响最大 | 协同效应的强度及与资源的交互 |
| 默认 N | 512 | 256 |
| 默认 k | 4 | 5 |
| 附加输出 | — | 交互热力图 |

---

## 4. monte_carlo_robust.py — 蒙特卡洛鲁棒性分析

### 4.1 概述

通过随机采样资源约束（patrol、drones、cameras、camps），运行 N 次独立的 DSSA 优化，统计保护收益和适应度的分布，评估优化结果的**鲁棒性**和**稳定性**。

### 4.2 算法

```
1. 从固定分布中随机采样资源约束:
   - total_patrol   ~ Uniform(15, 25)
   - total_drones   ~ Uniform(2, 6)
   - total_cameras  ~ Uniform(8, 15)
   - total_camps    ~ Uniform(3, 7)

2. 对每组约束调用 run_pipeline() 获取:
   - best_fitness
   - total_protection_benefit
   - resource_efficiency = benefit / total_resource

3. 统计分析:
   - 均值、标准差、分位数
   - 直方图分布
   - 资源效率 vs 总资源量散点图
```

### 4.3 用法

```powershell
# 基本用法
py monte_carlo_robust.py inputs/etosha8.json \
    --num-trials 100 --workers 4 --vectorized

# 指定随机种子
py monte_carlo_robust.py inputs/etosha8.json \
    --num-trials 200 --seed 42 --workers 4 --vectorized

# 跳过图表（只输出 JSON）
py monte_carlo_robust.py inputs/etosha8.json \
    --num-trials 100 --no-visualize --workers 4

# 限制 DSSA 迭代次数
py monte_carlo_robust.py inputs/etosha8.json \
    --num-trials 100 --max-iterations 100 --workers 4

# 热启动（提供已有解作为初始部署）
py monte_carlo_robust.py inputs/etosha8.json \
    --num-trials 100 --warm-start figures/etosha_new/3/output.json
```

### 4.4 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `base_config` | str | (必填) | 基础输入 JSON 路径 |
| `--num-trials` | int | 100 | 蒙特卡洛试验次数 |
| `--output-dir` | str | `./robust_results` | 输出目录 |
| `--seed` | int | None | 随机种子 |
| `--vectorized` | flag | False | 使用向量化覆盖模型 |
| `--no-visualize` | flag | False | 跳过图表生成 |
| `--max-iterations` | int | 输入 JSON 配置 | DSSA 最大迭代次数 |
| `--warm-start` | str | None | 热启动解路径（output JSON） |
| `--workers` | int | CPU 核数 | 并行工作进程数 |

### 4.5 资源采样分布

| 资源 | 分布 | 范围 |
|------|------|------|
| total_patrol | Uniform | [15, 25] |
| total_drones | Uniform | [2, 6] |
| total_cameras | Uniform | [8, 15] |
| total_camps | Uniform | [3, 7] |

### 4.6 评估次数

总评估次数 = `--num-trials`（每次试验一组随机资源约束）。

| num-trials | 总评估次数 |
|------------|----------|
| 50 | 50 |
| 100 | 100 |
| 200 | 200 |
| 500 | 500 |

### 4.7 输出

- `trial_XXX_output.json` — 每次试验的完整输出
- `robustness_summary.json` — 统计摘要（均值、标准差、分位数）
- `robustness_chart.png` — 鲁棒性分析图表（直方图 + 散点图 + 箱线图）

### 4.8 关键指标

| 指标 | 计算方式 | 含义 |
|------|---------|------|
| best_fitness | DSSA 优化输出 | 优化适应度（越大越好） |
| total_protection_benefit | run_pipeline 输出 | 总保护收益 |
| resource_efficiency | benefit / total_resource | 单位资源收益（越大越好） |
| 标准差 | 所有试验的 std | 越小表示系统越稳定 |

---

## 5. 四种分析对比

| 维度 | sensitivity_batch | sobol_sensitivity | sobol_synergy | monte_carlo_robust |
|------|-------------------|-------------------|---------------|-------------------|
| **分析类型** | 局部敏感性 | 全局敏感性 | 全局敏感性 | 鲁棒性 |
| **方法** | 逐资源扫描 | 方差分解 (Sobol) | 方差分解 (Sobol) | 蒙特卡洛随机采样 |
| **参数空间** | 单参数变化 | 多参数独立 | 多参数 + 协同系数 | 随机采样固定分布 |
| **交互效应** | 无法捕捉 | 可捕捉 | 专门分析协同 | 不分析 |
| **输出重点** | 边际收益、饱和点 | 参数重要性排名 | 协同效应强度 | 分布统计、稳定性 |
| **典型 N** | 50 | 5,120 | 3,072 | 100 |
| **适用场景** | 确定单种资源最优投入 | 识别关键参数 | 评估协同机制价值 | 验证系统鲁棒性 |

### 5.1 推荐使用顺序

1. **sensitivity_batch** — 先做单资源扫描，了解每种资源的边际收益曲线和饱和点
2. **sobol_sensitivity** — 再做多参数全局敏感性，识别关键资源和交互效应
3. **sobol_synergy** — 深入分析协同系数的影响
4. **monte_carlo_robust** — 最后验证系统在随机约束下的鲁棒性

### 5.2 内存与并行建议

| 脚本 | workers 建议 | 原因 |
|------|-------------|------|
| sensitivity_batch | 4-8 | 资源内并行，单次评估轻量 |
| sobol_sensitivity | 4 | 评估次数多，每 worker 需加载完整 pipeline |
| sobol_synergy | 4 | 同上 |
| monte_carlo_robust | 4-8 | 试验独立，单次评估轻量 |

> Windows 环境下使用 `spawn` 启动子进程，每个 worker 独立加载 Python 运行时和所有模块。如遇 MemoryError，优先减少 `--workers`。

### 5.3 输入 JSON 中的关键字段

所有脚本都读取输入 JSON 中的 `constraints` 字段作为基础配置：

```json
{
  "constraints": {
    "total_patrol": 20,
    "total_drones": 3,
    "total_cameras": 50,
    "total_camps": 5,
    "total_fence_length": 5000
  }
}
```

各脚本在基础配置上修改对应字段后调用 `run_pipeline()`。
