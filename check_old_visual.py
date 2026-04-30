
import subprocess

result = subprocess.run(
    ['git', 'show', '6143bac:hexdynamic/visualize_output.py'],
    cwd=r'd:\code\immc2026-BAI',
    capture_output=True,
    text=True,
    encoding='utf-8',
    errors='replace'
)

if result.returncode == 0:
    with open(r'temp_old_visual.py', 'w', encoding='utf-8') as f:
        f.write(result.stdout)
    print("Old visualize_output.py saved to temp_old_visual.py")
    print("\n=== Plot functions in old version ===")
    import re
    matches = re.findall(r'def plot_(\w+)', result.stdout)
    print("\n".join(matches))
else:
    print(f"Error: {result.stderr}")

