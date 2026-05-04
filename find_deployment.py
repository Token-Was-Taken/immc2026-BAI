"""
find_deployment.py — 二分查找最小资源量，达到指定保护水平

通过折半查找调整某种资源的总量约束，找到恰好满足目标保护水平
（best_fitness 或 total_protection_benefit）的最小资源部署方案。

用法:
    # 找到使 best_fitness >= 0.3 所需的最少 camera 数量
    python find_deployment.py --input input.json --resource camera --target-fitness 0.3

    # 找到使 total_protection_benefit >= 50 所需的最少 patrol 数量
    python find_deployment.py --input input.json --resource patrol --target-benefit 50

    # 指定搜索范围和精度
    python find_deployment.py --input input.json --resource drone --target-fitness 0.25 \\
        --min 0 --max 500 --tolerance 2 --vectorized

    # 冻结其他资源（只调整 camera，其他资源固定）
    python find_deployment.py --input input.json --resource camera --target-fitness 0.3 \\
        --freeze patrol,drone,camp
"""

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def load_json(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path: str, data: dict):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


RESOURCE_CONSTRAINT_KEY = {
    'patrol': 'total_patrol',
    'camera': 'total_cameras',
    'drone':  'total_drones',
    'camp':   'total_camps',
    'fence':  'total_fence_length',
}


def run_pipeline(input_path: str, output_path: str,
                 vectorized: bool = False, freeze: str = None) -> dict:
    """运行 protection_pipeline，返回 summary dict，失败抛出 RuntimeError。"""
    cmd = [sys.executable, 'hexdynamic/protection_pipeline.py', input_path, output_path]
    if vectorized:
        cmd.append('--vectorized')
    if freeze:
        cmd.extend(['--freeze-resources', freeze])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-500:])

    out = load_json(output_path)
    return out['summary']


def run_pipeline_parallel(tasks: list, vectorized: bool = False, freeze: str = None) -> list:
    """
    并行运行多个 pipeline 任务。
    
    Args:
        tasks: list of (input_path, output_path)
    
    Returns:
        list of (summary_dict or None, error_msg or None)
    """
    cmd_base = [sys.executable, 'hexdynamic/protection_pipeline.py']
    if vectorized:
        cmd_base.append('--vectorized')
    
    procs = []
    for inp, out in tasks:
        cmd = cmd_base + [inp, out]
        if freeze:
            cmd.extend(['--freeze-resources', freeze])
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        procs.append((p, out))
    
    results = []
    for p, out_path in procs:
        stdout, stderr = p.communicate()
        if p.returncode != 0:
            results.append((None, stderr[-500:]))
        else:
            try:
                out = load_json(out_path)
                results.append((out['summary'], None))
            except Exception as e:
                results.append((None, str(e)))
    
    return results


def make_input(base: dict, resource: str, value: int) -> dict:
    """复制 base，修改指定资源的约束值。"""
    data = copy.deepcopy(base)
    key = RESOURCE_CONSTRAINT_KEY[resource]
    data['constraints'][key] = value
    return data


def get_metric(summary: dict, metric: str) -> float:
    if metric == 'fitness':
        return summary['best_fitness']
    elif metric == 'benefit':
        return summary['total_protection_benefit']
    raise ValueError(f"Unknown metric: {metric}")


# ---------------------------------------------------------------------------
# 二分查找
# ---------------------------------------------------------------------------

def binary_search(
    base_input: dict,
    resource: str,
    target: float,
    metric: str,
    lo: int,
    hi: int,
    tolerance: int,
    vectorized: bool,
    freeze: str,
    work_dir: str,
) -> dict:
    """
    折半查找满足 metric >= target 的最小资源量。

    优化策略：
    - 第 0 轮并行运行 hi 和 mid=(lo+hi)/2，快速确定搜索方向
    - 后续根据结果串行二分

    返回:
        {
            'found': bool,
            'resource_value': int,
            'metric_value': float,
            'summary': dict,
            'output_path': str,
            'iterations': int,
            'history': list
        }
    """
    best_value   = None
    best_summary = None
    best_output  = None
    iterations   = 0
    history      = []

    def record(iter_no, rv, summary, met):
        history.append({
            'iter':           iter_no,
            'resource_value': rv,
            'total_benefit':  summary.get('total_protection_benefit', 0.0),
            'avg_benefit':    summary.get('average_protection_benefit', 0.0),
            'best_fitness':   summary.get('best_fitness', 0.0),
            'met_target':     met,
        })

    def prepare(rv):
        inp = make_input(base_input, resource, rv)
        p_in  = os.path.join(work_dir, f'input_{resource}_{rv}.json')
        p_out = os.path.join(work_dir, f'output_{resource}_{rv}.json')
        save_json(p_in, inp)
        return p_in, p_out

    # ------------------------------------------------------------------
    # 第 0 轮：并行运行 hi 和 mid
    # ------------------------------------------------------------------
    mid0 = (lo + hi) // 2
    print(f"\n[INIT] 并行探测 {resource}={hi} 和 {resource}={mid0} ...")

    tasks = [prepare(hi), prepare(mid0)]
    par_results = run_pipeline_parallel(tasks, vectorized, freeze)

    # 处理 hi 结果
    summary_hi, err_hi = par_results[0]
    if err_hi or summary_hi is None:
        print(f"[ERROR] 上界 {resource}={hi} 运行失败: {err_hi}")
        return {'found': False, 'resource_value': hi, 'metric_value': 0.0,
                'summary': {}, 'output_path': '', 'iterations': 0, 'history': history}

    val_hi = get_metric(summary_hi, metric)
    met_hi = val_hi >= target
    record(0, hi, summary_hi, met_hi)
    print(f"       {resource}={hi:5d}  {metric}={val_hi:.6f}  {'[OK]' if met_hi else '[LOW]'}")

    if not met_hi:
        print(f"[WARN] 上界 {resource}={hi} 仍无法达到目标，请增大 --max")
        return {'found': False, 'resource_value': hi, 'metric_value': val_hi,
                'summary': summary_hi, 'output_path': tasks[0][1],
                'iterations': 0, 'history': history}

    best_value   = hi
    best_summary = summary_hi
    best_output  = tasks[0][1]

    # 处理 mid0 结果
    summary_mid, err_mid = par_results[1]
    iterations = 1

    if err_mid or summary_mid is None:
        print(f"       {resource}={mid0:5d}  [ERROR] {err_mid}")
        lo = mid0  # 失败视为不满足
    else:
        val_mid = get_metric(summary_mid, metric)
        met_mid = val_mid >= target
        record(1, mid0, summary_mid, met_mid)
        print(f"       {resource}={mid0:5d}  {metric}={val_mid:.6f}  {'[OK] -> 缩小上界' if met_mid else '[LOW] -> 提高下界'}")

        if met_mid:
            hi = mid0
            best_value   = mid0
            best_summary = summary_mid
            best_output  = tasks[1][1]
        else:
            lo = mid0

    # ------------------------------------------------------------------
    # 后续串行二分
    # ------------------------------------------------------------------
    while hi - lo > tolerance:
        iterations += 1
        mid = (lo + hi) // 2
        print(f"\n[ITER {iterations:3d}]  lo={lo:5d}  mid={mid:5d}  hi={hi:5d}", end='  ')

        p_in, p_out = prepare(mid)
        try:
            summary = run_pipeline(p_in, p_out, vectorized, freeze)
            val = get_metric(summary, metric)
            met = val >= target
            print(f"{metric}={val:.6f}  target={target:.6f}  {'[OK] -> 缩小上界' if met else '[LOW] -> 提高下界'}")
            record(iterations, mid, summary, met)

            if met:
                hi = mid
                best_value   = mid
                best_summary = summary
                best_output  = p_out
            else:
                lo = mid
        except RuntimeError as e:
            print(f"[ERROR] {e}")
            record(iterations, mid, {}, False)
            lo = mid

    return {
        'found':          best_value is not None,
        'resource_value': best_value,
        'metric_value':   get_metric(best_summary, metric) if best_summary else 0.0,
        'summary':        best_summary or {},
        'output_path':    best_output or '',
        'iterations':     iterations,
        'history':        history,
    }


# ---------------------------------------------------------------------------
# 可视化
# ---------------------------------------------------------------------------

COLORS = {
    'total':   '#2ca02c',
    'avg':     '#1f77b4',
    'fitness': '#9467bd',
    'target':  '#d62728',
    'met':     '#2ca02c',
    'not_met': '#ff7f0e',
}


def _plot_single(history: list, y_key: str, y_label: str, title: str,
                 target: float, target_label: str, color: str, save_path: str):
    """输出单张趋势图。"""
    iters  = [h['iter'] for h in history]
    values = [h[y_key] for h in history]
    colors = [COLORS['met'] if h['met_target'] else COLORS['not_met'] for h in history]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(iters, values, '-', color=color, lw=1.5, zorder=1)
    ax.scatter(iters, values, c=colors, s=60, zorder=2,
               label='met target / not met')
    ax.axhline(target, color=COLORS['target'], ls='--', lw=1.2,
               label=f'target ({target_label}={target:.4f})')
    ax.set_xlabel('Iteration', fontsize=11)
    ax.set_ylabel(y_label, fontsize=11)
    ax.set_title(title, fontsize=12, fontweight='bold')
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    fig.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  saved: {save_path}")


def plot_convergence(history: list, resource: str, target: float,
                     metric: str, out_dir: str) -> list:
    """
    输出 3 张独立趋势图 + 1 张合并图（上：3 图，下：表格）。
    返回所有输出文件路径列表。
    """
    os.makedirs(out_dir, exist_ok=True)
    saved = []

    specs = [
        ('total_benefit',  'Total Protection Benefit', 'Total Benefit',  COLORS['total']),
        ('avg_benefit',    'Average Protection Benefit','Avg Benefit',    COLORS['avg']),
        ('best_fitness',   'Best Fitness',              'Best Fitness',   COLORS['fitness']),
    ]
    target_label = 'fitness' if metric == 'fitness' else 'benefit'

    # --- 3 张独立图 ---
    for y_key, y_label, title, color in specs:
        path = os.path.join(out_dir, f'convergence_{y_key}.png')
        _plot_single(history, y_key, y_label, title,
                     target, target_label, color, path)
        saved.append(path)

    # --- 合并图 ---
    n_rows_tbl = len(history)
    # 图表区固定高度，表格区按行数动态扩展
    chart_h = 5.0
    table_h = max(2.5, n_rows_tbl * 0.30 + 0.8)
    total_h = chart_h + table_h + 0.5

    fig = plt.figure(figsize=(18, total_h))
    fig.suptitle(
        f"Binary Search Convergence: {resource.upper()}  (target {target_label}>={target})",
        fontsize=13, fontweight='bold', y=1.0 - 0.3 / total_h
    )

    chart_ratio = chart_h / (chart_h + table_h)
    table_ratio = table_h / (chart_h + table_h)

    gs = gridspec.GridSpec(
        2, 1, figure=fig,
        height_ratios=[chart_ratio, table_ratio],
        hspace=0.06,
        left=0.06, right=0.97,
        top=1.0 - 0.5 / total_h,
        bottom=0.02,
    )

    gs_charts = gridspec.GridSpecFromSubplotSpec(
        1, 3, subplot_spec=gs[0], wspace=0.35
    )

    iters  = [h['iter'] for h in history]
    pt_colors = [COLORS['met'] if h['met_target'] else COLORS['not_met'] for h in history]

    for col, (y_key, y_label, title, color) in enumerate(specs):
        ax = fig.add_subplot(gs_charts[0, col])
        values = [h[y_key] for h in history]
        ax.plot(iters, values, '-', color=color, lw=1.5, zorder=1)
        ax.scatter(iters, values, c=pt_colors, s=50, zorder=2)
        ax.axhline(target, color=COLORS['target'], ls='--', lw=1.2,
                   label=f'target={target:.4f}')
        ax.set_xlabel('Iteration', fontsize=9)
        ax.set_ylabel(y_label, fontsize=9)
        ax.set_title(title, fontsize=10, fontweight='bold')
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)

    # --- 表格 ---
    ax_tbl = fig.add_subplot(gs[1])
    ax_tbl.axis('off')

    col_labels = ['Iter', f'{resource.capitalize()} Count',
                  'Total Benefit', 'Avg Benefit', 'Best Fitness', 'Met Target']
    rows = []
    for h in history:
        rows.append([
            str(h['iter']),
            str(h['resource_value']),
            f"{h['total_benefit']:.4f}",
            f"{h['avg_benefit']:.4f}",
            f"{h['best_fitness']:.4f}",
            'YES' if h['met_target'] else 'NO',
        ])

    tbl = ax_tbl.table(
        cellText=rows,
        colLabels=col_labels,
        cellLoc='center',
        loc='upper center',
        colWidths=[0.07, 0.14, 0.16, 0.16, 0.16, 0.12],
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1, 1.4)

    # 表头
    for j in range(len(col_labels)):
        tbl[(0, j)].set_facecolor('#2c7bb6')
        tbl[(0, j)].set_text_props(color='white', fontweight='bold')

    # 行颜色：满足目标的行绿色，否则交替灰白
    for row_idx, h in enumerate(history):
        if h['met_target']:
            bg = '#d4edda'
        else:
            bg = '#f5f5f5' if row_idx % 2 == 0 else 'white'
        for j in range(len(col_labels)):
            tbl[(row_idx + 1, j)].set_facecolor(bg)

    ax_tbl.set_title(
        'Iteration History  (green rows = met target)',
        fontsize=9, pad=4, loc='left'
    )

    combined_path = os.path.join(out_dir, 'convergence_combined.png')
    fig.savefig(combined_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  saved: {combined_path}")
    saved.append(combined_path)

    return saved


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="二分查找：找到满足目标保护水平的最小资源量",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog="""
示例:
  python find_deployment.py --input input.json --resource camera --target-fitness 0.3
  python find_deployment.py --input input.json --resource patrol --target-benefit 50
  python find_deployment.py --input input.json --resource drone  --target-fitness 0.25 --min 0 --max 300
  python find_deployment.py --input input.json --resource camera --target-fitness 0.3 --freeze patrol,drone,camp
        """
    )
    p.add_argument('--input',  '-i', required=True, help='基础输入 JSON 路径')
    p.add_argument('--resource', '-r', required=True,
                   choices=list(RESOURCE_CONSTRAINT_KEY.keys()),
                   help='要调整的资源类型')

    # 目标（二选一）
    tgt = p.add_mutually_exclusive_group(required=True)
    tgt.add_argument('--target-fitness',  type=float, metavar='F',
                     help='目标 best_fitness（如 0.3）')
    tgt.add_argument('--target-benefit',  type=float, metavar='B',
                     help='目标 total_protection_benefit（如 50.0）')

    p.add_argument('--min',       type=int,   default=0,    help='搜索下界（资源数量）')
    p.add_argument('--max',       type=int,   default=1000, help='搜索上界（资源数量）')
    p.add_argument('--tolerance', type=int,   default=5,
                   help='收敛精度：当 hi-lo <= tolerance 时停止（默认 5）')
    p.add_argument('--output',    '-o', default=None,
                   help='最终部署方案输出 JSON 路径（默认自动命名）')
    p.add_argument('--work-dir',  default='./find_deployment_tmp',
                   help='中间文件目录')
    p.add_argument('--out-dir',   default=None,
                   help='图表输出目录（默认与 --work-dir 相同）')
    p.add_argument('--vectorized', action='store_true', default=False,
                   help='使用向量化模式（大规模地图推荐）')
    p.add_argument('--freeze',    default=None,
                   help='冻结其他资源，逗号分隔，如 patrol,drone,camp')
    return p.parse_args()


def main():
    args = parse_args()

    # 确定目标
    if args.target_fitness is not None:
        metric, target = 'fitness', args.target_fitness
    else:
        metric, target = 'benefit', args.target_benefit

    base_input = load_json(args.input)
    os.makedirs(args.work_dir, exist_ok=True)

    # 确定上界：优先用 --max，若未指定（默认1000）则从 input 文件读取
    constraint_key = RESOURCE_CONSTRAINT_KEY[args.resource]
    if args.max != 1000:
        hi = args.max
    else:
        input_hi = base_input.get('constraints', {}).get(constraint_key)
        if input_hi is not None:
            hi = int(input_hi)
            print(f"  [AUTO] 上界从 input 文件读取: {args.resource} = {hi}")
        else:
            hi = args.max

    print(f"{'='*60}")
    print(f"  资源:   {args.resource}")
    print(f"  目标:   {metric} >= {target}")
    print(f"  范围:   [{args.min}, {hi}]  精度: {args.tolerance}")
    if args.freeze:
        print(f"  冻结:   {args.freeze}")
    print(f"{'='*60}")

    result = binary_search(
        base_input  = base_input,
        resource    = args.resource,
        target      = target,
        metric      = metric,
        lo          = args.min,
        hi          = hi,
        tolerance   = args.tolerance,
        vectorized  = args.vectorized,
        freeze      = args.freeze,
        work_dir    = args.work_dir,
    )

    print(f"\n{'='*60}")
    if result['found']:
        rv = result['resource_value']
        mv = result['metric_value']
        print(f"  [RESULT] 最小 {args.resource} 数量: {rv}")
        print(f"  {metric}: {mv:.6f}  (目标: {target})")
        print(f"  迭代次数: {result['iterations']}")

        # 复制最终结果到指定路径
        out_path = args.output or f"find_deployment_{args.resource}_{rv}.json"
        import shutil
        shutil.copy(result['output_path'], out_path)
        print(f"  部署方案: {out_path}")

        # 打印关键指标
        s = result['summary']
        print(f"\n  关键指标:")
        print(f"    best_fitness              : {s.get('best_fitness', 0):.6f}")
        print(f"    total_protection_benefit  : {s.get('total_protection_benefit', 0):.6f}")
        print(f"    total_risk                : {s.get('total_risk', 0):.6f}")
        deployed = s.get('resources_deployed', {})
        print(f"    resources_deployed        : {deployed}")
    else:
        print(f"  [FAIL] 未能在范围 [{args.min}, {args.max}] 内找到满足目标的方案")
        print(f"  建议增大 --max 或降低目标值")
    print(f"{'='*60}\n")

    # 输出收敛趋势图（无论是否找到结果，只要有历史数据就输出）
    if result.get('history'):
        out_dir = args.out_dir or args.work_dir
        print(f"\n[VIZ] 生成收敛趋势图 -> {out_dir}")
        plot_convergence(
            history  = result['history'],
            resource = args.resource,
            target   = target,
            metric   = metric,
            out_dir  = out_dir,
        )


if __name__ == '__main__':
    main()
