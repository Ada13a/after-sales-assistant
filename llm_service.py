"""
LLM服务层 - 支持多模型切换
默认: DeepSeek (OpenAI兼容接口)
可选: Claude, OpenAI GPT, 通义千问
"""
import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ============================================================
# 模型配置
# ============================================================
MODEL_CONFIGS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-pro",
        "api_key_env": "DEEPSEEK_API_KEY",
        "max_tokens": 2048,
        "temperature": 0.7,
    },
    "deepseek-reasoner": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-reasoner",
        "api_key_env": "DEEPSEEK_API_KEY",
        "max_tokens": 4096,
        "temperature": 0.7,
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "api_key_env": "OPENAI_API_KEY",
        "max_tokens": 2048,
        "temperature": 0.7,
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-6",
        "api_key_env": "ANTHROPIC_API_KEY",
        "max_tokens": 2048,
        "temperature": 0.7,
    },
}


class LLMService:
    """多模型LLM服务"""

    def __init__(self, provider: str = "deepseek"):
        self.provider = provider
        self.config = MODEL_CONFIGS.get(provider, MODEL_CONFIGS["deepseek"])
        self.api_key = os.getenv(self.config["api_key_env"], "")
        self.client = None

        if not self.api_key:
            print(f"[LLM] 警告: {self.config['api_key_env']} 未设置，将使用模拟模式")
            return

        if provider in ("deepseek", "deepseek-reasoner", "openai"):
            from openai import OpenAI
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.config["base_url"],
            )
        elif provider == "anthropic":
            import anthropic
            self.client = anthropic.Anthropic(api_key=self.api_key)

    def chat(self, messages: list, **kwargs) -> str:
        """发送对话请求"""
        if not self.client:
            return self._mock_reply(messages)

        model = kwargs.get("model", self.config["model"])
        max_tokens = kwargs.get("max_tokens", self.config["max_tokens"])
        temperature = kwargs.get("temperature", self.config["temperature"])

        try:
            if self.provider == "anthropic":
                # Anthropic API格式不同
                system_msg = ""
                user_messages = []
                for m in messages:
                    if m["role"] == "system":
                        system_msg = m["content"]
                    else:
                        user_messages.append(m)

                response = self.client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system_msg,
                    messages=user_messages,
                    temperature=temperature,
                )
                return response.content[0].text
            else:
                # OpenAI兼容接口 (DeepSeek, OpenAI, etc.)
                response = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return response.choices[0].message.content

        except Exception as e:
            print(f"[LLM] API错误: {e}")
            return self._mock_reply(messages)

    def _mock_reply(self, messages: list) -> str:
        """模拟回复（无API Key时使用）"""
        last_msg = messages[-1]["content"] if messages else ""
        return self._generate_rule_based_reply(last_msg)

    def _generate_rule_based_reply(self, message: str) -> str:
        """基于规则的模拟回复"""
        msg_lower = message.lower()

        if any(w in msg_lower for w in ["多少钱", "价格", "报价", "收费"]):
            return "这个方案半套报价1000-1300左右，定金300。具体要看您需要的功能复杂度，方便的话发一下详细需求~"

        if any(w in msg_lower for w in ["便宜", "优惠", "少点", "贵"]):
            return "价格是根据难度评估的，包含所有器件和人工费，包售后到答辩结束，很实在了。"

        if any(w in msg_lower for w in ["多久", "周期", "几天", "加急"]):
            return "正常10个工作日，加急+300压缩到3-4天。您什么时间前需要？"

        if any(w in msg_lower for w in ["下单", "付款", "定金", "链接"]):
            return "下单链接：https://www.liangjiedaming.top/ 复制到浏览器打开，微信限额用支付宝，截图发我~"

        if any(w in msg_lower for w in ["发货", "快递", "尾款"]):
            return "同学您好，验收视频确认后付尾款，我这边安排发货。视频链接：https://data1.liangjiedaming.top/"

        if any(w in msg_lower for w in ["stm32", "esp32", "传感器", "dht11", "ds18b20"]):
            return "收到，这个方案可以做。半套包含实物+代码+原理图+PCB+演示视频+售后，具体价格要看器件清单，您把完整需求发我评估一下~"

        return "收到~ 方便的话把您的具体功能需求发我，我给您评估一下价格和周期。"
