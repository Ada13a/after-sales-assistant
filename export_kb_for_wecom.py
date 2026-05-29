"""导出清洗后的知识库为企微可用的文档"""
import json, re
from collections import defaultdict

with open(r'F:/自媒体/智能体/售后助手/knowledge_base/aftersales_faq.json', 'r', encoding='utf-8') as f:
    faqs = json.load(f)

def clean_text(text):
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'wxid_[a-z0-9]+:', '', text)
    text = re.sub(r'\d{15,}@\w+:', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text if len(text) >= 5 else ''

by_category = defaultdict(list)
for qa in faqs:
    cat = qa.get('category', '其他咨询')
    q = clean_text(qa.get('question', ''))
    a = clean_text(qa.get('answer', ''))
    if q and a and len(q) > 5 and len(a) > 10:
        by_category[cat].append((q, a))

cat_names = {
    '代码问题': '代码编译烧录问题',
    '论文问题': '论文查重降重问题',
    '硬件问题': '硬件故障排查问题',
    '使用指导': '使用指导接线调试',
    '答辩支持': '答辩准备PPT指导',
    '器件采购': '器件采购BOM清单',
    '功能修改': '功能修改定制需求',
    '物流跟踪': '物流发货快递',
    '其他咨询': '其他售后咨询',
}

output_path = r'F:/自媒体/智能体/售后助手/knowledge_base/企微知识库.txt'
with open(output_path, 'w', encoding='utf-8') as f:
    for cat, cat_display in cat_names.items():
        items = by_category.get(cat, [])
        if not items:
            continue

        seen = set()
        unique_items = []
        for q, a in items:
            key = q[:60]
            if key not in seen and len(a) > 10:
                seen.add(key)
                unique_items.append((q, a))

        unique_items.sort(key=lambda x: len(x[1]), reverse=True)
        unique_items = unique_items[:200]

        f.write(f'# {cat_display}\n\n')
        for i, (q, a) in enumerate(unique_items, 1):
            f.write(f'## 问题{i}: {q[:300]}\n')
            f.write(f'回答: {a[:600]}\n\n')
        f.write('\n---\n\n')

print(f'Generated: {output_path}')
total = sum(len(v) for v in by_category.values())
print(f'Total cleaned Q&A: {total}')
for cat, items in sorted(by_category.items(), key=lambda x: len(x[1]), reverse=True):
    print(f'  {cat}: {len(items)}')
