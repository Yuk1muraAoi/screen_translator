from __future__ import annotations

import base64
import binascii
import ctypes
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PyQt5.QtCore import QPoint, QSize, Qt, QTimer
from PyQt5.QtGui import QFont, QIcon, QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .capture import RegionSelector, capture_desktop, virtual_geometry
from .config import AppConfig, load_config, load_env_text, save_config, save_env_text
from .hotkeys import GlobalHotkeyManager
from .projects import ProjectStore, TEMP_PROJECT_ID, TranslationProject, TranslationRecord
from .translator import Translator


HOTKEY_FULL_SCREEN = 101
HOTKEY_REGION = 102
HOTKEY_COLLAPSE = 103
APP_USER_MODEL_ID = "YukimuraAoi.ScreenTranslator"


def _resource_path(name: str) -> Path:
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        return Path(bundle_dir) / name
    return Path(__file__).resolve().parent.parent / name


def app_icon() -> QIcon:
    icon_path = _resource_path("logo.jpg")
    if icon_path.exists():
        return QIcon(str(icon_path))
    return QIcon()


def set_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


def make_button(text: str, tooltip: str = "") -> QPushButton:
    button = QPushButton(text)
    button.setCursor(Qt.PointingHandCursor)
    button.setToolTip(tooltip)
    button.setMinimumHeight(34)
    return button


def make_plain_text_edit(text: str = "") -> QTextEdit:
    editor = QTextEdit()
    editor.setAcceptRichText(False)
    editor.setPlainText(text)
    return editor


class ShortcutEdit(QLineEdit):
    def __init__(self, value: str = "") -> None:
        super().__init__(value)
        self.setPlaceholderText("例如 Ctrl+Alt+A")
        self.setReadOnly(True)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            return

        sequence = QKeySequence(event.modifiers() | key).toString(QKeySequence.NativeText)
        sequence = sequence.replace(",", "").replace("Meta", "Win")
        if sequence:
            self.setText(sequence)


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model_tester = Translator(config.disable_thinking)
        self.setWindowTitle("设置")
        self.setMinimumWidth(520)

        self.full_hotkey = ShortcutEdit(config.full_screen_hotkey)
        self.region_hotkey = ShortcutEdit(config.region_hotkey)
        self.collapse_hotkey = ShortcutEdit(config.collapse_hotkey)
        self.disable_thinking = QCheckBox("关闭思考模式")
        self.disable_thinking.setChecked(config.disable_thinking)
        self.prompt = make_plain_text_edit(config.prompt)
        self.prompt.setMinimumHeight(160)
        self.env_editor = make_plain_text_edit(load_env_text())
        self.env_editor.setMinimumHeight(150)
        self.env_editor.setPlaceholderText("OPENAI_API_KEY=\nOPENAI_API_BASE=\nMODEL_NAME=")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(QLabel("全屏截图快捷键"))
        layout.addWidget(self.full_hotkey)
        layout.addWidget(QLabel("选区截图快捷键"))
        layout.addWidget(self.region_hotkey)
        layout.addWidget(QLabel("收起/唤起快捷键"))
        layout.addWidget(self.collapse_hotkey)
        layout.addWidget(self.disable_thinking)
        layout.addWidget(QLabel("全局默认提示词"))
        layout.addWidget(self.prompt)
        layout.addWidget(QLabel("模型 .env 配置"))
        layout.addWidget(self.env_editor)
        self.test_model_button = make_button("测试模型", "发送“你好”测试当前模型配置")
        self.test_model_button.clicked.connect(self.test_model)
        layout.addWidget(self.test_model_button)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply_to(self, config: AppConfig) -> AppConfig:
        config.full_screen_hotkey = self.full_hotkey.text().strip()
        config.region_hotkey = self.region_hotkey.text().strip()
        config.collapse_hotkey = self.collapse_hotkey.text().strip()
        config.disable_thinking = self.disable_thinking.isChecked()
        config.prompt = self.prompt.toPlainText().strip()
        return config

    def env_text(self) -> str:
        return self.env_editor.toPlainText()

    def test_model(self) -> None:
        save_env_text(self.env_text())
        self.model_tester.set_disable_thinking(self.disable_thinking.isChecked())
        self.test_model_button.setEnabled(False)
        self.test_model_button.setText("测试中...")
        self.model_tester.test_model(
            on_started=lambda: None,
            on_finished=self._model_test_finished,
            on_failed=self._model_test_failed,
        )

    def _model_test_finished(self, text: str) -> None:
        self.test_model_button.setEnabled(True)
        self.test_model_button.setText("测试模型")
        QMessageBox.information(self, "测试成功", f"模型正常返回：\n{text}")

    def _model_test_failed(self, error: str) -> None:
        self.test_model_button.setEnabled(True)
        self.test_model_button.setText("测试模型")
        QMessageBox.warning(self, "测试失败", error)


class PromptDialog(QDialog):
    def __init__(self, title: str, prompt: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(560)
        self.editor = make_plain_text_edit(prompt)
        self.editor.setMinimumHeight(220)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("项目提示词"))
        layout.addWidget(self.editor)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def prompt(self) -> str:
        return self.editor.toPlainText().strip()


class ChatBubble(QFrame):
    def __init__(
        self,
        project_id: str,
        round_number: int,
        pixmap: QPixmap | None,
        original_text: str = "",
        text: str = "",
    ) -> None:
        super().__init__()
        self.project_id = project_id
        self.round_number = round_number
        self.setObjectName("bubble")
        self.setFrameShape(QFrame.NoFrame)

        self.image = QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.image.setMinimumHeight(72)
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(QSize(360, 220), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.image.setPixmap(scaled)
        else:
            self.image.setText("图片文件缺失")
            self.image.setObjectName("missingImage")

        original_label = QLabel("原文")
        original_label.setObjectName("fieldLabel")
        self.original_text = make_plain_text_edit(original_text)
        self.original_text.setPlaceholderText("模型识别出的原文会显示在这里，也可以直接手动修改。")
        self.original_text.setMinimumHeight(96)

        translation_label = QLabel("翻译")
        translation_label.setObjectName("fieldLabel")
        self.translation = make_plain_text_edit(text)
        self.translation.setPlaceholderText("翻译结果会显示在这里，也可以直接手动修改。")
        self.translation.setMinimumHeight(120)

        self.retry_button = make_button("重试", "使用同一张截图重新调用模型")
        self.retry_button.setFixedWidth(72)
        self.retry_translation_button = make_button("重试翻译", "使用当前原文重新翻译")
        self.retry_translation_button.setFixedWidth(96)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addStretch(1)
        footer.addWidget(self.retry_button)
        footer.addWidget(self.retry_translation_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(self.image)
        layout.addWidget(original_label)
        layout.addWidget(self.original_text)
        layout.addWidget(translation_label)
        layout.addWidget(self.translation)
        layout.addLayout(footer)

    def set_translation(self, text: str) -> None:
        self.translation.blockSignals(True)
        self.translation.setPlainText(text)
        self.translation.blockSignals(False)

    def set_texts(self, original_text: str, translation: str) -> None:
        self.original_text.blockSignals(True)
        self.translation.blockSignals(True)
        self.original_text.setPlainText(original_text)
        self.translation.setPlainText(translation)
        self.translation.blockSignals(False)
        self.original_text.blockSignals(False)


class AddImageBox(QPushButton):
    def __init__(self) -> None:
        super().__init__("+")
        self.setObjectName("addImageBox")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("从剪贴板读取图片链接或 base64 图片并翻译")
        self.setMinimumHeight(92)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        font = self.font()
        font.setPointSize(24)
        font.setBold(True)
        self.setFont(font)


class FloatingWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config = load_config()
        self.store = ProjectStore(self.config.prompt, self.config.temp_prompt)
        self.translator = Translator(self.config.disable_thinking)
        self.hotkeys = GlobalHotkeyManager()
        self.drag_position: QPoint | None = None
        self.region_selector: RegionSelector | None = None
        self.current_project_id = TEMP_PROJECT_ID
        self.loading_project = False
        self.temp_pixmaps: dict[int, QPixmap] = {}

        self.setWindowTitle("截图翻译")
        self.setWindowIcon(app_icon())
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(max(self.config.window_width, 620), max(self.config.window_height, 620))
        self._build_ui()
        self._apply_style()
        self._refresh_project_list(self.config.selected_project_id)
        self._register_hotkeys()

        app = QApplication.instance()
        if app:
            app.installNativeEventFilter(self.hotkeys)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        self.title = QLabel("截图翻译")
        self.title.setObjectName("title")
        self.title.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))

        self.full_button = make_button("全屏", "截取全屏并翻译")
        self.region_button = make_button("选区", "框选屏幕区域并翻译")
        self.delete_last_button = make_button("删末轮", "删除当前项目最后一轮截图和翻译结果")
        self.settings_button = make_button("设置", "修改全局快捷键和默认提示词")
        self.collapse_button = make_button("收起", "收起到任务栏")
        self.close_button = make_button("×", "退出")
        self.close_button.setFixedWidth(38)

        self.full_button.clicked.connect(self.capture_full_screen)
        self.region_button.clicked.connect(self.capture_region)
        self.delete_last_button.clicked.connect(self.delete_last_round)
        self.settings_button.clicked.connect(self.open_settings)
        self.collapse_button.clicked.connect(self.minimize_to_taskbar)
        self.close_button.clicked.connect(QApplication.quit)

        header = QHBoxLayout()
        header.setContentsMargins(12, 10, 12, 6)
        header.setSpacing(8)
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.full_button)
        header.addWidget(self.region_button)
        header.addWidget(self.delete_last_button)
        header.addWidget(self.settings_button)
        header.addWidget(self.collapse_button)
        header.addWidget(self.close_button)

        self.project_list = QListWidget()
        self.project_list.setObjectName("projectList")
        self.project_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.project_list.currentItemChanged.connect(self._project_selection_changed)
        self.project_list.customContextMenuRequested.connect(self._show_project_menu)

        self.new_project_button = make_button("新建项目", "创建一个独立的翻译项目")
        self.new_project_button.clicked.connect(self.create_project)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(152)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 8, 8, 12)
        sidebar_layout.setSpacing(8)
        sidebar_layout.addWidget(QLabel("项目"))
        sidebar_layout.addWidget(self.project_list)
        sidebar_layout.addWidget(self.new_project_button)

        self.scroll_body = QWidget()
        self.chat_layout = QVBoxLayout(self.scroll_body)
        self.chat_layout.setContentsMargins(12, 8, 12, 12)
        self.chat_layout.setSpacing(12)
        self.chat_layout.addStretch(1)
        self.add_image_box = AddImageBox()
        self.add_image_box.clicked.connect(self.import_clipboard_image)
        self.chat_layout.addWidget(self.add_image_box)

        self.empty_label = QLabel("点击“全屏”或“选区”开始截图翻译")
        self.empty_label.setObjectName("empty")
        self.empty_label.setAlignment(Qt.AlignCenter)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.scroll_body)

        self.status = QLabel()
        self.status.setObjectName("status")

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(scroll)
        right_layout.addWidget(self.status)

        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.addWidget(sidebar)
        content.addWidget(right_panel, 1)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(header)
        layout.addLayout(content, 1)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget#root {
                background: #f8fafc;
                border: 1px solid #cbd5e1;
                border-radius: 10px;
            }
            QWidget#sidebar {
                background: #eef2f7;
                border-top: 1px solid #dbe3ee;
                border-right: 1px solid #dbe3ee;
            }
            QListWidget#projectList {
                background: #ffffff;
                color: #172033;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                outline: none;
            }
            QListWidget#projectList::item {
                padding: 8px;
                border-radius: 4px;
            }
            QListWidget#projectList::item:selected {
                background: #d9ebff;
                color: #0f172a;
            }
            QLabel#title {
                color: #172033;
            }
            QLabel#empty {
                color: #64748b;
                padding: 60px 16px;
            }
            QLabel#missingImage {
                color: #94a3b8;
                background: #f1f5f9;
                border-radius: 6px;
            }
            QLabel#fieldLabel {
                color: #334155;
                font-weight: 700;
            }
            QLabel#status {
                color: #64748b;
                padding: 6px 12px 10px 12px;
                font-size: 12px;
            }
            QPushButton {
                background: #ffffff;
                color: #1e293b;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px 10px;
            }
            QPushButton:hover {
                background: #eef6ff;
                border-color: #7db7ee;
            }
            QPushButton:pressed {
                background: #d9ebff;
            }
            QPushButton#addImageBox {
                background: #ffffff;
                color: #64748b;
                border: 2px dashed #b6c3d1;
                border-radius: 8px;
                padding: 0;
            }
            QPushButton#addImageBox:hover {
                background: #f0f7ff;
                color: #2563eb;
                border-color: #7db7ee;
            }
            QFrame#bubble {
                background: #ffffff;
                border: 1px solid #dbe3ee;
                border-radius: 8px;
            }
            QTextEdit, QLineEdit {
                background: #ffffff;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 8px;
                selection-background-color: #a7d4ff;
            }
            QScrollArea {
                background: transparent;
            }
            """
        )

    def _register_hotkeys(self) -> None:
        try:
            self.hotkeys.register(
                HOTKEY_FULL_SCREEN,
                self.config.full_screen_hotkey,
                self.capture_full_screen,
            )
            self.hotkeys.register(HOTKEY_REGION, self.config.region_hotkey, self.capture_region)
            self.hotkeys.register(HOTKEY_COLLAPSE, self.config.collapse_hotkey, self.toggle_taskbar_visibility)
            self._set_ready_status()
        except Exception as exc:  # noqa: BLE001 - show actionable shortcut conflicts in-app.
            self.status.setText(str(exc))
            QMessageBox.warning(self, "快捷键注册失败", str(exc))

    def _refresh_project_list(self, selected_project_id: str | None = None) -> None:
        self.project_list.blockSignals(True)
        self.project_list.clear()
        selected_row = 0
        for row, project in enumerate(self.store.all_projects()):
            label = project.name
            if project.is_temporary:
                label = "★ 临时翻译"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, project.project_id)
            self.project_list.addItem(item)
            if project.project_id == selected_project_id:
                selected_row = row
        self.project_list.setCurrentRow(selected_row)
        self.project_list.blockSignals(False)
        item = self.project_list.currentItem()
        if item:
            self.select_project(item.data(Qt.UserRole))

    def _project_selection_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        del previous
        if current:
            self.select_project(current.data(Qt.UserRole))

    def select_project(self, project_id: str) -> None:
        self.current_project_id = project_id
        self.config.selected_project_id = project_id
        save_config(self.config)
        self._load_project_messages()
        self._set_ready_status()

    def _load_project_messages(self) -> None:
        self.loading_project = True
        self._clear_chat()
        project = self.current_project()
        for record in project.records:
            if record.round == 0:
                continue
            pixmap = self._pixmap_for_record(project, record)
            self._add_bubble(
                project.project_id,
                record.round,
                pixmap,
                record.original_text,
                record.translation,
            )

        if not self._has_message_bubbles():
            self.chat_layout.insertWidget(self._message_insert_index(), self.empty_label)
            self.empty_label.show()
        self.loading_project = False

    def _clear_chat(self) -> None:
        for index in reversed(range(self.chat_layout.count())):
            item = self.chat_layout.itemAt(index)
            widget = item.widget()
            if widget is self.empty_label:
                self.chat_layout.takeAt(index)
                widget.setParent(None)
            elif isinstance(widget, ChatBubble):
                self.chat_layout.takeAt(index)
                widget.deleteLater()

    def _message_insert_index(self) -> int:
        for index in range(self.chat_layout.count()):
            if self.chat_layout.itemAt(index).spacerItem():
                return index
        return max(0, self.chat_layout.count() - 1)

    def _has_message_bubbles(self) -> bool:
        for index in range(self.chat_layout.count()):
            widget = self.chat_layout.itemAt(index).widget()
            if isinstance(widget, ChatBubble):
                return True
        return False

    def _pixmap_for_record(
        self,
        project: TranslationProject,
        record: TranslationRecord,
    ) -> QPixmap | None:
        if project.is_temporary:
            return self.temp_pixmaps.get(record.round)
        image_path = self.store.image_path_for(project, record)
        if image_path and image_path.exists():
            return QPixmap(str(image_path))
        return None

    def _add_bubble(
        self,
        project_id: str,
        round_number: int,
        pixmap: QPixmap | None,
        original_text: str,
        text: str,
    ) -> ChatBubble:
        self.empty_label.hide()
        self.empty_label.setParent(None)
        bubble = ChatBubble(project_id, round_number, pixmap, original_text, text)
        bubble.original_text.textChanged.connect(lambda bubble=bubble: self._bubble_text_changed(bubble))
        bubble.translation.textChanged.connect(lambda bubble=bubble: self._bubble_text_changed(bubble))
        bubble.retry_button.clicked.connect(lambda checked=False, bubble=bubble: self.retry_translation(bubble))
        bubble.retry_translation_button.clicked.connect(
            lambda checked=False, bubble=bubble: self.retry_translation_only(bubble)
        )
        self.chat_layout.insertWidget(self._message_insert_index(), bubble)
        return bubble

    def _bubble_text_changed(self, bubble: ChatBubble) -> None:
        if self.loading_project:
            return
        self.store.update_record_texts(
            bubble.project_id,
            bubble.round_number,
            original_text=bubble.original_text.toPlainText(),
            translation=bubble.translation.toPlainText(),
        )

    def current_project(self) -> TranslationProject:
        return self.store.get(self.current_project_id)

    def create_project(self) -> None:
        project = self.store.create_project()
        self._refresh_project_list(project.project_id)

    def _show_project_menu(self, position: QPoint) -> None:
        item = self.project_list.itemAt(position)
        if not item:
            return
        project_id = item.data(Qt.UserRole)
        project = self.store.get(project_id)

        menu = QMenu(self)
        prompt_action = menu.addAction("修改提示词")
        rename_action = None
        delete_action = None
        if not project.is_temporary:
            rename_action = menu.addAction("修改名称")
            delete_action = menu.addAction("删除项目")

        action = menu.exec_(self.project_list.mapToGlobal(position))
        if action == prompt_action:
            self.edit_project_prompt(project_id)
        elif rename_action and action == rename_action:
            self.rename_project(project_id)
        elif delete_action and action == delete_action:
            self.delete_project(project_id)

    def edit_project_prompt(self, project_id: str) -> None:
        project = self.store.get(project_id)
        dialog = PromptDialog(f"{project.name} - 提示词", project.prompt, self)
        if dialog.exec_() == QDialog.Accepted:
            prompt = dialog.prompt()
            if not prompt:
                return
            self.store.update_prompt(project_id, prompt)
            if project_id == TEMP_PROJECT_ID:
                self.config.temp_prompt = prompt
                save_config(self.config)
            self._set_ready_status()

    def rename_project(self, project_id: str) -> None:
        project = self.store.get(project_id)
        name, ok = QInputDialog.getText(self, "修改项目名称", "项目名称", text=project.name)
        if not ok or not name.strip():
            return
        updated = self.store.rename_project(project_id, name.strip())
        self._refresh_project_list(updated.project_id)

    def delete_project(self, project_id: str) -> None:
        project = self.store.get(project_id)
        reply = QMessageBox.question(
            self,
            "删除项目",
            f"确认删除项目“{project.name}”？该项目的历史截图和 JSON 会一起删除。",
        )
        if reply != QMessageBox.Yes:
            return
        self.store.delete_project(project_id)
        self._refresh_project_list(TEMP_PROJECT_ID)

    def delete_last_round(self) -> None:
        project = self.current_project()
        deleted = self.store.delete_last_record(project.project_id)
        if not deleted:
            self.status.setText("当前项目没有可删除的翻译轮次。")
            return

        if project.is_temporary:
            self.temp_pixmaps.pop(deleted.round, None)

        self._load_project_messages()
        self._set_ready_status()
        self.status.setText(f"已删除最后一轮翻译：第 {deleted.round} 轮。")

    def capture_full_screen(self) -> None:
        self.restore_from_taskbar()
        self.hide()
        QTimer.singleShot(180, self._capture_full_screen_after_hide)

    def _capture_full_screen_after_hide(self) -> None:
        pixmap = capture_desktop()
        self.show()
        self._translate_pixmap(pixmap)

    def capture_region(self) -> None:
        self.restore_from_taskbar()
        self.hide()
        QTimer.singleShot(180, self._show_region_selector)

    def _show_region_selector(self) -> None:
        pixmap = capture_desktop()
        self.region_selector = RegionSelector(pixmap)
        self.region_selector.selected.connect(self._region_selected)
        self.region_selector.canceled.connect(self.show)
        self.region_selector.show()
        self.region_selector.activateWindow()

    def _region_selected(self, pixmap: QPixmap) -> None:
        self.show()
        self._translate_pixmap(pixmap)

    def import_clipboard_image(self) -> None:
        app = QApplication.instance()
        if not app:
            return

        clipboard = app.clipboard()
        mime_data = clipboard.mimeData()
        pixmap = QPixmap()
        source = ""

        if mime_data.hasImage():
            pixmap = QPixmap.fromImage(mime_data.imageData())
            source = "剪贴板图片"
        else:
            text = clipboard.text().strip()
            try:
                pixmap, source = self._pixmap_from_clipboard_text(text)
            except ValueError as exc:
                self.status.setText(str(exc))
                QMessageBox.warning(self, "导入失败", str(exc))
                return

        if pixmap.isNull():
            message = "剪贴板中没有可识别的图片、图片链接或 base64 图片。"
            self.status.setText(message)
            QMessageBox.warning(self, "导入失败", message)
            return

        self.status.setText(f"已读取{source}，正在识别和翻译...")
        self._translate_pixmap(pixmap)

    def _pixmap_from_clipboard_text(self, text: str) -> tuple[QPixmap, str]:
        if not text:
            raise ValueError("剪贴板文本为空，请先复制网页图片链接或 base64 图片链接。")

        cleaned = text.strip().strip("\"'<>")
        parsed = urllib.parse.urlparse(cleaned)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return self._download_pixmap(cleaned), "网页图片链接"

        image_bytes = self._decode_base64_image(cleaned)
        pixmap = QPixmap()
        if not pixmap.loadFromData(image_bytes):
            raise ValueError("剪贴板中的 base64 内容无法解析为图片。")
        return pixmap, "base64 图片"

    def _download_pixmap(self, url: str) -> QPixmap:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 screen-translator/1.0",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            },
        )
        self.add_image_box.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                content_type = response.headers.get("Content-Type", "")
                payload = response.read(16 * 1024 * 1024 + 1)
        except (OSError, urllib.error.URLError) as exc:
            raise ValueError(f"下载图片失败：{exc}") from exc
        finally:
            QApplication.restoreOverrideCursor()
            self.add_image_box.setEnabled(True)

        if len(payload) > 16 * 1024 * 1024:
            raise ValueError("图片超过 16MB，已取消导入。")

        pixmap = QPixmap()
        if not pixmap.loadFromData(payload):
            if content_type and not content_type.lower().startswith("image/"):
                raise ValueError(f"链接返回的内容不是图片：{content_type}")
            raise ValueError("链接内容无法解析为图片。")
        return pixmap

    @staticmethod
    def _decode_base64_image(text: str) -> bytes:
        match = re.match(r"^data:image/[^;]+;base64,(?P<payload>.+)$", text, flags=re.I | re.S)
        payload = match.group("payload") if match else text
        payload = re.sub(r"\s+", "", payload)
        if len(payload) < 32:
            raise ValueError("剪贴板中没有可识别的图片链接或 base64 图片。")

        padding = "=" * (-len(payload) % 4)
        try:
            return base64.b64decode(payload + padding, validate=True)
        except (binascii.Error, ValueError):
            try:
                return base64.urlsafe_b64decode(payload + padding)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("剪贴板中没有可识别的图片链接或 base64 图片。") from exc

    def _translate_pixmap(self, pixmap: QPixmap) -> None:
        project = self.current_project()
        context = project.context_translations()
        record = self.store.add_record(project.project_id, pixmap, "正在识别原文...", "正在翻译...")
        if project.is_temporary:
            self.temp_pixmaps[record.round] = pixmap

        bubble = self._add_bubble(
            project.project_id,
            record.round,
            pixmap,
            record.original_text,
            record.translation,
        )
        bubble.retry_button.setEnabled(False)
        bubble.retry_translation_button.setEnabled(False)
        self.translator.translate(
            pixmap,
            project.prompt,
            context,
            on_started=lambda: self.status.setText("正在调用大模型 API..."),
            on_finished=lambda original, translation, pid=project.project_id, rnd=record.round: self._translation_finished(
                pid,
                rnd,
                original,
                translation,
            ),
            on_failed=lambda error, pid=project.project_id, rnd=record.round: self._translation_failed(
                pid,
                rnd,
                error,
            ),
        )
        bubble.translation.setFocus()

    def retry_translation(self, bubble: ChatBubble) -> None:
        project = self.store.get(bubble.project_id)
        record = self._record_for(project, bubble.round_number)
        if not record:
            self.status.setText("重试失败：找不到这条翻译记录。")
            return

        pixmap = self._pixmap_for_record(project, record)
        if not pixmap or pixmap.isNull():
            self.status.setText("重试失败：找不到原始截图。")
            return

        context = self._context_excluding(project, bubble.round_number)

        self._disable_retry_buttons_temporarily(bubble)
        bubble.set_texts("正在重新识别原文...", "正在重新翻译...")
        self.store.update_record_texts(
            project.project_id,
            bubble.round_number,
            original_text="正在重新识别原文...",
            translation="正在重新翻译...",
        )
        self.translator.translate(
            pixmap,
            project.prompt,
            context,
            on_started=lambda: self.status.setText("正在重试完整识别和翻译..."),
            on_finished=lambda original, translation, pid=project.project_id, rnd=bubble.round_number: self._translation_finished(
                pid,
                rnd,
                original,
                translation,
            ),
            on_failed=lambda error, pid=project.project_id, rnd=bubble.round_number: self._translation_failed(
                pid,
                rnd,
                error,
            ),
        )

    def retry_translation_only(self, bubble: ChatBubble) -> None:
        project = self.store.get(bubble.project_id)
        record = self._record_for(project, bubble.round_number)
        if not record:
            self.status.setText("重试翻译失败：找不到这条翻译记录。")
            return

        pixmap = self._pixmap_for_record(project, record)
        if not pixmap or pixmap.isNull():
            self.status.setText("重试翻译失败：找不到原始截图。")
            return

        original_text = bubble.original_text.toPlainText().strip()
        if not original_text:
            self.status.setText("重试翻译失败：原文为空。")
            return

        context = self._context_excluding(project, bubble.round_number)
        context.append(f"当前原文:\n{original_text}")

        self._disable_retry_buttons_temporarily(bubble)
        bubble.set_translation("正在重新翻译...")
        self.store.update_record_texts(
            project.project_id,
            bubble.round_number,
            original_text=original_text,
            translation="正在重新翻译...",
        )
        self.translator.translate_text(
            pixmap,
            project.prompt,
            original_text,
            context,
            on_started=lambda: self.status.setText("正在基于原文重试翻译..."),
            on_finished=lambda original, translation, pid=project.project_id, rnd=bubble.round_number: self._translation_finished(
                pid,
                rnd,
                original,
                translation,
            ),
            on_failed=lambda error, pid=project.project_id, rnd=bubble.round_number: self._translation_failed(
                pid,
                rnd,
                error,
            ),
        )

    def _disable_retry_buttons_temporarily(self, bubble: ChatBubble) -> None:
        bubble.retry_button.setEnabled(False)
        bubble.retry_translation_button.setEnabled(False)
        project_id = bubble.project_id
        round_number = bubble.round_number
        QTimer.singleShot(
            10000,
            lambda: self._enable_retry_buttons_if_visible(project_id, round_number),
        )

    def _enable_retry_buttons_if_visible(self, project_id: str, round_number: int) -> None:
        bubble = self._find_bubble(project_id, round_number)
        if bubble:
            bubble.retry_button.setEnabled(True)
            bubble.retry_translation_button.setEnabled(True)

    def _context_excluding(self, project: TranslationProject, round_number: int) -> list[str]:
        context: list[str] = []
        for item in project.records:
            original = item.original_text.strip()
            translation = item.translation.strip()
            if item.round <= 0 or item.round == round_number:
                continue
            if translation in {"正在翻译...", "正在重新翻译..."} or translation.startswith("翻译失败:"):
                continue
            if original:
                context.append(f"原文:\n{original}\n翻译:\n{translation}")
            elif translation:
                context.append(f"翻译:\n{translation}")
        return context

    def _record_for(self, project: TranslationProject, round_number: int) -> TranslationRecord | None:
        for record in project.records:
            if record.round == round_number:
                return record
        return None

    def _translation_finished(
        self,
        project_id: str,
        round_number: int,
        original_text: str,
        translation: str,
    ) -> None:
        original = original_text or ""
        result = translation or "未返回翻译结果"
        self.store.update_record_texts(
            project_id,
            round_number,
            original_text=original,
            translation=result,
        )
        bubble = self._find_bubble(project_id, round_number)
        if bubble:
            bubble.set_texts(original, result)
            bubble.retry_button.setEnabled(True)
            bubble.retry_translation_button.setEnabled(True)
        self.status.setText("翻译完成，可直接编辑结果。")

    def _translation_failed(self, project_id: str, round_number: int, error: str) -> None:
        result = f"翻译失败:\n{error}"
        bubble = self._find_bubble(project_id, round_number)
        original = ""
        if bubble:
            original = bubble.original_text.toPlainText()
            if original in {"正在识别原文...", "正在重新识别原文..."}:
                original = ""
            bubble.set_texts(original, result)
            bubble.retry_button.setEnabled(True)
            bubble.retry_translation_button.setEnabled(True)
        self.store.update_record_texts(
            project_id,
            round_number,
            original_text=original,
            translation=result,
        )
        self.status.setText("翻译失败，请检查 .env、网络或模型是否支持图片输入。")

    def _find_bubble(self, project_id: str, round_number: int) -> ChatBubble | None:
        for index in range(self.chat_layout.count()):
            widget = self.chat_layout.itemAt(index).widget()
            if (
                isinstance(widget, ChatBubble)
                and widget.project_id == project_id
                and widget.round_number == round_number
            ):
                return widget
        return None

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.config, self)
        if dialog.exec_() == QDialog.Accepted:
            self.config = dialog.apply_to(self.config)
            save_env_text(dialog.env_text())
            self.store.default_prompt = self.config.prompt
            self.translator.set_disable_thinking(self.config.disable_thinking)
            save_config(self.config)
            self.hotkeys.unregister_all()
            self._register_hotkeys()
            self.status.setText("设置已保存，新的模型配置会在下一次翻译时生效。")

    def _set_ready_status(self) -> None:
        project = self.current_project()
        context_hint = "无上下文" if project.is_temporary else f"{len(project.context_translations())} 条上下文"
        self.status.setText(
            f"当前项目: {project.name}    {context_hint}    "
            f"快捷键: 全屏 {self.config.full_screen_hotkey}    "
            f"选区 {self.config.region_hotkey}    收起/唤起 {self.config.collapse_hotkey}"
        )

    def minimize_to_taskbar(self) -> None:
        self.showMinimized()

    def restore_from_taskbar(self) -> None:
        if self.isMinimized():
            self.showNormal()
        elif not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()

    def toggle_taskbar_visibility(self) -> None:
        if self.isMinimized() or not self.isVisible():
            self.restore_from_taskbar()
        else:
            self.minimize_to_taskbar()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.LeftButton and self.drag_position is not None:
            self.move(event.globalPos() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self.drag_position = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event) -> None:
        self.config.window_width = max(620, self.width())
        self.config.window_height = max(420, self.height())
        self.config.selected_project_id = self.current_project_id
        self.config.temp_prompt = self.store.temp_project.prompt
        save_config(self.config)
        self.hotkeys.unregister_all()
        super().closeEvent(event)


def run_app() -> int:
    set_windows_app_user_model_id()
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("ScreenTranslator")
    app.setApplicationDisplayName("ScreenTranslator")
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(True)
    window = FloatingWindow()
    screen_geometry = virtual_geometry()
    window.move(screen_geometry.right() - window.width() - 80, screen_geometry.top() + 100)
    window.show()
    return app.exec_()
