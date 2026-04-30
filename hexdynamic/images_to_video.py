#!/usr/bin/env python3
"""
将指定目录中指定前缀的图片生成视频

支持两种后端:
1. Pillow + ffmpeg (推荐，更通用)
2. OpenCV (需要安装 opencv-python)

用法:
    python images_to_video.py --input_dir ./figures/4 --prefix "deployment_map" --output video.mp4 --fps 5
"""

import argparse
import os
import re
import subprocess
import sys
from typing import List, Tuple
from pathlib import Path

# 尝试导入 PIL/Pillow
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# 尝试导入 OpenCV
try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


def natural_sort_key(path: str) -> List:
    """
    自然排序键函数，提取文件名中的数字
    这样 iteration_0000.png 排在 iteration_0001.png 前面
    """
    path_str = str(path)
    parts = re.split(r'(\d+)', path_str)
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def find_images(input_dir: str, prefix: str, extensions: Tuple[str, ...] = ('.png', '.jpg', '.jpeg')) -> List[str]:
    """
    在指定目录中查找符合指定前缀的图片文件
    """
    input_path = Path(input_dir)
    if not input_path.exists():
        raise ValueError(f"目录不存在: {input_dir}")

    images = []
    
    # 支持两种模式:
    # 1. 直接在 input_dir 目录中查找
    for ext in extensions:
        for file in input_path.glob(f"{prefix}*{ext}"):
            images.append(str(file))
    
    # 2. 如果没有找到，在子目录中查找（如 iteration_0000/deployment_map.png）
    if not images:
        for subdir in sorted(input_path.iterdir()):
            if subdir.is_dir():
                for ext in extensions:
                    for file in subdir.glob(f"{prefix}*{ext}"):
                        images.append(str(file))
    
    # 自然排序
    images.sort(key=natural_sort_key)
    return images


def get_image_info(image_path: str) -> Tuple[int, int]:
    """获取图片的宽和高"""
    if HAS_PIL:
        with Image.open(image_path) as img:
            return img.width, img.height
    elif HAS_CV2:
        img = cv2.imread(image_path)
        return img.shape[1], img.shape[0]
    else:
        raise RuntimeError("需要安装 Pillow 或 OpenCV")


def create_video_with_ffmpeg(image_paths: List[str], output_path: str, fps: float = 10.0, 
                             resize_factor: float = 1.0) -> None:
    """
    使用 ffmpeg 从图片列表创建视频
    """
    if not image_paths:
        print("错误: 没有找到图片!")
        return

    # 获取第一张图片的尺寸
    width, height = get_image_info(image_paths[0])
    
    if resize_factor != 1.0:
        width = int(width * resize_factor)
        height = int(height * resize_factor)
    
    print(f"图片尺寸: {width}x{height}")
    print(f"帧率: {fps} fps")
    print(f"使用 ffmpeg 后端")
    
    # 创建临时文本文件，列出所有图片
    temp_list = Path(output_path).parent / "image_list.txt"
    try:
        with open(temp_list, 'w', encoding='utf-8') as f:
            for img_path in image_paths:
                f.write(f"file '{img_path}'\n")
                f.write(f"duration {1.0/fps:.6f}\n")
        
        # 构建 ffmpeg 命令
        cmd = [
            'ffmpeg',
            '-y',  # 覆盖输出文件
            '-f', 'concat',
            '-safe', '0',
            '-i', str(temp_list),
            '-vsync', 'vfr',
            '-pix_fmt', 'yuv420p',
            '-r', str(fps)
        ]
        
        if resize_factor != 1.0:
            cmd.extend(['-vf', f'scale={width}:{height}'])
        
        cmd.append(output_path)
        
        print(f"\n开始处理 {len(image_paths)} 张图片...")
        
        # 运行 ffmpeg
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"ffmpeg 错误:\n{result.stderr}")
            print(f"\n尝试仅使用 ffmpeg 的简单模式...")
            
            # 尝试更简单的方法
            # 假设文件名有顺序，使用通配符模式
            first_path = Path(image_paths[0])
            pattern = str(first_path.parent / f"%*.png")
            
            cmd2 = [
                'ffmpeg',
                '-y',
                '-framerate', str(fps),
                '-i', pattern,
                '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p',
                output_path
            ]
            
            if resize_factor != 1.0:
                cmd2.insert(-1, '-vf')
                cmd2.insert(-1, f'scale={width}:{height}')
            
            result2 = subprocess.run(cmd2, capture_output=True, text=True)
            if result2.returncode == 0:
                print("\n✅ 视频已保存至:", output_path)
                print(f"   总时长: {len(image_paths)/fps:.1f} 秒")
                return
            else:
                print(f"第二种方法也失败:\n{result2.stderr}")
                return
        
        print("\n✅ 视频已保存至:", output_path)
        print(f"   总时长: {len(image_paths)/fps:.1f} 秒")
        
    except FileNotFoundError:
        print("错误: 没有找到 ffmpeg!")
        print("请安装 ffmpeg:")
        print("  - Windows: 下载 https://ffmpeg.org/download.html 并添加到 PATH")
        print("  - macOS: brew install ffmpeg")
        print("  - Linux: sudo apt install ffmpeg")
        
    finally:
        if temp_list.exists():
            temp_list.unlink()


def create_video_with_cv2(image_paths: List[str], output_path: str, fps: float = 10.0, 
                         resize_factor: float = 1.0) -> None:
    """
    使用 OpenCV 从图片列表创建视频
    """
    if not image_paths:
        print("错误: 没有找到图片!")
        return

    # 读取第一张图片获取尺寸
    first_img = cv2.imread(image_paths[0])
    if first_img is None:
        print(f"错误: 无法读取图片: {image_paths[0]}")
        return

    height, width = first_img.shape[:2]
    
    if resize_factor != 1.0:
        width = int(width * resize_factor)
        height = int(height * resize_factor)
    
    print(f"图片尺寸: {width}x{height}")
    print(f"帧率: {fps} fps")
    print(f"使用 OpenCV 后端")

    # 创建视频写入器
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    print(f"\n开始处理 {len(image_paths)} 张图片...")
    
    for i, img_path in enumerate(image_paths, 1):
        img = cv2.imread(img_path)
        if img is None:
            print(f"警告: 无法读取图片 {img_path}，跳过")
            continue
        
        if resize_factor != 1.0:
            img = cv2.resize(img, (width, height))
        
        out.write(img)
        
        if i % 10 == 0 or i == len(image_paths):
            print(f"  已处理: {i}/{len(image_paths)} ({i*100/len(image_paths):.1f}%)")
    
    out.release()
    print(f"\n✅ 视频已保存至: {output_path}")
    print(f"   总时长: {len(image_paths)/fps:.1f} 秒")


def create_video(image_paths: List[str], output_path: str, fps: float = 10.0, 
                 resize_factor: float = 1.0, backend: str = None) -> None:
    """
    从图片列表创建视频，自动选择可用的后端
    """
    if backend == 'cv2' and HAS_CV2:
        create_video_with_cv2(image_paths, output_path, fps, resize_factor)
    elif backend == 'ffmpeg' or HAS_PIL:
        create_video_with_ffmpeg(image_paths, output_path, fps, resize_factor)
    elif HAS_CV2:
        create_video_with_cv2(image_paths, output_path, fps, resize_factor)
    else:
        print("错误: 没有可用的后端!")
        print("请安装以下之一:")
        print("  - ffmpeg (推荐)")
        print("  - Pillow (pip install pillow)")
        print("  - opencv-python (pip install opencv-python)")


def main():
    parser = argparse.ArgumentParser(
        description="将指定目录中指定前缀的图片生成视频",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基础用法 - 在 figurs/4 目录下找 deployment_map 开头的图片生成 video.mp4
  python images_to_video.py --input_dir ./figures/4 --prefix deployment_map --output video.mp4
  
  # 指定帧率
  python images_to_video.py --input_dir ./figures/4 --prefix deployment_map --output video.mp4 --fps 5
  
  # 调整图片大小
  python images_to_video.py --input_dir ./figures/4 --prefix deployment_map --output video.mp4 --resize 0.5
  
  # 指定扩展
  python images_to_video.py --input_dir ./figures/4 --prefix deployment_map --output video.mp4 --extensions .jpg .png
  
  # 无确认模式 (适合脚本调用)
  python images_to_video.py --input_dir ./figures/4 --prefix deployment_map --output video.mp4 --no_confirm
  
  # 指定后端
  python images_to_video.py --input_dir ./figures/4 --prefix deployment_map --output video.mp4 --backend ffmpeg
"""
    )
    
    parser.add_argument(
        "--input_dir", "-i",
        required=True,
        help="图片所在目录"
    )
    parser.add_argument(
        "--prefix", "-p",
        required=True,
        help="图片文件名前缀"
    )
    parser.add_argument(
        "--output", "-o",
        default="output.mp4",
        help="输出视频文件路径"
    )
    parser.add_argument(
        "--fps", "-f",
        type=float,
        default=10.0,
        help="视频帧率 (默认: 10.0)"
    )
    parser.add_argument(
        "--resize", "-r",
        type=float,
        default=1.0,
        help="图片缩放因子 (默认: 1.0 = 不缩放)"
    )
    parser.add_argument(
        "--extensions", "-e",
        nargs="+",
        default=[".png", ".jpg", ".jpeg"],
        help="图片文件扩展名 (默认: .png, .jpg, .jpeg)"
    )
    parser.add_argument(
        "--no_confirm", "-y",
        action="store_true",
        help="跳过确认提示 (适合脚本调用)"
    )
    parser.add_argument(
        "--backend", "-b",
        choices=["ffmpeg", "cv2"],
        help="指定使用的后端 (默认: 自动选择)"
    )
    
    args = parser.parse_args()
    
    print("="*60)
    print("图片转视频")
    print("="*60)
    print(f"输入目录: {args.input_dir}")
    print(f"文件名前缀: {args.prefix}")
    print(f"输出视频: {args.output}")
    print(f"帧率: {args.fps} fps")
    print(f"缩放因子: {args.resize}")
    if args.backend:
        print(f"指定后端: {args.backend}")
    print("="*60)
    
    try:
        image_paths = find_images(args.input_dir, args.prefix, tuple(args.extensions))
        
        if not image_paths:
            print(f"\n错误: 在目录 {args.input_dir} 中没有找到前缀为 '{args.prefix}' 的图片!")
            return
        
        print(f"\n找到 {len(image_paths)} 张图片:")
        print(f"  第一张: {Path(image_paths[0]).name}")
        print(f"  最后一张: {Path(image_paths[-1]).name}")
        
        if not args.no_confirm:
            confirm = input("\n是否继续创建视频? (y/n): ").strip().lower()
            if confirm != 'y':
                print("操作已取消")
                return
        
        create_video(image_paths, args.output, args.fps, args.resize, args.backend)
        
    except Exception as e:
        print(f"\n错误: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
