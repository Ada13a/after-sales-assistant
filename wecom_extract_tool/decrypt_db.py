"""
WeCom Database Decryptor v2
Tries many encryption variants since WeCom uses WCDB (not vanilla SQLCipher).

Usage: decrypt_db.exe --all
"""
import os
import sys
import json
import struct
import hashlib
import argparse

try:
    from Crypto.Cipher import AES
except ImportError:
    print("ERROR: pycryptodome not installed")
    sys.exit(1)


def get_tool_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def clean_key(raw_key_hex):
    """Clean key string to pure hex."""
    k = raw_key_hex.strip()
    if k.startswith("x'") and k.endswith("'"):
        k = k[2:-1]
    if k.startswith('"') and k.endswith('"'):
        k = k[1:-1]
    return k


def try_all_variants(db_data, raw_key_hex):
    """
    Try to decrypt page 0 with many variants.
    Returns (True, (aes_key, page_format)) or (False, None).
    page_format is a dict describing the successful configuration.
    """
    key_hex = clean_key(raw_key_hex)
    try:
        raw_key = bytes.fromhex(key_hex)
    except ValueError:
        return False, None

    if len(raw_key) < 16:
        return False, None

    # Derive keys for all methods
    derived_keys = []

    # Method 0: PBKDF2-SHA512, 256k iter, 96 bytes (SQLCipher 4)
    dk4 = hashlib.pbkdf2_hmac('sha512', raw_key, b'', 256000, dklen=96)
    derived_keys.append(('sc4', dk4[:32]))

    # Method 1: PBKDF2-SHA1, 64k iter, 64 bytes (SQLCipher 3)
    dk3 = hashlib.pbkdf2_hmac('sha1', raw_key, b'', 64000, dklen=64)
    derived_keys.append(('sc3', dk3[:32]))

    # Method 2: Raw key (first 32 bytes)
    if len(raw_key) >= 32:
        derived_keys.append(('raw32', raw_key[:32]))

    # Method 3: SHA256 of raw key
    derived_keys.append(('sha256', hashlib.sha256(raw_key).digest()))

    # Method 4: PBKDF2-SHA512, 64000 iter (hybrid)
    dkh = hashlib.pbkdf2_hmac('sha512', raw_key, b'', 64000, dklen=64)
    derived_keys.append(('hybrid', dkh[:32]))

    # Page formats: (reserve_size, iv_at_start, reserve_at_end, iv_size, label)
    page_formats = [
        # WeCom WCDB: IV at start (0-15), 64-byte reserve at page end
        (64, True, True, 16, 'wcdb_iv0_rsv64'),
        # WeCom WCDB: IV at start, 48-byte reserve at page end
        (48, True, True, 16, 'wcdb_iv0_rsv48'),
        # SQLCipher 4: IV in reserve at page end
        (48, False, True, 16, 'sc4_rsv48'),
        # SQLCipher 4 with 64 reserve
        (64, False, True, 16, 'sc4_rsv64'),
        # IV at start, no reserve
        (0, True, False, 16, 'iv_first'),
        # SQLCipher 3
        (32, False, True, 16, 'sc3'),
        # Other variants
        (80, False, True, 16, 'rsv80'),
        (56, False, True, 16, 'rsv56'),
        (16, False, True, 16, 'rsv16'),
        (48, False, True, 12, 'sc4_iv12'),
    ]

    page0 = db_data[:4096]
    if len(page0) < 4096:
        return False, None

    for reserve_size, iv_at_start, reserve_at_end, iv_size, fmt_label in page_formats:
        if iv_at_start:
            iv = page0[:iv_size]
            if reserve_at_end:
                content = page0[iv_size:4096 - reserve_size]
            else:
                content = page0[iv_size:4096]
        else:
            content = page0[:4096 - reserve_size]
            iv = page0[4096 - reserve_size:4096 - reserve_size + iv_size]

        if len(iv) < iv_size:
            continue

        for key_label, aes_key in derived_keys:
            try:
                cipher = AES.new(aes_key, AES.MODE_CBC, iv[:16])
                decrypted = cipher.decrypt(content)
                if decrypted[:16] == b"SQLite format 3\x00":
                    return True, {
                        'aes_key': aes_key,
                        'page0_iv': iv[:16],
                        'reserve_size': reserve_size,
                        'reserve_at_end': reserve_at_end,
                        'iv_at_start': iv_at_start,
                        'key_method': key_label,
                        'fmt_label': fmt_label,
                    }
            except Exception:
                continue

    return False, None


def decrypt_full(data, aes_key, page0_iv, reserve_size, reserve_at_end, iv_at_start):
    """Decrypt entire database."""
    PAGE = 4096
    decrypted = bytearray()
    pages = (len(data) + PAGE - 1) // PAGE

    for p in range(pages):
        start = p * PAGE
        end = min(start + PAGE, len(data))
        page = data[start:end]

        if p == 0:
            if iv_at_start:
                iv_size = len(page0_iv)
                content = page[iv_size:PAGE - reserve_size]
            else:
                content = page[:PAGE - reserve_size]
            iv = page0_iv
        else:
            if len(page) < 32:
                decrypted.extend(page)
                continue
            iv = page[:16]
            if reserve_at_end:
                content_len = PAGE - reserve_size - 16
                content = page[16:16 + content_len] if len(page) >= 16 + content_len else page[16:]
            else:
                content = page[16:]

        pad_len = ((len(content) + 15) // 16) * 16
        padded = content + b'\x00' * (pad_len - len(content))

        try:
            cipher = AES.new(aes_key, AES.MODE_CBC, iv)
            dec = cipher.decrypt(padded)
            decrypted.extend(dec[:len(content)])
        except Exception:
            decrypted.extend(page)

    # Trim to actual size
    result = bytes(decrypted)
    if len(result) >= 100 and result[:16] == b"SQLite format 3\x00":
        try:
            page_count = struct.unpack('>I', result[28:32])[0]
            actual = page_count * PAGE
            if 0 < actual < len(result):
                result = result[:actual]
        except Exception:
            pass

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    tool_dir = get_tool_dir()
    keys_file = os.path.join(tool_dir, "found_keys.json")
    txt_file = os.path.join(tool_dir, "found_keys.txt")

    print("=" * 60)
    print("  WeCom DB Decryptor v2")
    print("=" * 60)

    # Load keys from multiple sources
    keys = []

    if os.path.exists(keys_file):
        with open(keys_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        keys = data.get("keys", [])

    if not keys and os.path.exists(txt_file):
        with open(txt_file, "r") as f:
            for line in f:
                k = line.strip()
                if k and len(k) >= 64:
                    keys.append(k)

    if not keys:
        # Fallback: scan for files
        for f in os.listdir(tool_dir):
            if f.endswith('.json') and 'key' in f.lower():
                with open(os.path.join(tool_dir, f), "r", encoding="utf-8") as fh:
                    try:
                        d = json.load(fh)
                        if 'keys' in d:
                            keys = d['keys']
                            break
                    except Exception:
                        pass

    print(f"Loaded {len(keys)} candidate keys.")

    if not keys:
        print("ERROR: No keys found.")
        print("Looked in:", tool_dir)
        print("Files:", os.listdir(tool_dir))
        sys.exit(1)

    # Load databases from found_keys.json or scan directory
    dbs = []
    if os.path.exists(keys_file):
        with open(keys_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        for entry in data.get("databases", []):
            p = entry.get("path", "")
            n = entry.get("name", "")
            if p and os.path.exists(p):
                dbs.append((p, n))

    if not dbs:
        print("ERROR: No databases found.")
        sys.exit(1)

    # Focus on message/msg databases first
    priority = []
    rest = []
    for path, name in dbs:
        lower = name.lower()
        if any(kw in lower for kw in ['message', 'msg', 'chat', 'im']) and 'lookup' not in lower and 'index' not in lower:
            priority.append((path, name))
        else:
            rest.append((path, name))

    targets = priority + rest
    print(f"\nTrying {len(targets)} DBs with {len(keys)} keys...")
    print(f"(Testing {len(keys) * 10} key+format combinations per DB)\n")

    success = 0
    for path, name in targets:
        size_mb = os.path.getsize(path) / (1024 * 1024)
        print(f"  {name} ({size_mb:.1f} MB) ...", end=" ", flush=True)

        with open(path, "rb") as f:
            db_data = f.read()

        found = False
        for key in keys:
            ok, config = try_all_variants(db_data, key)
            if ok:
                print(f"MATCH! ({config['key_method']}/{config['fmt_label']}) Decrypting...", end=" ", flush=True)

                decrypted = decrypt_full(
                    db_data,
                    config['aes_key'],
                    config['page0_iv'],
                    config['reserve_size'],
                    config['reserve_at_end'],
                    config.get('iv_at_start', False)
                )

                out_path = path + ".decrypted.db"
                # If path already has .db, use different naming
                if out_path == path:
                    out_path = path.replace('.db', '.decrypted.db')

                with open(out_path, "wb") as f:
                    f.write(decrypted)

                out_mb = os.path.getsize(out_path) / (1024 * 1024)
                print(f"OK ({out_mb:.1f} MB)")
                success += 1
                found = True
                break

        if not found:
            print("FAILED")

    print(f"\n{'=' * 60}")
    print(f"Done! {success}/{len(targets)} decrypted.")
    if success > 0:
        print(f"Next: extract_messages.exe")
    else:
        print("No DBs could be decrypted. The encryption format may be different.")
        print("Please send the tool folder back for analysis.")
    print("=" * 60)


if __name__ == "__main__":
    main()
