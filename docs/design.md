# 核心代码详细设计文档

本文档描述野生动物保护区资源部署优化系统（IMMC 2026 BAI）的核心代码架构、模块设计、数据流和关键算法。

***

## 一、系统架构概览

### 1.1 模块划分

系统由两大子系统组成：

| 子系统 | 目录 | 职责 |
| :--- | :--- | :--- |
| **riskIndex** | `riskIndex/` | 风险评估：计算每个网格的综合风险指数 R_i ∈ [0,1] |
| **hexdynamic** | `hexdynamic/` | 部署优化：基于风险指数，用 DSSA 算法优化资源部署方案 |

辅助模块：

| 模块 | 目录/文件 | 职责 |
| :--- | :--- | :--- |
| **数据生成** | `generate_map.py`, `marker_to_pipeline.py` | 生成/转换 pipeline 输入 JSON |
| **可视化** | `visualize_output.py`, `visualize_iteration.py` 等 | 生成热力图、部署图、对比图 |
| **分析工具** | `sensitivity_analysis.py`, `sobol_sensitivity.py` 等 | 敏感性分析、鲁棒性分析 |
| **Marker** | `marker/` | 浏览器端六边形网格标注工具 |

### 1.2 端到端数据流

```
输入 JSON (pipeline_input.json)
  │
  ├─→ riskIndex: 计算风险
  │     │
  │     ▼
  │   GridRiskResult[] (每个网格的归一化风险 R_i)
  │     │
  │     ▼
  ├─→ hexdynamic/DataLoader: 构建内部数据结构
  │     │
  │     ▼
  │   HexGridModel + CoverageModel + 约束参数
  │     │
  │     ▼
  ├─→ hexdynamic/DSSAOptimizer: 优化部署方案
  │     │
  │     ▼
  │   最优部署方案 (deployment vectors)
  │     │
  │     ▼
  └─→ 输出 JSON (output.json) → 可视化
```

***

## 二、riskIndex 子系统设计

### 2.1 模块结构

```
riskIndex/
├── risk_model_wrapper.py          ← 外部调用入口（CLI + API）
├── visualize_risk_from_json.py    ← 风险热力图可视化
├── generate_hex_map.py            ← 六边形地图生成器
├── generate_square_map.py         ← 方形地图生成器
└── src/risk_model/
    ├── __init__.py
    ├── core/                      ← 核心数据结构
    │   ├── grid.py                   Grid 类
    │   ├── environment.py            Environment, VegetationType
    │   └── species.py                Species, SpeciesDensity, Season
    ├── config/                    ← 权重配置
    │   ├── defaults.py               DEFAULT_RISK_WEIGHTS
    │   └── weights.py                WeightManager, RiskWeights, HumanRiskWeights, EnvironmentalRiskWeights
    ├── risk/                      ← 风险计算引擎
    │   ├── human.py                  HumanRiskCalculator
    │   ├── environmental.py          EnvironmentalRiskCalculator
    │   ├── density.py                DensityRiskCalculator
    │   ├── temporal.py               TemporalFactorCalculator, DiurnalFactorCalculator, SeasonalFactorCalculator
    │   ├── composite.py              CompositeRiskCalculator, NormalizationEngine, RiskModel
    │   └── __init__.py               GridRiskResult, RiskComponents
    ├── data/                      ← 数据 IO 与验证
    │   ├── io.py
    │   ├── validation.py
    │   └── generator.py
    ├── visualization/             ← 可视化组件
    │   ├── heatmap.py                RiskHeatmap
    │   ├── temporal.py               TemporalVisualizer
    │   └── analysis.py
    └── advanced/                  ← 高级功能
        ├── spatiotemporal.py
        └── dssa.py
```

### 2.2 核心数据结构

#### Grid（`core/grid.py`）

```python
@dataclass
class Grid:
    grid_id: str
    x: float                    # 笛卡尔坐标 x（列方向）
    y: float                    # 笛卡尔坐标 y（行方向，向上递增）
    distance_to_boundary: float # 到保护区边界的接近度 [0,1]
    distance_to_road: float    # 到道路的接近度 [0,1]
    distance_to_water: float   # 到水源的接近度 [0,1]
```

接近度 = `1 - 归一化距离`，越近值越高。

#### Environment（`core/environment.py`）

```python
class VegetationType(Enum):
    GRASSLAND = "GRASSLAND"
    FOREST = "FOREST"
    SHRUB = "SHRUB"

@dataclass
class Environment:
    fire_risk: float           # 火灾风险 [0,1]
    terrain_complexity: float  # 地形复杂度 [0,1]
    vegetation_type: VegetationType
```

#### SpeciesDensity（`core/species.py`）

```python
@dataclass
class Species:
    name: str
    weight: float              # 物种保护权重
    rainy_season_multiplier: float
    dry_season_multiplier: float

@dataclass
class SpeciesDensity:
    densities: Dict[str, float]  # species_name → density [0,1]
```

### 2.3 风险计算引擎

#### 综合风险公式

```
R'_i = (ω₁·H_i + ω₂·E_i + ω₃·D_i) × T_t × S_t
R_i  = (R'_i - R_min) / (R_max - R_min)     ← min-max 归一化
```

#### HumanRiskCalculator（`risk/human.py`）

```
H_i = (α₁·prox_boundary + α₂·prox_road + α₃·prox_water) × P_t
```

| 参数 | 默认值 | 含义 |
| :--- | :---: | :--- |
| α₁ (boundary_weight) | 0.2 | 边界邻近度权重 |
| α₂ (road_weight) | 0.3 | 道路邻近度权重 |
| α₃ (water_weight) | 0.5 | 水源邻近度权重 |
| P_t (poaching_probability) | 1.0 | 盗猎时间概率 |

#### EnvironmentalRiskCalculator（`risk/environmental.py`）

```
E_i = β₁·fire_risk + β₂·terrain_complexity
```

| 参数 | 默认值 | 含义 |
| :--- | :---: | :--- |
| β₁ (fire_weight) | 0.6 | 火灾风险权重 |
| β₂ (terrain_weight) | 0.4 | 地形复杂度权重 |

#### DensityRiskCalculator（`risk/density.py`）

```
D_i = Σ_s (w_s × density_{s,i} × seasonal_multiplier_s)
```

默认物种配置：

| 物种 | weight | rainy_multiplier | dry_multiplier |
| :--- | :---: | :---: | :---: |
| rhino | 0.5 | 1.2 | 1.0 |
| elephant | 0.3 | 1.3 | 0.9 |
| bird | 0.2 | 1.5 | 0.8 |

#### TemporalFactorCalculator（`risk/temporal.py`）

支持两种昼夜模式：

| 模式 | 计算 | 说明 |
| :--- | :--- | :--- |
| DISCRETE | 白天(6:00-18:00)=daytime_factor, 夜间=nighttime_factor | 阶跃函数 |
| CONTINUOUS | daytime + (nighttime-daytime) × (0.5 + 0.5·sin(π(h-6)/12))^γ | 正弦平滑过渡 |

季节因子：旱季=dry_season_factor, 雨季=rainy_season_factor

综合时间因子：`temporal_factor = diurnal_factor × seasonal_factor`

#### NormalizationEngine（`risk/composite.py`）

min-max 归一化，将原始风险映射到 [0,1]：

```
R_normalized = (R_raw - R_min) / (R_max - R_min)
```

当 R_max == R_min 时返回 0.5。

### 2.4 DistanceCalculator（`risk_model_wrapper.py`）

距离计算器，将网格坐标转换为接近度：

| 方法 | 计算方式 |
| :--- | :--- |
| `calculate_distance_to_boundary()` | 矩形边界：到四边最短格距 / 归一化 → 1-归一化距离；不规则边界：到最近边界格子的欧氏距离 |
| `calculate_distance_to_feature()` | 到最近特征格子的欧氏距离 → 归一化 → 1-归一化距离 |

### 2.5 RiskModel 调用流程

```
risk_model_wrapper.run_risk_model()
  │
  ├─ 1. load_data_from_json()         → ModelInputData
  ├─ 2. DistanceCalculator(map_config)
  ├─ 3. load_config_from_json()       → ModelConfigData
  ├─ 4. create_model_from_config()    → RiskModel
  ├─ 5. convert_grid_input()          → (Grid, Environment, SpeciesDensity)[]
  └─ 6. model.calculate_batch()       → GridRiskResult[]
        │
        ├─ CompositeRiskCalculator.calculate_raw()  → (raw_risk, RiskComponents)
        └─ NormalizationEngine.fit() + normalize()  → normalized_risk
```

***

## 三、hexdynamic 子系统设计

### 3.1 模块结构

```
hexdynamic/
├── run.py                         ← 一键运行入口
├── protection_pipeline.py         ← 主流程控制
├── data_loader.py                 ← 数据加载与初始化
├── grid_model.py                  ← 六边形网格模型
├── coverage_model.py              ← 覆盖模型（Python 循环版）
├── coverage_model_vectorized.py   ← 覆盖模型（NumPy 向量化版）
├── dssa_optimizer.py              ← DSSA 优化器
├── risk_analysis.py               ← 风险分析（不含优化）
├── generate_map.py                ← 随机地图生成
├── visualize_output.py            ← 输出可视化
├── visualize_iteration.py         ← 单次迭代可视化
├── visualize_iterations.py        ← 批量迭代可视化
├── postprocess_iteration.py       ← 迭代结果后处理
├── batch_pipeline.py              ← 批量 Pipeline
├── monte_carlo_robust.py          ← 蒙特卡洛鲁棒性分析
├── images_to_video.py             ← 图片转视频
└── sensitivity_analysis.py        ← 敏感性分析
```

### 3.2 HexGridModel（`grid_model.py`）

六边形网格的基础数据模型，提供邻接关系、距离计算和边界检测。

#### 核心属性

| 属性 | 类型 | 说明 |
| :--- | :--- | :--- |
| `num_grids` | int | 网格总数 |
| `grid_centers` | np.ndarray (N, 2) | 各网格中心坐标 |
| `adjacency_matrix` | scipy.sparse.csr_matrix | 邻接矩阵（6 邻居） |
| `distance_matrix` | np.ndarray or scipy.sparse | 网格间欧氏距离矩阵 |
| `boundary_edges` | list | 边界边列表 [(grid_id, direction), ...] |

#### 六边形坐标系

采用 **pointy-top, even-r offset** 坐标系：

- 轴坐标 (q, r)：q = col - (r // 2)
- 像素坐标：x = size × √3 × (col + 0.5 × (r & 1)), y = size × 1.5 × r
- 6 个邻居方向：E(1,0), NE(0,1), NW(-1,1), W(-1,0), SW(0,-1), SE(1,-1)

#### 距离矩阵内存控制

| 策略 | 条件 | 行为 |
| :--- | :--- | :--- |
| 预计算全矩阵 | N² × 8B ≤ max_precompute_bytes (默认 800MB) | 一次性计算并缓存 N×N 距离矩阵 |
| 稀疏矩阵回退 | 超过阈值 | 仅存储邻接距离，按需计算远距离 |
| 分块计算 | 向量化模式 | chunk_size=2048，分块计算避免 OOM |

#### 关键方法

| 方法 | 说明 |
| :--- | :--- |
| `get_neighbors(grid_id)` | 获取 6 邻居 grid_id 列表 |
| `get_distance(g1, g2)` | 获取两格间距离 |
| `get_boundary_edges()` | 获取所有边界边（朝向保护区外的边） |
| `precompute_distance_matrix()` | 预计算距离矩阵（惰性加载） |

### 3.3 CoverageModel（`coverage_model.py`）

覆盖模型，计算各类资源对网格的覆盖效果和综合保护收益。

#### 覆盖度计算

每种资源的覆盖度基于**指数衰减函数**：

```
patrol_coverage[i]  = effectiveness[i] × (1 - exp(-patrol_intensity[i]))
drone_coverage[i]   = 1 - exp(-drone_intensity[i])
camera_coverage[i]  = 1 - exp(-camera_intensity[i])
fence_protection[i] = fence_value × fence_protection_coeff
```

其中资源强度通过距离衰减计算：

```
patrol_intensity[i] = Σ_{j where patrol[j]>0} patrol[j] × exp(-dist(i,j) / patrol_radius)
drone_intensity[i]  = Σ_{j where drone[j]>0}  drone[j]  × exp(-dist(i,j) / drone_radius)
camera_intensity[i] = Σ_{j where camera[j]>0} camera[j] × exp(-dist(i,j) / camera_radius)
```

#### 协同增强效应

```
synergy[i] = α_pd × (P_i × D_i) / (1 + P_i + D_i)
           + α_pc × (P_i × C_i) / (1 + P_i + C_i)
```

| 参数 | 默认值 | 说明 |
| :--- | :---: | :--- |
| α_pd | 0.4 | Patrol + Drone 协同系数 |
| α_pc | 0.15 | Patrol + Camera 协同系数 |

#### 综合保护效果

```
E_i = wp × P_i + wd × D_i + wc × C_i + wf × F_i + synergy_i
```

| 权重 | 默认值 | 说明 |
| :--- | :---: | :--- |
| wp | 0.3 | 巡逻覆盖权重 |
| wd | 0.3 | 无人机覆盖权重 |
| wc | 0.2 | 摄像头覆盖权重 |
| wf | 0.2 | 围栏保护权重 |

#### 保护收益与适应度

```
protection_benefit[i] = R_i × (1 - exp(-E_i))     ← 单格保护收益
residual_risk[i]      = R_i × exp(-E_i)            ← 部署后剩余风险
total_pb              = Σ protection_benefit[i]     ← 总保护收益
fitness               = total_pb / Σ R_i            ← 风险加权归一化保护效率（优化目标）
```

#### 约束修复（repair_solution）

修复顺序：

1. **单格上限裁剪**：每种资源不超过 `max_*_per_grid`
2. **全局总量裁剪**：按保护收益从低到高移除超额资源
3. **互斥冲突清除**：同一格只能有一种资源类型，优先级 patrol > drone > camera > camp
4. **部署可行性校验**：移除违反 deployment_matrix 的部署

#### 部署可行性矩阵（Deployment Matrix）

基于地形类型，控制每种资源能否部署在某个格子上：

| terrain_type | patrol | camp | drone | camera | fence |
| :--- | :---: | :---: | :---: | :---: | :---: |
| SparseGrass | ✓* | ✗ | ✓ | ✓ | ✓(仅边缘) |
| DenseGrass | ✗ | ✗ | ✓ | ✗ | ✓(仅边缘) |
| WaterHole | ✗ | ✗ | ✓ | ✗ | ✗ |
| SaltMarsh | ✗ | ✗ | ✓ | ✗ | ✗ |
| Road | ✓ | ✓ | ✓ | ✓ | ✓(仅边缘) |

> *巡逻员特殊规则：只能部署在 Road 或无物种的 SparseGrass 格子

#### 覆盖效果折扣系数

```python
coverage_effectiveness = {
    "DenseGrass": {"patrol": 0.3, "camp": 0.3}
}
```

折扣作用于覆盖度最终结果：`patrol_coverage[i] = effectiveness × (1 - exp(-intensity))`

### 3.4 VectorizedCoverageModel（`coverage_model_vectorized.py`）

CoverageModel 的向量化优化版本，用 NumPy 矩阵运算替代 Python 循环。

#### 优化策略

| 方面 | CoverageModel | VectorizedCoverageModel |
| :--- | :--- | :--- |
| 距离查询 | 逐格循环计算 | 预计算距离矩阵切片 |
| 覆盖度计算 | Python for 循环 | NumPy 矩阵广播 |
| 内存使用 | 低 | 高（需存储距离矩阵） |
| 计算速度 | 基准 | 120 格约 4x 加速，上千格预计 10x+ |

#### 关键实现

```python
class VectorizedCoverageModel(CoverageModel):
    def __init__(self, data_loader, chunk_size=2048):
        # 预计算资源部署掩码数组
        self._precompute_resource_arrays()
    
    def evaluate_fitness(self, solution):
        # 分块计算距离 × 部署向量，矩阵广播
        for chunk_start in range(0, N, chunk_size):
            chunk_dist = dist_matrix[chunk_start:chunk_end, :]
            intensity = chunk_dist @ deployment_vector
            coverage[chunk_start:chunk_end] = 1 - np.exp(-intensity)
```

- 分块大小 `chunk_size=2048`，避免大矩阵运算导致 OOM
- 若内存不足，自动回退到普通 CoverageModel

### 3.5 DSSAOptimizer（`dssa_optimizer.py`）

分布式随机搜索算法（Distributed Stochastic Search Algorithm），优化资源部署方案。

#### 算法流程

```
初始化种群（population_size 个个体）
  │
  ▼
迭代循环（max_iterations 轮）:
  │
  ├─ 1. 评估适应度（evaluate_fitness）
  │     └─ 使用 CoverageModel 计算每个个体的 fitness
  │
  ├─ 2. 排序种群，分为 Producer / Follower / Scout
  │     └─ Producer: 前 producer_ratio × N
  │     └─ Scout: 后 scout_ratio × N
  │     └─ Follower: 其余
  │
  ├─ 3. 更新个体
  │     ├─ Producer: 在当前解附近搜索更优解（离散交换扰动）
  │     ├─ Follower: 向最优 Producer 靠拢
  │     └─ Scout: 随机重新生成部分解
  │
  ├─ 4. 修复约束（repair_solution）
  │
  ├─ 5. 停滞检测
  │     └─ 若连续 stagnation_threshold 轮无改善 → 触发 boost 扰动
  │
  └─ 6. 更新全局最优解
```

#### 个体编码

每个个体是一个部署方案，包含 5 个资源向量：

| 向量 | 类型 | 说明 |
| :--- | :--- | :--- |
| `cameras` | Dict[int, int] | grid_id → 摄像头数量 |
| `drones` | Dict[int, int] | grid_id → 无人机数量 |
| `camps` | Dict[int, int] | grid_id → 营地数量 |
| `rangers` | Dict[int, int] | grid_id → 巡逻员数量 |
| `fences` | Dict[str, int] | "grid_id-direction" → 围栏数量 |

#### 离散交换扰动（_discrete_swap_perturbation）

Producer 更新策略的核心操作：

1. 随机选择一种资源类型
2. 从当前有该资源的格子中随机选一个（源格子）
3. 从可部署该资源的格子中随机选一个（目标格子）
4. 将源格子的资源移动/交换到目标格子
5. 修复约束

#### 停滞检测与恢复

| 参数 | 默认值 | 说明 |
| :--- | :---: | :--- |
| `stagnation_threshold` | 15 | 连续 N 轮无改善触发 boost |
| `stagnation_boost` | 0.3 | boost 时扰动比例 |

boost 操作：对当前最优解进行大规模随机扰动（30% 的资源被重新分配）。

#### 高级特性

| 特性 | 参数 | 说明 |
| :--- | :--- | :--- |
| 热启动 | `warm_start_solution` | 从已有解注入，1/3 种群为热启动个体 |
| 资源冻结 | `freeze_resources` | 指定资源不参与优化 |
| 适应度缓存 | `fitness_cache_max_size` | 缓存最近 N 个解的适应度，避免重复计算 |
| 并行评估 | `fitness_workers` | 多进程并行评估种群适应度 |
| 资源迁移 | `migrate_prob` | 以概率 p 将资源从低收益格迁移到高收益格 |
| 全局重排 | `reshuffle_prob` | 以概率 p 完全重新随机分配资源 |
| 迭代输出 | `output_dir` | 每轮迭代异步写入 JSON，不阻塞主流程 |

### 3.6 DataLoader（`data_loader.py`）

数据加载器，将输入 JSON 转换为内部数据结构。

#### 初始化流程

```
DataLoader(input_data)
  │
  ├─ 1. 生成六边形网格（HexGridModel）
  ├─ 2. 设置地形类型和风险值
  ├─ 3. 初始化部署矩阵（deployment_matrix）
  │     └─ 基于地形类型 + 边缘检测
  ├─ 4. 设置可见性参数和覆盖有效性
  ├─ 5. 设置约束参数（总量、单格上限）
  └─ 6. 设置覆盖参数（半径、权重、协同系数）
```

#### 部署矩阵初始化规则

```python
def initialize_deployment_matrix(self):
    for grid_id, terrain in enumerate(terrain_types):
        # 基础规则（见 3.3 部署可行性矩阵表）
        self.deployment_matrix['patrol'][grid_id] = ...
        self.deployment_matrix['camera'][grid_id] = ...
        # ...
        
        # 围栏：仅边缘格子 + 地形允许
        if is_boundary and terrain allows fence:
            self.deployment_matrix['fence'][grid_id] = 1
```

### 3.7 ProtectionPipeline（`protection_pipeline.py`）

主流程控制脚本，串联风险计算和部署优化。

#### 执行流程

```
protection_pipeline.run(input_json, output_json)
  │
  ├─ 1. 加载输入 JSON
  ├─ 2. 调用 riskIndex 计算风险
  │     └─ risk_model_wrapper.run_risk_model()
  ├─ 3. 构建 DataLoader
  ├─ 4. 选择覆盖模型
  │     ├─ CoverageModel（默认）
  │     └─ VectorizedCoverageModel（--vectorized）
  ├─ 5. 初始化 DSSAOptimizer
  │     ├─ 加载冻结资源配置
  │     └─ 加载热启动方案（可选）
  ├─ 6. 运行优化
  │     └─ optimizer.optimize()
  ├─ 7. 计算保护收益和剩余风险
  └─ 8. 输出 JSON
```

***

## 四、数据格式设计

### 4.1 输入 JSON 结构

```
{
  "map_config": {
    "map_width": int,           // 列数
    "map_height": int,          // 行数
    "boundary_type": "RECTANGLE",
    "road_locations": [[x, y], ...],
    "water_locations": [[x, y], ...],
    "boundary_locations": [{x, y}, ...]  // 可选，不规则边界
  },
  "time": { "hour_of_day": int, "season": "DRY"|"RAINY" },
  "use_temporal_factors": bool,
  "risk_model_config": { ... },          // 可选，权重配置
  "species_config": { ... },             // 物种配置
  "grids": [
    {
      "grid_id": int,
      "q": int, "r": int,               // 六边形轴坐标
      "x": int, "y": int,               // 笛卡尔坐标
      "hex_size": int,                   // 像素半径
      "terrain_type": str,               // 地形类型
      "fire_risk": float,                // 火灾风险 [0,1]
      "terrain_complexity": float,       // 地形复杂度 [0,1]
      "vegetation_type": str,            // GRASSLAND|FOREST|SHRUB
      "species_densities": { str: float } // 物种密度
    }
  ],
  "constraints": { ... },                // 资源约束
  "coverage_params": { ... },            // 覆盖参数
  "dssa_config": { ... }                 // DSSA 配置
}
```

### 4.2 输出 JSON 结构

```
{
  "summary": {
    "total_grids": int,
    "total_risk": float,
    "best_fitness": float,               // 优化目标
    "total_protection_benefit": float,
    "average_protection_benefit": float,
    "fitness_history": [float, ...],
    "resources_deployed": { ... }
  },
  "grids": [
    {
      "grid_id": int,
      "q": int, "r": int, "x": int, "y": int,
      "terrain_type": str,
      "risk_normalized": float,           // 归一化风险 [0,1]
      "protection_benefit_raw": float,    // 原始保护收益
      "protection_benefit_normalized": float, // 归一化保护收益
      "residual_risk_normalized": float,  // 部署后剩余风险
      "deployment": {
        "patrol_rangers": int,
        "camp": int,
        "drone": int,
        "camera": int
      },
      "fences": {                         // 围栏部署
        "fence_count": int,
        "boundary_edge_list": [int, ...]  // 方向列表
      },
      "hex_size": int
    }
  ],
  "fence_edges": [ ... ],                // 全局围栏边列表
  "visualization_config": {              // 可视化配置
    "show_grid_ids": bool
  }
}
```

***

## 五、关键算法详解

### 5.1 风险归一化

```python
# NormalizationEngine
def fit(self, raw_risks):
    self._min_risk = min(raw_risks)
    self._max_risk = max(raw_risks)

def normalize(self, raw_risk):
    if self._max_risk == self._min_risk:
        return 0.5
    return (raw_risk - self._min_risk) / (self._max_risk - self._min_risk)
```

**注意**：启用时间因子后，所有原始风险乘以相同因子，归一化后统计指标不变。这是预期行为，确保不同时段风险分布形状一致。

### 5.2 指数衰减覆盖

```python
# 覆盖度计算
intensity[i] = Σ_j resource[j] × exp(-dist(i,j) / radius)
coverage[i] = effectiveness[i] × (1 - exp(-intensity[i]))
```

- 距离越远，衰减越严重（指数衰减）
- 多个资源叠加时，强度累加
- effectiveness 折扣系数作用于最终覆盖度

### 5.3 协同增强

```python
# Patrol-Drone 协同
synergy_pd = alpha_pd × (P × D) / (1 + P + D)

# Patrol-Camera 协同
synergy_pc = alpha_pc × (P × C) / (1 + P + C)
```

使用调和形式 `(P×D)/(1+P+D)` 而非简单乘积 `P×D`，避免两者都很高时协同效应过大。

### 5.4 DSSA 离散交换扰动

```python
def _discrete_swap_perturbation(self, solution):
    # 1. 随机选资源类型
    resource_type = random.choice(['camera', 'drone', 'camp', 'rangers'])
    
    # 2. 从有该资源的格子中选源
    source = random.choice(grids_with_resource)
    
    # 3. 从可部署格子中选目标
    candidates = deployment_matrix[resource_type] == 1
    target = random.choice(candidates)
    
    # 4. 交换/移动
    move_amount = random.randint(1, solution[source][resource_type])
    solution[source][resource_type] -= move_amount
    solution[target][resource_type] += move_amount
    
    # 5. 修复约束
    repair_solution(solution)
```

### 5.5 围栏部署

围栏部署在边界格子的外侧边上：

```python
# 边界边检测
for grid_id in boundary_grids:
    for direction in range(6):
        neighbor_q = grid.q + neighbor_dirs[direction][0]
        neighbor_r = grid.r + neighbor_dirs[direction][1]
        if (neighbor_q, neighbor_r) not in inner_grids:
            # 这条边朝向保护区外 → 可部署围栏
            boundary_edges.append((grid_id, direction))

# 部署策略
if len(boundary_edges) <= total_fence_length:
    deploy_all(boundary_edges)  # 全部署
else:
    random.sample(boundary_edges, total_fence_length)  # 随机选
```

***

## 六、可视化系统设计

### 6.1 可视化模块层次

| 层次 | 文件 | 用途 |
| :--- | :--- | :--- |
| 最终输出 | `visualize_output.py` | 8 张完整图片（风险/保护/地形/物种/对比） |
| 单次迭代 | `visualize_iteration.py` | 4 张轻量图片（部署/风险对比/保护热力图） |
| 批量迭代 | `visualize_iterations.py` | 并行生成所有迭代的可视化 |
| 后处理 | `postprocess_iteration.py` | 迭代 JSON → 可视化格式 JSON |
| 风险专用 | `visualize_risk_from_json.py` | 方形/六边形风险热力图 |

### 6.2 visualize_output.py 输出图片

| 图片 | 布局 | 内容 |
| :--- | :--- | :--- |
| `risk_heatmap.png` | 地图+颜色条+图例 | YlOrRd 色阶风险热力图 |
| `risk_comparison.png` | 上下双图+颜色条+图例 | 部署前 vs 部署后风险对比 |
| `protection_heatmap.png` | 地图+颜色条+图例 | Greens 色阶保护收益（归一化+原始） |
| `terrain_map.png` | 地图+图例 | 5 色地形分类图+围栏边线 |
| `terrain_deployment_map.png` | 地图+图例 | 半透明地形+资源图标+围栏 |
| `species_map.png` | 地图+图例 | 半透明地形+物种散点（大小∝密度） |
| `species_deployment_comparison.png` | 上下双图+图例 | 物种密度 vs 部署资源对比 |
| `protection_deployment_comparison.png` | 上下双图+颜色条+图例 | 保护收益热力图 vs 部署资源对比 |

### 6.3 六边形绘制

所有可视化使用 pointy-top 六边形：

```python
def hex_corners(cx, cy, size):
    return [(cx + size*cos(π/3*i + π/6), cy + size*sin(π/3*i + π/6)) for i in range(6)]

def grid_center(q, r, size):
    col = q + (r // 2)
    x = size * sqrt(3) * (col + 0.5 * (r & 1))
    y = size * 1.5 * r
    return x, y
```

***

## 七、性能优化设计

### 7.1 向量化覆盖模型

| 优化点 | 实现方式 |
| :--- | :--- |
| 距离矩阵预计算 | 一次性计算 N×N 距离矩阵，避免重复计算 |
| 矩阵广播 | NumPy 广播替代 Python for 循环 |
| 分块计算 | chunk_size=2048，避免大矩阵 OOM |
| OOM 回退 | 内存不足时自动回退到普通 CoverageModel |

### 7.2 DSSA 优化器优化

| 优化点 | 实现方式 |
| :--- | :--- |
| 适应度缓存 | LRU 缓存最近 N 个解的适应度 |
| 并行评估 | ProcessPoolExecutor 并行评估种群 |
| 热启动 | 从已有解注入，加速收敛 |
| 停滞检测 | 连续 N 轮无改善时触发 boost 扰动 |
| 异步迭代输出 | 每轮迭代结果异步写入 JSON，不阻塞主流程 |

### 7.3 HexGridModel 内存控制

| 策略 | 条件 | 效果 |
| :--- | :--- | :--- |
| 全量预计算 | N² × 8B ≤ 800MB | O(1) 距离查询 |
| 稀疏矩阵 | 超过阈值 | 仅存邻接距离，O(k) 查询 |
| 惰性加载 | 首次访问时计算 | 避免不必要的计算 |

***

## 八、约束体系设计

### 8.1 四层约束

```
┌─────────────────────────────────────────┐
│ 第一层：部署可行性矩阵 (Deployment Matrix) │  ← 地形决定能否部署
├─────────────────────────────────────────┤
│ 第二层：单格上限 (Per-Grid Cap)           │  ← 每格最多部署数
├─────────────────────────────────────────┤
│ 第三层：全局总量 (Global Budget)          │  ← 资源总预算
├─────────────────────────────────────────┤
│ 第四层：互斥规则 (Mutual Exclusion)       │  ← 同格资源互斥
└─────────────────────────────────────────┘
```

### 8.2 约束执行时机

| 阶段 | 代码位置 | 执行内容 |
| :--- | :--- | :--- |
| 初始化 | `dssa_optimizer._initialize_solution()` | 可行性矩阵 + 单格上限 + 全局总量 |
| 向量解码 | `dssa_optimizer._vector_to_solution()` | 单格上限截断 |
| 修复 | `coverage_model.repair_solution()` | 单格上限 → 全局总量 → 互斥冲突 |
| 验证 | `coverage_model.validate_solution()` | 检查最终解是否违规 |

***

*文档版本: 1.0\
*最后更新: 2026-05-08*
