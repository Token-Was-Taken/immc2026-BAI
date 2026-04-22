"""
Monte Carlo Robustness Analysis for Wildlife Protection Optimization

Runs N trials of the DSSA optimizer with randomly sampled resource constraints,
then generates a robustness analysis chart summarizing the distribution of outcomes.

Usage:
    python monte_carlo_robust.py <base_config.json> [options]
"""

import argparse
import copy
import json
import os
import sys

import numpy as np


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Monte Carlo robustness analysis for the wildlife protection optimizer."
    )
    parser.add_argument(
        "base_config",
        help="Path to the base input JSON configuration file.",
    )
    parser.add_argument(
        "--num-trials",
        type=int,
        default=100,
        metavar="N",
        help="Number of Monte Carlo trials to run (default: 100).",
    )
    parser.add_argument(
        "--output-dir",
        default="./robust_results",
        metavar="DIR",
        help="Directory for trial outputs and the final chart (default: ./robust_results).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="SEED",
        help="Random seed for reproducibility.",
    )
    parser.add_argument(
        "--vectorized",
        action="store_true",
        help="Use the vectorized coverage model (recommended for grids > 1000).",
    )
    parser.add_argument(
        "--no-visualize",
        action="store_true",
        help="Skip chart generation; write summary JSON only.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=os.cpu_count(),
        metavar="W",
        help="Number of parallel worker processes (default: os.cpu_count()).",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_base_config(path: str) -> dict:
    """Load and parse the base JSON configuration file.

    Raises SystemExit with a descriptive message if the file is missing or
    contains invalid JSON.
    """
    if not os.path.exists(path):
        sys.exit(f"Error: base config file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        sys.exit(f"Error: invalid JSON in base config '{path}': {exc}")


# ---------------------------------------------------------------------------
# Constraint sampling
# ---------------------------------------------------------------------------

def sample_constraints(rng: np.random.Generator) -> dict:
    """Draw one set of integer resource constraints from the fixed distributions.

    Distributions (inclusive on both ends):
        total_patrol   ~ Uniform(15, 25)
        total_drones   ~ Uniform(2,  6)
        total_cameras  ~ Uniform(8,  15)
        total_camps    ~ Uniform(3,  7)

    Args:
        rng: A numpy random Generator (e.g. np.random.default_rng(seed)).

    Returns:
        dict with keys total_patrol, total_drones, total_cameras, total_camps.
    """
    return {
        "total_patrol":  int(rng.integers(15, 25, endpoint=True)),
        "total_drones":  int(rng.integers(2,  6,  endpoint=True)),
        "total_cameras": int(rng.integers(8,  15, endpoint=True)),
        "total_camps":   int(rng.integers(3,  7,  endpoint=True)),
    }


# ---------------------------------------------------------------------------
# Placeholder stubs (implemented in later tasks)
# ---------------------------------------------------------------------------

def run_trial(base_config: dict, constraints_sample: dict, trial_idx: int, output_dir: str,
              vectorized: bool = False) -> dict:
    """Execute one Monte Carlo trial.

    Deep-copies base_config, overrides the four constraint fields, writes
    the trial input JSON, calls run_pipeline, reads the output JSON, and
    returns a trial record dict.

    Args:
        base_config: The original base configuration dict (never mutated).
        constraints_sample: Dict with total_patrol/drones/cameras/camps.
        trial_idx: Zero-based trial index.
        output_dir: Directory where trial input/output JSONs are written.

    Returns:
        Trial record dict with keys: trial, success, constraints,
        best_fitness, total_protection_benefit, error.
    """
    from protection_pipeline import run_pipeline  # local import to keep module importable without pipeline deps

    input_path = os.path.join(output_dir, f"trial_{trial_idx:04d}_input.json")
    output_path = os.path.join(output_dir, f"trial_{trial_idx:04d}_output.json")

    record = {
        "trial": trial_idx,
        "success": False,
        "constraints": constraints_sample,
        "best_fitness": None,
        "total_protection_benefit": None,
        "error": None,
    }

    try:
        # Deep-copy so base_config is never mutated
        trial_config = copy.deepcopy(base_config)

        # Override only the four sampled constraint fields
        if "constraints" not in trial_config:
            trial_config["constraints"] = {}
        for key in ("total_patrol", "total_drones", "total_cameras", "total_camps"):
            trial_config["constraints"][key] = constraints_sample[key]

        # Write trial input JSON
        os.makedirs(output_dir, exist_ok=True)
        with open(input_path, "w", encoding="utf-8") as fh:
            json.dump(trial_config, fh)

        # Run the pipeline
        run_pipeline(input_path, output_path, vectorized=vectorized)

        # Read output and extract metrics
        with open(output_path, "r", encoding="utf-8") as fh:
            output = json.load(fh)

        summary = output.get("summary", {})
        record["best_fitness"] = summary.get("best_fitness")
        record["total_protection_benefit"] = summary.get("total_protection_benefit")
        record["success"] = True

    except Exception as exc:  # noqa: BLE001
        record["error"] = str(exc)

    return record


# ---------------------------------------------------------------------------
# Parallel worker (must be top-level for ProcessPoolExecutor pickling on Windows)
# ---------------------------------------------------------------------------

def _parallel_worker(args_tuple):
    """Top-level picklable worker function for ProcessPoolExecutor.

    Unpacks (base_config, constraints, trial_idx, output_dir, vectorized) and delegates
    to run_trial. Must be defined at module level so it can be pickled on
    Windows (spawn start method).
    """
    base_config, constraints, trial_idx, output_dir, vectorized = args_tuple
    return run_trial(base_config, constraints, trial_idx, output_dir, vectorized=vectorized)


def run_monte_carlo(base_config: dict, num_trials: int, output_dir: str, seed,
                    workers: int = 1, vectorized: bool = False) -> list:
    """Orchestrate N Monte Carlo trials and return a list of trial records.

    Pre-generates all N Constraint_Sample dicts in the main process before
    dispatching workers, so the constraint sequence is deterministic regardless
    of worker count.

    Args:
        base_config: The base configuration dict (never mutated).
        num_trials: Number of trials to run.
        output_dir: Directory where trial input/output JSONs are written.
        seed: Integer seed for reproducibility, or None for a random seed.
        workers: Number of parallel worker processes. When 1, runs sequentially
                 via a plain for loop (no subprocess overhead). Otherwise uses
                 ProcessPoolExecutor with max_workers=workers.

    Returns:
        List of trial record dicts sorted by trial index (one per trial,
        including failed ones).
    """
    import concurrent.futures

    os.makedirs(output_dir, exist_ok=True)

    # Pre-generate ALL constraint samples in the main process to preserve
    # seed determinism regardless of worker count.
    rng = np.random.default_rng(seed)
    all_constraints = [sample_constraints(rng) for _ in range(num_trials)]

    results = []

    if workers == 1:
        # Sequential fallback — no subprocess overhead, useful for debugging/testing.
        for i in range(num_trials):
            try:
                record = run_trial(base_config, all_constraints[i], i, output_dir, vectorized=vectorized)
            except Exception as exc:  # noqa: BLE001
                print(f"[Trial {i + 1}/{num_trials}] FAILED: {exc}")
                record = {
                    "trial": i,
                    "success": False,
                    "constraints": all_constraints[i],
                    "best_fitness": None,
                    "total_protection_benefit": None,
                    "error": str(exc),
                }
            print(f"[Trial {i + 1}/{num_trials} done]")
            results.append(record)
    else:
        # Parallel execution via ProcessPoolExecutor.
        args_list = [
            (base_config, all_constraints[i], i, output_dir, vectorized)
            for i in range(num_trials)
        ]

        future_to_idx = {}
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
            for i, args in enumerate(args_list):
                future = executor.submit(_parallel_worker, args)
                future_to_idx[future] = i

            for future in concurrent.futures.as_completed(future_to_idx):
                i = future_to_idx[future]
                exc = future.exception()
                if exc is not None:
                    print(f"[Trial {i + 1}/{num_trials}] FAILED: {exc}")
                    record = {
                        "trial": i,
                        "success": False,
                        "constraints": all_constraints[i],
                        "best_fitness": None,
                        "total_protection_benefit": None,
                        "error": str(exc),
                    }
                else:
                    record = future.result()
                print(f"[Trial {i + 1}/{num_trials} done]")
                results.append(record)

        # Sort by trial index since as_completed() may yield out of order.
        results.sort(key=lambda r: r["trial"])

    return results


def save_summary(results: list, meta: dict, output_dir: str,
                 elapsed_seconds: float = None, workers: int = None) -> None:
    """Write results_summary.json to output_dir.

    Args:
        results: List of trial record dicts.
        meta: Metadata dict (base_config path, num_trials, seed, counts).
        output_dir: Directory where the summary file is written.
        elapsed_seconds: Wall-clock time (seconds) taken by run_monte_carlo.
        workers: Number of parallel worker processes used.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Augment meta with timing and worker info
    if elapsed_seconds is not None:
        meta["elapsed_seconds"] = round(elapsed_seconds, 3)
        num_trials = meta.get("num_trials", len(results))
        meta["trials_per_second"] = (
            round(num_trials / elapsed_seconds, 4) if elapsed_seconds > 0 else None
        )
    if workers is not None:
        meta["workers"] = workers

    summary = {"meta": meta, "trials": results}
    summary_path = os.path.join(output_dir, "results_summary.json")
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)


def plot_robustness(results: list, output_dir: str) -> None:
    """Generate robustness_analysis.png with a 3×2 panel layout.

    Panels:
        Row 1: histogram of best_fitness | histogram of total_protection_benefit
        Row 2: scatter total_patrol vs fitness | scatter total_drones vs fitness
        Row 3: scatter total_cameras vs fitness | scatter total_camps vs fitness

    Each histogram is annotated with mean, std, min, max.
    Each scatter plot includes a linear trend line.

    Args:
        results: List of trial record dicts (may include failed trials).
        output_dir: Directory where robustness_analysis.png is saved.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    successful = [r for r in results if r.get("success")]
    if len(successful) < 2:
        print(
            f"Warning: only {len(successful)} successful trial(s); "
            "skipping chart generation (need at least 2)."
        )
        return

    fitness = np.array([r["best_fitness"] for r in successful], dtype=float)
    benefit = np.array([r["total_protection_benefit"] for r in successful], dtype=float)
    patrol  = np.array([r["constraints"]["total_patrol"]  for r in successful], dtype=float)
    drones  = np.array([r["constraints"]["total_drones"]  for r in successful], dtype=float)
    cameras = np.array([r["constraints"]["total_cameras"] for r in successful], dtype=float)
    camps   = np.array([r["constraints"]["total_camps"]   for r in successful], dtype=float)

    fig, axes = plt.subplots(3, 2, figsize=(14, 12))
    fig.suptitle("Monte Carlo Robustness Analysis", fontsize=14, fontweight="bold")

    def _hist(ax, data, label):
        ax.hist(data, bins=20, color="steelblue", edgecolor="white", alpha=0.85)
        ax.set_xlabel(label)
        ax.set_ylabel("Count")
        stats_text = (
            f"mean={data.mean():.4f}  std={data.std():.4f}\n"
            f"min={data.min():.4f}  max={data.max():.4f}"
        )
        ax.set_title(f"{label} Distribution\n{stats_text}", fontsize=9)

    def _scatter(ax, x, y, xlabel, ylabel="Best Fitness"):
        ax.scatter(x, y, alpha=0.6, s=20, color="steelblue")
        # Linear trend line
        if len(np.unique(x)) > 1:
            coeffs = np.polyfit(x, y, 1)
            x_line = np.linspace(x.min(), x.max(), 200)
            ax.plot(x_line, np.polyval(coeffs, x_line), color="tomato", linewidth=1.5)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.set_title(f"{xlabel} vs {ylabel}", fontsize=9)

    _hist(axes[0, 0], fitness, "Best Fitness")
    _hist(axes[0, 1], benefit, "Total Protection Benefit")
    _scatter(axes[1, 0], patrol,  fitness, "Total Patrol")
    _scatter(axes[1, 1], drones,  fitness, "Total Drones")
    _scatter(axes[2, 0], cameras, fitness, "Total Cameras")
    _scatter(axes[2, 1], camps,   fitness, "Total Camps")

    fig.tight_layout()
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "robustness_analysis.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Robustness chart saved to {out_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv=None):
    import time

    args = parse_args(argv)
    os.makedirs(args.output_dir, exist_ok=True)

    base_config = load_base_config(args.base_config)

    t_start = time.monotonic()
    results = run_monte_carlo(base_config, args.num_trials, args.output_dir, args.seed,
                              args.workers, vectorized=args.vectorized)
    elapsed = time.monotonic() - t_start

    meta = {
        "base_config": args.base_config,
        "num_trials": args.num_trials,
        "seed": args.seed,
        "successful_trials": sum(1 for r in results if r.get("success")),
        "failed_trials": sum(1 for r in results if not r.get("success")),
    }
    save_summary(results, meta, args.output_dir, elapsed_seconds=elapsed, workers=args.workers)

    if not args.no_visualize:
        plot_robustness(results, args.output_dir)


if __name__ == "__main__":
    main()
