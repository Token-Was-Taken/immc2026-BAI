with open('hexdynamic/dssa_optimizer.py', 'rb') as f:
    content = f.read()
lines = content.split(b'\n')
# show lines 50-70
for i in range(49, 75):
    line = lines[i] if i < len(lines) else b''
    leading = len(line) - len(line.lstrip())
    print(f'{i+1:3d} leading={leading}: {line}')
