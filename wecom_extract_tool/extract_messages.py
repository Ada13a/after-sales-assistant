"""
WeCom Message Extractor
Extract chat messages from decrypted databases and export as text files.

Usage: python extract_messages.py
Output: output/ (one text file per chat + _index.txt)
"""
import sqlite3
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import zstandard
except ImportError:
    print("ERROR: zstandard not installed. Run: pip install zstandard")
    sys.exit(1)

if getattr(sys, 'frozen', False):
    TOOL_DIR = Path(os.path.dirname(os.path.abspath(sys.executable)))
else:
    TOOL_DIR = Path(__file__).parent
OUTPUT_DIR = TOOL_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def decompress(data):
    if not data or not isinstance(data, bytes) or len(data) < 4:
        return data
    if data[:4] == b'\x28\xb5\x2f\xfd':
        try:
            dctx = zstandard.ZstdDecompressor()
            return dctx.decompress(data, max_output_size=100 * 1024 * 1024)
        except Exception:
            return data
    return data


def safe_decode(data):
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if isinstance(data, bytes):
        d = decompress(data)
        if isinstance(d, bytes):
            try:
                return d.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    return d.decode("gbk")
                except UnicodeDecodeError:
                    return f"[binary:{len(d)}b]"
        return str(d)
    return str(data)


def find_decrypted_dbs():
    """Find all decrypted database files."""
    dbs = {}
    for f in TOOL_DIR.glob("*.decrypted.db"):
        name = f.stem.replace('.decrypted', '')
        dbs[name] = str(f)
    for f in TOOL_DIR.rglob("*.decrypted.db"):
        name = f.stem.replace('.decrypted', '')
        if name not in dbs:
            dbs[name] = str(f)
    return dbs


def load_contacts(contact_db_path):
    """Load contacts from decrypted contact DB."""
    contacts = {}
    if not contact_db_path or not os.path.exists(contact_db_path):
        return contacts
    try:
        conn = sqlite3.connect(contact_db_path)
        for row in conn.execute("SELECT username, remark, nick_name, alias FROM contact"):
            username, remark, nick, alias = row
            contacts[username] = {
                "remark": remark or "",
                "nick": nick or "",
                "alias": alias or ""
            }
        conn.close()
    except Exception:
        pass
    return contacts


def extract(msg_db_path, contact_db_path):
    """Extract all messages from decrypted message DB."""
    print(f"Message DB: {msg_db_path}")

    contacts = load_contacts(contact_db_path)
    print(f"Contacts: {len(contacts)}")

    def get_display_name(username):
        c = contacts.get(username, {})
        return c.get("remark") or c.get("nick") or c.get("alias") or username

    conn = sqlite3.connect(msg_db_path)

    # Build Name2Id -> MD5 mapping
    name2id = {}
    try:
        for row in conn.execute("SELECT user_name, is_session FROM Name2Id"):
            name2id[row[0]] = row[1]
    except Exception:
        pass

    md5_to_user = {}
    for username in name2id:
        md5 = hashlib.md5(username.encode()).hexdigest()
        md5_to_user[md5] = username

    # Get all message tables
    msg_tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
    ).fetchall()

    if not msg_tables:
        print("ERROR: No Msg_ tables found. Not a WeCom message database?")
        # Try alternative: messages stored differently
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        print(f"Available tables: {[t[0] for t in tables[:30]]}")
        conn.close()
        return []

    total_msgs = 0
    chat_stats = []

    for (table,) in msg_tables:
        try:
            cnt = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
            total_msgs += cnt
            md5_hash = table[4:]
            username = md5_to_user.get(md5_hash, "?")
            display = get_display_name(username)
            chat_stats.append({
                "table": table, "username": username,
                "display": display, "count": cnt
            })
        except Exception:
            continue

    chat_stats.sort(key=lambda x: x["count"], reverse=True)

    print(f"Chats: {len(chat_stats)}")
    print(f"Total messages: {total_msgs}")
    print(f"Extracting...")

    extracted = []
    for i, chat in enumerate(chat_stats):
        table = chat["table"]
        display = chat["display"][:60]
        # Sanitize filename
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', display)[:60]

        cols = [d[1] for d in conn.execute(f"PRAGMA table_info('{table}')").fetchall()]
        has_content = "message_content" in cols

        select_cols = ["local_id", "create_time"]
        if has_content:
            select_cols.append("message_content")

        try:
            rows = conn.execute(
                f"SELECT {', '.join(select_cols)} FROM [{table}] ORDER BY create_time ASC"
            ).fetchall()
        except Exception:
            continue

        if not rows:
            continue

        out_file = OUTPUT_DIR / f"{i+1:03d}_{safe_name}.txt"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(f"Chat: {display}\n")
            f.write(f"Messages: {len(rows)}\n")
            f.write("=" * 60 + "\n\n")

            for row in rows:
                ts = row[1]
                time_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "?"
                content = ""
                if has_content and len(row) > 2:
                    content = safe_decode(row[2])
                if content and len(content.strip()) > 1:
                    f.write(f"[{time_str}] {content}\n")

        extracted.append({
            "seq": i + 1,
            "chat_name": chat["display"],
            "msg_count": len(rows),
            "file": out_file.name
        })

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(chat_stats)} done...")

    conn.close()

    # Write index
    index_file = OUTPUT_DIR / "_index.txt"
    with open(index_file, "w", encoding="utf-8") as f:
        f.write(f"{'#':>4} {'Msgs':>6}  Chat\n")
        f.write("-" * 80 + "\n")
        for i, chat in enumerate(chat_stats):
            f.write(f"{i+1:4d} {chat['count']:6d}  {chat['display']}  ({chat['username']})\n")

    print(f"\nDone!")
    print(f"  Output: {OUTPUT_DIR}")
    print(f"  Index:  {index_file}")
    print(f"  Files:  {len(extracted)} chat(s)")

    # Save extract info
    info = {
        "extract_time": datetime.now().isoformat(),
        "tool_dir": str(TOOL_DIR),
        "output_dir": str(OUTPUT_DIR),
    }
    with open(OUTPUT_DIR / "_extract_info.json", "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    return extracted


def main():
    print("=" * 60)
    print("  WeCom Message Extractor")
    print("=" * 60)

    dbs = find_decrypted_dbs()
    if not dbs:
        print("\nERROR: No decrypted .db files found.")
        print("Run: python decrypt_db.py --all  first.")
        sys.exit(1)

    print(f"\nFound {len(dbs)} decrypted DB(s):")
    for name, path in dbs.items():
        size_mb = os.path.getsize(path) / (1024 * 1024)
        print(f"  {name}  ({size_mb:.1f} MB)")

    # Find message and contact DBs
    msg_db = None
    contact_db = None
    for name, path in dbs.items():
        lower = name.lower()
        if 'message' in lower or 'msg' in lower:
            msg_db = path
        if 'contact' in lower:
            contact_db = path

    if not msg_db:
        # Try any large decrypted db
        dbs_sorted = sorted(dbs.items(), key=lambda x: os.path.getsize(x[1]), reverse=True)
        for name, path in dbs_sorted:
            try:
                conn = sqlite3.connect(path)
                tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                table_names = [t[0] for t in tables]
                if any('Msg_' in t for t in table_names) or 'Name2Id' in table_names:
                    msg_db = path
                    print(f"\nUsing: {name} as message DB")
                conn.close()
                if msg_db:
                    break
            except Exception:
                continue

    if not msg_db:
        print("\nNo message database found automatically.")
        path = input("Enter message DB path: ").strip()
        if path and os.path.exists(path):
            msg_db = path
        else:
            print("ERROR: No valid message DB.")
            sys.exit(1)

    print(f"\nExtracting messages...")
    extract(msg_db, contact_db)

    print("\n" + "=" * 60)
    print("All done!")
    print("Pack the entire wecom_extract_tool folder and send it back.")
    print("=" * 60)


if __name__ == "__main__":
    main()
