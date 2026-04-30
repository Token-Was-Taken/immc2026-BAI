
# 直接测试这个新添加的函数
import sys
import os
sys.path.insert(0, r'd:\code\immc2026-BAI\hexdynamic')

from visualize_output import (
    load_data, plot_species_deployment_comparison
)

os.chdir(r'd:\code\immc2026-BAI\hexdynamic')

print("Loading data...")
out, out_map, species_map, hex_size, boundary_xy = load_data(
    'test_fence_fixed.json', 'base1.json'
)

print("Plotting species_deployment_comparison...")
try:
    os.makedirs('test_output', exist_ok=True)
    plot_species_deployment_comparison(
        out, species_map, hex_size, boundary_xy,
        'test_output/species_deployment_comparison.png'
    )
    print("\n✓ Success!")
    print("  Check: test_output/species_deployment_comparison.png")
    
except Exception as e:
    print(f"\n✗ Error: {type(e).__name__}: {e}")
    import traceback
    print(traceback.format_exc())

