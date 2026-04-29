with open('hexdynamic/dssa_optimizer.py', 'rb') as f:
    content = f.read()
# Find the __init__ area
lines = content.split(b'\n')
for i in range(36, 51):
    line = lines[i] if i < len(lines) else b''
    # Count leading whitespace characters (spaces or tabs)
    leading = len(line) - len(line.lstrip())
    print(f'{i+1:3d} leading_bytes={leading}: {line[:50]}')
