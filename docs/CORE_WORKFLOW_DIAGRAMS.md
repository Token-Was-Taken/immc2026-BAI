# 核心流程图文档

本文档描述了 riskIndex 风险计算模块和 DSSA 优化算法的核心流程。

## 1. riskIndex 风险计算流程

riskIndex 模块负责计算保护区内每个网格的综合风险指数，包括人类活动风险、环境风险和物种密度风险。

### 1.1 核心流程图

```mermaid
flowchart TD
    subgraph Input["输入层"]
        A1[地图配置<br/>map_config.json]
        A2[网格数据<br/>grids: fire_risk, terrain, species]
        A3[时间上下文<br/>hour_of_day, season]
        A4[权重配置<br/>risk_weights, human_risk_weights]
    end

    subgraph DistanceCalc["距离计算模块"]
        B1[DistanceCalculator]
        B2[计算到边界距离<br/>distance_to_boundary]
        B3[计算到道路距离<br/>distance_to_road]
        B4[计算到水源距离<br/>distance_to_water]
    end

    subgraph RiskCalc["风险计算模块"]
        C1[HumanRiskCalculator<br/>人类活动风险]
        C2[EnvironmentalRiskCalculator<br/>环境风险]
        C3[DensityRiskCalculator<br/>物种密度风险]
        C4[CompositeRiskCalculator<br/>综合风险计算]
    end

    subgraph Temporal["时间因子模块"]
        D1[DiurnalFactor<br/>昼夜因子]
        D2[SeasonalFactor<br/>季节因子]
        D3[TemporalFactor<br/>综合时间因子]
    end

    subgraph Output["输出层"]
        E1[原始风险值<br/>raw_risk]
        E2[归一化风险值<br/>normalized_risk]
        E3[风险分量详情<br/>components]
    end

    A1 --> B1
    A2 --> B1
    B1 --> B2
    B1 --> B3
    B1 --> B4

    B2 --> C1
    B3 --> C1
    B4 --> C1
    A2 --> C2
    A2 --> C3

    C1 --> C4
    C2 --> C4
    C3 --> C4
    A4 --> C4

    A3 --> D1
    A3 --> D2
    D1 --> D3
    D2 --> D3

    C4 --> E1
    D3 --> E1
    E1 --> E2
    C4 --> E3
```

### 1.2 风险计算公式

综合风险计算公式：

```
R'_{i,t} = (ω₁·H_{i,t} + ω₂·E_i + ω₃·Σ_s w_s·D_{s,i,t}) × T_t × S_t

R_i = (R'_{i,t} - R_min) / (R_max - R_min)
```

| 符号 | 说明 |
|------|------|
| H_{i,t} | 人类活动风险（边界/道路/水源距离） |
| E_i | 环境风险（火灾风险 + 地形复杂度） |
| D_{s,i,t} | 物种密度风险 |
| T_t | 昼夜因子 |
| S_t | 季节因子 |

### 1.3 主要组件

| 组件 | 文件 | 功能 |
|------|------|------|
| DistanceCalculator | risk_model_wrapper.py | 计算网格到各特征的距离 |
| HumanRiskCalculator | risk_model/risk/human.py | 计算人类活动风险 |
| EnvironmentalRiskCalculator | risk_model/risk/environmental.py | 计算环境风险 |
| DensityRiskCalculator | risk_model/risk/density.py | 计算物种密度风险 |
| CompositeRiskCalculator | risk_model/risk/composite.py | 综合风险计算 |
| RiskModel | risk_model/risk/model.py | 风险模型入口 |

---

## 2. DSSA 优化算法流程

DSSA (Drone Swarm Scheduling Algorithm) 是一种基于麻雀搜索算法的资源部署优化算法，用于优化保护区内的巡逻资源分配。

### 2.1 核心流程图

```mermaid
flowchart TD
    subgraph Input["输入层"]
        A1[网格数据<br/>GridData: q, r, risk, terrain]
        A2[覆盖参数<br/>patrol_radius, drone_radius, camera_radius]
        A3[资源约束<br/>total_patrol, total_cameras, total_drones]
        A4[DSSA配置<br/>population_size, max_iterations, ST]
    end

    subgraph Init["初始化模块"]
        B1[DataLoader<br/>数据加载器]
        B2[HexGridModel<br/>六边形网格模型]
        B3[CoverageModel<br/>覆盖模型]
        B4[初始化种群<br/>population_size个解]
    end

    subgraph DSSA["DSSA优化算法"]
        C1[Producer更新<br/>生产者阶段]
        C2[Follower更新<br/>跟随者阶段]
        C3[Scout更新<br/>侦察者阶段]
        C4[适应度评估<br/>calculate_total_benefit]
        C5[最优解更新<br/>best_solution]
        
        C1 --> C4
        C2 --> C4
        C3 --> C4
        C4 --> C5
        C5 --> C1
    end

    subgraph Coverage["覆盖计算"]
        D1[巡逻覆盖<br/>PatrolCoverage]
        D2[无人机覆盖<br/>DroneCoverage]
        D3[摄像头覆盖<br/>CameraCoverage]
        D4[围栏保护<br/>FenceProtection]
        D5[保护收益<br/>ProtectionBenefit]
    end

    subgraph Output["输出层"]
        E1[最优部署方案<br/>best_solution]
        E2[资源部署统计<br/>cameras, drones, camps, rangers]
        E3[保护收益分布<br/>protection_benefit_per_grid]
        E4[收敛曲线<br/>fitness_history]
    end

    A1 --> B1
    A2 --> B1
    A3 --> B1
    A4 --> B4

    B1 --> B2
    B2 --> B3
    B4 --> C1

    D1 --> D5
    D2 --> D5
    D3 --> D5
    D4 --> D5
    D5 --> C4

    C5 --> E1
    E1 --> E2
    E1 --> E3
    C4 --> E4
```

### 2.2 DSSA 算法参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| population_size | 50 | 种群大小 |
| max_iterations | 100 | 最大迭代次数 |
| producer_ratio | 0.2 | 生产者比例 |
| scout_ratio | 0.2 | 侦察者比例 |
| ST | 0.8 | 安全阈值 |
| R2 | 0.5 | 警戒阈值（已弃用，现动态生成） |

### 2.3 三种角色更新策略

#### Producer（生产者）
- **正常更新 (R2 < ST)**: 向最优解方向移动
- **警戒更新 (R2 >= ST)**: 大范围随机探索

#### Follower（跟随者）
- **正常更新**: 跟随生产者或向最优解移动
- **警戒更新**: 大范围随机探索

#### Scout（侦察者）
- 当适应度低于阈值时，重新初始化

### 2.4 主要组件

| 组件 | 文件 | 功能 |
|------|------|------|
| DSSAOptimizer | dssa_optimizer.py | DSSA优化器主类 |
| DSSAConfig | dssa_optimizer.py | 算法配置 |
| CoverageModel | coverage_model.py | 覆盖模型 |
| VectorizedCoverageModel | coverage_model_vectorized.py | 向量化覆盖模型（大规模地图） |
| HexGridModel | grid_model.py | 六边形网格模型 |
| DataLoader | data_loader.py | 数据加载器 |

---

## 3. Protection Pipeline 完整流程

Protection Pipeline 整合了风险计算和DSSA优化，提供端到端的保护资源优化方案。

### 3.1 完整流程图

```mermaid
flowchart TD
    subgraph Stage1["阶段1: 输入加载"]
        A1[input.json]
        A2[地图配置<br/>map_config]
        A3[网格数据<br/>grids]
        A4[约束条件<br/>constraints]
    end

    subgraph Stage2["阶段2: 风险计算"]
        B1[compute_risk_with_riskindex]
        B2[距离计算<br/>DistanceCalculator]
        B3[风险模型<br/>RiskModel]
        B4[时间因子<br/>TemporalFactor]
        B5[risk_map<br/>temporal_factor_map]
    end

    subgraph Stage3["阶段3: DSSA优化"]
        C1[build_data_loader]
        C2[HexGridModel]
        C3[CoverageModel / VectorizedCoverageModel]
        C4[DSSAOptimizer]
        C5[迭代优化<br/>max_iterations次]
        C6[best_solution]
    end

    subgraph Stage4["阶段4: 结果输出"]
        D1[计算保护收益<br/>protection_benefit]
        D2[计算剩余风险<br/>residual_risk]
        D3[生成统计摘要<br/>summary]
        D4[output.json]
    end

    A1 --> A2
    A1 --> A3
    A1 --> A4

    A2 --> B2
    A3 --> B3
    B2 --> B3
    B4 --> B3
    B3 --> B5

    B5 --> C1
    A4 --> C1
    C1 --> C2
    C2 --> C3
    C3 --> C4
    C4 --> C5
    C5 --> C6

    C6 --> D1
    C6 --> D2
    D1 --> D3
    D2 --> D3
    D3 --> D4
```

### 3.2 使用方式

```bash
# 基本用法
python protection_pipeline.py input.json output.json

# 使用向量化模型（大规模地图）
python protection_pipeline.py input.json output.json --vectorized

# 允许部分部署
python protection_pipeline.py input.json output.json --allow-partial-deployment

# 冻结特定资源
python protection_pipeline.py input.json output.json --freeze-resources patrol,camera
```

### 3.3 输出结果结构

```json
{
  "summary": {
    "total_grids": 120,
    "total_risk": 45.6,
    "best_fitness": 123.45,
    "total_protection_benefit": 89.2,
    "risk_min": 0.1,
    "risk_max": 0.9,
    "residual_risk_mean": 0.35,
    "resources_deployed": {
      "total_cameras": 10,
      "total_drones": 3,
      "total_camps": 5,
      "total_rangers": 20,
      "fence_segments": 15
    }
  },
  "grids": [...],
  "fence_edges": [...]
}
```

---

## 4. 模块依赖关系

```mermaid
graph LR
    subgraph riskIndex
        R1[risk_model_wrapper.py]
        R2[risk_model/core/]
        R3[risk_model/risk/]
        R4[risk_model/config/]
    end

    subgraph hexdynamic
        H1[protection_pipeline.py]
        H2[data_loader.py]
        H3[grid_model.py]
        H4[coverage_model.py]
        H5[dssa_optimizer.py]
    end

    R1 --> R2
    R1 --> R3
    R1 --> R4
    R2 --> R3
    R4 --> R3

    H1 --> R1
    H1 --> H2
    H1 --> H5
    H2 --> H3
    H3 --> H4
    H4 --> H5
```

---

## 5. 参考资料

- [riskIndex README](../riskIndex/README.md)
- [DSSA 设计文档](./DSSA_DESIGN_DOCUMENT.md)
- [快速开始指南](../QUICK_START_GUIDE.md)
