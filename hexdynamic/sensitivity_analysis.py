"""
敏感性分析脚本

分析每种保护资源对总保护收益的影响。
通过逐个改变单一资源数量，保持其他资源不变，观察保护效果的变化趋势。

用法：
    python sensitivity_analysis.py --input base_input.json --resource patrol --range 0 50 5
    python sensitivity_analysis.py --input base_input.json --resource camera --range 0 20 2
    python sensitivity_analysis.py --input base_input.json --resource all
"""

import argparse
import json
import os
import sys
import copy
import subprocess
from typing import Dict, List, Tuple
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def load_json(path: str) -> dict:
    """加载 JSON 文件"""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path: str, data: dict):
    """保存 JSON 文件"""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def run_protection_pipeline(input_path: str, output_path: str, freeze_resources: str = None, vectorized: bool = False):
    """运行 protection_pipeline.py"""
    cmd = [
        sys.executable,
        'hexdynamic/protection_pipeline.py',
        input_path,
        output_path
    ]
    
    if vectorized:
        cmd.append('--vectorized')
    
    if freeze_resources:
        cmd.extend(['--freeze-resources', freeze_resources])
    
    print(f"  运行: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"  错误: {result.stderr}")
        raise RuntimeError(f"Pipeline 运行失败: {result.stderr}")
    
    return result.stdout


def run_sensitivity_analysis(
    base_input_path: str,
    resource_type: str,
    resource_range: Tuple[int, int, int] = None,
    output_dir: str = './sensitivity_results',
    vectorized: bool = False
):
    """
    运行敏感性分析
    
    Args:
        base_input_path: 基础输入 JSON 路径
        resource_type: 要分析的资源类型 ('patrol', 'camera', 'drone', 'camp', 'fence', 'all')
        resource_range: (最小值, 最大值, 步长)
        output_dir: 输出目录
        vectorized: 是否使用向量化模式
    """
    
    os.makedirs(output_dir, exist_ok=True)
    
    # 加载基础输入
    print(f"\n加载基础输入: {base_input_path}")
    base_input = load_json(base_input_path)
    
    # 资源类型映射
    resource_map = {
        'patrol': 'total_patrol',
        'camera': 'total_cameras',
        'drone': 'total_drones',
        'camp': 'total_camps',
        'fence': 'total_fence_length',
    }
    
    # 如果是 'all'，分析所有资源
    if resource_type == 'all':
        resources_to_analyze = list(resource_map.keys())
    else:
        resources_to_analyze = [resource_type]
    
    # 对每种资源进行分析
    for res_type in resources_to_analyze:
        print(f"\n{'='*70}")
        print(f"分析资源: {res_type.upper()}")
        print(f"{'='*70}")
        
        # 确定资源范围
        if resource_range is None:
            # 使用默认范围
            if res_type == 'patrol':
                resource_range = (0, 50, 5)
            elif res_type == 'camera':
                resource_range = (0, 20, 2)
            elif res_type == 'drone':
                resource_range = (0, 10, 1)
            elif res_type == 'camp':
                resource_range = (0, 5, 1)
            elif res_type == 'fence':
                resource_range = (0, 100, 10)
        
        min_val, max_val, step = resource_range
        resource_values = list(range(min_val, max_val + 1, step))
        
        print(f"资源范围: {min_val} - {max_val}, 步长: {step}")
        print(f"将运行 {len(resource_values)} 次优化...")
        
        results = []
        
        # 对每个资源值运行优化
        for idx, resource_value in enumerate(resource_values):
            print(f"\n[{idx+1}/{len(resource_values)}] 运行优化: {res_type}={resource_value}")
            
            # 创建临时输入文件
            temp_input = copy.deepcopy(base_input)
            temp_input['constraints'][resource_map[res_type]] = resource_value
            
            temp_input_path = os.path.join(output_dir, f'temp_input_{res_type}_{resource_value}.json')
            save_json(temp_input_path, temp_input)
            
            # 冻结其他资源
            frozen_list = [r for r in resource_map.keys() if r != res_type]
            freeze_resources_str = ','.join(frozen_list)
            
            # 运行 protection_pipeline
            temp_output_path = os.path.join(output_dir, f'temp_output_{res_type}_{resource_value}.json')
            
            try:
                run_protection_pipeline(
                    temp_input_path,
                    temp_output_path,
                    freeze_resources=freeze_resources_str,
                    vectorized=vectorized
                )
            except RuntimeError as e:
                print(f"  警告: 优化失败，跳过此值")
                continue
            
            # 提取结果
            try:
                output = load_json(temp_output_path)
                result = {
                    'resource_value': resource_value,
                    'total_protection_benefit': output['summary']['total_protection_benefit'],
                    'best_fitness': output['summary']['best_fitness'],
                    'resources_deployed': output['summary']['resources_deployed'],
                    'output_json': temp_output_path
                }
                results.append(result)
                
                print(f"  [OK] 完成: benefit={result['total_protection_benefit']:.6f}, fitness={result['best_fitness']:.6f}")
            except Exception as e:
                print(f"  错误: 无法解析输出 JSON: {e}")
                continue
        
        # 保存敏感性分析结果
        sensitivity_results = {
            'resource_type': res_type,
            'resource_values': resource_values,
            'results': results
        }
        
        result_path = os.path.join(output_dir, f'sensitivity_{res_type}.json')
        save_json(result_path, sensitivity_results)
        print(f"\n[OK] 结果已保存: {result_path}")
        
        # 绘制敏感性曲线
        plot_sensitivity_results(result_path, os.path.join(output_dir, f'sensitivity_{res_type}_plot.png'))


def plot_sensitivity_results(sensitivity_json_path: str, output_path: str):
    """
    绘制敏感性分析曲线
    
    X轴：资源数量
    Y轴：总保护收益 / 最佳适应度
    """
    
    results = load_json(sensitivity_json_path)
    resource_type = results['resource_type']
    resource_values = results['resource_values']
    
    if not results['results']:
        print(f"  [skip] 无有效结果，跳过绘图")
        return
    
    # 提取指标
    total_benefits = [r['total_protection_benefit'] for r in results['results']]
    best_fitnesses = [r['best_fitness'] for r in results['results']]
    
    # 计算边际收益
    marginal_benefits = [0]
    for i in range(1, len(total_benefits)):
        if resource_values[i] != resource_values[i-1]:
            mb = (total_benefits[i] - total_benefits[i-1]) / (resource_values[i] - resource_values[i-1])
            marginal_benefits.append(mb)
        else:
            marginal_benefits.append(0)
    
    # 绘制
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    
    # 曲线1：总保护收益
    ax = axes[0, 0]
    ax.plot(resource_values, total_benefits, 'o-', linewidth=2, markersize=8, color='#2ca02c')
    ax.set_xlabel(f'{resource_type.capitalize()} Count', fontsize=11)
    ax.set_ylabel('Total Protection Benefit', fontsize=11)
    ax.set_title(f'Protection Benefit vs {resource_type.capitalize()} Count', fontsize=12, fontweight='bold')
    ax.grid(True, alpha=0.3)
    ax.set_xlim(min(resource_values) - 1, max(resource_values) + 1)
    
    # 曲线2：最佳适应度
    ax = axes[0, 1]
    ax.plot(resource_values, best_fitnesses, 's-', linewidth=2, markersize=8, color='#1f77b4')
    ax.set_xlabel(f'{resource_type.capitalize()} Count', fontsize=11)
    ax.set_ylabel('Best Fitness', fontsize=11)
    ax.set_title(f'Fitness vs {resource_type.capitalize()} Count', fontsize=12, fontweight='bold')
    ax.grid(True, alpha=0.3)
    ax.set_xlim(min(resource_values) - 1, max(resource_values) + 1)
    
    # 曲线3：边际收益
    ax = axes[1, 0]
    ax.plot(resource_values, marginal_benefits, '^-', linewidth=2, markersize=8, color='#ff7f0e')
    ax.set_xlabel(f'{resource_type.capitalize()} Count', fontsize=11)
    ax.set_ylabel('Marginal Benefit', fontsize=11)
    ax.set_title(f'Marginal Benefit vs {resource_type.capitalize()} Count', fontsize=12, fontweight='bold')
    ax.grid(True, alpha=0.3)
    ax.axhline(y=0, color='k', linestyle='--', linewidth=0.5, alpha=0.5)
    ax.set_xlim(min(resource_values) - 1, max(resource_values) + 1)
    
    # 表格：数据汇总
    ax = axes[1, 1]
    ax.axis('off')
    
    # 创建表格数据
    table_data = [['Resource', 'Benefit', 'Fitness', 'Marginal']]
    for i, rv in enumerate(resource_values):
        table_data.append([
            str(rv),
            f"{total_benefits[i]:.4f}",
            f"{best_fitnesses[i]:.4f}",
            f"{marginal_benefits[i]:.4f}"
        ])
    
    # 绘制表格
    table = ax.table(cellText=table_data, cellLoc='center', loc='center',
                     colWidths=[0.2, 0.25, 0.25, 0.25])
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.5)
    
    # 表头样式
    for i in range(4):
        table[(0, i)].set_facecolor('#4CAF50')
        table[(0, i)].set_text_props(weight='bold', color='white')
    
    # 行颜色交替
    for i in range(1, len(table_data)):
        for j in range(4):
            if i % 2 == 0:
                table[(i, j)].set_facecolor('#f0f0f0')
            else:
                table[(i, j)].set_facecolor('#ffffff')
    
    ax.set_title(f'Sensitivity Analysis Summary: {resource_type.upper()}', 
                 fontsize=12, fontweight='bold', pad=20)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    
    print(f"  [OK] 曲线已保存: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="敏感性分析：分析每种资源对保护效果的影响",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog="""
Examples:
  python sensitivity_analysis.py --input base_input.json --resource patrol --range 0 50 5
  python sensitivity_analysis.py --input base_input.json --resource camera --range 0 20 2
  python sensitivity_analysis.py --input base_input.json --resource all
  python sensitivity_analysis.py --input base_input.json --resource patrol --vectorized

Resources:
  patrol  - 巡逻人员 (default range: 0-50, step 5)
  camera  - 摄像头 (default range: 0-20, step 2)
  drone   - 无人机 (default range: 0-10, step 1)
  camp    - 营地 (default range: 0-5, step 1)
  fence   - 围栏 (default range: 0-100, step 10)
  all     - 分析所有资源
        """
    )
    parser.add_argument("--input", "-i", required=True, help="基础输入 JSON 路径")
    parser.add_argument("--resource", "-r", default="patrol", 
                       help="要分析的资源类型 (patrol|camera|drone|camp|fence|all)")
    parser.add_argument("--range", "-R", nargs=3, type=int, metavar=('MIN', 'MAX', 'STEP'),
                       help="资源范围 (最小值 最大值 步长)")
    parser.add_argument("--output", "-o", default="./sensitivity_results", 
                       help="输出目录")
    parser.add_argument("--vectorized", action="store_true", default=False,
                       help="使用向量化模式（大规模地图推荐）")
    
    args = parser.parse_args()
    
    # 验证输入文件
    if not os.path.exists(args.input):
        print(f"错误: 输入文件不存在: {args.input}")
        sys.exit(1)
    
    # 解析资源范围
    resource_range = None
    if args.range:
        resource_range = tuple(args.range)
    
    # 运行敏感性分析
    run_sensitivity_analysis(
        args.input,
        args.resource,
        resource_range=resource_range,
        output_dir=args.output,
        vectorized=args.vectorized
    )
    
    print(f"\n{'='*70}")
    print("[OK] 敏感性分析完成！")
    print(f"  结果保存在: {args.output}")
    print(f"{'='*70}\n")


if __name__ == '__main__':
    main()
