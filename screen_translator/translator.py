from __future__ import annotations

import base64
import os

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
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)


class TranslationTask(QRunnable):
    def __init__(self, pixmap: QPixmap, prompt: str) -> None:
        super().__init__()
        self.pixmap = pixmap
        self.prompt = prompt
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

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": self.prompt},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    }
                ],
                temperature=0.2,
            )
            text = response.choices[0].message.content or ""
            self.signals.finished.emit(text.strip())
        except Exception as exc:  # noqa: BLE001 - surface API/configuration errors to the UI.
            self.signals.failed.emit(str(exc))


class Translator(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.pool = QThreadPool.globalInstance()

    def translate(
        self,
        pixmap: QPixmap,
        prompt: str,
        on_started,
        on_finished,
        on_failed,
    ) -> None:
        task = TranslationTask(pixmap, prompt)
        task.signals.started.connect(on_started)
        task.signals.finished.connect(on_finished)
        task.signals.failed.connect(on_failed)
        self.pool.start(task)
