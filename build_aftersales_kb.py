"""
售后知识库构建脚本
功能:
1. 从微信解密DB提取售后相关消息
2. 识别 Q&A 问答对（客户提问 → 商家回答）
3. 构建售后 FAQ 知识库
"""
import sqlite3
import hashlib
import zstandard
import json
import re
import os
from datetime import datetime
from pathlib import Path
from collections import defaultdict

MSG_DB = r"F:/sotfware shit/Weixin_file/xwechat_files/wxid_4ylmjumlahzd22_3c59/db_storage/message/message_0.decrypted.db"
CONTACT_DB = r"F:/sotfware shit/Weixin_file/xwechat_files/wxid_4ylmjumlahzd22_3c59/db_storage/contact/contact.decrypted.db"
KB_DIR = Path(__file__).parent / "knowledge_base"
TAN_DAN_KB = Path(r"d:/Agent_project/谈单助手/knowledge_base")
KB_DIR.mkdir(exist_ok=True)


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
                    return ""
        return str(d)
    return str(data)


# ============================================================
# 售后关键词模式（用于过滤和分类）
# ============================================================
AFTERSALES_PATTERNS = {
    "代码问题": [
        r"(编译|烧录|下载|程序|代码|bug|error|报错|不运行|运行不了|没反应|卡住|闪退)",
        r"(keil|IAR|STM32CubeIDE|Arduino IDE|串口|下载器|ST-Link|JLINK|ISP)",
        r"(main\.c|\.h文件|头文件|库函数|HAL库|标准库|寄存器)",
        r"(改了|修改了|换了个|调了).*(不行|不对|没用|没好)",
        r"(初始化|配置|引脚|GPIO|时钟|定时器|中断|PWM|ADC|I2C|SPI|UART)",
    ],
    "硬件问题": [
        r"(不亮|没反应|没电|短路|烧了|冒烟|发热|烫|松了|接触不良|虚焊)",
        r"(连不上|接不上|不通|断了|线.*掉|焊接|万用表|电压|电源|电池|充电)",
        r"(屏幕|显示|LCD|OLED|TFT).*(不亮|不显示|花屏|乱码|闪烁)",
        r"(传感器|模块|器件).*(坏|不工作|没数据|读不到|没输出|数据不对|不准)",
        r"(电机|舵机|水泵|风扇|继电器).*(不转|不动|不工作|卡住|抖动|异响)",
    ],
    "使用指导": [
        r"(怎么用|怎么操作|怎么连|怎么接|接线|连线|电路图|原理图|PCB)",
        r"(教程|说明书|手册|文档|资料|步骤|流程|演示|视频)",
        r"(烧录|下载).*(怎么|如何|步骤|教程|不会)",
        r"(APP|手机|蓝牙|WiFi).*(怎么|如何|连不上|连不了|搜索不到|配对)",
        r"(不懂|不会|不清楚|不知道|没看懂|看不太懂).*(怎么|如何|什么)",
    ],
    "论文问题": [
        r"(论文|文章|初稿|终稿|定稿|格式|排版|目录|图表|参考文献)",
        r"(查重|降重|重复率|知网|维普|万方|PaperPass)",
        r"(导师|老师).*(意见|说|要改|要求|让改|不通过|退回)",
        r"(摘要|绪论|引言|文献综述|系统设计|测试结果|结论|致谢)",
        r"(改.*论文|修.*论文|论文.*改|论文.*修|再改|再修)",
    ],
    "答辩支持": [
        r"(答辩|PPT|演示文稿|演讲|讲解|汇报|评审|评委)",
        r"(答辩).*(什么|怎么|如何|准备|问题|注意|技巧|经验)",
        r"(老师.*问|评.*问|答辩.*问|提问|问题.*回答)",
        r"(演示|展示).*(什么|怎么|如何|注意|技巧)",
    ],
    "物流跟踪": [
        r"(发货|快递|物流|单号|运单|顺丰|中通|圆通|申通|韵达|EMS)",
        r"(地址|收货|收件|电话|改地址|换地址)",
        r"(什么时候.*发|发.*没有|还没.*发|发.*了吗|发.*没发)",
        r"(收到|到货|签收|快递.*到|包裹|包装|开箱|检查)",
    ],
    "功能修改": [
        r"(能不能|可以|想).*(加|改|换|删|去掉|修改|增加|调整).*(功能|模块|传感器|器件)",
        r"(功能|方案).*(不够|太多|少了|多了|不行|不好|不满意)",
        r"(再加|加一个|多加点|补充|扩展|升级)",
        r"(换成|替换|更换|改用).*(传感器|模块|器件|芯片|方案)",
    ],
    "器件采购": [
        r"(买|购买|采购|淘宝|闲鱼|京东|链接|店铺|推荐|哪里买).*(器件|传感器|模块|元件|配件)",
        r"(BOM|物料|清单|元器件|器件.*列表|元件.*列表)",
        r"(什么.*型号|哪个.*型号|型号.*什么|型号.*哪个)",
        r"(规格|参数|封装|贴片|直插|排针|排母|杜邦线|面包板)",
    ],
}

# 商家回复特征（用于识别 Q&A 中的 Answer）
MERCHANT_PATTERNS = [
    r"(你|您).*(试|查|看|测|检|调|改|换|重新|再).*",
    r"(发|给|传|发你|发您|给你|给您).*(文件|代码|程序|图片|截图|视频|链接)",
    r"(好的|没问题|可以的|能改|可以做|这个简单)",
    r"(检查|排查|确认|核实|测试|验证).*",
    r"(先|再|然后|接着|下一步).*",
    r"(正常.*的|没问题.*的|可以.*的|需要.*的)",
    r"(告诉我|发我|给.*看|截图|拍照|录.*视频)",
    r"(退货|返修|寄回|发回|补发|重做|退款)",
]


def is_aftersales_message(text):
    """判断消息是否与售后相关"""
    if not text or len(text) < 4:
        return None
    for category, patterns in AFTERSALES_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                return category
    return None


def is_merchant_reply(text):
    """判断是否是商家回复（用于找 Answer）"""
    if not text or len(text) < 4:
        return False
    for pat in MERCHANT_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


def extract_qa_pairs(messages, chat_name):
    """从消息列表中提取 Q&A 问答对"""
    qa_pairs = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        category = is_aftersales_message(msg["text"])
        if category:
            question = msg
            # 向后找最近的商家回答（最多往后看10条）
            answer = None
            for j in range(i + 1, min(i + 11, len(messages))):
                if is_merchant_reply(messages[j]["text"]):
                    answer = messages[j]
                    break
            if answer:
                qa_pairs.append({
                    "category": category,
                    "chat_name": chat_name,
                    "question": question["text"][:500],
                    "question_time": question["time"],
                    "answer": answer["text"][:500],
                    "answer_time": answer["time"],
                })
                i = j + 1
                continue
        i += 1
    return qa_pairs


def load_contacts():
    """加载联系人信息"""
    contacts = {}
    try:
        conn = sqlite3.connect(CONTACT_DB)
        for row in conn.execute("SELECT username, remark, nick_name, alias FROM contact"):
            username, remark, nick, alias = row
            contacts[username] = {
                "remark": remark or "",
                "nick": nick or "",
                "alias": alias or ""
            }
        conn.close()
    except Exception as e:
        print(f"  加载联系人失败: {e}")
    return contacts


def build_knowledge_base():
    print("=" * 60)
    print("售后知识库构建")
    print("=" * 60)

    # 加载联系人
    print("\n[1/4] 加载联系人...")
    contacts = load_contacts()
    print(f"  加载 {len(contacts)} 个联系人")

    # 连接消息DB
    print("\n[2/4] 扫描售后消息...")
    conn_msg = sqlite3.connect(MSG_DB)

    # 构建 username -> display_name 映射
    name2id = {}
    for row in conn_msg.execute("SELECT user_name, is_session FROM Name2Id"):
        name2id[row[0]] = row[1]

    md5_to_user = {}
    for username in name2id:
        md5 = hashlib.md5(username.encode()).hexdigest()
        md5_to_user[md5] = username

    def get_display_name(username):
        c = contacts.get(username, {})
        return c.get("remark") or c.get("nick") or c.get("alias") or username

    # 获取所有 Msg_ 表并按消息数排序
    msg_tables = conn_msg.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
    ).fetchall()

    table_stats = []
    for (table,) in msg_tables:
        cnt = conn_msg.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
        table_stats.append((table, cnt))

    table_stats.sort(key=lambda x: x[1], reverse=True)
    total_msgs = sum(c for _, c in table_stats)
    print(f"  共 {len(table_stats)} 个会话, {total_msgs} 条消息")

    # 处理前200个最大的会话（覆盖主要业务对话）
    top_tables = table_stats[:200]
    print(f"  分析前 {len(top_tables)} 个最大会话...")

    all_qa_pairs = []
    all_issues = []
    category_counts = defaultdict(int)
    chat_issue_stats = []

    for idx, (table, cnt) in enumerate(top_tables):
        md5_hash = table[4:]
        username = md5_to_user.get(md5_hash, "?@" + md5_hash[:8])
        display = get_display_name(username)

        # 提取项目代号
        project_code = ""
        code_match = re.search(r'(26[A-Z]\d{4})', display)
        if code_match:
            project_code = code_match.group(1)

        # 读取消息
        cols = [d[1] for d in conn_msg.execute(f"PRAGMA table_info('{table}')").fetchall()]
        has_content = "message_content" in cols

        try:
            select_cols = ["local_id", "create_time"]
            if has_content:
                select_cols.append("message_content")
            rows = conn_msg.execute(
                f"SELECT {', '.join(select_cols)} FROM [{table}] ORDER BY create_time ASC"
            ).fetchall()
        except Exception as e:
            continue

        # 解析消息
        messages = []
        for row in rows:
            ts = row[1]
            time_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "?"
            content = ""
            if has_content and len(row) > 2:
                content = safe_decode(row[2])
            if content and len(content) > 2:
                messages.append({"time": time_str, "text": content})

        # 提取 Q&A 对
        qa_pairs = extract_qa_pairs(messages, display)
        if qa_pairs:
            for qa in qa_pairs:
                category_counts[qa["category"]] += 1
            all_qa_pairs.extend(qa_pairs)

            # 记录项目售后统计
            issue_categories = list(set(qa["category"] for qa in qa_pairs))
            chat_issue_stats.append({
                "chat_name": display,
                "project_code": project_code,
                "msg_count": cnt,
                "qa_count": len(qa_pairs),
                "categories": issue_categories,
            })
            all_issues.append({
                "chat_name": display,
                "project_code": project_code,
                "qa_pairs": qa_pairs,
            })

        if (idx + 1) % 50 == 0:
            print(f"  {idx+1}/{len(top_tables)} 已处理, 找到 {len(all_qa_pairs)} 个QA对...")

    conn_msg.close()

    # 加载谈单助手项目数据补充项目信息
    print("\n[3/4] 关联项目信息...")
    projects_map = {}
    tan_dan_projects = TAN_DAN_KB / "projects.json"
    if tan_dan_projects.exists():
        with open(tan_dan_projects, "r", encoding="utf-8") as f:
            tan_dan_data = json.load(f)
        for p in tan_dan_data:
            code = p.get("code", "")
            if code:
                projects_map[code] = {
                    "name": p.get("name", ""),
                    "category": p.get("category", ""),
                    "device_scheme": p.get("device_scheme", "")[:300],
                    "mcu": p.get("mcu", ""),
                    "sensors": p.get("sensors", []),
                }

    # 为每个售后问题补充项目信息
    for issue in all_issues:
        code = issue["project_code"]
        if code and code in projects_map:
            issue["project_info"] = projects_map[code]

    # 保存
    print("\n[4/4] 保存知识库文件...")

    with open(KB_DIR / "aftersales_faq.json", "w", encoding="utf-8") as f:
        json.dump(all_qa_pairs, f, ensure_ascii=False, indent=2)
    print(f"  售后FAQ: {KB_DIR / 'aftersales_faq.json'} ({len(all_qa_pairs)} 个QA对)")

    with open(KB_DIR / "aftersales_issues.json", "w", encoding="utf-8") as f:
        json.dump(all_issues, f, ensure_ascii=False, indent=2)
    print(f"  售后问题记录: {KB_DIR / 'aftersales_issues.json'} ({len(all_issues)} 个项目)")

    # 统计
    stats = {
        "total_qa_pairs": len(all_qa_pairs),
        "total_projects_with_issues": len(all_issues),
        "total_chats_analyzed": len(top_tables),
        "category_breakdown": dict(sorted(category_counts.items(), key=lambda x: x[1], reverse=True)),
        "top_issue_chats": sorted(
            [{"name": c["chat_name"], "qa_count": c["qa_count"], "project_code": c["project_code"]}
             for c in chat_issue_stats],
            key=lambda x: x["qa_count"], reverse=True
        )[:20],
    }

    with open(KB_DIR / "aftersales_stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"  统计报告: {KB_DIR / 'aftersales_stats.json'}")

    # 打印摘要
    print("\n" + "=" * 60)
    print("售后知识库构建完成!")
    print("=" * 60)
    print(f"\nQA问答对: {len(all_qa_pairs)} 个")
    print(f"涉及项目: {len(all_issues)} 个")
    print(f"\n问题类型分布:")
    for cat, count in stats["category_breakdown"].items():
        bar = "█" * (count // max(1, len(all_qa_pairs) // 30))
        print(f"  {cat}: {count} {bar}")
    print(f"\n知识库路径: {KB_DIR}")


if __name__ == "__main__":
    build_knowledge_base()
