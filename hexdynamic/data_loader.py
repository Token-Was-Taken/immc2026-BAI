import numpy as np
from typing import Dict, List, Tuple
from dataclasses import dataclass


@dataclass
class GridData:
    grid_id: int
    q: int
    r: int
    terrain_type: str
    risk: float
    temporal_factor: float = 1.0  # T_t × S_t (diurnal × seasonal)


@dataclass
class ResourceConstraints:
    total_patrol: int
    total_camps: int
    max_rangers_per_camp: int
    total_cameras: int
    total_drones: int
    total_fence_length: float
    # 单格最大部署数量
    max_cameras_per_grid: int = 1
    max_drones_per_grid: int = 1
    max_camps_per_grid: int = 1
    max_rangers_per_grid: int = 1
    max_fences_per_grid: int = 6  # Default: one per hexagonal side


@dataclass
class CoverageParameters:
    patrol_radius: float = 5.0
    drone_radius: float = 8.0
    camera_radius: float = 3.0
    fence_protection: float = 0.5
    wp: float = 0.3
    wd: float = 0.3
    wc: float = 0.2
    wf: float = 0.2

# Default coverage effectiveness: terrain -> resource -> multiplier (1.0 = full effect)
DEFAULT_COVERAGE_EFFECTIVENESS: Dict[str, Dict[str, float]] = {
    'DenseGrass': {'patrol': 0.3, 'camp': 0.3},
}


class DataLoader:
    def __init__(self):
        self.grids: List[GridData] = []
        self.deployment_matrix: Dict[str, Dict[int, int]] = {}
        self.visibility_params: Dict[str, Dict[str, float]] = {}
        self.coverage_effectiveness: Dict[str, Dict[str, float]] = {}
        self.constraints: ResourceConstraints = None
        self.coverage_params: CoverageParameters = None

    def generate_hexagonal_grid(self, radius: int = 5) -> List[GridData]:
        """生成矩形边界的六边形蜂窝网格"""
        grids = []
        grid_id = 0
        
        # 矩形地图参数
        width = 12   # 矩形宽度 (列数)
        height = 10  # 矩形高度 (行数)
        
        for row in range(height):
            for col in range(width):
                # 将行列坐标转换为六边形轴坐标 (q, r)
                # 奇数行偏移，形成蜂窝状排列
                q = col - (row // 2)
                r = row
                
                grid = GridData(
                    grid_id=grid_id,
                    q=q,
                    r=r,
                    terrain_type='SparseGrass',
                    risk=0.0
                )
                grids.append(grid)
                grid_id += 1
        
        self.grids = grids
        return grids
    
    def generate_rectangular_hex_grid(self, width: int = 12, height: int = 10) -> List[GridData]:
        """生成指定尺寸的矩形六边形网格，确保紧密嵌合"""
        grids = []
        grid_id = 0
        
        for row in range(height):
            for col in range(width):
                # 使用偶数行偏移坐标系统（even-r offset）
                # 将行列坐标转换为六边形轴坐标 (q, r)
                # 对于偶数行偏移：q = col - floor(r/2)
                q = col - (row // 2)
                r = row
                
                grid = GridData(
                    grid_id=grid_id,
                    q=q,
                    r=r,
                    terrain_type='SparseGrass',
                    risk=0.0
                )
                grids.append(grid)
                grid_id += 1
        
        self.grids = grids
        return grids

    def set_terrain_types(self, terrain_map: Dict[int, str]):
        for grid in self.grids:
            if grid.grid_id in terrain_map:
                grid.terrain_type = terrain_map[grid.grid_id]

    def set_risk_values(self, risk_map: Dict[int, float]):
        for grid in self.grids:
            if grid.grid_id in risk_map:
                grid.risk = risk_map[grid.grid_id]

    def initialize_deployment_matrix(self, edge_grids: List[int] = None, grid_model=None):
        """初始化部署矩阵
        
        Args:
            edge_grids: 边缘网格ID列表，Fence只能在这些网格部署
            grid_model: HexGridModel实例，用于获取边界边数量。如果提供，
                        fence部署矩阵值将设置为该网格的边界边数量（0-6）
        """
        terrain_deployment = {
            'SaltMarsh':  {'patrol': 0, 'camp': 0, 'drone': 1, 'camera': 0, 'fence': 0},
            'SparseGrass':{'patrol': 1, 'camp': 0, 'drone': 1, 'camera': 1, 'fence': 1},
            'DenseGrass': {'patrol': 0, 'camp': 0, 'drone': 1, 'camera': 0, 'fence': 1},
            'WaterHole':  {'patrol': 0, 'camp': 0, 'drone': 1, 'camera': 0, 'fence': 0},
            'Road':       {'patrol': 1, 'camp': 1, 'drone': 1, 'camera': 1, 'fence': 1}
        }

        self.deployment_matrix = {}
        for resource in ['patrol', 'camp', 'drone', 'camera', 'fence']:
            self.deployment_matrix[resource] = {}
            for grid in self.grids:
                # 对于Fence，只能在边缘网格部署
                if resource == 'fence':
                    if edge_grids is not None:
                        # 如果提供了边缘网格列表，只有在边缘且地形允许时才可部署
                        can_deploy = grid.grid_id in edge_grids and terrain_deployment[grid.terrain_type][resource] == 1
                    else:
                        # 如果没有提供边缘网格列表，使用地形规则
                        can_deploy = terrain_deployment[grid.terrain_type][resource] == 1
                    
                    if can_deploy:
                        if grid_model is not None:
                            # 使用边界边数量作为部署矩阵值（0-6）
                            boundary_edges = grid_model.get_boundary_edges_for_grid(grid.grid_id)
                            num_boundary_edges = len(boundary_edges)
                            # 限制为max_fences_per_grid（如果已设置约束）
                            max_fences = 6
                            if self.constraints is not None:
                                max_fences = self.constraints.max_fences_per_grid
                            self.deployment_matrix[resource][grid.grid_id] = min(num_boundary_edges, max_fences)
                        else:
                            # 如果没有grid_model，使用默认值1（向后兼容）
                            self.deployment_matrix[resource][grid.grid_id] = 1
                    else:
                        self.deployment_matrix[resource][grid.grid_id] = 0
                else:
                    # 其他资源使用地形规则
                    self.deployment_matrix[resource][grid.grid_id] = terrain_deployment[grid.terrain_type][resource]

    def initialize_coverage_effectiveness(self, overrides: Dict[str, Dict[str, float]] = None):
        """Build per-grid coverage effectiveness map.
        
        Merges DEFAULT_COVERAGE_EFFECTIVENESS with any overrides from config.
        Result: self.coverage_effectiveness[grid_id][resource] = multiplier (0.0-1.0)
        """
        terrain_eff = {k: dict(v) for k, v in DEFAULT_COVERAGE_EFFECTIVENESS.items()}
        if overrides:
            for terrain, res_map in overrides.items():
                terrain_eff.setdefault(terrain, {}).update(res_map)

        self.coverage_effectiveness = {}
        for grid in self.grids:
            terrain = grid.terrain_type
            self.coverage_effectiveness[grid.grid_id] = terrain_eff.get(terrain, {})

    def initialize_visibility_params(self):
        terrain_visibility = {
            'SparseGrass': {'drone': 1.0, 'camera': 1.0},
            'DenseGrass': {'drone': 0.7, 'camera': 0.5},
            'SaltMarsh': {'drone': 0.9, 'camera': 0.6},
            'WaterHole': {'drone': 1.0, 'camera': 0.8},
            'Road': {'drone': 1.0, 'camera': 1.0}
        }

        self.visibility_params = {}
        for grid in self.grids:
            self.visibility_params[grid.grid_id] = terrain_visibility[grid.terrain_type]

    def set_constraints(self, total_patrol: int, total_camps: int, 
                       max_rangers_per_camp: int, total_cameras: int, 
                       total_drones: int, total_fence_length: float,
                       max_cameras_per_grid: int = 1,
                       max_drones_per_grid: int = 1,
                       max_camps_per_grid: int = 1,
                       max_rangers_per_grid: int = 1,
                       max_fences_per_grid: int = 6):
        self.constraints = ResourceConstraints(
            total_patrol=total_patrol,
            total_camps=total_camps,
            max_rangers_per_camp=max_rangers_per_camp,
            total_cameras=total_cameras,
            total_drones=total_drones,
            total_fence_length=total_fence_length,
            max_cameras_per_grid=max_cameras_per_grid,
            max_drones_per_grid=max_drones_per_grid,
            max_camps_per_grid=max_camps_per_grid,
            max_rangers_per_grid=max_rangers_per_grid,
            max_fences_per_grid=max_fences_per_grid
        )

    def set_coverage_parameters(self, patrol_radius: float = 5.0, drone_radius: float = 8.0,
                               camera_radius: float = 3.0, fence_protection: float = 0.5,
                               wp: float = 0.3, wd: float = 0.3, wc: float = 0.2, wf: float = 0.2):
        self.coverage_params = CoverageParameters(
            patrol_radius=patrol_radius,
            drone_radius=drone_radius,
            camera_radius=camera_radius,
            fence_protection=fence_protection,
            wp=wp, wd=wd, wc=wc, wf=wf
        )

    def get_grid_by_id(self, grid_id: int) -> GridData:
        for grid in self.grids:
            if grid.grid_id == grid_id:
                return grid
        return None

    def get_all_grid_ids(self) -> List[int]:
        return [grid.grid_id for grid in self.grids]

    def get_terrain_distribution(self) -> Dict[str, int]:
        terrain_count = {}
        for grid in self.grids:
            terrain_count[grid.terrain_type] = terrain_count.get(grid.terrain_type, 0) + 1
        return terrain_count

    def load_from_config(self, config: Dict):
        self.generate_hexagonal_grid(radius=config.get('grid_radius', 5))
        
        if 'terrain_map' in config:
            self.set_terrain_types(config['terrain_map'])
        
        if 'risk_map' in config:
            self.set_risk_values(config['risk_map'])
        
        self.initialize_deployment_matrix()
        self.initialize_visibility_params()
        self.initialize_coverage_effectiveness(config.get('coverage_effectiveness'))
        
        if 'constraints' in config:
            c = config['constraints']
            self.set_constraints(
                total_patrol=c.get('total_patrol', 20),
                total_camps=c.get('total_camps', 5),
                max_rangers_per_camp=c.get('max_rangers_per_camp', 5),
                total_cameras=c.get('total_cameras', 10),
                total_drones=c.get('total_drones', 3),
                total_fence_length=c.get('total_fence_length', 50.0),
                max_cameras_per_grid=c.get('max_cameras_per_grid', 1),
                max_drones_per_grid=c.get('max_drones_per_grid', 1),
                max_camps_per_grid=c.get('max_camps_per_grid', 1),
                max_rangers_per_grid=c.get('max_rangers_per_grid', 1),
                max_fences_per_grid=c.get('max_fences_per_grid', 6)
            )
        
        if 'coverage_params' in config:
            cp = config['coverage_params']
            self.set_coverage_parameters(
                patrol_radius=cp.get('patrol_radius', 5.0),
                drone_radius=cp.get('drone_radius', 8.0),
                camera_radius=cp.get('camera_radius', 3.0),
                fence_protection=cp.get('fence_protection', 0.5),
                wp=cp.get('wp', 0.3),
                wd=cp.get('wd', 0.3),
                wc=cp.get('wc', 0.2),
                wf=cp.get('wf', 0.2)
            )
