# 基于保护收益贡献度的资源移除策略设计文档

## 一、背景与动机

在 DSSA 优化算法的 `repair_solution` 阶段，当资源部署方案违反约束条件时，需要移除部分资源以满足约束。原有的移除策略存在以下问题：

| 场景 | 原有策略 | 问题 |
|------|----------|------|
| 互斥冲突（单格多资源） | 固定优先级：patrol > drone > camera > camp | 优先级与实际保护收益无关，可能移除高贡献资源 |
| 总量超限移除 | 按字典序遍历移除 | 移除顺序随机，无法保证保留最优资源组合 |
| 围栏超限 | 按数量从大到小移除 | 仅考虑数量，未考虑保护效果 |

**核心问题**：原有策略未考虑资源对整体保护收益的贡献差异，可能导致移除高贡献资源、保留低贡献资源，降低整体保护效果。

**优化目标**：按资源对整体保护收益的边际贡献度排序，优先移除贡献度最低的资源，确保在约束条件下保留的资源组合对整体保护收益最大化。

## 二、数学模型

### 2.1 保护收益计算

网格 $i$ 的保护效果 $E_i$ 由四类资源的覆盖度加权组合及协同项计算：

$$E_i = \underbrace{w_p P_i + w_d D_i + w_c C_i + w_f F_i}_{\text{基础贡献}} + \underbrace{\alpha_{pd} \frac{P_i D_i}{1+P_i+D_i} + \alpha_{pc} \frac{P_i C_i}{1+P_i+C_i}}_{\text{协同增益}}$$

其中：
- $P_i$：巡逻覆盖度（patrol coverage）
- $D_i$：无人机覆盖度（drone coverage）
- $C_i$：摄像头覆盖度（camera coverage）
- $F_i$：围栏防护度（fence protection）
- $w_p, w_d, w_c, w_f$：各资源类型的权重
- $\alpha_{pd}, \alpha_{pc}$：协同增益系数

网格 $i$ 的保护收益 $B_i$ 为：

$$B_i = R_i \cdot (1 - e^{-E_i})$$

其中 $R_i$ 为网格 $i$ 的风险指数。

系统总保护收益 $\mathcal{B}$ 为所有网格保护收益的归一化之和：

$$\mathcal{B} = \frac{\sum_i B_i}{\sum_i R_i}$$

### 2.2 边际贡献度定义

资源 $r$ 部署在网格 $g$ 的边际贡献度 $MC(r, g)$ 定义为移除该资源后系统总保护收益的下降量：

$$MC(r, g) = \mathcal{B}(S) - \mathcal{B}(S \setminus \{(r, g)\})$$

其中 $S$ 为当前资源部署方案，$S \setminus \{(r, g)\}$ 为移除资源 $(r, g)$ 后的方案。

**边际贡献度的性质**：
- $MC(r, g) \geq 0$：移除任何资源不会增加总保护收益
- $MC(r, g)$ 越大，该资源对整体保护越重要
- 由于协同增益项的存在，$MC(r, g)$ 不等于该资源的孤立贡献，而是考虑了与其他资源交互后的净贡献

### 2.3 Camp 的联动移除

Camp（营地）是 Ranger（巡逻人员）的载体，移除 Camp 时需联动移除同网格的 Rangers：

$$MC(\text{camp}, g) = \mathcal{B}(S) - \mathcal{B}(S \setminus \{(\text{camp}, g), (\text{ranger}, g)\})$$

这意味着 Camp 的边际贡献度包含了其承载的 Rangers 的贡献，避免低估 Camp 的实际价值。

## 三、算法设计

### 3.1 边际贡献度计算算法

```
算法: _calculate_resource_marginal_contributions(solution)
输入: 当前部署方案 S
输出: 边际贡献度字典 contributions[(资源类型, 网格ID)] → 贡献值

1.  total_benefit ← calculate_total_benefit(S)
2.  contributions ← {}
3.  for each (resource_type, grid_id) in S:
4.      S' ← S 移除 (resource_type, grid_id)
5.      // Camp 联动移除同网格 Rangers
6.      if resource_type == 'camp':
7.          S' ← S' 移除 (ranger, grid_id)
8.      contributions[(resource_type, grid_id)] ← total_benefit - calculate_total_benefit(S')
9.  return contributions
```

**时间复杂度**：$O(N \cdot M)$，其中 $N$ 为资源部署数量，$M$ 为网格数量（每次 `calculate_total_benefit` 的开销）。

### 3.2 基于贡献度的资源移除策略

repair_solution 的完整流程如下：

```
算法: repair_solution(solution, constraints)
输入: 初始部署方案 S，约束条件 C
输出: 修复后的可行方案 S'

阶段1: 清洗无效部署
  - 移除部署矩阵中不可行位置的资源
  - 移除数量为0的资源

阶段2: 互斥冲突解决（贡献度优先）
  - 检测同一网格存在多种资源类型的冲突
  - 计算各冲突资源的边际贡献度
  - 保留贡献度最高的资源类型，移除其余

阶段3: 围栏约束修复
  - 清洗无效围栏部署
  - 超限时按数量从大到小移除

阶段4: 各资源类型总量约束修复（贡献度优先）
  对每种资源类型 (camera, drone, camp, ranger):
    a. 截断单格上限
    b. 若总量超限:
       - 计算该类资源的边际贡献度
       - 按贡献度升序排列
       - 从贡献度最低的开始移除，直到满足约束

阶段5: 资源补充（force_full_deployment 模式）
  - 补充不足的资源至约束上限
```

## 四、关键实现细节

### 4.1 互斥冲突解决

**原有逻辑**：固定优先级 `patrol > drone > camera > camp`，始终保留高优先级资源。

**优化逻辑**：对冲突网格上的每种资源计算边际贡献度，保留贡献度最高的资源类型。

```python
if conflict_grids:
    contributions = self._calculate_resource_marginal_contributions(repaired)
    for grid_id in conflict_grids:
        best_type = argmax_{rtype} contributions[(rtype, grid_id)]
        移除 best_type 以外的所有资源
```

**示例**：网格 5 同时部署了 camera 和 drone
- $MC(\text{camera}, 5) = 0.03$（该位置视野开阔，摄像头覆盖范围大）
- $MC(\text{drone}, 5) = 0.01$（附近已有其他无人机覆盖，冗余）
- 结果：保留 camera，移除 drone

### 4.2 总量超限移除

**原有逻辑**：按字典序遍历，逐个移除直到满足约束。

**优化逻辑**：一次性计算所有同类资源的边际贡献度，按升序排列后依次移除。

```python
if total_cameras > constraints['total_cameras']:
    contributions = self._calculate_resource_marginal_contributions(repaired)
    cam_contribs = [(gid, contributions.get(('camera', gid), 0.0))
                   for gid in repaired.cameras.keys()]
    cam_contribs.sort(key=lambda x: x[1])  # 升序：贡献度最低的排前面
    for gid, _ in cam_contribs:
        if total_cameras <= constraints['total_cameras']:
            break
        移除 grid_id 上的 camera
```

**注意**：当前实现中，边际贡献度在移除开始前一次性计算，后续移除不再重新计算。这是对计算效率的权衡——每次移除后重新计算可得到更精确的排序，但计算开销为 $O(N^2 \cdot M)$。对于 DSSA 算法中频繁调用的 repair_solution，一次性计算是合理的折中。

### 4.3 Camp 联动移除

移除 Camp 时联动移除同网格 Rangers，边际贡献度计算已包含此联动效应：

```python
for gid in solution.camps.keys():
    test_rangers = dict(solution.rangers)
    if gid in test_rangers:
        del test_rangers[gid]  # 联动移除 Rangers
    test = DeploymentSolution(..., rangers=test_rangers, ...)
    contributions[('camp', gid)] = total_benefit - calculate_total_benefit(test)
```

### 4.4 Patrol 的特殊处理

独立巡逻人员（不在 Camp 网格上的 Rangers）单独计算边际贡献度。位于 Camp 网格上的 Rangers 不单独计算，因为它们的贡献已包含在 Camp 的边际贡献度中。

## 五、与原有策略的对比

| 维度 | 原有策略 | 贡献度优先策略 |
|------|----------|----------------|
| 互斥冲突 | 固定优先级，与收益无关 | 按边际贡献度保留最优 |
| 总量超限 | 字典序遍历，随机性强 | 按贡献度升序，优先移除低贡献 |
| Camp 移除 | 未考虑联动 Rangers 的损失 | 边际贡献度包含 Rangers 贡献 |
| 计算开销 | $O(1)$ 每次移除 | $O(N \cdot M)$ 一次性计算 |
| 全局最优性 | 不保证 | 贪心近似，显著优于随机移除 |

## 六、代码位置

| 组件 | 文件 | 说明 |
|------|------|------|
| `_calculate_resource_marginal_contributions` | `hexdynamic/coverage_model.py` | 边际贡献度计算 |
| `repair_solution` | `hexdynamic/coverage_model.py` | 基于贡献度的修复逻辑 |
| `calculate_total_benefit` | `hexdynamic/coverage_model.py` | 总保护收益计算 |
| `calculate_protection_benefit` | `hexdynamic/coverage_model.py` | 单网格保护收益计算 |
| `calculate_protection_effect` | `hexdynamic/coverage_model.py` | 保护效果计算（含协同项） |
