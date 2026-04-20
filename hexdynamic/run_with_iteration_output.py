"""
Wrapper script to run DSSA optimization with iteration output and visualization.

Usage:
    python run_with_iteration_output.py input.json [-o output_dir] [--iterations N] [--vectorized] [--visualize]

Example:
    python run_with_iteration_output.py input.json -o results/ --iterations 50 --visualize
    python run_with_iteration_output.py input.json -o results/ --vectorized --visualize
"""

import argparse
import os
import sys
import json
import shutil
import tempfile

from protection_pipeline import run_pipeline
from postprocess_iteration import postprocess_iteration


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run DSSA optimization with iteration output and visualization"
    )
    parser.add_argument('input_json', help="Input JSON file")
    parser.add_argument('-o', '--output', default='./output_results', help="Output directory")
    parser.add_argument('--iterations', type=int, default=50, help="Number of DSSA iterations")
    parser.add_argument('--vectorized', action='store_true', help="Use vectorized coverage model (recommended for grid count > 1000)")
    parser.add_argument('--visualize', action='store_true', help="Generate visualizations")
    parser.add_argument('--best-only', action='store_true', help="Only visualize best solution")
    return parser.parse_args()


def prepare_input_with_config(input_path: str, cli_iterations: int = None, cli_output_dir: str = '', 
                               cli_vectorized: bool = False) -> tuple:
    """Create a modified input JSON with the desired DSSA config.
    
    Priority: command-line args > input.json > defaults
    Returns: (temp_file_path, vectorized_from_config)
    """
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Load DSSA config from input.json (or use defaults)
    dssa_config = data.get('dssa_config', {})
    
    # Determine final values: CLI > input.json > defaults
    final_iterations = cli_iterations if cli_iterations is not None else dssa_config.get('max_iterations', 50)
    final_output_dir = cli_output_dir if cli_output_dir else dssa_config.get('output_dir', '')
    config_vectorized = dssa_config.get('vectorized', False)
    
    # Merge back with CLI override
    dssa_config['max_iterations'] = final_iterations
    if final_output_dir:
        dssa_config['output_dir'] = final_output_dir
    if cli_vectorized:
        dssa_config['vectorized'] = True
    
    data['dssa_config'] = dssa_config
    
    temp_path = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
    json.dump(data, temp_path, indent=2)
    temp_path.close()
    
    return temp_path.name, config_vectorized


def _generate_iteration_visualizations(iter_viz_dir: str, input_path: str, iter_name: str, output_dir: str):
    """Generate visualizations for all JSON files in an iteration directory."""
    try:
        from visualize_output import main as visualize_main
        import matplotlib
        matplotlib.use('Agg')
        
        json_files = [f for f in os.listdir(iter_viz_dir) if f.endswith('.json')]
        
        for json_file in json_files:
            json_path = os.path.join(iter_viz_dir, json_file)
            out_subdir = os.path.join(output_dir, 'figures', iter_name)
            os.makedirs(out_subdir, exist_ok=True)
            
            base_name = json_file.replace('.json', '')
            out_dir = os.path.join(out_subdir, base_name)
            
            try:
                sys.argv = ['visualize_output.py', json_path, '--input', input_path, '--out_dir', out_dir]
                visualize_main()
            except Exception as e:
                print(f"    Warning: Failed to visualize {json_file}: {e}")
        
        print(f"  Generated visualizations for {len(json_files)} solutions in {iter_name}")
    except Exception as e:
        print(f"  Warning: Failed to generate visualizations: {e}")


def main():
    args = parse_args()
    print(f"Input: {args.input_json}")
    print(f"Output dir: {args.output}")
    
    input_path = os.path.abspath(args.input_json)
    output_dir = os.path.abspath(args.output)
    
    # CLI iterations=None means "use from input.json", which prepare_input_with_config handles
    cli_iterations = args.iterations if args.iterations != 50 else None
    
    # Only set iteration output dir if visualize is requested  
    iteration_output_dir = os.path.abspath(os.path.join(output_dir, 'iterations')) if args.visualize else ''
    
    os.makedirs(output_dir, exist_ok=True)
    
    print("=" * 60)
    print("Step 1: Running DSSA Optimization")
    print("=" * 60)
    
    modified_input, use_vectorized = prepare_input_with_config(
        input_path, 
        cli_iterations=cli_iterations,
        cli_output_dir=iteration_output_dir,
        cli_vectorized=args.vectorized
    )
    
    # CLI --vectorized has higher priority than input.json, otherwise use the value from config
    final_vectorized = args.vectorized if args.vectorized else use_vectorized
    
    try:
        run_pipeline(
            input_path=modified_input,
            output_path=os.path.join(output_dir, 'final_output.json'),
            vectorized=final_vectorized
        )
    finally:
        os.unlink(modified_input)
    
    print("\n" + "=" * 60)
    print("Step 2: Post-processing Iteration Results")
    print("=" * 60)
    
    viz_base_dir = os.path.join(output_dir, 'visualization')
    os.makedirs(viz_base_dir, exist_ok=True)
    
    if os.path.exists(iteration_output_dir):
        iteration_dirs = sorted([
            d for d in os.listdir(iteration_output_dir)
            if os.path.isdir(os.path.join(iteration_output_dir, d))
        ])
        
        print(f"Found {len(iteration_dirs)} iteration directories")
        
        for iter_dir in iteration_dirs:
            iter_full_path = os.path.join(iteration_output_dir, iter_dir)
            iter_viz_dir = os.path.join(viz_base_dir, iter_dir)
            
            print(f"Post-processing {iter_dir}...")
            try:
                postprocess_iteration(iter_full_path, input_path, iter_viz_dir)
                
                if args.visualize:
                    print(f"  Generating visualizations for {iter_dir}...")
                    _generate_iteration_visualizations(iter_viz_dir, input_path, iter_dir, output_dir)
            except Exception as e:
                print(f"  Warning: Failed to post-process {iter_dir}: {e}")
    else:
        print("Warning: No iteration output directory found")
    
    print("\n" + "=" * 60)
    print("Step 3: Generating Visualizations")
    print("=" * 60)
    
    final_output = os.path.join(output_dir, 'final_output.json')
    
    if args.visualize and os.path.exists(final_output):
        try:
            from visualize_output import main as visualize_main
            import matplotlib
            matplotlib.use('Agg')
            
            sys.argv = ['visualize_output.py', final_output, '--input', input_path, '--out_dir', os.path.join(output_dir, 'figures')]
            visualize_main()
            print(f"Visualizations saved to {os.path.join(output_dir, 'figures')}")
        except Exception as e:
            print(f"Warning: Failed to generate visualizations: {e}")
    
    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)
    print(f"Results saved to: {output_dir}")
    print(f"  - Final output: {os.path.join(output_dir, 'final_output.json')}")
    if args.visualize:
        print(f"  - Iteration visualizations: {os.path.join(output_dir, 'visualization')}")
        print(f"  - Final visualization: {os.path.join(output_dir, 'figures')}")


if __name__ == '__main__':
    main()