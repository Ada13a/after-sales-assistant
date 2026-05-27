"""Quick check: what do the WeCom DB file headers look like?"""
import os
import sys

tool_dir = os.path.dirname(os.path.abspath(__file__))
# Also check if running from frozen exe
if getattr(sys, 'frozen', False):
    tool_dir = os.path.dirname(os.path.abspath(sys.executable))

keys_file = os.path.join(tool_dir, "found_keys.json")
if not os.path.exists(keys_file):
    print("No found_keys.json - run scan_key.exe first")
    input("Press Enter...")
    sys.exit(1)

import json
with open(keys_file, "r", encoding="utf-8") as f:
    data = json.load(f)

for db_info in data.get("databases", [])[:10]:
    path = db_info["path"]
    name = db_info["name"]
    size = db_info["size_mb"]
    if not os.path.exists(path):
        continue

    with open(path, "rb") as f:
        header = f.read(100)

    print(f"\n{'='*60}")
    print(f"File: {name} ({size:.1f} MB)")
    print(f"Path: {path}")
    print(f"First 16 bytes (hex): {header[:16].hex()}")
    print(f"First 16 bytes (raw): {header[:16]}")
    print(f"Bytes 16-32 (hex): {header[16:32].hex()}")

    # Check for known signatures
    if header[:16] == b"SQLite format 3\x00":
        print(">>> PLAIN SQLite (not encrypted)")
    elif header[:4] == b"\x28\xb5\x2f\xfd":
        print(">>> ZSTD compressed")
    elif header[:4] == b"\x50\x4b\x03\x04":
        print(">>> ZIP file")
    else:
        # Check if it looks like encrypted data (high entropy)
        unique = len(set(header[:32]))
        print(f">>> Unique bytes in first 32: {unique}/32")
        print(f">>> Looks ENCRYPTED")

input("\nPress Enter to exit...")
