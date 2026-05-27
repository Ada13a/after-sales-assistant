# 企微聊天记录提取工具

## 使用说明

### 前提条件
1. 已安装 Python 3.x
2. 企业微信客户端**已登录并正在运行**
3. Windows 系统

### 使用方法

#### 一键运行（推荐）
右键 `run_all.bat` → **以管理员身份运行**

#### 分步运行
```bash
# 安装依赖
pip install psutil pymem pycryptodome zstandard

# 步骤1: 扫描密钥（需要管理员权限）
python scan_key.py

# 步骤2: 解密数据库
python decrypt_db.py --all

# 步骤3: 提取消息
python extract_messages.py
```

### 输出
- `found_keys.json` / `found_keys.txt` — 提取的数据库密钥
- `*.decrypted.db` — 解密后的数据库文件
- `output/` — 导出的聊天记录（每个会话一个 .txt）
- `output/_index.txt` — 会话索引

### 打包回传
完成后，将**整个 wecom_extract_tool 文件夹**打包（zip），传回开发环境。

### 故障排除

**"未找到 WXWork.exe 进程"**
→ 确保企业微信已登录且正在运行

**"未找到候选密钥"**
→ 关闭并重新打开企业微信，确保有活跃的聊天窗口

**权限不足**
→ 右键以管理员身份运行

**数据库文件不存在**
→ 手动查找企微数据目录，通常在：
- `C:\Users\<用户名>\Documents\WXWork\`
- 或在企微客户端 → 设置 → 文件管理 中查看路径
