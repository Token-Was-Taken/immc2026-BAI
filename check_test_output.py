
import os
from pathlib import Path

test_output_dir = Path(r'd:\code\immc2026-BAI\hexdynamic\test_output')

print(f"Checking directory: {test_output_dir}")
print(f"Directory exists: {test_output_dir.exists()}")

if test_output_dir.exists():
    print("\nFiles in directory:")
    for f in sorted(test_output_dir.iterdir()):
        print(f"  - {f.name}")
        
        if 'species' in f.name.lower():
            print("    ✓ Found species-related file!")

else:
    print("Creating directory...")
    test_output_dir.mkdir(exist_ok=True)

