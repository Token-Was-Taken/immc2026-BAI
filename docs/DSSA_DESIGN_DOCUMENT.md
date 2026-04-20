# DSSA 优化器设计文档

## 1. 概述

DSSA (Dynamic Sparrow Search Algorithm) 是一种基于麻雀搜索算法的动态优化方法，用于解决野生动物保护区的资源部署优化问题。该算法通过模拟麻雀群体的觅食行为，在满足约束条件的前提下，最大化保护效益。

### 1.1 问题定义

给定一个六边形网格地图，每个网格具有以下属性：

- 地形类型（SparseGrass、DenseGrass、SaltMarsh、WaterHole、Road）
- 风险值（0-1）
- 时间因子（昼夜 × 季节）

需要部署以下资源：

- 摄像头（Camera）
- 无人机（Drone）
- 营地（Camp）
- 巡逻人员（Patrol/Ranger）
- 围栏（Fence）

目标：在资源约束下最大化保护效益（Protection Benefit）。

***

## 2. 核心数据结构

### 2.1 网格数据 (GridData)

```python
@dataclass
class GridData:
    grid_id: int           # 网格唯一标识
    q: int                 # 六边形轴坐标 q
    r: int                 # 六边形轴坐标 r
    terrain_type: str      # 地形类型
    risk: float            # 风险值 [0, 1]
    temporal_factor: float = 1.0  # 时间因子 T_t × S_t
```

### 2.2 部署解决方案 (DeploymentSolution)

```python
@dataclass
class DeploymentSolution:
    cameras: Dict[int, int]              # grid_id -> 摄像头数量
    camps: Dict[int, int]                # grid_id -> 营地数量
    drones: Dict[int, int]               # grid_id -> 无人机数量
    rangers: Dict[int, int]              # grid_id -> 巡逻人员数量
    fences: Dict[Tuple[int, int], int]   # (grid_id1, grid_id2) -> 围栏长度
```

### 2.3 资源约束 (ResourceConstraints)

```python
@dataclass
class ResourceConstraints:
    total_patrol: int           # 巡逻人员总数
    total_camps: int            # 营地总数
    max_rangers_per_camp: int   # 每个营地最大巡逻人数
    total_cameras: int          # 摄像头总数
    total_drones: int           # 无人机总数
    total_fence_length: float   # 围栏总长度
    # 单格最大部署数量
    max_cameras_per_grid: int = 1
    max_drones_per_grid: int = 1
    max_camps_per_grid: int = 1
    max_rangers_per_grid: int = 1
```

### 2.4 覆盖参数 (CoverageParameters)

```python
@dataclass
class CoverageParameters:
    patrol_radius: float = 5.0      # 巡逻覆盖半径
    drone_radius: float = 8.0       # 无人机覆盖半径
    camera_radius: float = 3.0      # 摄像头覆盖半径
    fence_protection: float = 0.5   # 围栏保护效果
    wp: float = 0.3                 # 巡逻权重
    wd: float = 0.3                 # 无人机权重
    wc: float = 0.2                 # 摄像头权重
    wf: float = 0.2                 # 围栏权重
```

### 2.5 DSSA 配置 (DSSAConfig)

```python
@dataclass
class DSSAConfig:
    population_size: int = 50        # 种群大小
    max_iterations: int = 100        # 最大迭代次数
    producer_ratio: float = 0.2      # 生产者比例
    scout_ratio: float = 0.2         # 侦察者比例
    ST: float = 0.8                  # 安全阈值
    R2: float = 0.5                  # 已弃用：现每次迭代随机生成
    use_time_aware_fitness: bool = False  # 启用时间感知适应度
```

***

## 3. 六边形网格模型 (HexGridModel)

### 3.1 网格坐标系统

使用轴坐标系统 (Axial Coordinates) 表示六边形网格：

```
     / \     / \     / \
   /     \ /     \ /     \
  | -1,0  |  0,0  |  1,0  |
   \     / \     / \     /
     \ /     \ /     \ /
      | -1,1  |  0,1  |
       \     / \     /
         \ /     \ /
          |  0,2  |
           \     /
             \ /
```

### 3.2 核心方法

```python
class HexGridModel:
    def __init__(self, grids: List[GridData]):
        self.grids = grids
        self.grid_dict = {grid.grid_id: grid for grid in grids}
        self.adjacency_matrix = self._build_adjacency_matrix()
        self.distance_matrix = self._build_distance_matrix()
```

#### 3.2.1 邻接矩阵构建

```python
def _build_adjacency_matrix(self) -> Dict[int, List[int]]:
    adjacency = {}
    # 六边形的六个方向
    directions = [
        (1, 0), (1, -1), (0, -1),
        (-1, 0), (-1, 1), (0, 1)
    ]
    
    for grid in self.grids:
        neighbors = []
        for dq, dr in directions:
            neighbor_q = grid.q + dq
            neighbor_r = grid.r + dr
            neighbor_grid = self._find_grid_by_coords(neighbor_q, neighbor_r)
            if neighbor_grid:
                neighbors.append(neighbor_grid.grid_id)
        adjacency[grid.grid_id] = neighbors
    
    return adjacency
```

#### 3.2.2 六边形距离计算

```python
@staticmethod
def hex_distance(grid1: GridData, grid2: GridData) -> int:
    return (abs(grid1.q - grid2.q) + 
            abs(grid1.q + grid1.r - grid2.q - grid2.r) + 
            abs(grid1.r - grid2.r)) // 2
```

#### 3.2.3 边缘网格识别

```python
def get_edge_grids(self) -> List[int]:
    """获取地图边缘的网格ID列表
    
    边缘网格定义：
    1. 邻居数量少于6的网格（边界网格）
    2. 位于矩形地图边界的网格
    """
    edge_grids = []
    
    # 获取网格的行列范围
    rows = set()
    cols = set()
    grid_info = {}
    
    for grid in self.grids:
        row = grid.r
        col = grid.q + (row // 2)
        rows.add(row)
        cols.add(col)
        grid_info[grid.grid_id] = (row, col)
    
    min_row, max_row = min(rows), max(rows)
    min_col, max_col = min(cols), max(cols)
    
    for grid_id, (row, col) in grid_info.items():
        is_edge = False
        
        # 邻居数量少于6
        neighbors = self.get_neighbors(grid_id)
        if len(neighbors) < 6:
            is_edge = True
        
        # 位于矩形地图边界
        if row == min_row or row == max_row or col == min_col or col == max_col:
            is_edge = True
        
        if is_edge:
            edge_grids.append(grid_id)
    
    return sorted(edge_grids)
```

***

## 4. 覆盖模型 (CoverageModel)

### 4.1 覆盖计算原理

每种资源都有其覆盖范围，覆盖强度随距离衰减：

```
coverage(d) = exp(-d / effective_radius)
```

### 4.2 巡逻覆盖计算

```python
def calculate_patrol_coverage(self, solution: DeploymentSolution) -> Dict[int, float]:
    patrol_coverage = {}
    
    for grid_id in self.grid_ids:
        if self.deployment_matrix['patrol'][grid_id] == 0:
            patrol_coverage[grid_id] = 0.0
            continue
        
        patrol_intensity = 0.0
        
        # 从营地出发的巡逻
        for camp_id, camp_value in solution.camps.items():
            if camp_value == 1:
                rangers = solution.rangers.get(camp_id, 0)
                distance = self.grid_model.get_distance(grid_id, camp_id)
                patrol_intensity += rangers * np.exp(-distance / self.params.patrol_radius)
        
        # 独立巡逻点
        for ranger_id, ranger_count in solution.rangers.items():
            if ranger_count > 0 and ranger_id not in solution.camps:
                distance = self.grid_model.get_distance(grid_id, ranger_id)
                patrol_intensity += ranger_count * np.exp(-distance / self.params.patrol_radius)
        
        # 覆盖率 = 1 - exp(-intensity)
        patrol_coverage[grid_id] = 1 - np.exp(-patrol_intensity)
    
    return patrol_coverage
```

### 4.3 无人机覆盖计算

```python
def calculate_drone_coverage(self, solution: DeploymentSolution) -> Dict[int, float]:
    drone_coverage = {}
    
    for grid_id in self.grid_ids:
        visibility = self.visibility_params[grid_id]['drone']
        effective_radius = self.params.drone_radius * visibility
        
        coverage = 0.0
        for drone_id, drone_value in solution.drones.items():
            if drone_value == 1 and self.deployment_matrix['drone'][grid_id] == 1:
                distance = self.grid_model.get_distance(grid_id, drone_id)
                if distance <= effective_radius * 2:
                    coverage += np.exp(-distance / effective_radius)
        
        drone_coverage[grid_id] = min(1.0, coverage)
    
    return drone_coverage
```

### 4.4 摄像头覆盖计算

```python
def calculate_camera_coverage(self, solution: DeploymentSolution) -> Dict[int, float]:
    camera_coverage = {}
    
    for grid_id in self.grid_ids:
        visibility = self.visibility_params[grid_id]['camera']
        effective_radius = self.params.camera_radius * visibility
        
        coverage = 0.0
        for cam_id, cam_count in solution.cameras.items():
            if cam_count > 0 and self.deployment_matrix['camera'][grid_id] == 1:
                distance = self.grid_model.get_distance(grid_id, cam_id)
                if distance <= effective_radius * 2:
                    coverage += cam_count * np.exp(-distance / effective_radius)
        
        camera_coverage[grid_id] = min(1.0, coverage)
    
    return camera_coverage
```

### 4.5 围栏保护计算

```python
def calculate_fence_protection(self, solution: DeploymentSolution) -> Dict[int, float]:
    fence_protection = {}
    
    for grid_id in self.grid_ids:
        protection = 0.0
        neighbors = self.grid_model.get_neighbors(grid_id)
        
        for neighbor_id in neighbors:
            edge_key = tuple(sorted((grid_id, neighbor_id)))
            if edge_key in solution.fences and solution.fences[edge_key] == 1:
                if self.deployment_matrix['fence'][grid_id] == 1:
                    protection += self.params.fence_protection
        
        fence_protection[grid_id] = min(1.0, protection)
    
    return fence_protection
```

### 4.6 保护效果计算

```python
def calculate_protection_effect(self, solution: DeploymentSolution) -> Dict[int, float]:
    patrol_cov = self.calculate_patrol_coverage(solution)
    drone_cov = self.calculate_drone_coverage(solution)
    camera_cov = self.calculate_camera_coverage(solution)
    fence_prot = self.calculate_fence_protection(solution)
    
    protection_effect = {}
    
    for grid_id in self.grid_ids:
        # 加权求和
        E_i = (self.params.wp * patrol_cov[grid_id] +
               self.params.wd * drone_cov[grid_id] +
               self.params.wc * camera_cov[grid_id] +
               self.params.wf * fence_prot[grid_id])
        
        protection_effect[grid_id] = E_i
    
    return protection_effect
```

### 4.7 保护效益计算（适应度函数）

```python
def calculate_protection_benefit(self, solution: DeploymentSolution) -> Dict[int, float]:
    protection_effect = self.calculate_protection_effect(solution)
    protection_benefit = {}
    
    for grid_id in self.grid_ids:
        risk = self.grid_model.get_grid_risk(grid_id)
        E_i = protection_effect[grid_id]
        # 效益 = 风险 × (1 - exp(-保护效果))
        protection_benefit[grid_id] = risk * (1 - np.exp(-E_i))
    
    return protection_benefit

def calculate_total_benefit(self, solution: DeploymentSolution) -> float:
    protection_benefit = self.calculate_protection_benefit(solution)
    total_risk = sum(self.grid_model.get_grid_risk(grid_id) for grid_id in self.grid_ids)
    
    total_benefit = sum(protection_benefit.values())
    if total_risk > 0:
        total_benefit = total_benefit / total_risk  # 归一化
    
    return total_benefit
```

### 4.8 时间感知适应度

```python
def calculate_time_aware_total_benefit(self, solution: DeploymentSolution) -> float:
    """
    使用时间加权风险计算适应度
    
    公式：
        fitness = total_protection_benefit / total_risk_weighted
        where total_risk_weighted = Σ [R_i × T_t × S_t]
    
    效果：资源分配反映时间风险差异
    """
    protection_benefit = self.calculate_protection_benefit(solution)
    total_risk_weighted = 0.0
    
    for grid_id in self.grid_ids:
        normalized_risk = self.grid_model.get_grid_risk(grid_id)
        temporal_factor = self.grid_model.get_grid_temporal_factor(grid_id)
        total_risk_weighted += normalized_risk * temporal_factor
    
    total_benefit = sum(protection_benefit.values())
    if total_risk_weighted > 0:
        total_benefit = total_benefit / total_risk_weighted
    
    return total_benefit
```

***

## 5. DSSA 优化器核心算法

### 5.1 算法流程图

```
┌─────────────────────────────────────────────────────────────┐
│                      DSSA 优化流程                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 初始化种群                                               │
│     ├── 生成 population_size 个随机解决方案                   │
│     └── 评估初始适应度，记录最优解                            │
│                                                             │
│  2. 迭代优化 (max_iterations 次)                             │
│     │                                                       │
│     ├── 2.1 更新生产者 (Producers)                           │
│     │   ├── R2 < ST: 开发模式 - 向最优解靠拢                  │
│     │   └── R2 >= ST: 探索模式 - 大范围随机搜索               │
│     │                                                       │
│     ├── 2.2 更新跟随者 (Followers)                           │
│     │   ├── R2 < ST: 开发模式 - 跟随生产者或最优解            │
│     │   └── R2 >= ST: 探索模式 - 大范围随机搜索               │
│     │                                                       │
│     ├── 2.3 更新侦察者 (Scouts)                              │
│     │   └── 适应度低于阈值的个体重新初始化                    │
│     │                                                       │
│     └── 2.4 更新最优解                                       │
│                                                             │
│  3. 返回最优解                                               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 种群角色划分

```
种群 (population_size = 50)
├── 生产者 (Producers): 前 20% (10个)
│   └── 负责寻找新的食物源
├── 跟随者 (Followers): 中间 60% (30个)
│   └── 跟随生产者觅食
└── 侦察者 (Scouts): 后 20% (10个)
    └── 负责全局探索
```

### 5.3 初始化方法

```python
def _initialize_solution(self) -> DeploymentSolution:
    """初始化解决方案
    
    如果 force_full_deployment=True，强制部署所有资源到上限
    """
    cameras = {}
    camps = {}
    drones = {}
    rangers = {}
    
    grid_ids_shuffled = self.grid_ids.copy()
    random.shuffle(grid_ids_shuffled)
    
    if self.force_full_deployment:
        # 强制部署模式：确保所有资源都部署到上限
        
        # 1. 部署所有摄像头
        max_cam = self.constraints.get('max_cameras_per_grid', 1)
        cam_target = self.constraints['total_cameras']
        cam_deployed = 0
        
        for grid_id in grid_ids_shuffled:
            if cam_deployed >= cam_target:
                break
            if self.coverage_model.deployment_matrix['camera'][grid_id] == 1:
                count = min(max_cam, cam_target - cam_deployed)
                cameras[grid_id] = count
                cam_deployed += count
        
        # 2. 部署所有无人机
        max_drone = self.constraints.get('max_drones_per_grid', 1)
        drone_target = self.constraints['total_drones']
        drone_deployed = 0
        
        for grid_id in grid_ids_shuffled:
            if drone_deployed >= drone_target:
                break
            if self.coverage_model.deployment_matrix['drone'][grid_id] == 1:
                count = min(max_drone, drone_target - drone_deployed)
                drones[grid_id] = count
                drone_deployed += count
        
        # 3. 部署所有营地
        # 4. 部署所有巡逻人员（避免与营地冲突）
        # ... 类似逻辑
    
    solution = DeploymentSolution(
        cameras=cameras,
        camps=camps,
        drones=drones,
        rangers=rangers,
        fences=dict(self.fixed_fences)
    )
    
    return self.coverage_model.repair_solution(solution, self.constraints, self.force_full_deployment)
```

### 5.4 解决方案编码与解码

#### 5.4.1 编码：解决方案 → 向量

```python
def _solution_to_vector(self, solution: DeploymentSolution) -> np.ndarray:
    vector = []
    
    # 摄像头编码
    for grid_id in self.grid_ids:
        vector.append(solution.cameras.get(grid_id, 0))
    
    # 营地编码
    for grid_id in self.grid_ids:
        vector.append(solution.camps.get(grid_id, 0))
    
    # 无人机编码
    for grid_id in self.grid_ids:
        vector.append(solution.drones.get(grid_id, 0))
    
    # 巡逻人员编码
    for grid_id in self.grid_ids:
        vector.append(solution.rangers.get(grid_id, 0))
    
    return np.array(vector)
```

#### 5.4.2 解码：向量 → 解决方案

```python
def _vector_to_solution(self, vector: np.ndarray) -> DeploymentSolution:
    cameras = {}
    camps = {}
    drones = {}
    rangers = {}
    
    idx = 0
    max_cam = self.constraints.get('max_cameras_per_grid', 1)
    
    # 解码摄像头
    for grid_id in self.grid_ids:
        val = int(round(vector[idx]))
        if val > 0 and self.coverage_model.deployment_matrix['camera'][grid_id] == 1:
            cameras[grid_id] = min(val, max_cam)
        idx += 1
    
    # 解码营地
    for grid_id in self.grid_ids:
        if vector[idx] > 0.5 and self.coverage_model.deployment_matrix['camp'][grid_id] == 1:
            camps[grid_id] = 1
        idx += 1
    
    # 解码无人机
    for grid_id in self.grid_ids:
        if vector[idx] > 0.5 and self.coverage_model.deployment_matrix['drone'][grid_id] == 1:
            drones[grid_id] = 1
        idx += 1
    
    # 解码巡逻人员
    for grid_id in self.grid_ids:
        val = int(round(vector[idx]))
        if val > 0 and self.coverage_model.deployment_matrix['patrol'][grid_id] == 1:
            max_ranger = self.constraints.get('max_rangers_per_grid', 1)
            rangers[grid_id] = min(val, max_ranger)
        idx += 1
    
    return DeploymentSolution(
        cameras=cameras,
        camps=camps,
        drones=drones,
        rangers=rangers,
        fences=dict(self.fixed_fences)
    )
```

### 5.5 生产者更新策略

```python
def _update_producers(self, iteration: int):
    num_producers = int(self.config.population_size * self.config.producer_ratio)
    producers = self.population[:num_producers]
    
    escape_count = 0  # 统计警戒更新次数
    
    for i, solution in enumerate(producers):
        # R2 在每次迭代中随机生成 [0, 1]
        R2 = random.uniform(0, 1)
        
        if R2 < self.config.ST:
            # 正常更新（开发 / exploitation）
            if i == 0:
                # 最优生产者向全局最优靠拢
                current_vector = self._solution_to_vector(solution)
                best_vector = self._solution_to_vector(self.best_solution)
                new_vector = current_vector + np.random.uniform(0, 1, current_vector.shape) * (best_vector - current_vector)
            else:
                # 其他生产者小范围搜索
                current_vector = self._solution_to_vector(solution)
                new_vector = current_vector + np.random.uniform(-1, 1, current_vector.shape)
        else:
            # 警戒更新（探索 / exploration）
            escape_count += 1
            current_vector = self._solution_to_vector(solution)
            # 使用更大的随机扰动进行探索
            new_vector = current_vector + np.random.uniform(-2, 2, current_vector.shape)
        
        # 解码并修复
        new_solution = self.coverage_model.repair_solution(
            self._vector_to_solution(new_vector),
            self.constraints,
            self.force_full_deployment
        )
        
        # 应用冻结资源
        new_solution = self._apply_frozen_resources(new_solution)
        
        # 贪婪选择
        if self.evaluate_fitness(new_solution) > self.evaluate_fitness(solution):
            self.population[i] = new_solution
    
    return escape_count
```

### 5.6 跟随者更新策略

```python
def _update_followers(self):
    num_producers = int(self.config.population_size * self.config.producer_ratio)
    num_followers = int(self.config.population_size * (1 - self.config.producer_ratio))
    followers = self.population[num_producers:num_producers + num_followers]
    
    escape_count = 0
    
    for i, solution in enumerate(followers):
        R2 = random.uniform(0, 1)
        
        if R2 < self.config.ST:
            # 正常更新（开发 / exploitation）
            if i > self.config.population_size / 2:
                # 后半部分跟随者向最优解靠拢
                current_vector = self._solution_to_vector(solution)
                best_vector = self._solution_to_vector(self.best_solution)
                new_vector = np.abs(best_vector - current_vector) * np.random.uniform(0, 1, current_vector.shape)
            else:
                # 前半部分跟随者随机选择一个生产者跟随
                idx = random.randint(0, num_producers - 1)
                producer = self.population[idx]
                current_vector = self._solution_to_vector(solution)
                producer_vector = self._solution_to_vector(producer)
                new_vector = current_vector + np.random.uniform(0, 1, current_vector.shape) * (producer_vector - current_vector)
        else:
            # 警戒更新（探索 / exploration）
            escape_count += 1
            current_vector = self._solution_to_vector(solution)
            new_vector = current_vector + np.random.uniform(-2, 2, current_vector.shape)
        
        new_solution = self.coverage_model.repair_solution(
            self._vector_to_solution(new_vector),
            self.constraints,
            self.force_full_deployment
        )
        
        new_solution = self._apply_frozen_resources(new_solution)
        
        if self.evaluate_fitness(new_solution) > self.evaluate_fitness(solution):
            self.population[num_producers + i] = new_solution
    
    return escape_count
```

### 5.7 侦察者更新策略

```python
def _update_scouts(self):
    num_scouts = int(self.config.population_size * self.config.scout_ratio)
    start_idx = self.config.population_size - num_scouts
    
    for i in range(start_idx, self.config.population_size):
        solution = self.population[i]
        # 适应度低于阈值的个体重新初始化
        if self.evaluate_fitness(solution) < self.config.ST * self.best_fitness:
            self.population[i] = self._initialize_solution()
```

### 5.8 主优化循环

```python
def optimize(self, callback: Callable[[int, float, DeploymentSolution], None] = None) -> Tuple[DeploymentSolution, float, List[float]]:
    import time
    
    # 1. 初始化种群
    self.initialize_population()
    
    # 保存初始解决方案（用于冻结资源）
    self.initial_solution = self._initialize_solution()
    
    # 2. 评估初始适应度
    for solution in self.population:
        fitness = self.evaluate_fitness(solution)
        if fitness > self.best_fitness:
            self.best_fitness = fitness
            self.best_solution = solution
    
    self.fitness_history = [self.best_fitness]
    
    total_start = time.time()
    iter_times = []
    
    # 3. 迭代优化
    for iteration in range(self.config.max_iterations):
        iter_start = time.time()
        
        # 3.1 更新三个群体
        escape_producers = self._update_producers(iteration)
        escape_followers = self._update_followers()
        self._update_scouts()
        
        # 3.2 更新最优解
        self._update_best_solution()
        
        # 3.3 计算当前效益
        pb_per_grid = self.coverage_model.calculate_protection_benefit(self.best_solution)
        total_benefit = sum(pb_per_grid.values())
        
        iter_elapsed = time.time() - iter_start
        iter_times.append(iter_elapsed)
        self.fitness_history.append(self.best_fitness)
        
        # 3.4 回调
        if callback:
            callback(iteration, self.best_fitness, self.best_solution)
        
        # 3.5 打印进度
        escape_total = escape_producers + escape_followers
        if escape_total > 0:
            print(f"Iter {iteration+1:>4}/{self.config.max_iterations}"
                  f"  fitness={self.best_fitness:.6f}"
                  f"  benefit={total_benefit:.6f}"
                  f"  [ESCAPE={escape_total}]")
        else:
            print(f"Iter {iteration+1:>4}/{self.config.max_iterations}"
                  f"  fitness={self.best_fitness:.6f}"
                  f"  benefit={total_benefit:.6f}")
    
    # 4. 返回结果
    total_elapsed = time.time() - total_start
    print(f"\nOptimization completed."
          f"  Best Fitness = {self.best_fitness:.6f}"
          f"  Total Time = {total_elapsed:.2f}s")
    
    return self.best_solution, self.best_fitness, self.fitness_history
```

***

## 6. 约束处理与修复机制

### 6.1 解决方案验证

```python
def validate_solution(self, solution: DeploymentSolution,
                      constraints: Dict[str, any]) -> Tuple[bool, List[str]]:
    violations = []
    
    # 1. 检查资源总量约束
    total_cameras = sum(solution.cameras.values())
    if total_cameras > constraints['total_cameras']:
        violations.append(f"Camera limit exceeded: {total_cameras} > {constraints['total_cameras']}")
    
    total_drones = sum(solution.drones.values())
    if total_drones > constraints['total_drones']:
        violations.append(f"Drone limit exceeded: {total_drones} > {constraints['total_drones']}")
    
    total_camps = sum(solution.camps.values())
    if total_camps > constraints['total_camps']:
        violations.append(f"Camp limit exceeded: {total_camps} > {constraints['total_camps']}")
    
    total_rangers = sum(solution.rangers.values())
    if total_rangers > constraints['total_patrol']:
        violations.append(f"Patrol limit exceeded: {total_rangers} > {constraints['total_patrol']}")
    
    # 2. 检查营地与巡逻人员冲突
    for grid_id in self.grid_ids:
        has_camp = solution.camps.get(grid_id, 0) > 0
        has_ranger = solution.rangers.get(grid_id, 0) > 0
        if has_camp and has_ranger:
            violations.append(f"Patrol and camp cannot share the same grid: {grid_id}")
    
    # 3. 检查部署可行性
    for grid_id in self.grid_ids:
        cam_count = solution.cameras.get(grid_id, 0)
        max_cam = constraints.get('max_cameras_per_grid', 1)
        if cam_count > self.deployment_matrix['camera'][grid_id] * max_cam:
            violations.append(f"Camera deployment infeasible at grid {grid_id}")
        
        if solution.camps.get(grid_id, 0) > self.deployment_matrix['camp'][grid_id]:
            violations.append(f"Camp deployment infeasible at grid {grid_id}")
        
        if solution.drones.get(grid_id, 0) > self.deployment_matrix['drone'][grid_id]:
            violations.append(f"Drone deployment infeasible at grid {grid_id}")
    
    # 4. 检查围栏部署
    for edge_key, fence_count in solution.fences.items():
        if fence_count <= 0:
            continue
        gid1, gid2 = edge_key
        if (self.deployment_matrix['fence'].get(gid1, 0) != 1 or
                self.deployment_matrix['fence'].get(gid2, 0) != 1):
            violations.append(f"Fence deployment infeasible at edge {edge_key}")
    
    return (len(violations) == 0, violations)
```

### 6.2 解决方案修复

```python
def repair_solution(self, solution: DeploymentSolution,
                   constraints: Dict[str, any],
                   force_full_deployment: bool = True) -> DeploymentSolution:
    # 1. 清理无效部署
    cleaned_cameras = {k: v for k, v in solution.cameras.items()
                       if v > 0 and self.deployment_matrix['camera'].get(k, 0) == 1}
    cleaned_camps = {k: v for k, v in solution.camps.items()
                     if v > 0 and self.deployment_matrix['camp'].get(k, 0) == 1}
    cleaned_drones = {k: v for k, v in solution.drones.items()
                      if v > 0 and self.deployment_matrix['drone'].get(k, 0) == 1}
    cleaned_rangers = {k: v for k, v in solution.rangers.items()
                       if v > 0 and self.deployment_matrix['patrol'].get(k, 0) == 1}
    cleaned_fences = {k: v for k, v in solution.fences.items() if v > 0}
    
    repaired = DeploymentSolution(
        cameras=cleaned_cameras,
        camps=cleaned_camps,
        drones=cleaned_drones,
        rangers=cleaned_rangers,
        fences=cleaned_fences
    )
    
    # 2. 移除不可行的部署
    for grid_id in self.grid_ids:
        if repaired.cameras.get(grid_id, 0) > self.deployment_matrix['camera'][grid_id]:
            repaired.cameras.pop(grid_id, None)
        
        if repaired.camps.get(grid_id, 0) > self.deployment_matrix['camp'][grid_id]:
            repaired.camps.pop(grid_id, None)
            repaired.rangers.pop(grid_id, None)
        
        if repaired.drones.get(grid_id, 0) > self.deployment_matrix['drone'][grid_id]:
            repaired.drones.pop(grid_id, None)
    
    # 3. 确保巡逻和营地不在同一网格
    for grid_id in list(repaired.rangers.keys()):
        if grid_id in repaired.camps:
            repaired.rangers.pop(grid_id, None)
    
    # 4. 截断超出约束的资源
    # 摄像头
    max_cam = constraints.get('max_cameras_per_grid', 1)
    for grid_id in list(repaired.cameras.keys()):
        if repaired.cameras[grid_id] > max_cam:
            repaired.cameras[grid_id] = max_cam
    
    total_cameras = sum(repaired.cameras.values())
    while total_cameras > constraints['total_cameras']:
        for grid_id in list(repaired.cameras.keys()):
            repaired.cameras[grid_id] -= 1
            if repaired.cameras[grid_id] <= 0:
                del repaired.cameras[grid_id]
            total_cameras -= 1
            if total_cameras <= constraints['total_cameras']:
                break
    
    # 无人机、营地、巡逻人员类似处理...
    
    # 5. 如果启用强制部署模式，补充不足的资源
    if force_full_deployment:
        import random
        
        # 补充摄像头
        total_cameras = sum(repaired.cameras.values())
        if total_cameras < constraints['total_cameras']:
            available_grids = [gid for gid in self.grid_ids 
                              if self.deployment_matrix['camera'][gid] == 1]
            random.shuffle(available_grids)
            max_cam = constraints.get('max_cameras_per_grid', 1)
            
            for grid_id in available_grids:
                if total_cameras >= constraints['total_cameras']:
                    break
                current = repaired.cameras.get(grid_id, 0)
                can_add = min(max_cam - current, constraints['total_cameras'] - total_cameras)
                if can_add > 0:
                    repaired.cameras[grid_id] = current + can_add
                    total_cameras += can_add
        
        # 补充无人机、营地、巡逻人员类似处理...
    
    return repaired
```

***

## 7. 冻结资源机制

冻结资源用于敏感性分析，保持某些资源部署不变，只优化其他资源。

```python
def _apply_frozen_resources(self, solution: DeploymentSolution) -> DeploymentSolution:
    """应用冻结资源：将冻结的资源替换为初始解决方案中的值"""
    if not self.frozen_resources or not self.initial_solution:
        return solution
    
    if 'patrol' in self.frozen_resources:
        solution.rangers = dict(self.initial_solution.rangers)
    if 'camera' in self.frozen_resources:
        solution.cameras = dict(self.initial_solution.cameras)
    if 'drone' in self.frozen_resources:
        solution.drones = dict(self.initial_solution.drones)
    if 'camp' in self.frozen_resources:
        solution.camps = dict(self.initial_solution.camps)
    if 'fence' in self.frozen_resources:
        solution.fences = dict(self.initial_solution.fences)
    
    return solution
```

***

## 8. 地形部署规则

### 8.1 地形类型与资源兼容性

| 地形类型        | 巡逻 | 营地 | 无人机 | 摄像头 | 围栏 |
| ----------- | -- | -- | --- | --- | -- |
| SaltMarsh   | ❌  | ❌  | ✅   | ❌   | ❌  |
| SparseGrass | ✅  | ❌  | ✅   | ✅   | ✅  |
| DenseGrass  | ❌  | ❌  | ✅   | ❌   | ✅  |
| WaterHole   | ❌  | ❌  | ✅   | ❌   | ❌  |
| Road        | ✅  | ✅  | ✅   | ✅   | ✅  |

### 8.2 地形可见性参数

可见性参数（Visibility）用于模拟地形对无人机和摄像头视野的影响，通过调整有效覆盖半径来体现。

#### 8.2.1 参数取值

| 地形类型 | 无人机可见性 | 摄像头可见性 | 说明 |
|---------|------------|------------|------|
| SparseGrass | 1.0 | 1.0 | 稀疏草地，视野完全无遮挡 |
| DenseGrass | 0.7 | 0.5 | 茂密草地，视野受限（摄像头受影响更大） |
| SaltMarsh | 0.9 | 0.6 | 盐沼地，略有遮挡 |
| WaterHole | 1.0 | 0.8 | 水源地，无人机视野好，摄像头略有遮挡 |
| Road | 1.0 | 1.0 | 道路，视野完全无遮挡 |

#### 8.2.2 使用方式

在覆盖计算中，visibility 参数用于调整有效覆盖半径：

```python
# 无人机覆盖计算
visibility = self.visibility_params[grid_id]['drone']
effective_radius = self.params.drone_radius * visibility

# 摄像头覆盖计算
visibility = self.visibility_params[grid_id]['camera']
effective_radius = self.params.camera_radius * visibility
```

**公式**：`effective_radius = base_radius × visibility`

#### 8.2.3 实际影响示例

假设基础参数：
- `drone_radius = 8.0`
- `camera_radius = 3.0`

| 地形类型 | 无人机有效半径 | 摄像头有效半径 |
|---------|--------------|--------------|
| SparseGrass | 8.0 × 1.0 = 8.0 | 3.0 × 1.0 = 3.0 |
| DenseGrass | 8.0 × 0.7 = 5.6 | 3.0 × 0.5 = 1.5 |
| SaltMarsh | 8.0 × 0.9 = 7.2 | 3.0 × 0.6 = 1.8 |
| WaterHole | 8.0 × 1.0 = 8.0 | 3.0 × 0.8 = 2.4 |
| Road | 8.0 × 1.0 = 8.0 | 3.0 × 1.0 = 3.0 |

#### 8.2.4 设计意图

这个设计模拟了真实世界中地形对视野的影响：

1. **茂密植被遮挡**：DenseGrass 对摄像头影响更大（0.5 vs 0.7），因为：
   - 无人机飞行高度较高，受植被遮挡影响较小
   - 摄像头固定在地面，受植被遮挡影响更大

2. **开阔地带视野最佳**：SparseGrass 和 Road 的 visibility = 1.0，表示无遮挡

3. **水源地特性**：WaterHole 对无人机无遮挡（1.0），但对摄像头有轻微遮挡（0.8）

#### 8.2.5 初始化代码

```python
def initialize_visibility_params(self):
    terrain_visibility = {
        'SparseGrass': {'drone': 1.0, 'camera': 1.0},
        'DenseGrass':  {'drone': 0.7, 'camera': 0.5},
        'SaltMarsh':   {'drone': 0.9, 'camera': 0.6},
        'WaterHole':   {'drone': 1.0, 'camera': 0.8},
        'Road':        {'drone': 1.0, 'camera': 1.0}
    }

    self.visibility_params = {}
    for grid in self.grids:
        self.visibility_params[grid.grid_id] = terrain_visibility[grid.terrain_type]
```

***

## 9. 使用示例

### 9.1 基本使用

```python
from data_loader import DataLoader
from grid_model import HexGridModel
from coverage_model import CoverageModel
from dssa_optimizer import DSSAOptimizer, DSSAConfig

# 1. 加载数据
loader = DataLoader()
loader.generate_rectangular_hex_grid(width=12, height=10)
loader.set_terrain_types(terrain_map)
loader.set_risk_values(risk_map)
loader.initialize_deployment_matrix(edge_grids=loader.get_edge_grids())
loader.initialize_visibility_params()

# 2. 设置约束
loader.set_constraints(
    total_patrol=20,
    total_camps=5,
    max_rangers_per_camp=5,
    total_cameras=10,
    total_drones=3,
    total_fence_length=50.0
)

# 3. 设置覆盖参数
loader.set_coverage_parameters(
    patrol_radius=5.0,
    drone_radius=8.0,
    camera_radius=3.0,
    fence_protection=0.5
)

# 4. 构建模型
grid_model = HexGridModel(loader.grids)
coverage_model = CoverageModel(
    grid_model=grid_model,
    coverage_params=loader.coverage_params,
    deployment_matrix=loader.deployment_matrix,
    visibility_params=loader.visibility_params
)

# 5. 配置优化器
config = DSSAConfig(
    population_size=50,
    max_iterations=100,
    producer_ratio=0.2,
    scout_ratio=0.2,
    ST=0.8
)

# 6. 运行优化
optimizer = DSSAOptimizer(
    coverage_model=coverage_model,
    constraints=vars(loader.constraints),
    config=config,
    force_full_deployment=True
)

best_solution, best_fitness, history = optimizer.optimize()

# 7. 获取统计信息
stats = optimizer.get_solution_statistics(best_solution)
print(f"Total cameras: {stats['total_cameras']}")
print(f"Total drones: {stats['total_drones']}")
print(f"Total camps: {stats['total_camps']}")
print(f"Total rangers: {stats['total_rangers']}")
```

### 9.2 时间感知优化

```python
# 启用时间感知适应度
config = DSSAConfig(
    population_size=50,
    max_iterations=100,
    use_time_aware_fitness=True  # 启用时间感知
)

# 设置时间因子（昼夜 × 季节）
for grid in loader.grids:
    # 例如：夜间雨季风险更高
    grid.temporal_factor = 1.3  # T_t × S_t
```

### 9.3 敏感性分析（冻结资源）

```python
# 冻结巡逻人员部署，优化其他资源
optimizer = DSSAOptimizer(
    coverage_model=coverage_model,
    constraints=vars(loader.constraints),
    config=config,
    frozen_resources=['patrol']  # 冻结巡逻人员
)

# 先运行一次获取基准部署
baseline_solution, _, _ = optimizer.optimize()

# 再次运行时，巡逻人员部署保持不变
optimizer.frozen_resources = ['patrol']
optimizer.initial_solution = baseline_solution
new_solution, _, _ = optimizer.optimize()
```

***

## 10. 算法参数调优建议

### 10.1 种群大小 (population\_size)

- 小规模问题（<100网格）：30-50
- 中等规模（100-500网格）：50-100
- 大规模问题（>500网格）：100-200

### 10.2 迭代次数 (max\_iterations)

- 快速测试：50-100
- 正常优化：100-200
- 高精度优化：200-500

### 10.3 安全阈值 (ST)

- ST = 0.8（默认）：平衡开发与探索
- ST < 0.7：偏向探索，适合多峰问题
- ST > 0.9：偏向开发，适合单峰问题

### 10.4 生产者/侦察者比例

- producer\_ratio = 0.2（默认）：20%生产者
- scout\_ratio = 0.2（默认）：20%侦察者
- 剩余60%为跟随者

***

## 11. 性能优化

### 11.1 向量化计算

对于大规模问题，可使用向量化版本的覆盖模型：

```python
from coverage_model_vectorized import CoverageModelVectorized

coverage_model = CoverageModelVectorized(
    grid_model=grid_model,
    coverage_params=loader.coverage_params,
    deployment_matrix=loader.deployment_matrix,
    visibility_params=loader.visibility_params
)
```

### 11.2 并行处理

对于多场景分析，可使用并行处理：

```python
from find_deployment import run_pipeline_parallel

tasks = [
    {'input_path': 'input1.json', 'output_path': 'output1.json'},
    {'input_path': 'input2.json', 'output_path': 'output2.json'},
]

results = run_pipeline_parallel(tasks, vectorized=True)
```

***

## 12. 输出结果说明

### 12.1 解决方案统计

```python
stats = optimizer.get_solution_statistics(best_solution)
# 返回：
{
    'total_cameras': 10,
    'total_drones': 3,
    'total_camps': 5,
    'total_rangers': 20,
    'total_fence_length': 50.0,
    'camera_locations': [1, 5, 10, ...],
    'drone_locations': [3, 7, 12],
    'ranger_locations': [2, 4, 6, ...],
    'camp_locations': [8, 15, 22, 30, 35],
    'fence_edges': [(1, 2), (3, 4), ...]
}
```

### 12.2 适应度历史

```python
fitness_history = optimizer.fitness_history
# 返回每代最优适应度列表
# [0.45, 0.52, 0.58, ..., 0.85]
```

### 12.3 保护效益分布

```python
pb_per_grid = coverage_model.calculate_protection_benefit(best_solution)
# 返回每个网格的保护效益
# {0: 0.12, 1: 0.25, 2: 0.08, ...}
```

***

## 13. 数学公式汇总

### 13.1 覆盖强度

$$C\_i^{patrol} = 1 - \exp\left(-\sum\_{j \in camps} r\_j \cdot \exp\left(-\frac{d\_{ij}}{R\_p}\right)\right)$$

$$C\_i^{drone} = \min\left(1, \sum\_{j \in drones} \exp\left(-\frac{d\_{ij}}{R\_d \cdot v\_i^{drone}}\right)\right)$$

$$C\_i^{camera} = \min\left(1, \sum\_{j \in cameras} n\_j \cdot \exp\left(-\frac{d\_{ij}}{R\_c \cdot v\_i^{camera}}\right)\right)$$

### 13.2 保护效果

$$E\_i = w\_p \cdot C\_i^{patrol} + w\_d \cdot C\_i^{drone} + w\_c \cdot C\_i^{camera} + w\_f \cdot F\_i$$

### 13.3 保护效益（适应度）

$$B\_i = R\_i \cdot (1 - \exp(-E\_i))$$

$$Fitness = \frac{\sum\_i B\_i}{\sum\_i R\_i}$$

### 13.4 时间感知适应度

$$Fitness\_{temporal} = \frac{\sum\_i B\_i}{\sum\_i R\_i \cdot T\_t \cdot S\_t}$$

***

## 14. 文件结构

```
hexdynamic/
├── data_loader.py          # 数据加载与初始化
├── grid_model.py           # 六边形网格模型
├── coverage_model.py       # 覆盖模型
├── coverage_model_vectorized.py  # 向量化覆盖模型
├── dssa_optimizer.py       # DSSA优化器
├── visualization.py        # 可视化工具
├── main.py                 # 主入口
└── run.py                  # 运行脚本
```

***

## 15. 参考文献

1. Xue, J., & Shen, B. (2020). A novel swarm intelligence optimization approach: sparrow search algorithm. Systems Science & Control Engineering, 8(1), 22-34.
2. Ouyang, X., et al. (2021). Dynamic sparrow search algorithm with multiple search strategies for global optimization problems. Mathematics, 9(24), 3193.

***

## 16. 扩展功能

### 16.1 强制部署模式

当 `force_full_deployment=True` 时，优化器确保所有资源都部署到约束上限：

```python
optimizer = DSSAOptimizer(
    coverage_model=coverage_model,
    constraints=constraints,
    config=config,
    force_full_deployment=True  # 强制部署所有资源
)
```

**实现逻辑**：

1. 初始化时，遍历所有可用网格，部署资源直到达到上限
2. 修复阶段，如果资源不足，自动补充到上限
3. 确保每次迭代后的解决方案都满足资源总量约束

### 16.2 固定围栏

可以预设固定围栏位置，优化过程中保持不变：

```python
fixed_fences = {
    (1, 2): 1,  # 在网格1和2之间部署围栏
    (3, 4): 1,  # 在网格3和4之间部署围栏
}

optimizer = DSSAOptimizer(
    coverage_model=coverage_model,
    constraints=constraints,
    config=config,
    fixed_fences=fixed_fences
)
```

### 16.3 围栏部署约束

围栏只能部署在地图边缘，通过 `get_fencing_edges()` 方法获取可部署的边：

```python
def get_fencing_edges(self) -> List[Tuple[int, int, float]]:
    """只返回至少一端是边缘格子的边，确保围栏只能部署在地图外围。"""
    edge_grid_set = set(self.get_edge_grids())
    fencing_edges = []
    for grid_id in self.get_all_grid_ids():
        for neighbor_id in self.get_neighbors(grid_id):
            if grid_id < neighbor_id:
                if grid_id in edge_grid_set or neighbor_id in edge_grid_set:
                    fencing_edges.append((grid_id, neighbor_id, 1.0))
    return fencing_edges
```

### 16.4 营地与巡逻人员互斥约束

同一网格不能同时部署营地和独立巡逻人员：

```python
# 验证阶段检查
for grid_id in self.grid_ids:
    has_camp = solution.camps.get(grid_id, 0) > 0
    has_ranger = solution.rangers.get(grid_id, 0) > 0
    if has_camp and has_ranger:
        violations.append(f"Patrol and camp cannot share the same grid: {grid_id}")

# 修复阶段处理
for grid_id in list(repaired.rangers.keys()):
    if grid_id in repaired.camps:
        repaired.rangers.pop(grid_id, None)
```

***

## 17. 算法收敛性分析

### 17.1 收敛特征

DSSA算法具有以下收敛特征：

1. **快速收敛阶段**（前20%迭代）：适应度快速提升
2. **平稳优化阶段**（中间60%迭代）：适应度稳步提升
3. **精细调整阶段**（后20%迭代）：适应度趋于稳定

### 17.2 警戒机制的作用

警戒更新（R2 >= ST）提供探索能力：

- 当 R2 < ST：执行开发操作，向最优解靠拢
- 当 R2 >= ST：执行探索操作，大范围随机搜索

```python
if R2 < self.config.ST:
    # 开发模式：小范围搜索
    new_vector = current_vector + np.random.uniform(-1, 1, current_vector.shape)
else:
    # 探索模式：大范围搜索
    new_vector = current_vector + np.random.uniform(-2, 2, current_vector.shape)
```

### 17.3 侦察者重初始化

适应度低于阈值的个体被重新初始化，避免陷入局部最优：

```python
if self.evaluate_fitness(solution) < self.config.ST * self.best_fitness:
    self.population[i] = self._initialize_solution()
```

***

## 18. 六边形网格坐标系统详解

### 18.1 轴坐标系统

使用轴坐标 (q, r) 表示六边形位置，其中 s = -q - r：

```
     / \\     / \\     / \\
   /     \\ /     \\ /     \\
  | -1,0  |  0,0  |  1,0  |
   \\     / \\     / \\     /
     \\ /     \\ /     \\ /
      | -1,1  |  0,1  |
       \\     / \\     /
         \\ /     \\ /
          |  0,2  |
           \\     /
             \\ /
```

### 18.2 六边形距离公式

```python
@staticmethod
def hex_distance(grid1: GridData, grid2: GridData) -> int:
    return (abs(grid1.q - grid2.q) + 
            abs(grid1.q + grid1.r - grid2.q - grid2.r) + 
            abs(grid1.r - grid2.r)) // 2
```

### 18.3 邻接方向

六边形有六个相邻方向：

```python
directions = [
    (1, 0), (1, -1), (0, -1),   # 右上、右、右下
    (-1, 0), (-1, 1), (0, 1)    # 左下、左、左上
]
```

### 18.4 笛卡尔坐标转换

从轴坐标转换为笛卡尔坐标（用于可视化）：

```python
def get_grid_center_coords(self, grid_id: int, hex_size: float = 1.0) -> Tuple[float, float]:
    grid = self.get_grid_by_id(grid_id)
    col = grid.q + (grid.r // 2)
    row = grid.r
    
    # pointy-topped 六边形
    x = hex_size * np.sqrt(3) * (col + 0.5 * (row & 1))
    y = hex_size * 3/2 * row
    return (x, y)
```

***

## 19. 时间因子计算

### 19.1 时间因子组成

时间因子由昼夜因子和季节因子组成：

```
temporal_factor = T_t × S_t
```

其中：

- T\_t：昼夜因子（白天=1.0，夜间=1.3）
- S\_t：季节因子（旱季=1.0，雨季=1.2）

### 19.2 时间感知适应度

```python
def calculate_time_aware_total_benefit(self, solution: DeploymentSolution) -> float:
    """
    使用时间加权风险计算适应度
    
    公式：
        fitness = total_protection_benefit / total_risk_weighted
        where total_risk_weighted = Σ [R_i × T_t × S_t]
    
    效果：资源分配反映时间风险差异
    """
    protection_benefit = self.calculate_protection_benefit(solution)
    total_risk_weighted = 0.0
    
    for grid_id in self.grid_ids:
        normalized_risk = self.grid_model.get_grid_risk(grid_id)
        temporal_factor = self.grid_model.get_grid_temporal_factor(grid_id)
        total_risk_weighted += normalized_risk * temporal_factor
    
    total_benefit = sum(protection_benefit.values())
    if total_risk_weighted > 0:
        total_benefit = total_benefit / total_risk_weighted
    
    return total_benefit
```

***

## 20. 常见问题与解决方案

### 20.1 资源未完全部署

**问题**：优化结果中某些资源未达到约束上限

**解决方案**：启用强制部署模式

```python
optimizer = DSSAOptimizer(
    coverage_model=coverage_model,
    constraints=constraints,
    config=config,
    force_full_deployment=True
)
```

### 20.2 适应度不收敛

**问题**：迭代过程中适应度波动较大

**解决方案**：

1. 增加种群大小（population\_size）
2. 增加迭代次数（max\_iterations）
3. 调整安全阈值（ST=0.8\~0.9）

### 20.3 围栏部署位置错误

**问题**：围栏出现在地图内部

**解决方案**：确保使用 `get_fencing_edges()` 获取可部署边

```python
fencing_edges = grid_model.get_fencing_edges()
```

### 20.4 营地与巡逻冲突

**问题**：同一网格同时出现营地和巡逻人员

**解决方案**：使用 `repair_solution()` 自动修复

```python
repaired = coverage_model.repair_solution(solution, constraints, force_full_deployment)
```

***

## 21. 复杂度分析

### 21.1 符号定义

| 符号 | 含义 | 典型值 |
|------|------|--------|
| N | 网格总数 | 2648 |
| P | 种群大小 (population_size) | 50 |
| I | 最大迭代次数 (max_iterations) | 100 |
| C_cam | 摄像头总数 | 4 |
| C_drone | 无人机总数 | 2 |
| C_camp | 营地总数 | 2 |
| C_ranger | 巡逻人员总数 | 8 |
| k | 每个网格平均邻居数 (≤6) | 6 |
| d | 解向量维度 = 4N | 10592 |

### 21.2 预处理阶段

#### 21.2.1 邻接矩阵构建

```python
def _build_adjacency_matrix(self):
    for grid in self.grids:          # N 次
        for dq, dr in directions:    # 6 次
            neighbor_grid = self._find_grid_by_coords(...)  # O(N) 线性查找
```

- **时间复杂度**: O(N² × 6) = O(N²)
- **空间复杂度**: O(N × k) = O(N)（每个网格最多6个邻居）

> 注：`_find_grid_by_coords` 使用线性遍历，可用哈希表优化至 O(1)。

#### 21.2.2 距离矩阵构建

```python
def _build_distance_matrix(self):
    for i, grid_i in enumerate(self.grids):    # N 次
        for j, grid_j in enumerate(self.grids):  # N 次
            distance_matrix[i][j] = self.hex_distance(grid_i, grid_j)  # O(1)
```

- **时间复杂度**: O(N²)
- **空间复杂度**: O(N²)（存储完整距离矩阵）

#### 21.2.3 预处理总计

| 项目 | 时间复杂度 | 空间复杂度 |
|------|-----------|-----------|
| 邻接矩阵 | O(N²) | O(N) |
| 距离矩阵 | O(N²) | O(N²) |
| **合计** | **O(N²)** | **O(N²)** |

### 21.3 适应度评估

适应度评估是 DSSA 优化的核心开销，每次调用 `evaluate_fitness` 的复杂度如下：

#### 21.3.1 巡逻覆盖 (Patrol Coverage)

```python
for grid_id in self.grid_ids:                    # N 次
    for camp_id, camp_value in solution.camps:   # C_camp 次
        distance = self.grid_model.get_distance(...)  # O(1) 查表
        patrol_intensity += rangers * exp(...)
    for ranger_id, ranger_count in solution.rangers:  # C_ranger 次
        distance = self.grid_model.get_distance(...)  # O(1) 查表
```

- **时间复杂度**: O(N × (C_camp + C_ranger))

#### 21.3.2 无人机覆盖 (Drone Coverage)

```python
for grid_id in self.grid_ids:                    # N 次
    for drone_id, drone_value in solution.drones:  # C_drone 次
        distance = self.grid_model.get_distance(...)  # O(1) 查表
```

- **时间复杂度**: O(N × C_drone)

#### 21.3.3 摄像头覆盖 (Camera Coverage)

```python
for grid_id in self.grid_ids:                    # N 次
    for cam_id, cam_count in solution.cameras:   # C_cam 次
        distance = self.grid_model.get_distance(...)  # O(1) 查表
```

- **时间复杂度**: O(N × C_cam)

#### 21.3.4 围栏保护 (Fence Protection)

```python
for grid_id in self.grid_ids:                    # N 次
    neighbors = self.grid_model.get_neighbors(grid_id)  # O(1) 查表
    for neighbor_id in neighbors:                # k 次 (≤6)
```

- **时间复杂度**: O(N × k) = O(N)

#### 21.3.5 适应度评估总计

```
T_fitness = T_patrol + T_drone + T_camera + T_fence + T_benefit
          = O(N × (C_camp + C_ranger)) + O(N × C_drone) + O(N × C_cam) + O(N) + O(N)
          = O(N × (C_camp + C_ranger + C_drone + C_cam))
```

令 C = C_camp + C_ranger + C_drone + C_cam（部署资源总数），则：

- **单次适应度评估时间复杂度**: O(N × C)

> 注：由于 C ≤ N（资源数不超过网格数），最坏情况为 O(N²)。但在实际场景中 C ≪ N，因此通常为 O(N)。

### 21.4 解向量编解码

#### 21.4.1 编码 (solution_to_vector)

```python
for grid_id in self.grid_ids:  # 4 × N 次
    vector.append(...)
```

- **时间复杂度**: O(N)
- **空间复杂度**: O(d) = O(4N)

#### 21.4.2 解码 (vector_to_solution)

```python
for grid_id in self.grid_ids:  # 4 × N 次
    # 检查 deployment_matrix, 约束等
```

- **时间复杂度**: O(N)

### 21.5 修复操作 (repair_solution)

修复操作包含以下步骤：

1. 清理非法部署：O(N)
2. 截断单格上限：O(N)
3. 截断总量上限：最坏 O(C)（C 为资源总数）
4. 补充不足资源：O(N)

- **时间复杂度**: O(N)
- **空间复杂度**: O(N)（存储清理后的字典）

### 21.6 单次迭代

每次迭代包含：

| 步骤 | 调用次数 | 单次时间 | 小计 |
|------|---------|---------|------|
| 生产者更新 | P_prod = P × 0.2 | 编解码 O(N) + 修复 O(N) + 适应度 O(N×C) | O(P_prod × N × C) |
| 跟随者更新 | P_foll = P × 0.8 | 编解码 O(N) + 修复 O(N) + 适应度 O(N×C) | O(P_foll × N × C) |
| 侦察者更新 | P_scout = P × 0.2 | 重新初始化 O(N) + 适应度 O(N×C) | O(P_scout × N × C) |
| 最优解更新 | P | 适应度 O(N×C) | O(P × N × C) |
| 保护效益计算 | 1 | O(N × C) | O(N × C) |

**单次迭代时间复杂度**:

```
T_iter = O(P_prod × N × C) + O(P_foll × N × C) + O(P_scout × N × C) + O(P × N × C)
       = O(P × N × C)
```

> 注：生产者和跟随者的适应度评估实际执行2次（新旧各一次），常数因子为2，不影响渐近复杂度。

### 21.7 完整优化过程

#### 21.7.1 时间复杂度

```
T_total = T_preprocess + T_init + T_iteration
        = O(N²) + O(P × N × C) + I × O(P × N × C)
        = O(N²) + O(I × P × N × C)
```

当 C ≪ N 时（实际场景）：

```
T_total = O(N²) + O(I × P × N)
```

当 C = O(N) 时（最坏情况）：

```
T_total = O(I × P × N²)
```

#### 21.7.2 空间复杂度

| 数据结构 | 空间 | 说明 |
|---------|------|------|
| 距离矩阵 | O(N²) | N×N 浮点数组 |
| 邻接矩阵 | O(N) | 每格最多6邻居 |
| 种群 | O(P × N) | P 个解，每个 O(N) |
| 解向量 | O(4N) | 临时编码向量 |
| 适应度历史 | O(I) | 每代一个值 |
| deployment_matrix | O(N) | 4种资源 × N |
| visibility_params | O(N) | N 个网格 |

**总空间复杂度**: O(N² + P × N)

- 距离矩阵 O(N²) 是主要空间开销
- 种群 O(P × N) 是次要开销

### 21.8 实际性能参考

基于 N=2648, P=50, I=100 的典型场景：

| 阶段 | 计算量估计 | 实际耗时 |
|------|-----------|---------|
| 预处理 (距离矩阵) | N² ≈ 7M | ~2s |
| 单次适应度评估 | N × C ≈ 2648 × 16 ≈ 42K | ~1ms |
| 单次迭代 | P × N × C ≈ 2.1M | ~50ms |
| 完整优化 | I × P × N × C ≈ 210M | ~5s |

### 21.9 优化建议

| 瓶颈 | 当前复杂度 | 优化方案 | 优化后复杂度 |
|------|-----------|---------|-------------|
| `_find_grid_by_coords` | O(N) 线性查找 | 使用 `{(q,r): grid}` 哈希表 | O(1) |
| 距离矩阵存储 | O(N²) 空间 | 按需计算（六边形距离 O(1)） | O(1) 每次查询 |
| 适应度评估 | O(N × C) | 向量化 numpy 运算 | O(N × C) 但常数更小 |
| 种群存储 | O(P × N) 字典 | 使用 numpy 矩阵存储 | O(P × N) 但内存更紧凑 |

***

## 22. 版本历史

| 版本  | 日期         | 变更内容                |
| --- | ---------- | ------------------- |
| 1.0 | 2026-04-17 | 初始版本                |
| 1.1 | 2026-04-17 | 添加扩展功能、收敛性分析、坐标系统详解 |
| 1.2 | 2026-04-16 | 添加复杂度分析（时间/空间） |

***

*文档版本: 1.2*
*最后更新: 2026-04-16*
