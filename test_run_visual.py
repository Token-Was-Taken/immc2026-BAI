
import subprocess
import os

# 直接运行 visualize_output.py，不经过 git pager
os.chdir(r'd:\code\immc2026-BAI\hexdynamic')
print("Running visualize_output.py...")
result = subprocess.run(
    [
        'python', 'visualize_output.py', 'test_fence_fixed.json',
        '--input', 'base1.json',
        '--out_dir', 'test_output'
    ],
    capture_output=True,
    text=True
)

print("\n=== STDOUT ===")
print(result.stdout)

print("\n=== STDERR ===")
print(result.stderr)

print("\n=== Files in test_output ===")
if os.path.exists('test_output'):
    for f in os.listdir('test_output'):
        if 'species_deployment' in f:
            print(f"✓ Found: {f}")

