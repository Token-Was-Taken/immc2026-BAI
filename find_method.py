with open('hexdynamic/dssa_optimizer.py', 'rb') as f:
    content = f.read()
lines = content.split(b'\n')
# find _apply_frozen_resources line number
for i, line in enumerate(lines):
    if b'_apply_frozen_resources' in line:
        print(f"Found at index {i} (line {i+1})")
        # show surrounding lines
        for j in range(max(0,i-2), min(len(lines), i+10)):
            l = lines[j]
            lead = len(l) - len(l.lstrip())
            print(f'{j+1:3d} lead={lead}: {l[:80]}')
        break