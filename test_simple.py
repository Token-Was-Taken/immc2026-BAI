
#! /usr/bin/env python3
import os
import sys

# 设置环境变量来禁用分页
os.environ['GIT_PAGER'] = ''
os.environ['PAGER'] = ''
os.environ['LESS'] = '-F -X -R'

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'hexdynamic'))

os.chdir(os.path.join(os.path.dirname(__file__), 'hexdynamic'))

from visualize_output import (
    load_data, plot_species_deployment_comparison
)

print("=== Loading data ===")
out, out_map, species_map, hex_size, boundary_xy = load_data(
    'test_fence_fixed.json', 'base1.json'
)

print("=== Plotting ===")

try:
    os.makedirs('test_output', exist_ok=True)
    
    # 先测试一下 load_data 和其他函数是否正常
    print("  - Number of grids:", len(out['grids']))
    print("  - Hex size:", hex_size)
    
    # 直接调用我们的函数
    plot_species_deployment_comparison(
        out, species_map, hex_size, boundary_xy,
        'test_output/species_deployment_comparison.png'
    )
    
    print("\n=== Success ===")
    print("  ✅ File created: test_output/species_deployment_comparison.png")
    
    # 验证文件是否存在
    if os.path.exists('test_output/species_deployment_comparison.png'):
        file_size = os.path.getsize('test_output/species_deployment_comparison.png')
        print(f"  ℹ️  File size: {file_size} bytes")
    else:
        print("  ❌ File NOT found!")
        
except Exception as e:
    print("\n=== ERROR ===")
    print(f"  {type(e).__name__}: {e}")
    import traceback
    print("  Traceback:")
    print("  " + "\n  ".join(traceback.format_exc().split("\n")))
    sys.exit(1)

sys.exit(0)

