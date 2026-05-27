"""
售后 Bot 服务层 - 组合意图识别 + FAQ检索 + 项目查询 + LLM生成回复
"""
import re
from pathlib import Path
from aftersales_engine import IntentRecognizer, AfterSalesState, extract_tech_info, INTENT_GUIDANCE
from aftersales_retriever import FAQKnowledgeBase, FAQRetriever
from project_service import ProjectService
from llm_service import LLMService

# 加载 System Prompt
PROMPT_PATH = Path(__file__).parent / "aftersales_system_prompt.md"
SYSTEM_PROMPT = ""
if PROMPT_PATH.exists():
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        SYSTEM_PROMPT = f.read()


class AfterSalesBot:
    """售后Bot完整服务"""

    def __init__(self, llm_provider: str = "deepseek"):
        print(f"启动售后服务 (LLM: {llm_provider})...")
        self.kb = FAQKnowledgeBase()
        self.retriever = FAQRetriever(self.kb)
        self.projects = ProjectService()
        self.llm = LLMService(provider=llm_provider)
        self.intent_recognizer = IntentRecognizer()
        self.conversations: dict[str, AfterSalesState] = {}

    def process(self, customer_id: str, message: str, project_code: str = "") -> dict:
        """处理客户售后消息"""
        # 获取或创建会话状态
        if customer_id not in self.conversations:
            self.conversations[customer_id] = AfterSalesState(customer_id=customer_id)
        state = self.conversations[customer_id]

        state.history.append({"role": "customer", "text": message})

        # 如果用户提供了项目代号，记录它
        if project_code:
            state.project_code = project_code

        # 尝试从消息中提取项目代号
        if not state.project_code:
            code_match = re.search(r'(26[A-Z]\d{4})', message)
            if code_match:
                state.project_code = code_match.group(1)

        # 1. 意图识别
        intent_result = self.intent_recognizer.recognize(message)
        intent = intent_result["intent"]
        state.issue_category = intent

        # 2. 提取技术信息
        tech_info = extract_tech_info(message)

        # 3. 检索相关FAQ
        faq_results = self.retriever.search(message, top_k=5, category=intent)
        # 同时做精确匹配
        exact_results = self.retriever.search_exact(message, top_k=3)

        # 4. 项目信息
        project_context = ""
        if state.project_code:
            project_context = self.projects.get_project_summary(state.project_code)

        # 5. 构建Prompt
        prompt_messages = self._build_prompt(
            state, message, intent, tech_info, faq_results, exact_results, project_context
        )

        # 6. LLM生成回复
        reply_text = self.llm.chat(prompt_messages)

        # 7. 检测是否需要升级
        self._check_escalation(state, message, intent)

        state.history.append({"role": "bot", "text": reply_text})

        return {
            "text": reply_text,
            "intent": intent,
            "confidence": intent_result.get("confidence", 0),
            "stage": state.stage,
            "faq_matches": len(faq_results),
            "project_code": state.project_code,
            "escalation": state.escalation_needed,
        }

    def _build_prompt(self, state: AfterSalesState, message: str,
                       intent: str, tech_info: dict, faq_results: list,
                       exact_results: list, project_context: str) -> list:
        """构建LLM Prompt消息"""

        # 上下文信息
        context_parts = []

        # 项目信息
        if project_context:
            context_parts.append(f"## 关联项目\n{project_context}")

        # 技术信息
        tech_parts = []
        if tech_info.get("mcu"):
            tech_parts.append(f"主控: {tech_info['mcu']}")
        if tech_info.get("sensors"):
            tech_parts.append(f"传感器: {', '.join(tech_info['sensors'][:5])}")
        if tech_info.get("tools"):
            tech_parts.append(f"工具/环境: {', '.join(tech_info['tools'][:3])}")
        if tech_parts:
            context_parts.append(f"## 技术信息\n" + "\n".join(tech_parts))

        # 相关FAQ（内部参考）
        if faq_results:
            context_parts.append(f"\n## 相关FAQ（供参考，不要直接复制）")
            for faq in faq_results[:3]:
                context_parts.append(f"- Q: {faq['question'][:100]}")
                context_parts.append(f"  A: {faq['answer'][:150]}")

        # 精确匹配的历史方案
        if exact_results:
            context_parts.append(f"\n## 高度匹配的历史解决方案")
            for faq in exact_results[:2]:
                context_parts.append(f"- {faq['question'][:80]}")
                context_parts.append(f"  解决: {faq['answer'][:120]}")

        # 当前状态
        context_parts.append(f"\n## 当前状态")
        context_parts.append(f"- 意图: {intent}")
        context_parts.append(f"- 对话阶段: {state.stage}")
        if state.diagnosis:
            context_parts.append(f"- 排查记录: {state.diagnosis[:200]}")

        context = "\n".join(context_parts)

        # 意图指引
        guidance = INTENT_GUIDANCE.get(intent, INTENT_GUIDANCE["其他咨询"])

        # 构建完整的 system prompt
        system_content = f"""{SYSTEM_PROMPT}

---
## 当前上下文
{context}

## 这次回复的指引
{guidance}

## 回复要求
1. 耐心解答，引导用户提供足够信息
2. 先给排查思路，再给具体方案
3. 语气轻松自然，像学长帮助学弟学妹
4. 2-5句话为主，需要详细说明时分步骤列出
5. 禁用markdown，禁用emoji，像微信聊天
6. 常见问题参考FAQ但用自己的话重新组织
7. 涉及返修/补发等需要人工处理的，明确告诉用户下一步"""

        messages = [{"role": "system", "content": system_content}]

        # 最近对话历史（最多8轮）
        recent = state.history[-16:]
        for h in recent:
            role = "assistant" if h["role"] == "bot" else "user"
            messages.append({"role": role, "content": h["text"]})

        return messages

    def _check_escalation(self, state: AfterSalesState, message: str, intent: str):
        """检测是否需要升级人工处理"""
        escalation_signals = [
            r"(退货|退款|投诉|差评|举报|曝光)",
            r"(找.*负责|找.*老板|找.*领导|投诉.*你)",
            r"(骗|坑|假|忽悠|不.*理|一直.*不回)",
            r"(已经.*(3|三|5|五)天|一个星期|很久|一直).*(没|不|还没)",
        ]
        for pat in escalation_signals:
            if re.search(pat, message):
                state.escalation_needed = True
                state.stage = "escalated"
                return

    def reset(self, customer_id: str):
        """重置对话"""
        if customer_id in self.conversations:
            del self.conversations[customer_id]

    def get_state(self, customer_id: str) -> dict | None:
        """获取对话状态"""
        state = self.conversations.get(customer_id)
        if not state:
            return None
        return {
            "customer_id": state.customer_id,
            "stage": state.stage,
            "issue_category": state.issue_category,
            "project_code": state.project_code,
            "escalation_needed": state.escalation_needed,
            "history_count": len(state.history),
        }


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    bot = AfterSalesBot(llm_provider="deepseek")

    test_msgs = [
        "学长 代码编译报错了 main.c(32): error: #20: identifier 'DHT11_PIN' is undefined",
        "板子插电没反应 屏幕也不亮",
        "论文查重率35% 学校要求20%以下 怎么办",
        "快递单号是多少 地址要改",
    ]

    for msg in test_msgs:
        result = bot.process("test_user", msg)
        print(f"\n客户: {msg[:80]}")
        print(f"意图: {result['intent']} | FAQ匹配: {result['faq_matches']}")
        print(f"Bot: {result['text'][:300]}")
