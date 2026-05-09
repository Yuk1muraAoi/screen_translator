from __future__ import annotations

import base64
import json
import os
import re

import httpx
from dotenv import load_dotenv
from openai import OpenAI
from PyQt5.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QPixmap


def pixmap_to_png_data_url(pixmap: QPixmap) -> str:
    from PyQt5.QtCore import QByteArray, QBuffer, QIODevice

    byte_array = QByteArray()
    buffer = QBuffer(byte_array)
    buffer.open(QIODevice.WriteOnly)
    pixmap.save(buffer, "PNG")
    payload = bytes(byte_array)
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:image/png;base64,{encoded}"


class TranslationSignals(QObject):
    started = pyqtSignal()
    finished = pyqtSignal(str, str)
    failed = pyqtSignal(str)


class TranslationTask(QRunnable):
    def __init__(
        self,
        pixmap: QPixmap,
        prompt: str,
        context: list[str] | None = None,
        original_text: str = "",
        mode: str = "full",
    ) -> None:
        super().__init__()
        self.pixmap = pixmap
        self.prompt = prompt
        self.context = context or []
        self.original_text = original_text
        self.mode = mode
        self.signals = TranslationSignals()

    @pyqtSlot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            load_dotenv()
            api_key = os.getenv("OPENAI_API_KEY")
            base_url = os.getenv("OPENAI_API_BASE") or os.getenv("OPENAI_BASE_URL")
            model = os.getenv("MODEL_NAME") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"

            if not api_key:
                raise RuntimeError("未在 .env 中找到 OPENAI_API_KEY")

            # openai 1.30.x still passes ``proxies=`` to its default httpx client,
            # while httpx 0.28 removed that argument. Supplying a client keeps the
            # app compatible with the versions already installed in this venv.
            http_client = httpx.Client(timeout=60.0)
            client = OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)
            image_url = pixmap_to_png_data_url(self.pixmap)
            text_prompt = self._build_prompt()

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": text_prompt},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    }
                ],
                temperature=0.2,
            )
            text = response.choices[0].message.content or ""
            original_text, translation = self._parse_response(text.strip())
            self.signals.finished.emit(original_text, translation)
        except Exception as exc:  # noqa: BLE001 - surface API/configuration errors to the UI.
            self.signals.failed.emit(str(exc))

    def _build_prompt(self) -> str:
        if self.mode == "translation_only":
            context_text = self._format_context()
            return (
                f"{self.prompt}\n\n"
                "请只翻译下面的原文，直接输出翻译结果，不要输出原文，不要解释过程。\n"
                "如果提供了项目上下文，请只把它作为术语、人名、地名和风格参考。\n\n"
                f"项目上下文:\n{context_text}\n\n"
                f"当前原文:\n{self.original_text}"
            )

        full_prompt = (
            f"{self.prompt}\n\n"
            "请识别截图中的原文并翻译。必须输出 JSON，不要使用 Markdown 代码块。"
            'JSON 格式为: {"original_text":"识别出的原文","translation":"翻译结果"}。'
        )
        if not self.context:
            return full_prompt

        return (
            f"{full_prompt}\n\n"
            "以下是同一翻译项目之前的原文和翻译，只作为术语、人名、地名和上下文参考，"
            "不要复述这些内容：\n"
            f"{self._format_context()}"
        )

    def _format_context(self) -> str:
        if not self.context:
            return "无"
        return "\n\n".join(
            f"第 {index} 轮:\n{text}"
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
    def __init__(self) -> None:
        super().__init__()
        self.pool = QThreadPool.globalInstance()

    def translate(
        self,
        pixmap: QPixmap,
        prompt: str,
        context: list[str] | None,
        on_started,
        on_finished,
        on_failed,
    ) -> None:
        task = TranslationTask(pixmap, prompt, context)
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
        )
        task.signals.started.connect(on_started)
        task.signals.finished.connect(on_finished)
        task.signals.failed.connect(on_failed)
        self.pool.start(task)
