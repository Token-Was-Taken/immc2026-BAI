with open('hexdynamic/dssa_optimizer.py', 'rb') as f:
    lines = f.readlines()
print(f"Total lines: {len(lines)}")
# show lines 288-291
for i in [287,288,289,290,291]:
    if i < len(lines):
        print(f'{i+1}: {repr(lines[i])}')
