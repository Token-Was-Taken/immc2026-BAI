"""
Minimal Patrol Finder — Wrapper for run.py

给定 best_fitness 目标值（< 1），通过二分搜索寻找满足目标的最小巡逻人员数量。
其他资源（无人机、摄像头、fence、camps）保持输入 JSON 中的值不变。

算法说明:
  1. 以输入 JSON 的 total_patrol 为基准 (scale=1.0)
  2. 仅缩放 total_patrol: scaled_patrol = max(1, round(base_patrol * scale))
  3. 在 [0, 1.0] 区间二分搜索最小的 scale, 使得 run.py 输出的
     best_fitness >= target_fitness
  4. 其他资源 (drones, cameras, fence, camps) 保持不变
  5. 每次: 生成临时 input JSON -> 调用 run.py -> 读取 output JSON 的 best_fitness

  二分搜索保证 O(log(1/eps)) 次 run.py 调用即可收敛。

Usage:
    python min_resource_finder.py <input.json> --target <fitness> [options]

Example:
    python min_resource_finder.py inputs/etosha8.json --target 0.85 --vectorized
"""

import argparse
import copy
import json
import os
import subprocess
import sys
import time
from typing import Tuple, Optional


def parse_args():
    parser = argparse.ArgumentParser(
        description="Find minimal patrol count for a target best_fitness",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("input", help="Base input JSON path")
    parser.add_argument("--target", type=float, required=True,
                        help="Target best_fitness (e.g. 0.85)")
    parser.add_argument("--output-dir", type=str, default="./min_resource_search",
                        help="Directory for temporary files and results")
    parser.add_argument("--eps", type=float, default=0.01,
                        help="Binary search precision (scale resolution)")
    parser.add_argument("--max-iterations", type=int, default=20,
                        help="Max binary search iterations")
    parser.add_argument("--vectorized", action="store_true", default=False,
                        help="Pass --vectorized to run.py")
    parser.add_argument("--gpu", action="store_true", default=False,
                        help="Pass --gpu to run.py")
    parser.add_argument("--pipeline-iterations", type=int, default=None,
                        help="Pass --max-iterations to run.py (DSSA iterations)")
    return parser.parse_args()


def load_base_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def scale_patrol(config: dict, scale: float) -> dict:
    """Scale only total_patrol by 'scale', keep all other resources unchanged."""
    cfg = copy.deepcopy(config)
    c = cfg.get("constraints", {})
    c["total_patrol"] = max(1, round(c["total_patrol"] * scale))
    cfg["constraints"] = c
    return cfg


def run_pipeline_once(
    config: dict,
    output_dir: str,
    eval_idx: int,
    vectorized: bool,
    gpu: bool,
    pipeline_iterations: Optional[int],
) -> Tuple[float, dict]:
    """
    生成临时 input/output JSON, 调用 run.py, 返回 (best_fitness, output_data).

    Returns:
        (fitness, output_json_dict)  如果失败返回 (NaN, {})
    """
    input_path = os.path.join(output_dir, f"search_{eval_idx:03d}_input.json")
    output_path = os.path.join(output_dir, f"search_{eval_idx:03d}_output.json")

    with open(input_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False)

    cmd = [
        sys.executable, "run.py", input_path, output_path,
        "--no-visualize",
        "-d", os.path.join(output_dir, f"search_{eval_idx:03d}_viz"),
    ]
    if vectorized:
        cmd.append("--vectorized")
    if gpu:
        cmd.append("--gpu")
    if pipeline_iterations is not None:
        cmd.extend(["--max-iterations", str(pipeline_iterations)])

    print(f"\n[Search #{eval_idx}] patrol={config['constraints']['total_patrol']}")

    result = subprocess.run(cmd, capture_output=True, text=True,
                            cwd=os.path.dirname(os.path.abspath(__file__)))

    if result.returncode != 0:
        print(f"  [ERROR] run.py failed:\n{result.stderr[-500:]}")
        return float("nan"), {}

    try:
        with open(output_path, "r", encoding="utf-8") as f:
            out_data = json.load(f)
        fitness = out_data.get("summary", {}).get("best_fitness", float("nan"))
        benefit = out_data.get("summary", {}).get("total_protection_benefit", float("nan"))
        print(f"  -> best_fitness={fitness:.6f}, benefit={benefit:.4f}")
        return float(fitness), out_data
    except Exception as e:
        print(f"  [ERROR] Failed to read output: {e}")
        return float("nan"), {}


def binary_search_min_patrol(
    base_config: dict,
    target_fitness: float,
    output_dir: str,
    eps: float,
    max_iter: int,
    vectorized: bool,
    gpu: bool,
    pipeline_iterations: Optional[int],
) -> dict:
    """
    二分搜索满足 target_fitness 的最小 patrol scale。

    搜索区间: [0, 1.0]
      - scale=1.0 对应原始 total_patrol
      - scale=0   对应 total_patrol=1

    不变量:
      - lo: 不满足 target (fitness < target)
      - hi: 满足 target (fitness >= target)

    Returns:
        包含搜索结果和最优配置的 dict
    """
    os.makedirs(output_dir, exist_ok=True)

    base_constraints = base_config.get("constraints", {})
    base_patrol = base_constraints.get("total_patrol", 20)

    # Track all evaluations for convergence plot
    search_history = []  # list of (eval_idx, patrol, fitness, meets_target)

    print("=" * 60)
    print("Minimal Patrol Finder")
    print("=" * 60)
    print(f"Base total_patrol: {base_patrol}")
    print(f"Other resources: fixed (drones, cameras, fence, camps unchanged)")
    print(f"Target best_fitness: {target_fitness}")
    print(f"Precision (eps): {eps}")
    print(f"Max iterations: {max_iter}")
    print("=" * 60)

    # Step 1: 检查 scale=1.0 (原始 patrol) 是否满足 target
    print("\n[Phase 1] Checking if base patrol meets target...")
    fitness_full, _ = run_pipeline_once(
        scale_patrol(base_config, 1.0), output_dir, 0,
        vectorized, gpu, pipeline_iterations,
    )
    search_history.append((0, base_patrol, fitness_full, fitness_full >= target_fitness))

    if fitness_full < target_fitness:
        print(f"\n[FAIL] Base patrol fitness={fitness_full:.6f} < target={target_fitness}")
        print("       Cannot meet target even with full patrol. Increase base patrol.")
        return {
            "success": False,
            "reason": "base_patrol_insufficient",
            "base_fitness": fitness_full,
            "target": target_fitness,
        }

    print(f"  -> Base fitness={fitness_full:.6f} >= target={target_fitness} ✓")

    # Step 2: 检查 patrol=1 是否不满足 target
    print("\n[Phase 2] Checking if minimal patrol (=1) fails target...")
    min_config = scale_patrol(base_config, 0.0)
    fitness_min, _ = run_pipeline_once(
        min_config, output_dir, 1,
        vectorized, gpu, pipeline_iterations,
    )
    search_history.append((1, min_config["constraints"]["total_patrol"], fitness_min, fitness_min >= target_fitness))

    if fitness_min >= target_fitness:
        print(f"\n[OK] Minimal patrol (1) already meets target: fitness={fitness_min:.6f}")
        result = {
            "success": True,
            "scale": 0.0,
            "fitness": fitness_min,
            "target": target_fitness,
            "patrol": min_config["constraints"]["total_patrol"],
            "base_patrol": base_patrol,
            "iterations_run": 2,
        }
        _save_result(result, output_dir)
        return result

    print(f"  -> Minimal fitness={fitness_min:.6f} < target={target_fitness} ✓")

    # Step 3: 二分搜索
    lo, hi = 0.0, 1.0
    eval_idx = 2
    best_config = scale_patrol(base_config, 1.0)
    best_fitness = fitness_full
    best_scale = 1.0

    print(f"\n[Phase 3] Binary search in [{lo}, {hi}]...")

    for i in range(max_iter):
        mid = (lo + hi) / 2.0
        if hi - lo < eps:
            print(f"\n[Converged] interval [{lo:.4f}, {hi:.4f}] < eps={eps}")
            break

        config = scale_patrol(base_config, mid)
        fitness, out_data = run_pipeline_once(
            config, output_dir, eval_idx,
            vectorized, gpu, pipeline_iterations,
        )
        meets = fitness >= target_fitness
        search_history.append((eval_idx, config["constraints"]["total_patrol"], fitness, meets))
        eval_idx += 1

        if meets:
            hi = mid
            best_scale = mid
            best_config = config
            best_fitness = fitness
            print(f"  -> ✓ meets target, try smaller (hi={hi:.4f})")
        else:
            lo = mid
            print(f"  -> ✗ below target, try larger (lo={lo:.4f})")

    final_patrol = best_config["constraints"]["total_patrol"]
    reduction = (1 - final_patrol / base_patrol) * 100

    print("\n" + "=" * 60)
    print("RESULT")
    print("=" * 60)
    print(f"Scale factor: {best_scale:.4f}")
    print(f"Achieved best_fitness: {best_fitness:.6f} (target: {target_fitness})")
    print(f"Evaluations run: {eval_idx}")
    print(f"")
    print(f"  Resource     Base  ->  Minimal  (Reduction)")
    print(f"  patrol      {base_patrol:>5}  ->  {final_patrol:>5}  ({reduction:.1f}%)")
    print(f"  (other resources unchanged)")
    print("=" * 60)

    result = {
        "success": True,
        "scale": best_scale,
        "fitness": best_fitness,
        "target": target_fitness,
        "patrol": final_patrol,
        "base_patrol": base_patrol,
        "reduction_pct": round(reduction, 2),
        "iterations_run": eval_idx,
        "search_history": [
            {"eval": e, "patrol": p, "fitness": f, "meets_target": m}
            for e, p, f, m in search_history
        ],
    }
    _plot_convergence(search_history, target_fitness, base_patrol, final_patrol, output_dir)
    _save_result(result, output_dir)
    return result


def _plot_convergence(history, target_fitness, base_patrol, final_patrol, output_dir):
    """Plot convergence report: iteration vs best_fitness and patrol count."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    evals = [h[0] for h in history]
    patrols = [h[1] for h in history]
    fitnesses = [h[2] for h in history]
    meets = [h[3] for h in history]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    # Top: fitness vs iteration
    ax1.plot(evals, fitnesses, "o-", color="#2563eb", linewidth=1.5, markersize=6, zorder=3)
    ax1.axhline(y=target_fitness, color="#dc2626", linestyle="--", linewidth=1.2,
                label=f"Target = {target_fitness:.4f}", zorder=2)
    # Color points by meet/fail
    for e, f, m in zip(evals, fitnesses, meets):
        color = "#16a34a" if m else "#dc2626"
        ax1.scatter([e], [f], color=color, s=50, zorder=4)
    ax1.set_ylabel("Best Fitness", fontsize=12)
    ax1.set_title("Convergence: Best Fitness vs Search Iteration", fontsize=13, fontweight="bold")
    ax1.legend(fontsize=10, loc="best")
    ax1.grid(True, alpha=0.3)

    # Bottom: patrol count vs iteration
    ax2.bar(evals, patrols, color="#6366f1", alpha=0.7, width=0.5)
    ax2.axhline(y=base_patrol, color="#64748b", linestyle=":", linewidth=1,
                label=f"Base patrol = {base_patrol}", zorder=2)
    ax2.axhline(y=final_patrol, color="#16a34a", linestyle="--", linewidth=1.2,
                label=f"Minimal patrol = {final_patrol}", zorder=2)
    ax2.set_xlabel("Search Iteration", fontsize=12)
    ax2.set_ylabel("Patrol Count", fontsize=12)
    ax2.set_title("Patrol Count per Iteration", fontsize=13, fontweight="bold")
    ax2.legend(fontsize=10, loc="best")
    ax2.grid(True, alpha=0.3, axis="y")

    plt.tight_layout()
    plot_path = os.path.join(output_dir, "convergence_report.png")
    fig.savefig(plot_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Convergence report saved to: {plot_path}")


def _save_result(result: dict, output_dir: str):
    result_path = os.path.join(output_dir, "min_resource_result.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\nResult saved to: {result_path}")


def main():
    args = parse_args()
    base_config = load_base_config(args.input)

    t0 = time.time()
    result = binary_search_min_patrol(
        base_config=base_config,
        target_fitness=args.target,
        output_dir=args.output_dir,
        eps=args.eps,
        max_iter=args.max_iterations,
        vectorized=args.vectorized,
        gpu=args.gpu,
        pipeline_iterations=args.pipeline_iterations,
    )
    elapsed = time.time() - t0
    print(f"\nTotal elapsed: {elapsed:.1f}s")

    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
