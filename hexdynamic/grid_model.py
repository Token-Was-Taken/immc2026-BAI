import numpy as np
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass
from data_loader import GridData
from scipy import sparse


@dataclass
class HexCoordinates:
    q: int
    r: int
    s: int

    def __post_init__(self):
        self.s = -self.q - self.r


class HexGridModel:
    _MAX_PRECOMPUTE_BYTES = 3 * 1024**3

    def __init__(self, grids: List[GridData], max_radius: Optional[int] = None):
        self.grids = grids
        self.grid_dict = {grid.grid_id: grid for grid in grids}
        self._id_to_idx: Dict[int, int] = {g.grid_id: i for i, g in enumerate(grids)}
        self._coord_to_grid: Dict[Tuple[int, int], GridData] = {
            (g.q, g.r): g for g in grids
        }
        self._qs = np.array([g.q for g in grids], dtype=np.int32)
        self._rs = np.array([g.r for g in grids], dtype=np.int32)
        self._qr = self._qs + self._rs
        self.adjacency_matrix = self._build_adjacency_matrix()
        self._max_radius = max_radius
        self._distance_matrix = None
        self._distance_matrix_loaded = False
        self._distance_sparse = None

    @property
    def distance_matrix(self) -> np.ndarray:
        if not self._distance_matrix_loaded:
            self._distance_matrix = self._try_build_distance_matrix()
            self._distance_matrix_loaded = True
        return self._distance_matrix

    def has_distance_matrix(self) -> bool:
        if not self._distance_matrix_loaded:
            self._distance_matrix = self._try_build_distance_matrix()
            self._distance_matrix_loaded = True
        return self._distance_matrix is not None

    def get_distance_sparse(self, max_radius: Optional[int] = None) -> sparse.csr_matrix:
        if self._distance_sparse is None:
            self._distance_sparse = self._build_distance_sparse(max_radius or self._max_radius)
        return self._distance_sparse

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

    def _try_build_distance_matrix(self) -> Optional[np.ndarray]:
        n = len(self.grids)
        estimated_bytes = n * n * 4
        if estimated_bytes > self._MAX_PRECOMPUTE_BYTES:
            print(f"      [MEM] 距离矩阵需 {estimated_bytes/1024**3:.2f} GiB > 阈值 "
                  f"{self._MAX_PRECOMPUTE_BYTES/1024**3:.1f} GiB，跳过预计算")
            return None
        try:
            dist = self._build_distance_matrix_vectorized()
            print(f"      [MEM] 预计算距离矩阵 {dist.shape} float32 "
                  f"({dist.nbytes/1024**2:.1f} MiB)")
            return dist
        except MemoryError:
            print(f"      [MEM] 距离矩阵分配失败 (MemoryError)，回退到按需计算")
            return None

    def _build_distance_matrix_vectorized(self) -> np.ndarray:
        n = len(self.grids)
        qs = self._qs
        rs = self._rs
        qr = self._qr

        dist = np.empty((n, n), dtype=np.float32)
        chunk = 512
        for start in range(0, n, chunk):
            end = min(start + chunk, n)
            dq = np.abs(qs[start:end, None] - qs[None, :])
            dr = np.abs(rs[start:end, None] - rs[None, :])
            ds = np.abs(qr[start:end, None] - qr[None, :])
            dist[start:end, :] = ((dq + dr + ds) >> 1)
        return dist

    def _build_distance_sparse(self, max_radius: Optional[int] = None) -> sparse.csr_matrix:
        n = len(self.grids)
        qs = np.array([g.q for g in self.grids], dtype=np.int32)
        rs = np.array([g.r for g in self.grids], dtype=np.int32)

        if max_radius is not None and max_radius >= 0:
            sort_idx = np.argsort(qs)
            qs_sorted = qs[sort_idx]

            row_blocks = []
            col_blocks = []
            val_blocks = []
            chunk = 500

            for start in range(0, n, chunk):
                end = min(start + chunk, n)
                r_rows, r_cols, r_vals = [], [], []

                for i in range(start, end):
                    lo = np.searchsorted(qs_sorted, qs[i] - max_radius)
                    hi = np.searchsorted(qs_sorted, qs[i] + max_radius + 1)
                    candidates = sort_idx[lo:hi]

                    dq = np.abs(qs[i] - qs[candidates])
                    dr = np.abs(rs[i] - rs[candidates])
                    ds = np.abs(qs[i] + rs[i] - qs[candidates] - rs[candidates])
                    dist = (dq + dr + ds) // 2
                    mask = dist <= max_radius
                    valid = candidates[mask]
                    valid_dist = dist[mask]

                    r_rows.append(np.full(len(valid), i, dtype=np.int32))
                    r_cols.append(valid)
                    r_vals.append(valid_dist.astype(np.float32))

                if r_rows:
                    row_blocks.append(np.concatenate(r_rows))
                    col_blocks.append(np.concatenate(r_cols))
                    val_blocks.append(np.concatenate(r_vals))

            all_rows = np.concatenate(row_blocks) if row_blocks else np.array([], dtype=np.int32)
            all_cols = np.concatenate(col_blocks) if col_blocks else np.array([], dtype=np.int32)
            all_vals = np.concatenate(val_blocks) if val_blocks else np.array([], dtype=np.float32)
        else:
            all_rows = np.repeat(np.arange(n, dtype=np.int32), n)
            all_cols = np.tile(np.arange(n, dtype=np.int32), n)
            qs2 = np.tile(qs, n)
            rs2 = np.tile(rs, n)
            dq = np.abs(np.repeat(qs, n) - qs2)
            dr = np.abs(np.repeat(rs, n) - rs2)
            ds = np.abs(np.repeat(qs + rs, n) - qs2 - rs2)
            all_vals = ((dq + dr + ds) // 2).astype(np.float32)

        return sparse.csr_matrix(
            (all_vals, (all_rows, all_cols)),
            shape=(n, n)
        )

    def compute_distances_to(self, target_indices: np.ndarray) -> np.ndarray:
        if self._distance_matrix is not None:
            return self._distance_matrix[:, target_indices]

        t_qs = self._qs[target_indices]
        t_rs = self._rs[target_indices]
        t_qr = self._qr[target_indices]

        dq = np.abs(self._qs[:, None] - t_qs[None, :])
        dr = np.abs(self._rs[:, None] - t_rs[None, :])
        ds = np.abs(self._qr[:, None] - t_qr[None, :])
        return ((dq + dr + ds) >> 1).astype(np.float32)

    def _find_grid_by_coords(self, q: int, r: int) -> GridData:
        return self._coord_to_grid.get((q, r))

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
