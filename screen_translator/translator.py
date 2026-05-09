from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

import httpx
from dotenv import load_dotenv
from openai import OpenAI
from PyQt5.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot

from .config import ENV_PATH


def pixmap_to_png_data_url(pixmap) -> str:
    from PyQt5.QtCore import QByteArray, QBuffer, QIODevice

    byte_array = QByteArray()
    buffer = QBuffer(byte_array)
    buffer.open(QIODevice.WriteOnly)
    pixmap.save(buffer, "PNG")
    payload = bytes(byte_array)
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _debug_print_api_payload(model: str, messages: list[dict[str, Any]], pixmap) -> None:
    printable_messages = json.loads(json.dumps(messages, ensure_ascii=False))
    for message in printable_messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            image_url = part.get("image_url", {}).get("url", "")
            part["image_url"] = {
                "url_prefix": image_url[:80],
                "url_length": len(image_url),
                "pixmap_size": f"{pixmap.width()}x{pixmap.height()}",
            }

    print("\n=== LLM REQUEST MODEL ===", flush=True)
    print(model, flush=True)
    print("=== LLM REQUEST MESSAGES ===", flush=True)
    print(json.dumps(printable_messages, ensure_ascii=False, indent=2), flush=True)


def _debug_print_api_response(response) -> None:
    print("=== LLM RAW RESPONSE ===", flush=True)
    try:
        print(response.model_dump_json(indent=2), flush=True)
    except AttributeError:
        print(response, flush=True)

    try:
        content = response.choices[0].message.content or ""
    except (AttributeError, IndexError):
        content = ""
    print("=== LLM MESSAGE CONTENT ===", flush=True)
    print(content, flush=True)


class TranslationSignals(QObject):
    started = pyqtSignal()
    finished = pyqtSignal(str, str)
    failed = pyqtSignal(str)


class ModelTestSignals(QObject):
    started = pyqtSignal()
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)


def make_openai_client(timeout: float = 60.0) -> tuple[OpenAI, str]:
    load_dotenv(dotenv_path=ENV_PATH, override=True)
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_API_BASE") or os.getenv("OPENAI_BASE_URL")
    model = os.getenv("MODEL_NAME") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"

    if not api_key:
        raise RuntimeError("在 .env 中找不到 OPENAI_API_KEY")

    # openai 1.30.x still passes ``proxies=`` to its default httpx client,
    # while httpx 0.28 removed that argument. Supplying a client keeps the
    # app compatible with the versions already installed in this venv.
    # http_client = httpx.Client(timeout=timeout)
    # return OpenAI(api_key=api_key, base_url=base_url, http_client=http_client), model
    return OpenAI(api_key=api_key, base_url=base_url), model


class ModelTestTask(QRunnable):
    def __init__(self, disable_thinking: bool = False) -> None:
        super().__init__()
        self.disable_thinking = disable_thinking
        self.signals = ModelTestSignals()

    @pyqtSlot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            client, model = make_openai_client(timeout=20.0)
            request_kwargs = {
                "model": model,
                "messages": [{"role": "user", "content": "你好"}]
            }
            if self.disable_thinking:
                request_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
            response = client.chat.completions.create(**request_kwargs)
            text = (response.choices[0].message.content or "").strip()
            if not text:
                raise RuntimeError("模型返回为空")
            self.signals.finished.emit(text)
        except Exception as exc:  # noqa: BLE001 - surface test errors to the UI.
            self.signals.failed.emit(str(exc))


class TranslationTask(QRunnable):
    def __init__(
        self,
        pixmap: QPixmap,
        prompt: str,
        context: list[str] | None = None,
        original_text: str = "",
        mode: str = "full",
        disable_thinking: bool = False,
    ) -> None:
        super().__init__()
        self.pixmap = pixmap
        self.prompt = prompt
        self.context = context or []
        self.original_text = original_text
        self.mode = mode
        self.disable_thinking = disable_thinking
        self.signals = TranslationSignals()

    @pyqtSlot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            client, model = make_openai_client(timeout=180.0)
            image_url = pixmap_to_png_data_url(self.pixmap)
            text_prompt = self._build_prompt()
            messages = [
                {"role": "system", "content": self.prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": text_prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ]

            _debug_print_api_payload(model, messages, self.pixmap)

            request_kwargs = {
                "model": model,
                "messages": messages,
            }
            if self.disable_thinking:
                request_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

            response = client.chat.completions.create(**request_kwargs)
            _debug_print_api_response(response)
            text = response.choices[0].message.content or ""
            original_text, translation = self._parse_response(text.strip())
            self.signals.finished.emit(original_text, translation)
        except Exception as exc:  # noqa: BLE001 - surface API/configuration errors to the UI.
            self.signals.failed.emit(str(exc))

    def _build_prompt(self) -> str:
        if self.mode == "translation_only":
            context_text = self._format_context()
            parts = [
                "请只翻译下面的原文，直接输出译文，不要输出原文，不要解释过程。",
                "如果提供了上下文，请只把它作为术语、人名、地名和风格参考，不要复述这些内容。",
                f"项目上下文:\n{context_text}",
                f"当前原文:\n{self.original_text}",
            ]
            return "\n\n".join(parts)

        parts = [
            "请识别截图中的原文并翻译。",
            '必须输出 JSON，不要使用 Markdown 代码块。',
            'JSON 格式为 {"original_text":"识别出的原文","translation":"翻译结果"}。',
        ]
        if self.context:
            parts.extend(
                [
                    "以下是同一翻译项目前的原文和翻译，只作为术语、人名、地名和上下文参考，不要复述这些内容：",
                    self._format_context(),
                ]
            )
        return "\n\n".join(parts)

    def _format_context(self) -> str:
        if not self.context:
            return "无"
        return "\n\n".join(
            f"第{index} 轮\n{text}"
            for index, text in enumerate(self.context, start=1)
            if text.strip()
        )

    def _parse_response(self, text: str) -> tuple[str, str]:
        if self.mode == "translation_only":
            return self.original_text, text

        data = self._json_from_text(text)
        if isinstance(data, dict):
            original = str(data.get("original_text") or data.get("original") or data.get("source") or "").strip()
            translation = str(data.get("translation") or data.get("translated_text") or data.get("target") or "").strip()
            if original or translation:
                return original, translation

        original_match = re.search(r"原文[:：]\s*(.*?)(?:\n\s*翻译[:：]|\Z)", text, re.S)
        translation_match = re.search(r"翻译[:：]\s*(.*)\Z", text, re.S)
        if original_match or translation_match:
            original = original_match.group(1).strip() if original_match else ""
            translation = translation_match.group(1).strip() if translation_match else text
            return original, translation

        return "", text

    @staticmethod
    def _json_from_text(text: str):
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", cleaned, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
        return None


class Translator(QObject):
    def __init__(self, disable_thinking: bool = False) -> None:
        super().__init__()
        self.pool = QThreadPool.globalInstance()
        self.disable_thinking = disable_thinking

    def set_disable_thinking(self, disabled: bool) -> None:
        self.disable_thinking = disabled

    def test_model(self, on_started, on_finished, on_failed) -> None:
        task = ModelTestTask(self.disable_thinking)
        task.signals.started.connect(on_started)
        task.signals.finished.connect(on_finished)
        task.signals.failed.connect(on_failed)
        self.pool.start(task)

    def translate(
        self,
        pixmap: QPixmap,
        prompt: str,
        context: list[str] | None,
        on_started,
        on_finished,
        on_failed,
    ) -> None:
        task = TranslationTask(
            pixmap,
            prompt,
            context,
            disable_thinking=self.disable_thinking,
        )
        task.signals.started.connect(on_started)
        task.signals.finished.connect(on_finished)
        task.signals.failed.connect(on_failed)
        self.pool.start(task)

    def translate_text(
        self,
        pixmap: QPixmap,
        prompt: str,
        original_text: str,
        context: list[str] | None,
        on_started,
        on_finished,
        on_failed,
    ) -> None:
        task = TranslationTask(
            pixmap,
            prompt,
            context,
            original_text=original_text,
            mode="translation_only",
            disable_thinking=self.disable_thinking,
        )
        task.signals.started.connect(on_started)
        task.signals.finished.connect(on_finished)
        task.signals.failed.connect(on_failed)
        self.pool.start(task)
