#!/usr/bin/env python3
"""
Convert protection_pipeline input JSON (exported by image-viewer.html)
back to image-viewer.html importable JSON format.

Round-trip flow:
  image-viewer.html  --导出Pipeline JSON-->  big.json  --本脚本-->  viewer.json  --导入--> image-viewer.html

Key: original_grid_id stores drawHexGrid()'s raw (row, col) coordinates.
     We preserve them as-is so import matching by row/col works correctly.
"""
import json
import math
import sys
import os


TERRAIN_TO_COLOR = {
    "DenseGrass": {"color": "#4ade80", "colorTag": 1},
    "SparseGrass": {"color": "#ef4444", "colorTag": 2},
    "WaterHole": {"color": "#3b82f6", "colorTag": 3},
    "SaltMarsh": {"color": "#eab308", "colorTag": 4},
    "Road": {"color": "#a855f7", "colorTag": 5},
}

DEFAULT_COLOR = {"color": "#000000", "colorTag": 0}


def parse_grid_row_col(grid):
    original_id = grid.get("original_grid_id", "")
    if "_" in original_id:
        parts = original_id.split("_", 1)
        return int(parts[0]), int(parts[1])
    return grid.get("y", 0), grid.get("x", 0)


def convert_to_viewer_format(input_grids, map_config, hex_size_override=None):
    grid_map = {}
    for grid in input_grids:
        row, col = parse_grid_row_col(grid)
        grid_id = f"{row}_{col}"
        grid_map[grid_id] = {"row": row, "col": col}

    viewer_data = []
    for grid in input_grids:
        row, col = parse_grid_row_col(grid)
        grid_id = f"{row}_{col}"

        hex_size = hex_size_override if hex_size_override is not None else grid.get("hex_size", 62)

        x_dist = hex_size * math.sqrt(3)
        y_dist = hex_size * 1.5

        offset = (row % 2) * (x_dist / 2)
        center_x = col * x_dist + offset
        center_y = row * y_dist

        neighbors = []
        if row % 2 == 0:
            neighbor_offsets = [
                (-1, -1), (-1, 0),
                (0, -1), (0, 1),
                (1, -1), (1, 0)
            ]
        else:
            neighbor_offsets = [
                (-1, 0), (-1, 1),
                (0, -1), (0, 1),
                (1, 0), (1, 1)
            ]

        for dr, dc in neighbor_offsets:
            neighbor_id = f"{row + dr}_{col + dc}"
            if neighbor_id in grid_map:
                neighbors.append(neighbor_id)

        terrain_type = grid.get("terrain_type", "")
        color_info = TERRAIN_TO_COLOR.get(terrain_type, DEFAULT_COLOR)

        viewer_item = {
            "gridId": grid_id,
            "row": row,
            "col": col,
            "x": center_x,
            "y": center_y,
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
        description="Convert pipeline input JSON back to image-viewer importable JSON"
    )
    parser.add_argument("input", help="Pipeline input JSON (e.g. big.json, etosha_input.json)")
    parser.add_argument("output", help="Output JSON file for image-viewer import")
    parser.add_argument("--hex-size", type=int, default=None,
                        help="Override hex size (default: use each grid's hex_size field)")

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: Input file {args.input} not found")
        sys.exit(1)

    print(f"Reading {args.input}...")
    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    input_grids = data.get("grids", [])
    if not input_grids:
        input_grids = data.get("input_grids", [])
    print(f"Found {len(input_grids)} grids")

    map_config = data.get("map_config", {})

    print("Converting to viewer format...")
    viewer_data = convert_to_viewer_format(input_grids, map_config, args.hex_size)

    print(f"Writing {args.output}...")
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(viewer_data, f, ensure_ascii=False, indent=2)

    print(f"Done! Converted {len(viewer_data)} grids")
    print(f"  Import this file in image-viewer: click '导入JSON' button")


if __name__ == "__main__":
    main()
