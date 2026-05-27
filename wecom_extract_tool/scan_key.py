"""
WeCom DB Key Extractor v2
Multi-source key extraction: memory + registry + config files

Usage: scan_key.exe
"""
import os
import sys
import re
import json
import struct
import hashlib
import ctypes
import ctypes.wintypes
from ctypes import wintypes

# Windows API
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)


def find_wxwork_process():
    try:
        import psutil
        for proc in psutil.process_iter(['pid', 'name', 'exe']):
            try:
                if proc.info['name'].lower() == 'wxwork.exe':
                    return proc
            except Exception:
                continue
    except ImportError:
        print("FATAL: psutil not available")
        sys.exit(1)
    return None


def find_wxwork_data_dirs():
    """Find WeCom data directories from common locations"""
    candidates = [
        os.path.expandvars(r"%USERPROFILE%\Documents\WXWork"),
        os.path.expandvars(r"%APPDATA%\Tencent\WXWork"),
        os.path.expandvars(r"%LOCALAPPDATA%\Tencent\WXWork"),
        r"D:\WXWork",
        r"C:\WXWork",
    ]
    found = set()
    for base in candidates:
        if not os.path.exists(base):
            continue
        # Walk 2 levels deep
        for item in os.listdir(base):
            full = os.path.join(base, item)
            if not os.path.isdir(full):
                continue
            for sub in ['Data', 'data', 'db_storage', 'Msg', 'msg']:
                test = os.path.join(full, sub)
                if os.path.exists(test):
                    found.add(full)
                    break
            # Also check if it directly contains .db files
            for f in os.listdir(full)[:5]:
                if f.endswith('.db'):
                    found.add(full)
                    break
    return list(found)


def find_databases(data_root):
    """Find all .db files in data root, return sorted by size desc"""
    dbs = []
    for root, dirs, files in os.walk(data_root):
        for f in files:
            if not f.endswith('.db') or f.endswith('.decrypted.db'):
                continue
            fpath = os.path.join(root, f)
            size_mb = os.path.getsize(fpath) / (1024 * 1024)
            if size_mb > 0.5:
                dbs.append((fpath, size_mb, f))
    return sorted(dbs, key=lambda x: x[1], reverse=True)


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", ctypes.c_uint32),
        ("__a1", ctypes.c_uint32),
        ("RegionSize", ctypes.c_uint64),
        ("State", ctypes.c_uint32),
        ("Protect", ctypes.c_uint32),
        ("Type", ctypes.c_uint32),
        ("__a2", ctypes.c_uint32),
    ]


def scan_memory(pid):
    """Scan process memory for potential DB keys"""
    h = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        print("ERROR: Cannot open process. Run as Administrator!")
        sys.exit(1)

    found = set()
    region_count = 0
    address = 0

    # Search patterns: different key formats
    # WCDB may store keys as raw bytes, not just hex strings
    patterns = [
        # 64-char hex strings (SQLCipher standard)
        rb"[0-9a-fA-F]{64}",
        # 96-char hex strings (longer keys)
        rb"[0-9a-fA-F]{96}",
        # x'...' quoted hex keys
        rb"x'([0-9a-fA-F]{64})'",
        rb"x'([0-9a-fA-F]{96})'",
    ]

    while region_count < 5000:
        mbi = MEMORY_BASIC_INFORMATION()
        r = kernel32.VirtualQueryEx(
            ctypes.c_void_p(h),
            ctypes.c_void_p(address),
            ctypes.byref(mbi),
            ctypes.sizeof(mbi)
        )
        if r == 0:
            break

        base = mbi.BaseAddress or 0
        size = mbi.RegionSize
        state = mbi.State
        protect = mbi.Protect

        address = base + size
        region_count += 1

        if region_count % 500 == 0:
            print(f"  Mem: {region_count} regions, {len(found)} keys...")

        if state != MEM_COMMIT:
            continue
        if protect & 0x100:
            continue
        if size > 200 * 1024 * 1024:
            continue

        offset = 0
        while offset < size:
            read_size = min(512 * 1024, size - offset)
            buf = (ctypes.c_char * read_size)()
            bytes_read = ctypes.c_size_t(0)

            ok = kernel32.ReadProcessMemory(
                h, ctypes.c_void_p(base + offset),
                buf, read_size, ctypes.byref(bytes_read)
            )
            if ok and bytes_read.value > 0:
                data = bytes(buf[:bytes_read.value])
                for pat in patterns:
                    for match in re.finditer(pat, data):
                        if match.lastindex and match.lastindex >= 1:
                            k = match.group(1).decode('ascii')
                        else:
                            k = match.group(0).decode('ascii')
                        found.add(k)
            offset += 512 * 1024

    kernel32.CloseHandle(h)
    return list(found)


def scan_registry():
    """Search Windows registry for WeCom DB keys"""
    import winreg
    keys = set()
    reg_paths = [
        r"Software\Tencent\WXWork",
        r"Software\Tencent\WeChatWork",
        r"Software\WOW6432Node\Tencent\WXWork",
    ]
    for reg_path in reg_paths:
        try:
            for hive in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
                try:
                    key = winreg.OpenKey(hive, reg_path)
                    i = 0
                    while True:
                        try:
                            name, value, _ = winreg.EnumValue(key, i)
                            val_str = str(value)
                            # Look for hex-looking values
                            hexes = re.findall(r'[0-9a-fA-F]{64,}', val_str)
                            keys.update(hexes)
                            i += 1
                        except OSError:
                            break
                    winreg.CloseKey(key)
                except OSError:
                    continue
        except Exception:
            continue
    return list(keys)


def scan_config_files(data_dirs):
    """Search config files in WeCom data directories"""
    keys = set()
    config_patterns = ['*.ini', '*.cfg', '*.conf', '*.json', '*.xml', 'config*', '*.dat']
    for data_dir in data_dirs:
        for root, dirs, files in os.walk(data_dir):
            for f in files:
                if not any(f.lower().endswith(p.replace('*', '')) or
                          (not p.startswith('*') and f.lower() == p.lower())
                          for p in config_patterns):
                    continue
                if os.path.getsize(os.path.join(root, f)) > 10 * 1024 * 1024:
                    continue
                try:
                    with open(os.path.join(root, f), 'rb') as fh:
                        content = fh.read()
                    text = content.decode('utf-8', errors='ignore')
                    hexes = re.findall(r'[0-9a-fA-F]{64,}', text)
                    keys.update(hexes)
                except Exception:
                    continue
    return list(keys)


def get_tool_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def main():
    tool_dir = get_tool_dir()

    print("=" * 60)
    print("  WeCom DB Key Extractor v2")
    print("=" * 60)

    # 1. Find process
    print("\n[1/5] Finding WXWork.exe...")
    proc = find_wxwork_process()
    if proc:
        print(f"  Found: PID={proc.pid}")
    else:
        print("  WARNING: WXWork.exe not found!")
        print("  Will skip memory scan, try registry + config files.")
        proc = None

    # 2. Memory scan
    all_keys = set()
    if proc:
        print(f"\n[2/5] Scanning memory (PID={proc.pid})...")
        mem_keys = scan_memory(proc.pid)
        all_keys.update(mem_keys)
        print(f"  Found: {len(mem_keys)} keys from memory")
    else:
        print("\n[2/5] Skipping memory scan (no process)")

    # 3. Registry scan
    print("\n[3/5] Scanning registry...")
    reg_keys = scan_registry()
    all_keys.update(reg_keys)
    print(f"  Found: {len(reg_keys)} keys from registry")

    # 4. Find data dirs and config files
    print("\n[4/5] Finding data directories...")
    data_dirs = find_wxwork_data_dirs()
    if not data_dirs:
        print("  No auto-detected dirs.")
        manual = input("  Enter WeCom data path: ").strip()
        if manual and os.path.exists(manual):
            data_dirs = [manual]

    all_dbs = []
    if data_dirs:
        print(f"  Found {len(data_dirs)} dir(s):")
        for d in data_dirs:
            print(f"    {d}")
            dbs = find_databases(d)
            for p, s, n in dbs[:15]:
                print(f"      {n}  ({s:.1f} MB)")
            all_dbs.extend(dbs)

        print(f"\n  Scanning config files for keys...")
        cfg_keys = scan_config_files(data_dirs)
        all_keys.update(cfg_keys)
        print(f"  Found: {len(cfg_keys)} keys from config files")

    # 5. Save
    print(f"\n[5/5] Saving ({len(all_keys)} total keys)...")

    output = {
        "pid": proc.pid if proc else 0,
        "keys": sorted(all_keys),
        "data_dirs": data_dirs,
        "databases": [{"path": p, "size_mb": round(s,1), "name": n} for p, s, n in all_dbs]
    }

    json_path = os.path.join(tool_dir, "found_keys.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    txt_path = os.path.join(tool_dir, "found_keys.txt")
    with open(txt_path, "w") as f:
        for k in sorted(all_keys):
            f.write(f"x'{k}'\n")

    print(f"  JSON: {json_path}")
    print(f"  TXT:  {txt_path}")
    print(f"  Total keys: {len(all_keys)}")
    print(f"  Databases:  {len(all_dbs)}")
    print(f"  Sources: memory{' + ' if proc else ''}registry + config files")

    print("\n" + "=" * 60)
    print("Done! Next: decrypt_db.exe --all")
    print("=" * 60)


if __name__ == "__main__":
    main()
