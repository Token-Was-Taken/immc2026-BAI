"""
Post-process iteration results to format compatible with visualize_output.py.

Usage:
    python postprocess_iteration.py <iteration_dir> <input_json> [-o output_json]
    python postprocess_iteration.py ./output_iterations/iteration_0005 input.json -o visualization/iter005.json
"""

import argparse
import json
import os
from typing import Dict, List, Any, Optional


def load_input_grids(input_path: str) -> Dict[int, Dict]:
    """Load grid information from input JSON."""
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    grid_map = {}
    for g in data.get('grids', []):
        grid_map[g['grid_id']] = g
    return grid_map


def load_iteration_solution(solution_path: str) -> Dict[str, Any]:
    """Load a single solution JSON file."""
    with open(solution_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def convert_to_visualize_format(solution: Dict[str, Any], grid_map: Dict[int, Dict],
                            filename: str) -> Dict[str, Any]:
    """Convert iteration solution to visualize_output.py format."""
    
    grids = []
    cameras = solution.get('cameras', {})
    camps = solution.get('camps', {})
    drones = solution.get('drones', {})
    rangers = solution.get('rangers', {})
    fences = solution.get('fences', {})
    fitness = solution.get('fitness', 0)
    stats = solution.get('statistics', {})
    
    for grid_id, grid_data in sorted(grid_map.items()):
        entry = {
            'grid_id': grid_id,
            'q': grid_data.get('q', 0),
            'r': grid_data.get('r', 0),
            'x': grid_data.get('x', 0),
            'y': grid_data.get('y', 0),
            'terrain_type': grid_data.get('terrain_type', 'unknown'),
            'risk_normalized': grid_data.get('risk_normalized', 0.0),
            'raw_risk': grid_data.get('raw_risk', 0.0),
            'protection_benefit_raw': 0.0,
            'protection_benefit_normalized': 0.0,
            'residual_risk_normalized': grid_data.get('risk_normalized', 0.0),
            'deployment': {
                'patrol_rangers': rangers.get(str(grid_id), 0),
                'camp': camps.get(str(grid_id), 0),
                'drone': drones.get(str(grid_id), 0),
                'camera': cameras.get(str(grid_id), 0)
            }
        }
        if 'hex_size' in grid_data:
            entry['hex_size'] = grid_data['hex_size']
        grids.append(entry)
    
    fence_edges = []
    for fence_key, value in fences.items():
        if value > 0:
            parts = fence_key.split('-')
            if len(parts) == 2:
                fence_edges.append({
                    'grid_id_1': int(parts[0]),
                    'grid_id_2': int(parts[1])
                })
    
    return {
        'summary': {
            'total_grids': len(grids),
            'best_fitness': fitness,
            'total_protection_benefit': fitness,
            'average_protection_benefit': fitness / len(grids) if grids else 0,
            'total_risk': 0,
            'resources_deployed': {
                'total_cameras': stats.get('total_cameras', 0),
                'total_drones': stats.get('total_drones', 0),
                'total_camps': stats.get('total_camps', 0),
                'total_rangers': stats.get('total_rangers', 0),
                'fence_segments': len(fence_edges)
            }
        },
        'grids': grids,
        'fence_edges': fence_edges
    }


def postprocess_iteration(iteration_dir: str, input_path: str, output_dir: Optional[str] = None):
    """Post-process all solution types in an iteration directory."""
    
    grid_map = load_input_grids(input_path)
    
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    
    solution_types = ['producers', 'followers', 'scouts']
    
    for sol_type in solution_types:
        solution_path = os.path.join(iteration_dir, f'{sol_type}.json')
        if not os.path.exists(solution_path):
            print(f"Warning: {solution_path} not found, skipping")
            continue
        
        print(f"Processing {sol_type}...")
        solutions = load_iteration_solution(solution_path)
        
        if not isinstance(solutions, list):
            solutions = [solutions]
        
        type_output_dir = output_dir if output_dir else iteration_dir
        
        for i, sol in enumerate(solutions):
            output_data = convert_to_visualize_format(sol, grid_map, f"{sol_type}_{i}")
            
            if len(solutions) > 1:
                out_path = os.path.join(type_output_dir, f'{sol_type}_{i:03d}.json')
            else:
                out_path = os.path.join(type_output_dir, f'{sol_type}.json')
            
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            
            print(f"  Saved: {out_path}")
    
    print("Done!")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Post-process iteration results for visualize_output.py"
    )
    parser.add_argument('iteration_dir', help="Iteration directory (e.g., output/iteration_0005)")
    parser.add_argument('input_json', help="Input JSON with grid information")
    parser.add_argument('-o', '--output', help="Output directory (default: same as iteration_dir)")
    
    args = parser.parse_args()
    postprocess_iteration(args.iteration_dir, args.input_json, args.output)