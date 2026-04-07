# CS2饰品价格监控工具

一个基于SteamDT开放平台API的CS2（Counter-Strike 2）饰品价格监控工具，支持三重指标监控（价格、在售数量、求购数量）并通过飞书机器人发送通知。

## ✨ 功能特性

- 📈 **三重指标监控**：同时监控饰品的价格、在售数量、求购数量
- 🔔 **飞书通知**：指标变动超过阈值时自动发送飞书通知
- 📊 **数据持久化**：保存历史数据，支持趋势分析
- 🌐 **API优先**：优先使用SteamDT开放平台API，支持网页爬取作为备用方案
- ⚙️ **灵活配置**：可自定义监控间隔、阈值和通知方式
- 🛡️ **安全机制**：支持飞书机器人签名验证

## 🚀 快速开始

### 环境要求

- Python 3.6+
- requests 库

### 安装依赖

```bash
pip install requests
```

### 配置说明

1. 复制代码并保存为 `share.py`
2. 配置文件中的关键参数：

```python
# SteamDT API KEY（必填）
STEAMDT_API_KEY = 'your_api_key_here'

# 饰品配置
ITEMS_TO_MONITOR = [
    {
        'name': 'M4A1-S | Guardian (Factory New)',
        'market_hash_name': 'M4A1-S | Guardian (Factory New)',
        'url': 'https://steamdt.com/cs2/M4A1-S%20%7C%20Guardian%20(Factory%20New)',
        'platform': 'YOUPIN'  # UU平台
    } 
]

# 飞书机器人配置
FEISHU_WEBHOOK = 'your_webhook_url_here'
FEISHU_SECRET = 'your_secret_here'
```

### 获取API密钥

1. 访问 [SteamDT开放平台](https://open.steamdt.com)
2. 注册账号并创建应用
3. 获取API密钥

### 获取飞书机器人配置

1. 在飞书群聊中添加机器人
2. 获取Webhook地址和签名密钥（可选）

## 📖 使用方法

### 运行监控

```bash
python share.py
```

### 测试API连接

```bash
python share.py --test
```

### 测试飞书机器人

```bash
python share.py --test-feishu
```

## ⚙️ 配置参数说明

### 监控设置

```python
# 监控间隔（秒）
CHECK_INTERVAL = 10 * 60  # 10分钟

# 三重阈值配置
THRESHOLDS = {
    'price': 0.01,        # 价格波动阈值（1%）
    'sell_count': 0.03,   # 在售数量波动阈值（3%）
    'bidding_count': 0.03 # 求购数量波动阈值（3%）
}
```

### 支持的平台

- `YOUPIN` - UU平台
- `STEAM` - Steam官方市场

## 📊 数据文件

程序会生成以下数据文件：

- `his_price_Guardian.json` - 价格历史数据
- `api_Guardian.json` - API调用统计信息

## 🛡️ 安全建议

1. **不要在代码中硬编码API密钥**：建议使用环境变量或配置文件
2. **保护数据文件**：确保数据文件不会被意外提交到版本控制
3. **定期更新依赖**：保持Python库的最新版本

## 🤝 贡献

欢迎提交Issue和Pull Request！

## 📄 许可证

MIT License

## 🙏 致谢

- [SteamDT开放平台](https://open.steamdt.com) - 提供API支持
- [飞书开放平台](https://open.feishu.cn) - 提供机器人通知服务

---

**注意**：请合理使用API，遵守SteamDT平台的使用条款。
