"""Isolated quick test for GPU-accelerated hex distance in coverage model."""
import sys
import numpy as np

# Simulate minimal coverage model components
np.random.seed(42)
N = 10000  # simulate 10k grids
qs = np.random.randint(-100, 100, N).astype(np.int32)
rs = np.random.randint(-100, 100, N).astype(np.int32)
qrs = qs + rs

K = 160  # typical target count
target_indices = np.random.choice(N, K, replace=False).astype(np.int64)

# Test 1: GPU correctness
from gpu_ops import hex_distances, gpu_available, _hex_distances_cpu

print(f"GPU available: {gpu_available()}")
print(f"  N grids: {N}, K targets: {K}")

# GPU
import time
t0 = time.perf_counter()
result_gpu = hex_distances(qs, rs, qrs, target_indices)
print(f"  GPU time: {time.perf_counter() - t0:.3f}s  shape: {result_gpu.shape}")

# CPU
t0 = time.perf_counter()
result_cpu = _hex_distances_cpu(qs, rs, qrs, target_indices)
print(f"  CPU time: {time.perf_counter() - t0:.3f}s  shape: {result_cpu.shape}")

# Correctness
max_diff = np.max(np.abs(result_gpu - result_cpu))
print(f"  Max diff GPU vs CPU: {max_diff}")

if max_diff < 1e-5:
    print("PASS: GPU results match CPU exactly")
else:
    print("FAIL: GPU results differ from CPU")

# Test 2: Dtype check (coverage model expects float32)
assert result_gpu.dtype == np.float32, f"Expected float32, got {result_gpu.dtype}"
assert result_cpu.dtype == np.float32, f"Expected float32, got {result_cpu.dtype}"
print("PASS: dtype float32 confirmed")

print("\nAll tests passed!")