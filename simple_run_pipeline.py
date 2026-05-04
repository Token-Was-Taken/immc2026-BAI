import os
import sys
sys.path.insert(0, os.path.abspath('hexdynamic'))

from protection_pipeline import run_pipeline

# Run pipeline
print("Running protection_pipeline with out35.json as input...")
run_pipeline(
    input_path='hexdynamic/out35.json',
    output_path='hexdynamic/out36.json',
    vectorized=False,
    allow_partial_deployment=False
)
print("\nPipeline completed!")

# Now let's check out36.json's grid944!
import json
d = json.load(open('hexdynamic/out36.json'))
g944 = None
for g in d['grids']:
    if g['grid_id'] == 944:
        g944 = g

if g944:
    print("grid944 found:")
    print(f"q: {g944['q']}, r: {g944['r']}")
    print(f"boundary_edge_list: {g944['fences']['boundary_edge_list']}")
else:
    print("grid944 not found!")