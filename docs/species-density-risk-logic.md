# 风险模型权重参数配置

所有权重参数统一在 input JSON 的 `risk_model_config` 和 `species_config` 中定义，所有字段均可选，缺失时使用代码默认值。

## 1. 综合风险公式

```
R = ω₁·H + ω₂·E + ω₃·D
```

可选乘以时间因子：`R' = R × T_diurnal × T_season`

## 2. 权重参数分组

### 2.1 综合风险权重 (`risk_weights`)

控制三大风险分量的相对重要性，三者之和必须为1。

| 参数 | 含义 | 默认值 |
|------|------|--------|
| `human_weight` | 人为风险权重 ω₁ | 0.4 |
| `environmental_weight` | 环境风险权重 ω₂ | 0.3 |
| `density_weight` | 物种密度权重 ω₃ | 0.3 |

代码位置：`riskIndex/src/risk_model/config/defaults.py`

### 2.2 人为风险权重 (`human_risk_weights`)

控制人为风险内部三个邻近度因子的相对重要性，三者之和必须为1。

| 参数 | 含义 | 默认值 |
|------|------|--------|
| `boundary_weight` | 边界邻近度权重 | 0.2 |
| `road_weight` | 道路邻近度权重 | 0.3 |
| `water_weight` | 水源邻近度权重 | 0.5 |

代码位置：`riskIndex/src/risk_model/risk/human.py`

### 2.3 环境风险权重 (`environmental_risk_weights`)

控制环境风险内部两个因子的相对重要性，两者之和必须为1。

| 参数 | 含义 | 默认值 |
|------|------|--------|
| `fire_weight` | 火灾风险权重 | 0.6 |
| `terrain_weight` | 地形复杂度权重 | 0.4 |

代码位置：`riskIndex/src/risk_model/risk/environmental.py`

### 2.4 时间因子权重 (`temporal_weights`)

控制昼夜和季节对风险的调节幅度。

| 参数 | 含义 | 默认值 |
|------|------|--------|
| `daytime_factor` | 白天风险因子 | 1.0 |
| `nighttime_factor` | 夜间风险因子 | 1.3 |
| `gamma` | 连续模式正弦波振幅 | 0.3 |
| `dry_season_factor` | 旱季风险因子 | 1.0 |
| `rainy_season_factor` | 雨季风险因子 | 1.2 |

代码位置：`riskIndex/src/risk_model/risk/temporal.py`

### 2.5 物种配置 (`species_config`)

每个物种独立配置，key 为物种名称。

| 参数 | 含义 |
|------|------|
| `weight` | 该物种的保护权重 |
| `rainy_season_multiplier` | 雨季密度乘数 |
| `dry_season_multiplier` | 旱季密度乘数 |

默认物种配置：

| 物种 | weight | rainy_season_multiplier | dry_season_multiplier |
|------|--------|------------------------|-----------------------|
| rhino | 0.5 | 1.2 | 1.0 |
| elephant | 0.3 | 1.3 | 0.9 |
| bird | 0.2 | 1.5 | 0.8 |

代码位置：`riskIndex/src/risk_model/risk/density.py`

## 3. JSON 配置示例

以下为包含所有权重参数的完整配置（值均为默认值）：

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
    "rhino": {
      "weight": 0.5,
      "rainy_season_multiplier": 1.2,
      "dry_season_multiplier": 1.0
    },
    "elephant": {
      "weight": 0.3,
      "rainy_season_multiplier": 1.3,
      "dry_season_multiplier": 0.9
    },
    "bird": {
      "weight": 0.2,
      "rainy_season_multiplier": 1.5,
      "dry_season_multiplier": 0.8
    }
  }
}
```

## 4. 物种密度的计算

```
D = Σ_s ( w_s × d_s × m_s(season) )
```

- `w_s`：物种保护权重（`species_config.<name>.weight`）
- `d_s`：该网格中物种的归一化密度 [0, 1]（`grids[].species_densities.<name>`）
- `m_s(season)`：季节乘数（`species_config.<name>.rainy/dry_season_multiplier`）

### 计算示例

假设某网格物种密度为 `rhino=0.6, elephant=0.4, bird=0.8`，雨季：

```
D = 0.5 × 0.6 × 1.2 + 0.3 × 0.4 × 1.3 + 0.2 × 0.8 × 1.5
  = 0.36 + 0.156 + 0.24
  = 0.756
```

## 5. 无物种分布网格的处理

当网格的 `species_densities` 为空字典 `{}` 时：

- `D = 0`（求和项为空）
- 实际风险公式退化为 `R = 0.4·H + 0.3·E + 0.3×0 = 0.4·H + 0.3·E`
- 风险值上限被压低到 **0.7**（即使 H=E=1.0）

这意味着无物种分布的网格，其风险值天然低于有物种分布的网格，密度项的 0.3 权重被"浪费"。

## 6. 数据流向

```
input.json
  ├─ risk_model_config.risk_weights         → ω₁, ω₂, ω₃
  ├─ risk_model_config.human_risk_weights    → 人为风险内部权重
  ├─ risk_model_config.environmental_risk_weights → 环境风险内部权重
  ├─ risk_model_config.temporal_weights      → 昼夜/季节因子
  ├─ species_config                          → 物种权重 + 季节乘数
  └─ grids[].species_densities               → 各网格物种密度
       │
       ▼
  R = ω₁·H + ω₂·E + ω₃·D
       │
       ▼
  归一化 → R_normalized ∈ [0, 1]
```

## 7. 设计意图

- **综合风险权重**：人为风险权重最高（0.4），因为偷猎是保护区主要威胁
- **人为风险权重**：水源邻近度权重最高（0.5），因为偷猎者倾向在水源附近设伏
- **环境风险权重**：火灾风险权重较高（0.6），因为火灾是主要环境威胁
- **时间因子**：夜间因子（1.3）高于白天（1.0），雨季因子（1.2）高于旱季（1.0），反映偷猎活动规律
- **物种密度**：代表保护价值，密度越高的网格越需要监控
