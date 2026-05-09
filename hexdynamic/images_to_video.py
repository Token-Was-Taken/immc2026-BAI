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
    best_json_path, output_png_path, iteration, precomputed_data = args

    try:
        import gc
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        matplotlib.rcParams["figure.max_open_warning"] = 0

        with open(best_json_path, 'r', encoding='utf-8') as f:
            best_data = json.load(f)

        from visualize_output import (
            make_figure, setup_map_ax, draw_hex, draw_boundary,
            draw_deployed_fence_edges, _draw_resources, _edge_grid_ids
        )

        grids = precomputed_data['grids']
        hex_size = precomputed_data['hex_size']
        boundary_xy = precomputed_data['boundary_xy']
        terrain_patches = precomputed_data['terrain_patches']

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

        fig, ax_map, _, ax_leg = make_figure(has_colorbar=False)

        for (cx, cy, fc) in terrain_patches:
            draw_hex(ax_map, cx, cy, hex_size * 0.97,
                    facecolor=fc, alpha=0.45)

        edge_ids = _edge_grid_ids(plot_grids, boundary_xy)

        _draw_resources(ax_map, plot_grids, output_base, hex_size, edge_ids)
        draw_deployed_fence_edges(ax_map, plot_grids, output_base, hex_size)
        setup_map_ax(ax_map, plot_grids, hex_size)
        draw_boundary(ax_map, plot_grids, boundary_xy, hex_size)

        ax_map.set_title(f"Iteration {iteration:04d}", fontsize=13, fontweight='bold', pad=8)

        _draw_legend(ax_leg)

        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)
        fig.savefig(output_png_path, dpi=72, bbox_inches="tight")

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
                    max_workers: int = None, fps: float = 5.0) -> List[str]:
    grid_data = load_grid_data(input_json_path)
    precomputed = precompute_terrain(grid_data)

    iterations = find_iteration_dirs(input_dir)
    if not iterations:
        print(f"错误: 在 {input_dir} 中没有找到包含 best.json 的 iteration_XXXX 目录!")
        return []

    print(f"找到 {len(iterations)} 个迭代目录")
    print(f"预计算地形底图: {len(precomputed['terrain_patches'])} 个网格")

    maps_dir = os.path.join(output_dir, "deployment_maps")
    os.makedirs(maps_dir, exist_ok=True)

    tasks = []
    for iter_num, iter_dir in iterations:
        best_json_path = os.path.join(iter_dir, "best.json")
        output_png_path = os.path.join(maps_dir, f"deployment_map_{iter_num:04d}.png")
        if os.path.exists(output_png_path):
            continue
        tasks.append((best_json_path, output_png_path, iter_num, precomputed))

    if not tasks:
        print("所有 deployment_map 已存在，跳过渲染")
        return sorted(
            [os.path.join(maps_dir, f"deployment_map_{i:04d}.png") for i, _ in iterations],
            key=natural_sort_key
        )

    print(f"需要渲染 {len(tasks)} 张 deployment_map（跳过 {len(iterations) - len(tasks)} 张已存在的）")

    if max_workers is None:
        max_workers = min(os.cpu_count() or 4, 8)

    print(f"使用 {max_workers} 个进程并发生成...")

    rendered = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_render_single_map, task): task for task in tasks}
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            if result:
                rendered.append(result)
            if i % 10 == 0 or i == len(tasks):
                print(f"  渲染进度: {i}/{len(tasks)} ({i*100/len(tasks):.1f}%)")

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
    parser.add_argument("--workers", "-w", type=int, default=None, help="并发进程数 (默认: CPU 核心数, 最大 8)")
    parser.add_argument("--output_dir", "-d", default=None, help="中间图片输出目录 (默认: input_dir 同级)")
    parser.add_argument("--backend", "-b", choices=["cv2", "ffmpeg"], default="cv2",
                        help="视频编码后端 (默认: cv2)")

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
    print("=" * 60)

    try:
        image_paths = render_all_maps(
            args.input_dir, args.input_json, output_dir,
            max_workers=args.workers, fps=args.fps
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
