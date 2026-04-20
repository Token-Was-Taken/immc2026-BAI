# 使用说明

本文档说明如何使用以下工具完成从地图标注到保护资源部署优化的完整流程。

---

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
```

---

## 一、Marker 标注工具

**文件**：`marker/image-viewer.html`，直接用浏览器打开，无需安装依赖。

### 基本操作

- **加载图片**：将地图图片拖入页面，或点击上传区域选择文件。
- **网格化**：点击 `⬡ 网格化` 按钮叠加六边形网格，拖动 `半径` 滑块调整网格大小。
- **标注地形**：调色板中每种颜色对应一种地形类型：

| 颜色 | 地形类型 | `terrain_type` |
| :--: | :------ | :------------- |
| 🟢 绿色 | 森林密集区 | DenseGrass |
| 🔴 红色 | 森林稀疏区 | SparseGrass |
| 🔵 蓝色 | 水坑 | WaterHole |
| 🟡 黄色 | 干坑 | SaltMarsh |
| 🟣 紫色 | 主路 | Road |
| 🟠 橙色 | 小路 | Road |
| 🩵 青色 | 盐沼 | SaltMarsh |

- 单击色块选色，再单击格子填色；框选可批量填色
- 再次单击已填色格子取消填色
- `Ctrl/Cmd + 点击` 多选后点色块统一填色
- `📥 导入JSON` / `📤 导出JSON`：导入或导出网格标注数据
- `📥 导出SVG`：导出带图例的矢量网格图

### 导出 Pipeline 输入 JSON

完成标注后点击 `🚀 导出Pipeline JSON`，在弹出的配置面板中填写参数后点击 `📥 生成并下载`，下载 `pipeline_input.json`。

> 配置面板参数说明见第二节（与 `generate_map.py` 参数一致）。

> 未标注颜色的格子默认视为 SparseGrass。主路/小路格子坐标自动提取为 `road_locations`，水坑格子自动提取为 `water_locations`。

---

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

- 道路随机选南北或东西方向贯穿，每隔 2~3 格随机横向偏移 ±1，不是直线
- 犀牛/大象密度只在 SparseGrass 格子生成，其他地形为 0
- 鸟类密度在 SaltMarsh 为 0.6~1.0，其他地形为 0~0.1

### 命令行参数

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `-m` | 10 | 地图行数 |
| `-n` | 12 | 地图列数 |
| `-o` | `pipeline_input.json` | 输出文件路径 |
| `--seed` | None | 随机种子 |
| `--hour_of_day` | 12 | 时间（0-23） |
| `--season` | DRY | 季节：DRY / RAINY |
| `--use_temporal_factors` | False | 启用昼夜/季节时间因子 |
| `--total_patrol` | 20 | 巡逻人员总数 |
| `--total_camps` | 5 | 营地总数 |
| `--max_rangers_per_camp` | 5 | 每营地最大人员 |
| `--total_cameras` | 10 | 摄像头总数 |
| `--total_drones` | 3 | 无人机总数 |
| `--total_fence_length` | 50 | 围栏参数（已不影响结果，围栏固定部署在所有边缘格） |
| `--patrol_radius` | 5.0 | 巡逻覆盖衰减半径 |
| `--drone_radius` | 8.0 | 无人机覆盖半径 |
| `--camera_radius` | 3.0 | 摄像头覆盖半径 |
| `--fence_protection` | 0.5 | 每段围栏保护系数 |
| `--wp/wd/wc/wf` | 0.3/0.3/0.2/0.2 | 巡逻/无人机/摄像头/围栏权重 |
| `--population_size` | 50 | DSSA 种群大小 |
| `--max_iterations` | 100 | DSSA 最大迭代次数 |

---

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

  // 风险模型权重（可选）
  "risk_model_config": {
    "risk_weights": { "human_weight": 0.4, "environmental_weight": 0.3, "density_weight": 0.3 },
    "human_risk_weights": { "boundary_weight": 0.4, "road_weight": 0.35, "water_weight": 0.25 },
    "environmental_risk_weights": { "fire_weight": 0.6, "terrain_weight": 0.4 }
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
    "fence_protection": 0.5, "wp": 0.3, "wd": 0.3, "wc": 0.2, "wf": 0.2
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

| `terrain_type` | 巡逻 | 营地 | 无人机 | 摄像头 | 围栏 |
| :------------ | :--: | :--: | :----: | :----: | :--: |
| SparseGrass | ✓（见下方规则） | ✗ | ✓ | ✓ | ✓（仅边缘） |
| DenseGrass | ✗ | ✗ | ✓ | ✗ | ✓（仅边缘） |
| WaterHole | ✗ | ✗ | ✓ | ✗ | ✗ |
| SaltMarsh | ✗ | ✗ | ✓ | ✗ | ✗ |
| Road | ✓ | ✓ | ✓ | ✓ | ✓（仅边缘） |

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

| 参数 | 默认值 | 说明 |
| :--- | :---: | :--- |
| `max_cameras_per_grid` | 1 | 每格最多摄像头数量（可 >1 实现密集监控） |
| `max_drones_per_grid` | 1 | 每格最多无人机数量 |
| `max_camps_per_grid` | 1 | 每格最多营地数量 |
| `max_rangers_per_grid` | 1 | 每格最多巡逻人员数量 |

> 营地和无人机/摄像头的单格上限通常为 1（一个格子建不了两个营地或停两架无人机），但摄像头可以设置 >1 以支持密集监控场景。

#### 第三层：全局总量（Global Budget）

所有同类资源的部署总数不得超过该资源的全局配额：

| 约束字段 | 默认值 | 说明 |
| :--- | :---: | :--- |
| `total_patrol` | 20 | 巡逻人员总数 |
| `total_camps` | 5 | 营地总数 |
| `total_cameras` | 10 | 摄像头总数 |
| `total_drones` | 3 | 无人机总数 |
| `total_fence_length` | 50 | 围栏总长度（已不影响结果，围栏固定部署在边缘） |

#### 第四层：互斥规则

- **巡逻员与营地互斥**：同一格子不能同时部署 patrol 和 camp。若优化过程中两者被分配到同一格，repair 阶段会自动移除该格的巡逻员。

#### 约束执行时机

| 阶段 | 代码位置 | 执行内容 |
| :--- | :--- | :--- |
| **初始化** | `dssa_optimizer._initialize_solution()` | 按可行性矩阵 + 单格上限 + 全局总量生成初始解 |
| **向量解码** | `dssa_optimizer._vector_to_solution()` | 将 DSSA 连续向量截断为整数解时应用单格上限 |
| **修复** | `coverage_model.repair_solution()` | 迭代修复违反约束的解：先裁单格上限 → 再裁全局总量 → 清除互斥冲突 |
| **验证** | `coverage_model.validate_solution()` | 检查最终解是否仍有违规（用于调试） |

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

| 指标 | 公式 | 含义 |
| :--- | :--- | :--- |
| `risk_normalized` | riskIndex min-max 归一化 | 综合威胁程度，越高越需要保护 |
| `protection_benefit_raw` | `R_i × (1 - e^(-E_i))` | 该格实际获得的保护收益 |
| `protection_benefit_normalized` | min-max 归一化 | 相对保护收益，便于可视化 |
| `residual_risk_normalized` | `R_i × e^(-E_i)`，min-max 归一化 | 部署后剩余风险，越低说明保护越充分 |
| Total Protection Benefit | `Σ protection_benefit_raw` | 全局保护收益总量 |
| Average Protection Benefit | `Total / N` | 每格平均保护收益 |
| Best Fitness | `Total / Σ R_i` | 风险加权归一化保护效率，优化目标 |

综合保护效果 `E_i = wp × patrol_cov + wd × drone_cov + wc × camera_cov + wf × fence_prot`，各覆盖度基于指数衰减函数计算。

---

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

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `input` | 必填 | 输入 JSON（pipeline 模式）或 output JSON（`--visualize-only` 模式） |
| `output` | 必填（pipeline 模式） | 输出 JSON 路径 |
| `--vectorized` | false | 使用向量化覆盖模型（网格数 >1000 推荐） |
| `--allow-partial-deployment` | false | 允许按边际收益决定是否部署资源 |
| `--freeze-resources` | None | 冻结资源列表，逗号分隔，如 `patrol,camera` |
| `--no-visualize` | false | 只运行优化，不生成图片 |
| `--visualize-only` | false | 只生成图片，跳过优化 |
| `--input, -i` | None | `--visualize-only` 时的原始 input JSON（用于物种数据） |
| `--out_dir, -d` | `./figures` | 图片输出目录 |
| `--prefix` | `""` | 输出文件名前缀 |

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

# 向量化 + 可视化（完整流程）
python run_with_iteration_output.py input.json -o results/ --vectorized --visualize
```

#### 命令行参数

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `input_json` | 必填 | 输入 JSON 路径 |
| `-o, --output` | `./output_results` | 输出目录 |
| `--iterations` | 从 input.json 读取 | DSSA 迭代次数，CLI 优先 |
| `--vectorized` | 从 input.json 读取 | 使用向量化覆盖模型（>1000 格推荐），CLI 优先 |
| `--visualize` | false | 生成可视化图片 |

> **优先级**：命令行参数 > input.json 中的 dsssa_config > 默认值（50次迭代）

#### 输出结构

```
results/
├── final_output.json              # 最终优化结果
├── iterations/                    # 每轮迭代的部署方案（非阻塞异步写入）
│   ├── iteration_0000/
│   │   ├── producers.json         # producer 个体列表
│   │   ├── followers.json         # follower 个体列表
│   │   └── scouts.json           # scout 个体列表
│   ├── iteration_0001/
│   └── ...
├── visualization/                 # 转换后的可视化格式（可选）
│   ├── iteration_0000/
│   │   ├── producers.json
│   │   └── ...
│   └── ...
└── figures/                       # 可视化图片（可选）
```

#### 迭代结果后处理

**文件**：`hexdynamic/postprocess_iteration.py`

将迭代输出转换为 `visualize_output.py` 可用的格式：

```bash
python hexdynamic/postprocess_iteration.py <迭代目录> <原始input_json> [-o 输出目录]

# 示例
python hexdynamic/postprocess_iteration.py ./results/iterations/iteration_0005 input.json -o ./viz/
```

#### DSSAConfig 新增参数

在输入 JSON 的 `dssa_config` 中可配置迭代输出：

```json
"dssa_config": {
  "population_size": 50,
  "max_iterations": 100,
  "producer_ratio": 0.2,
  "scout_ratio": 0.2,
  "ST": 0.8,
  "output_dir": "./output_iterations"   // 迭代输出目录
}
```

当 `output_dir` 设置后，DSSA 优化器会在每轮迭代结束后异步写入 JSON 文件，不阻塞主迭代流程。

### 批量 Pipeline（多场景优化+可视化）

**文件**：`hexdynamic/batch_pipeline.py`

对目录中多个 input JSON 依次执行完整的 protection_pipeline（DSSA 优化）+ visualize_output（出图），适用于多时段/多场景批量分析。

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

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `--input-dir, -i` | 必填 | 输入 JSON 所在目录 |
| `--output-dir, -o` | `./batch_results` | 输出根目录 |
| `--pattern, -p` | `*.json` | 文件匹配模式 |
| `--vectorized` | false | 使用向量化覆盖模型（>1000 格推荐） |
| `--allow-partial-deployment` | false | 允许按边际收益决定是否部署资源 |
| `--freeze-resources` | None | 冻结资源列表，逗号分隔 |
| `--no-visualize` | false | 跳过可视化，仅运行优化 |

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

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `--input, -i` | 必填 | 基础输入 JSON 路径 |
| `--resource, -r` | 必填 | 要调整的资源：`patrol` / `camera` / `drone` / `camp` / `fence` |
| `--target-fitness` | —（二选一） | 目标 best_fitness 阈值（如 0.3） |
| `--target-benefit` | —（二选一） | 目标 total_protection_benefit 阈值（如 50.0） |
| `--min` | 0 | 搜索下界（资源数量） |
| `--max` | 1000 | 搜索上界（资源数量） |
| `--tolerance` | 5 | 收敛精度：`hi - lo <= tolerance` 时停止 |
| `--output, -o` | 自动命名 | 最终部署方案输出 JSON 路径 |
| `--work-dir` | `./find_deployment_tmp` | 中间文件目录 |
| `--out-dir` | 与 work-dir 相同 | 图表输出目录 |
| `--vectorized` | false | 使用向量化模式（大规模地图推荐） |
| `--freeze` | None | 冻结其他资源，逗号分隔，如 `patrol,drone,camp` |

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

| 文件/内容 | 说明 |
| :--- | :--- |
| `find_deployment_{resource}_{value}.json` | 最终最小资源量的完整部署方案（output.json 格式） |
| `convergence_total_benefit.png` | Total Protection Benefit 收敛曲线 |
| `convergence_avg_benefit.png` | Average Protection Benefit 收敛曲线 |
| `convergence_best_fitness.png` | Best Fitness 收敛曲线 |
| `convergence_combined.png` | 合并图：3 条曲线 + 迭代历史表格（绿色行=满足目标） |

中间文件保存在 `--work-dir` 目录中（每次迭代的 input/output JSON），可用于调试或复现。

---

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

| 文件 | 内容 | 说明 |
| :--- | :--- | :--- |
| `risk_heatmap.png` | 归一化风险指数热力图 | YlOrRd 色阶，[0,1] 范围，便于跨时段对比 |
| `geo_attr_map.png` | 地理属性地图（到边界/道路/水源的距离） | 三通道 RGB 分别表示三种接近度 |
| `species_attr_map.png` | 物种属性地图（各物种密度分布） | 图标大小正比于密度，形状区分物种 |
| `combined_attr_map.png` | 综合属性图（地理+物种叠加） | 合并展示所有输入属性 |

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

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `--input-dir, -i` | 必填 | 输入 JSON 所在目录 |
| `--output-dir, -o` | `./risk_analysis_results` | 输出根目录 |
| `--pattern, -p` | `*.json` | 文件匹配模式 |
| `--hex-size` | 自动检测 | 六边形大小 |

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

---

## 六、风险模型说明（riskIndex）

pipeline 脚本调用 `riskIndex` 模块计算每个网格的归一化综合风险值 `R_i ∈ [0, 1]`，作为 DSSA 优化的输入。

### 综合风险公式

```
R'_i = (ω₁·H_i + ω₂·E_i + ω₃·D_i) × T_t × S_t

R_i = (R'_i - R_min) / (R_max - R_min)
```

| 符号 | 含义 | 默认权重 |
| :--: | :--- | :-----: |
| H_i | 人为风险（盗猎/人兽冲突） | ω₁ = 0.4 |
| E_i | 环境风险（火灾 + 地形） | ω₂ = 0.3 |
| D_i | 物种密度风险（珍稀物种分布） | ω₃ = 0.3 |
| T_t | 昼夜因子（可选） | — |
| S_t | 季节因子（可选） | — |

### 人为风险 H_i（盗猎风险 + 人兽冲突）

反映人类活动对保护区的威胁，综合考虑三个距离因素：

```
H_i = (α₁·prox_boundary + α₂·prox_road + α₃·prox_water) × P_t
```

| 因素 | 含义 | 默认权重 |
| :--- | :--- | :-----: |
| `prox_boundary` | 到保护区边界的接近度（越近越高） | α₁ = 0.40 |
| `prox_road` | 到道路的接近度（道路是盗猎者进入通道） | α₂ = 0.35 |
| `prox_water` | 到水源的接近度（水源是人兽冲突热点） | α₃ = 0.25 |
| `P_t` | 盗猎时间概率（由昼夜因子决定） | — |

接近度 = `1 - 归一化距离`，即距离越近，接近度越高，风险越大。

在输入 JSON 中，`road_locations` 和 `water_locations` 用于自动计算各格到道路/水源的距离。

### 环境风险 E_i（火灾风险 + 地形复杂度）

```
E_i = β₁·fire_risk + β₂·terrain_complexity
```

| 字段 | 含义 | 默认权重 |
| :--- | :--- | :-----: |
| `fire_risk` | 火灾风险 [0,1]，由植被类型和干燥程度决定 | β₁ = 0.6 |
| `terrain_complexity` | 地形复杂度 [0,1]，复杂地形增加巡逻难度 | β₂ = 0.4 |

这两个值在每个网格的输入数据中直接提供（`generate_map.py` 按地形类型随机生成，marker 工具按颜色给出默认值）。

### 物种密度风险 D_i（珍稀物种分布）

反映该格子的保护价值，物种越密集、保护权重越高，风险值越高：

```
D_i = Σ_s (w_s × density_{s,i} × seasonal_multiplier_s)
```

| 参数 | 含义 |
| :--- | :--- |
| `w_s` | 物种保护权重（rhino=0.5, elephant=0.3, bird=0.2） |
| `density_{s,i}` | 物种 s 在格子 i 的密度 [0,1] |
| `seasonal_multiplier_s` | 季节密度系数（雨季/旱季不同） |

### 时间因子（可选，`use_temporal_factors: true` 时启用）

| 因子 | 计算方式 | 默认值 |
| :--- | :--- | :---: |
| 昼夜因子 T_t | 白天（6:00-18:00）= 1.0，夜间 = 1.3 | 离散模式 |
| 季节因子 S_t | 旱季 = 1.0，雨季 = 1.2 | — |

时间因子作为乘数叠加在基础风险上，夜间雨季的综合风险最高（×1.56）。默认关闭，适合需要分析特定时段风险的场景。

#### 时间因子与归一化的交互

启用时间因子后，原始风险值会按时间因子放大（例如夜间约 1.3 倍），但**归一化后的风险统计指标（min/max/mean）会相同**。这是因为：

1. 原始风险计算：`R'_i = (ω₁·H_i + ω₂·E_i + ω₃·D_i) × T_t × S_t`
2. 归一化处理：`R_i = (R'_i - R_min) / (R_max - R_min)`

所有原始风险都乘以相同的时间因子，因此 min/max 也同时放大，归一化后仍映射到 [0, 1] 范围。结果是：

- **原始风险**：夜间 ≈ 1.3 × 白天
- **归一化风险**：夜间与白天的 min/max/mean 统计值相同（都是 [0, 1] 范围）

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

---

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

| 文件 | 内容 | 颜色条 |
| :--- | :--- | :---: |
| `risk_heatmap.png` | 部署前风险热力图，右侧显示 Total PB / Average PB / Best Fitness | YlOrRd |
| `risk_comparison.png` | 部署前后风险对比（左：原始风险，右：剩余风险），同色阶便于直接对比 | YlOrRd |
| `protection_heatmap.png` | 保护收益热力图，叠加摄像头/无人机/营地/巡逻员/围栏图标 | RdYlGn |
| `terrain_map.png` | 地形颜色地图 | — |
| `terrain_deployment_map.png` | 地形底图 + 部署资源图标叠加 | — |
| `species_map.png` | 地形底图 + 物种密度图标（大小正比于密度，形状区分物种） | — |

有颜色条的图采用三列布局：**地图 | 颜色条 | 图例+指标**，三者互不遮挡。`risk_comparison.png` 采用双图并排布局，左右共用同一颜色条，颜色越深（红色）表示风险越高，对比左右可直观看出哪些高风险区域被有效覆盖。

### 资源图标说明

| 图标 | 颜色 | 资源 |
| :--: | :--: | :--- |
| ■ 方形 | 蓝色 | Camera（摄像头） |
| ▲ 三角 | 橙色 | Drone（无人机） |
| ◆ 菱形 | 紫色 | Camp（营地） |
| ● 圆形 | 绿色 | Patrol（巡逻员） |
| ⬠ 五边形 | 红色 | Fence（围栏，仅显示在边缘格） |

---

## 八、敏感性分析

### 8.1 敏感性分析脚本

**文件**：`sensitivity_analysis.py`

分析每种资源数量对保护效果的影响，找出边际收益递减点，辅助资源配置决策。

#### 用法

```bash
# 分析单种资源
python sensitivity_analysis.py --input base_input.json --resource camera --range 0 400 10

# 分析所有资源（使用默认范围）
python sensitivity_analysis.py --input base_input.json --resource all

# 向量化模式（大规模地图推荐）
python sensitivity_analysis.py --input base_input.json --resource patrol --vectorized
```

#### 命令行参数

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `--input, -i` | 必填 | 基础输入 JSON 路径 |
| `--resource, -r` | `patrol` | 资源类型：`patrol` / `camera` / `drone` / `camp` / `fence` / `all` |
| `--range MIN MAX STEP` | 各资源默认范围 | 资源数量范围，如 `--range 0 400 10` |
| `--output, -o` | `./sensitivity_results` | 输出目录 |
| `--vectorized` | false | 使用向量化模式 |

各资源默认范围：

| 资源 | 默认范围 | 步长 |
| :--- | :--- | :--: |
| patrol | 0 ~ 50 | 5 |
| camera | 0 ~ 20 | 2 |
| drone | 0 ~ 10 | 1 |
| camp | 0 ~ 5 | 1 |
| fence | 0 ~ 100 | 10 |

#### 输出

每种资源生成两个文件：

| 文件 | 说明 |
| :--- | :--- |
| `sensitivity_{resource}.json` | 原始数据，包含每个资源值对应的 total_protection_benefit、best_fitness、resources_deployed |
| `sensitivity_{resource}_plot.png` | 原始曲线图（3 曲线 + 数据表格） |

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

---

### 8.2 敏感性分析报告脚本

**文件**：`sensitivity_report.py`

读取 `sensitivity_analysis.py` 生成的 JSON 数据，生成优化后的可视化报告。相比原始曲线图，报告新增了饱和点标注、累计收益增幅图和优化后的数据表格。

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

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `input` | 必填 | sensitivity JSON 文件路径，或目录（配合 `--all`） |
| `--all` | false | 处理目录下所有 `sensitivity_*.json` 文件 |
| `--out_dir, -d` | 与输入文件同目录 | 图片输出目录 |

#### 输出

每种资源生成一个报告图 `report_{resource}.png`，包含 4 个子图和 1 个数据表格：

| 子图 | 内容 | 说明 |
| :--- | :--- | :--- |
| 左上 | Protection Benefit 曲线 | 总保护收益随资源数量的变化 |
| 右上 | Best Fitness 曲线 | 最佳适应度随资源数量的变化 |
| 左下 | Marginal Benefit 柱状图 | 每增加一单位资源的边际收益 |
| 右下 | Cumulative Gain 曲线 | 相对于零资源基准的累计收益增幅（%） |
| 底部 | 数据表格 | 关键数据点汇总（自动抽样，最多 20 行） |

所有子图均标注饱和点（边际收益降至峰值 5% 的位置），数据表格中饱和点行以黄色高亮。

#### 典型工作流

```bash
# 1. 运行敏感性分析（生成原始数据）
python sensitivity_analysis.py --input base_input.json --resource camera --range 0 400 10 --vectorized

# 2. 生成优化报告
python sensitivity_report.py sensitivity_results/sensitivity_camera.json

# 3. 批量生成所有资源的报告
python sensitivity_analysis.py --input base_input.json --resource all --vectorized
python sensitivity_report.py sensitivity_results/ --all --out_dir ./reports
```
