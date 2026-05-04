import subprocess
result = subprocess.run(
    ['git', 'show', 'HEAD:hexdynamic/dssa_optimizer.py'],
    capture_output=True, text=True, encoding='utf-8'
)
lines = result.stdout.split('\n')
# print lines 30-70
for i in range(29, 70):
    if i < len(lines):
        print(f'{i+1:3d}: {lines[i]}')
