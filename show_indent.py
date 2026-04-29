import subprocess
import subprocess

result = subprocess.run(
    ['git', 'show', 'HEAD:hexdynamic/dssa_optimizer.py'],
    capture_output=True, text=True, encoding='utf-8'
)
lines = result.stdout.split('\n')
for i in range(35, 60):
    if i < len(lines):
        line = lines[i]
        # Show leading length and repr
        leading_spaces = len(line) - len(line.lstrip())
        print(f'{i+1:3d} lead={leading_spaces}: {repr(line[:50])}')
