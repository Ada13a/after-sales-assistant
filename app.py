"""
售后助手 - Web API + 企微回调 + 管理后台
启动: python app.py
访问: http://localhost:5051
"""
import json
import os
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

app = Flask(__name__, static_folder="web_ui")
CORS(app)

# 延迟初始化
bot_service = None
wecom_service = None


def get_bot():
    global bot_service
    if bot_service is None:
        from aftersales_bot import AfterSalesBot
        provider = os.getenv("LLM_PROVIDER", "deepseek")
        bot_service = AfterSalesBot(llm_provider=provider)
    return bot_service


def get_wecom():
    global wecom_service
    if wecom_service is None:
        from wecom_service import WeComService
        wecom_service = WeComService()
    return wecom_service


# ============================================================
# 售后 API 路由
# ============================================================
@app.route("/api/chat", methods=["POST"])
def chat():
    """发送售后消息，获取Bot回复"""
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "缺少 message 参数"}), 400

    customer_id = data.get("customer_id", "default")
    message = data["message"].strip()
    project_code = data.get("project_code", "")

    if not message:
        return jsonify({"error": "消息不能为空"}), 400

    bot = get_bot()
    result = bot.process(customer_id, message, project_code)

    return jsonify({
        "reply": result["text"],
        "intent": result["intent"],
        "confidence": result["confidence"],
        "stage": result["stage"],
        "faq_matches": result.get("faq_matches", 0),
        "project_code": result.get("project_code", ""),
        "escalation": result.get("escalation", False),
        "customer_id": customer_id,
    })


@app.route("/api/reset", methods=["POST"])
def reset():
    """重置对话"""
    data = request.get_json() or {}
    customer_id = data.get("customer_id", "default")
    bot = get_bot()
    bot.reset(customer_id)
    return jsonify({"status": "ok", "message": f"已重置 {customer_id} 的对话"})


@app.route("/api/state", methods=["GET"])
def get_state():
    """获取对话状态"""
    customer_id = request.args.get("customer_id", "default")
    bot = get_bot()
    state = bot.get_state(customer_id)
    if not state:
        return jsonify({"exists": False})
    return jsonify({"exists": True, **state})


@app.route("/api/search", methods=["GET"])
def search_faq():
    """搜索售后FAQ"""
    query = request.args.get("q", "")
    category = request.args.get("category", "")
    if not query:
        return jsonify({"error": "缺少 q 参数"}), 400

    bot = get_bot()
    results = bot.retriever.search(query, top_k=10, category=category or None)

    faqs = []
    for r in results:
        faqs.append({
            "category": r.get("category", ""),
            "question": r.get("question", ""),
            "answer": r.get("answer", ""),
            "chat_name": r.get("chat_name", ""),
        })

    return jsonify({"query": query, "count": len(faqs), "faqs": faqs})


@app.route("/api/project", methods=["GET"])
def get_project():
    """查询项目信息"""
    code = request.args.get("code", "")
    if not code:
        return jsonify({"error": "缺少 code 参数"}), 400

    bot = get_bot()
    proj = bot.projects.get_project(code)
    if not proj:
        return jsonify({"found": False, "code": code})

    history = bot.projects.get_aftersales_history(code)
    return jsonify({
        "found": True,
        "code": code,
        "name": proj.get("name", ""),
        "category": proj.get("category", ""),
        "mcu": proj.get("mcu", ""),
        "sensors": proj.get("sensors", []),
        "device_scheme": proj.get("device_scheme", "")[:300],
        "aftersales_history": [{
            "category": h.get("category", ""),
            "question": h.get("question", "")[:100],
            "answer": h.get("answer", "")[:100],
        } for h in history[:10]],
    })


@app.route("/api/aftersales/stats", methods=["GET"])
def get_aftersales_stats():
    """获取售后知识库统计"""
    stats_path = Path(__file__).parent / "knowledge_base" / "aftersales_stats.json"
    if stats_path.exists():
        with open(stats_path, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    return jsonify({"error": "stats not found"}), 404


@app.route("/api/health", methods=["GET"])
def health():
    bot = get_bot()
    return jsonify({
        "status": "ok",
        "faq_count": len(bot.kb.faq),
        "projects_count": len(bot.projects.projects),
        "active_conversations": len(bot.conversations),
    })


# ============================================================
# 企业微信回调路由
# ============================================================
@app.route("/wecom/callback", methods=["GET", "POST"])
def wecom_callback():
    """企业微信消息回调"""
    wc = get_wecom()

    if request.method == "GET":
        # URL验证
        msg_signature = request.args.get("msg_signature", "")
        timestamp = request.args.get("timestamp", "")
        nonce = request.args.get("nonce", "")
        echostr = request.args.get("echostr", "")

        code, result = wc.verify_url(msg_signature, timestamp, nonce, echostr)
        if code == 0:
            return result, 200, {"Content-Type": "text/plain; charset=utf-8"}
        return f"verify failed: {result}", 403

    elif request.method == "POST":
        # 消息接收
        xml_body = request.data.decode("utf-8")
        msg_signature = request.args.get("msg_signature", "")
        timestamp = request.args.get("timestamp", "")
        nonce = request.args.get("nonce", "")

        msg = wc.parse_message(msg_signature, timestamp, nonce, xml_body)
        if not msg:
            return "解析失败", 400

        # 只处理文本消息
        if msg.get("msg_type") != "text":
            return "", 200

        from_user = msg.get("from_user", "")
        content = msg.get("content", "")

        if not content:
            return "", 200

        # 调用Bot处理
        try:
            bot = get_bot()
            result = bot.process(from_user, content)
            reply_text = result["text"]
        except Exception as e:
            print(f"Bot处理错误: {e}")
            reply_text = "收到你的消息了，我稍后回复你~"

        # 构建回复
        reply_xml = wc.build_reply(
            to_user=from_user,
            from_user=msg.get("to_user", ""),
            content=reply_text
        )

        # 加密回复
        encrypted_xml = wc.encrypt_reply(reply_xml, nonce)
        return encrypted_xml, 200, {"Content-Type": "text/xml; charset=utf-8"}


# ============================================================
# Web 界面
# ============================================================
@app.route("/")
def index():
    return send_from_directory("web_ui", "chat.html")


@app.route("/chat")
def chat_page():
    return send_from_directory("web_ui", "chat.html")


@app.route("/admin")
def admin():
    return send_from_directory("web_ui", "admin.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("web_ui", path)


# ============================================================
# 启动
# ============================================================
if __name__ == "__main__":
    port = int(os.getenv("SERVER_PORT", 5051))
    print(f"\n{'='*50}")
    print(f"  售后助手 API 服务")
    print(f"  http://localhost:{port}")
    print(f"  对话测试: http://localhost:{port}/")
    print(f"  管理后台: http://localhost:{port}/admin")
    print(f"  企微回调: http://localhost:{port}/wecom/callback")
    print(f"{'='*50}\n")
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
