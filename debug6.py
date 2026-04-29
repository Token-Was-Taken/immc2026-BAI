with open('hexdynamic/dssa_optimizer.py', 'rb') as f:
    content = f.read()
lines = content.split(b'\n')
# Show lines 36-40 to see class and __init__ def indent
for i in [36,37,38,39,40,50,69,70,77]:
    line = lines[i] if i < len(lines) else b''
    leading = len(line) - len(line.lstrip())
    print(f'{i+1:3d} leading={leading}: {line[:80]}')
