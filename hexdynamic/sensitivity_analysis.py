"""
敏感性分析脚本

分析每种保护资源对总保护收益的影响。
通过逐个改变单一资源数量，其他资源约束置0，观察保护效果的变化趋势。

支持：
  - 资源内并行：先生成所有 temp_input JSON，再并行运行 pipeline
  - 两步法：粗扫全范围 → 定位饱和区 → 细扫关键区间 → 合并结果
  - 热启动：从低资源点的结果初始化高资源点的优化，加速收敛
  - 缓存：避免重复计算相同配置的边际贡献

用法：
    python sensitivity_analysis.py --input base.json --resource camera --range 0 400 10 --workers 4
    python sensitivity_analysis.py --input base.json --resource camera --range 0 400 50 --two-step --workers 4
    python sensitivity_analysis.py --input base.json --resource camera --range 0 400 10 --warm-start
    python sensitivity_analysis.py --input base.json --resource all
"""

import argparse
import json
import os
import sys
import copy
import subprocess
import time
import hashlib
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, List, Tuple, Optional
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


RESOURCE_MAP = {
    'patrol': 'total_patrol',
    'camera': 'total_cameras',
    'drone': 'total_drones',
    'camp': 'total_camps',
    'fence': 'total_fence_length',
}

DEFAULT_RANGES = {
    'patrol': (0, 50, 5),
    'camera': (0, 20, 2),
    'drone': (0, 10, 1),
    'camp': (0, 5, 1),
    'fence': (0, 100, 10),
}


class BenefitCache:
    def __init__(self, cache_dir: str = None):
        self._cache = {}
        self._cache_dir = cache_dir
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
            self._load_disk_cache()

    def _cache_key(self, res_type: str, resource_value: int) -> str:
        return f"{res_type}_{resource_value}"

    def _cache_file_path(self) -> str:
        if self._cache_dir:
            return os.path.join(self._cache_dir, "benefit_cache.json")
        return None

    def _load_disk_cache(self):
        path = self._cache_file_path()
        if path and os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    self._cache = json.load(f)
                print(f"  [CACHE] 从磁盘加载 {len(self._cache)} 条缓存记录")
            except (IOError, OSError, json.JSONDecodeError):
                self._cache = {}

    def _save_disk_cache(self):
        path = self._cache_file_path()
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(self._cache, f, indent=2)
            except (IOError, OSError):
                pass

    def get(self, res_type: str, resource_value: int) -> Optional[dict]:
        key = self._cache_key(res_type, resource_value)
        return self._cache.get(key)

    def set(self, res_type: str, resource_value: int, result: dict):
        key = self._cache_key(res_type, resource_value)
        self._cache[key] = result
        self._save_disk_cache()

    def has(self, res_type: str, resource_value: int) -> bool:
        return self._cache_key(res_type, resource_value) in self._cache


def load_json(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path: str, data: dict):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _run_single_pipeline(args_tuple):
    input_path, output_path, freeze_resources, vectorized, warm_start_path = args_tuple
    pipeline_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'protection_pipeline.py')
    cmd = [sys.executable, pipeline_path, input_path, output_path]
    if vectorized:
        cmd.append('--vectorized')
    if freeze_resources:
        cmd.extend(['--freeze-resources', freeze_resources])
    if warm_start_path:
        cmd.extend(['--warm-start', warm_start_path])

    result = subprocess.run(cmd, capture_output=True, text=True)
    return output_path, result.returncode, result.stderr


def _generate_temp_inputs(base_input: dict, res_type: str, resource_values: List[int],
                          output_dir: str) -> List[Tuple[str, str, str, bool]]:
    tasks = []
    other_resources = [r for r in RESOURCE_MAP.keys() if r != res_type]
    freeze_str = ','.join(other_resources)

    for rv in resource_values:
        temp_input = copy.deepcopy(base_input)
        temp_input['constraints'][RESOURCE_MAP[res_type]] = rv
        for other in other_resources:
            temp_input['constraints'][RESOURCE_MAP[other]] = 0

        temp_input_path = os.path.join(output_dir, f'temp_input_{res_type}_{rv}.json')
        temp_output_path = os.path.join(output_dir, f'temp_output_{res_type}_{rv}.json')
        save_json(temp_input_path, temp_input)
        tasks.append((temp_input_path, temp_output_path, freeze_str, False, None))

    return tasks


def _run_pipeline_parallel(tasks: List[Tuple], workers: int, vectorized: bool,
                           res_type: str, resource_values: List[int],
                           cache: BenefitCache = None) -> List[dict]:
    final_tasks = []
    final_rvs = []
    for idx, (inp, outp, freeze, _, _) in enumerate(tasks):
        rv = resource_values[idx]
        if cache and cache.has(res_type, rv):
            continue
        final_tasks.append((inp, outp, freeze, vectorized, None))
        final_rvs.append(rv)

    results = {}
    if cache:
        for rv in resource_values:
            cached = cache.get(res_type, rv)
            if cached:
                results[rv] = cached

    if final_tasks:
        print(f"  [CACHE] 命中 {len(resource_values) - len(final_tasks)}/{len(resource_values)} 个缓存，需运行 {len(final_tasks)} 个任务")

    failed_rvs = []
    total = len(final_tasks)
    done = 0
    start = time.time()

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for idx, task in enumerate(final_tasks):
            rv = final_rvs[idx]
            futures[executor.submit(_run_single_pipeline, task)] = rv

        for future in as_completed(futures):
            rv = futures[future]
            done += 1
            output_path, returncode, stderr = future.result()
            elapsed = time.time() - start

            if returncode != 0:
                print(f"  [{done}/{total}] {res_type}={rv} FAIL ({elapsed:.0f}s) {stderr[:200]}")
                failed_rvs.append(rv)
                continue

            try:
                output = load_json(output_path)
                result = {
                    'resource_value': rv,
                    'total_protection_benefit': output['summary']['total_protection_benefit'],
                    'best_fitness': output['summary']['best_fitness'],
                    'resources_deployed': output['summary']['resources_deployed'],
                    'output_json': output_path
                }
                results[rv] = result
                if cache:
                    cache.set(res_type, rv, result)
                print(f"  [{done}/{total}] {res_type}={rv} OK  benefit={result['total_protection_benefit']:.4f}  fitness={result['best_fitness']:.4f}  ({elapsed:.0f}s)")
            except (IOError, OSError, json.JSONDecodeError, KeyError, ValueError) as e:
                print(f"  [{done}/{total}] {res_type}={rv} PARSE ERROR: {e}")
                failed_rvs.append(rv)

    if failed_rvs:
        print(f"\n  [RETRY] {len(failed_rvs)} 个失败点将串行重试...")
        rv_to_task = {final_rvs[idx]: final_tasks[idx] for idx in range(len(final_tasks))}
        for rv in sorted(failed_rvs):
            if rv not in rv_to_task:
                continue
            task = rv_to_task[rv]
            output_path, returncode, stderr = _run_single_pipeline(task)
            if returncode == 0:
                try:
                    output = load_json(output_path)
                    result = {
                        'resource_value': rv,
                        'total_protection_benefit': output['summary']['total_protection_benefit'],
                        'best_fitness': output['summary']['best_fitness'],
                        'resources_deployed': output['summary']['resources_deployed'],
                        'output_json': output_path
                    }
                    results[rv] = result
                    if cache:
                        cache.set(res_type, rv, result)
                    print(f"  [RETRY OK] {res_type}={rv}  benefit={result['total_protection_benefit']:.4f}")
                except (IOError, OSError, json.JSONDecodeError, KeyError, ValueError) as e:
                    print(f"  [RETRY FAIL] {res_type}={rv}  parse error: {e}")
            else:
                print(f"  [RETRY FAIL] {res_type}={rv}  {stderr[:200]}")

    sorted_results = [results[rv] for rv in resource_values if rv in results]
    return sorted_results


def _run_single_group(args_tuple):
    base_input, res_type, group_values, output_dir, vectorized, freeze_str, pipeline_path, group_id = args_tuple
    other_resources = [r for r in RESOURCE_MAP.keys() if r != res_type]
    group_results = {}
    prev_output_path = None
    prefix = f"  [G{group_id}]"

    for idx, rv in enumerate(group_values):
        temp_input = copy.deepcopy(base_input)
        temp_input['constraints'][RESOURCE_MAP[res_type]] = rv
        for other in other_resources:
            temp_input['constraints'][RESOURCE_MAP[other]] = 0

        temp_input_path = os.path.join(output_dir, f'temp_input_{res_type}_{rv}.json')
        temp_output_path = os.path.join(output_dir, f'temp_output_{res_type}_{rv}.json')
        save_json(temp_input_path, temp_input)

        cmd = [sys.executable, pipeline_path, temp_input_path, temp_output_path]
        if vectorized:
            cmd.append('--vectorized')
        if freeze_str:
            cmd.extend(['--freeze-resources', freeze_str])
        if prev_output_path and os.path.exists(prev_output_path):
            cmd.extend(['--warm-start', prev_output_path])

        warm_tag = "WARM" if (prev_output_path and os.path.exists(prev_output_path)) else "COLD"

        run_start = time.time()
        proc_result = subprocess.run(cmd, capture_output=True, text=True)
        run_elapsed = time.time() - run_start

        if proc_result.returncode != 0:
            print(f"{prefix} [{idx+1}/{len(group_values)}] {res_type}={rv} [{warm_tag}] FAIL ({run_elapsed:.0f}s)")
            print(f"{prefix} {proc_result.stderr[:300]}")
            prev_output_path = None
            continue

        try:
            output = load_json(temp_output_path)
            result = {
                'resource_value': rv,
                'total_protection_benefit': output['summary']['total_protection_benefit'],
                'best_fitness': output['summary']['best_fitness'],
                'resources_deployed': output['summary']['resources_deployed'],
                'output_json': temp_output_path
            }
            group_results[rv] = result
            prev_output_path = temp_output_path
            print(f"{prefix} [{idx+1}/{len(group_values)}] {res_type}={rv} [{warm_tag}] OK  benefit={result['total_protection_benefit']:.4f}  ({run_elapsed:.0f}s)")
        except (IOError, OSError, json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"{prefix} [{idx+1}/{len(group_values)}] {res_type}={rv} [{warm_tag}] PARSE ERROR: {e}")
            prev_output_path = None

    return group_results


def _run_pipeline_hybrid(base_input: dict, res_type: str, resource_values: List[int],
                         output_dir: str, vectorized: bool, num_groups: int,
                         cache: BenefitCache = None) -> List[dict]:
    other_resources = [r for r in RESOURCE_MAP.keys() if r != res_type]
    freeze_str = ','.join(other_resources)
    pipeline_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'protection_pipeline.py')

    cached_results = {}
    remaining_values = []
    for rv in resource_values:
        if cache and cache.has(res_type, rv):
            cached_results[rv] = cache.get(res_type, rv)
        else:
            remaining_values.append(rv)

    if cached_results:
        print(f"  [CACHE] 命中 {len(cached_results)}/{len(resource_values)} 个缓存")

    if not remaining_values:
        print(f"  [HYBRID] 所有点均已缓存，跳过运行")
        sorted_vals = sorted(resource_values)
        return [cached_results[v] for v in sorted_vals if v in cached_results]

    actual_groups = min(num_groups, len(remaining_values))
    groups = []
    chunk_size = (len(remaining_values) + actual_groups - 1) // actual_groups
    for i in range(actual_groups):
        start_idx = i * chunk_size
        end_idx = min(start_idx + chunk_size, len(remaining_values))
        group_chunk = remaining_values[start_idx:end_idx]
        if group_chunk:
            groups.append(group_chunk)

    total_points = sum(len(g) for g in groups)
    print(f"  [HYBRID] 分组模式: {actual_groups} 组并行, {total_points} 个待计算点")
    for gi, g in enumerate(groups):
        print(f"    组{gi+1}: {g[0]}-{g[-1]} ({len(g)}点)")

    all_results = dict(cached_results)
    start = time.time()

    with ProcessPoolExecutor(max_workers=actual_groups) as executor:
        futures = {}
        for gi, group_vals in enumerate(groups):
            task_args = (
                base_input, res_type, group_vals,
                output_dir, vectorized, freeze_str, pipeline_path, gi + 1
            )
            futures[executor.submit(_run_single_group, task_args)] = gi

        for future in as_completed(futures):
            gi = futures[future]
            try:
                group_results = future.result()
                for rv, result in group_results.items():
                    all_results[rv] = result
                    if cache:
                        cache.set(res_type, rv, result)
                elapsed = time.time() - start
                print(f"  [GROUP {gi+1} DONE] {len(group_results)}/{len(groups[gi])} 成功  ({elapsed:.0f}s)")
            except (IOError, OSError, json.JSONDecodeError, KeyError, ValueError) as e:
                elapsed = time.time() - start
                print(f"  [GROUP {gi+1} ERROR] {e}  ({elapsed:.0f}s)")

    sorted_results = [all_results[rv] for rv in resource_values if rv in all_results]
    return sorted_results



def _find_saturation_point(results: List[dict], resource_values: List[int],
                           threshold_ratio: float = 0.05) -> Optional[int]:
    if len(results) < 3:
        return None

    benefits = {r['resource_value']: r['total_protection_benefit'] for r in results}

    marginal = {}
    sorted_vals = sorted(resource_values)
    for i in range(1, len(sorted_vals)):
        v_prev, v_curr = sorted_vals[i - 1], sorted_vals[i]
        if v_prev in benefits and v_curr in benefits:
            dv = v_curr - v_prev
            if dv > 0:
                marginal[v_curr] = (benefits[v_curr] - benefits[v_prev]) / dv

    if not marginal:
        return None

    max_marginal = max(marginal.values())
    if max_marginal <= 0:
        return None

    for v in sorted_vals:
        if v in marginal and marginal[v] < max_marginal * threshold_ratio:
            return v

    return None


def _merge_results(coarse_results: List[dict], fine_results: List[dict]) -> List[dict]:
    merged = {r['resource_value']: r for r in coarse_results}
    for r in fine_results:
        merged[r['resource_value']] = r
    return sorted(merged.values(), key=lambda x: x['resource_value'])


def run_sensitivity_analysis(
    base_input_path: str,
    resource_type: str,
    resource_range: Tuple[int, int, int] = None,
    output_dir: str = './sensitivity_results',
    vectorized: bool = False,
    workers: int = None,
    two_step: bool = False,
    fine_step_ratio: int = 5,
    warm_start: bool = False,
    warm_start_groups: int = None,
    use_cache: bool = True,
):
    if workers is None:
        workers = os.cpu_count() or 1

    if warm_start and warm_start_groups is None:
        warm_start_groups = 1

    os.makedirs(output_dir, exist_ok=True)

    cache = None
    if use_cache:
        cache = BenefitCache(cache_dir=os.path.join(output_dir, '.cache'))

    print(f"\n加载基础输入: {base_input_path}")
    base_input = load_json(base_input_path)

    if resource_type == 'all':
        resources_to_analyze = list(RESOURCE_MAP.keys())
    else:
        resources_to_analyze = [resource_type]

    for res_type in resources_to_analyze:
        mode_str = "parallel" if not warm_start else (f"hybrid({warm_start_groups}groups)" if warm_start_groups > 1 else "serial-warm")
        print(f"\n{'=' * 70}")
        print(f"分析资源: {res_type.upper()}  (workers={workers}, mode={mode_str}, vectorized={vectorized}, two_step={two_step})")
        print(f"{'=' * 70}")

        current_range = resource_range if resource_range is not None else DEFAULT_RANGES.get(res_type)
        if current_range is None:
            print(f"  [skip] 未知资源类型: {res_type}")
            continue

        min_val, max_val, step = current_range
        resource_values = list(range(min_val, max_val + 1, step))

        print(f"资源范围: {min_val} - {max_val}, 步长: {step}, 采样点: {len(resource_values)}")
        print(f"其他资源约束置0，冻结资源: {','.join(r for r in RESOURCE_MAP.keys() if r != res_type)}")

        if warm_start:
            if warm_start_groups > 1:
                actual_groups = min(warm_start_groups, len(resource_values))
                print(f"\n--- 分组热启动模式：{actual_groups} 组并行，组内串行热启动 ---")
                results = _run_pipeline_hybrid(base_input, res_type, resource_values,
                                               output_dir, vectorized, actual_groups, cache)
            else:
                print(f"\n--- 纯串行热启动模式：按资源值递增顺序执行 ---")
                results = _run_pipeline_warm_start(base_input, res_type, resource_values,
                                                   output_dir, vectorized, cache)
        else:
            tasks = _generate_temp_inputs(base_input, res_type, resource_values, output_dir)
            results = _run_pipeline_parallel(tasks, workers, vectorized, res_type, resource_values, cache)

        if two_step and len(results) >= 3:
            print(f"\n--- 两步法：粗扫完成，定位饱和区 ---")
            sat_point = _find_saturation_point(results, resource_values)
            if sat_point is not None:
                fine_step = max(1, step // fine_step_ratio)
                lo = max(min_val, sat_point - 2 * step)
                hi = min(max_val, sat_point + 2 * step)
                fine_values = [v for v in range(lo, hi + 1, fine_step) if v not in set(resource_values)]

                if fine_values:
                    if warm_start:
                        if warm_start_groups > 1:
                            fine_groups = min(warm_start_groups, len(fine_values))
                            print(f"  饱和点 ≈ {sat_point}, 细扫区间: [{lo}, {hi}], 步长: {fine_step}, 新增点: {len(fine_values)} (分组热启动 {fine_groups}组)")
                            fine_results = _run_pipeline_hybrid(base_input, res_type, fine_values,
                                                                output_dir, vectorized, fine_groups, cache)
                        else:
                            print(f"  饱和点 ≈ {sat_point}, 细扫区间: [{lo}, {hi}], 步长: {fine_step}, 新增点: {len(fine_values)} (串行热启动)")
                            fine_results = _run_pipeline_warm_start(base_input, res_type, fine_values,
                                                                    output_dir, vectorized, cache)
                    else:
                        fine_workers = max(1, min(4, workers // 2))
                        print(f"  饱和点 ≈ {sat_point}, 细扫区间: [{lo}, {hi}], 步长: {fine_step}, 新增点: {len(fine_values)}, workers={fine_workers}")
                        fine_tasks = _generate_temp_inputs(base_input, res_type, fine_values, output_dir)
                        fine_results = _run_pipeline_parallel(fine_tasks, fine_workers, vectorized, res_type, fine_values, cache)
                    results = _merge_results(results, fine_results)
                    resource_values = sorted(set(resource_values + fine_values))
                    print(f"  合并后总数据点: {len(results)}")
                else:
                    print(f"  饱和点 ≈ {sat_point}, 但无新增细扫点（粗扫已覆盖），跳过细扫")
            else:
                print(f"  未找到明确饱和点，跳过细扫")

        sensitivity_results = {
            'resource_type': res_type,
            'resource_values': resource_values,
            'results': results
        }

        result_path = os.path.join(output_dir, f'sensitivity_{res_type}.json')
        save_json(result_path, sensitivity_results)

        if not results:
            print(f"\n[ERROR] 资源 {res_type} 的所有优化均失败！")
        else:
            print(f"\n[OK] 结果已保存: {result_path} ({len(results)}/{len(resource_values)} 成功)")

        plot_sensitivity_results(result_path, os.path.join(output_dir, f'sensitivity_{res_type}_plot.png'))


def plot_sensitivity_results(sensitivity_json_path: str, output_path: str):
    results = load_json(sensitivity_json_path)
    resource_type = results['resource_type']
    resource_values = results['resource_values']

    if not results['results']:
        print(f"  [skip] 无有效结果，跳过绘图")
        return

    rv_map = {r['resource_value']: r for r in results['results']}

    sorted_vals = sorted(rv_map.keys())
    total_benefits = [rv_map[v]['total_protection_benefit'] for v in sorted_vals]
    best_fitnesses = [rv_map[v]['best_fitness'] for v in sorted_vals]

    marginal_benefits = [0]
    for i in range(1, len(sorted_vals)):
        dv = sorted_vals[i] - sorted_vals[i - 1]
        if dv > 0:
            marginal_benefits.append((total_benefits[i] - total_benefits[i - 1]) / dv)
        else:
            marginal_benefits.append(0)

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    ax = axes[0, 0]
    ax.plot(sorted_vals, total_benefits, 'o-', linewidth=2, markersize=6, color='#2ca02c')
    ax.set_xlabel(f'{resource_type.capitalize()} Count', fontsize=11)
    ax.set_ylabel('Total Protection Benefit', fontsize=11)
    ax.set_title(f'Protection Benefit vs {resource_type.capitalize()} Count', fontsize=12, fontweight='bold')
    ax.grid(True, alpha=0.3)

    ax = axes[0, 1]
    ax.plot(sorted_vals, best_fitnesses, 's-', linewidth=2, markersize=6, color='#1f77b4')
    ax.set_xlabel(f'{resource_type.capitalize()} Count', fontsize=11)
    ax.set_ylabel('Best Fitness', fontsize=11)
    ax.set_title(f'Fitness vs {resource_type.capitalize()} Count', fontsize=12, fontweight='bold')
    ax.grid(True, alpha=0.3)

    ax = axes[1, 0]
    ax.plot(sorted_vals, marginal_benefits, '^-', linewidth=2, markersize=6, color='#ff7f0e')
    ax.set_xlabel(f'{resource_type.capitalize()} Count', fontsize=11)
    ax.set_ylabel('Marginal Benefit', fontsize=11)
    ax.set_title(f'Marginal Benefit vs {resource_type.capitalize()} Count', fontsize=12, fontweight='bold')
    ax.grid(True, alpha=0.3)
    ax.axhline(y=0, color='k', linestyle='--', linewidth=0.5, alpha=0.5)

    ax = axes[1, 1]
    ax.axis('off')
    table_data = [['Resource', 'Benefit', 'Fitness', 'Marginal']]
    for i, v in enumerate(sorted_vals):
        table_data.append([
            str(v),
            f"{total_benefits[i]:.4f}",
            f"{best_fitnesses[i]:.4f}",
            f"{marginal_benefits[i]:.4f}"
        ])
    table = ax.table(cellText=table_data, cellLoc='center', loc='upper center',
                     colWidths=[0.2, 0.25, 0.25, 0.25])
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.4)
    for i in range(4):
        table[(0, i)].set_facecolor('#4CAF50')
        table[(0, i)].set_text_props(weight='bold', color='white')
    for i in range(1, len(table_data)):
        for j in range(4):
            table[(i, j)].set_facecolor('#f0f0f0' if i % 2 == 0 else '#ffffff')

    ax.set_title(f'Sensitivity Analysis Summary: {resource_type.upper()}',
                 fontsize=11, fontweight='bold', pad=6, loc='left')

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
  python sensitivity_analysis.py --input base.json --resource camera --range 0 400 10 --workers 4
  python sensitivity_analysis.py --input base.json --resource camera --range 0 400 50 --two-step --workers 4
  python sensitivity_analysis.py --input base.json --resource camera --range 0 400 10 --warm-start
  python sensitivity_analysis.py --input base.json --resource camera --range 0 400 10 --warm-start --warm-start-groups 4
  python sensitivity_analysis.py --input base.json --resource all --vectorized

Resources:
  patrol  - 巡逻人员 (default range: 0-50, step 5)
  camera  - 摄像头 (default range: 0-20, step 2)
  drone   - 无人机 (default range: 0-10, step 1)
  camp    - 营地 (default range: 0-5, step 1)
  fence   - 围栏 (default range: 0-100, step 10)
  all     - 分析所有资源

Optimization Strategies:
  --warm-start          启用热启动（默认1组=纯串行）
  --warm-start-groups N 分组混合模式：N组并行，组内串行热启动（推荐 N=workers 数量）
                        例如: --warm-start --warm-start-groups 4 表示4个并行组
  --no-cache            禁用缓存（默认启用缓存避免重复计算）
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
    parser.add_argument("--workers", "-w", type=int, default=os.cpu_count(),
                        help="资源内并行工作进程数（默认系统核数）")
    parser.add_argument("--two-step", action="store_true", default=False,
                        help="启用两步法：粗扫全范围后自动定位饱和区细扫")
    parser.add_argument("--fine-step-ratio", type=int, default=5,
                        help="两步法细扫步长 = 粗步长 / 此值（默认5）")
    parser.add_argument("--warm-start", action="store_true", default=False,
                        help="启用热启动：按资源值递增顺序串行执行，低资源点结果作为高资源点初始解")
    parser.add_argument("--warm-start-groups", type=int, default=None,
                        help="分组混合模式的并行组数（需配合 --warm-start 使用）。"
                             "默认1（纯串行），设为>1时启用分组并行，推荐设为workers数")
    parser.add_argument("--no-cache", action="store_true", default=False,
                        help="禁用缓存（默认启用缓存避免重复计算）")

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"错误: 输入文件不存在: {args.input}")
        sys.exit(1)

    resource_range = None
    if args.range:
        resource_range = tuple(args.range)

    run_sensitivity_analysis(
        args.input,
        args.resource,
        resource_range=resource_range,
        output_dir=args.output,
        vectorized=args.vectorized,
        workers=args.workers,
        two_step=args.two_step,
        fine_step_ratio=args.fine_step_ratio,
        warm_start=args.warm_start,
        warm_start_groups=args.warm_start_groups,
        use_cache=not args.no_cache,
    )

    has_empty = False
    resources_to_check = list(RESOURCE_MAP.keys()) if args.resource == 'all' else [args.resource]
    for res in resources_to_check:
        result_path = os.path.join(args.output, f'sensitivity_{res}.json')
        if os.path.exists(result_path):
            with open(result_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not data.get('results'):
                has_empty = True
                break

    if has_empty:
        print(f"\n{'=' * 70}")
        print("[ERROR] 敏感性分析完成，但部分资源结果为空！")
        print(f"  请检查 protection_pipeline.py 是否可正常运行")
        print(f"{'=' * 70}\n")
        sys.exit(2)

    print(f"\n{'=' * 70}")
    print("[OK] 敏感性分析完成！")
    print(f"  结果保存在: {args.output}")
    print(f"{'=' * 70}\n")


if __name__ == '__main__':
    main()
