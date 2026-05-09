from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_DIR / "config.json"


DEFAULT_PROMPT = (
    "你是专业截图翻译助手。请识别截图中的文字，并将其翻译为简体中文。"
    "保持原文含义，必要时保留专有名词；只输出翻译结果，不要解释过程。"
)


@dataclass
class AppConfig:
    full_screen_hotkey: str = "Ctrl+Alt+F"
    region_hotkey: str = "Ctrl+Alt+A"
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
