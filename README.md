# Screen Translator

Windows 10 桌面端截图翻译工具，使用 Python 3.10、PyQt5 和 openai API框架 实现。

应用以一个小型悬浮窗运行，支持截图、图片导入、项目历史、上下文翻译、快捷键和运行时模型配置。

## 功能

- 全屏截图翻译：点击按钮或使用全局快捷键截取全屏。
- 选区截图翻译：点击按钮或使用全局快捷键框选屏幕区域。
- 剪贴板图片导入：每个项目底部有一个加号方框，可读取剪贴板中的网页图片链接、`data:image/...;base64,...` 图片内容，并自动识别翻译。
- 大模型调用：通过 `openai` Python SDK 调用支持图片输入的 Chat Completions 兼容模型。
- `.env` 实时配置：设置界面可直接查看和编辑 `.env` 内容，保存后下一次请求生效。
- 自定义提示词：支持全局默认提示词，也支持每个项目单独设置项目提示词。
- 原文/译文双栏：每轮翻译显示截图、模型识别出的原文和翻译结果，两栏都可以手动修改。
- 重试：支持重试完整 OCR+翻译流程。
- 重试翻译：基于当前可编辑的原文，只重新生成译文。
- 删除最后一轮：可删除当前项目最后一轮截图及翻译结果。
- 项目历史：非临时项目会保存截图和翻译历史，并在后续翻译中作为上下文。
- 临时翻译：临时项目不保存历史，也不带入项目上下文。
- 模型测试：设置界面可发送“你好”测试当前模型配置。
- 关闭思考模式：可在设置中勾选，发送大模型请求时会关闭思考推理模式。
- 收起/唤起：顶部“收起”按钮会最小化到任务栏；对应快捷键可在最小化和唤起之间切换。

默认快捷键：

- 全屏截图：`Ctrl+Alt+F`
- 选区截图：`Ctrl+Alt+A`
- 收起/唤起：`Ctrl+Alt+S`

这些快捷键都可以在设置界面中修改。

## 环境要求

- Windows 10 或更新版本
- Python 3.10
- 一个支持图片输入的 OpenAI-compatible Chat Completions 模型

建议使用项目内虚拟环境：

```powershell
py -3.10 -m venv venv
.\venv\Scripts\activate
```

## 安装依赖

运行应用所需依赖：

```powershell
.\venv\Scripts\python.exe -m pip install PyQt5 openai python-dotenv httpx
```

打包 exe 还需要：

```powershell
.\venv\Scripts\python.exe -m pip install pyinstaller
```

当前项目主要使用的第三方库：

- `PyQt5`：桌面 UI、截图、选区窗口、全局事件处理。
- `openai`：调用 OpenAI-compatible Chat Completions API。
- `python-dotenv`：读取 `.env` 中的模型配置。
- `httpx`：OpenAI SDK 的 HTTP 依赖。
- `pyinstaller`：构建 Windows `.exe`。

## 模型配置

在项目根目录创建 `.env`：

```dotenv
OPENAI_API_KEY=你的 API Key
OPENAI_API_BASE=https://你的 OpenAI 兼容接口地址
MODEL_NAME=支持图片输入的模型名
```

## 源码运行

```powershell
.\venv\Scripts\python.exe .\main.py
```

如果全局快捷键注册失败，通常是快捷键已被其他程序占用，可以在设置界面修改。

## 打包为 exe

项目根目录提供：

- `screen_translator.spec`
- `build_exe.ps1`
- `logo.jpg`

`logo.jpg` 会用于生成 exe 图标，并作为运行时窗口图标资源打包。

先安装 PyInstaller：

```powershell
.\venv\Scripts\python.exe -m pip install pyinstaller
```

然后执行：

```powershell
.\build_exe.ps1
```

构建产物：

```text
dist/
  ScreenTranslator.exe
  .env.example
```

源码运行时，程序读取项目根目录的 `.env`。打包为 exe 后，程序读取 `ScreenTranslator.exe` 同级目录的 `.env`。构建脚本不会复制或打包你的本地 `.env`，只会生成不含密钥的 `.env.example` 模板。

构建脚本会在打包前后清理以下敏感或本地运行数据，避免误分发：

- `dist/.env`
- `dist/config.json`
- `dist/history/`

## 使用方法

1. 启动程序。
2. 点击“设置”，填写或确认 `.env`、默认提示词和快捷键。
3. 可点击“测试模型”确认 API 配置是否可用。
4. 点击“全屏”或“选区”，或使用快捷键进行截图翻译。
5. 也可以复制图片链接/base64 图片内容后，点击项目底部的加号方框导入翻译。
6. 翻译完成后，可直接编辑原文和译文。
7. 如结果不理想，可点击“重试”或“重试翻译”。
8. 点击“收起”可最小化到任务栏；使用收起/唤起快捷键可快速恢复窗口。

## 数据存储

源码运行时，本地数据位于项目根目录：

```text
.env
config.json
history/
```

打包运行时，本地数据位于 exe 同级目录：

```text
ScreenTranslator.exe
.env
config.json
history/
```

项目历史结构：

```text
history/<项目名>/
  translations.json
  images/
    round_1.png
    round_2.png
```

`translations.json` 中第 `0` 轮用于保存项目提示词，后续轮次保存图片路径、原文和译文。

## 项目架构

```text
main.py
screen_translator/
  config.py
  capture.py
  hotkeys.py
  projects.py
  translator.py
  ui.py
```

主要模块：

- `main.py`：应用入口，调用 `screen_translator.ui.run_app()`。
- `screen_translator/ui.py`：主窗口、设置窗口、项目列表、聊天气泡、剪贴板导入、任务栏最小化/恢复、按钮和快捷键入口。
- `screen_translator/capture.py`：多显示器虚拟桌面截图、全屏捕获、屏幕选区窗口。
- `screen_translator/hotkeys.py`：基于 Windows `RegisterHotKey` 的全局快捷键注册和分发。
- `screen_translator/translator.py`：OpenAI-compatible API 调用、图片转 data URL、模型测试、完整翻译和仅翻译重试。
- `screen_translator/projects.py`：翻译项目、历史 JSON、截图图片保存、项目增删改。
- `screen_translator/config.py`：应用配置、`.env` 读写路径、源码/打包运行目录判断。

核心流程：

1. UI 触发截图或剪贴板导入，得到 `QPixmap`。
2. `ProjectStore.add_record()` 保存当前轮次和图片。
3. `Translator.translate()` 在线程池中调用模型。
4. 模型返回 JSON：`{"original_text": "...", "translation": "..."}`。
5. UI 更新原文/译文两栏，并写回项目历史。
6. 后续翻译会读取同一项目历史作为上下文。

## 注意事项

- `.env`、`config.json`、`history/`、`venv/`、`dist/` 和 `build/` 不应提交到仓库。
- 模型必须支持图片输入，否则截图翻译会失败。
- 如果使用的兼容模型不支持 `extra_body.thinking`，请不要勾选“关闭思考模式”。
- 自动化测试或烟测一般不应真实调用模型 API，以免消耗额度。
- PowerShell 控制台可能会把中文显示成乱码；源码文件本身使用 UTF-8。
