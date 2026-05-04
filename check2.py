with open('hexdynamic/dssa_optimizer.py', encoding='utf-8') as f:
    lines = f.readlines()
    for i in range(35, 70):
        line = lines[i]
        spaces = len(line) - len(line.lstrip())
        print(f'{i+1:3d} (spaces={spaces}): {line.rstrip()}')
