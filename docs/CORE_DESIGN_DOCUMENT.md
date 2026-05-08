# 核心代码详细设计文档

## 1. 项目概述

### 1.1 项目背景

本项目为 **IMM C 2026 野生动物保护区资源优化部署系统**，面向非洲野生动物保护区（如纳米比亚埃托沙国家公园）的巡逻资源部署问题，通过数学建模和智能优化算法，在六边形网格地图上为多种保护资源找到最优部署方案。

### 1.2 三大子系统

| 子系统 | 路径 | 功能 |
|--------|------|------|
| **hexdynamic** | `hexdynamic/` | 六边形网格动态资源优化引擎，包含覆盖模型、DSSA 优化器、数据加载器 |
| **riskIndex** | `riskIndex/` | 保护区风险指数模型，计算人为风险、环境风险、物种密度风险及时间因子 |
| **marker** | `marker/` | 地图标注工具，用于在地图上标注六边形网格坐标、地形类型等，并导出为 JSON |

### 1.3 核心目标

在六边形网格地图上，使用 **DSSA（Discrete Sparrow Search Algorithm，离散麻雀搜索算法）** 优化算法，为以下五类保护资源找到最优部署方案：

- **巡逻人员 (Rangers)**：从营地出发巡逻，覆盖范围由巡逻半径决定
- **无人机 (Drones)**：空中巡逻，覆盖范围由无人机半径决定
- **摄像头 (Cameras)**：固定监控，覆盖范围由摄像头半径决定
- **营地 (Camps)**：巡逻人员驻扎点，间接提供巡逻覆盖
- **围栏 (Fences)**：部署在地图边缘，提供物理防护

### 1.4 技术栈

- **语言**：Python 3.x
- **核心依赖**：NumPy, SciPy
- **并行计算**：`concurrent.futures.ThreadPoolExecutor`
- **数据格式**：JSON（输入/输出）

---

## 2. 系统架构

### 2.1 整体架构图

```
用户层: Marker工具 (marker/) / CLI脚本 (run.py, find_deployment.py)
  |
  v
数据准备层: generate_map.py / marker_to_pipeline.py / riskIndex地图生成器
  |  输出: pipeline_input.json (包含 grids, map_config, constraints, ...)
  v
风险计算层: riskIndex模块 (risk_model_wrapper.py)
  |  输入: map_config, time, risk_model_config, species_config, grids
  |  输出: normalized_risk [0,1], raw_risk, temporal_factor (T_t x S_t)
  v
优化层: protection_pipeline.py
  +-- HexGridModel (grid_model.py)        - 六边形网格拓扑与距离计算
  +-- CoverageModel (coverage_model.py)   - 覆盖效果评估（基础版）
  +-- VectorizedCoverageModel             - 覆盖效果评估（向量化加速版）
  |   (coverage_model_vectorized.py)
  +-- DSSAOptimizer (dssa_optimizer.py)   - DSSA 优化引擎
  +-- DataLoader (data_loader.py)         - 数据加载、约束与参数管理
  |
  v
输出层: visualize_output.py / sensitivity_analysis.py / monte_carlo_robust.py
  |  输出: pipeline_output.json (包含 summary, grids, deployment)
  v
分析层: sobol_sensitivity.py / risk_analysis.py / batch_pipeline.py
```

### 2.2 模块依赖关系

```
protection_pipeline.py
  |-- data_loader.py          (GridData, ResourceConstraints, CoverageParameters, DataLoader)
  |-- grid_model.py           (HexGridModel)
  |-- coverage_model.py       (CoverageModel, DeploymentSolution)
  |-- coverage_model_vectorized.py  (VectorizedCoverageModel -> CoverageModel)
  |-- dssa_optimizer.py       (DSSAOptimizer, DSSAConfig)
  |-- riskIndex/risk_model_wrapper.py  (MapConfig, GridInputData, TimeInputData, ...)
  |-- riskIndex/src/risk_model/risk/composite.py  (RiskModel, CompositeRiskCalculator)
  |-- riskIndex/src/risk_model/risk/human.py      (HumanRiskCalculator)
  |-- riskIndex/src/risk_model/risk/environmental.py  (EnvironmentalRiskCalculator)
  |-- riskIndex/src/risk_model/risk/density.py    (DensityRiskCalculator)
  |-- riskIndex/src/risk_model/risk/temporal.py   (TemporalFactorCalculator)
  |-- riskIndex/src/risk_model/config/weights.py  (WeightManager)

generate_map.py
  (独立脚本，生成 pipeline_input.json)

marker_to_pipeline.py
  (独立脚本，从 marker 导出的 grid-coordinates.json 生成 pipeline_input.json)

visualize_output.py
  |-- 读取 pipeline_output.json，生成热力图和部署图

sensitivity_analysis.py
  |-- protection_pipeline.py (通过 subprocess 调用)

monte_carlo_robust.py
  |-- protection_pipeline.py (通过 subprocess 调用)
```

### 2.3 核心文件清单

| 文件路径 | 说明 | 行数(约) |
|----------|------|----------|
| `hexdynamic/grid_model.py` | 六边形网格模型 | 438 |
| `hexdynamic/coverage_model.py` | 覆盖效果模型（基础版） | 678 |
| `hexdynamic/coverage_model_vectorized.py` | 覆盖效果模型（向量化版） | 325 |
| `hexdynamic/dssa_optimizer.py` | DSSA 优化器 | 1200+ |
| `hexdynamic/data_loader.py` | 数据加载与约束管理 | 305 |
| `hexdynamic/protection_pipeline.py` | 优化流水线（主入口） | 667 |
| `hexdynamic/generate_map.py` | 随机地图生成器 | - |
| `hexdynamic/visualize_output.py` | 可视化输出 | - |
| `hexdynamic/sensitivity_analysis.py` | 敏感性分析 | - |
| `hexdynamic/monte_carlo_robust.py` | 蒙特卡洛鲁棒性分析 | - |
| `riskIndex/risk_model_wrapper.py` | 风险模型封装 | 703 |
| `riskIndex/src/risk_model/risk/composite.py` | 综合风险计算与归一化 | 344 |
| `riskIndex/src/risk_model/risk/human.py` | 人为风险计算 | 97 |
| `riskIndex/src/risk_model/risk/environmental.py` | 环境风险计算 | 85 |
| `riskIndex/src/risk_model/risk/density.py` | 物种密度风险计算 | 101 |
| `riskIndex/src/risk_model/risk/temporal.py` | 时间因子计算（昼夜+季节） | 163 |
| `marker_to_pipeline.py` | Marker 数据转换 | - |

---

## 3. 核心数据结构

### 3.1 GridData

**文件**：`hexdynamic/data_loader.py`

**用途**：单个六边形网格的完整数据，是整个系统的基本数据单元。

```python
@dataclass
class GridData:
    grid_id: int                          # 网格唯一标识
    q: int                                # 轴坐标 q 分量
    r: int                                # 轴坐标 r 分量
    terrain_type: str                     # 地形类型: SparseGrass/DenseGrass/WaterHole/SaltMarsh/Road
    risk: float                           # 归一化风险值 [0, 1]
    temporal_factor: float = 1.0          # 时间因子 T_t x S_t (昼夜 x 季节)
    species_densities: Dict[str, float] = None  # 物种密度 {species_name: density}
```

**说明**：
- `q` 和 `r` 为六边形轴坐标，满足 `q + r + s = 0`（其中 `s = -q - r`）
- `risk` 由 riskIndex 模块计算并归一化到 [0, 1]
- `temporal_factor` 由昼夜因子和季节因子相乘得到，默认为 1.0
- `species_densities` 的键为物种名称（如 `"rhino"`, `"elephant"`, `"bird"`），值为密度

### 3.2 DeploymentSolution

**文件**：`hexdynamic/coverage_model.py`

**用途**：DSSA 优化过程中的部署方案，描述五类资源在网格上的分配。

```python
@dataclass
class DeploymentSolution:
    cameras: Dict[int, int]               # {grid_id: camera_count}
    camps: Dict[int, int]                 # {grid_id: camp_count} (0 or 1)
    drones: Dict[int, int]                # {grid_id: drone_count} (0 or 1)
    rangers: Dict[int, int]               # {grid_id: ranger_count}
    fences: Dict[Tuple[int, int], int]    # {(grid_id, direction): count}
    _cache_key: int = field(default=None, init=False, repr=False, compare=False)
```

**围栏键格式说明**：
- **边界边**：`(grid_id, direction)`，其中 `direction` 为 0-5 的整数，表示六边形的六个方向
- **内部边**（旧格式）：`(grid_id_1, grid_id_2)`，两个相邻网格之间的边

**`_cache_key`**：适应度缓存的哈希键，避免重复计算相同方案的适应度值。

### 3.3 ResourceConstraints

**文件**：`hexdynamic/data_loader.py`

**用途**：资源总量和单格上限约束。

```python
@dataclass
class ResourceConstraints:
    total_patrol: int                     # 巡逻人员总数
    total_camps: int                      # 营地总数
    max_rangers_per_camp: int             # 每个营地最大巡逻员数
    total_cameras: int                    # 摄像头总数
    total_drones: int                     # 无人机总数
    total_fence_length: float             # 围栏总长度（段数）
    max_cameras_per_grid: int = 1         # 单格最大摄像头数
    max_drones_per_grid: int = 1          # 单格最大无人机数
    max_camps_per_grid: int = 1           # 单格最大营地数
    max_rangers_per_grid: int = 1         # 单格最大巡逻员数
    max_fences_per_grid: int = 6          # 单格最大围栏段数（六边形最多6条边）
```

### 3.4 CoverageParameters

**文件**：`hexdynamic/data_loader.py`

**用途**：覆盖模型参数，控制各类资源的覆盖范围和权重。

```python
@dataclass
class CoverageParameters:
    patrol_radius: float = 5.0            # 巡逻覆盖半径（六边形距离单位）
    drone_radius: float = 8.0             # 无人机覆盖半径
    camera_radius: float = 3.0            # 摄像头覆盖半径
    fence_protection: float = 0.5         # 每段围栏的保护系数
    wp: float = 0.3                       # 巡逻覆盖权重
    wd: float = 0.3                       # 无人机覆盖权重
    wc: float = 0.2                       # 摄像头覆盖权重
    wf: float = 0.2                       # 围栏保护权重
    alpha_pd: float = 0.4                 # 巡逻+无人机协同系数
    alpha_pc: float = 0.15                # 巡逻+摄像头协同系数
```

### 3.5 DSSAConfig

**文件**：`hexdynamic/dssa_optimizer.py`

**用途**：DSSA 优化器的全部配置参数。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `population_size` | int | 50 | 种群大小 |
| `max_iterations` | int | 100 | 最大迭代次数 |
| `producer_ratio` | float | 0.2 | Producer 占比（前 20%） |
| `scout_ratio` | float | 0.3 | Scout 占比（后 30%） |
| `ST` | float | 0.8 | 发现者/跟随者转换阈值 |
| `use_time_aware_fitness` | bool | False | 启用时间感知适应度 |
| `force_full_deployment` | bool | None | 强制部署所有资源 |
| `output_dir` | str | None | 迭代输出目录 |
| `save_iteration_visualization` | bool | False | 保存迭代可视化 |
| **风险优先配置** | | | |
| `use_risk_priority` | bool | False | 启用风险优先部署 |
| `high_risk_percentage` | float | 0.3 | 高风险网格占比 |
| `high_risk_perturbation_priority` | float | 0.7 | 高风险网格扰动优先级 |
| **探索范围调度** | | | |
| `initial_alpha` | float | 3.0 | 早期探索范围（iter < 30%） |
| `mid_alpha` | float | 2.0 | 中期探索范围（30%-70%） |
| `final_alpha` | float | 1.0 | 后期探索范围（>= 70%） |
| `exploitation_alpha` | float | 1.0 | 开发模式扰动范围 |
| **停滞检测** | | | |
| `stagnation_threshold` | int | 10 | 停滞检测阈值（连续不改善迭代数） |
| `stagnation_tolerance` | float | 1e-6 | 最小改善量（重置计数器） |
| `stagnation_boost` | float | 1.5 | 停滞时 alpha 放大倍数 |
| **离散操作配置** | | | |
| `swap_prob` | float | 0.6 | Producer 使用离散交换的概率 |
| `migrate_prob` | float | 0.25 | 资源迁移操作概率 |
| `reshuffle_prob` | float | 0.15 | 全局重排操作概率 |
| `follower_explore_ratio` | float | 0.5 | Follower 随机探索比例 |
| `scout_reset_threshold` | float | 0.95 | Scout 重置阈值 |
| `scout_partial_reset_ratio` | float | 0.5 | Scout 部分重置比例 |
| `diversity_min_threshold` | float | 0.3 | 种群多样性最低阈值 |
| `diversity_inject_ratio` | float | 0.2 | 多样性注入比例 |
| **修复策略** | | | |
| `use_marginal_contribution_repair` | bool | False | 边际贡献修复（默认随机移除） |
| `skip_conflict_resolution` | bool | False | 跳过资源冲突解决 |
| **性能配置** | | | |
| `fitness_cache_max_size` | int | 10000 | 适应度缓存最大条目数 |
| `fitness_workers` | int | 16 | 并行适应度评估线程数 |

### 3.6 HexGridModel

**文件**：`hexdynamic/grid_model.py`

**用途**：六边形网格拓扑模型，管理网格的邻接关系、距离计算和几何属性。

**内部数据**：

| 属性 | 类型 | 说明 |
|------|------|------|
| `grids` | `List[GridData]` | 所有网格数据列表 |
| `grid_dict` | `Dict[int, GridData]` | grid_id -> GridData 映射 |
| `_id_to_idx` | `Dict[int, int]` | grid_id -> 数组索引映射 |
| `_coord_to_grid` | `Dict[Tuple[int,int], GridData]` | (q,r) -> GridData 映射 |
| `_qs`, `_rs`, `_qr` | `np.ndarray (int32)` | 预提取的坐标数组（向量化计算用） |
| `adjacency_matrix` | `Dict[int, List[int]]` | 邻接表（6-邻接图） |
| `_distance_matrix` | `np.ndarray (float32)` 或 None | N x N 距离矩阵（惰性加载） |
| `_distance_sparse` | `sparse.csr_matrix` 或 None | 稀疏距离矩阵（按需构建） |

**关键方法**：

| 方法 | 返回类型 | 说明 |
|------|----------|------|
| `distance_matrix` (property) | `np.ndarray` 或 None | 惰性加载的完整距离矩阵 |
| `has_distance_matrix()` | `bool` | 是否成功预计算距离矩阵 |
| `get_distance_sparse(max_radius)` | `sparse.csr_matrix` | 获取指定半径内的稀疏距离矩阵 |
| `compute_distances_to(target_indices)` | `np.ndarray (N x K)` | 计算所有网格到目标网格的距离 |
| `get_edge_grids()` | `List[int]` | 获取地图边缘网格 ID 列表 |
| `get_boundary_edges_for_grid(grid_id)` | `List[Tuple[int, int]]` | 获取单个网格的边界边 |
| `get_fencing_edges()` | `List[Tuple[int, int, float]]` | 获取所有可部署围栏的边 |
| `get_grid_center_coords(grid_id)` | `Tuple[float, float]` | 获取网格中心笛卡尔坐标 |
| `get_grid_corners(grid_id)` | `List[Tuple[float, float]]` | 获取网格六个角点坐标 |
| `get_neighbors(grid_id)` | `List[int]` | 获取相邻网格 ID 列表 |
| `get_high_risk_grids(threshold)` | `List[int]` | 获取高风险网格列表 |

---

## 4. 核心算法设计

### 4.1 六边形网格模型 (`grid_model.py`)

#### 4.1.1 坐标系统

采用 **轴坐标 (Axial Coordinates)** 系统，使用 `(q, r)` 两个分量表示六边形位置，第三个分量 `s = -q - r` 可隐式推导。

```
六边形六个方向（轴坐标偏移）:
  方向0: (+1,  0)  - 东
  方向1: ( 0, +1)  - 东北
  方向2: (-1, +1)  - 西北
  方向3: (-1,  0)  - 西
  方向4: ( 0, -1)  - 西南
  方向5: (+1, -1)  - 东南
```

**行列坐标与轴坐标的转换**（even-r offset 系统）：

```python
# 行列 -> 轴坐标
q = col - (row // 2)
r = row

# 轴坐标 -> 行列
col = q + (r // 2)
row = r
```

#### 4.1.2 邻接矩阵

使用 **6-邻接图**，通过遍历六个方向查找邻居构建邻接表：

```python
def _build_adjacency_matrix(self) -> Dict[int, List[int]]:
    adjacency = {}
    directions = [(1,0), (1,-1), (0,-1), (-1,0), (-1,1), (0,1)]
    for grid in self.grids:
        neighbors = []
        for dq, dr in directions:
            neighbor = self._find_grid_by_coords(grid.q + dq, grid.r + dr)
            if neighbor:
                neighbors.append(neighbor.grid_id)
        adjacency[grid.grid_id] = neighbors
    return adjacency
```

#### 4.1.3 距离矩阵

**距离公式**（六边形曼哈顿距离）：

```
hex_distance = (|dq| + |dr| + |ds|) / 2
其中 ds = (q1 + r1) - (q2 + r2)
```

**惰性加载策略**：

```python
@property
def distance_matrix(self) -> np.ndarray:
    if not self._distance_matrix_loaded:
        self._distance_matrix = self._try_build_distance_matrix()
        self._distance_matrix_loaded = True
    return self._distance_matrix
```

**内存阈值控制**：

- 默认阈值：`max_precompute_bytes = 800 MB`
- 估算公式：`estimated_bytes = N * N * 4`（float32）
- 超过阈值时跳过预计算，回退到按需计算
- 分配失败时（`MemoryError`）自动回退

**分块向量化计算**：

```python
def _build_distance_matrix_vectorized(self) -> np.ndarray:
    n = len(self.grids)
    dist = np.empty((n, n), dtype=np.float32)
    chunk = 512  # 每次处理 512 行，避免内存峰值
    for start in range(0, n, chunk):
        end = min(start + chunk, n)
        dq = np.abs(qs[start:end, None] - qs[None, :])
        dr = np.abs(rs[start:end, None] - rs[None, :])
        ds = np.abs(qr[start:end, None] - qr[None, :])
        dist[start:end, :] = ((dq + dr + ds) >> 1)
    return dist
```

#### 4.1.4 边缘检测

**边缘网格定义**（`get_edge_grids()`）：
1. 邻居数量少于 6 的网格（自然边界）
2. 位于矩形地图边界的网格（行列极值）

**围栏可部署边**（`get_fencing_edges()`）：
- **内部边**：两个相邻格子之间的边，至少一端是边缘格子（`edge_type=1.0`）
- **边界边**：边缘格子面向外部的边，即没有邻居的方向（`edge_type=2.0`）

#### 4.1.5 笛卡尔坐标转换

采用 **even-r offset** 坐标系统计算像素坐标（pointy-topped 六边形）：

```python
def get_grid_center_coords(self, grid_id, hex_size=1.0):
    col = grid.q + (grid.r // 2)
    row = grid.r
    x = hex_size * sqrt(3) * (col + 0.5 * (row & 1))
    y = hex_size * 3/2 * row
    return (x, y)
```

---

### 4.2 覆盖模型 (`coverage_model.py`)

覆盖模型是系统的核心评估组件，负责计算给定部署方案下每个网格的保护效果。

#### 4.2.1 巡逻覆盖

基于营地和巡逻员的指数衰减模型。巡逻员从营地出发或独立部署，覆盖强度随距离指数衰减。

```python
def calculate_patrol_coverage(self, solution):
    for grid_id in self.grid_ids:
        eff = self._effectiveness(grid_id, 'patrol')  # 地形效率系数
        patrol_intensity = 0.0

        # 从营地出发的巡逻员
        for camp_id, camp_value in solution.camps.items():
            if camp_value == 1:
                rangers = solution.rangers.get(camp_id, 0)
                distance = self.grid_model.get_distance(grid_id, camp_id)
                patrol_intensity += rangers * exp(-distance / patrol_radius)

        # 独立部署的巡逻员（不在营地）
        for ranger_id, ranger_count in solution.rangers.items():
            if ranger_count > 0 and ranger_id not in solution.camps:
                distance = self.grid_model.get_distance(grid_id, ranger_id)
                patrol_intensity += ranger_count * exp(-distance / patrol_radius)

        patrol_coverage[grid_id] = eff * (1 - exp(-patrol_intensity))
```

**公式**：

```
intensity_i = sum(rangers_j * exp(-dist(i,j) / patrol_radius))
P_i = effectiveness_i * (1 - exp(-intensity_i))
```

#### 4.2.2 无人机覆盖

有效半径内指数衰减，考虑地形可见度修正。

```python
def calculate_drone_coverage(self, solution):
    for grid_id in self.grid_ids:
        visibility = visibility_params[grid_id]['drone']
        effective_radius = drone_radius * visibility  # 可见度修正
        coverage = 0.0
        for drone_id in solution.drones:
            distance = get_distance(grid_id, drone_id)
            if distance <= effective_radius * 2:  # 2倍有效半径内
                coverage += exp(-distance / effective_radius)
        drone_coverage[grid_id] = effectiveness * min(1.0, coverage)
```

**公式**：

```
D_i = eff_i * min(1, sum(exp(-dist(i,j) / (drone_radius * vis_j))))
```

#### 4.2.3 摄像头覆盖

有效半径内加权指数衰减，权重为摄像头数量。

```python
def calculate_camera_coverage(self, solution):
    for grid_id in self.grid_ids:
        visibility = visibility_params[grid_id]['camera']
        effective_radius = camera_radius * visibility
        coverage = 0.0
        for cam_id, cam_count in solution.cameras.items():
            distance = get_distance(grid_id, cam_id)
            if distance <= effective_radius * 2:
                coverage += cam_count * exp(-distance / effective_radius)
        camera_coverage[grid_id] = effectiveness * min(1.0, coverage)
```

**公式**：

```
C_i = eff_i * min(1, sum(cam_count_j * exp(-dist(i,j) / (camera_radius * vis_j))))
```

#### 4.2.4 围栏保护

相邻围栏段累积保护，支持内部边和边界边两种格式。

```python
def calculate_fence_protection(self, solution):
    for grid_id in self.grid_ids:
        protection = 0.0
        # 内部边
        for neighbor_id in get_neighbors(grid_id):
            edge_key = tuple(sorted((grid_id, neighbor_id)))
            if edge_key in solution.fences:
                protection += fence_count * fence_protection_coefficient
        # 边界边
        for direction in range(6):
            boundary_key = (grid_id, direction)
            if boundary_key in solution.fences:
                protection += fence_count * fence_protection_coefficient
        fence_protection[grid_id] = effectiveness * min(1.0, protection)
```

**公式**：

```
F_i = eff_i * min(1, sum(fences_k * fence_protection_coefficient))
```

#### 4.2.5 综合保护效果

将四类覆盖效果加权求和，并叠加协同效应。

```python
def calculate_protection_effect(self, solution):
    for grid_id in self.grid_ids:
        P, D, C, F = patrol_cov, drone_cov, camera_cov, fence_prot

        # 基础贡献
        base = wp * P + wd * D + wc * C + wf * F

        # 协同项（归一化防止爆炸增长）
        synergy_pd = alpha_pd * (P * D) / (1.0 + P + D)  # 巡逻+无人机
        synergy_pc = alpha_pc * (P * C) / (1.0 + P + C)  # 巡逻+摄像头

        E_i = base + synergy_pd + synergy_pc
```

**公式**：

```
E_i = wp*P_i + wd*D_i + wc*C_i + wf*F_i
    + alpha_pd * (P_i * D_i) / (1 + P_i + D_i)
    + alpha_pc * (P_i * C_i) / (1 + P_i + C_i)
```

**协同效应说明**：
- `alpha_pd = 0.4`：巡逻+无人机协同（地面+空中联合巡逻效果）
- `alpha_pc = 0.15`：巡逻+摄像头协同（巡逻验证摄像头发现）
- 分母 `(1 + P + D)` 确保协同项有上界，防止数值爆炸

#### 4.2.6 保护收益与适应度

```python
def calculate_total_benefit(self, solution):
    for grid_id in self.grid_ids:
        risk = grid_model.get_grid_risk(grid_id)
        E_i = protection_effect[grid_id]
        protection_benefit[grid_id] = risk * (1 - exp(-E_i))

    total_benefit = sum(protection_benefit.values())
    total_risk = sum(all_risk_values)
    fitness = total_benefit / total_risk  # 归一化适应度
```

**公式**：

```
protection_benefit_i = R_i * (1 - exp(-E_i))
fitness = sum(protection_benefit_i) / sum(R_i)
```

**时间感知适应度**（可选）：

```
fitness_time = sum(protection_benefit_i) / sum(R_i * T_i)
其中 T_i = temporal_factor_i (昼夜因子 x 季节因子)
```

---

### 4.3 向量化覆盖模型 (`coverage_model_vectorized.py`)

#### 4.3.1 设计目标

`VectorizedCoverageModel` 继承 `CoverageModel`，用 NumPy 矩阵运算替代 Python 循环，适合网格数量较大（千级以上）的场景。

#### 4.3.2 预计算向量

初始化时预计算以下向量，避免在每次 `evaluate_fitness` 时重复构建：

| 向量名 | 形状 | 说明 |
|--------|------|------|
| `_risk_vec` | `(N,)` float64 | 各网格风险值 |
| `_deploy_patrol` | `(N,)` float64 | 巡逻部署可行性掩码 |
| `_deploy_drone` | `(N,)` float64 | 无人机部署可行性掩码 |
| `_deploy_camera` | `(N,)` float64 | 摄像头部署可行性掩码 |
| `_deploy_fence` | `(N,)` float64 | 围栏部署可行性掩码 |
| `_eff_patrol` | `(N,)` float64 | 巡逻地形效率系数 |
| `_eff_drone` | `(N,)` float64 | 无人机地形效率系数 |
| `_eff_camera` | `(N,)` float64 | 摄像头地形效率系数 |
| `_eff_fence` | `(N,)` float64 | 围栏地形效率系数 |
| `_vis_drone` | `(N,)` float64 | 无人机可见度向量 |
| `_vis_camera` | `(N,)` float64 | 摄像头可见度向量 |
| `_temporal_vec` | `(N,)` float64 | 时间因子向量 |

#### 4.3.3 距离矩阵策略

```
if 预计算距离矩阵存在:
    使用 float32 矩阵查表 O(1)
else:
    按需分块计算 (chunk=2048)
```

```python
def _compute_dists_to(self, target_indices):
    if self._use_precomputed:
        return self._dist[:, target_indices]  # O(1) 查表

    # 分块向量化回退
    chunk = 2048
    for start in range(0, N, chunk):
        end = min(start + chunk, N)
        dq = np.abs(self._qs[start:end, None] - t_qs[None, :])
        dr = np.abs(self._rs[start:end, None] - t_rs[None, :])
        ds = np.abs(self._qr[start:end, None] - t_qr[None, :])
        out[start:end, :] = ((dq + dr + ds) >> 1)
```

#### 4.3.4 核心向量化方法

`_calculate_coverage_arrays` 一次性返回四个 NumPy 数组：

```python
def _calculate_coverage_arrays(self, solution):
    """返回 (pc, dc, cc, fp) 四个 (N,) float64 数组"""

    # 巡逻覆盖
    ranger_vec = self._ranger_vec(solution)  # (N,) 巡逻强度
    active_p = np.where(ranger_vec > 0)[0]
    dists_p = self._compute_dists_to(active_p)
    weights_p = ranger_vec[active_p]
    intensity = (np.exp(-dists_p / patrol_radius) * weights_p).sum(axis=1)
    pc = (1.0 - np.exp(-intensity)) * self._eff_patrol

    # 无人机覆盖
    drone_idx = self._resource_indices(solution.drones)
    eff_radius_d = drone_radius * self._vis_drone
    dists_d = self._compute_dists_to(drone_idx)
    within_d = dists_d <= eff_radius_d[:, None] * 2
    dc = (np.exp(-dists_d / eff_radius_d[:, None]) * within_d).sum(axis=1)
    dc = np.minimum(1.0, dc) * self._eff_drone

    # 摄像头覆盖（类似无人机，但有权重）
    # 围栏保护
    fence_counts = self._fence_vec(solution)
    fp = np.minimum(1.0, fence_counts * fence_protection) * self._eff_fence

    return pc, dc, cc, fp
```

#### 4.3.5 适用场景

| 网格规模 | 推荐模型 | 预期加速比 |
|----------|----------|-----------|
| < 100 | CoverageModel | 基准 |
| ~120 | VectorizedCoverageModel | ~4x |
| > 1000 | VectorizedCoverageModel | ~10x+ |

通过 `protection_pipeline.py` 的 `--vectorized` 参数启用。

---

### 4.4 DSSA 优化器 (`dssa_optimizer.py`)

#### 4.4.1 算法概述

DSSA（Discrete Sparrow Search Algorithm）是一种受麻雀觅食行为启发的元启发式优化算法。本系统将其改造为离散版本，用于解决资源部署的组合优化问题。

**三种群策略**：

| 角色 | 占比 | 位置 | 职责 |
|------|------|------|------|
| **Producer** | 20% | 种群前部 | 向最优解探索，执行开发操作 |
| **Follower** | 50% | 种群中部 | 向 Producer/Best 靠拢或随机探索 |
| **Scout** | 30% | 种群后部 | 监测种群停滞，触发重置 |

**离散编码**：每个资源类型独立编码为网格索引向量，通过 `_solution_to_vector` 和 `_vector_to_solution` 进行转换。

```
向量结构: [cameras(N) | camps(N) | drones(N) | rangers(N) | fences(N)]
总长度: 5N（N 为网格数量）
```

#### 4.4.2 初始化

```python
def initialize_population(self):
    for _ in range(population_size):
        self.population.append(self._initialize_solution())

    if warm_start_solution is not None:
        self._inject_warm_start(warm_start_solution)
```

**风险优先初始化**（`use_risk_priority=True`）：
- 将网格按风险值排序，高风险网格优先部署资源
- 高风险网格占比由 `high_risk_percentage` 控制（默认 30%）

**热启动**（`warm_start_solution`）：
- 注入 `population_size // 3` 个热启动个体
- 第一个为原始热启动解，其余为扰动版本

**围栏初始化**：
- 如果可部署边界边数量 <= `total_fence_length`，部署所有边界边
- 否则随机选择 `total_fence_length` 条边界边

#### 4.4.3 Producer 阶段

```python
def _update_producers(self, iteration, alpha):
    for i, producer in enumerate(producers):
        R2 = random.uniform(0, 1)
        if R2 < ST:  # ST = 0.8
            if i == 0:
                new_solution = self._exploit_toward_best(solution)  # 向最优解靠拢
            else:
                new_solution = self._discrete_perturb(solution)      # 离散扰动
        else:
            new_solution = self._discrete_perturb(solution)          # 探索
            if random.random() < 0.5:
                new_solution = self._discrete_perturb(new_solution)  # 二次探索
```

**Producer 0 开发操作**（`_exploit_toward_best`）：
- 随机选择交叉比例（30%-70%）
- 将当前解的部署位置替换为最优解的部署位置
- 对每种资源类型独立执行交叉

**离散扰动操作**（`_discrete_perturb`）：
- 以 `swap_prob=0.6` 概率执行离散交换（将资源从一个网格移到另一个）
- 以 `migrate_prob=0.25` 概率执行资源迁移
- 以 `reshuffle_prob=0.15` 概率执行全局重排

#### 4.4.4 Follower 阶段

```python
def _update_followers(self, alpha):
    for i, follower in enumerate(followers):
        R2 = random.uniform(0, 1)
        if R2 < ST:
            if random.random() < follower_explore_ratio:  # 0.5
                new_solution = self._discrete_perturb(solution)  # 随机探索
            else:
                if i > len(followers) / 2:
                    new_solution = self._exploit_toward_best(solution)  # 向 best 靠拢
                else:
                    new_solution = self._follow_producer(solution, producer)  # 向 producer 靠拢
        else:
            new_solution = self._discrete_perturb(solution)
```

**向 Producer 靠拢**（`_follow_producer`）：
- 随机选择交叉比例（20%-50%）
- 从 Producer 继承部分部署位置

#### 4.4.5 Scout 阶段

```python
def _update_scouts(self):
    for solution, fitness in zip(scout_solutions, scout_fitnesses):
        if fitness < scout_reset_threshold * best_fitness:  # 0.95
            if fitness < 0.5 * best_fitness:
                # 完全重置
                self.population[pop_idx] = self._initialize_solution()
            else:
                # 部分重置：只重置部分资源类型
                self.population[pop_idx] = self._partial_reset_scout(solution)
```

**部分重置**（`_partial_reset_scout`）：
- 随机选择 `scout_partial_reset_ratio`（50%）比例的资源类型进行重置
- 保留表现好的资源部署

#### 4.4.6 高级特性

**停滞检测与增强**：

```python
def _get_exploration_alpha(self, iteration):
    # 三阶段调度
    if progress < 0.3:   scheduled = initial_alpha  # 3.0
    elif progress < 0.7: scheduled = mid_alpha      # 2.0
    else:                scheduled = final_alpha     # 1.0

    # 停滞增强
    if stagnation_count > stagnation_threshold:  # > 10
        extra = (stagnation_count - threshold) // 10
        amplified_boost = stagnation_boost * (1.0 + 0.5 * extra)
        return scheduled * amplified_boost
    return scheduled
```

**适应度缓存**：
- 使用 LRU 策略，最大缓存 `fitness_cache_max_size=10000` 条
- 基于 `_cache_key`（部署方案的哈希值）进行缓存查找
- 缓存键在 `DeploymentSolution` 对象上惰性计算并存储

**并行评估**：
```python
self._fitness_executor = ThreadPoolExecutor(
    max_workers=min(fitness_workers, population_size),
    thread_name_prefix='fitness'
)

def _evaluate_fitness_parallel(self, solutions):
    futures = [self._fitness_executor.submit(evaluate_fitness, sol) for sol in solutions]
    return [f.result() for f in futures]
```

**多样性维护**：
```python
diversity = self._calculate_diversity()
if diversity < diversity_min_threshold:  # < 0.3
    self._inject_random_solutions(diversity_inject_ratio)  # 注入 20% 随机解
```

**冻结资源**：
- 通过 `frozen_resources` 参数指定不优化的资源类型
- 每次迭代后通过 `_apply_frozen_resources` 恢复冻结资源的初始值

**约束修复**（`repair_solution`）：
1. 移除不可行部署（地形不允许的位置）
2. 解决资源冲突（单格多资源类型）
3. 裁剪超量资源（全局总量超限）
4. 补充不足资源（`force_full_deployment=True` 时）

---

### 4.5 风险模型 (`riskIndex`)

#### 4.5.1 综合风险公式

```
R'_i = (w_h * H_i + w_e * E_i + w_d * D_i) x T_t x S_t
R_i  = (R'_i - min) / (max - min)    # 归一化到 [0, 1]
```

其中：
- `w_h, w_e, w_d`：人为风险、环境风险、物种密度权重（默认 0.4, 0.3, 0.3）
- `H_i`：人为风险
- `E_i`：环境风险
- `D_i`：物种密度风险
- `T_t`：昼夜时间因子
- `S_t`：季节因子

#### 4.5.2 人为风险 (`human.py`)

```
H_i = (alpha_1 * prox_boundary + alpha_2 * prox_road + alpha_3 * prox_water) x P_t
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `boundary_weight` | 0.2 | 边界距离权重 |
| `road_weight` | 0.3 | 道路距离权重 |
| `water_weight` | 0.5 | 水源距离权重 |
| `P_t` | 1.0 | 偷猎概率因子 |

**距离计算**（`DistanceCalculator`）：
- 支持矩形边界和不规则边界（`boundary_locations`）
- 欧氏距离计算，归一化到 [0, 1]
- 距离越近，风险越高（反转归一化）

#### 4.5.3 环境风险 (`environmental.py`)

```
E_i = beta_1 * fire_risk + beta_2 * terrain_complexity
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `fire_weight` | 0.6 | 火灾风险权重 |
| `terrain_weight` | 0.4 | 地形复杂度权重 |

#### 4.5.4 物种密度风险 (`density.py`)

```
D_i = sum(w_s * density_s * seasonal_multiplier_s)
```

默认物种配置：

| 物种 | 权重 | 雨季乘数 | 旱季乘数 |
|------|------|----------|----------|
| rhino（犀牛） | 0.5 | 1.2 | 1.0 |
| elephant（大象） | 0.3 | 1.3 | 0.9 |
| bird（鸟类） | 0.2 | 1.5 | 0.8 |

#### 4.5.5 时间因子 (`temporal.py`)

**昼夜因子**（两种模式）：

- **离散模式**（默认）：
  ```
  T_t = daytime_factor    (6:00-18:00, 默认 1.0)
  T_t = nighttime_factor  (18:00-6:00, 默认 1.3)
  ```

- **连续模式**（正弦波）：
  ```
  T_t = 1.0 + gamma * sin(2*pi*(hour-6)/24)
  默认 gamma=0.3，正午最低，午夜最高
  ```

**季节因子**：
```
S_t = dry_season_factor     (DRY, 默认 1.0)
S_t = rainy_season_factor   (RAINY, 默认 1.2)
```

#### 4.5.6 归一化引擎 (`NormalizationEngine`)

```python
class NormalizationEngine:
    def fit(self, raw_risks):
        self._min_risk = min(raw_risks)
        self._max_risk = max(raw_risks)

    def normalize(self, raw_risk):
        if self._max_risk == self._min_risk:
            return 0.5  # 所有值相同
        normalized = (raw_risk - self._min_risk) / (self._max_risk - self._min_risk)
        return max(0.0, min(1.0, normalized))  # 钳位到 [0, 1]
```

**批量计算流程**（`RiskModel.calculate_batch`）：
1. 逐网格计算原始风险 `R'_i`
2. 拟合归一化器（找 min/max）
3. 批量归一化到 [0, 1]

---

## 5. 部署约束体系

### 5.1 四层约束

#### 第一层：部署可行性矩阵

由 `DataLoader.initialize_deployment_matrix()` 生成，基于地形类型决定每种资源是否可部署。

| 地形 | patrol | camp | drone | camera | fence |
|------|--------|------|-------|--------|-------|
| SaltMarsh（盐沼） | 0 | 0 | 1 | 0 | 0 |
| SparseGrass（稀疏草地） | 1 | 0 | 1 | 1 | 1 |
| DenseGrass（密集草地） | 0 | 0 | 1 | 0 | 1 |
| WaterHole（水坑） | 0 | 0 | 1 | 0 | 0 |
| Road（道路） | 1 | 1 | 1 | 1 | 1 |

**额外约束**：`patrol` 和 `camp` 不能部署在物种密度不为零的网格。

**围栏特殊规则**：
- 围栏只能在边缘网格部署
- 部署矩阵值为该网格的边界边数量（0-6），而非简单的 0/1

#### 第二层：单格上限

| 资源 | 参数 | 默认值 |
|------|------|--------|
| 摄像头 | `max_cameras_per_grid` | 1 |
| 无人机 | `max_drones_per_grid` | 1 |
| 营地 | `max_camps_per_grid` | 1 |
| 巡逻员 | `max_rangers_per_grid` | 1 |
| 围栏 | `max_fences_per_grid` | 6 |

#### 第三层：全局总量

| 资源 | 参数 |
|------|------|
| 巡逻人员总数 | `total_patrol` |
| 营地总数 | `total_camps` |
| 摄像头总数 | `total_cameras` |
| 无人机总数 | `total_drones` |
| 围栏总长度 | `total_fence_length` |

#### 第四层：互斥规则

1. **巡逻 vs 营地**：同一网格不能同时部署巡逻员和营地
2. **单格单资源**：同一网格只能部署一种资源类型（patrol/camp/drone/camera 互斥）

### 5.2 约束执行时机

| 阶段 | 方法 | 说明 |
|------|------|------|
| 初始化 | `_initialize_solution` | 按优先级顺序部署资源，避免冲突 |
| 向量解码 | `_vector_to_solution` | 解码时检查部署可行性矩阵 |
| 修复 | `repair_solution` | 全面修复：可行性、冲突、总量、补充 |
| 验证 | `validate_solution` | 检查所有约束，返回违规列表 |

### 5.3 覆盖效果折扣

独立于部署可行性矩阵，通过 `coverage_effectiveness` 控制：

```python
DEFAULT_COVERAGE_EFFECTIVENESS = {
    'DenseGrass': {'patrol': 0.3, 'camp': 0.3},
}
```

**说明**：DenseGrass 地形虽然不允许部署巡逻和营地（部署可行性为 0），但覆盖效果折扣表定义了如果部署的话效率降至 0.3。这主要用于覆盖效果计算中，确保即使有特殊情况也不会产生过高的覆盖估计。

**地形可见度**（影响无人机和摄像头有效半径）：

| 地形 | drone 可见度 | camera 可见度 |
|------|-------------|--------------|
| SparseGrass | 1.0 | 1.0 |
| DenseGrass | 0.7 | 0.5 |
| SaltMarsh | 0.9 | 0.6 |
| WaterHole | 1.0 | 0.8 |
| Road | 1.0 | 1.0 |

---

## 6. 数据流

### 6.1 输入 JSON 格式

`pipeline_input.json` 的顶层结构：

```json
{
  "map_config": {
    "map_width": 12,
    "map_height": 10,
    "boundary_type": "RECTANGLE",
    "road_locations": [[2, 3], [5, 7]],
    "water_locations": [[1, 1], [8, 5]],
    "boundary_locations": [[0, 0], [1, 0], ...]
  },
  "time": {
    "hour_of_day": 12,
    "season": "DRY"
  },
  "risk_model_config": {
    "risk_weights": {
      "human_weight": 0.4,
      "environmental_weight": 0.3,
      "density_weight": 0.3
    },
    "human_risk_weights": {
      "boundary_weight": 0.2,
      "road_weight": 0.3,
      "water_weight": 0.5
    },
    "environmental_risk_weights": {
      "fire_weight": 0.6,
      "terrain_weight": 0.4
    },
    "temporal_weights": {
      "daytime_factor": 1.0,
      "nighttime_factor": 1.3,
      "gamma": 0.3,
      "dry_season_factor": 1.0,
      "rainy_season_factor": 1.2
    }
  },
  "species_config": {
    "rhino": {"weight": 0.5, "rainy_season_multiplier": 1.2, "dry_season_multiplier": 1.0},
    "elephant": {"weight": 0.3, "rainy_season_multiplier": 1.3, "dry_season_multiplier": 0.9},
    "bird": {"weight": 0.2, "rainy_season_multiplier": 1.5, "dry_season_multiplier": 0.8}
  },
  "constraints": {
    "total_patrol": 20,
    "total_camps": 5,
    "max_rangers_per_camp": 5,
    "total_cameras": 10,
    "total_drones": 3,
    "total_fence_length": 50,
    "max_cameras_per_grid": 1,
    "max_drones_per_grid": 1,
    "max_camps_per_grid": 1,
    "max_rangers_per_grid": 1,
    "max_fences_per_grid": 6
  },
  "coverage_params": {
    "patrol_radius": 5.0,
    "drone_radius": 8.0,
    "camera_radius": 3.0,
    "fence_protection": 0.5,
    "wp": 0.3, "wd": 0.3, "wc": 0.2, "wf": 0.2,
    "alpha_pd": 0.4, "alpha_pc": 0.15
  },
  "dssa_config": {
    "population_size": 50,
    "max_iterations": 100,
    "producer_ratio": 0.2,
    "scout_ratio": 0.2,
    "ST": 0.8,
    "use_time_aware_fitness": false,
    "force_full_deployment": true,
    "use_risk_priority": false
  },
  "use_temporal_factors": false,
  "grids": [
    {
      "grid_id": 0,
      "q": 0, "r": 0,
      "x": 0, "y": 0,
      "terrain_type": "SparseGrass",
      "fire_risk": 0.3,
      "terrain_complexity": 0.2,
      "vegetation_type": "GRASSLAND",
      "species_densities": {"rhino": 0.5, "elephant": 0.3, "bird": 0.1}
    }
  ]
}
```

### 6.2 处理流程

```
1. 读取输入 JSON
   load_input(input_path)

2. riskIndex 计算归一化风险
   compute_risk_with_riskindex(data)
   -> risk_map: {grid_id: normalized_risk}
   -> temporal_factor_map: {grid_id: T_t * S_t}
   -> raw_risk_map: {grid_id: raw_risk}

3. 构建数据加载器
   build_data_loader(data, risk_map, temporal_factor_map)
   -> DataLoader (grids, constraints, coverage_params, deployment_matrix, ...)

4. 构建网格模型和覆盖模型
   HexGridModel(loader.grids)
   CoverageModel / VectorizedCoverageModel(grid_model, ...)

5. DSSA 优化
   DSSAOptimizer(coverage_model, constraints, dssa_config, ...)
   optimizer.optimize()
   -> best_solution, best_fitness, fitness_history

6. 计算保护收益并输出
   calculate_protection_benefit(best_solution)
   -> 输出 JSON (summary + grids)
```

### 6.3 输出 JSON 格式

```json
{
  "summary": {
    "total_grids": 120,
    "total_risk": 45.678,
    "total_risk_weighted": 52.340,
    "best_fitness": 0.654321,
    "total_protection_benefit": 29.876,
    "average_protection_benefit": 0.248967,
    "risk_min": 0.0, "risk_max": 1.0, "risk_mean": 0.380650,
    "raw_risk_min": 0.05, "raw_risk_max": 0.85, "raw_risk_mean": 0.38,
    "residual_risk_min": 0.0, "residual_risk_max": 0.85, "residual_risk_mean": 0.15,
    "total_residual_risk": 18.234,
    "fitness_history": [0.1, 0.2, 0.35, ...],
    "resources_deployed": {
      "total_cameras": 10,
      "total_drones": 3,
      "total_camps": 5,
      "total_rangers": 20,
      "fence_segments": 50
    }
  },
  "visualization_config": {
    "show_grid_ids": false
  },
  "grids": [
    {
      "grid_id": 0,
      "q": 0, "r": 0,
      "x": 0, "y": 0,
      "terrain_type": "SparseGrass",
      "risk_normalized": 0.5,
      "raw_risk": 0.42,
      "protection_benefit_raw": 0.15,
      "protection_benefit_normalized": 0.3,
      "residual_risk_normalized": 0.35,
      "deployment": {
        "patrol_rangers": 1,
        "camp": 0,
        "drone": 0,
        "camera": 1
      },
      "fences": {
        "fence_count": 2,
        "boundary_edge_list": [0, 5]
      }
    }
  ]
}
```

---

## 7. 性能优化

### 7.1 向量化加速

**VectorizedCoverageModel vs CoverageModel**：

| 特性 | CoverageModel | VectorizedCoverageModel |
|------|---------------|------------------------|
| 覆盖计算 | Python 循环 | NumPy 矩阵运算 |
| 距离查询 | 逐对调用 `get_distance` | 批量矩阵切片 |
| 适用场景 | 小规模（< 100 网格） | 中大规模（> 100 网格） |
| 内存占用 | 低 | 需要预计算向量 |

**预期加速比**：

| 网格数 | 基础版耗时 | 向量化版耗时 | 加速比 |
|--------|-----------|-------------|--------|
| ~120 | 基准 | ~1/4 | ~4x |
| ~500 | 基准 | ~1/8 | ~8x |
| > 1000 | 基准 | ~1/10 | ~10x+ |

### 7.2 内存管理

**距离矩阵惰性加载**：

```
初始化时:
  _distance_matrix = None
  _distance_matrix_loaded = False

首次访问 distance_matrix 属性时:
  1. 估算内存: N * N * 4 bytes
  2. if 估算 > max_precompute_bytes (800MB):
       跳过预计算，返回 None
  3. 尝试构建:
       成功 -> 缓存矩阵
       MemoryError -> 返回 None，回退到按需计算
```

**稀疏矩阵回退**：

当预计算矩阵不可用时，`get_distance_sparse(max_radius)` 提供基于半径的稀疏距离矩阵，使用二分搜索优化候选网格范围。

### 7.3 并行计算

| 场景 | 并行方式 | 实现 |
|------|----------|------|
| DSSA 适应度评估 | `ThreadPoolExecutor` | `_evaluate_fitness_parallel` |
| Producer/Follower 更新 | 批量提交 | `_update_producers`, `_update_followers` |
| 敏感性分析 | 多进程 | `sensitivity_analysis.py` (subprocess) |
| 蒙特卡洛试验 | 多进程 | `monte_carlo_robust.py` (subprocess) |
| 迭代结果输出 | 异步线程 | `_async_output_iteration_results` |

**适应度并行评估**：

```python
# 线程池大小: min(fitness_workers, population_size)
# 默认 fitness_workers=16
self._fitness_executor = ThreadPoolExecutor(max_workers=16)
```

### 7.4 缓存机制

| 缓存类型 | 位置 | 策略 | 大小限制 |
|----------|------|------|----------|
| 适应度缓存 | `DSSAOptimizer._fitness_cache` | LRU (dict) | 10000 条 |
| 敏感性分析 | 磁盘 JSON | 按参数组合缓存 | 无限制 |
| 热启动 | 输出 JSON | 读取上次优化结果 | 无限制 |

**适应度缓存键生成**：

```python
def _make_cache_key(self, solution):
    key = hash((
        tuple(sorted(solution.cameras.items())),
        tuple(sorted(solution.camps.items())),
        tuple(sorted(solution.drones.items())),
        tuple(sorted(solution.rangers.items())),
        tuple(sorted(solution.fences.items())),
    ))
    solution._cache_key = key  # 缓存到对象上，避免重复计算
    return key
```

---

## 8. 扩展性设计

### 8.1 添加新资源类型

如需添加新的保护资源类型（如传感器、观察塔等），需修改以下组件：

**1. 数据结构**（`data_loader.py`）：

```python
# 在 DeploymentSolution 中添加新字段
@dataclass
class DeploymentSolution:
    cameras: Dict[int, int]
    camps: Dict[int, int]
    drones: Dict[int, int]
    rangers: Dict[int, int]
    fences: Dict[Tuple[int, int], int]
    sensors: Dict[int, int] = field(default_factory=dict)  # 新增

# 在 ResourceConstraints 中添加约束
@dataclass
class ResourceConstraints:
    ...
    total_sensors: int = 0
    max_sensors_per_grid: int = 1
```

**2. 部署可行性矩阵**（`data_loader.py`）：

```python
# 在 terrain_deployment 中添加新列
terrain_deployment = {
    'SparseGrass': {'patrol': 1, 'camp': 0, 'drone': 1, 'camera': 1, 'fence': 1, 'sensor': 1},
    ...
}
```

**3. 覆盖模型**（`coverage_model.py`）：

```python
# 添加覆盖计算方法
def calculate_sensor_coverage(self, solution):
    ...

# 在 calculate_protection_effect 中整合
def calculate_protection_effect(self, solution):
    ...
    S = self.calculate_sensor_coverage(solution)
    base = wp*P + wd*D + wc*C + wf*F + ws*S
```

**4. DSSA 优化器**（`dssa_optimizer.py`）：

```python
# 在 _solution_to_vector 和 _vector_to_solution 中添加编码
# 在 _exploit_toward_best 和 _follow_producer 中添加交叉逻辑
# 在 _discrete_perturb 中添加扰动逻辑
```

### 8.2 修改覆盖模型

覆盖模型采用策略模式设计，修改覆盖计算逻辑只需：

**1. 修改衰减函数**：

```python
# 将指数衰减替换为其他衰减函数
# 原始: exp(-distance / radius)
# 替换: 1 / (1 + (distance / radius)^2)  # 逆二次衰减
```

**2. 修改协同模型**：

```python
# 在 CoverageParameters 中添加新的协同参数
@dataclass
class CoverageParameters:
    ...
    alpha_dc: float = 0.1  # 无人机+摄像头协同

# 在 calculate_protection_effect 中添加
synergy_dc = alpha_dc * (D * C) / (1.0 + D + C)
E_i = base + synergy_pd + synergy_pc + synergy_dc
```

**3. 使用向量化版本**：

`VectorizedCoverageModel` 继承 `CoverageModel`，只需重写需要向量化的方法，其余方法自动继承。

### 8.3 自定义可视化

可视化模块（`visualize_output.py`）读取输出 JSON，生成热力图和部署图。自定义可视化只需：

**1. 修改颜色映射**：

```python
# 在 visualize_output.py 中修改 colormap
cmap = plt.cm.RdYlGn_r  # 红-黄-绿反转
```

**2. 添加新的可视化层**：

```python
# 添加资源覆盖范围的可视化
for grid_id in drone_locations:
    center = grid_model.get_grid_center_coords(grid_id)
    circle = plt.Circle(center, drone_radius, fill=False, color='blue')
    ax.add_patch(circle)
```

**3. 迭代可视化**：

通过 `dssa_config.output_dir` 和 `save_iteration_visualization` 启用每轮迭代的部署图输出，可用于制作优化过程动画。

---

## 附录 A：地形类型与资源部署规则汇总

| 地形 | 中文 | patrol | camp | drone | camera | fence | 巡逻效率 | 无人机可见度 | 摄像头可见度 |
|------|------|--------|------|-------|--------|-------|----------|-------------|-------------|
| SparseGrass | 稀疏草地 | 1 | 0 | 1 | 1 | 1 | 1.0 | 1.0 | 1.0 |
| DenseGrass | 密集草地 | 0 | 0 | 1 | 0 | 1 | 0.3 | 0.7 | 0.5 |
| WaterHole | 水坑 | 0 | 0 | 1 | 0 | 0 | 1.0 | 1.0 | 0.8 |
| SaltMarsh | 盐沼 | 0 | 0 | 1 | 0 | 0 | 1.0 | 0.9 | 0.6 |
| Road | 道路 | 1 | 1 | 1 | 1 | 1 | 1.0 | 1.0 | 1.0 |

## 附录 B：DSSA 优化流程图

```
开始
  |
  v
initialize_population()
  |-- _initialize_solution() x population_size
  |-- _inject_warm_start() (如果提供热启动解)
  |
  v
评估初始适应度 -> 记录 best_solution, best_fitness
  |
  v
+---> 迭代 iteration = 0 .. max_iterations-1
|       |
|       |-- 计算 effective_alpha (三阶段调度 + 停滞增强)
|       |
|       |-- _update_producers()
|       |     |-- Producer 0: _exploit_toward_best() (离散交叉)
|       |     |-- 其他 Producer: _discrete_perturb() (交换/迁移/重排)
|       |     |-- 并行评估适应度，贪心更新
|       |
|       |-- _update_followers()
|       |     |-- ST < R2: 随机探索 / 向best靠拢 / 向producer靠拢
|       |     |-- ST >= R2: 离散扰动
|       |     |-- 并行评估适应度，贪心更新
|       |
|       |-- _update_scouts()
|       |     |-- fitness < 0.95 * best: 部分重置
|       |     |-- fitness < 0.50 * best: 完全重置
|       |
|       |-- 多样性检查
|       |     |-- diversity < 0.3: 注入 20% 随机解
|       |
|       |-- 停滞检测
|       |     |-- 改善 > tolerance: 重置计数器
|       |     |-- 否则: stagnation_count++
|       |
|       |-- 异步输出迭代结果 (如果配置了 output_dir)
|       |
+-------+
  |
  v
输出 best_solution, best_fitness, fitness_history
  |
  v
结束
```

## 附录 C：风险模型计算流程

```
输入: grid_data, time_context, risk_model_config, species_config
  |
  v
对每个网格 i:
  |
  +-- HumanRiskCalculator.calculate()
  |     H_i = (w_b * prox_boundary + w_r * prox_road + w_w * prox_water) * P_t
  |
  +-- EnvironmentalRiskCalculator.calculate()
  |     E_i = w_f * fire_risk + w_t * terrain_complexity
  |
  +-- DensityRiskCalculator.calculate()
  |     D_i = sum(w_s * density_s * seasonal_multiplier_s)
  |
  +-- TemporalFactorCalculator.calculate()
  |     T_t = diurnal_factor(hour)
  |     S_t = seasonal_factor(season)
  |
  v
CompositeRiskCalculator.calculate_raw():
  R'_i = (w_h * H_i + w_e * E_i + w_d * D_i) * T_t * S_t
  |
  v
NormalizationEngine:
  fit(all raw risks) -> min, max
  R_i = (R'_i - min) / (max - min)
  |
  v
输出: {grid_id: (normalized_risk, raw_risk, temporal_factor)}
```

## 附录 D：关键文件路径索引

| 模块 | 文件 | 绝对路径 |
|------|------|----------|
| 网格模型 | grid_model.py | `d:\code\immc2026-BAI\hexdynamic\grid_model.py` |
| 覆盖模型 | coverage_model.py | `d:\code\immc2026-BAI\hexdynamic\coverage_model.py` |
| 向量化覆盖 | coverage_model_vectorized.py | `d:\code\immc2026-BAI\hexdynamic\coverage_model_vectorized.py` |
| DSSA 优化器 | dssa_optimizer.py | `d:\code\immc2026-BAI\hexdynamic\dssa_optimizer.py` |
| 数据加载 | data_loader.py | `d:\code\immc2026-BAI\hexdynamic\data_loader.py` |
| 优化流水线 | protection_pipeline.py | `d:\code\immc2026-BAI\hexdynamic\protection_pipeline.py` |
| 地图生成 | generate_map.py | `d:\code\immc2026-BAI\hexdynamic\generate_map.py` |
| Marker 转换 | marker_to_pipeline.py | `d:\code\immc2026-BAI\marker_to_pipeline.py` |
| 风险模型封装 | risk_model_wrapper.py | `d:\code\immc2026-BAI\riskIndex\risk_model_wrapper.py` |
| 综合风险 | composite.py | `d:\code\immc2026-BAI\riskIndex\src\risk_model\risk\composite.py` |
| 人为风险 | human.py | `d:\code\immc2026-BAI\riskIndex\src\risk_model\risk\human.py` |
| 环境风险 | environmental.py | `d:\code\immc2026-BAI\riskIndex\src\risk_model\risk\environmental.py` |
| 物种密度 | density.py | `d:\code\immc2026-BAI\riskIndex\src\risk_model\risk\density.py` |
| 时间因子 | temporal.py | `d:\code\immc2026-BAI\riskIndex\src\risk_model\risk\temporal.py` |
