# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

售后助手 (After-sales Assistant) — 专注于 MCU 毕设业务售后阶段的 AI 客服系统。通过企业微信官方 API 接入，自动解答客户的技术问题、使用指导和论文答辩支持。

基于谈单助手架构构建，复用了 LLM 服务层、BM25 检索器等技术组件。

## Architecture

```
Flask API (app.py)
  ├── /api/chat — 售后对话接口
  ├── /wecom/callback — 企业微信回调
  └── /admin — 管理后台

Bot Service (aftersales_bot.py)
  ├── IntentRecognizer (aftersales_engine.py)
  ├── FAQRetriever (aftersales_retriever.py)
  ├── ProjectService (project_service.py)
  └── LLMService (llm_service.py — copied from 谈单助手)

WeCom Integration (wecom_service.py)
  ├── Message encryption/decryption (AES + SHA1)
  └── XML message parsing/building
```

## Data Sources

| 用途 | 路径 |
|------|------|
| 微信解密 DB (消息) | `F:/sotfware shit/Weixin_file/xwechat_files/wxid_4ylmjumlahzd22_3c59/db_storage/message/message_0.decrypted.db` |
| 微信解密 DB (联系人) | `F:/sotfware shit/Weixin_file/xwechat_files/wxid_4ylmjumlahzd22_3c59/db_storage/contact/contact.decrypted.db` |
| 谈单助手知识库 | `d:/Agent_project/谈单助手/knowledge_base/` |
| 售后知识库 | `knowledge_base/` (本项目) |

## Key Dependencies

- Flask + Flask-CORS (Web API)
- OpenAI SDK (LLM client, compatible with DeepSeek API)
- PyCryptodome (WeCom message encryption)
- Python dotenv (environment config)

## Dev Notes

- Default LLM: DeepSeek V4 via OpenAI-compatible API
- Server runs on port 5051 (谈单助手 uses 5050)
- For WeCom callback testing, use ngrok or similar to expose local server
