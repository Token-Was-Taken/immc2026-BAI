import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grid_model import HexGridModel, HexCoordinates
from data_loader import GridData


class TestHexCoordinates(unittest.TestCase):
    def test_creation(self):
        c = HexCoordinates(q=1, r=-2, s=0)
        self.assertEqual(c.q, 1)
        self.assertEqual(c.r, -2)
        self.assertEqual(c.s, 1)

    def test_equality(self):
        c1 = HexCoordinates(q=1, r=2, s=0)
        c2 = HexCoordinates(q=1, r=2, s=0)
        c3 = HexCoordinates(q=2, r=1, s=0)
        self.assertEqual(c1, c2)
        self.assertNotEqual(c1, c3)


class TestHexGridModel(unittest.TestCase):
    def setUp(self):
        self.grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.5),
            GridData(grid_id=1, q=1, r=0, terrain_type="SparseGrass", risk=0.3),
            GridData(grid_id=2, q=0, r=1, terrain_type="DenseGrass", risk=0.7),
            GridData(grid_id=3, q=1, r=1, terrain_type="WaterHole", risk=0.9),
        ]
        self.model = HexGridModel(self.grids)

    def test_grid_count(self):
        self.assertEqual(self.model.get_grid_count(), 4)

    def test_get_grid_by_id(self):
        g = self.model.get_grid_by_id(2)
        self.assertIsNotNone(g)
        self.assertEqual(g.terrain_type, "DenseGrass")
        self.assertEqual(g.risk, 0.7)

    def test_get_grid_by_id_not_found(self):
        g = self.model.get_grid_by_id(99)
        self.assertIsNone(g)

    def test_get_all_grid_ids(self):
        ids = self.model.get_all_grid_ids()
        self.assertEqual(set(ids), {0, 1, 2, 3})

    def test_adjacency_matrix(self):
        adj = self.model.get_adjacency_matrix()
        self.assertIsInstance(adj, dict)
        self.assertEqual(len(adj), 4)

    def test_get_grid_risk(self):
        self.assertEqual(self.model.get_grid_risk(0), 0.5)
        self.assertEqual(self.model.get_grid_risk(3), 0.9)

    def test_get_grid_risk_default(self):
        self.assertEqual(self.model.get_grid_risk(99), 0.0)

    def test_get_neighbors(self):
        neighbors = self.model.get_neighbors(0)
        self.assertIsInstance(neighbors, list)
        for n in neighbors:
            self.assertIn(n, [0, 1, 2, 3])

    def test_get_grid_center_coords(self):
        x, y = self.model.get_grid_center_coords(0, hex_size=1.0)
        self.assertIsInstance(x, float)
        self.assertIsInstance(y, float)

    def test_get_boundary_edges(self):
        edges = self.model.get_boundary_edges()
        self.assertIsInstance(edges, list)

    def test_get_fencing_edges(self):
        edges = self.model.get_fencing_edges()
        self.assertIsInstance(edges, list)

    def test_get_distance(self):
        d = self.model.get_distance(0, 1)
        self.assertGreaterEqual(d, 0)

    def test_distance_same_grid(self):
        d = self.model.get_distance(0, 0)
        self.assertEqual(d, 0)

    def test_max_precompute_bytes_configurable(self):
        model = HexGridModel(self.grids, max_precompute_bytes=100)
        self.assertEqual(model._max_precompute_bytes, 100)

    def test_max_precompute_bytes_default(self):
        model = HexGridModel(self.grids)
        self.assertEqual(model._max_precompute_bytes, 800 * 1024**2)

    def test_get_grid_terrain(self):
        self.assertEqual(self.model.get_grid_terrain(0), "SparseGrass")
        self.assertEqual(self.model.get_grid_terrain(2), "DenseGrass")

    def test_get_grids_by_terrain(self):
        sparse = self.model.get_grids_by_terrain("SparseGrass")
        self.assertEqual(set(sparse), {0, 1})

    def test_get_high_risk_grids(self):
        high = self.model.get_high_risk_grids(threshold=0.6)
        self.assertIn(2, high)
        self.assertIn(3, high)

    def test_get_edge_grids(self):
        edges = self.model.get_edge_grids()
        self.assertIsInstance(edges, list)


class TestHexGridModelLarge(unittest.TestCase):
    def setUp(self):
        self.grids = []
        gid = 0
        for r in range(10):
            for q in range(-5, 6):
                self.grids.append(GridData(
                    grid_id=gid, q=q, r=r,
                    terrain_type="SparseGrass", risk=0.5
                ))
                gid += 1
        self.model = HexGridModel(self.grids)

    def test_large_grid_count(self):
        self.assertEqual(self.model.get_grid_count(), 110)

    def test_large_adjacency(self):
        adj = self.model.get_adjacency_matrix()
        self.assertEqual(len(adj), 110)

    def test_large_neighbors(self):
        for gid in [0, 55, 109]:
            neighbors = self.model.get_neighbors(gid)
            self.assertLessEqual(len(neighbors), 6)
            self.assertGreaterEqual(len(neighbors), 1)


if __name__ == '__main__':
    unittest.main()
