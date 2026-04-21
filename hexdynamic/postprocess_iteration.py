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


def load_risk_data(output_json_path: str) -> Dict[int, Dict]:
    """Load pre-computed risk data from final output JSON."""
    risk_map = {}
    if os.path.exists(output_json_path):
        try:
            with open(output_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for g in data.get('grids', []):
                risk_map[g['grid_id']] = {
                    'risk_normalized': g.get('risk_normalized', 0.0),
                    'raw_risk': g.get('raw_risk', 0.0)
                }
        except Exception as e:
            print(f"Warning: Could not load risk data: {e}")
    return risk_map


def load_iteration_solution(solution_path: str) -> Dict[str, Any]:
    """Load a single solution JSON file."""
    with open(solution_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def convert_to_visualize_format(solution: Dict[str, Any], grid_map: Dict[int, Dict],
                            risk_map: Dict[int, Dict], filename: str) -> Dict[str, Any]:
    """Convert iteration solution to visualize_output.py format."""
    
    grids = []
    cameras = solution.get('cameras', {})
    camps = solution.get('camps', {})
    drones = solution.get('drones', {})
    rangers = solution.get('rangers', {})
    fences = solution.get('fences', {})
    fitness = solution.get('fitness', 0)
    total_pb = solution.get('total_protection_benefit', 0)
    pb_per_grid_raw = solution.get('protection_benefit_per_grid', {})
    stats = solution.get('statistics', {})
    
    pb_vals = [v for v in pb_per_grid_raw.values()]
    pb_min = 0.0  # always anchor at 0
    pb_max = max(pb_vals) if pb_vals else 1
    pb_range = pb_max - pb_min if pb_max > 0 else 1
    
    for grid_id, grid_data in sorted(grid_map.items()):
        risk_data = risk_map.get(grid_id, {})
        pb_raw = pb_per_grid_raw.get(str(grid_id), 0.0)
        pb_norm = (pb_raw - pb_min) / pb_range if pb_range > 0 else 0.0
        risk_norm = risk_data.get('risk_normalized', grid_data.get('risk_normalized', 0.0))
        
        entry = {
            'grid_id': grid_id,
            'q': grid_data.get('q', 0),
            'r': grid_data.get('r', 0),
            'x': grid_data.get('x', 0),
            'y': grid_data.get('y', 0),
            'terrain_type': grid_data.get('terrain_type', 'unknown'),
            'risk_normalized': risk_norm,
            'raw_risk': risk_data.get('raw_risk', grid_data.get('raw_risk', 0.0)),
            'protection_benefit_raw': pb_raw,
            'protection_benefit_normalized': pb_norm,
            'residual_risk_normalized': risk_norm * (1 - min(pb_raw / max(risk_norm, 0.001), 1)),
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
            'total_protection_benefit': total_pb,
            'average_protection_benefit': total_pb / len(grids) if grids else 0,
            'total_risk': sum(g.get('raw_risk', 0) for g in grids),
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


def postprocess_iteration(iteration_dir: str, input_path: str, output_dir: Optional[str] = None, 
                         final_output_path: Optional[str] = None):
    """Post-process all solution types in an iteration directory."""
    
    grid_map = load_input_grids(input_path)
    
    # Try to load risk data from final output JSON
    if final_output_path and os.path.exists(final_output_path):
        risk_map = load_risk_data(final_output_path)
    else:
        # Fallback: try to find final output in common locations
        possible_paths = [
            os.path.join(os.path.dirname(iteration_dir), 'final_output.json'),
            os.path.join(os.path.dirname(os.path.dirname(iteration_dir)), 'final_output.json'),
        ]
        risk_map = {}
        for path in possible_paths:
            if os.path.exists(path):
                risk_map = load_risk_data(path)
                if risk_map:
                    break
    
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
            output_data = convert_to_visualize_format(sol, grid_map, risk_map, f"{sol_type}_{i}")
            
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
    parser.add_argument('-f', '--final-output', help="Path to final_output.json with computed risk data")
    
    args = parser.parse_args()
    postprocess_iteration(args.iteration_dir, args.input_json, args.output, final_output_path=args.final_output)