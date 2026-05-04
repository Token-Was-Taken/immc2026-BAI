with open('hexdynamic/dssa_optimizer.py', 'rb') as f:
    content = f.read()
lines = content.split(b'\n')
for i in range(35, 65):
    line = lines[i] if i < len(lines) else b''
    leading = len(line) - len(line.lstrip())
    print(f'{i+1:3d} lead={leading}: {line[:80]}')
