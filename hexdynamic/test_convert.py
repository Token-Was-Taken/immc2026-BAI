#!/usr/bin/env python3
import json
import sys
import os
import math

# Import the conversion script
sys.path.insert(0, os.path.dirname(__file__))
from convert_bigjson_to_viewer import convert_to_viewer_format

input_path = r"c:\immc2026-BAI\immc2026-BAI\hexdynamic\inputs\big.json"
output_path = r"c:\immc2026-BAI\immc2026-BAI\marker\big-viewer.json"
hex_size = 20  # Use the same hex_size as in big.json

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
