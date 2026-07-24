#!/usr/bin/env python3
"""
生成保护效益对比图表：Total Protection Benefit 和 Best Fitness by Scenario

用法:
    python plot_protection_benefit.py --outputs path/to/output1.json path/to/output2.json ... \
                                      --scenarios dry-day dry-night rainy-day rainy-night \
                                      --output-fig figures/benefit_vs_fitness.png
"""

import argparse
import json
import os
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Patch


SCENARIO_COLORS = {
    "dry-day": "#5cb85c",
    "dry-night": "#2d6a2d",
    "rainy-day": "#5b9bd5",
    "rainy-night": "#2e5fa1",
}


def load_benefit_from_output(output_path: str) -> dict:
    """从 output JSON 中提取保护效益数据"""
    with open(output_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    summary = data.get('summary', {})
    return {
        'total_protection_benefit': summary.get('total_protection_benefit', 0.0),
        'average_protection_benefit': summary.get('average_protection_benefit', 0.0),
        'best_fitness': summary.get('best_fitness', 0.0),
    }


def main():
    parser = argparse.ArgumentParser(
        description="生成保护效益对比图表",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--outputs', '-o', nargs='+', required=True,
                        help='多个输出 JSON 文件路径')
    parser.add_argument('--scenarios', '-s', nargs='+',
                        default=['dry-day', 'dry-night', 'rainy-day', 'rainy-night'],
                        help='场景名称列表')
    parser.add_argument('--output-fig', '-f', default='benefit_vs_fitness.png',
                        help='输出图表路径')
    parser.add_argument('--dpi', type=int, default=150, help='输出图片 DPI')
    args = parser.parse_args()

    if len(args.outputs) != len(args.scenarios):
        print(f"错误: outputs 数量({len(args.outputs)})与 scenarios 数量({len(args.scenarios)})不匹配")
        return

    scenario_data = {}
    for scenario, output_path in zip(args.scenarios, args.outputs):
        if not os.path.exists(output_path):
            print(f"警告: 文件不存在 {output_path}，跳过")
            continue
        benefit = load_benefit_from_output(output_path)
        scenario_data[scenario] = benefit
        print(f"  {scenario}: total_benefit={benefit['total_protection_benefit']:.4f}, "
              f"best_fitness={benefit['best_fitness']:.6f}")

    if not scenario_data:
        print("错误: 没有加载到任何数据")
        return

    scenarios = list(scenario_data.keys())
    total_pb = [scenario_data[s]['total_protection_benefit'] for s in scenarios]
    best_fitness = [scenario_data[s]['best_fitness'] for s in scenarios]
    colors = [SCENARIO_COLORS.get(s, '#666666') for s in scenarios]

    x = np.arange(len(scenarios))
    width = 0.8

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    bars1 = ax1.bar(x, total_pb, width, color=colors)
    ax1.set_title('Total Protection Benefit by Scenario', fontsize=12, fontweight='bold')
    ax1.set_xlabel('Scenario', fontsize=11)
    ax1.set_ylabel('Total Protection Benefit', fontsize=11)
    ax1.set_xticks(x)
    ax1.set_xticklabels(scenarios, fontsize=10)
    ax1.tick_params(axis='both', labelsize=10)

    for bar in bars1:
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width() / 2., height,
                 f'{height:.4f}', ha='center', va='bottom', fontsize=9)

    max_total = max(total_pb)
    ax1.set_ylim(0, max_total * 1.15)

    bars2 = ax2.bar(x, best_fitness, width, color=colors)
    ax2.set_title('Best Fitness by Scenario', fontsize=12, fontweight='bold')
    ax2.set_xlabel('Scenario', fontsize=11)
    ax2.set_ylabel('Best Fitness', fontsize=11)
    ax2.set_xticks(x)
    ax2.set_xticklabels(scenarios, fontsize=10)
    ax2.tick_params(axis='both', labelsize=10)

    for bar in bars2:
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width() / 2., height,
                 f'{height:.6f}', ha='center', va='bottom', fontsize=9)

    max_fitness = max(best_fitness)
    ax2.set_ylim(0, max_fitness * 1.15)

    legend_handles = [Patch(facecolor=SCENARIO_COLORS[s], label=s) for s in scenarios]
    fig.legend(handles=legend_handles, loc='upper center', ncol=4, fontsize=10)

    plt.tight_layout(rect=[0, 0, 1, 0.92])
    plt.savefig(args.output_fig, dpi=args.dpi, bbox_inches='tight')
    print(f"\n图表已保存至: {args.output_fig}")


if __name__ == '__main__':
    main()
