# Script to check indentation in dssa_optimizer.py __init__ method
with open('hexdynamic/dssa_optimizer.py', encoding='utf-8') as f:
    lines = f.readlines()

# Find __init__ start
start = None
for i, line in enumerate(lines):
    if 'def __init__' in line and i < 50:
        start = i
        break

if start:
    print(f"Found __init__ at line {start+1}")
    for i in range(start, min(start+30, len(lines))):
        line = lines[i]
        if line.strip() == '':
            continue
        spaces = len(line) - len(line.lstrip())
        print(f'{i+1:3d} (spaces={spaces}): {line.rstrip()}')
        if line.strip().startswith('def ') and i > start:
            break
