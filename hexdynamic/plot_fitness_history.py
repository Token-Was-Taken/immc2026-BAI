"""
plot_fitness_history.py - 从 out.json 的 fitness_history 生成收敛曲线图

用法:
    python plot_fitness_history.py out.json [output.png]
    python plot_fitness_history.py out.json                    # 默认保存到 out_fitness_history.png
"""

import argparse
import json
import os
import sys
import numpy as np


def plot_fitness_history(json_path: str, output_path: str = None):
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    summary = data.get('summary', {})
    fitness_history = summary.get('fitness_history', [])

    if not fitness_history:
        print("错误: JSON 中没有 fitness_history 数据")
        sys.exit(1)

    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print("错误: 需要 matplotlib，请安装: pip install matplotlib")
        sys.exit(1)

    iterations = list(range(len(fitness_history)))
    best_fitness = float(summary.get('best_fitness', max(fitness_history)))
    best_iter = int(np.argmax(fitness_history))
    initial_fitness = float(fitness_history[0])
    improvement = best_fitness - initial_fitness

    fig, ax = plt.subplots(figsize=(10, 5.5))

    ax.plot(iterations, fitness_history, color='#3498db', linewidth=1.2, label='Best Fitness', drawstyle='steps-post')

    ax.scatter([best_iter], [best_fitness], color='#e74c3c', s=60, zorder=5,
               label=f'Best: {best_fitness:.6f} (iter {best_iter})')

    ax.axhline(y=best_fitness, color='#e74c3c', linestyle='--', linewidth=0.8, alpha=0.4)

    ax.set_xlabel('Iteration', fontsize=11)
    ax.set_ylabel('Best Fitness', fontsize=11)
    ax.set_title('Fitness Convergence', fontsize=13, fontweight='bold')

    ax.grid(True, linestyle='-', alpha=0.3)
    ax.legend(loc='lower right', fontsize=9)

    info_text = (
        f"Total Iterations: {len(fitness_history)}\n"
        f"Best Fitness: {best_fitness:.6f}\n"
        f"Best Iteration: {best_iter}\n"
        f"Initial Fitness: {initial_fitness:.6f}\n"
        f"Improvement: {improvement:.6f}"
    )
    ax.text(0.02, 0.98, info_text, transform=ax.transAxes,
            fontsize=9, verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.8, edgecolor='gray'))

    plt.tight_layout()

    if output_path is None:
        base, _ = os.path.splitext(json_path)
        output_path = base + '_fitness_history.png'

    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"图表已保存: {output_path}")
    print(f"  迭代数: {len(fitness_history)}")
    print(f"  最优 fitness: {best_fitness:.6f} (第 {best_iter} 轮)")
    print(f"  初始 fitness: {initial_fitness:.6f}")
    print(f"  提升: {improvement:.6f}")


def main():
    parser = argparse.ArgumentParser(
        description="从 out.json 的 fitness_history 生成收敛曲线图",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('json', help='输入的 out.json 文件路径')
    parser.add_argument('output', nargs='?', default=None,
                        help='输出图片路径 (默认: <json>_fitness_history.png)')
    args = parser.parse_args()

    if not os.path.exists(args.json):
        print(f"错误: 文件不存在: {args.json}")
        sys.exit(1)

    plot_fitness_history(args.json, args.output)


if __name__ == '__main__':
    main()
