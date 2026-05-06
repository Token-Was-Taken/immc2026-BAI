#!/usr/bin/env python3
"""
Convert big.json format to image-viewer.html compatible JSON format.
"""
import json
import math
import sys
import os


def convert_to_viewer_format(input_grids, hex_size):
    # 地形类型到颜色和colorTag的映射（与image-viewer.html保持一致）
    terrain_to_color = {
        "DenseGrass": {"color": "#4ade80", "colorTag": 1},
        "SparseGrass": {"color": "#ef4444", "colorTag": 2},
        "WaterHole": {"color": "#3b82f6", "colorTag": 3},
        "SaltMarsh": {"color": "#06b6d4", "colorTag": 7},
        "Road": {"color": "#a855f7", "colorTag": 5},
    }
    
    # 第一步：找出所有row和col的最小值，用于偏移
    min_row = float('inf')
    min_col = float('inf')
    
    for grid in input_grids:
        original_id = grid.get("original_grid_id", "")
        if "_" in original_id:
            row, col = original_id.split("_", 1)
            row = int(row)
            col = int(col)
        else:
            row = grid.get("y", 0)
            col = grid.get("x", 0)
        
        if row < min_row:
            min_row = row
        if col < min_col:
            min_col = col
    
    print(f"Offset - min_row: {min_row}, min_col: {min_col}")
    
    grid_map = {}
    viewer_data = []

    # 第二步：构建索引（使用偏移后的坐标）
    for grid in input_grids:
        original_id = grid.get("original_grid_id", "")
        if "_" in original_id:
            orig_row, orig_col = original_id.split("_", 1)
            orig_row = int(orig_row)
            orig_col = int(orig_col)
        else:
            orig_row = grid.get("y", 0)
            orig_col = grid.get("x", 0)
        
        # 应用偏移
        row = orig_row - min_row
        col = orig_col - min_col

        grid_id = f"{row}_{col}"
        grid_map[grid_id] = {
            "grid_id": grid_id,
            "row": row,
            "col": col,
            "orig_row": orig_row,
            "orig_col": orig_col
        }

    # 第三步：生成viewer格式（使用偏移后的坐标）
    for grid in input_grids:
        original_id = grid.get("original_grid_id", "")
        if "_" in original_id:
            orig_row, orig_col = original_id.split("_", 1)
            orig_row = int(orig_row)
            orig_col = int(orig_col)
        else:
            orig_row = grid.get("y", 0)
            orig_col = grid.get("x", 0)
        
        # 应用偏移
        row = orig_row - min_row
        col = orig_col - min_col

        grid_id = f"{row}_{col}"

        # Calculate center coordinates (matches image-viewer.html's logic
        x_dist = hex_size * math.sqrt(3)
        y_dist = hex_size * 1.5

        offset = (row % 2) * (x_dist / 2)
        center_x = col * x_dist + offset
        center_y = row * y_dist

        # Find neighbors
        neighbors = []
        neighbor_offsets = []
        if row % 2 == 0:
            # Even row
            neighbor_offsets = [
                (-1, -1), (-1, 0),
                (0, -1), (0, 1),
                (1, -1), (1, 0)
            ]
        else:
            # Odd row
            neighbor_offsets = [
                (-1, 0), (-1, 1),
                (0, -1), (0, 1),
                (1, 0), (1, 1)
            ]

        for dr, dc in neighbor_offsets:
            neighbor_row = row + dr
            neighbor_col = col + dc
            neighbor_id = f"{neighbor_row}_{neighbor_col}"
            if neighbor_id in grid_map:
                neighbors.append(neighbor_id)

        # 根据地形类型获取颜色
        terrain_type = grid.get("terrain_type", "")
        color_info = terrain_to_color.get(terrain_type, {"color": "#000000", "colorTag": 0})

        viewer_item = {
            "gridId": grid_id,
            "row": row,
            "col": col,
            "x": 10000 - center_x,
            "y": 4663 + center_y,
            "centerXNatural": center_x,
            "centerYNatural": center_y,
            "hexSizeNatural": hex_size,
            "neighbors": neighbors,
            "color": color_info["color"],
            "colorTag": color_info["colorTag"]
        }
        viewer_data.append(viewer_item)

    return viewer_data


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Convert big.json to image-viewer format"
    )
    parser.add_argument(
        "input",
        help="Input big.json file"
    )
    parser.add_argument(
        "output",
        help="Output JSON file for image-viewer"
    )
    parser.add_argument(
        "--hex-size",
        type=int,
        default=62,
        help="Hex size (default: 62)"
    )

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: Input file {args.input} not found")
        sys.exit(1)

    print(f"Reading {args.input}...")
    with open(args.input, "r", encoding="utf-8") as f:
        big_data = json.load(f)

    input_grids = big_data.get("grids", [])
    if not input_grids:
        input_grids = big_data.get("input_grids", [])
    print(f"Found {len(input_grids)} grids")

    print("Converting to viewer format...")
    viewer_data = convert_to_viewer_format(input_grids, args.hex_size)

    print(f"Writing {args.output}...")
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(viewer_data, f, ensure_ascii=False, indent=2)

    print(f"Done! Converted {len(viewer_data)} grids")


if __name__ == "__main__":
    main()
