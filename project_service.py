"""
项目信息查询服务 - 查询项目方案、器件清单、售后记录
"""
import json
from pathlib import Path

KB_DIR = Path(__file__).parent / "knowledge_base"
# 优先使用本地知识库，谈单助手路径作为可选的外部源
TAN_DAN_KB = Path(r"F:/自媒体/智能体/谈单助手v2.0/谈单助手/knowledge_base")
if not (TAN_DAN_KB / "projects.json").exists():
    TAN_DAN_KB = KB_DIR  # fallback to local


class ProjectService:
    """项目信息查询"""

    def __init__(self):
        self.projects = {}  # code -> project info
        self.aftersales_issues = {}  # code -> after-sales issues
        self._load()

    def _load(self):
        # 加载谈单助手项目库
        projects_path = TAN_DAN_KB / "projects.json"
        if projects_path.exists():
            with open(projects_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for p in data:
                code = p.get("code", "")
                if code:
                    self.projects[code] = {
                        "name": p.get("name", ""),
                        "category": p.get("category", ""),
                        "price": p.get("price", ""),
                        "device_scheme": p.get("device_scheme", ""),
                        "function_scheme": p.get("function_scheme", ""),
                        "mcu": p.get("mcu", ""),
                        "sensors": p.get("sensors", []),
                        "actuators": p.get("actuators", []),
                        "comm_modules": p.get("comm_modules", []),
                    }
        print(f"项目信息加载: {len(self.projects)} 个项目")

        # 加载售后问题记录
        issues_path = KB_DIR / "aftersales_issues.json"
        if issues_path.exists():
            with open(issues_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for issue in data:
                code = issue.get("project_code", "")
                if code:
                    self.aftersales_issues[code] = issue
        print(f"售后记录加载: {len(self.aftersales_issues)} 个项目")

    def get_project(self, code: str) -> dict | None:
        """按项目代号查询"""
        # 精确匹配
        if code in self.projects:
            return self.projects[code]
        # 模糊匹配
        for k in self.projects:
            if code.upper() in k.upper():
                return self.projects[k]
        return None

    def search_project(self, keyword: str) -> list:
        """按关键词搜索项目"""
        results = []
        kw_lower = keyword.lower()
        for code, info in self.projects.items():
            text = f"{code} {info['name']} {info['device_scheme']}"
            if kw_lower in text.lower():
                results.append({"code": code, **info})
        return results[:10]

    def get_aftersales_history(self, code: str) -> list:
        """查询项目的售后历史"""
        issues = self.aftersales_issues.get(code)
        if issues:
            return issues.get("qa_pairs", [])
        return []

    def get_project_summary(self, code: str) -> str:
        """生成项目摘要（用于Bot上下文）"""
        proj = self.get_project(code)
        if not proj:
            return ""

        parts = [
            f"项目代号: {code}",
            f"项目名称: {proj['name']}",
            f"主控: {proj['mcu']}",
        ]
        if proj["sensors"]:
            parts.append(f"传感器: {', '.join(proj['sensors'][:8])}")
        if proj["actuators"]:
            parts.append(f"执行器: {', '.join(proj['actuators'][:5])}")
        if proj["comm_modules"]:
            parts.append(f"通信: {', '.join(proj['comm_modules'][:4])}")

        # 售后历史
        history = self.get_aftersales_history(code)
        if history:
            parts.append(f"\n历史售后问题({len(history)}条):")
            for qa in history[-3:]:  # 最近3条
                parts.append(f"  - [{qa['category']}] {qa['question'][:60]}")

        return "\n".join(parts)

    def get_common_issues_by_mcu(self, mcu: str) -> list:
        """根据MCU类型查找常见问题"""
        common = []
        for code, proj in self.projects.items():
            if mcu.lower() in proj.get("mcu", "").lower():
                issues = self.get_aftersales_history(code)
                if issues:
                    common.append({"code": code, "name": proj["name"], "issues": issues})
        return common[:5]


if __name__ == "__main__":
    ps = ProjectService()
    print("\n--- 项目查询测试 ---")
    p = ps.get_project("26Q0568")
    if p:
        print(f"找到: {p['name']} | MCU: {p['mcu']}")
        print(ps.get_project_summary("26Q0568"))
