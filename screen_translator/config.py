from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_DIR = _app_dir()
CONFIG_PATH = APP_DIR / "config.json"
ENV_PATH = APP_DIR / ".env"


DEFAULT_PROMPT = (
    "你是专业截图翻译助手。请识别截图中的文字，并将其翻译为简体中文。"
    "保持原文含义，必要时保留专有名词；只输出翻译结果，不要解释过程。"
)


@dataclass
class AppConfig:
    full_screen_hotkey: str = "Ctrl+Alt+F"
    region_hotkey: str = "Ctrl+Alt+A"
    collapse_hotkey: str = "Ctrl+Alt+S"
    disable_thinking: bool = False
    prompt: str = DEFAULT_PROMPT
    temp_prompt: str = DEFAULT_PROMPT
    selected_project_id: str = "__temporary__"
    window_width: int = 430
    window_height: int = 620


def load_config() -> AppConfig:
    if not CONFIG_PATH.exists():
        return AppConfig()

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppConfig()

    defaults = asdict(AppConfig())
    defaults.update({key: value for key, value in data.items() if key in defaults})
    return AppConfig(**defaults)


def save_config(config: AppConfig) -> None:
    CONFIG_PATH.write_text(
        json.dumps(asdict(config), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_env_text() -> str:
    if not ENV_PATH.exists():
        return "OPENAI_API_KEY=\nOPENAI_API_BASE=\nMODEL_NAME=\n"
    return ENV_PATH.read_text(encoding="utf-8")


def save_env_text(text: str) -> None:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized and not normalized.endswith("\n"):
        normalized += "\n"
    ENV_PATH.write_text(normalized, encoding="utf-8")
