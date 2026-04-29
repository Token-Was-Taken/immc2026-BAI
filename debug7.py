with open('hexdynamic/dssa_optimizer.py', 'rb') as f:
    content = f.read()
lines = content.split(b'\n')
# print lines around _initialize_solution
for i in range(68, 77):
    line = lines[i] if i < len(lines) else b''
    leading = len(line) - len(line.lstrip())
    print(f'{i+1:3d} leading={leading}: {line[:80]}')
