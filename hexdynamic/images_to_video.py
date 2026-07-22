#!/usr/bin/env python3
"""
从 DSSA 优化输出目录读取每轮迭代的 best.json，生成 deployment_map 图片并合成视频。

工作流程:
  1. 加载 input JSON 获取网格数据，预计算地形底图（hex 位置 + 颜色）
  2. 遍历 iteration_XXXX 目录，读取 best.json
  3. 多进程并发生成 deployment_map PNG（底图预渲染 + 部署增量绘制）
  4. 使用 ffmpeg 将 PNG 序列合成为 MP4 视频

用法:
    python images_to_video.py --input_dir ./figures/big1 --input_json ./inputs/base.json --output video.mp4 --fps 5
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional


TERRAIN_COLORS = {
    "SparseGrass": "#a8d5a2",
    "DenseGrass":  "#2d6a2d",
    "WaterHole":   "#5b9bd5",
    "SaltMarsh":   "#c8b97a",
    "Road":        "#888888",
}

RESOURCE_MARKERS = {
    "camera":         ("s", "#1f77b4", "Camera"),
    "drone":          ("^", "#ff7f0e", "Drone"),
    "camp":           ("D", "#9467bd", "Camp"),
    "patrol_rangers": ("o", "#2ca02c", "Patrol"),
}

FENCE_COLOR = "#c0392b"
FENCE_EDGE_LINEWIDTH = 3.0

# ── Worker process globals (loaded from file in initializer to avoid pickle OOM) ──
_worker_grids = None
_worker_hex_size = None
_worker_boundary_xy = None
_worker_terrain_patches = None
_worker_terrain_png_path = None        # pre-rendered terrain base layer PNG
_worker_terrain_extent = None           # (xmin, xmax, ymin, ymax) matching the PNG
_worker_terrain_img = None              # uint8 RGBA numpy array (loaded once per worker)


def _worker_init(params: Dict[str, Any]):
    """Initialize worker process — loads data from lightweight index file.

    Instead of loading the full input JSON (50+ MB for 43K grids), workers
    load a minimal grid index (~3 MB) containing only grid_id, q, r,
    terrain_type, and hex_size. This avoids MemoryError when 8+ workers
    start simultaneously on Windows (spawn mode).
    """
    global _worker_grids, _worker_hex_size, _worker_boundary_xy, _worker_terrain_patches
    global _worker_terrain_png_path, _worker_terrain_extent, _worker_terrain_img

    _worker_hex_size = params['hex_size']
    _worker_boundary_xy = params['boundary_xy']
    _worker_terrain_patches = params.get('terrain_patches')  # only in fallback mode
    _worker_terrain_png_path = params.get('terrain_png_path')
    _worker_terrain_extent = params.get('terrain_extent')

    # Load minimal grid index (created by master process) instead of full JSON
    grid_index_path = params.get('grid_index_path')
    if grid_index_path and os.path.exists(grid_index_path):
        with open(grid_index_path, 'r', encoding='utf-8') as f:
            _worker_grids = json.load(f)
    else:
        # Fallback: load full input JSON
        input_json_path = params['input_json_path']
        with open(input_json_path, 'r', encoding='utf-8') as f:
            _data = json.load(f)
        _worker_grids = _data.get('grids', [])

    # Pre-load terrain PNG as uint8 once per worker (plt.imread would
    # convert to float32, wasting 4x memory — 228 MB vs 57 MB).
    if _worker_terrain_png_path and os.path.exists(_worker_terrain_png_path):
        from PIL import Image
        import numpy as np
        pil_img = Image.open(_worker_terrain_png_path)
        _worker_terrain_img = np.asarray(pil_img)
        pil_img.close()


def _get_available_memory_mb() -> Optional[float]:
    """Return available system RAM in MB, or None if can't determine."""
    try:
        import psutil
        return psutil.virtual_memory().available / (1024 * 1024)
    except ImportError:
        return None


def _read_deployment(best_json_path: str) -> dict:
    """Extract deployment dict from best.json for comparison."""
    with open(best_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return {
        'cameras': {int(k): v for k, v in data.get('cameras', {}).items()},
        'camps': {int(k): v for k, v in data.get('camps', {}).items()},
        'drones': {int(k): v for k, v in data.get('drones', {}).items()},
        'rangers': {int(k): v for k, v in data.get('rangers', {}).items()},
        'fences': {str(k): v for k, v in data.get('fences', {}).items()},
    }


def natural_sort_key(path: str) -> List:
    parts = re.split(r'(\d+)', str(path))
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def load_grid_data(input_json_path: str) -> Dict[str, Any]:
    with open(input_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    grids = data.get('grids', [])
    hex_size = 10.0
    for g in grids:
        if g.get('hex_size'):
            hex_size = float(g['hex_size'])
            break

    boundary_xy = None
    mc = data.get('map_config', {})
    bl = mc.get('boundary_locations')
    if bl:
        boundary_xy = []
        for item in bl:
            if isinstance(item, dict):
                boundary_xy.append((item['x'], item['y']))
            else:
                boundary_xy.append(tuple(item))

    return {
        'grids': grids,
        'hex_size': hex_size,
        'boundary_xy': boundary_xy,
    }


def precompute_terrain(grid_data: Dict[str, Any]) -> Dict[str, Any]:
    from visualize_output import grid_center

    grids = grid_data['grids']
    hex_size = grid_data['hex_size']
    terrain_patches = []
    for g in grids:
        cx, cy = grid_center(g['q'], g['r'], hex_size)
        fc = TERRAIN_COLORS.get(g.get('terrain_type', 'SparseGrass'), '#ccc')
        terrain_patches.append((cx, cy, fc))

    return {
        'grids': grids,
        'hex_size': hex_size,
        'boundary_xy': grid_data['boundary_xy'],
        'terrain_patches': terrain_patches,
    }


def _render_terrain_base_map(grids, hex_size, boundary_xy, terrain_patches,
                              grid_dpi, save_dpi, output_path):
    """
    Pre-render the static terrain + boundary layer once as a standalone
    map image. Workers load this PNG as background and only overlay
    per-iteration resources, avoiding 43K polygon allocations per process.

    Returns (extent_xmin, extent_xmax, extent_ymin, extent_ymax) so workers
    can align their imshow() to the data coordinate system.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon
    from matplotlib.collections import PatchCollection
    from visualize_output import (compute_figsize, hex_corners, setup_map_ax,
                                   draw_boundary)

    # Build a figure with only the map axes (no legend panel) at the
    # same position / size as the full deployment-map figure.
    figsize, fracs = compute_figsize(grids, hex_size, grid_dpi, save_dpi, has_colorbar=False)
    map_fw, map_fh, _, _ = fracs

    left_pad = 0.02
    bottom_pad = 0.06
    usable_w = 1.0 - left_pad - 0.01   # right_pad
    usable_h = 1.0 - 0.08 - bottom_pad  # top_pad - bottom_pad
    map_w = map_fw * usable_w

    fig = plt.figure(figsize=figsize)
    ax_map = fig.add_axes([left_pad, bottom_pad, map_w, map_fh * usable_h])

    # Draw terrain hexagons
    _patches = [Polygon(hex_corners(cx, cy, hex_size * 0.97), closed=True)
                for cx, cy, _fc in terrain_patches]
    _facecolors = [fc for _, _, fc in terrain_patches]
    pc = PatchCollection(_patches, facecolors=_facecolors,
                         edgecolors='black', linewidths=0.4, alpha=0.45, zorder=1)
    ax_map.add_collection(pc)
    setup_map_ax(ax_map, grids, hex_size)
    draw_boundary(ax_map, grids, boundary_xy, hex_size)
    ax_map.axis('off')

    # Record the data-extent of the rendered image
    xlim = ax_map.get_xlim()
    ylim = ax_map.get_ylim()
    extent = (xlim[0], xlim[1], ylim[0], ylim[1])

    fig.savefig(output_path, dpi=save_dpi, bbox_inches='tight',
                pad_inches=0, facecolor=fig.get_facecolor())
    plt.close(fig)

    return extent


def _draw_legend(ax_leg):
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt

    terrain_handles = [mpatches.Patch(facecolor=c, edgecolor="black", linewidth=0.5, alpha=0.5, label=t)
                       for t, c in TERRAIN_COLORS.items()]
    res_handles = [
        plt.Line2D([0], [0], marker=m, color="w", markerfacecolor=c,
               markeredgecolor="black", markersize=8, label=l)
        for _, (m, c, l) in RESOURCE_MARKERS.items()
    ]
    fence_handle = plt.Line2D([0], [0], color=FENCE_COLOR, linewidth=FENCE_EDGE_LINEWIDTH, label="Fence")

    y = 0.97
    ax_leg.text(0.05, y, "Terrain Type", transform=ax_leg.transAxes,
            fontsize=9, fontweight="bold", va="top")
    y -= 0.06
    for h in terrain_handles:
        rect = mpatches.FancyBboxPatch((0.05, y - 0.025), 0.12, 0.04,
                                   boxstyle="square,pad=0",
                                   facecolor=h.get_facecolor(),
                                   edgecolor="black", linewidth=0.5,
                                   transform=ax_leg.transAxes, clip_on=False)
        ax_leg.add_patch(rect)
        ax_leg.text(0.22, y - 0.005, h.get_label(), transform=ax_leg.transAxes,
                fontsize=9, va="center")
        y -= 0.055

    y -= 0.02
    ax_leg.text(0.05, y, "Resources", transform=ax_leg.transAxes,
            fontsize=9, fontweight="bold", va="top")
    y -= 0.06
    for h in res_handles + [fence_handle]:
        marker = h.get_marker()
        if marker and marker != 'None':
            mfc = h.get_markerfacecolor()
            mec = h.get_markeredgecolor()
            ax_leg.plot(0.11, y - 0.005, marker=marker, color="w",
                    markerfacecolor=mfc, markeredgecolor=mec,
                    markersize=8, transform=ax_leg.transAxes,
                    clip_on=False)
        else:
            ax_leg.plot([0.05, 0.17], [y - 0.005, y - 0.005],
                    color=h.get_color(), linewidth=h.get_linewidth(),
                    transform=ax_leg.transAxes, clip_on=False)
        ax_leg.text(0.22, y - 0.005, h.get_label(), transform=ax_leg.transAxes,
                fontsize=9, va="center")
        y -= 0.055


def _render_single_map(args: Tuple) -> Optional[str]:
    """Render a single deployment map (runs in worker process, uses shared globals)."""
    best_json_path, output_png_path, iteration, grid_dpi, save_dpi = args

    try:
        import gc
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        matplotlib.rcParams["figure.max_open_warning"] = 0

        with open(best_json_path, 'r', encoding='utf-8') as f:
            best_data = json.load(f)

        from visualize_output import (
            make_figure, setup_map_ax, hex_corners, draw_boundary,
            draw_deployed_fence_edges, _draw_resources, _edge_grid_ids
        )

        # Use shared read-only data from worker globals (set by initializer)
        grids = _worker_grids
        hex_size = _worker_hex_size
        boundary_xy = _worker_boundary_xy
        terrain_patches = _worker_terrain_patches

        cameras = {int(k): v for k, v in best_data.get('cameras', {}).items()}
        camps = {int(k): v for k, v in best_data.get('camps', {}).items()}
        drones = {int(k): v for k, v in best_data.get('drones', {}).items()}
        rangers = {int(k): v for k, v in best_data.get('rangers', {}).items()}
        fences_raw = best_data.get('fences', {})
        fences = {}
        for k, v in fences_raw.items():
            parts = k.split('-')
            if len(parts) == 2:
                fences[(int(parts[0]), int(parts[1]))] = v

        plot_grids = []
        for g in grids:
            gid = g['grid_id']
            ng = dict(g)
            dep = dict(g.get('deployment', {}))
            dep['camera'] = cameras.get(gid, 0)
            dep['drone'] = drones.get(gid, 0)
            dep['camp'] = camps.get(gid, 0)
            dep['patrol_rangers'] = rangers.get(gid, 0)
            ng['deployment'] = dep
            grid_fence_edges = [(e[0], e[1]) for e, v in fences.items()
                               if v > 0 and e[0] == gid and isinstance(e[1], int)]
            if grid_fence_edges:
                ng['fences'] = {
                    'fence_count': len(grid_fence_edges),
                    'boundary_edge_list': [direction for _, direction in grid_fence_edges]
                }
            elif 'fences' in ng:
                del ng['fences']
            plot_grids.append(ng)

        output_base = {'grids': plot_grids}

        fig, ax_map, _, ax_leg = make_figure(
            grids=plot_grids, hex_size=hex_size,
            grid_dpi=grid_dpi, save_dpi=save_dpi, has_colorbar=False
        )

        # ── Base layer: pre-rendered terrain (uint8 array loaded once per worker) ──
        terrain_extent = _worker_terrain_extent
        if _worker_terrain_img is not None and terrain_extent:
            ax_map.imshow(_worker_terrain_img, extent=terrain_extent,
                          interpolation='none', zorder=0, aspect='auto')
            ax_map.set_xlim(terrain_extent[0], terrain_extent[1])
            ax_map.set_ylim(terrain_extent[2], terrain_extent[3])
            ax_map.set_aspect('equal')
            ax_map.axis('off')
        else:
            # Fallback: render terrain hexagons inline (43K polygons — heavy!)
            from matplotlib.patches import Polygon
            from matplotlib.collections import PatchCollection
            _patches = [Polygon(hex_corners(cx, cy, hex_size * 0.97), closed=True)
                        for cx, cy, _fc in terrain_patches]
            _facecolors = [fc for _, _, fc in terrain_patches]
            pc = PatchCollection(_patches, facecolors=_facecolors,
                                 edgecolors='black', linewidths=0.4, alpha=0.45, zorder=1)
            ax_map.add_collection(pc)
            setup_map_ax(ax_map, plot_grids, hex_size)
            draw_boundary(ax_map, plot_grids, boundary_xy, hex_size)

        # ── Upper layer: per-iteration resource deployment ──
        edge_ids = _edge_grid_ids(plot_grids, boundary_xy, hex_size)

        _draw_resources(ax_map, plot_grids, output_base, hex_size, edge_ids)
        draw_deployed_fence_edges(ax_map, plot_grids, output_base, hex_size)

        ax_map.set_title(f"Iteration {iteration:04d}", fontsize=13, fontweight='bold', pad=8)

        _draw_legend(ax_leg)

        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        # Try savefig at requested save_dpi; on MemoryError, retry at lower DPI
        # on the SAME figure object (lower dpi = smaller raster = less memory).
        last_err = None
        for attempt_dpi in (save_dpi, max(50, save_dpi // 2), max(40, save_dpi // 4)):
            try:
                fig.savefig(output_png_path, dpi=attempt_dpi, bbox_inches="tight")
                if attempt_dpi != save_dpi:
                    print(f"  [WARN] iteration {iteration}: OOM at dpi={save_dpi}, saved at dpi={attempt_dpi}")
                last_err = None
                break
            except MemoryError:
                last_err = sys.exc_info()[1]
                # Raster buffer allocation failed, but the figure is still intact.
                # Clean up any partial allocations, then retry at a lower dpi
                # (1/2 dpi → 1/4 pixels → 1/4 memory).
                gc.collect()
                continue
        if last_err is not None:
            raise last_err

        plt.close(fig)
        plt.close('all')
        gc.collect()

        return output_png_path

    except Exception as e:
        print(f"[ERROR] Failed to render iteration {iteration}: {e}")
        traceback.print_exc()
        try:
            import matplotlib.pyplot as plt
            plt.close('all')
            import gc
            gc.collect()
        except:
            pass
        return None


def find_iteration_dirs(input_dir: str) -> List[Tuple[int, str]]:
    input_path = Path(input_dir)
    iterations = []
    for subdir in input_path.iterdir():
        if subdir.is_dir():
            m = re.match(r'iteration_(\d+)', subdir.name)
            if m:
                best_json = subdir / 'best.json'
                if best_json.exists():
                    iterations.append((int(m.group(1)), str(subdir)))
    iterations.sort(key=lambda x: x[0])
    return iterations


def render_all_maps(input_dir: str, input_json_path: str, output_dir: str,
                    max_workers: int = None, fps: float = 5.0,
                    grid_dpi: int = 80, save_dpi: int = 150) -> List[str]:
    grid_data = load_grid_data(input_json_path)
    precomputed = precompute_terrain(grid_data)

    iterations = find_iteration_dirs(input_dir)
    if not iterations:
        print(f"错误: 在 {input_dir} 中没有找到包含 best.json 的 iteration_XXXX 目录!")
        return []

    num_grids = len(precomputed['grids'])
    print(f"找到 {len(iterations)} 个迭代目录")
    print(f"预计算地形底图: {num_grids} 个网格")

    # ── Pre-render the static terrain base layer as PNG ──
    # This PNG is shared read-only across all workers; each worker loads it
    # via imshow() instead of constructing 43K Polygon objects.
    terrain_png_path = os.path.join(output_dir, "_terrain_base_layer.png")
    if not os.path.exists(terrain_png_path):
        print("渲染地形底图 PNG（仅一次）...")
        try:
            terrain_extent = _render_terrain_base_map(
                precomputed['grids'], precomputed['hex_size'],
                precomputed['boundary_xy'], precomputed['terrain_patches'],
                grid_dpi, save_dpi, terrain_png_path
            )
            precomputed['terrain_png_path'] = terrain_png_path
            precomputed['terrain_extent'] = terrain_extent
            print(f"  地形底图已保存: {terrain_png_path}")
        except MemoryError:
            print("  [WARN] 地形底图渲染 OOM，退化为每迭代独立渲染")
            precomputed['terrain_png_path'] = None
            precomputed['terrain_extent'] = None
    else:
        # PNG exists from a previous run — load it to extract extent
        # (extent is deterministic from grid geometry, but we need the values)
        print("地形底图 PNG 已存在，跳过渲染")
        precomputed['terrain_png_path'] = terrain_png_path
        # Recompute extent quickly without re-rendering
        from visualize_output import grid_center
        xmn = xmx = ymn = ymx = None
        hs = precomputed['hex_size']
        for g in precomputed['grids']:
            cx, cy = grid_center(g['q'], g['r'], hs)
            if xmn is None:
                xmn = xmx = cx; ymn = ymx = cy
            else:
                if cx < xmn: xmn = cx
                if cx > xmx: xmx = cx
                if cy < ymn: ymn = cy
                if cy > ymx: ymx = cy
        m = hs + 1.5  # margin matching setup_map_ax
        precomputed['terrain_extent'] = (xmn - m, xmx + m, ymn - m, ymx + m)

    maps_dir = os.path.join(output_dir, "deployment_maps")
    os.makedirs(maps_dir, exist_ok=True)

    # ── Create minimal grid index file for workers ──
    # The full input JSON can be 50+ MB (43K grids with species_densities etc).
    # Workers only need grid_id, q, r, terrain_type, hex_size — strip everything
    # else to produce a ~3 MB index file that loads fast and uses little RAM.
    grid_index_path = os.path.join(output_dir, "_grid_index.json")
    if not os.path.exists(grid_index_path):
        print("生成轻量网格索引...")
        minimal_grids = []
        for g in precomputed['grids']:
            minimal_grids.append({
                'grid_id': g['grid_id'],
                'q': g['q'],
                'r': g['r'],
                'x': g.get('x'),
                'y': g.get('y'),
                'terrain_type': g.get('terrain_type', 'SparseGrass'),
                'hex_size': g.get('hex_size'),
            })
        with open(grid_index_path, 'w', encoding='utf-8') as f:
            json.dump(minimal_grids, f, separators=(',', ':'))
        print(f"  网格索引已保存: {grid_index_path}")

    # ── Build task list with deployment deduplication ──
    tasks = []       # (best_json_path, output_png_path, iter_num, grid_dpi, save_dpi) for rendering
    copy_ops = []    # (dest_path, src_path) — copy after rendering
    prev_deployment = None
    prev_png_path = None

    for iter_num, iter_dir in iterations:
        best_json_path = os.path.join(iter_dir, "best.json")
        output_png_path = os.path.join(maps_dir, f"deployment_map_{iter_num:04d}.png")

        if os.path.exists(output_png_path):
            # Already exists — read its deployment for subsequent comparisons
            try:
                prev_deployment = _read_deployment(best_json_path)
                prev_png_path = output_png_path
            except Exception:
                prev_deployment = None
                prev_png_path = None
            continue

        try:
            current_deployment = _read_deployment(best_json_path)
        except Exception:
            tasks.append((best_json_path, output_png_path, iter_num, grid_dpi, save_dpi))
            continue

        if prev_deployment is not None and current_deployment == prev_deployment and prev_png_path:
            # Identical deployment → copy from previous map
            copy_ops.append((output_png_path, prev_png_path))
        else:
            tasks.append((best_json_path, output_png_path, iter_num, grid_dpi, save_dpi))
            prev_deployment = current_deployment
            prev_png_path = output_png_path

    copied_count = len(copy_ops)

    if not tasks and not copy_ops:
        print("所有 deployment_map 已存在，跳过渲染")
        return sorted(
            [os.path.join(maps_dir, f"deployment_map_{i:04d}.png") for i, _ in iterations],
            key=natural_sort_key
        )

    if copied_count > 0:
        print(f"检测到 {copied_count} 张 deployment_map 与上一轮部署相同，将直接复制（无需重新渲染）")

    print(f"需要渲染 {len(tasks)} 张 deployment_map（跳过 {len(iterations) - len(tasks) - copied_count} 张已存在的）")

    # ── Calculate optimal worker count with memory safety ──
    # Layered mode: terrain PNG loaded as uint8 once per worker (~57 MB for
    # 2308×6465), then per-iteration peak is imshow-copy + raster buffer (~250 MB).
    if max_workers is None:
        cpu_count = os.cpu_count() or 4
        terrain_png_loaded = bool(precomputed.get('terrain_png_path'))
        if terrain_png_loaded and os.path.exists(precomputed['terrain_png_path']):
            # Use actual PNG dimensions for accurate estimation
            from PIL import Image
            try:
                with Image.open(precomputed['terrain_png_path']) as im:
                    png_w, png_h = im.size
                # uint8 terrain array + imshow copy + raster buffer (~3x raster)
                terrain_mb = png_w * png_h * 4 / (1024 * 1024)
                raster_mb = (png_w + 300) * png_h * 4 / (1024 * 1024)  # +legend width
                est_mb_per_figure = max(80, int(terrain_mb + raster_mb * 1.5))
            except Exception:
                est_mb_per_figure = max(60, int(num_grids * save_dpi * 0.000035))
        elif terrain_png_loaded:
            est_mb_per_figure = max(60, int(num_grids * save_dpi * 0.000035))
        else:
            est_mb_per_figure = max(80, int(num_grids * save_dpi * 0.10))
        avail_mb = _get_available_memory_mb()

        if avail_mb is not None:
            safe_mb = avail_mb * 0.4  # 40% of available RAM for workers
            mem_limit = max(1, int(safe_mb / est_mb_per_figure))
            max_workers = min(cpu_count, mem_limit, 24)  # hard cap at 24
            mode = "layered" if terrain_png_loaded else "polygon"
            print(f"  可用内存: {avail_mb:.0f} MB, 单worker峰值: ~{est_mb_per_figure:.0f} MB ({mode} mode), "
                  f"内存上限: {mem_limit} workers")
        else:
            if terrain_png_loaded:
                max_workers = min(cpu_count, 8)
            else:
                max_workers = min(cpu_count, 2)
            print(f"  无法检测内存，保守设置 workers={max_workers} "
                  f"(num_grids={num_grids}, save_dpi={save_dpi}, layered={terrain_png_loaded})")
    else:
        max_workers = min(max_workers, os.cpu_count() or 4)

    print(f"使用 {max_workers} 个进程并发生成...")

    # Build lightweight init params (no grids/terrain_patches — workers load from file)
    worker_params = {
        'input_json_path': input_json_path,
        'grid_index_path': grid_index_path,
        'hex_size': precomputed['hex_size'],
        'boundary_xy': precomputed['boundary_xy'],
        'terrain_png_path': precomputed.get('terrain_png_path'),
        'terrain_extent': precomputed.get('terrain_extent'),
    }

    rendered = []
    with ProcessPoolExecutor(
        max_workers=max_workers,
        initializer=_worker_init,
        initargs=(worker_params,)
    ) as executor:
        futures = {executor.submit(_render_single_map, task): task for task in tasks}
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            if result:
                rendered.append(result)
            if i % 10 == 0 or i == len(tasks):
                print(f"  渲染进度: {i}/{len(tasks)} ({i*100/len(tasks):.1f}%)")

    # ── Perform copy operations for duplicate deployments ──
    if copy_ops:
        print(f"复制 {len(copy_ops)} 张重复部署地图...")
        for dest, src in copy_ops:
            shutil.copy2(src, dest)

    all_maps = sorted(
        [os.path.join(maps_dir, f"deployment_map_{i:04d}.png") for i, _ in iterations],
        key=natural_sort_key
    )
    return all_maps


def create_video_with_cv2(image_paths: List[str], output_path: str, fps: float = 10.0,
                          resize_factor: float = 1.0) -> None:
    if not image_paths:
        print("错误: 没有找到图片!")
        return

    try:
        import cv2
    except ImportError:
        print("错误: 需要安装 opencv-python (pip install opencv-python)")
        return

    print(f"使用 OpenCV 后端")

    frame = cv2.imread(image_paths[0])
    if frame is None:
        print(f"错误: 无法读取图片 {image_paths[0]}")
        return

    height, width = frame.shape[:2]
    if resize_factor != 1.0:
        width = int(width * resize_factor)
        height = int(height * resize_factor)

    print(f"图片尺寸: {width}x{height}")
    print(f"帧率: {fps} fps")

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    print(f"\n开始合成 {len(image_paths)} 张图片为视频...")
    for i, img_path in enumerate(image_paths):
        frame = cv2.imread(img_path)
        if frame is None:
            print(f"警告: 跳过无法读取的图片 {img_path}")
            continue
        if resize_factor != 1.0:
            frame = cv2.resize(frame, (width, height))
        out.write(frame)
        if (i + 1) % 10 == 0 or i + 1 == len(image_paths):
            print(f"  合成进度: {i + 1}/{len(image_paths)} ({(i + 1) * 100 / len(image_paths):.1f}%)")

    out.release()
    print(f"\n视频已保存至: {output_path}")
    print(f"   总时长: {len(image_paths) / fps:.1f} 秒")


def create_video_with_ffmpeg(image_paths: List[str], output_path: str, fps: float = 10.0) -> None:
    if not image_paths:
        print("错误: 没有找到图片!")
        return

    try:
        from PIL import Image
        with Image.open(image_paths[0]) as img:
            width, height = img.width, img.height
    except ImportError:
        print("错误: 需要安装 Pillow 来读取图片尺寸")
        return

    print(f"图片尺寸: {width}x{height}")
    print(f"帧率: {fps} fps")
    print(f"使用 ffmpeg 后端")

    temp_list = Path(output_path).parent / "image_list.txt"
    try:
        with open(temp_list, 'w', encoding='utf-8') as f:
            for img_path in image_paths:
                abs_path = os.path.abspath(img_path)
                f.write(f"file '{abs_path}'\n")
                f.write(f"duration {1.0/fps:.6f}\n")

        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-i', str(temp_list),
            '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2',
            '-fps_mode', 'cfr', '-pix_fmt', 'yuv420p', '-r', str(fps),
            output_path
        ]

        print(f"\n开始合成 {len(image_paths)} 张图片为视频...")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"ffmpeg concat 失败:\n{result.stderr}")
            first_path = Path(image_paths[0])
            pattern = str(first_path.parent / f"deployment_map_%04d.png")
            cmd2 = [
                'ffmpeg', '-y',
                '-framerate', str(fps),
                '-i', pattern,
                '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2',
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                output_path
            ]
            result2 = subprocess.run(cmd2, capture_output=True, text=True)
            if result2.returncode == 0:
                print(f"\n视频已保存至: {output_path}")
                print(f"   总时长: {len(image_paths)/fps:.1f} 秒")
                return
            else:
                print(f"第二种方法也失败:\n{result2.stderr}")
                return

        print(f"\n视频已保存至: {output_path}")
        print(f"   总时长: {len(image_paths)/fps:.1f} 秒")

    except FileNotFoundError:
        print("错误: 没有找到 ffmpeg!")
        print("请安装 ffmpeg 并添加到 PATH")
    finally:
        if temp_list.exists():
            temp_list.unlink()


def find_images(directory: str, prefix: str = "deployment_map") -> List[str]:
    """
    在目录中递归查找指定前缀的 PNG 图片，按自然顺序排序。
    兼容 run.py 的旧接口。
    """
    image_paths = []
    dir_path = Path(directory)
    if not dir_path.exists():
        return image_paths
    for root, dirs, files in os.walk(str(dir_path)):
        for f in files:
            if f.startswith(prefix) and f.endswith('.png'):
                image_paths.append(os.path.join(root, f))
    image_paths.sort(key=natural_sort_key)
    return image_paths


def create_video(image_paths: List[str], output_path: str, fps: float = 10.0,
                 resize_factor: float = 1.0, backend: str = None) -> None:
    """
    从图片列表创建视频。
    兼容 run.py 的旧接口。
    """
    if not image_paths:
        print("错误: 没有找到图片!")
        return

    backend = backend or 'cv2'

    if backend == 'cv2':
        create_video_with_cv2(image_paths, output_path, fps, resize_factor)
    elif backend == 'ffmpeg':
        create_video_with_ffmpeg(image_paths, output_path, fps)
    else:
        print(f"错误: 不支持的后端 '{backend}'，可选: cv2, ffmpeg")


def main():
    parser = argparse.ArgumentParser(
        description="从 DSSA 优化输出生成 deployment_map 图片并合成视频",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python images_to_video.py --input_dir ./figures/big1 --input_json ./inputs/base.json --output video.mp4 --fps 5
  python images_to_video.py --input_dir ./figures/big1 --input_json ./inputs/base.json --output video.mp4 --fps 10 --workers 4
"""
    )
    parser.add_argument("--input_dir", "-i", required=True, help="DSSA 优化输出目录（包含 iteration_XXXX 子目录）")
    parser.add_argument("--input_json", "-j", required=True, help="输入 JSON 文件路径（包含网格数据）")
    parser.add_argument("--output", "-o", default="output.mp4", help="输出视频文件路径")
    parser.add_argument("--fps", "-f", type=float, default=5.0, help="视频帧率 (默认: 5.0)")
    parser.add_argument("--workers", "-w", type=int, default=None, help="并发进程数 (默认: 自动检测，根据可用内存动态计算，上限 32)")
    parser.add_argument("--output_dir", "-d", default=None, help="中间图片输出目录 (默认: input_dir 同级)")
    parser.add_argument("--backend", "-b", choices=["cv2", "ffmpeg"], default="cv2",
                        help="视频编码后端 (默认: cv2)")
    parser.add_argument("--grid_dpi", type=int, default=80,
                        help="网格渲染分辨率（DPI），控制地图尺寸 (默认: 80)")
    parser.add_argument("--map_dpi", type=int, default=150,
                        help="保存图片的 DPI（也即 save_dpi） (默认: 150)")

    args = parser.parse_args()

    output_dir = args.output_dir or args.input_dir

    print("=" * 60)
    print("DSSA Deployment Map → 视频")
    print("=" * 60)
    print(f"输入目录: {args.input_dir}")
    print(f"输入 JSON: {args.input_json}")
    print(f"输出视频: {args.output}")
    print(f"帧率: {args.fps} fps")
    print(f"并发进程: {args.workers or '自动'}")
    print(f"视频后端: {args.backend}")
    print(f"grid_dpi: {args.grid_dpi}, map_dpi (save_dpi): {args.map_dpi}")
    print("=" * 60)

    try:
        image_paths = render_all_maps(
            args.input_dir, args.input_json, output_dir,
            max_workers=args.workers, fps=args.fps,
            grid_dpi=args.grid_dpi, save_dpi=args.map_dpi
        )

        if not image_paths:
            print("没有生成任何图片，退出")
            return

        print(f"\n共 {len(image_paths)} 张 deployment_map")
        create_video(image_paths, args.output, fps=args.fps, backend=args.backend)

    except Exception as e:
        print(f"\n错误: {str(e)}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
