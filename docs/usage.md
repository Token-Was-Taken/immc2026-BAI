# 使用说明

本文档说明如何使用以下工具完成从地图标注到保护资源部署优化的完整流程。

***

## 整体流程

```
地图图片
  │
  ▼
[Marker] 在图片上绘制六边形网格，标注地形与物种信息
  │  导出 pipeline_input.json
  │
  │  或者
  │
[generate_map.py] 随机生成 m×n 地图数据
  │  输出 pipeline_input.json
  ├─────────────────────────────────────┐
  │                                     │
  ▼                                     ▼
[risk_analysis.py]                   [run.py]  ← 推荐入口
计算风险指数                      计算风险指数 → DSSA 优化 → 可视化
生成热力图+属性图                  （整合 protection_pipeline + visualize_output）
                                         │
                                    也可分步运行：
                                    [protection_pipeline.py] → output.json
                                    [visualize_output.py]    → 图片
                                    │
                                    ▼
                              [run_with_iteration_output.py]  ← 迭代输出版
                              优化 + 每轮迭代JSON输出 + 可视化
                                         │
                                    已有迭代结果时：
                                    [visualize_iterations.py] ← 独立可视化
                                    后处理 + 批量出图（支持全局色阶）
```

***

## 一、Marker 标注工具

**文件**：`marker/image-viewer.html`，直接用浏览器打开，无需安装依赖。

### 基本操作

- **加载图片**：将地图图片拖入页面，或点击上传区域选择文件。
- **网格化**：点击 `⬡ 网格化` 按钮叠加六边形网格，拖动 `半径` 滑块调整网格大小。
- **标注地形**：调色板中每种颜色对应一种地形类型：

|   颜色  | 地形类型  | `terrain_type` |
| :---: | :---- | :------------- |
| 🟢 绿色 | 森林密集区 | DenseGrass     |
| 🔴 红色 | 森林稀疏区 | SparseGrass    |
| 🔵 蓝色 | 水坑    | WaterHole      |
| 🟡 黄色 | 干坑    | SaltMarsh      |
| 🟣 紫色 | 主路    | Road           |
| 🟠 橙色 | 小路    | Road           |
| 🩵 青色 | 盐沼    | SaltMarsh      |

- 单击色块选色，再单击格子填色；框选可批量填色
- 再次单击已填色格子取消填色
- `Ctrl/Cmd + 点击` 多选后点色块统一填色
- `📥 导入JSON` / `📤 导出JSON`：导入或导出网格标注数据
- `📥 导出SVG`：导出带图例的矢量网格图

### 导出 Pipeline 输入 JSON

完成标注后点击 `🚀 导出Pipeline JSON`，在弹出的配置面板中填写参数后点击 `📥 生成并下载`，下载 `pipeline_input.json`。

> 配置面板参数说明见第二节（与 `generate_map.py` 参数一致）。

> 未标注颜色的格子默认视为 SparseGrass。主路/小路格子坐标自动提取为 `road_locations`，水坑格子自动提取为 `water_locations`。

***

## 二、地图生成脚本

**文件**：`hexdynamic/generate_map.py`

随机生成 m×n 规模的地图，直接输出 pipeline 输入 JSON，无需手动标注。

### 用法

```bash
# 基本用法（10×12，默认参数）
python generate_map.py -m 10 -n 12 -o pipeline_input.json

# 指定资源约束和时间
python generate_map.py -m 20 -n 25 --total_patrol 40 --total_cameras 20 --season RAINY -o map.json

# 固定随机种子（可复现）
python generate_map.py -m 15 -n 15 --seed 42 -o map.json
```

### 生成规则

- 道路随机选南北或东西方向贯穿，每隔 2\~3 格随机横向偏移 ±1，不是直线
- 犀牛/大象密度只在 SparseGrass 格子生成，其他地形为 0
- 鸟类密度在 SaltMarsh 为 0.6\~1.0，其他地形为 0\~0.1

### 命令行参数

| 参数                       | 默认值                   | 说明                        |
| :----------------------- | :-------------------- | :------------------------ |
| `-m`                     | 10                    | 地图行数                      |
| `-n`                     | 12                    | 地图列数                      |
| `-o`                     | `pipeline_input.json` | 输出文件路径                    |
| `--seed`                 | None                  | 随机种子                      |
| `--hour_of_day`          | 12                    | 时间（0-23）                  |
| `--season`               | DRY                   | 季节：DRY / RAINY            |
| `--use_temporal_factors` | False                 | 启用昼夜/季节时间因子               |
| `--total_patrol`         | 20                    | 巡逻人员总数                    |
| `--total_camps`          | 5                     | 营地总数                      |
| `--max_rangers_per_camp` | 5                     | 每营地最大人员                   |
| `--total_cameras`        | 10                    | 摄像头总数                     |
| `--total_drones`         | 3                     | 无人机总数                     |
| `--total_fence_length`   | 50                    | 围栏参数（已不影响结果，围栏固定部署在所有边缘格） |
| `--patrol_radius`        | 5.0                   | 巡逻覆盖衰减半径                  |
| `--drone_radius`         | 8.0                   | 无人机覆盖半径                   |
| `--camera_radius`        | 3.0                   | 摄像头覆盖半径                   |
| `--fence_protection`     | 0.5                   | 每段围栏保护系数                  |
| `--wp/wd/wc/wf`          | 0.3/0.3/0.2/0.2       | 巡逻/无人机/摄像头/围栏权重           |
| `--population_size`      | 50                    | DSSA 种群大小                 |
| `--max_iterations`       | 100                   | DSSA 最大迭代次数               |
| `--human_weight`         | 0.4                   | 综合风险：人为风险权重 ω₁            |
| `--environmental_weight` | 0.3                   | 综合风险：环境风险权重 ω₂            |
| `--density_weight`       | 0.3                   | 综合风险：物种密度权重 ω₃            |
| `--boundary_weight`      | 0.2                   | 人为风险：边界邻近度权重              |
| `--road_weight`          | 0.3                   | 人为风险：道路邻近度权重              |
| `--water_weight`         | 0.5                   | 人为风险：水源邻近度权重              |
| `--fire_weight`          | 0.6                   | 环境风险：火灾风险权重               |
| `--terrain_weight`       | 0.4                   | 环境风险：地形复杂度权重              |
| `--daytime_factor`       | 1.0                   | 时间因子：白天风险因子               |
| `--nighttime_factor`     | 1.3                   | 时间因子：夜间风险因子               |
| `--gamma`                | 0.3                   | 时间因子：昼夜正弦波振幅              |
| `--dry_season_factor`    | 1.0                   | 时间因子：旱季风险因子               |
| `--rainy_season_factor`  | 1.2                   | 时间因子：雨季风险因子               |

***

## 三、Protection Pipeline 脚本

**文件**：`hexdynamic/protection_pipeline.py`

> 推荐使用 `run.py`（见第四节）一键完成优化+可视化。`protection_pipeline.py` 适合只需要输出 JSON、不需要图片的场景。

### 依赖安装

```bash
pip install -r hexdynamic/requirements.txt
pip install -r riskIndex/requirements.txt
```

### 用法

```bash
cd hexdynamic

# 默认模式
python protection_pipeline.py <input.json> <output.json>

# 向量化模式（大规模网格推荐，千级以上网格约 4x+ 加速）
python protection_pipeline.py <input.json> <output.json> --vectorized

# 冻结部分资源（不参与优化）
python protection_pipeline.py <input.json> <output.json> --freeze-resources patrol,camera
```

`--vectorized` 启用 `VectorizedCoverageModel`，用 NumPy 矩阵运算替代 Python 循环计算覆盖度，初始化时预构建距离矩阵切片和部署掩码，每次 `evaluate_fitness` 只做矩阵广播运算。网格数越大加速比越显著，120 格约 4x，上千格预计 10x+。

运行时每轮迭代输出格式：

```
Iter    1/100  fitness=0.351623  iter=84.5ms  avg=84.5ms
...
Optimization completed.  Best Fitness = 0.498100  Total = 8.45s  Avg/iter = 84.5ms
```

- `fitness`：当前最优适应度
- `iter`：本轮耗时
- `avg`：累计平均每轮耗时

### 输入 JSON 格式

```jsonc
{
  // * 地图配置（用于计算各格到边界/道路/水源的距离）
  "map_config": {
    "map_width": 12,
    "map_height": 10,
    "boundary_type": "RECTANGLE",
    "road_locations": [[1,0], [2,1]],   // 道路格子的 [x, y] 坐标
    "water_locations": [[0,3], [4,0]]   // 水源格子的 [x, y] 坐标
  },

  // 时间上下文（可选，默认 hour=12, season=DRY）
  "time": { "hour_of_day": 14, "season": "DRY" },

  // 是否启用昼夜/季节时间因子（可选，默认 false）
  "use_temporal_factors": false,

  // 风险模型权重（可选，所有字段均可选，缺失时使用默认值）
  "risk_model_config": {
    "risk_weights": {
      "human_weight": 0.4,          // ω₁ 人为风险权重（默认 0.4）
      "environmental_weight": 0.3,  // ω₂ 环境风险权重（默认 0.3）
      "density_weight": 0.3         // ω₃ 物种密度权重（默认 0.3）
    },
    "human_risk_weights": {
      "boundary_weight": 0.2,       // 边界邻近度权重（默认 0.2）
      "road_weight": 0.3,           // 道路邻近度权重（默认 0.3）
      "water_weight": 0.5           // 水源邻近度权重（默认 0.5）
    },
    "environmental_risk_weights": {
      "fire_weight": 0.6,           // 火灾风险权重（默认 0.6）
      "terrain_weight": 0.4         // 地形复杂度权重（默认 0.4）
    },
    "temporal_weights": {
      "daytime_factor": 1.0,        // 白天风险因子（默认 1.0）
      "nighttime_factor": 1.3,      // 夜间风险因子（默认 1.3）
      "gamma": 0.3,                 // 昼夜正弦波振幅（默认 0.3）
      "dry_season_factor": 1.0,     // 旱季风险因子（默认 1.0）
      "rainy_season_factor": 1.2    // 雨季风险因子（默认 1.2）
    }
  },

  // * 物种配置
  "species_config": {
    "rhino":    { "weight": 0.5, "rainy_season_multiplier": 1.2, "dry_season_multiplier": 1.0 },
    "elephant": { "weight": 0.3, "rainy_season_multiplier": 1.3, "dry_season_multiplier": 0.9 },
    "bird":     { "weight": 0.2, "rainy_season_multiplier": 1.5, "dry_season_multiplier": 0.8 }
  },

  // * 网格列表
  "grids": [
    {
      "grid_id": 0,
      "q": 0, "r": 0,             // * 六边形轴坐标
      "x": 0, "y": 0,             // * 笛卡尔坐标（原点左下，y 轴向上）
      "hex_size": 62,             // 格子像素半径（来自 marker）
      "terrain_type": "SparseGrass",  // * 见地形类型表
      "fire_risk": 0.3,           // * 火灾风险 [0,1]
      "terrain_complexity": 0.2,  // * 地形复杂度 [0,1]
      "vegetation_type": "GRASSLAND", // * GRASSLAND / FOREST / SHRUB
      "species_densities": { "rhino": 0.4, "elephant": 0.3, "bird": 0.5 }
    }
  ],

  // * 资源约束
  "constraints": {
    "total_patrol": 20, "total_camps": 5, "max_rangers_per_camp": 5,
    "total_cameras": 10, "total_drones": 3, "total_fence_length": 50,
    "max_cameras_per_grid": 3,   // 单格最大摄像头数（默认 3）
    "max_drones_per_grid": 1,    // 单格最大无人机数（默认 1）
    "max_camps_per_grid": 1,     // 单格最大营地数（默认 1）
    "max_rangers_per_grid": 1    // 单格最大巡逻人员数（默认 1）
  },

   // 覆盖参数（可选）
   "coverage_params": {
     "patrol_radius": 5.0, "drone_radius": 8.0, "camera_radius": 3.0,
     "fence_protection": 0.5,
     "wp": 0.3, "wd": 0.3, "wc": 0.2, "wf": 0.2,
     // 协同增强参数：值域 [0.0, 1.0]
     //   alpha_pd: Patrol + Drone 协同系数（推荐 0.3~0.5，默认 0.4）
     //   alpha_pc: Patrol + Camera 协同系数（推荐 0.1~0.2，默认 0.15）
     "alpha_pd": 0.4, "alpha_pc": 0.15
   },

  // 覆盖效果折扣系数（可选）
  // 定义不同地形对各资源覆盖效果的折扣系数（0.0~1.0），不在此配置中的地形默认系数为 1.0
  // 注意：此配置影响覆盖效果计算，与部署可行性矩阵（deployment_matrix）相互独立
  "coverage_effectiveness": {
    "DenseGrass": { "patrol": 0.3, "camp": 0.3 }
  },

  // DSSA 优化参数（可选）
  "dssa_config": {
    "population_size": 50, "max_iterations": 100,
    "producer_ratio": 0.2, "scout_ratio": 0.2, "ST": 0.8, "R2": 0.5
  }
}
```

### 部署约束体系

DSSA 优化器的资源部署受**四层约束**共同限制，按优先级从高到低依次为：

#### 第一层：部署可行性矩阵（Deployment Matrix）

基于地形类型，决定每种资源**能否**部署在某个格子上（二值 0/1）。在 `data_loader.py` 的 `initialize_deployment_matrix()` 中构建：

| `terrain_type` |    巡逻    |  营地 | 无人机 | 摄像头 |   围栏   |
| :------------- | :------: | :-: | :-: | :-: | :----: |
| SparseGrass    | ✓（见下方规则） |  ✗  |  ✓  |  ✓  | ✓（仅边缘） |
| DenseGrass     |     ✗    |  ✗  |  ✓  |  ✗  | ✓（仅边缘） |
| WaterHole      |     ✗    |  ✗  |  ✓  |  ✗  |    ✗   |
| SaltMarsh      |     ✗    |  ✗  |  ✓  |  ✗  |    ✗   |
| Road           |     ✓    |  ✓  |  ✓  |  ✓  | ✓（仅边缘） |

> 围栏额外受边缘格子限制：仅当格子位于地图边界且地形允许时，`deployment_matrix['fence'][grid_id] = 1`。

**巡逻员特殊规则**（在 DSSA 初始化时额外校验，不写入矩阵）：

- 只能部署在 **Road** 或 **无物种的 SparseGrass** 格子
- 有任意物种密度（`species_densities` 中任一值 > 0）的格子禁止部署巡逻员
- 不能部署在 WaterHole、DenseGrass、SaltMarsh

#### 第二层：单格上限（Per-Grid Cap）

在输入 JSON 的 `constraints` 中定义，控制**每个格子最多可部署多少个**同类资源：

```jsonc
"constraints": {
    "max_cameras_per_grid": 3,   // 单格最大摄像头数（默认 1）
    "max_drones_per_grid": 1,    // 单格最大无人机数（默认 1）
    "max_camps_per_grid": 1,     // 单格最大营地数（默认 1）
    "max_rangers_per_grid": 1    // 单格最大巡逻人员数（默认 1）
}
```

| 参数                     | 默认值 | 说明                     |
| :--------------------- | :-: | :--------------------- |
| `max_cameras_per_grid` |  1  | 每格最多摄像头数量（可 >1 实现密集监控） |
| `max_drones_per_grid`  |  1  | 每格最多无人机数量              |
| `max_camps_per_grid`   |  1  | 每格最多营地数量               |
| `max_rangers_per_grid` |  1  | 每格最多巡逻人员数量             |

> 营地和无人机/摄像头的单格上限通常为 1（一个格子建不了两个营地或停两架无人机），但摄像头可以设置 >1 以支持密集监控场景。

#### 第三层：全局总量（Global Budget）

所有同类资源的部署总数不得超过该资源的全局配额：

| 约束字段                 | 默认值 | 说明                      |
| :------------------- | :-: | :---------------------- |
| `total_patrol`       |  20 | 巡逻人员总数                  |
| `total_camps`        |  5  | 营地总数                    |
| `total_cameras`      |  10 | 摄像头总数                   |
| `total_drones`       |  3  | 无人机总数                   |
| `total_fence_length` |  50 | 围栏总长度（已不影响结果，围栏固定部署在边缘） |

#### 第四层：互斥规则

- **巡逻员与营地互斥**：同一格子不能同时部署 patrol 和 camp。若优化过程中两者被分配到同一格，repair 阶段会自动移除该格的巡逻员。
- **单格单资源类型**：同一格子只能部署一种资源类型（camera、drone、camp、patrol 四者互斥）。repair 阶段按优先级保留：patrol > drone > camera > camp，其余自动移除。

#### 覆盖效果折扣系数（Coverage Effectiveness）

> 与部署可行性矩阵相互独立，控制的是**覆盖效果**而非**部署权限**。

某些地形虽然允许被资源覆盖（如 DenseGrass 可以被周边 patrol 覆盖），但由于植被遮挡等原因，实际覆盖效果会打折。通过 `coverage_effectiveness` 配置可以为每种地形的每种资源指定折扣系数：

```jsonc
"coverage_effectiveness": {
  "DenseGrass": { "patrol": 0.3, "camp": 0.3 }
}
```

| 地形         | 资源     | 默认系数 | 说明                 |
| :--------- | :----- | :--: | :----------------- |
| DenseGrass | patrol |  0.3 | 密林遮挡，巡逻覆盖效果仅 30%   |
| DenseGrass | camp   |  0.3 | 密林遮挡，营地辐射覆盖效果仅 30% |
| 其他所有地形     | 所有资源   |  1.0 | 默认无折扣              |

折扣系数作用于覆盖度计算的最终结果：

```
patrol_coverage[grid_id] = effectiveness × (1 - exp(-patrol_intensity))
```

这意味着即使 DenseGrass 格子不能**部署** patrol，周边格子的 patrol 仍然可以**覆盖**到它，但效果只有 30%。

#### 约束执行时机

| 阶段       | 代码位置                                    | 执行内容                                |
| :------- | :-------------------------------------- | :---------------------------------- |
| **初始化**  | `dssa_optimizer._initialize_solution()` | 按可行性矩阵 + 单格上限 + 全局总量生成初始解           |
| **向量解码** | `dssa_optimizer._vector_to_solution()`  | 将 DSSA 连续向量截断为整数解时应用单格上限            |
| **修复**   | `coverage_model.repair_solution()`      | 迭代修复违反约束的解：先裁单格上限 → 再裁全局总量 → 清除互斥冲突 |
| **验证**   | `coverage_model.validate_solution()`    | 检查最终解是否仍有违规（用于调试）                   |

修复顺序保证：先满足**硬约束**（地形可行性、单格上限、互斥），再满足**软约束**（全局总量不足时优先保留高收益格子的部署）。

### 输出 JSON 格式

```jsonc
{
  "summary": {
    "total_grids": 120,
    "total_risk": 45.23,
    "best_fitness": 0.498,          // 风险加权归一化保护效率（优化目标）
    "total_protection_benefit": 33.2, // Σ [R_i × (1 - e^(-E_i))]
    "average_protection_benefit": 0.277, // Total / 格子数
    "fitness_history": [...],
    "resources_deployed": { "total_cameras": 10, "total_drones": 3, ... }
  },
  "grids": [
    {
      "grid_id": 0, "q": 0, "r": 0, "x": 0, "y": 0,
      "terrain_type": "SparseGrass",
      "risk_normalized": 0.35,              // riskIndex 归一化风险 [0,1]
      "protection_benefit_raw": 0.22,       // R_i × (1 - e^(-E_i))
      "protection_benefit_normalized": 0.43, // min-max 归一化 [0,1]
      "residual_risk_normalized": 0.18,     // 部署后剩余风险 R_i × e^(-E_i)，min-max 归一化
      "deployment": {
        "patrol_rangers": 0, "camp": 0, "drone": 1, "camera": 2
      },
      "hex_size": 62
    }
  ],
  "fence_edges": [
    { "grid_id_1": 0, "grid_id_2": 1 }  // 部署围栏的相邻格子对
  ]
}
```

### 关键指标说明

| 指标                              | 公式                              | 含义                   |
| :------------------------------ | :------------------------------ | :------------------- |
| `risk_normalized`               | riskIndex min-max 归一化           | 综合威胁程度，越高越需要保护       |
| `protection_benefit_raw`        | `R_i × (1 - e^(-E_i))`          | 该格实际获得的保护收益          |
| `protection_benefit_normalized` | min-max 归一化，vmin=0，vmax=max(pb) | 相对保护收益，便于可视化，0 表示无覆盖 |
| `residual_risk_normalized`      | `R_i × e^(-E_i)`，min-max 归一化    | 部署后剩余风险，越低说明保护越充分    |
| Total Protection Benefit        | `Σ protection_benefit_raw`      | 全局保护收益总量             |
| Average Protection Benefit      | `Total / N`                     | 每格平均保护收益             |
| Best Fitness                    | `Total / Σ R_i`                 | 风险加权归一化保护效率，优化目标     |

综合保护效果 `E_i = wp × patrol_cov + wd × drone_cov + wc × camera_cov + wf × fence_prot`，各覆盖度基于指数衰减函数计算。

***

## 四、一键运行脚本（推荐）

**文件**：`hexdynamic/run.py`

整合 `protection_pipeline.py` 和 `visualize_output.py`，一条命令完成优化和出图。

### 用法

```bash
cd hexdynamic

# 完整流程：优化 + 出图
python run.py input.json output.json

# 指定图片目录和文件名前缀
python run.py input.json output.json --out_dir ./figures --prefix night_rainy

# 向量化模式 + 出图
python run.py input.json output.json --vectorized --out_dir ./figures

# 只优化，不出图
python run.py input.json output.json --no-visualize

# 只出图（已有 output JSON）
python run.py output.json --visualize-only --input input.json --out_dir ./figures
```

### 命令行参数

| 参数                           | 默认值             | 说明                                                       |
| :--------------------------- | :-------------- | :------------------------------------------------------- |
| `input`                      | 必填              | 输入 JSON（pipeline 模式）或 output JSON（`--visualize-only` 模式） |
| `output`                     | 必填（pipeline 模式） | 输出 JSON 路径                                               |
| `--vectorized`               | false           | 使用向量化覆盖模型（网格数 >1000 推荐）                                  |
| `--allow-partial-deployment` | false           | 允许按边际收益决定是否部署资源                                          |
| `--freeze-resources`         | None            | 冻结资源列表，逗号分隔，如 `patrol,camera`                            |
| `--no-visualize`             | false           | 只运行优化，不生成图片                                              |
| `--visualize-only`           | false           | 只生成图片，跳过优化                                               |
| `--input, -i`                | None            | `--visualize-only` 时的原始 input JSON（用于物种数据）               |
| `--out_dir, -d`              | `./figures`     | 图片输出目录                                                   |
| `--prefix`                   | `""`            | 输出文件名前缀                                                  |

### 输出

优化结果写入 `output.json`，图片写入 `--out_dir` 目录，文件名同 `visualize_output.py`（见第七节）。

### 迭代过程输出（完整追溯）

**文件**：`hexdynamic/run_with_iteration_output.py`

在 DSSA 迭代过程中，每轮迭代生成 producer、follower、scout 的部署方案，并异步输出为 JSON 文件。适合分析迭代收敛过程或调试优化策略。

#### 用法

```bash
cd hexdynamic

# 基本用法：运行优化并输出每轮迭代结果
python run_with_iteration_output.py input.json -o results/ --iterations 50

# 向量化模式（大规模地图推荐，网格数 > 1000）
python run_with_iteration_output.py input.json -o results/ --vectorized

# 生成可视化图片
python run_with_iteration_output.py input.json -o results/ --iterations 50 --visualize

# 向量化 + 可视化（完整流程，4个并行worker）
python run_with_iteration_output.py input.json -o results/ --vectorized --visualize

# 使用8个worker并行生成可视化（加快速度）
python run_with_iteration_output.py input.json -o results/ --visualize --workers 8
```

#### 命令行参数

| 参数             | 默认值                | 说明                          |
| :------------- | :----------------- | :-------------------------- |
| `input_json`   | 必填                 | 输入 JSON 路径                  |
| `-o, --output` | `./output_results` | 输出目录                        |
| `--iterations` | 从 input.json 读取    | DSSA 迭代次数，CLI 优先            |
| `--vectorized` | 从 input.json 读取    | 使用向量化覆盖模型（>1000 格推荐），CLI 优先 |
| `--visualize`  | false              | 生成可视化图片                     |
| `--workers`    | 4                  | 可视化并行生成的工作进程数               |

> **优先级**：命令行参数 > input.json 中的 `dssa_config` > 默认值（50次迭代）

#### 输出结构

```
results/
├── final_output.json              # 最终优化结果
├── iterations/                    # 每轮迭代的部署方案（非阻塞异步写入）
│   ├── iteration_0000/
│   │   ├── producers.json         # producer 个体列表
│   │   ├── followers.json         # follower 个体列表
│   │   └── scouts.json            # scout 个体列表
│   ├── iteration_0001/
│   └── ...
├── visualization/                 # 转换后的可视化格式 JSON（postprocess 产物）
│   ├── iteration_0000/
│   │   ├── producers_000.json
│   │   └── ...
│   └── ...
└── figures/                       # 可视化图片
    ├── iteration_0000/
    │   ├── producers_000/
    │   │   ├── terrain_deployment_map.png
    │   │   ├── risk_comparison.png
    │   │   ├── protection_heatmap.png      # 归一化保护收益（全局色阶）
    │   │   └── protection_heatmap_raw.png  # 原始保护收益（全局色阶）
    │   └── ...
    └── ...
```

> 同一迭代内所有解的保护收益热力图使用**全局统一色阶**（global vmax），确保不同解之间颜色可直接对比。

#### 迭代结果后处理

**文件**：`hexdynamic/postprocess_iteration.py`

将迭代输出转换为可视化格式（单个迭代目录）：

```bash
python hexdynamic/postprocess_iteration.py <迭代目录> <原始input_json> [-o 输出目录]

# 示例
python hexdynamic/postprocess_iteration.py ./results/iterations/iteration_0005 input.json -o ./viz/
```

#### 批量迭代可视化（推荐）

**文件**：`hexdynamic/visualize_iterations.py`

对已有的迭代输出目录一键完成后处理 + 可视化，无需重新运行优化。

```bash
cd hexdynamic

# 基本用法
python visualize_iterations.py ./output_results/iterations --input sensitivity/base.json

# 指定 final_output.json 以获取准确风险数据（推荐）
python visualize_iterations.py ./output_results/iterations \
    --input sensitivity/base.json \
    --final-output ./output_results/final_output.json \
    --out-dir ./output_results/figures \
    --workers 8

# 跳过后处理步骤（viz JSON 已存在时）
python visualize_iterations.py ./output_results/iterations \
    --input sensitivity/base.json \
    --skip-postprocess

# 只处理特定迭代
python visualize_iterations.py ./output_results/iterations \
    --input sensitivity/base.json \
    --iterations iteration_0000 iteration_0099
```

| 参数                   | 默认值                      | 说明                                    |
| :------------------- | :----------------------- | :------------------------------------ |
| `iterations_dir`     | 必填                       | 迭代输出目录（如 `output_results/iterations`） |
| `--input, -i`        | 必填                       | 原始输入 JSON                             |
| `--final-output, -f` | None                     | `final_output.json` 路径，用于准确的风险数据      |
| `--viz-dir`          | `<parent>/visualization` | 后处理 JSON 输出目录                         |
| `--out-dir, -o`      | `<parent>/figures`       | 图片输出目录                                |
| `--workers, -w`      | 4                        | 并行工作进程数                               |
| `--skip-postprocess` | false                    | 跳过后处理，直接使用已有 viz JSON                 |
| `--iterations`       | 全部                       | 只处理指定迭代，空格分隔                          |

#### DSSAConfig 迭代输出参数

在输入 JSON 的 `dssa_config` 中配置迭代输出目录：

```json
"dssa_config": {
  "population_size": 50,
  "max_iterations": 100,
  "producer_ratio": 0.2,
  "scout_ratio": 0.2,
  "ST": 0.8,
  "output_dir": "./output_iterations"
}
```

当 `output_dir` 设置后，DSSA 优化器会在每轮迭代结束后异步写入 JSON 文件，不阻塞主迭代流程。

### 批量 Pipeline（多场景优化+可视化）

**文件**：`hexdynamic/batch_pipeline.py`

对目录中多个 input JSON 依次执行完整的 protection\_pipeline（DSSA 优化）+ visualize\_output（出图），适用于多时段/多场景批量分析。

#### 用法

```bash
cd hexdynamic

# 基本用法：扫描目录中所有 .json，逐个跑优化 + 可视化
python batch_pipeline.py --input-dir ./scenarios --output-dir ./results

# 指定文件匹配模式
python batch_pipeline.py --input-dir ./scenarios --output-dir ./results --pattern "night_*.json"

# 向量化 + 冻结部分资源
python batch_pipeline.py --input-dir ./scenarios --output-dir ./results --vectorized --freeze-resources patrol,camera

# 只跑优化，不出图
python batch_pipeline.py --input-dir ./scenarios --output-dir ./results --no-visualize
```

#### 命令行参数

| 参数                           | 默认值               | 说明                   |
| :--------------------------- | :---------------- | :------------------- |
| `--input-dir, -i`            | 必填                | 输入 JSON 所在目录         |
| `--output-dir, -o`           | `./batch_results` | 输出根目录                |
| `--pattern, -p`              | `*.json`          | 文件匹配模式               |
| `--vectorized`               | false             | 使用向量化覆盖模型（>1000 格推荐） |
| `--allow-partial-deployment` | false             | 允许按边际收益决定是否部署资源      |
| `--freeze-resources`         | None              | 冻结资源列表，逗号分隔          |
| `--no-visualize`             | false             | 跳过可视化，仅运行优化          |

#### 输出结构

```
results/
├── scenario_1/
│   ├── output.json              # protection_pipeline 优化结果
│   ├── risk_heatmap.png
│   ├── risk_comparison.png
│   ├── protection_heatmap.png
│   ├── terrain_map.png
│   ├── terrain_deployment_map.png
│   └── species_map.png
├── scenario_2/
│   └── ...
└── batch_summary.json           # 所有场景汇总（fitness/PB 统计）
```

### 最小资源量查找（二分搜索）

**文件**：`find_deployment.py`

通过二分查找自动调整某种资源的总量约束，找到**恰好满足目标保护水平**（`best_fitness` 或 `total_protection_benefit`）的**最小资源部署方案**。适用于回答"至少需要多少个摄像头才能让 fitness 达到 0.3？"这类问题。

#### 用法

```bash
# 找到使 best_fitness >= 0.3 所需的最少 camera 数量
python find_deployment.py --input input.json --resource camera --target-fitness 0.3

# 找到使 total_protection_benefit >= 50 所需的最少 patrol 数量
python find_deployment.py --input input.json --resource patrol --target-benefit 50

# 指定搜索范围和精度
python find_deployment.py --input input.json --resource drone --target-fitness 0.25 \
    --min 0 --max 500 --tolerance 2 --vectorized

# 冻结其他资源（只调整 camera，patrol/drone/camp 固定不变）
python find_deployment.py --input input.json --resource camera --target-fitness 0.3 \
    --freeze patrol,drone,camp
```

#### 命令行参数

| 参数                 | 默认值                     | 说明                                                      |
| :----------------- | :---------------------- | :------------------------------------------------------ |
| `--input, -i`      | 必填                      | 基础输入 JSON 路径                                            |
| `--resource, -r`   | 必填                      | 要调整的资源：`patrol` / `camera` / `drone` / `camp` / `fence` |
| `--target-fitness` | —（二选一）                  | 目标 best\_fitness 阈值（如 0.3）                              |
| `--target-benefit` | —（二选一）                  | 目标 total\_protection\_benefit 阈值（如 50.0）                |
| `--min`            | 0                       | 搜索下界（资源数量）                                              |
| `--max`            | 1000                    | 搜索上界（资源数量）                                              |
| `--tolerance`      | 5                       | 收敛精度：`hi - lo <= tolerance` 时停止                         |
| `--output, -o`     | 自动命名                    | 最终部署方案输出 JSON 路径                                        |
| `--work-dir`       | `./find_deployment_tmp` | 中间文件目录                                                  |
| `--out-dir`        | 与 work-dir 相同           | 图表输出目录                                                  |
| `--vectorized`     | false                   | 使用向量化模式（大规模地图推荐）                                        |
| `--freeze`         | None                    | 冻结其他资源，逗号分隔，如 `patrol,drone,camp`                       |

> `--target-fitness` 和 `--target-benefit` **二选一必填**，分别对应两种优化目标。

#### 算法流程

```
1. 验证上界 (--max) 是否可达目标
   │  若不可达 → 提示增大 --max，终止
   ▼
2. 二分搜索 [lo, hi]
   │  每轮 mid = (lo + hi) // 2
   │  调用 protection_pipeline 计算 metric
   │  ├─ metric >= target → 缩小上界 hi = mid（记录为候选解）
   │  └─ metric < target  → 提高下界 lo = mid
   ▼
3. 收敛条件: hi - lo <= tolerance
   │  输出最后一次满足目标的最小 resource_value
   ▼
4. 输出收敛趋势图 + 迭代历史表格
```

#### 输出

| 文件/内容                                     | 说明                              |
| :---------------------------------------- | :------------------------------ |
| `find_deployment_{resource}_{value}.json` | 最终最小资源量的完整部署方案（output.json 格式）  |
| `convergence_total_benefit.png`           | Total Protection Benefit 收敛曲线   |
| `convergence_avg_benefit.png`             | Average Protection Benefit 收敛曲线 |
| `convergence_best_fitness.png`            | Best Fitness 收敛曲线               |
| `convergence_combined.png`                | 合并图：3 条曲线 + 迭代历史表格（绿色行=满足目标）    |

中间文件保存在 `--work-dir` 目录中（每次迭代的 input/output JSON），可用于调试或复现。

***

## 五、风险分析脚本

**文件**：`hexdynamic/risk_analysis.py`

仅计算综合风险指数，生成风险热力图和地理属性+物种属性地图，不涉及 DSSA 优化。

### 用法

```bash
cd hexdynamic

# 基本用法（hex_size 自动从 input JSON 中提取）
python risk_analysis.py <input.json> <output_dir>

# 指定六边形大小（覆盖 input JSON 中的值）
python risk_analysis.py <input.json> <output_dir> --hex-size 1.0
```

`hex_size` 优先级：命令行参数 > input JSON 中的 `grids[0].hex_size` > 默认值 1.0

### 输入

同 `protection_pipeline.py` 的输入 JSON 格式（见第三节）。

### 输出

输出到指定目录的四个文件：

| 文件                      | 内容                   | 说明                          |
| :---------------------- | :------------------- | :-------------------------- |
| `risk_heatmap.png`      | 归一化风险指数热力图           | YlOrRd 色阶，\[0,1] 范围，便于跨时段对比 |
| `geo_attr_map.png`      | 地理属性地图（到边界/道路/水源的距离） | 三通道 RGB 分别表示三种接近度           |
| `species_attr_map.png`  | 物种属性地图（各物种密度分布）      | 图标大小正比于密度，形状区分物种            |
| `combined_attr_map.png` | 综合属性图（地理+物种叠加）       | 合并展示所有输入属性                  |

### 批量风险分析（多场景对比）

**文件**：`hexdynamic/risk_analysis_batch.py`

对目录中多个 input JSON 依次执行风险分析，生成每个场景的独立可视化 + 多场景对比热力图（含 raw risk 数值标注）。

#### 用法

```bash
cd hexdynamic

# 基本用法（扫描目录中所有 .json）
python risk_analysis_batch.py --input-dir ./scenarios --output-dir ./results

# 指定文件匹配模式
python risk_analysis_batch.py --input-dir ./scenarios --output-dir ./results --pattern "day_*.json"
```

#### 命令行参数

| 参数                 | 默认值                       | 说明           |
| :----------------- | :------------------------ | :----------- |
| `--input-dir, -i`  | 必填                        | 输入 JSON 所在目录 |
| `--output-dir, -o` | `./risk_analysis_results` | 输出根目录        |
| `--pattern, -p`    | `*.json`                  | 文件匹配模式       |
| `--hex-size`       | 自动检测                      | 六边形大小        |

#### 输出结构

```
results/
├── scenario_1/
│   ├── risk_heatmap.png
│   ├── raw_risk_heatmap.png
│   ├── attributes_map.png
│   └── risk_results.json
├── scenario_2/
│   └── ...
├── risk_heatmap_comparison.png      # 2×2 归一化风险对比（含数值标注）
├── raw_risk_heatmap_comparison.png  # 2×2 原始风险对比（含数值标注）
└── summary_report.json              # 所有场景统计汇总
```

对比热力图采用 2×2 布局（最多 4 个场景），每个六边形格子中心标注 **raw risk 数值**，颜色深浅（YlOrRd 色阶）表示归一化/原始风险高低，左下角显示该场景的 min/max/mean 统计。

***

## 六、风险模型说明（riskIndex）

pipeline 脚本调用 `riskIndex` 模块计算每个网格的归一化综合风险值 `R_i ∈ [0, 1]`，作为 DSSA 优化的输入。

### 综合风险公式

```
R'_i = (ω₁·H_i + ω₂·E_i + ω₃·D_i) × T_t × S_t

R_i = (R'_i - R_min) / (R_max - R_min)
```

|  符号  | 含义             |   默认权重   |
| :--: | :------------- | :------: |
| H\_i | 人为风险（盗猎/人兽冲突）  | ω₁ = 0.4 |
| E\_i | 环境风险（火灾 + 地形）  | ω₂ = 0.3 |
| D\_i | 物种密度风险（珍稀物种分布） | ω₃ = 0.3 |
| T\_t | 昼夜因子（可选）       |     —    |
| S\_t | 季节因子（可选）       |     —    |

### 人为风险 H\_i（盗猎风险 + 人兽冲突）

反映人类活动对保护区的威胁，综合考虑三个距离因素：

```
H_i = (α₁·prox_boundary + α₂·prox_road + α₃·prox_water) × P_t
```

| 因素              | 含义                  |    默认权重   |
| :-------------- | :------------------ | :-------: |
| `prox_boundary` | 到保护区边界的接近度（越近越高）    | α₁ = 0.2  |
| `prox_road`     | 到道路的接近度（道路是盗猎者进入通道） | α₂ = 0.3  |
| `prox_water`    | 到水源的接近度（水源是人兽冲突热点）  | α₃ = 0.5  |
| `P_t`           | 盗猎时间概率（由昼夜因子决定）     |     —     |

接近度 = `1 - 归一化距离`，即距离越近，接近度越高，风险越大。

在输入 JSON 中，`road_locations` 和 `water_locations` 用于自动计算各格到道路/水源的距离。

### 环境风险 E\_i（火灾风险 + 地形复杂度）

```
E_i = β₁·fire_risk + β₂·terrain_complexity
```

| 字段                   | 含义                       |   默认权重   |
| :------------------- | :----------------------- | :------: |
| `fire_risk`          | 火灾风险 \[0,1]，由植被类型和干燥程度决定 | β₁ = 0.6 |
| `terrain_complexity` | 地形复杂度 \[0,1]，复杂地形增加巡逻难度  | β₂ = 0.4 |

这两个值在每个网格的输入数据中直接提供（`generate_map.py` 按地形类型随机生成，marker 工具按颜色给出默认值）。

### 物种密度风险 D\_i（珍稀物种分布）

反映该格子的保护价值，物种越密集、保护权重越高，风险值越高：

```
D_i = Σ_s (w_s × density_{s,i} × seasonal_multiplier_s)
```

| 参数                      | 含义                                        |
| :---------------------- | :---------------------------------------- |
| `w_s`                   | 物种保护权重（rhino=0.5, elephant=0.3, bird=0.2） |
| `density_{s,i}`         | 物种 s 在格子 i 的密度 \[0,1]                     |
| `seasonal_multiplier_s` | 季节密度系数（雨季/旱季不同）                           |

### 时间因子（可选，`use_temporal_factors: true` 时启用）

| 因子        | 计算方式                         |  默认值 |
| :-------- | :--------------------------- | :--: |
| 昼夜因子 T\_t | 白天（6:00-18:00）= 1.0，夜间 = 1.3 | 离散模式 |
| 季节因子 S\_t | 旱季 = 1.0，雨季 = 1.2            |   —  |

时间因子作为乘数叠加在基础风险上，夜间雨季的综合风险最高（×1.56）。默认关闭，适合需要分析特定时段风险的场景。

### 权重参数配置

所有权重参数统一在输入 JSON 的 `risk_model_config` 和 `species_config` 中定义，所有字段均可选，缺失时使用代码默认值。可通过 `generate_map.py` 命令行参数、Marker 工具导出面板、或直接编辑 JSON 来配置。

#### 综合风险权重 (`risk_weights`)

控制三大风险分量的相对重要性，三者之和应为 1。

| 参数                     | 含义            | 默认值  | CLI 参数                |
| :--------------------- | :------------ | :--: | :-------------------- |
| `human_weight`         | 人为风险权重 ω₁    | 0.4  | `--human_weight`      |
| `environmental_weight` | 环境风险权重 ω₂    | 0.3  | `--environmental_weight` |
| `density_weight`       | 物种密度权重 ω₃    | 0.3  | `--density_weight`    |

代码位置：`riskIndex/src/risk_model/config/defaults.py`

#### 人为风险权重 (`human_risk_weights`)

控制人为风险内部三个邻近度因子的相对重要性，三者之和应为 1。

| 参数                | 含义      | 默认值  | CLI 参数             |
| :---------------- | :------ | :--: | :----------------- |
| `boundary_weight` | 边界邻近度权重 | 0.2  | `--boundary_weight` |
| `road_weight`     | 道路邻近度权重 | 0.3  | `--road_weight`    |
| `water_weight`    | 水源邻近度权重 | 0.5  | `--water_weight`   |

代码位置：`riskIndex/src/risk_model/risk/human.py`

#### 环境风险权重 (`environmental_risk_weights`)

控制环境风险内部两个因子的相对重要性，两者之和应为 1。

| 参数               | 含义      | 默认值  | CLI 参数            |
| :--------------- | :------ | :--: | :---------------- |
| `fire_weight`    | 火灾风险权重 | 0.6  | `--fire_weight`   |
| `terrain_weight` | 地形复杂度权重 | 0.4  | `--terrain_weight` |

代码位置：`riskIndex/src/risk_model/risk/environmental.py`

#### 时间因子权重 (`temporal_weights`)

控制昼夜和季节对风险的调节幅度。

| 参数                   | 含义         | 默认值  | CLI 参数                 |
| :------------------- | :--------- | :--: | :--------------------- |
| `daytime_factor`     | 白天风险因子    | 1.0  | `--daytime_factor`     |
| `nighttime_factor`   | 夜间风险因子    | 1.3  | `--nighttime_factor`   |
| `gamma`              | 连续模式正弦波振幅 | 0.3  | `--gamma`              |
| `dry_season_factor`  | 旱季风险因子    | 1.0  | `--dry_season_factor`  |
| `rainy_season_factor`| 雨季风险因子    | 1.2  | `--rainy_season_factor`|

代码位置：`riskIndex/src/risk_model/risk/temporal.py`

#### 物种配置 (`species_config`)

每个物种独立配置，key 为物种名称。

| 参数                        | 含义     |
| :------------------------ | :----- |
| `weight`                  | 物种保护权重 |
| `rainy_season_multiplier` | 雨季密度乘数 |
| `dry_season_multiplier`   | 旱季密度乘数 |

默认物种配置：

| 物种      | weight | rainy\_season\_multiplier | dry\_season\_multiplier |
| :------ | :----: | :-----------------------: | :---------------------: |
| rhino   |  0.5   |           1.2            |           1.0           |
| elephant|  0.3   |           1.3            |           0.9           |
| bird    |  0.2   |           1.5            |           0.8           |

代码位置：`riskIndex/src/risk_model/risk/density.py`

#### JSON 配置示例

以下为包含所有权重参数的完整 `risk_model_config` + `species_config` 配置（值均为默认值）：

```json
{
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
    "rhino":    { "weight": 0.5, "rainy_season_multiplier": 1.2, "dry_season_multiplier": 1.0 },
    "elephant": { "weight": 0.3, "rainy_season_multiplier": 1.3, "dry_season_multiplier": 0.9 },
    "bird":     { "weight": 0.2, "rainy_season_multiplier": 1.5, "dry_season_multiplier": 0.8 }
  }
}
```

#### 时间因子与归一化的交互

启用时间因子后，原始风险值会按时间因子放大（例如夜间约 1.3 倍），但**归一化后的风险统计指标（min/max/mean）会相同**。这是因为：

1. 原始风险计算：`R'_i = (ω₁·H_i + ω₂·E_i + ω₃·D_i) × T_t × S_t`
2. 归一化处理：`R_i = (R'_i - R_min) / (R_max - R_min)`

所有原始风险都乘以相同的时间因子，因此 min/max 也同时放大，归一化后仍映射到 \[0, 1] 范围。结果是：

- **原始风险**：夜间 ≈ 1.3 × 白天
- **归一化风险**：夜间与白天的 min/max/mean 统计值相同（都是 \[0, 1] 范围）

这是**预期行为**，用于确保不同时段的风险分布形状一致，便于跨时段对比。若需要保留时间因子的绝对差异，应在输出后对原始风险值进行分析。

### 时间感知优化策略

当启用时间因子后，可使用以下策略进行优化：

#### 方案 A：标准模式（默认）

- 不启用时间感知
- DSSA 按静态风险分配资源
- 适用于通用场景

#### 方案 B：时间感知模式

- 启用 `use_time_aware_fitness: true`
- DSSA 自动调整资源分配
- 夜间部署更多资源

#### 方案 C：分时段优化（推荐用于多时段规划）

1. **分别生成不同时段的输入**：
   ```bash
   # 白天输入
   python generate_map.py -m 15 -n 15 --hour_of_day 12 --season DRY --use_temporal_factors -o input_day.json

   # 夜间输入
   python generate_map.py -m 15 -n 15 --hour_of_day 2 --season DRY --use_temporal_factors -o input_night.json
   ```
2. **分别运行优化**：
   ```bash
   python run.py input_day.json output_day.json --vectorized
   python run.py input_night.json output_night.json --vectorized
   ```
3. **对比分析**：比较两个时段的部署方案差异
4. **融合方案**：根据实际需求选择或融合两套方案

#### 典型工作流建议

1. **单时段分析**：使用方案 A（标准模式），快速得到基础部署方案
2. **重点时段强化**：使用方案 B（时间感知模式）
   - 启用 `use_time_aware_fitness: true`
   - DSSA 自动调整资源分配
   - 夜间部署更多资源
3. **多时段规划**：使用方案 C（分时段优化）
   - 为 day 和 night 分别运行 DSSA
   - 输出两套部署方案
   - 根据实际需求选择或融合
4. **资源调度**：根据季节和昼夜周期动态调整部署方案
   - 白天：按标准模式部署
   - 夜间：启用时间感知模式，增加资源
   - 雨季：增加时间因子权重

***

## 七、可视化脚本

**文件**：`hexdynamic/visualize_output.py`

> 推荐通过 `run.py` 调用（自动在优化后出图）。直接使用 `visualize_output.py` 适合已有 output JSON、只需重新生成图片的场景。

### 用法

```bash
# 基本用法（无物种图）
python visualize_output.py output.json --out_dir ./figures

# 完整用法（同时提供 input，生成物种密度图）
python visualize_output.py output.json --input pipeline_input.json --out_dir ./figures

# 加前缀区分多次运行
python visualize_output.py output.json --input pipeline_input.json --out_dir ./figures --prefix run1
```

### 输出图片

| 文件                           | 内容                                                 |   颜色条  |
| :--------------------------- | :------------------------------------------------- | :----: |
| `risk_heatmap.png`           | 部署前风险热力图，右侧显示 Total PB / Average PB / Best Fitness | YlOrRd |
| `risk_comparison.png`        | 部署前后风险对比（左：原始风险，右：剩余风险），同色阶便于直接对比                  | YlOrRd |
| `protection_heatmap.png`     | 保护收益热力图（归一化），叠加摄像头/无人机/营地/巡逻员/围栏图标                 | Greens |
| `protection_heatmap_raw.png` | 保护收益热力图（原始值），与归一化版使用相同布局，便于跨方案绝对值对比                | Greens |
| `terrain_map.png`            | 地形颜色地图                                             |    —   |
| `terrain_deployment_map.png` | 地形底图 + 部署资源图标叠加                                    |    —   |
| `species_map.png`            | 地形底图 + 物种密度图标（大小正比于密度，形状区分物种）                      |    —   |

有颜色条的图采用三列布局：**地图 | 颜色条 | 图例+指标**，三者互不遮挡。`risk_comparison.png` 采用双图并排布局，左右共用同一颜色条，颜色越深（红色）表示风险越高，对比左右可直观看出哪些高风险区域被有效覆盖。

### 资源图标说明

|   图标  |  颜色 | 资源                |
| :---: | :-: | :---------------- |
|  ■ 方形 |  蓝色 | Camera（摄像头）       |
|  ▲ 三角 |  橙色 | Drone（无人机）        |
|  ◆ 菱形 |  紫色 | Camp（营地）          |
|  ● 圆形 |  绿色 | Patrol（巡逻员）       |
| ⬠ 五边形 |  红色 | Fence（围栏，仅显示在边缘格） |

***

## 八、图片转视频工具

**文件**：`hexdynamic/images_to_video.py`

将指定目录中具有相同前缀的图片序列生成视频，适合展示优化迭代过程的动态效果。

### 用法

```bash
cd hexdynamic

# 基础用法：从目录中查找 deployment_map 开头的图片生成视频
python images_to_video.py --input_dir ./figures --prefix deployment_map --output video.mp4

# 指定帧率（默认 10 fps）
python images_to_video.py --input_dir ./figures --prefix deployment_map --output video.mp4 --fps 8

# 缩放图片尺寸（减小视频体积）
python images_to_video.py --input_dir ./figures --prefix deployment_map --output video.mp4 --resize 0.5

# 无确认模式（适合脚本调用）
python images_to_video.py --input_dir ./figures --prefix deployment_map --output video.mp4 --no_confirm

# 指定后端（可选）
python images_to_video.py --input_dir ./figures --prefix deployment_map --output video.mp4 --backend cv2
```

### 命令行参数

| 参数                 | 默认值                 | 说明                           |
| :----------------- | :------------------ | :--------------------------- |
| `--input_dir, -i`  | 必填                  | 图片所在目录                       |
| `--prefix, -p`     | 必填                  | 图片文件名前缀（如 `deployment_map`）  |
| `--output, -o`     | `output.mp4`        | 输出视频文件路径                     |
| `--fps, -f`        | `10.0`              | 视频帧率                         |
| `--resize, -r`     | `1.0`               | 图片缩放因子（1.0=不缩放）              |
| `--extensions, -e` | `.png, .jpg, .jpeg` | 图片文件扩展名，空格分隔                 |
| `--no_confirm, -y` | `false`             | 跳过确认提示                       |
| `--backend, -b`    | 自动选择                | 指定后端：`cv2`（OpenCV）或 `ffmpeg` |

### 后端说明

**支持两种后端**：

1. \*\*OpenCV (`--backend cv2`)：
   - 依赖：\`pip install opencv-python
   - 优点：纯 Python 实现，无需额外安装软件
   - 适合快速生成视频
2. \*\*FFmpeg (`--backend ffmpeg`)：
   - 依赖：需安装 FFmpeg 软件并添加到 PATH
   - 优点：视频质量更好，压缩率更高
   - 适合生成高质量视频

**自动选择规则**：

- 优先使用 OpenCV（如果已安装）
- 否则尝试使用 FFmpeg
- 两者都不可用时提示错误

### 图片查找逻辑

1. **直接查找**：在 `--input_dir` 中查找符合前缀的图片
2. **子目录查找**：如果没找到时，在 `--input_dir` 的子目录中查找（如 `iteration_0000/deployment_map.png`）
3. **自然排序**：按文件名中的数字顺序排序，确保迭代顺序正确

### 示例

```bash
# 完整示例：从迭代输出目录生成部署演化视频
python images_to_video.py --input_dir ./figures --prefix deployment_map --output deployment_evolution.mp4 --fps 8 --no_confirm
```

***

## 九、敏感性分析

本节包含三个敏感性分析工具：

| 工具 | 功能 | 适用场景 |
| :--- | :--- | :--- |
| **sensitivity\_analysis.py** | 单资源单因素敏感性分析 | 分析一种资源的影响，自定义范围 |
| **sensitivity\_batch.py** | 多资源并行敏感性分析 + 自动报告 | 一次性分析所有资源，并行加速 |
| **sensitivity\_report.py** | 可视化报告生成 | 从已有 JSON 数据生成优化报告 |

***

### 9.1 敏感性分析脚本

**文件**：`sensitivity_analysis.py`

分析每种资源数量对保护效果的影响，找出边际收益递减点，辅助资源配置决策。支持三种执行模式：纯并行、串行热启动、分组混合热启动。

#### 用法

```bash
# 分析单种资源（纯并行模式）
python sensitivity_analysis.py --input base_input.json --resource camera --range 0 400 10

# 分析所有资源（使用默认范围）
python sensitivity_analysis.py --input base_input.json --resource all

# 向量化模式（大规模地图推荐）
python sensitivity_analysis.py --input base_input.json --resource patrol --vectorized

# 两步法：粗扫后自动细扫饱和区
python sensitivity_analysis.py --input base_input.json --resource camera --range 0 400 50 --two-step

# 串行热启动：低资源点结果作为高资源点初始解
python sensitivity_analysis.py --input base_input.json --resource camera --range 0 400 10 --warm-start

# 分组混合热启动：4组并行，组内串行热启动（推荐）
python sensitivity_analysis.py --input base_input.json --resource camera --range 0 400 10 --warm-start --warm-start-groups 4
```

#### 命令行参数

| 参数                     | 默认值                     | 说明                                                            |
| :--------------------- | :---------------------- | :------------------------------------------------------------ |
| `--input, -i`          | 必填                      | 基础输入 JSON 路径                                                  |
| `--resource, -r`       | `patrol`                | 资源类型：`patrol` / `camera` / `drone` / `camp` / `fence` / `all` |
| `--range MIN MAX STEP` | 各资源默认范围                 | 资源数量范围，如 `--range 0 400 10`                                   |
| `--output, -o`         | `./sensitivity_results` | 输出目录                                                          |
| `--vectorized`         | false                   | 使用向量化模式                                                       |
| `--workers, -w`        | 系统CPU核数                 | 纯并行模式的工作进程数                                                   |
| `--two-step`           | false                   | 启用两步法：粗扫全范围后自动定位饱和区细扫                                         |
| `--fine-step-ratio`    | 5                       | 两步法细扫步长 = 粗步长 / 此值                                            |
| `--warm-start`         | false                   | 启用热启动：按资源值递增顺序串行执行，低资源点结果作为高资源点初始解                            |
| `--warm-start-groups`  | 1                       | 分组混合模式的并行组数（需配合 `--warm-start`）。默认1（纯串行），设为>1时启用分组并行，推荐设为workers数 |
| `--no-cache`           | false                   | 禁用缓存（默认启用缓存避免重复计算）                                            |

各资源默认范围：

| 资源     | 默认范围     |  步长 |
| :----- | :------- | :-: |
| patrol | 0 \~ 50  |  5  |
| camera | 0 \~ 20  |  2  |
| drone  | 0 \~ 10  |  1  |
| camp   | 0 \~ 5   |  1  |
| fence  | 0 \~ 100 |  10 |

> `--resource all` 时，每种资源使用各自的默认范围。若同时指定 `--range`，则所有资源共用该范围。

#### 输出

每种资源生成两个文件：

| 文件                                | 说明                                                                           |
| :-------------------------------- | :--------------------------------------------------------------------------- |
| `sensitivity_{resource}.json`     | 原始数据，包含每个资源值对应的 total\_protection\_benefit、best\_fitness、resources\_deployed |
| `sensitivity_{resource}_plot.png` | 原始曲线图（3 曲线 + 数据表格）                                                           |

#### 输出 JSON 格式

```jsonc
{
  "resource_type": "camera",
  "resource_values": [0, 10, 20, ...],
  "results": [
    {
      "resource_value": 0,
      "total_protection_benefit": 4.087532,
      "best_fitness": 0.018217,
      "resources_deployed": {
        "total_cameras": 0,
        "total_drones": 0,
        "total_camps": 0,
        "total_rangers": 0,
        "fence_segments": 106
      },
      "output_json": "./sensitivity_results/temp_output_camera_0.json"
    }
  ]
}
```

***

### 9.2 多资源并行敏感性分析脚本

**文件**：`sensitivity_batch.py`

并行运行多种资源的单因素敏感性分析，最后自动调用 `sensitivity_report.py` 生成可视化报告。每种资源可设置不同的分析范围。所有输出文件统一存放在 `--report-dir` 目录下，启动前自动清理缓存和临时文件。

#### 用法

```bash
# 使用默认范围分析所有资源（5种），4进程并行
python sensitivity_batch.py --input base.json --workers 4

# 指定部分资源及自定义范围
python sensitivity_batch.py --input base.json \
    --ranges patrol:0:50:5 camera:0:400:10 drone:0:10:1

# 向量化模式
python sensitivity_batch.py --input base.json --workers 4 --vectorized

# 两步法 + 向量化
python sensitivity_batch.py --input base.json --ranges camera:0:400:50 --two-step --workers 4

# 分组混合热启动：4组并行，组内串行热启动
python sensitivity_batch.py --input base.json --warm-start --warm-start-groups 4 --vectorized

# 跳过报告生成
python sensitivity_batch.py --input base.json --no-report

# 指定顶层输出目录
python sensitivity_batch.py --input base.json --report-dir ./my_results
```

#### 命令行参数

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `--input, -i` | 必填 | 基础输入 JSON 路径 |
| `--ranges` | 所有资源默认范围 | 资源范围定义，格式 `resource:min:max:step`，可指定多个 |
| `--output, -o` | `--report-dir` 下的 `sensitivity_results/` | 敏感性分析中间结果目录 |
| `--report-dir` | `./figures/single_sensitivity` | 顶层输出目录，所有文件统一存放于此 |
| `--workers, -w` | 系统CPU核数 | 资源内并行工作进程数 |
| `--vectorized` | false | 使用向量化模式 |
| `--two-step` | false | 启用两步法：粗扫全范围后自动定位饱和区细扫 |
| `--fine-step-ratio` | 5 | 两步法细扫步长 = 粗步长 / 此值 |
| `--no-report` | false | 跳过报告生成 |
| `--warm-start` | false | 启用热启动：按资源值递增顺序串行执行，低资源点结果作为高资源点初始解 |
| `--warm-start-groups` | 1 | 分组混合模式的并行组数（需配合 `--warm-start`）。默认1（纯串行），设为>1时启用分组并行，推荐设为workers数 |
| `--no-cache` | false | 禁用缓存（默认启用缓存避免重复计算） |

#### `--ranges` 格式

```
resource:min:max:step
```

| 示例 | 含义 |
| :--- | :--- |
| `patrol:0:50:5` | patrol 从 0 到 50，步长 5 |
| `camera:0:400:10` | camera 从 0 到 400，步长 10 |
| `drone:0:10:1` | drone 从 0 到 10，步长 1 |

> 未在 `--ranges` 中指定的资源使用默认范围。只指定部分资源时，其余资源仍会使用默认范围分析。

#### 输出

所有文件统一存放在 `--report-dir` 目录下：

```
figures/single_sensitivity/          # --report-dir（默认）
├── sensitivity_results/             # 中间结果（sensitivity_analysis.py 的输出）
│   ├── sensitivity_patrol.json      # 各资源的敏感性数据
│   ├── sensitivity_camera.json
│   ├── sensitivity_drone.json
│   ├── sensitivity_camp.json
│   ├── sensitivity_fence.json
│   ├── sensitivity_{resource}_plot.png  # 各资源的原始曲线图
│   ├── temp_input_*.json            # 临时输入文件（运行后自动清理）
│   ├── temp_output_*.json           # 临时输出文件（运行后自动清理）
│   └── .cache/                      # 结果缓存（启动前自动清理）
├── batch_config.json                # 批量分析配置和运行结果
├── report_patrol.png                # 优化后的可视化报告
├── report_camera.png
├── report_drone.png
├── report_camp.png
└── report_fence.png
```

`batch_config.json` 记录了本次批量分析的配置、各资源的运行状态和耗时。

> **启动前自动清理**：每次运行时自动清理缓存目录（`.cache/`）和临时文件（`temp_input_*.json`、`temp_output_*.json`），确保从干净状态启动。

#### 与单资源脚本的对比

| 对比维度 | `sensitivity_analysis.py` | `sensitivity_batch.py` |
| :--- | :--- | :--- |
| 分析资源数 | 单种或全部（顺序执行） | 全部（并行执行） |
| 自定义范围 | 所有资源共用一个 `--range` | 每种资源可设不同 `--ranges` |
| 并行支持 | `--workers` 多进程并行 | `--workers` 资源内并行 |
| 热启动 | `--warm-start` + `--warm-start-groups` | 同左，参数透传 |
| 两步法 | `--two-step` | 同左，参数透传 |
| 缓存 | `--no-cache` 禁用 | 同左，启动前自动清理 |
| 自动报告 | 需手动调用 `sensitivity_report.py` | 自动调用 |
| 输出目录 | `--output` 单一目录 | `--report-dir` 顶层 + `sensitivity_results/` 子目录 |
| 适用场景 | 单资源精细分析 | 多资源一次性分析 |

***

### 9.3 敏感性分析报告脚本

**文件**：`sensitivity_report.py`

读取 `sensitivity_analysis.py` 或 `sensitivity_batch.py` 生成的 JSON 数据，生成优化后的可视化报告。相比原始曲线图，报告新增了饱和点标注、累计收益增幅图和优化后的数据表格。

#### 用法

```bash
# 单个资源报告
python sensitivity_report.py sensitivity_results/sensitivity_camera.json

# 批量生成目录下所有资源的报告
python sensitivity_report.py sensitivity_results/ --all

# 指定输出目录
python sensitivity_report.py sensitivity_results/ --all --out_dir ./reports
```

#### 命令行参数

| 参数              | 默认值      | 说明                                    |
| :-------------- | :------- | :------------------------------------ |
| `input`         | 必填       | sensitivity JSON 文件路径，或目录（配合 `--all`） |
| `--all`         | false    | 处理目录下所有 `sensitivity_*.json` 文件       |
| `--out_dir, -d` | 与输入文件同目录 | 图片输出目录                                |

#### 输出

每种资源生成一个报告图 `report_{resource}.png`，包含 4 个子图和 1 个数据表格：

| 子图 | 内容                    | 说明                    |
| :- | :-------------------- | :-------------------- |
| 左上 | Protection Benefit 曲线 | 总保护收益随资源数量的变化         |
| 右上 | Best Fitness 曲线       | 最佳适应度随资源数量的变化         |
| 左下 | Marginal Benefit 柱状图  | 每增加一单位资源的边际收益         |
| 右下 | Cumulative Gain 曲线    | 相对于零资源基准的累计收益增幅（%）    |
| 底部 | 数据表格                  | 关键数据点汇总（自动抽样，最多 20 行） |

所有子图均标注饱和点（边际收益降至峰值 5% 的位置），数据表格中饱和点行以黄色高亮。

#### 典型工作流

```bash
# 方式一：使用 batch 脚本一次性完成（推荐）
python sensitivity_batch.py --input base.json --workers 4 --vectorized

# 方式二：分组混合热启动（推荐，兼顾并行度和热启动优势）
python sensitivity_batch.py --input base.json --warm-start --warm-start-groups 4 --vectorized

# 方式三：分步执行
# 1. 运行敏感性分析（生成原始数据）
python sensitivity_analysis.py --input base_input.json --resource camera --range 0 400 10 --vectorized

# 2. 生成优化报告
python sensitivity_report.py sensitivity_results/sensitivity_camera.json

# 3. 批量生成所有资源的报告
python sensitivity_analysis.py --input base_input.json --resource all --vectorized
python sensitivity_report.py sensitivity_results/ --all --out_dir ./reports
```

#### 执行模式说明

sensitivity_analysis.py 和 sensitivity_batch.py 支持三种执行模式：

| 模式 | 参数 | 并行度 | 热启动 | 适用场景 |
| :--- | :--- | :--- | :--- | :--- |
| 纯并行 | （默认） | workers 个进程 | ✗ | 采样点少、每点耗时短 |
| 串行热启动 | `--warm-start` | 1 | ✓ 全链路 | 采样点多、资源值跨度大 |
| 分组混合热启动 | `--warm-start --warm-start-groups N` | N 组并行 | ✓ 组内 | **推荐**，兼顾并行度和热启动优势 |

分组混合策略将采样点按资源值顺序切分为 N 个连续块，每个块内部串行热启动（低资源点结果作为高资源点初始解），块之间并行执行。例如 41 个采样点、4 组并行：

```
组1 (并行): [0]COLD → [10]WARM → [20]WARM → ... → [100]WARM   ↘
组2 (并行): [110]COLD → [120]WARM → ... → [210]WARM            并发
组3 (并行): [220]COLD → [230]WARM → ... → [320]WARM            执行
组4 (并行): [330]COLD → [340]WARM → ... → [400]WARM           ↗
```

***

## 十、蒙特卡洛鲁棒性分析

**文件**：`hexdynamic/monte_carlo_robust.py`

对资源约束进行随机采样，运行 N 次 DSSA 优化试验，统计优化结果的分布，评估部署方案在不同资源配置下的鲁棒性。

### 用法

```bash
cd hexdynamic

# 基本用法（100 次试验，结果保存到 ./robust_results）
python monte_carlo_robust.py base_config.json

# 指定试验次数和输出目录
python monte_carlo_robust.py base_config.json --num-trials 200 --output-dir ./mc_results

# 固定随机种子（可复现）
python monte_carlo_robust.py base_config.json --seed 42

# 并行加速（使用 4 个进程）
python monte_carlo_robust.py base_config.json --num-trials 500 --workers 4

# 向量化模式（大规模网格推荐）
python monte_carlo_robust.py base_config.json --vectorized

# 只生成汇总 JSON，跳过图表
python monte_carlo_robust.py base_config.json --no-visualize
```

### 命令行参数

| 参数                 | 默认值                | 说明                                           |
| :----------------- | :----------------- | :------------------------------------------- |
| `base_config`      | 必填                 | 基础输入 JSON 路径（地图、地形、DSSA 配置等）                 |
| `--num-trials N`   | 100                | 蒙特卡洛试验次数                                     |
| `--output-dir DIR` | `./robust_results` | 输出目录（试验 JSON + 图表）                           |
| `--seed SEED`      | None               | 随机种子，设置后结果可复现                                |
| `--workers W`      | `os.cpu_count()`   | 并行工作进程数；`--workers 1` 为顺序执行                  |
| `--vectorized`     | false              | 使用向量化覆盖模型（网格数 >1000 推荐）                      |
| `--no-visualize`   | false              | 跳过图表生成，只写 `results_summary.json`             |
| `--weights W`      | 见下表                | 资源权重配置，格式：`patrol:w,camp:w,drone:w,camera:w` |

### 资源权重配置

计算资源效率时，不同资源类型可配置不同的权重，反映其相对成本或战略价值：

| 资源     | 默认权重 | 说明            |
| :----- | :--: | :------------ |
| patrol | 0.40 | 最劳动密集，单位成本最高  |
| camp   | 0.25 | 基础设施成本，支持巡逻后勤 |
| drone  | 0.20 | 设备 + 维护成本     |
| camera | 0.15 | 单位成本最低，固定基础设施 |

**权重配置方式**（优先级从高到低）：

1. **命令行参数** `--weights`：
   ```bash
   python monte_carlo_robust.py base.json --weights patrol:0.5,camp:0.2,drone:0.2,camera:0.1
   ```
2. **基础配置 JSON** 中的 `robustness_weights` 字段：
   ```jsonc
   {
     "robustness_weights": {
       "patrol": 0.4,
       "camp": 0.25,
       "drone": 0.2,
       "camera": 0.15
     },
     "grids": [...],
     "constraints": {...}
   }
   ```
3. **默认权重**：上表所列默认值

> 若提供的权重之和不为 1.0，系统会自动归一化（每个权重除以总和）。权重信息会记录在 `results_summary.json` 的 `meta` 块中，并在效率分析图表中显示。

### 资源约束采样分布

每次试验从以下均匀分布中独立采样（整数，端点包含）：

| 参数              | 分布      | 范围        |
| :-------------- | :------ | :-------- |
| `total_patrol`  | Uniform | \[15, 25] |
| `total_drones`  | Uniform | \[2, 6]   |
| `total_cameras` | Uniform | \[8, 15]  |
| `total_camps`   | Uniform | \[3, 7]   |

其余约束字段（`total_fence_length`、`max_rangers_per_camp` 等）保持基础配置不变。

### 输出

```
robust_results/
├── trial_0000_input.json      # 每次试验的输入 JSON（含采样约束）
├── trial_0000_output.json     # 每次试验的优化输出 JSON
├── trial_0001_input.json
├── trial_0001_output.json
├── ...
├── results_summary.json       # 所有试验汇总
├── robustness_analysis.png    # 鲁棒性分析图表
└── efficiency_analysis.png    # 效率分析图表
```

#### `results_summary.json` 格式

```jsonc
{
  "meta": {
    "base_config": "robust/base.json",
    "num_trials": 100,
    "seed": 42,
    "workers": 8,
    "successful_trials": 97,
    "failed_trials": 3,
    "elapsed_seconds": 142.7,
    "trials_per_second": 0.68,
    "weights": {
      "patrol": 0.40,
      "camp": 0.25,
      "drone": 0.20,
      "camera": 0.15
    }
  },
  "trials": [
    {
      "trial": 0,
      "success": true,
      "constraints": {
        "total_patrol": 18,
        "total_drones": 4,
        "total_cameras": 11,
        "total_camps": 5
      },
      "best_fitness": 0.423,
      "total_protection_benefit": 12.7,
      "weighted_total_resource": 14.35,
      "resource_efficiency": 0.885,
      "error": null
    }
  ]
}
```

#### 效率指标说明

| 指标                        | 公式                                                                        | 含义          |
| :------------------------ | :------------------------------------------------------------------------ | :---------- |
| `weighted_total_resource` | `w_patrol × patrol + w_drone × drone + w_camera × camera + w_camp × camp` | 加权资源总量      |
| `resource_efficiency`     | `total_protection_benefit / weighted_total_resource`                      | 单位加权资源的保护收益 |

#### `robustness_analysis.png` 图表布局

3 行 × 2 列共 6 个子图：

| 位置     | 内容                                              |
| :----- | :---------------------------------------------- |
| 第 1 行左 | `best_fitness` 分布直方图（标注 mean / std / min / max） |
| 第 1 行右 | `total_protection_benefit` 分布直方图（同上）            |
| 第 2 行左 | `total_patrol` vs `best_fitness` 散点图 + 线性趋势线    |
| 第 2 行右 | `total_drones` vs `best_fitness` 散点图 + 线性趋势线    |
| 第 3 行左 | `total_cameras` vs `best_fitness` 散点图 + 线性趋势线   |
| 第 3 行右 | `total_camps` vs `best_fitness` 散点图 + 线性趋势线     |

成功试验少于 2 次时跳过图表生成并打印警告。

#### `efficiency_analysis.png` 图表布局

2 行布局：

| 位置    | 内容                                                               |
| :---- | :--------------------------------------------------------------- |
| 第 1 行 | `resource_efficiency` 分布直方图（标注 mean / std / min / max，副标题显示权重配置） |
| 第 2 行 | 4 个散点图：各资源参数 vs `resource_efficiency`，每个带线性趋势线                   |

成功试验少于 2 次时跳过效率图表生成并打印警告。

### 并行执行说明

- 默认使用 `os.cpu_count()` 个进程并行运行试验（`ProcessPoolExecutor`）
- 所有约束采样在主进程中预先生成，保证相同 `--seed` 下无论 `--workers` 取何值，采样序列完全一致
- `--workers 1` 退化为顺序执行（无子进程开销），适合调试
- 各试验的输入/输出 JSON 写入独立文件，进程间无共享状态

### 典型工作流

```bash
# 1. 准备基础配置（可用 generate_map.py 或 marker 工具生成）
python generate_map.py -m 15 -n 15 --seed 0 -o robust/base.json

# 2. 运行蒙特卡洛分析（固定种子，4 进程并行，向量化模式）
python monte_carlo_robust.py robust/base.json \
    --num-trials 200 --seed 42 --workers 4 --vectorized --output-dir ./mc_results

# 3. 使用自定义权重运行
python monte_carlo_robust.py robust/base.json \
    --num-trials 100 --seed 42 \
    --weights patrol:0.5,camp:0.2,drone:0.2,camera:0.1 \
    --output-dir ./mc_custom_weights

# 4. 查看汇总结果
#    mc_results/results_summary.json  — 所有试验数据
#    mc_results/robustness_analysis.png — 分布图表
#    mc_results/efficiency_analysis.png — 效率分析图表

# 5. 复现特定试验（直接用保存的 trial_XXXX_input.json）
python run.py mc_results/trial_0003_input.json mc_results/trial_0003_rerun.json
```

***

## 十一、Sobol 敏感性分析

本节包含三种 Sobol 敏感性分析工具，从不同角度量化参数对保护收益的影响：

| 工具 | 分析变量 | 核心问题 |
| :--- | :--- | :--- |
| **资源总量 Sobol 分析** | 资源数量（patrol, drone, camera, camp） | 哪种资源数量对保护收益影响最大？ |
| **协同系数 Sobol 分析** | α\_pd, α\_pc + 资源数量 | 协同系数对保护收益的敏感性如何？与资源数量相比如何？ |
| **覆盖度层面 Sobol 分析** | P\_i, D\_i, C\_i（各网格覆盖度） | 保护收益公式中覆盖度的交互效应有多大？ |

### 基本概念

Sobol 敏感性分析是一种全局方法，通过分解输出方差来量化每个输入参数对输出结果的影响程度：

| 指数类型                 | 含义   | 说明                    |
| :------------------- | :--- | :-------------------- |
| **First-order (S1)** | 一阶指数 | 单独考虑该参数引起的输出方差        |
| **Total-order (ST)** | 总阶指数 | 包含该参数与其他参数所有交互作用引起的方差 |

若 `S1 + ST ≈ 1`，说明参数间交互作用弱；若 `ST >> S1`，说明该参数主要通过交互作用影响输出。

***

### 11.1 资源总量 Sobol 分析

**文件**：`sobol_sensitivity.py`（运行分析）和 `analyze_sobol_results.py`（分析已有结果）

以资源数量（total\_patrol, total\_drones, total\_cameras, total\_camps）为变量，分析各资源对保护收益的 Sobol 指数。

#### 运行新的敏感性分析

```bash
cd immc2026-BAI

# 基本用法（使用默认参数范围）
python sobol_sensitivity.py input.json --num-samples 512 --output-dir ./sobol_results

# 指定参数范围（JSON文件）
python sobol_sensitivity.py input.json \
    --params param_defs.json \
    --num-samples 1024 \
    --output-dir ./sobol_results \
    --vectorized

# 指定参数范围（JSON字符串）
python sobol_sensitivity.py input.json \
    --params '[{"name":"total_patrol","min":10,"max":30},{"name":"total_drones","min":1,"max":8}]' \
    --output-dir ./sobol_results \
    --workers 4

# 固定随机种子（可复现）
python sobol_sensitivity.py input.json --num-samples 512 --seed 42 --output-dir ./sobol_results
```

#### 命令行参数

| 参数               | 默认值               | 说明                       |
| :--------------- | :---------------- | :----------------------- |
| `base_config`    | 必填                | 基础输入 JSON 配置文件           |
| `--params`       | 内置默认参数            | 参数定义：JSON 文件路径或 JSON 字符串 |
| `--num-samples`  | 512               | Saltelli 采样基础样本数         |
| `--output-dir`   | `./sobol_results` | 输出目录                     |
| `--seed`         | None              | 随机种子（可复现）                |
| `--workers`      | CPU 核数            | 并行工作进程数                  |
| `--vectorized`   | false             | 使用向量化覆盖模型（大规模地图推荐）       |
| `--no-visualize` | false             | 跳过图表生成（仅输出 JSON）         |

#### 内置默认参数

若不指定 `--params`，使用以下默认参数范围：

| 参数              | 最小值 | 最大值 | 说明     |
| :-------------- | :-: | :-: | :----- |
| `total_patrol`  |  10 |  30 | 巡逻人员总数 |
| `total_drones`  |  1  |  8  | 无人机总数  |
| `total_cameras` |  5  |  20 | 摄像头总数  |
| `total_camps`   |  2  |  10 | 营地总数   |

#### 参数定义 JSON 格式

```jsonc
[
  {"name": "total_patrol", "min": 10, "max": 30},
  {"name": "total_drones", "min": 1, "max": 8},
  {"name": "total_cameras", "min": 5, "max": 20},
  {"name": "total_camps", "min": 2, "max": 10}
]
```

#### 分析已有结果

**文件**：`analyze_sobol_results.py`

当已有评估结果（`eval_*_output.json` 文件）时，使用此脚本重新计算 Sobol 指数并生成可视化图表，无需重新运行优化。

#### 用法

```bash
cd immc2026-BAI

# 基本用法（自动检测参数名）
python analyze_sobol_results.py ./sobol_results

# 指定输出目录
python analyze_sobol_results.py ./sobol_results --output-dir ./sobol_analysis

# 手动指定参数名
python analyze_sobol_results.py ./sobol_results --param-names total_patrol,total_drones,total_cameras,total_camps
```

#### 命令行参数

| 参数              | 默认值               | 说明                            |
| :-------------- | :---------------- | :---------------------------- |
| `results_dir`   | 必填                | 包含 `eval_*_output.json` 文件的目录 |
| `--output-dir`  | 与 results\_dir 相同 | 输出目录                          |
| `--param-names` | 自动检测              | 逗号分隔的参数名列表                    |

#### 输出文件

```
sobol_results/
├── evaluations.json           # 所有评估记录（成功/失败状态、参数值、指标）
├── sobol_indices.json        # Sobol 指数结果（含收敛判断）
├── analysis_config.json      # 分析配置（参数定义）
├── sobol_indices.png         # S1/ST 指数柱状图
└── parameter_ranking.png     # 参数重要性排名图
```

#### Sobol 指数结果解读

#### sobol\_indices.json 结构

```jsonc
{
  "meta": {
    "base_config": "/path/to/input.json",
    "num_samples": 512,
    "total_evaluations": 6144,
    "seed": 42,
    "workers": 8,
    "successful_evaluations": 6144,
    "failed_evaluations": 0
  },
  "problem": {
    "num_vars": 4,
    "names": ["total_patrol", "total_drones", "total_cameras", "total_camps"],
    "bounds": [[10, 30], [1, 8], [5, 20], [2, 10]]
  },
  "first_order": [
    {
      "name": "total_patrol",
      "value": 0.35,
      "conf_low": 0.28,
      "conf_high": 0.42,
      "converged": true
    }
    // ... 其他参数
  ],
  "total_order": [
    {
      "name": "total_patrol",
      "value": 0.52,
      "conf_low": 0.45,
      "conf_high": 0.59,
      "converged": true
    }
    // ... 其他参数
  ],
  "convergence_summary": {
    "all_converged": true,
    "max_conf_width": 0.14,
    "parameters_not_converged": []
  }
}
```

#### 收敛判断标准

置信区间宽度 < 0.2 时认为该参数已收敛：`2 * conf_interval < 0.2`

| 字段                         | 含义             |
| :------------------------- | :------------- |
| `converged`                | 该参数是否收敛        |
| `max_conf_width`           | 所有参数中最大的置信区间宽度 |
| `parameters_not_converged` | 未收敛的参数名列表      |

> 若有参数未收敛，说明样本量不足，建议增加 `--num-samples`（通常 512-1024 可达收敛）。

#### 指数解读示例

```
total_patrol:   S1=0.35, ST=0.52
total_drones:   S1=0.20, ST=0.45
total_cameras:  S1=0.10, ST=0.25
total_camps:    S1=0.05, ST=0.08
```

- `total_patrol` 的 S1=0.35 表示该参数单独解释 35% 的输出方差
- `total_patrol` 的 ST=0.52 表示该参数及其交互作用共解释 52% 的方差
- `S1 << ST` 说明 `total_patrol` 与其他参数存在显著交互作用
- 按 ST 从大到小排序：`total_patrol > total_drones > total_cameras > total_camps`

#### 算法原理

SALib 使用 Saltelli 采样生成 `N × (2k + 2)` 个样本（k=参数个数），每个样本调用一次保护 pipeline 获取 `best_fitness`。采样后使用 Sobol 分解计算各阶指数：

```
Y = V_0 + Σ V_i + Σ V_{ij} + ... + V_{12...k}

S_i = V_i / V_total
ST_i = Σ V_{u} / V_total  (u 为包含 i 的所有集合)
```

计算完成后通过 Bootstrap 重采样计算置信区间。

***

### 11.2 协同系数 Sobol 分析

**文件**：`sobol_synergy_analysis.py`

将协同系数 `alpha_pd`（Patrol+Drone）和 `alpha_pc`（Patrol+Camera）作为 Sobol 分析的输入变量，与资源数量变量一起分析，量化协同系数对保护收益的一阶敏感性和交互效应。

#### 分析变量

| 变量 | 范围 | 说明 |
| :--- | :--- | :--- |
| `alpha_pd` | [0.0, 1.0] | Patrol+Drone 协同系数 |
| `alpha_pc` | [0.0, 0.5] | Patrol+Camera 协同系数 |
| `total_patrol` | [10, 30] | 巡逻人员总数 |
| `total_drones` | [1, 8] | 无人机总数 |
| `total_cameras` | [5, 20] | 摄像头总数 |

#### 用法

```bash
# 基本用法
python sobol_synergy_analysis.py base.json --num-samples 256

# 并行 + 向量化模式
python sobol_synergy_analysis.py base.json --num-samples 256 --workers 8 --vectorized

# 自定义参数范围（JSON 文件或 JSON 字符串）
python sobol_synergy_analysis.py base.json \
    --params '[{"name":"alpha_pd","min":0.0,"max":2.0},{"name":"alpha_pc","min":0.0,"max":1.0},{"name":"total_patrol","min":5,"max":40}]' \
    --num-samples 512

# 固定随机种子
python sobol_synergy_analysis.py base.json --num-samples 256 --seed 42
```

#### 命令行参数

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `base_config` | 必填 | 基础输入 JSON 配置文件 |
| `--params` | 内置默认参数 | 参数定义：JSON 文件路径或 JSON 字符串 |
| `--num-samples` | 256 | Saltelli 采样基础样本数 |
| `--output-dir` | `./sobol_synergy_results` | 输出目录 |
| `--seed` | 42 | 随机种子 |
| `--workers` | CPU 核数 | 并行工作进程数 |
| `--vectorized` | false | 使用向量化覆盖模型 |

#### 自定义参数定义

通过 `--params` 指定 JSON 文件路径或内联 JSON 字符串，格式如下：

```jsonc
[
  {"name": "alpha_pd", "min": 0.0, "max": 1.0},
  {"name": "alpha_pc", "min": 0.0, "max": 0.5},
  {"name": "total_patrol", "min": 10, "max": 30},
  {"name": "total_drones", "min": 1, "max": 8},
  {"name": "total_cameras", "min": 5, "max": 20}
]
```

> 以 `alpha_` 开头的参数自动注入 `coverage_params`，`total_` 开头的参数注入 `constraints`，覆盖权重/半径参数注入 `coverage_params`。

#### 输出

```
sobol_synergy_results/
├── evaluations.json                # 所有评估记录
├── sobol_synergy_indices.json      # Sobol 指数结果（含 S1/ST/S2）
├── sobol_synergy_indices.png       # S1/ST 柱状图 + 交互效应图 + 二阶交互图
└── synergy_vs_resource_comparison.png  # 协同系数 vs 资源数量敏感性对比
```

#### 结果解读要点

- **一阶指数 S1**：`alpha_pd` 和 `alpha_pc` 的 S1 反映协同系数单独对保护收益的贡献
- **交互效应 ST - S1**：若协同系数的交互效应较大，说明协同效果依赖于资源数量配置
- **二阶指数 S2**：关注 `alpha_pd × total_patrol`、`alpha_pc × total_patrol` 等交叉项，量化协同系数与资源数量的联合效应
- **协同 vs 资源对比图**：直观比较协同系数与资源数量的平均敏感性大小

***

### 11.3 覆盖度层面 Sobol 分析

**文件**：`sobol_coverage_analysis.py`

不以资源总量为变量，而以各网格的覆盖度 P\_i、D\_i、C\_i 为变量，直接对保护收益公式进行 Sobol 分析。绕过 DSSA 优化器，隔离出保护效果模型中覆盖度交互的纯数学效应。

#### 核心思路

传统 Sobol 分析以资源数量为变量，需要运行完整 pipeline（含 DSSA 优化），优化器会"吸收"协同效应。覆盖度层面分析直接采样覆盖值，计算保护收益公式 `B = R × (1 - e^{-E})` 的 Sobol 指数，其中：

```
E = wp·P + wd·D + wc·C + wf·F + α_pd·(P·D)/(1+P+D) + α_pc·(P·C)/(1+P+C)
```

F 固定为 0，聚焦 P/D/C 三者交互。

#### 分析模式

| 模式 | 说明 | 适用场景 |
| :--- | :--- | :--- |
| `single` | 选取一个代表性网格，对 P, D, C ∈ [0,1] 采样 | 详细分析单个网格的交互效应 |
| `aggregate` | 对所有网格逐一计算覆盖度 Sobol 指数，汇总统计 | 了解交互效应的空间分布特征 |
| `both` | 同时运行两种模式 | 完整分析（默认） |

#### 用法

```bash
# 默认模式（single + aggregate）
python sobol_coverage_analysis.py base.json --num-samples 1024

# 仅单网格分析
python sobol_coverage_analysis.py base.json --mode single --num-samples 2048

# 指定网格 ID
python sobol_coverage_analysis.py base.json --grid-id 5 --num-samples 2048 --mode single

# 自定义协同系数
python sobol_coverage_analysis.py base.json --alpha-pd 0.8 --alpha-pc 0.3 --mode aggregate

# 仅聚合分析
python sobol_coverage_analysis.py base.json --mode aggregate --num-samples 1024
```

#### 命令行参数

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `base_config` | 必填 | 基础输入 JSON 配置文件 |
| `--num-samples` | 1024 | Saltelli 采样基础样本数 |
| `--output-dir` | `./sobol_coverage_results` | 输出目录 |
| `--seed` | 42 | 随机种子 |
| `--grid-id` | 中位风险网格 | 单网格分析的目标网格 ID |
| `--alpha-pd` | 0.4 | Patrol+Drone 协同系数 |
| `--alpha-pc` | 0.15 | Patrol+Camera 协同系数 |
| `--mode` | `both` | 分析模式：`single` / `aggregate` / `both` |

#### 输出

```
sobol_coverage_results/
├── sobol_coverage_results.json     # 完整结果（单网格 + 多网格汇总）
├── coverage_sobol_single_grid.png  # 单网格 S1/ST/交互/S2 图
├── coverage_sobol_aggregate.png    # 多网格 S1/ST/交互分布图
└── coverage_s2_vs_risk.png         # 二阶交互指数 vs 网格风险散点图
```

#### 结果解读要点

- **二阶指数 S2**：核心指标
  - `P × D` 的 S2 对应 `alpha_pd` 协同效应的数学贡献
  - `P × C` 的 S2 对应 `alpha_pc` 协同效应的数学贡献
  - `D × C` 的 S2 作为对照（无协同项，理论上应接近 0）
- **S2 vs 网格风险散点图**：展示协同效应是否在高风险区域更显著
- **与资源总量 Sobol 的区别**：覆盖度层面分析消除了空间衰减和优化器"吸收"效应，`P × D` 和 `P × C` 的 S2 指数通常显著高于资源总量层面的分析结果

#### 三种 Sobol 分析的对比

| 对比维度 | 11.1 资源总量 | 11.2 协同系数 | 11.3 覆盖度层面 |
| :--- | :--- | :--- | :--- |
| 分析变量 | 资源数量 | α\_pd, α\_pc + 资源数量 | P, D, C 覆盖度 |
| 是否运行 DSSA | ✓ | ✓ | ✗ |
| 计算速度 | 慢（每次需优化） | 慢（每次需优化） | 快（纯数学计算） |
| 推荐样本量 | 512+ | 256+ | 1024+ |
| 二阶交互 | 资源间交互 | 协同系数 × 资源 | P×D, P×C, D×C |
| 核心价值 | 资源重要性排名 | 协同系数敏感性 | 公式层面交互效应 |

***

## 十二、变更历史（Change History）

### 2026-05-08：文档全面审查与更新

- **文档版本升级至 2.3**：基于完整代码审查，全面校验文档与代码的一致性
- **新增根目录工具说明**：
  - `marker_to_pipeline.py`：Marker 导出 JSON 到 pipeline 输入 JSON 的转换工具，支持 odd-r offset 坐标到轴坐标转换、colorTag 到地形类型映射、物种密度规则生成
  - `analyze_resource_contribution.py`：资源贡献诊断工具，通过假设场景分析各资源的边际收益，辅助排查资源利用率为 0% 的问题
  - `analyze_sobol_results.py`：从已有 Sobol 评估结果重新计算指数并生成可视化图表，支持 Bootstrap 置信区间
- **新增 riskIndex 子系统工具说明**：
  - `risk_model_wrapper.py`：风险模型外部调用封装，6 步流程（加载数据→距离计算→配置→模型创建→数据转换→风险计算），支持矩形/不规则边界
  - `generate_hex_map.py`：六边形网格地图生成器，支持 JSON 配置自定义地形特征（道路、水源、森林、山脉、盐沼等），含物种密度规则和火灾风险模型
  - `generate_square_map.py`：方形网格地图生成器，功能与六边形版本对应
  - `convert_map_for_wrapper.py`：地图格式转换工具（字段重命名）
  - `visualize_risk_from_json.py`：风险热力图生成，支持方形/六边形网格，自适应字号和图片尺寸
- **整体流程图更新**：补充 `marker_to_pipeline.py` 转换步骤和 `riskIndex/` 子系统路径
- **补充 coverage_model_vectorized.py 说明**：向量化覆盖模型继承自 CoverageModel，预计算向量、分块距离计算（chunk=2048）、OOM 回退机制
- **补充 DSSA 优化器完整参数表**：包括停滞检测（stagnation_threshold/stagnation_boost）、适应度缓存（fitness_cache_max_size）、并行评估（fitness_workers）、资源迁移（migrate_prob）和全局重排（reshuffle_prob）操作
- **补充 HexGridModel 内存控制说明**：距离矩阵惰性加载、max_precompute_bytes 阈值（默认 800MB）、稀疏距离矩阵回退
- **数据文件说明**：`data/` 目录新增 Q2 保护结果 CSV（4 种时间场景：Day/Night × Dry/Rainy），记录各网格的风险指数和保护水平

### 2026-05-07：敏感性分析优化——热启动、缓存、分组混合策略、目录结构统一

- **sensitivity_analysis.py 新增参数**：`--workers`（纯并行模式工作进程数）、`--two-step`（两步法）、`--fine-step-ratio`、`--warm-start`（串行热启动）、`--warm-start-groups`（分组混合热启动并行组数）、`--no-cache`（禁用缓存）
- **sensitivity_batch.py 目录结构统一**：所有输出文件统一存放在 `--report-dir`（默认 `./figures/single_sensitivity`）目录下，中间结果放在 `sensitivity_results/` 子目录中；`--output` 参数改为可选，默认为 `--report-dir/sensitivity_results/`
- **sensitivity_batch.py 启动前自动清理**：每次运行时自动清理缓存目录（`.cache/`）和临时文件（`temp_input_*.json`、`temp_output_*.json`），确保从干净状态启动
- **sensitivity_batch.py 新增参数**：`--two-step`、`--fine-step-ratio`、`--warm-start`、`--warm-start-groups`、`--no-cache`，参数透传至 sensitivity_analysis.py
- **dssa_optimizer.py 热启动支持**：新增 `warm_start_solution` 参数，支持从已有解注入和扰动初始化种群（1/3 种群为热启动个体）
- **protection_pipeline.py 热启动支持**：新增 `--warm-start` CLI 参数，从已有输出 JSON 加载部署方案作为初始解
- **Bug 修复**：`dssa_optimizer._perturb_solution` 中 rangers 扰动的 `dst_candidates` 误用 `perturbed.camps` 判断，已修正为 `perturbed.rangers`

### 2026-05-02：新增多资源并行敏感性分析与 bug 修复

- **新增 `sensitivity_batch.py`**：并行运行多种资源的单因素敏感性分析，支持每种资源设置不同的分析范围（`--ranges resource:min:max:step`），分析完成后自动调用 `sensitivity_report.py` 生成可视化报告
- **修复 `sensitivity_analysis.py` 的 `--resource all` bug**：原代码在循环中修改 `resource_range` 变量，导致 `--resource all` 时所有资源都使用第一个资源（patrol）的默认范围。修复后改为使用 `DEFAULT_RANGES` 字典为每种资源独立查找默认范围
- **文档更新**：`usage.md` 第九节重构为三个子章节（9.1 单资源分析 / 9.2 多资源并行分析 / 9.3 报告生成），新增工具总览表和对比表

### 2026-05-02：新增协同系数与覆盖度层面 Sobol 敏感性分析

- **新增 `sobol_synergy_analysis.py`**：以协同系数 `alpha_pd`、`alpha_pc` 为分析变量，与资源数量一起进行 Sobol 敏感性分析，量化协同系数的一阶敏感性和与资源数量的二阶交互效应
- **新增 `sobol_coverage_analysis.py`**：以各网格覆盖度 P\_i、D\_i、C\_i 为变量，绕过 DSSA 优化器直接对保护收益公式进行 Sobol 分析，隔离覆盖度层面的纯数学交互效应
- **文档更新**：`usage.md` 第十一节重构为三个子章节（11.1 资源总量 Sobol / 11.2 协同系数 Sobol / 11.3 覆盖度层面 Sobol），新增三种分析工具的对比表

### 2026-05-02：权重参数统一配置

- **权重参数 JSON 化**：所有权重参数（`risk_weights`、`human_risk_weights`、`environmental_risk_weights`、`temporal_weights`）统一在输入 JSON 的 `risk_model_config` 中定义，所有字段均可选，缺失时使用代码默认值
- **新增 `temporal_weights` 分组**：昼夜因子（`daytime_factor`、`nighttime_factor`、`gamma`）和季节因子（`dry_season_factor`、`rainy_season_factor`）可通过 JSON 配置
- **修正人为风险默认权重**：从 `boundary=0.4, road=0.35, water=0.25` 修正为 `boundary=0.2, road=0.3, water=0.5`，与代码中 `HumanRiskWeights` 默认值一致
- **`generate_map.py` 新增 CLI 参数**：`--boundary_weight`、`--road_weight`、`--water_weight`、`--fire_weight`、`--terrain_weight`、`--daytime_factor`、`--nighttime_factor`、`--gamma`、`--dry_season_factor`、`--rainy_season_factor`
- **Marker 导出面板新增权重输入**：综合风险权重、人为风险权重、环境风险权重、时间因子权重四个区块
- **代码改动**：`risk_model_wrapper.py`、`risk_analysis.py`、`protection_pipeline.py`、`check_temporal.py` 均支持从 JSON 读取 `temporal_weights` 并创建 `TemporalFactorCalculator`
- **文档更新**：`usage.md` 第六节新增「权重参数配置」子章节，章节序号修正（九～十一）

### 2026-04-30：图片转视频工具与优化功能增强

#### 新增图片转视频工具

- **新增** **`images_to_video.py`**：
  - 支持 OpenCV 和 FFmpeg 两种后端
  - 自然排序图片序列，确保迭代顺序正确
  - 支持指定帧率、缩放因子
  - 支持子目录查找图片（如 `iteration_0000/deployment_map.png`）
  - 提供无确认模式，适合脚本调用
  - 默认优先使用 OpenCV 后端（如果已安装）
- **依赖说明**：
  - OpenCV：`pip install opencv-python`（推荐）
  - FFmpeg：需单独安装软件并添加到 PATH

#### 优化算法增强

- **风险优先部署策略**：
  - DSSA 配置新增 `use_risk_priority: true` 选项
  - 将网格按归一化风险值排序，分为高风险组和低风险组
  - 初始化解决方案时优先在高风险网格部署资源
  - 配置参数：`high_risk_percentage`（默认 0.3）控制高风险网格比例
- **迭代可视化优化**：
  - `save_iteration_visualization` 配置启用时，异步绘制每轮迭代最优方案
  - 添加 `matplotlib.rcParams["figure.max_open_warning"] = 0` 避免警告
  - 异步绘制函数中添加 `plt.close('all')` 和 `gc.collect()` 清理内存
- **网格编号配置**：
  - 输出 JSON 新增 `visualization_config.show_grid_ids` 配置项
  - 默认 `false` 不显示网格编号
  - 所有绘图函数统一读取该参数控制网格编号显示

#### 文档更新

- 新增第八节「图片转视频工具」，完整说明 `images_to_video.py` 的用法
- 同步更新后续章节编号

***

### 2026-04-30：围栏边缘部署增强与可视化优化

#### 围栏部署逻辑重构

- **围栏存储格式变更**：从 `(grid_id, None)` 改为 `(grid_id, direction)`，支持按方向精确控制围栏部署
  - `direction` 为 0-5 的整数，对应六边形的 6 个边
  - 支持每个边界格子在不同方向上部署多段围栏
- **围栏部署规则优化**：
  - 如果可部署边界边总数 ≤ `total_fence_length`，则部署所有边界边
  - 如果可部署边界边总数 > `total_fence_length`，则随机选择 `total_fence_length` 条边部署
- **六边形方向映射修正**：修正了 NE/NW/SW/SE 的方向坐标对应关系，与标准 pointy-top 六边形网格规范一致

#### 可视化增强

- **新增** **`species_deployment_comparison.png`**：上下布局对比图
  - 上半部分：物种密度图（地形半透明底图 + 物种散点）
  - 下半部分：资源部署图（地形半透明底图 + 资源图标 + 围栏边线）
  - 右侧图例：地形、资源、物种说明
- **`risk_comparison.png`** **布局调整**：从左右并排改为上下排列
  - 上半部分：部署前原始风险热力图
  - 下半部分：部署后剩余风险热力图
  - 颜色条移至最左侧，summary 统计信息移至最右侧
- **地形颜色透明化**：
  - `terrain_deployment_map.png` 和 `species_deployment_comparison.png` 的地形底图改为半透明（alpha=0.45）
  - 图例中的地形色块同步半透明（alpha=0.5）
  - 与 `species_map.png` 风格统一，前景元素（资源标记、围栏边线、物种散点）更加突出
- **围栏可视化函数**：新增 `draw_deployed_fence_edges()` 函数
  - 根据 `(grid_id, direction)` 格式精确绘制围栏边线
  - 仅绘制边界边缘（朝向保护区外的边），内部边不绘制
  - 使用加粗红色线段（linewidth=3.0）标识围栏

#### 输出格式变更

- **围栏输出格式**（`protection_pipeline.py`）：
  - 旧格式：`fence_edges: [{grid_id_1, grid_id_2}, ...]`
  - 新格式：每个格子的 `fences` 字段包含 `fence_count` 和 `boundary_edge_list`（方向列表）
  - 全局 `fence_segments` 统计改为 `sum(fences.values())`
- **兼容性**：`coverage_model.py` 和 `dssa_optimizer.py` 同时支持新旧两种围栏格式，旧格式 `(grid_id, None)` 在 repair 阶段自动转换或移除

#### 代码清理

- 删除旧版 `visualization.py` 脚本（已被 `visualize_output.py` 替代）
- 删除测试文件（`test_*.py`），测试逻辑已整合到主流程中

***

*文档版本: 2.3*\
*最后更新: 2026-05-08*
