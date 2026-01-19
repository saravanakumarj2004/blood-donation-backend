import os

file_path = 'api/views.py'

try:
    with open(file_path, 'rb') as f:
        content = f.read()

    # Strip null bytes caused by PowerShell 'type >>' UTF-16 behavior
    clean_content = content.replace(b'\x00', b'')

    with open(file_path, 'wb') as f:
        f.write(clean_content)

    print(f"Successfully cleaned {file_path}")

except Exception as e:
    print(f"Error: {e}")
