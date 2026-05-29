"""
convert_best.py — 将 DSSA 迭代输出的 best.json 转换为 evaluate_solution.py 可接受的格式

用法:
    python convert_best.py input.json best.json output.json
    python convert_best.py input.json figures/big/2/iteration_0000/best.json converted.json
"""

import argparse
import json
import sys


def convert_best_to_eval_format(input_path: str, best_path: str, output_path: str):
    with open(best_path, 'r', encoding='utf-8') as f:
        best = json.load(f)

    with open(input_path, 'r', encoding='utf-8') as f:
        inp = json.load(f)

    cameras = {int(k): v for k, v in best.get('cameras', {}).items()}
    camps = {int(k): v for k, v in best.get('camps', {}).items()}
    drones = {int(k): v for k, v in best.get('drones', {}).items()}
    rangers = {int(k): v for k, v in best.get('rangers', {}).items()}
    fences_raw = best.get('fences', {})

    fences = {}
    for k, v in fences_raw.items():
        parts = k.split('-')
        if len(parts) == 2:
            fences[(int(parts[0]), int(parts[1]))] = v

    output_grids = []
    for grid in inp.get('grids', []):
        gid = grid['grid_id']
        entry = {
            'grid_id': gid,
            'q': grid.get('q', 0),
            'r': grid.get('r', 0),
            'x': grid.get('x', 0),
            'y': grid.get('y', 0),
            'terrain_type': grid.get('terrain_type', 'SparseGrass'),
            'deployment': {
                'patrol_rangers': rangers.get(gid, 0),
                'camp': camps.get(gid, 0),
                'drone': drones.get(gid, 0),
                'camera': cameras.get(gid, 0)
            }
        }

        grid_fences = [(gid, d) for (g, d) in fences.keys() if g == gid]
        if grid_fences:
            entry['fences'] = {
                'fence_count': len(grid_fences),
                'boundary_edge_list': [d for _, d in grid_fences]
            }

        output_grids.append(entry)

    output = {
        'summary': best.get('statistics', {}),
        'grids': output_grids
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Converted: {best_path} -> {output_path}")
    print(f"  Grids: {len(output_grids)}")
    print(f"  Cameras: {sum(cameras.values())}, Drones: {sum(drones.values())}, "
          f"Camps: {sum(camps.values())}, Rangers: {sum(rangers.values())}, "
          f"Fences: {sum(fences.values())}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert DSSA best.json to evaluate_solution.py format"
    )
    parser.add_argument("input", help="Input JSON (problem definition)")
    parser.add_argument("best", help="DSSA best.json to convert")
    parser.add_argument("output", help="Output JSON path")
    args = parser.parse_args()

    convert_best_to_eval_format(args.input, args.best, args.output)


if __name__ == '__main__':
    main()
