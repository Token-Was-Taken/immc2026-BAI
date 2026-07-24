"""
从已有的 eval_*_output.json 文件重建 _checkpoint.json，
使断点续传功能能接上旧任务。

Usage:
    python recover_checkpoint.py --output-dir figures/final/sobol --params inputs/sobol-params.json
"""
import argparse
import json
import os
import glob


def recover(output_dir, param_names):
    pattern = os.path.join(output_dir, "eval_*_output.json")
    output_files = glob.glob(pattern)

    records = []
    skipped = 0

    for out_path in sorted(output_files):
        basename = os.path.basename(out_path)
        # eval_00000_output.json -> 0
        idx = int(basename.split("_")[1])

        input_path = os.path.join(output_dir, f"eval_{idx:05d}_input.json")

        try:
            with open(out_path, "r", encoding="utf-8") as f:
                result = json.load(f)

            best_fitness = result.get("summary", {}).get("best_fitness", float("nan"))
            total_protection_benefit = result.get("summary", {}).get("total_protection_benefit", float("nan"))

            # Read params from input file
            params = {}
            if os.path.exists(input_path):
                with open(input_path, "r", encoding="utf-8") as f:
                    input_config = json.load(f)
                constraints = input_config.get("constraints", {})
                for name in param_names:
                    params[name] = constraints.get(name, 0)

            records.append({
                "eval_idx": idx,
                "success": True,
                "params": params,
                "best_fitness": float(best_fitness),
                "total_protection_benefit": float(total_protection_benefit),
                "error": None
            })
        except Exception as e:
            print(f"  [SKIP] eval_{idx:05d}: {e}")
            skipped += 1

    records.sort(key=lambda r: r["eval_idx"])

    # Save checkpoint
    ckpt_path = os.path.join(output_dir, "_checkpoint.json")
    with open(ckpt_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False)

    print(f"Recovered {len(records)} evaluations (skipped {skipped})")
    print(f"Checkpoint saved to: {ckpt_path}")
    print(f"Eval range: {records[0]['eval_idx']} - {records[-1]['eval_idx']}")

    # Find gaps
    all_indices = set(r["eval_idx"] for r in records)
    max_idx = records[-1]["eval_idx"]
    gaps = [i for i in range(max_idx + 1) if i not in all_indices]
    if gaps:
        print(f"Missing eval indices ({len(gaps)}): {gaps[:20]}{'...' if len(gaps) > 20 else ''}")
    else:
        print(f"No gaps in range 0-{max_idx}")


def main():
    parser = argparse.ArgumentParser(description="Rebuild checkpoint from existing eval output files")
    parser.add_argument("--output-dir", required=True, help="Sobol output directory")
    parser.add_argument("--params", default=None, help="Params JSON file (to get param names)")
    args = parser.parse_args()

    # Determine param names
    if args.params and os.path.exists(args.params):
        with open(args.params, "r", encoding="utf-8") as f:
            param_defs = json.load(f)
        param_names = [p["name"] for p in param_defs]
    else:
        # Default from sobol_sensitivity.py
        param_names = ["total_patrol", "total_drones", "total_cameras", "total_camps"]

    print(f"Param names: {param_names}")
    print(f"Output dir: {args.output_dir}")
    recover(args.output_dir, param_names)


if __name__ == "__main__":
    main()
