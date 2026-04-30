import numpy as np
from typing import List, Tuple, Dict
from dataclasses import dataclass
from data_loader import GridData


@dataclass
class HexCoordinates:
    q: int
    r: int
    s: int

    def __post_init__(self):
        self.s = -self.q - self.r


class HexGridModel:
    def __init__(self, grids: List[GridData]):
        self.grids = grids
        self.grid_dict = {grid.grid_id: grid for grid in grids}
        self.adjacency_matrix = self._build_adjacency_matrix()
        self.distance_matrix = self._build_distance_matrix()

    def _build_adjacency_matrix(self) -> Dict[int, List[int]]:
        adjacency = {}
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

    def _build_distance_matrix(self) -> np.ndarray:
        n = len(self.grids)
        distance_matrix = np.zeros((n, n))

        for i, grid_i in enumerate(self.grids):
            for j, grid_j in enumerate(self.grids):
                distance_matrix[i][j] = self.hex_distance(grid_i, grid_j)

        return distance_matrix

    def _find_grid_by_coords(self, q: int, r: int) -> GridData:
        for grid in self.grids:
            if grid.q == q and grid.r == r:
                return grid
        return None

    @staticmethod
    def hex_distance(grid1: GridData, grid2: GridData) -> int:
        return (abs(grid1.q - grid2.q) + 
                abs(grid1.q + grid1.r - grid2.q - grid2.r) + 
                abs(grid1.r - grid2.r)) // 2

    def get_distance(self, grid_id1: int, grid_id2: int) -> int:
        if grid_id1 not in self.grid_dict or grid_id2 not in self.grid_dict:
            return float('inf')
        grid1 = self.grid_dict[grid_id1]
        grid2 = self.grid_dict[grid_id2]
        return self.hex_distance(grid1, grid2)

    def get_neighbors(self, grid_id: int) -> List[int]:
        return self.adjacency_matrix.get(grid_id, [])

    def get_all_grid_ids(self) -> List[int]:
        return list(self.grid_dict.keys())

    def get_grid_by_id(self, grid_id: int) -> GridData:
        return self.grid_dict.get(grid_id, None)

    def get_grid_center_coords(self, grid_id: int, hex_size: float = 1.0) -> Tuple[float, float]:
        """获取六边形网格中心坐标，确保网格紧密嵌合"""
        grid = self.get_grid_by_id(grid_id)
        if not grid:
            return (0.0, 0.0)

        # 使用even-r offset坐标系统计算笛卡尔坐标
        # 对于pointy-topped六边形
        # col = q + floor(r/2)
        # row = r
        # x = hex_size * sqrt(3) * (col + 0.5 * (row & 1))
        # y = hex_size * 3/2 * row
        
        col = grid.q + (grid.r // 2)
        row = grid.r
        
        x = hex_size * np.sqrt(3) * (col + 0.5 * (row & 1))
        y = hex_size * 3/2 * row
        return (x, y)

    def get_grid_corners(self, grid_id: int, hex_size: float = 1.0) -> List[Tuple[float, float]]:
        """获取六边形网格的六个角点坐标"""
        center_x, center_y = self.get_grid_center_coords(grid_id, hex_size)
        corners = []
        for i in range(6):
            # 对于pointy-topped六边形，从30度开始
            angle_deg = 60 * i + 30
            angle_rad = np.pi / 180 * angle_deg
            corner_x = center_x + hex_size * np.cos(angle_rad)
            corner_y = center_y + hex_size * np.sin(angle_rad)
            corners.append((corner_x, corner_y))
        return corners

    def get_boundary_edges(self) -> List[Tuple[int, int, float]]:
        boundary_edges = []
        grid_ids = self.get_all_grid_ids()

        for grid_id in grid_ids:
            neighbors = self.get_neighbors(grid_id)
            for neighbor_id in neighbors:
                if grid_id < neighbor_id:
                    boundary_edges.append((grid_id, neighbor_id, 1.0))

        return boundary_edges

    def get_boundary_edges_for_grid(self, grid_id: int) -> List[Tuple[int, int]]:
        """
        Get boundary edges for a specific grid.
        
        A boundary edge is an edge that faces outside the protected area.
        For hexagonal grids, this means the neighbor in that direction doesn't exist.
        
        Args:
            grid_id: The ID of the grid to check
            
        Returns:
            List of (grid_id, direction) tuples where direction is 0-5
            representing the 6 hexagonal directions.
            Direction mapping:
            0: (1, 0)   - East
            1: (0, 1)   - Northeast
            2: (-1, 1)  - Northwest
            3: (-1, 0)  - West
            4: (0, -1)  - Southwest
            5: (1, -1)  - Southeast
        """
        if grid_id not in self.grid_dict:
            return []
        
        grid = self.grid_dict[grid_id]
        boundary_edges = []
        
        # Hexagonal directions (same as used in adjacency matrix)
        directions = [
            (1, 0),   # 0: East
            (0, 1),   # 1: Northeast
            (-1, 1),  # 2: Northwest
            (-1, 0),  # 3: West
            (0, -1),  # 4: Southwest
            (1, -1)   # 5: Southeast
        ]
        
        for dir_idx, (dq, dr) in enumerate(directions):
            neighbor_q = grid.q + dq
            neighbor_r = grid.r + dr
            neighbor_grid = self._find_grid_by_coords(neighbor_q, neighbor_r)
            
            # If no neighbor exists in this direction, it's a boundary edge
            if neighbor_grid is None:
                boundary_edges.append((grid_id, dir_idx))
        
        return boundary_edges

    def get_all_boundary_edges(self) -> List[Tuple[int, int, int]]:
        """
        Get all boundary edges in the grid.
        
        Returns:
            List of (grid_id, direction, edge_type) tuples where:
            - grid_id: The edge grid
            - direction: 0-5, hexagonal direction
            - edge_type: 1 for boundary edge (facing outside)
        """
        all_boundary_edges = []
        
        for grid_id in self.get_all_grid_ids():
            boundary_edges = self.get_boundary_edges_for_grid(grid_id)
            for grid_id, direction in boundary_edges:
                all_boundary_edges.append((grid_id, direction, 1))
        
        return all_boundary_edges

    def get_fencing_edges(self) -> List[Tuple[int, int, float]]:
        """只返回至少一端是边缘格子的边，确保围栏只能部署在地图外围。
        
        返回两种类型的边：
        1. 内部边：两个相邻格子之间的边，至少一端是边缘格子
        2. 边界边：边缘格子面向外部的边（没有邻居的方向）
        
        Returns:
            List of (grid_id_1, grid_id_2, edge_type) tuples where:
            - grid_id_1, grid_id_2: Grid IDs (grid_id_2 is None for boundary edges)
            - edge_type: 1.0 for internal edges, 2.0 for boundary edges
        """
        edge_grid_set = set(self.get_edge_grids())
        fencing_edges = []
        seen_edges = set()
        
        # 1. Add internal edges (between two grids)
        for grid_id in self.get_all_grid_ids():
            for neighbor_id in self.get_neighbors(grid_id):
                if grid_id < neighbor_id:
                    if grid_id in edge_grid_set or neighbor_id in edge_grid_set:
                        edge_key = (min(grid_id, neighbor_id), max(grid_id, neighbor_id))
                        if edge_key not in seen_edges:
                            fencing_edges.append((grid_id, neighbor_id, 1.0))
                            seen_edges.add(edge_key)
        
        # 2. Add boundary edges (facing outside)
        for grid_id in edge_grid_set:
            boundary_edges = self.get_boundary_edges_for_grid(grid_id)
            for _, direction in boundary_edges:
                # Use (grid_id, None) as edge key for boundary edges
                edge_key = (grid_id, None, direction)
                if edge_key not in seen_edges:
                    fencing_edges.append((grid_id, None, 2.0))
                    seen_edges.add(edge_key)
        
        return fencing_edges

    def get_grid_risk(self, grid_id: int) -> float:
        grid = self.get_grid_by_id(grid_id)
        return grid.risk if grid else 0.0

    def get_grid_temporal_factor(self, grid_id: int) -> float:
        """Get temporal factor (T_t × S_t) for time-aware fitness."""
        grid = self.get_grid_by_id(grid_id)
        return grid.temporal_factor if grid else 1.0

    def get_grid_terrain(self, grid_id: int) -> str:
        grid = self.get_grid_by_id(grid_id)
        return grid.terrain_type if grid else 'Unknown'

    def get_grids_by_terrain(self, terrain_type: str) -> List[int]:
        return [grid.grid_id for grid in self.grids if grid.terrain_type == terrain_type]

    def get_high_risk_grids(self, threshold: float = 0.7) -> List[int]:
        return [grid.grid_id for grid in self.grids if grid.risk >= threshold]

    def get_edge_grids(self) -> List[int]:
        """获取地图边缘的网格ID列表
        
        边缘网格定义为：
        1. 邻居数量少于6的网格（边界网格）
        2. 位于矩形地图边界的网格
        """
        edge_grids = []
        
        # 获取网格的行列范围
        rows = set()
        cols = set()
        grid_info = {}  # grid_id -> (row, col)
        
        for grid in self.grids:
            row = grid.r
            col = grid.q + (row // 2)  # 从轴坐标转换回行列坐标
            rows.add(row)
            cols.add(col)
            grid_info[grid.grid_id] = (row, col)
        
        min_row, max_row = min(rows), max(rows)
        min_col, max_col = min(cols), max(cols)
        
        for grid_id, (row, col) in grid_info.items():
            # 检查是否为边缘网格
            is_edge = False
            
            # 1. 邻居数量少于6（边界网格）
            neighbors = self.get_neighbors(grid_id)
            if len(neighbors) < 6:
                is_edge = True
            
            # 2. 位于矩形地图边界
            if row == min_row or row == max_row or col == min_col or col == max_col:
                is_edge = True
            
            if is_edge:
                edge_grids.append(grid_id)
        
        return sorted(edge_grids)

    def get_grid_bounds(self, hex_size: float = 1.0) -> Tuple[float, float, float, float]:
        min_x, max_x = float('inf'), float('-inf')
        min_y, max_y = float('inf'), float('-inf')

        for grid_id in self.get_all_grid_ids():
            corners = self.get_grid_corners(grid_id, hex_size)
            for x, y in corners:
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)

        return (min_x, max_x, min_y, max_y)

    def get_grid_count(self) -> int:
        return len(self.grids)

    def get_distance_matrix(self) -> np.ndarray:
        return self.distance_matrix

    def get_adjacency_matrix(self) -> Dict[int, List[int]]:
        return self.adjacency_matrix
