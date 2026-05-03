"""
多资源并行敏感性分析脚本

并行运行多种资源的单因素敏感性分析，最后自动调用 sensitivity_report.py
生成可视化报告。

用法：
    # 使用默认范围分析所有资源
    python sensitivity_batch.py --input base.json

    # 指定部分资源及自定义范围
    python sensitivity_batch.py --input base.json \
        --ranges patrol:0:50:5 camera:0:400:10 drone:0:10:1

    # 指定并行数和向量化模式
    python sensitivity_batch.py --input base.json --workers 4 --vectorized

    # 跳过报告生成
    python sensitivity_batch.py --input base.json --no-report
"""

import argparse
import json
import os
import sys
import time
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, List, Tuple, Optional


DEFAULT_RANGES = {
    "patrol": (0, 50, 5),
    "camera": (0, 20, 2),
    "drone": (0, 10, 1),
    "camp": (0, 5, 1),
    "fence": (0, 100, 10),
}


def parse_ranges(ranges_input: Optional[List[str]]) -> Dict[str, Tuple[int, int, int]]:
    result = {}
    if ranges_input is None:
        return dict(DEFAULT_RANGES)
    for item in ranges_input:
        parts = item.split(":")
        if len(parts) != 4:
            raise ValueError(
                f"Invalid range format '{item}', expected resource:min:max:step"
            )
        name = parts[0].strip().lower()
        min_val, max_val, step = int(parts[1]), int(parts[2]), int(parts[3])
        if min_val < 0 or max_val < min_val or step <= 0:
            raise ValueError(
                f"Invalid range values for '{name}': min={min_val}, max={max_val}, step={step}"
            )
        result[name] = (min_val, max_val, step)
    return result


def run_single_resource(args_tuple):
    input_path, resource, range_tuple, output_dir, vectorized = args_tuple
    min_val, max_val, step = range_tuple
    cmd = [
        sys.executable,
        os.path.join(os.path.dirname(__file__), "sensitivity_analysis.py"),
        "--input", input_path,
        "--resource", resource,
        "--range", str(min_val), str(max_val), str(step),
        "--output", output_dir,
    ]
    if vectorized:
        cmd.append("--vectorized")

    print(f"[START] {resource}: range={min_val}-{max_val}, step={step}")
    start = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        elapsed = time.time() - start
        if result.returncode != 0:
            print(f"[FAIL]  {resource}: error after {elapsed:.1f}s")
            print(result.stderr[:500])
            return {"resource": resource, "success": False, "error": result.stderr[:200], "elapsed": elapsed}
        print(f"[DONE]  {resource}: completed in {elapsed:.1f}s")
        return {"resource": resource, "success": True, "elapsed": elapsed}
    except Exception as e:
        elapsed = time.time() - start
        print(f"[FAIL]  {resource}: exception after {elapsed:.1f}s - {e}")
        return {"resource": resource, "success": False, "error": str(e), "elapsed": elapsed}


def generate_reports(output_dir: str, report_dir: Optional[str] = None):
    report_script = os.path.join(os.path.dirname(__file__), "sensitivity_report.py")
    if not os.path.exists(report_script):
        print(f"\n[WARN] sensitivity_report.py not found, skipping report generation")
        return

    target_dir = report_dir or output_dir
    cmd = [
        sys.executable, report_script,
        output_dir, "--all",
        "--out_dir", target_dir,
    ]
    print(f"\n{'=' * 60}")
    print("Generating sensitivity reports...")
    print(f"{'=' * 60}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[WARN] Report generation failed: {result.stderr[:300]}")
        else:
            print(result.stdout)
            print(f"[OK] Reports saved to {target_dir}")
    except Exception as e:
        print(f"[WARN] Report generation failed: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="多资源并行敏感性分析",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog="""
Examples:
  # Analyze all resources with default ranges (4 parallel workers)
  python sensitivity_batch.py --input base.json --workers 4

  # Analyze specific resources with custom ranges
  python sensitivity_batch.py --input base.json \\
      --ranges patrol:0:50:5 camera:0:400:10 drone:0:10:1

  # Analyze all resources, override patrol range
  python sensitivity_batch.py --input base.json --ranges patrol:0:100:10

  # Skip report generation
  python sensitivity_batch.py --input base.json --no-report

Range format:  resource:min:max:step
  e.g.  camera:0:400:10  means camera count from 0 to 400, step 10
        """
    )
    parser.add_argument("--input", "-i", required=True, help="基础输入 JSON 路径")
    parser.add_argument("--ranges", nargs="+", default=None,
                        help="资源范围定义，格式 resource:min:max:step。"
                             "未指定的资源使用默认范围。"
                             "例: patrol:0:50:5 camera:0:400:10")
    parser.add_argument("--output", "-o", default="./sensitivity_results",
                        help="敏感性分析输出目录")
    parser.add_argument("--report-dir", default=None,
                        help="报告图片输出目录（默认与 --output 相同）")
    parser.add_argument("--workers", "-w", type=int, default=1,
                        help="并行工作进程数（每种资源一个进程）")
    parser.add_argument("--vectorized", action="store_true", default=False,
                        help="使用向量化模式（大规模地图推荐）")
    parser.add_argument("--no-report", action="store_true", default=False,
                        help="跳过报告生成")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: input file not found: {args.input}")
        sys.exit(1)

    ranges = parse_ranges(args.ranges)

    print("=" * 60)
    print("Multi-Resource Sensitivity Analysis")
    print("=" * 60)
    print(f"Input:       {args.input}")
    print(f"Output:      {args.output}")
    print(f"Workers:     {args.workers}")
    print(f"Vectorized:  {args.vectorized}")
    print(f"\nResources to analyze:")
    for res, (lo, hi, step) in ranges.items():
        n_points = len(range(lo, hi + 1, step))
        print(f"  {res:<10} range=[{lo}, {hi}]  step={step}  ({n_points} points)")
    print("=" * 60)

    os.makedirs(args.output, exist_ok=True)

    task_args = [
        (os.path.abspath(args.input), res, rng, args.output, args.vectorized)
        for res, rng in ranges.items()
    ]

    results = []
    start_time = time.time()

    if args.workers <= 1:
        for task in task_args:
            results.append(run_single_resource(task))
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(run_single_resource, t): t[1] for t in task_args}
            for future in as_completed(futures):
                results.append(future.result())

    elapsed = time.time() - start_time

    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    print(f"\n{'=' * 60}")
    print("Summary")
    print(f"{'=' * 60}")
    print(f"Total:     {len(results)} resources")
    print(f"Success:   {len(successful)}")
    print(f"Failed:    {len(failed)}")
    print(f"Elapsed:   {elapsed:.1f}s")
    if failed:
        print("\nFailed resources:")
        for r in failed:
            print(f"  {r['resource']}: {r.get('error', 'unknown')[:100]}")

    config_path = os.path.join(args.output, "batch_config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump({
            "input": os.path.abspath(args.input),
            "ranges": {k: list(v) for k, v in ranges.items()},
            "workers": args.workers,
            "vectorized": args.vectorized,
            "results": results,
            "elapsed_seconds": elapsed,
        }, f, indent=2, ensure_ascii=False)

    if not args.no_report and successful:
        generate_reports(args.output, args.report_dir)

    print(f"\n[OK] Batch analysis complete. Results in: {args.output}")


if __name__ == "__main__":
    main()
