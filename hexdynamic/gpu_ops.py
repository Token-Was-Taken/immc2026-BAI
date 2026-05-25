"""
gpu_ops.py — GPU-accelerated hex-grid distance computation via OpenCL.

Auto-falls back to CPU numpy if GPU is unavailable.
"""
import numpy as np

_GPU_AVAILABLE = False
_GPU_CTX = None
_GPU_QUEUE = None
_GPU_PROG = None
_GPU_KERNEL = None  # cached kernel to avoid RepeatedKernelRetrieval
_GPU_DISABLED = False  # set to True after an OOM to skip GPU in this process

# OpenCL kernel: computes hex distances (N × K) in float32
_HEX_DIST_KERNEL = """
__kernel void hex_distances(
    __global const int *qs,      // (N,)
    __global const int *rs,      // (N,)
    __global const int *qr,      // (N,) q+r
    __global const int *targets, // (K,) indices into qs/rs/qr
    __global float *output,      // (N, K) float32 distances
    const int N,
    const int K,
    const int t_offset           // start offset in targets
) {
    int row = get_global_id(0);  // 0..N-1
    int col = get_global_id(1);  // 0..chunk_K-1

    if (row >= N || col >= K) return;

    int t_idx = targets[t_offset + col];
    int dq = abs(qs[row] - qs[t_idx]);
    int dr = abs(rs[row] - rs[t_idx]);
    int ds = abs(qr[row] - qr[t_idx]);
    int dist = (dq + dr + ds) >> 1;

    output[row * K + col] = (float)dist;
}
"""


def _init_gpu():
    """Lazy-initialize OpenCL context. Returns True if GPU is available."""
    global _GPU_AVAILABLE, _GPU_CTX, _GPU_QUEUE, _GPU_PROG, _GPU_KERNEL
    if _GPU_CTX is not None:
        return _GPU_AVAILABLE
    try:
        import pyopencl as cl
        _GPU_CTX = cl.create_some_context(interactive=False)
        _GPU_QUEUE = cl.CommandQueue(_GPU_CTX)
        _GPU_PROG = cl.Program(_GPU_CTX, _HEX_DIST_KERNEL).build()
        _GPU_KERNEL = _GPU_PROG.hex_distances  # cache to avoid repeated retrieval
        _GPU_AVAILABLE = True
    except Exception as e:
        _GPU_AVAILABLE = False
    return _GPU_AVAILABLE


def gpu_available() -> bool:
    """Check if GPU acceleration is available."""
    return _init_gpu()


def hex_distances(qs: np.ndarray, rs: np.ndarray, qrs: np.ndarray,
                  target_indices: np.ndarray) -> np.ndarray:
    """
    Compute hex-grid distances from all N grids to K target grids.

    GPU-accelerated via OpenCL. Falls back to CPU numpy if GPU unavailable or OOM.
    """
    global _GPU_DISABLED

    if _GPU_DISABLED or not _init_gpu():
        return _hex_distances_cpu(qs, rs, qrs, target_indices)

    import pyopencl as cl

    N = len(qs)
    K = len(target_indices)

    qs = np.asarray(qs, dtype=np.int32)
    rs = np.asarray(rs, dtype=np.int32)
    qrs = np.asarray(qrs, dtype=np.int32)
    targets = np.asarray(target_indices, dtype=np.int32)

    mf = cl.mem_flags
    try:
        qs_buf = cl.Buffer(_GPU_CTX, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=qs)
        rs_buf = cl.Buffer(_GPU_CTX, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=rs)
        qr_buf = cl.Buffer(_GPU_CTX, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=qrs)
        targets_buf = cl.Buffer(_GPU_CTX, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=targets)

        result = np.empty((N, K), dtype=np.float32)

        chunk_size = 4096
        for t_start in range(0, K, chunk_size):
            t_end = min(t_start + chunk_size, K)
            kc = t_end - t_start

            out_buf = cl.Buffer(_GPU_CTX, mf.WRITE_ONLY, N * kc * 4)

            _GPU_KERNEL(
                _GPU_QUEUE, (N, kc), None,
                qs_buf, rs_buf, qr_buf, targets_buf,
                out_buf,
                np.int32(N), np.int32(kc), np.int32(t_start)
            )

            cl.enqueue_copy(_GPU_QUEUE,
                            result[:, t_start:t_end].ravel(),
                            out_buf)

        return result

    except cl.RuntimeError as e:
        # GPU out of resources (likely concurrent multiprocessing) — fall back to CPU
        # and disable GPU for future calls in this process
        _GPU_DISABLED = True
        return _hex_distances_cpu(qs, rs, qrs, target_indices)

    except Exception:
        # Any other GPU error — fall back to CPU
        _GPU_DISABLED = True
        return _hex_distances_cpu(qs, rs, qrs, target_indices)


def _hex_distances_cpu(qs: np.ndarray, rs: np.ndarray, qrs: np.ndarray,
                        target_indices: np.ndarray) -> np.ndarray:
    """CPU fallback for hex distance computation."""
    N = len(qs)
    K = len(target_indices)
    result = np.empty((N, K), dtype=np.float32)

    t_qs = qs[target_indices]
    t_rs = rs[target_indices]
    t_qrs = qrs[target_indices]

    chunk = 2048
    for start in range(0, N, chunk):
        end = min(start + chunk, N)
        dq = np.abs(qs[start:end, None] - t_qs[None, :])
        dr = np.abs(rs[start:end, None] - t_rs[None, :])
        ds = np.abs(qrs[start:end, None] - t_qrs[None, :])
        result[start:end, :] = ((dq + dr + ds) >> 1)

    return result