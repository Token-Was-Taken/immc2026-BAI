"""
Risk Analysis Batch Processing Script

批量处理多个输入 JSON 文件，生成：
1. 每个场景的独立可视化
2. 所有场景的对比图（risk_heatmap + raw_risk_heatmap）

用法：
    python risk_analysis_batch.py --input-dir ./data --output-dir ./results
    python risk_analysis_batch.py --input-dir ./data --output-dir ./results --pattern "scenario_*.json"
"""

import os
import sys
import glob
import json
import math
import numpy as np
from typing import List, Dict, Tuple
import argparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Polygon
from matplotlib.colors import Normalize
from matplotlib import cm

# Import from risk_analysis
from risk_analysis import (
    compute_risk, load_input, hex_corners, grid_center, draw_hex,
    setup_map_ax, TERRAIN_COLORS, VEGETATION_COLORS
)


def scan_input_files(input_dir: str, pattern: str = "*.json") -> List[str]:
    """扫描输入目录，返回所有 JSON 文件路径"""
    files = glob.glob(os.path.join(input_dir, pattern))
    # 排除输出文件
    files = [f for f in files if not os.path.basename(f).startswith('risk_results')]
    files = [f for f in files if not os.path.basename(f).startswith('temp_')]
    return sorted(files)


def process_single_file(input_path: str, output_dir: str) -> dict:
    """
    处理单个文件
    
    Returns:
        {
            'name': 'scenario_1',
            'normalized_risks': {grid_id: risk, ...},
            'raw_risks': {grid_id: risk, ...},
            'grids': [...],
            'hex_size': 62.0
        }
    """
    # 1. 加载数据
    data = load_input(input_path)
    grids = data['grids']
    
    # 2. 计算 hex_size
    if grids and 'hex_size' in grids[0]:
        hex_size = float(grids[0]['hex_size'])
    else:
        hex_size = 1.0
    
    # 3. 计算风险
    normalized_risks, raw_risks = compute_risk(data)
    
    # 4. 创建场景输出目录
    scenario_name = os.path.splitext(os.path.basename(input_path))[0]
    scenario_dir = os.path.join(output_dir, scenario_name)
    os.makedirs(scenario_dir, exist_ok=True)
    
    # 5. 生成独立可视化
    from risk_analysis import plot_risk_heatmap, plot_raw_risk_heatmap, plot_attributes_map
    
    plot_risk_heatmap(grids, normalized_risks, hex_size,
                      save_path=os.path.join(scenario_dir, 'risk_heatmap.png'))
    plot_raw_risk_heatmap(grids, raw_risks, hex_size,
                          save_path=os.path.join(scenario_dir, 'raw_risk_heatmap.png'))
    plot_attributes_map(grids, hex_size,
                        save_path=os.path.join(scenario_dir, 'attributes_map.png'))
    
    # 6. 保存 JSON 结果
    norm_vals = list(normalized_risks.values())
    raw_vals = list(raw_risks.values())
    
    result_path = os.path.join(scenario_dir, 'risk_results.json')
    with open(result_path, 'w', encoding='utf-8') as f:
        summary = {
            'total_grids': len(norm_vals),
            'normalized_risk_min': round(min(norm_vals), 6),
            'normalized_risk_max': round(max(norm_vals), 6),
            'normalized_risk_mean': round(float(np.mean(norm_vals)), 6),
            'raw_risk_min': round(min(raw_vals), 6),
            'raw_risk_max': round(max(raw_vals), 6),
            'raw_risk_mean': round(float(np.mean(raw_vals)), 6),
        }
        
        json.dump({
            'summary': summary,
            'grids': [
                {
                    'grid_id': g['grid_id'],
                    'q': g['q'],
                    'r': g['r'],
                    'normalized_risk': round(normalized_risks.get(g['grid_id'], 0.0), 6),
                    'raw_risk': round(raw_risks.get(g['grid_id'], 0.0), 6),
                    'vegetation_type': g.get('vegetation_type', ''),
                    'terrain_complexity': g.get('terrain_complexity', 0.0),
                    'fire_risk': g.get('fire_risk', 0.0),
                    'species_densities': g.get('species_densities', {}),
                }
                for g in grids
            ]
        }, f, indent=2, ensure_ascii=False)
    
    print(f"  Saved to: {scenario_dir}/")
    
    # 7. 返回数据用于对比
    return {
        'name': scenario_name,
        'normalized_risks': normalized_risks,
        'raw_risks': raw_risks,
        'grids': grids,
        'hex_size': hex_size
    }


def generate_single_comparison(results: List[dict], risk_key: str, 
                                max_val: float, save_path: str, title: str):
    """生成单个对比图，2x2 布局"""
    
    n_scenarios = len(results)
    if n_scenarios == 0:
        return
    
    # 固定使用 2x2 布局（最多4个场景）
    n_cols = 2
    n_rows = 2
    
    # 创建图形 - 每个子图保持原始尺寸
    fig_width = 14 * n_cols  # 每个子图宽度 14
    fig_height = 7 * n_rows  # 每个子图高度压缩，减少上下间距
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(fig_width, fig_height))
    
    if n_scenarios == 1:
        axes = [[axes[0, 0], axes[0, 1]], [axes[1, 0], axes[1, 1]]]
    elif n_scenarios == 2:
        axes = [[axes[0, 0], axes[0, 1]], [axes[1, 0], axes[1, 1]]]
    else:
        axes = axes if hasattr(axes, 'flatten') else [[axes[0, 0], axes[0, 1]], [axes[1, 0], axes[1, 1]]]
    
    # 统一颜色条
    cmap = matplotlib.colormaps.get_cmap("YlOrRd")
    norm = Normalize(vmin=0, vmax=min(max_val, 1.0))  # 限制最大值为1.0
    
    # 绘制每个场景
    for i in range(n_rows):
        for j in range(n_cols):
            idx = i * n_cols + j
            ax = axes[i][j]
            
            if idx < n_scenarios:
                result = results[idx]
                grids = result['grids']
                risks = result[risk_key]
                hex_size = result['hex_size']
                
                # 绘制六边形 + raw risk 数值标注
                for g in grids:
                    gid = g['grid_id']
                    risk = risks.get(gid, 0.0)
                    cx, cy = grid_center(g["q"], g["r"], hex_size)
                    draw_hex(ax, cx, cy, hex_size * 0.97, facecolor=cmap(norm(risk)))

                    # 标注 raw risk 值
                    raw_val = result['raw_risks'].get(gid, 0.0)
                    text_color = 'black' if norm(risk) < 0.6 else 'white'
                    ax.text(cx, cy, f"{raw_val:.2f}",
                            fontsize=3 if len(grids) > 100 else 5,
                            ha='center', va='center',
                            color=text_color, fontweight='bold',
                            zorder=3, alpha=0.85)

                # 设置
                setup_map_ax(ax, grids, hex_size)
                ax.set_title(result['name'], fontsize=13, fontweight='bold', pad=10)
                ax.axis('off')

                # 在子图左下角显示 raw risk 统计
                raw_vals = list(result['raw_risks'].values())
                stats_text = (
                    f"raw min:  {min(raw_vals):.4f}\n"
                    f"raw max:  {max(raw_vals):.4f}\n"
                    f"raw mean: {float(sum(raw_vals)/len(raw_vals)):.4f}"
                )
                ax.text(
                    0.01, 0.01, stats_text,
                    transform=ax.transAxes,
                    fontsize=8, va='bottom', ha='left',
                    fontfamily='monospace',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.75, edgecolor='gray')
                )
            else:
                # 隐藏多余的子图
                ax.axis('off')
    
    # 添加统一颜色条（右侧）
    sm = cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar_ax = fig.add_axes([0.92, 0.15, 0.015, 0.7])  # 右侧颜色条
    cbar = fig.colorbar(sm, cax=cbar_ax)
    cbar.set_label('Risk Value', fontsize=11)
    
    # 标题
    fig.suptitle(title, fontsize=16, fontweight='bold', y=0.98)
    
    # 调整布局
    plt.subplots_adjust(left=0.05, right=0.90, top=0.95, bottom=0.05, wspace=0.1, hspace=0.05)
    
    # 保存
    fig.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved: {os.path.basename(save_path)}")


def generate_comparison_plots(results: List[dict], output_dir: str):
    """生成对比图"""
    
    if not results:
        print("  No results to generate comparison plots")
        return
    
    print("\nGenerating comparison plots...")
    
    # 1. 计算统一颜色条范围
    all_normalized_max = max([max(r['normalized_risks'].values()) for r in results if r['normalized_risks']])
    all_raw_max = max([max(r['raw_risks'].values()) for r in results if r['raw_risks']])
    
    print(f"  Normalized risk max: {all_normalized_max:.6f}")
    print(f"  Raw risk max: {all_raw_max:.6f}")
    
    # 2. 生成 normalized risk 对比图
    generate_single_comparison(
        results, 
        'normalized_risks',
        all_normalized_max,
        os.path.join(output_dir, 'risk_heatmap_comparison.png'),
        'Normalized Risk Comparison'
    )
    
    # 3. 生成 raw risk 对比图
    generate_single_comparison(
        results,
        'raw_risks',
        all_raw_max,
        os.path.join(output_dir, 'raw_risk_heatmap_comparison.png'),
        'Raw Risk Comparison'
    )


def generate_summary_report(results: List[dict], output_dir: str):
    """生成统计汇总报告"""
    
    summary = {
        'total_scenarios': len(results),
        'scenarios': []
    }
    
    for r in results:
        norm_vals = list(r['normalized_risks'].values())
        raw_vals = list(r['raw_risks'].values())
        
        summary['scenarios'].append({
            'name': r['name'],
            'total_grids': len(norm_vals),
            'normalized_risk_min': round(min(norm_vals), 6) if norm_vals else 0,
            'normalized_risk_max': round(max(norm_vals), 6) if norm_vals else 0,
            'normalized_risk_mean': round(float(np.mean(norm_vals)), 6) if norm_vals else 0,
            'raw_risk_min': round(min(raw_vals), 6) if raw_vals else 0,
            'raw_risk_max': round(max(raw_vals), 6) if raw_vals else 0,
            'raw_risk_mean': round(float(np.mean(raw_vals)), 6) if raw_vals else 0,
        })
    
    report_path = os.path.join(output_dir, 'summary_report.json')
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"  Saved: summary_report.json")


def main():
    parser = argparse.ArgumentParser(
        description="Risk Analysis Batch Processing: process multiple input files and generate comparison plots.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog="""
Examples:
  python risk_analysis_batch.py --input-dir ./data --output-dir ./results
  python risk_analysis_batch.py --input-dir ./data --output-dir ./results --pattern "scenario_*.json"

Output:
  - Each scenario gets its own subdirectory with individual visualizations
  - Comparison plots: risk_heatmap_comparison.png, raw_risk_heatmap_comparison.png
  - Summary report: summary_report.json
        """
    )
    parser.add_argument("--input-dir", "-i", required=True, help="Input directory containing JSON files")
    parser.add_argument("--output-dir", "-o", default="./risk_analysis_results", help="Output directory")
    parser.add_argument("--pattern", "-p", default="*.json", help="File pattern to match (e.g., 'scenario_*.json')")
    parser.add_argument("--hex-size", type=float, default=None, help="Hex cell size (auto-detected if not provided)")
    
    args = parser.parse_args()
    
    # 验证输入目录
    if not os.path.exists(args.input_dir):
        print(f"Error: Input directory does not exist: {args.input_dir}")
        sys.exit(1)
    
    # 创建输出目录
    os.makedirs(args.output_dir, exist_ok=True)
    
    # 扫描输入文件
    print(f"\nScanning input directory: {args.input_dir}")
    print(f"  Pattern: {args.pattern}")
    input_files = scan_input_files(args.input_dir, args.pattern)
    
    if not input_files:
        print(f"Error: No JSON files found matching pattern '{args.pattern}' in {args.input_dir}")
        sys.exit(1)
    
    print(f"  Found {len(input_files)} file(s)")
    for f in input_files:
        print(f"    - {os.path.basename(f)}")
    
    # 处理每个文件
    print(f"\nProcessing {len(input_files)} file(s)...")
    results = []
    
    for i, input_path in enumerate(input_files):
        print(f"\n[{i+1}/{len(input_files)}] Processing: {os.path.basename(input_path)}")
        try:
            result = process_single_file(input_path, args.output_dir)
            results.append(result)
            
            # 打印统计
            norm_vals = list(result['normalized_risks'].values())
            raw_vals = list(result['raw_risks'].values())
            print(f"  Normalized: min={min(norm_vals):.4f}  max={max(norm_vals):.4f}  mean={np.mean(norm_vals):.4f}")
            print(f"  Raw       : min={min(raw_vals):.6f}  max={max(raw_vals):.6f}  mean={np.mean(raw_vals):.6f}")
        except Exception as e:
            print(f"  Error: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    # 生成对比图
    if results:
        generate_comparison_plots(results, args.output_dir)
        generate_summary_report(results, args.output_dir)
    
    print(f"\n{'='*70}")
    print(f"Batch processing complete!")
    print(f"  Processed: {len(results)}/{len(input_files)} file(s)")
    print(f"  Output directory: {args.output_dir}")
    print(f"{'='*70}\n")


if __name__ == '__main__':
    main()
