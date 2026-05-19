# 时序风险对比分析脚本 - 设计文档

## 1. 架构设计

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    time_risk_analyzer.py                     │
├─────────────────────────────────────────────────────────────┤
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐    │
│  │  Input JSON   │  │   Config      │  │  CLI Args     │    │
│  │  (Base Map)   │  │   Manager     │  │  Parser       │    │
│  └───────┬───────┘  └───────────────┘  └───────────────┘    │
│          │                                                   │
│  ┌───────▼───────────────────────────────────────────────┐   │
│  │                  Risk Calculator                        │   │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐      │   │
│  │  │ Day+DRY │ │Day+RAINY│ │Night+DRY│ │Night+   │      │   │
│  │  │         │ │         │ │         │ │ RAINY   │      │   │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘      │   │
│  └──────────────────────────────────────────────────────────┘   │
│          │                                                   │
│  ┌───────▼───────────────────────────────────────────────┐   │
│  │               Visualization Engine                      │   │
│  │  ┌──────────────────┐  ┌──────────────────┐          │   │
│  │  │ Single Heatmap   │  │ 4-Panel Compare  │          │   │
│  │  │ Generator        │  │ Generator        │          │   │
│  │  └──────────────────┘  └──────────────────┘          │   │
│  └──────────────────────────────────────────────────────────┘   │
│          │                                                   │
│  ┌───────▼───────────────────────────────────────────────┐   │
│  │                  Output Manager                         │   │
│  │  - File naming                                        │   │
│  │  - Directory creation                                 │   │
│  │  - Summary report                                     │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 模块划分

| 模块 | 职责 | 主要类/函数 |
|:----|:----|:-----------|
| 输入处理 | 解析输入 JSON | `parse_base_input()` |
| 配置管理 | 管理四种场景配置 | `ScenarioConfig` |
| 风险计算 | 计算各场景风险 | `compute_scenario_risk()` |
| 单图生成 | 生成单个热力图 | `plot_single_risk_heatmap()` |
| 对比图生成 | 生成四象限对比图 | `plot_4panel_comparison()` |
| 输出管理 | 文件输出和摘要 | `save_results()` |

## 2. 数据流设计

### 2.1 输入数据流

```
Input JSON
    │
    ├─ map_config (网格、地形、位置)
    ├─ species_config (物种权重、季节系数)
    ├─ risk_model_config (风险权重参数)
    └─ time_config (use_temporal_factors)
           │
           ▼
    ┌─────────────────┐
    │  Base Risk Data │
    │  (共享数据)      │
    └─────────────────┘
           │
           ├──────────────────────────────┐
           │                              │
           ▼                              ▼
    ┌──────────────┐              ┌──────────────┐
    │ 场景1: Day   │              │ 场景2: Day   │
    │     + DRY    │              │     + RAINY  │
    └──────────────┘              └──────────────┘
           │                              │
           ├──────────────────────────────┤
           ▼                              ▼
    ┌──────────────┐              ┌──────────────┐
    │ 场景3: Night │              │ 场景4: Night │
    │     + DRY    │              │     + RAINY  │
    └──────────────┘              └──────────────┘
```

### 2.2 输出数据流

```
四种场景的风险数据
    │
    ├─→ 8 个单场景热力图
    │       ├─ 4 个归一化风险图
    │       └─ 4 个原始风险图
    │
    └─→ 1 个四象限对比图
            └─ 统一颜色尺 (0 ~ max_raw_risk)
```

## 3. 核心算法设计

### 3.1 场景配置生成

```python
SCENARIOS = [
    {"name": "day_dry",    "hour": 12, "season": "DRY",   "label": "Day + DRY"},
    {"name": "day_rainy",  "hour": 12, "season": "RAINY", "label": "Day + RAINY"},
    {"name": "night_dry",  "hour": 22, "season": "DRY",   "label": "Night + DRY"},
    {"name": "night_rainy","hour": 22, "season": "RAINY", "label": "Night + RAINY"},
]
```

### 3.2 风险计算流程

```
对于每个场景:
    1. 复制基础输入配置
    2. 设置 hour_of_day 和 season
    3. 调用 GridModel 计算综合风险
    4. 提取每个网格的 risk_normalized 和原始风险值
    5. 返回风险数据字典
```

### 3.3 颜色尺范围计算

```python
# 归一化风险图：固定范围 [0, 1]
norm = Normalize(vmin=0, vmax=1)

# 原始风险图：统一范围 [0, max_raw_risk_all_scenarios]
max_raw_risk = max([
    scenario_data["max_raw_risk"]
    for scenario_data in all_scenarios
])
```

## 4. 界面设计

### 4.1 四象限对比图布局

```
┌─────────────────────┬─────────────────────┐
│                     │                     │
│    Day + DRY        │    Day + RAINY      │
│   (raw risk)        │   (raw risk)        │
│                     │                     │
├─────────────────────┼─────────────────────┤
│                     │                     │
│   Night + DRY       │   Night + RAINY     │
│   (raw risk)        │   (raw risk)        │
│                     │                     │
└─────────────────────┴─────────────────────┘
                    │
                    ▼
            ┌───────────────┐
            │  Colorbar    │
            │  [0 ~ max]   │
            └───────────────┘
```

### 4.2 单图布局

```
┌─────────────────────────────────────────┐
│                                         │
│           六边形网格热力图               │
│                                         │
├─────────────────────────────────────────┤
│ Title: {场景名称} - {风险类型}           │
├─────────────────────────┬───────────────┤
│                         │               │
│     六边形网格          │   Colorbar     │
│                         │   [min ~ max] │
│                         │               │
└─────────────────────────┴───────────────┘
```

## 5. 函数设计

### 5.1 核心函数

| 函数名 | 输入 | 输出 | 说明 |
|:------|:-----|:-----|:-----|
| `parse_base_input()` | json_path | dict | 解析输入 JSON |
| `compute_scenario_risk()` | base_input, hour, season | dict | 计算单场景风险 |
| `plot_single_heatmap()` | data, title, cmap_norm, path | None | 绘制单热力图 |
| `plot_4panel_comparison()` | all_scenarios, out_path | None | 绘制四象限图 |
| `generate_all_heatmaps()` | input_path, out_dir, options | None | 生成所有热力图 |

### 5.2 数据结构

```python
# 场景风险数据
ScenarioRiskData = {
    "name": str,              # 场景标识 "day_dry"
    "label": str,             # 展示标签 "Day + DRY"
    "hour": int,             # 小时 12
    "season": str,           # 季节 "DRY"
    "grids": [               # 网格列表
        {
            "grid_id": int,
            "q": int, "r": int,
            "x": int, "y": int,
            "risk_normalized": float,  # 归一化风险
            "risk_raw": float,         # 原始风险
        }
    ],
    "max_raw_risk": float,   # 最大原始风险
    "min_raw_risk": float,   # 最小原始风险
    "mean_raw_risk": float,  # 平均原始风险
}
```

## 6. 错误处理设计

### 6.1 错误类型

| 错误类型 | 处理方式 | 用户提示 |
|:--------|:--------|:--------|
| 文件不存在 | 退出 | "Error: Input file not found: {path}" |
| JSON 解析失败 | 退出 | "Error: Invalid JSON format in {path}" |
| 缺少必需字段 | 使用默认值或警告 | "Warning: Missing field '{field}', using default" |
| 网格数据为空 | 退出 | "Error: No grid data in input" |

### 6.2 警告处理

| 警告类型 | 处理方式 |
|:--------|:--------|
| 缺少物种配置 | 使用默认权重 1.0 |
| 缺少风险权重 | 使用文档默认值 |
| 时间因子未启用 | 自动启用并警告 |

## 7. 性能优化设计

### 7.1 优化策略

1. **共享计算**：基础风险数据（人为风险、环境风险）只计算一次
2. **时间因子复用**：四个场景共享基础风险，通过简单乘法应用时间因子
3. **批量绘图**：预计算所有场景后再开始绘图，减少上下文切换
4. **内存复用**：使用 `__slots__` 或 `numpy` 数组减少内存分配

### 7.2 缓存策略

```
base_risk_data (共享)
    │
    ├─→ Day factor → Day risk
    │       │
    │       ├─→ DRY factor → Day+DRY risk
    │       └─→ RAINY factor → Day+RAINY risk
    │
    └─→ Night factor → Night risk
            │
            ├─→ DRY factor → Night+DRY risk
            └─→ RAINY factor → Night+RAINY risk
```

## 8. 测试设计

### 8.1 单元测试

| 测试用例 | 输入 | 预期输出 |
|:--------|:-----|:---------|
| test_parse_valid_json | 有效 JSON | 正确解析所有字段 |
| test_parse_invalid_json | 无效 JSON | 抛出异常 |
| test_scenario_config | 4 种场景 | 每个场景 hour/season 正确 |
| test_risk_normalization | 任意风险值 | 归一化后范围 [0, 1] |
| test_colorbar_range | 多场景数据 | 颜色尺上界 = max_raw_risk |

### 8.2 集成测试

| 测试用例 | 输入 | 验证点 |
|:--------|:-----|:-------|
| test_full_pipeline | 小地图 JSON | 输出 9 个文件 |
| test_large_map | 大地图 JSON | 性能和内存正常 |
| test_no_temporal_factors | 未启用时间因子 | 自动启用并警告 |

## 9. 文件结构

```
hexdynamic/
├── time_risk_analyzer.py      # 主脚本
├── grid_model.py             # 网格模型（依赖）
├── risk_calculator.py        # 风险计算（依赖）
└── visualize_output.py       # 可视化工具（依赖）
```

## 10. 命令行接口

### 10.1 参数定义

| 参数 | 类型 | 默认值 | 说明 |
|:-----|:-----|:-------|:-----|
| `input` | 位置 | - | 输入 JSON 路径（必填） |
| `-o, --out_dir` | 字符串 | `./time_risk_analysis` | 输出目录 |
| `--dpi` | 整数 | 150 | 图片 DPI |
| `--grid_dpi` | 整数 | None | 每网格像素（None=自动） |
| `--normalized_max` | 浮点数 | None | 归一化图上限（None=1.0） |
| `--no-summary` | 标志 | False | 不生成摘要文件 |

### 10.2 使用示例

```bash
# 基本用法
python time_risk_analyzer.py input.json

# 指定输出目录
python time_risk_analyzer.py input.json -o ./risk_results

# 高清输出
python time_risk_analyzer.py input.json --dpi 200 --grid_dpi 100

# 不生成摘要
python time_risk_analyzer.py input.json --no-summary
```

## 11. 附录：六边形网格风险计算公式

### 11.1 综合风险公式

```
R_grid = ω₁ × H_grid + ω₂ × E_grid + ω₃ × D_grid

其中：
- H_grid = 人为风险 (基于道路、水源、边界距离)
- E_grid = 环境风险 (基于火灾、地形复杂度)
- D_grid = 物种密度风险 (基于所有物种加权密度)
```

### 11.2 时间因子

```
R_time = R_base × temporal_factor

temporal_factor = base_factor × (1 + γ × sin(2π × hour / 24))
    × (season == "RAINY" ? rainy_factor : dry_factor)
```
