import sys
import os
import unittest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grid_model import HexGridModel, HexCoordinates
from data_loader import GridData


class TestHexCoordinatesExtended(unittest.TestCase):
    def test_s_computed_correctly(self):
        c = HexCoordinates(q=3, r=-5, s=0)
        self.assertEqual(c.s, 2)

    def test_s_always_minus_q_minus_r(self):
        for q, r in [(-10, 5), (0, 0), (100, -200)]:
            c = HexCoordinates(q=q, r=r, s=0)
            self.assertEqual(c.s, -q - r)


class TestHexDistance(unittest.TestCase):
    def test_same_grid(self):
        g = GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0)
        self.assertEqual(HexGridModel.hex_distance(g, g), 0)

    def test_adjacent(self):
        g0 = GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0)
        g1 = GridData(grid_id=1, q=1, r=0, terrain_type="SparseGrass", risk=0.0)
        self.assertEqual(HexGridModel.hex_distance(g0, g1), 1)

    def test_opposite(self):
        g0 = GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0)
        g3 = GridData(grid_id=3, q=3, r=0, terrain_type="SparseGrass", risk=0.0)
        self.assertEqual(HexGridModel.hex_distance(g0, g3), 3)

    def test_diagonal(self):
        g0 = GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0)
        g2 = GridData(grid_id=2, q=1, r=1, terrain_type="SparseGrass", risk=0.0)
        self.assertEqual(HexGridModel.hex_distance(g0, g2), 2)


class TestDistanceMatrix(unittest.TestCase):
    def setUp(self):
        self.grids = [
            GridData(grid_id=i, q=i % 5, r=i // 5, terrain_type="SparseGrass", risk=0.5)
            for i in range(25)
        ]
        self.model = HexGridModel(self.grids)

    def test_distance_matrix_shape(self):
        dm = self.model.distance_matrix
        self.assertEqual(dm.shape, (25, 25))

    def test_distance_matrix_dtype(self):
        dm = self.model.distance_matrix
        self.assertEqual(dm.dtype, np.float32)

    def test_distance_matrix_diagonal_zero(self):
        dm = self.model.distance_matrix
        for i in range(25):
            self.assertEqual(dm[i, i], 0.0)

    def test_distance_matrix_symmetric(self):
        dm = self.model.distance_matrix
        np.testing.assert_array_equal(dm, dm.T)

    def test_has_distance_matrix(self):
        self.assertTrue(self.model.has_distance_matrix())

    def test_precompute_skipped_when_too_large(self):
        model = HexGridModel(self.grids, max_precompute_bytes=100)
        self.assertFalse(model.has_distance_matrix())
        self.assertIsNone(model._distance_matrix)


class TestSparseDistanceMatrix(unittest.TestCase):
    def setUp(self):
        self.grids = [
            GridData(grid_id=i, q=i % 10, r=i // 10, terrain_type="SparseGrass", risk=0.5)
            for i in range(100)
        ]
        self.model = HexGridModel(self.grids)

    def test_sparse_matrix_shape(self):
        sm = self.model.get_distance_sparse(max_radius=3)
        self.assertEqual(sm.shape, (100, 100))

    def test_sparse_matrix_values_bounded(self):
        sm = self.model.get_distance_sparse(max_radius=3)
        self.assertTrue(np.all(sm.data <= 3))

    def test_sparse_no_radius(self):
        sm = self.model.get_distance_sparse()
        self.assertEqual(sm.shape, (100, 100))


class TestComputeDistancesTo(unittest.TestCase):
    def setUp(self):
        self.grids = [
            GridData(grid_id=i, q=i, r=0, terrain_type="SparseGrass", risk=0.5)
            for i in range(10)
        ]
        self.model = HexGridModel(self.grids)

    def test_with_precomputed(self):
        targets = np.array([0, 5])
        dists = self.model.compute_distances_to(targets)
        self.assertEqual(dists.shape, (10, 2))
        self.assertEqual(dists[0, 0], 0.0)
        self.assertEqual(dists[0, 1], 5.0)

    def test_without_precomputed(self):
        model = HexGridModel(self.grids, max_precompute_bytes=1)
        targets = np.array([0, 5])
        dists = model.compute_distances_to(targets)
        self.assertEqual(dists.shape, (10, 2))


class TestBoundaryEdges(unittest.TestCase):
    def setUp(self):
        self.grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0),
            GridData(grid_id=1, q=1, r=0, terrain_type="SparseGrass", risk=0.0),
            GridData(grid_id=2, q=0, r=1, terrain_type="SparseGrass", risk=0.0),
            GridData(grid_id=3, q=1, r=1, terrain_type="SparseGrass", risk=0.0),
        ]
        self.model = HexGridModel(self.grids)

    def test_get_boundary_edges_for_grid(self):
        edges = self.model.get_boundary_edges_for_grid(0)
        self.assertIsInstance(edges, list)
        for gid, direction in edges:
            self.assertEqual(gid, 0)
            self.assertIn(direction, range(6))

    def test_get_boundary_edges_nonexistent_grid(self):
        edges = self.model.get_boundary_edges_for_grid(999)
        self.assertEqual(edges, [])

    def test_get_all_boundary_edges(self):
        all_edges = self.model.get_all_boundary_edges()
        self.assertIsInstance(all_edges, list)
        for gid, direction, edge_type in all_edges:
            self.assertIn(direction, range(6))
            self.assertEqual(edge_type, 1)


class TestEdgeGrids(unittest.TestCase):
    def test_single_grid(self):
        grids = [GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0)]
        model = HexGridModel(grids)
        edges = model.get_edge_grids()
        self.assertEqual(edges, [0])

    def test_two_grids(self):
        grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0),
            GridData(grid_id=1, q=1, r=0, terrain_type="SparseGrass", risk=0.0),
        ]
        model = HexGridModel(grids)
        edges = model.get_edge_grids()
        self.assertEqual(len(edges), 2)


class TestFencingEdges(unittest.TestCase):
    def setUp(self):
        self.grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0),
            GridData(grid_id=1, q=1, r=0, terrain_type="SparseGrass", risk=0.0),
        ]
        self.model = HexGridModel(self.grids)

    def test_fencing_edges_exist(self):
        edges = self.model.get_fencing_edges()
        self.assertIsInstance(edges, list)
        self.assertGreater(len(edges), 0)

    def test_fencing_edges_types(self):
        edges = self.model.get_fencing_edges()
        for edge in edges:
            self.assertEqual(len(edge), 3)
            gid1, gid2, edge_type = edge
            self.assertIn(edge_type, [1.0, 2.0])


class TestGridCenterCoords(unittest.TestCase):
    def test_origin(self):
        grids = [GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0)]
        model = HexGridModel(grids)
        x, y = model.get_grid_center_coords(0, hex_size=1.0)
        self.assertAlmostEqual(x, 0.0, places=5)
        self.assertAlmostEqual(y, 0.0, places=5)

    def test_nonzero_r(self):
        grids = [GridData(grid_id=0, q=0, r=2, terrain_type="SparseGrass", risk=0.0)]
        model = HexGridModel(grids)
        x, y = model.get_grid_center_coords(0, hex_size=1.0)
        self.assertAlmostEqual(y, 3.0, places=5)

    def test_invalid_grid(self):
        grids = [GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0)]
        model = HexGridModel(grids)
        x, y = model.get_grid_center_coords(999, hex_size=1.0)
        self.assertEqual(x, 0.0)
        self.assertEqual(y, 0.0)


class TestGridCorners(unittest.TestCase):
    def test_six_corners(self):
        grids = [GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0)]
        model = HexGridModel(grids)
        corners = model.get_grid_corners(0, hex_size=1.0)
        self.assertEqual(len(corners), 6)
        for cx, cy in corners:
            self.assertIsInstance(cx, float)
            self.assertIsInstance(cy, float)


class TestGetGridTerrain(unittest.TestCase):
    def test_terrain_types(self):
        grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="Road", risk=0.0),
            GridData(grid_id=1, q=1, r=0, terrain_type="WaterHole", risk=0.0),
        ]
        model = HexGridModel(grids)
        self.assertEqual(model.get_grid_terrain(0), "Road")
        self.assertEqual(model.get_grid_terrain(1), "WaterHole")
        self.assertEqual(model.get_grid_terrain(99), "Unknown")


class TestGetGridBounds(unittest.TestCase):
    def test_bounds(self):
        grids = [
            GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0),
            GridData(grid_id=1, q=2, r=0, terrain_type="SparseGrass", risk=0.0),
            GridData(grid_id=2, q=0, r=2, terrain_type="SparseGrass", risk=0.0),
        ]
        model = HexGridModel(grids)
        min_x, max_x, min_y, max_y = model.get_grid_bounds(hex_size=1.0)
        self.assertLess(min_x, max_x)
        self.assertLess(min_y, max_y)


class TestGetDistanceInvalidGrids(unittest.TestCase):
    def test_invalid_grid_returns_inf(self):
        grids = [GridData(grid_id=0, q=0, r=0, terrain_type="SparseGrass", risk=0.0)]
        model = HexGridModel(grids)
        d = model.get_distance(0, 99)
        self.assertEqual(d, float('inf'))


if __name__ == '__main__':
    unittest.main()
