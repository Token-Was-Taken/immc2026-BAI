#!/usr/bin/env python3
"""
批量运行多场景优化并生成保护效益对比图表

用法:
    python run_multi_scenario.py --prefix etosha8_ --max-iterations 10 --vectorized
    python run_multi_scenario.py --prefix etosha8_ --max-iterations 20 --workers 4 --out-base figures/etosha/temporal
"""

import argparse
import subprocess
import os
import sys
import json


SCENARIOS = ['dry-day', 'dry-night', 'rainy-day', 'rainy-night']


def main():
    parser = argparse.ArgumentParser(
        description="批量运行多场景优化并生成保护效益对比图表",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--prefix', '-p', required=True,
                        help='输入文件前缀（如 etosha8_），脚本会查找 {prefix}{scenario}.json')
    parser.add_argument('--out-base', '-o', default='figures/scenario_results',
                        help='输出基础目录')
    parser.add_argument('--max-iterations', '-m', type=int, default=10,
                        help='DSSA 最大迭代次数')
    parser.add_argument('--workers', '-w', type=int, default=None,
                        help='并行工作进程数')
    parser.add_argument('--vectorized', action='store_true',
                        help='使用向量化覆盖模型')
    parser.add_argument('--no-visualize', action='store_true',
                        help='禁用可视化输出')
    parser.add_argument('--dry-run', action='store_true',
                        help='只打印命令不执行')
    parser.add_argument('--skip-optimize', action='store_true',
                        help='跳过优化，直接生成图表（需已有输出）')
    parser.add_argument('--inputs-dir', default='inputs',
                        help='输入文件目录')
    parser.add_argument('--fig-dpi', type=int, default=150,
                        help='图表输出 DPI')
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    input_files = []
    for scenario in SCENARIOS:
        filename = f"{args.prefix}{scenario}.json"
        filepath = os.path.join(script_dir, args.inputs_dir, filename)
        if not os.path.exists(filepath):
            print(f"错误: 输入文件不存在 {filepath}")
            return
        input_files.append(filepath)

    out_base_abs = os.path.abspath(args.out_base)
    os.makedirs(out_base_abs, exist_ok=True)

    output_files = []
    for scenario, input_file in zip(SCENARIOS, input_files):
        out_dir = os.path.join(out_base_abs, scenario)
        os.makedirs(out_dir, exist_ok=True)
        output_file = os.path.join(out_dir, f"{scenario}_output.json")
        output_files.append(output_file)

    if not args.skip_optimize:
        print("=" * 60)
        print("批量运行场景优化")
        print("=" * 60)

        processes = []
        for i, (scenario, input_file, output_file) in enumerate(zip(SCENARIOS, input_files, output_files), 1):
            out_dir = os.path.dirname(output_file)
            
            cmd = [sys.executable, os.path.join(script_dir, 'run.py'), input_file, output_file]
            cmd.append(f"--max-iterations={args.max_iterations}")
            cmd.append(f"--out_dir={out_dir}")
            
            if args.vectorized:
                cmd.append("--vectorized")
            if args.no_visualize:
                cmd.append("--no-visualize")

            print(f"\n[{i}/{len(SCENARIOS)}] 场景: {scenario}")
            print(f"  输入: {input_file}")
            print(f"  输出: {output_file}")
            print(f"  命令: {' '.join(cmd)}")

            if not args.dry_run:
                proc = subprocess.Popen(cmd, cwd=os.path.dirname(__file__))
                processes.append((proc, scenario))

        if not args.dry_run:
            print("\n等待所有场景完成...")
            completed = 0
            failed = []
            while processes:
                remaining = []
                for proc, scenario in processes:
                    if proc.poll() is not None:
                        completed += 1
                        if proc.returncode == 0:
                            print(f"  [OK] 场景 {scenario} 运行成功 ({completed}/{len(SCENARIOS)})")
                        else:
                            print(f"  [!] 场景 {scenario} 运行失败，退出码: {proc.returncode}")
                            failed.append(scenario)
                    else:
                        remaining.append((proc, scenario))
                processes = remaining

            if failed:
                print(f"\n警告: 以下场景运行失败: {', '.join(failed)}")

    print("\n" + "=" * 60)
    print("生成保护效益对比图表")
    print("=" * 60)

    fig_path = os.path.join(out_base_abs, "benefit_by_scenario.png")
    
    valid_outputs = []
    valid_scenarios = []
    for scenario, output_file in zip(SCENARIOS, output_files):
        if os.path.exists(output_file):
            valid_outputs.append(output_file)
            valid_scenarios.append(scenario)
        else:
            print(f"  跳过缺失的输出文件: {output_file}")

    if len(valid_outputs) < 2:
        print(f"  [!] 有效输出文件不足（需要至少2个），跳过图表生成")
    else:
        cmd = [sys.executable, os.path.join(script_dir, 'plot_protection_benefit.py'), '--output-fig', fig_path]
        cmd.append(f"--dpi={args.fig_dpi}")
        cmd.append('--outputs')
        cmd.extend(valid_outputs)
        cmd.append('--scenarios')
        cmd.extend(valid_scenarios)

        print(f"  图表输出: {fig_path}")
        print(f"  命令: {' '.join(cmd)}")

        if not args.dry_run:
            result = subprocess.run(cmd, cwd=os.path.dirname(__file__))
            if result.returncode != 0:
                print(f"  [!] 图表生成失败，退出码: {result.returncode}")
            else:
                print(f"  [OK] 图表生成成功")

    print("\n" + "=" * 60)
    print("批量运行完成")
    print("=" * 60)
    print(f"输出目录: {args.out_base}")
    print(f"图表路径: {fig_path}")


if __name__ == '__main__':
    main()
