# 截屏翻译

Windows 10 桌面端 PyQt 截屏翻译小浮窗。

## 运行

```powershell
.\venv\Scripts\python.exe .\main.py
```

## `.env` 配置

应用通过 `python-dotenv` 读取项目根目录的 `.env`：

```dotenv
OPENAI_API_KEY=你的 API Key
OPENAI_API_BASE=https://你的 OpenAI 兼容地址
MODEL_NAME=支持图片输入的模型名
```

兼容变量：`OPENAI_BASE_URL`、`OPENAI_MODEL`。

## 功能

- 点击按钮或全局快捷键截取全屏。
- 点击按钮或全局快捷键截取屏幕选区。
- 使用 OpenAI Python SDK 调用兼容 Chat Completions 的视觉模型。
- 在设置中修改翻译提示词、全屏截图快捷键、选区截图快捷键。
- 翻译结果显示在聊天式浮窗中，并可手动编辑。
- 每轮结果分为“原文”和“翻译”两栏，均可手动编辑并写回历史。
- 支持完整重试，也支持基于当前原文只重试翻译。
- 支持多个翻译项目，每个项目有独立提示词和上下文。
- 非临时项目会保存到 `history/<项目名>/translations.json`，截图保存在对应项目的 `images/` 目录。
- “临时翻译”项目不会带入历史上下文，重启后会清空翻译记录。
- 浮窗拖到屏幕左右边界后会收缩成侧边栏，点击侧边栏可展开。

默认快捷键：

- 全屏截图：`Ctrl+Alt+F`
- 选区截图：`Ctrl+Alt+A`
