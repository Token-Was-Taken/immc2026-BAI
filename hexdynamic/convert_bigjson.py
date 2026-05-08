#!/usr/bin/env python3
"""
Convert big.json format to image-viewer.html compatible JSON format.
"""
import json
import math
import os


def convert_to_viewer_format(input_grids, hex_size):
    grid_map = {}
    viewer_data = []

    # First pass: build index
    for grid in input_grids:
        original_id = grid.get("original_grid_id", "")
        if "_" in original_id:
            row, col = original_id.split("_", 1)
            row = int(row)
            col = int(col)
        else:
            row = grid.get("y", 0)
            col = grid.get("x", 0)

        grid_id = f"{row}_{col}"
        grid_map[grid_id] = {
            "grid_id": grid_id,
            "row": row,
            "col": col
        }

    # Second pass: generate viewer format
    for grid in input_grids:
        original_id = grid.get("original_grid_id", "")
        if "_" in original_id:
            row, col = original_id.split("_", 1)
            row = int(row)
            col = int(col)
        else:
            row = grid.get("y", 0)
            col = grid.get("x", 0)

        grid_id = f"{row}_{col}"

        # Calculate center coordinates using the same method as grid-coordinates.json
        x_dist = hex_size * math.sqrt(3)
        y_dist = hex_size * 1.5

        offset = (row % 2) * (x_dist / 2)
        center_x = col * x_dist + offset
        center_y = row * y_dist

        # Find neighbors - use even-row offset coordinate system
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

        viewer_item = {
            "gridId": grid_id,
            "row": row,
            "col": col,
            "x": 10000 - center_x,  # Mirror to match viewer's coordinate system
            "y": 4663 + center_y,
            "centerXNatural": center_x,
            "centerYNatural": center_y,
            "hexSizeNatural": hex_size,
            "neighbors": neighbors,
            "color": "#000000",
            "colorTag": 0
        }
        viewer_data.append(viewer_item)

    return viewer_data


def main():
    input_path = r"c:\immc2026-BAI\immc2026-BAI\hexdynamic\inputs\big.json"
    output_path = r"c:\immc2026-BAI\immc2026-BAI\marker\big-viewer.json"
    hex_size = 62

    if not os.path.exists(input_path):
        print(f"Error: Input file {input_path} not found")
        return

    print(f"Reading {input_path}...")
    with open(input_path, "r", encoding="utf-8") as f:
        big_data = json.load(f)

    input_grids = big_data.get("grids", [])
    if not input_grids:
        input_grids = big_data.get("input_grids", [])
    print(f"Found {len(input_grids)} grids")

    print("Converting to viewer format...")
    viewer_data = convert_to_viewer_format(input_grids, hex_size)

    print(f"Writing {output_path}...")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(viewer_data, f, ensure_ascii=False, indent=2)

    print(f"Done! Converted {len(viewer_data)} grids")


if __name__ == "__main__":
    main()
