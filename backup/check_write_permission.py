# check_write_permission.py
try:
    with open('/Users/yanzhang/Documents/test_permission.txt', 'w') as f:
        f.write('Test')
    print("Write permission confirmed.")
except PermissionError:
    print("No write permission.")
