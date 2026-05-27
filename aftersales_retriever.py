"""
售后 FAQ 检索引擎 - BM25 + 关键词匹配
"""
import json
import re
from pathlib import Path
from collections import defaultdict

KB_DIR = Path(__file__).parent / "knowledge_base"


class FAQKnowledgeBase:
    """售后知识库加载与管理"""

    def __init__(self):
        self.faq = []          # Q&A 问答对
        self.issues = []       # 按项目分类的售后记录
        self.stats = {}        # 统计数据

        self._load()

        # 构建检索索引
        self._faq_search_texts = []
        self._build_faq_index()

    def _load(self):
        for name, attr in [("aftersales_faq.json", "faq"),
                            ("aftersales_issues.json", "issues"),
                            ("aftersales_stats.json", "stats")]:
            path = KB_DIR / name
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    setattr(self, attr, json.load(f))
        print(f"售后知识库加载: {len(self.faq)} FAQ, {len(self.issues)} 项目")

    def _build_faq_index(self):
        for qa in self.faq:
            text = f"{qa.get('category','')} {qa.get('question','')} {qa.get('answer','')}"
            self._faq_search_texts.append(text)

    def get_issues_by_project(self, project_code: str) -> list:
        for issue in self.issues:
            if issue.get("project_code") == project_code:
                return issue.get("qa_pairs", [])
        return []

    def get_category_faqs(self, category: str) -> list:
        return [qa for qa in self.faq if qa.get("category") == category]


class FAQRetriever:
    """FAQ 检索引擎 - 轻量 BM25 + 关键词匹配"""

    def __init__(self, kb: FAQKnowledgeBase):
        self.kb = kb
        self.k1 = 1.5
        self.b = 0.75

        # 构建文档
        self.docs = list(kb._faq_search_texts)
        self._tokenize_docs()
        self._compute_idf()

    def _tokenize(self, text):
        """中文分词（简单2-gram + 关键词）"""
        tokens = []

        # 中文2-gram
        chinese = re.findall(r'[一-鿿]{2,}', text)
        for w in chinese:
            for i in range(len(w) - 1):
                tokens.append(w[i:i + 2])
            tokens.append(w)

        # 英文/数字词
        eng = re.findall(r'[a-zA-Z0-9]+', text)
        tokens.extend(eng)

        # 技术关键词
        keywords = re.findall(
            r'(STM32\w*|ESP32|Arduino|DHT11|DS18B20|BH1750|OLED|LCD|TFT|'
            r'MQ-\d+|HC-05|ESP8266|GPS|WiFi|蓝牙|4G|LoRa|舵机|步进电机|继电器|'
            r'Keil|IAR|CubeIDE|编译|烧录|接线|论文|答辩|查重|降重|快递|发货)',
            text, re.IGNORECASE
        )
        tokens.extend(keywords)

        return [t.lower() for t in tokens]

    def _tokenize_docs(self):
        self.doc_tokens = []
        doc_lengths = []
        for text in self.docs:
            tokens = self._tokenize(text)
            self.doc_tokens.append(tokens)
            doc_lengths.append(len(tokens))
        self.avg_dl = sum(doc_lengths) / max(len(doc_lengths), 1)
        self.doc_lengths = doc_lengths

    def _compute_idf(self):
        N = len(self.doc_tokens)
        df = defaultdict(int)
        for tokens in self.doc_tokens:
            for token in set(tokens):
                df[token] += 1
        self.idf = {}
        for token, freq in df.items():
            self.idf[token] = max(0, __import__('math').log((N - freq + 0.5) / (freq + 0.5) + 1))

    def search(self, query, top_k=5, category=None):
        """搜索最匹配的FAQ

        Args:
            query: 用户消息
            top_k: 返回条数
            category: 可选，限定问题分类
        """
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores = []
        for i, doc_tokens in enumerate(self.doc_tokens):
            # 如果指定了分类，只搜索该分类
            if category and i < len(self.kb.faq):
                if self.kb.faq[i].get("category") != category:
                    continue

            score = 0
            doc_len = self.doc_lengths[i]
            tf = defaultdict(int)
            for t in doc_tokens:
                tf[t] += 1

            for qt in query_tokens:
                if qt in self.idf:
                    idf = self.idf[qt]
                    f = tf.get(qt, 0)
                    numerator = f * (self.k1 + 1)
                    denominator = f + self.k1 * (1 - self.b + self.b * doc_len / self.avg_dl)
                    score += idf * numerator / max(denominator, 0.001)

            if score > 0:
                scores.append((score, i))

        scores.sort(key=lambda x: x[0], reverse=True)
        results = []
        for _, idx in scores[:top_k]:
            if idx < len(self.kb.faq):
                results.append(self.kb.faq[idx])
        return results

    def search_exact(self, query, top_k=3):
        """精确关键词匹配（用于快速查找）"""
        query_lower = query.lower()
        results = []

        for i, qa in enumerate(self.kb.faq):
            q_text = qa.get("question", "").lower()
            # 提取关键术语
            terms = re.findall(r'[a-zA-Z0-9一-鿿]{2,}', query_lower)
            matches = sum(1 for t in terms if t in q_text)
            if matches >= 2:
                results.append((matches, i))

        results.sort(key=lambda x: x[0], reverse=True)
        return [self.kb.faq[idx] for _, idx in results[:top_k]]


if __name__ == "__main__":
    kb = FAQKnowledgeBase()
    retriever = FAQRetriever(kb)

    queries = [
        "代码编译报错 undefined reference",
        "OLED屏幕不显示",
        "论文查重率太高了怎么办",
        "答辩老师一般问什么问题",
    ]
    for q in queries:
        print(f"\n查询: {q}")
        results = retriever.search(q, top_k=3)
        for r in results:
            print(f"  [{r['category']}] Q: {r['question'][:80]}")
            print(f"    A: {r['answer'][:120]}")
