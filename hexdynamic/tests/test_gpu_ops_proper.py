import sys
import os
import unittest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpu_ops import hex_distances, gpu_available, _hex_distances_cpu


class TestCPUDistances(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        self.N = 100
        self.qs = np.random.randint(-10, 10, self.N).astype(np.int32)
        self.rs = np.random.randint(-10, 10, self.N).astype(np.int32)
        self.qrs = self.qs + self.rs
        self.K = 10
        self.targets = np.random.choice(self.N, self.K, replace=False).astype(np.int64)

    def test_shape(self):
        result = _hex_distances_cpu(self.qs, self.rs, self.qrs, self.targets)
        self.assertEqual(result.shape, (self.N, self.K))

    def test_dtype(self):
        result = _hex_distances_cpu(self.qs, self.rs, self.qrs, self.targets)
        self.assertEqual(result.dtype, np.float32)

    def test_diagonal_zero(self):
        result = _hex_distances_cpu(self.qs, self.rs, self.qrs, self.targets)
        for j, t in enumerate(self.targets):
            self.assertEqual(result[t, j], 0.0)

    def test_symmetry(self):
        result = _hex_distances_cpu(self.qs, self.rs, self.qrs, self.targets)
        for i in range(self.N):
            for j in range(self.K):
                t = self.targets[j]
                d_ij = result[i, j]
                d_ji = result[t, np.where(self.targets == i)[0][0]] if i in self.targets else None
                if d_ji is not None:
                    self.assertEqual(d_ij, d_ji)

    def test_known_distance(self):
        qs = np.array([0, 1, 0], dtype=np.int32)
        rs = np.array([0, 0, 1], dtype=np.int32)
        qrs = qs + rs
        targets = np.array([0, 1, 2], dtype=np.int64)
        result = _hex_distances_cpu(qs, rs, qrs, targets)
        self.assertEqual(result[0, 0], 0.0)
        self.assertEqual(result[0, 1], 1.0)
        self.assertEqual(result[0, 2], 1.0)
        self.assertEqual(result[1, 2], 1.0)

    def test_nonnegative(self):
        result = _hex_distances_cpu(self.qs, self.rs, self.qrs, self.targets)
        self.assertTrue(np.all(result >= 0))


class TestGPUDistances(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        self.N = 200
        self.qs = np.random.randint(-50, 50, self.N).astype(np.int32)
        self.rs = np.random.randint(-50, 50, self.N).astype(np.int32)
        self.qrs = self.qs + self.rs
        self.K = 20
        self.targets = np.random.choice(self.N, self.K, replace=False).astype(np.int64)

    def test_shape_and_dtype(self):
        result = hex_distances(self.qs, self.rs, self.qrs, self.targets)
        self.assertEqual(result.shape, (self.N, self.K))
        self.assertEqual(result.dtype, np.float32)

    def test_matches_cpu(self):
        cpu_result = _hex_distances_cpu(self.qs, self.rs, self.qrs, self.targets)
        gpu_result = hex_distances(self.qs, self.rs, self.qrs, self.targets)
        np.testing.assert_array_equal(gpu_result, cpu_result)

    def test_known_distance(self):
        qs = np.array([0, 2, 0], dtype=np.int32)
        rs = np.array([0, 0, 2], dtype=np.int32)
        qrs = qs + rs
        targets = np.array([0, 1, 2], dtype=np.int64)
        result = hex_distances(qs, rs, qrs, targets)
        self.assertEqual(result[0, 0], 0.0)
        self.assertEqual(result[0, 1], 2.0)
        self.assertEqual(result[0, 2], 2.0)
        self.assertEqual(result[1, 2], 2.0)


class TestGPUAvailability(unittest.TestCase):
    def test_returns_bool(self):
        result = gpu_available()
        self.assertIsInstance(result, bool)


class TestCPULargeInput(unittest.TestCase):
    def test_large_n(self):
        np.random.seed(0)
        N = 5000
        qs = np.random.randint(-200, 200, N).astype(np.int32)
        rs = np.random.randint(-200, 200, N).astype(np.int32)
        qrs = qs + rs
        targets = np.random.choice(N, 100, replace=False).astype(np.int64)
        result = _hex_distances_cpu(qs, rs, qrs, targets)
        self.assertEqual(result.shape, (N, 100))
        self.assertTrue(np.all(result >= 0))


if __name__ == '__main__':
    unittest.main()
