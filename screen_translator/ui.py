from __future__ import annotations

from PyQt5.QtCore import QPoint, QRect, QSize, Qt, QTimer
from PyQt5.QtGui import QFont, QIcon, QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .capture import RegionSelector, capture_desktop, virtual_geometry
from .config import AppConfig, load_config, save_config
from .hotkeys import GlobalHotkeyManager
from .translator import Translator


HOTKEY_FULL_SCREEN = 101
HOTKEY_REGION = 102


def make_button(text: str, tooltip: str = "") -> QPushButton:
    button = QPushButton(text)
    button.setCursor(Qt.PointingHandCursor)
    button.setToolTip(tooltip)
    button.setMinimumHeight(34)
    return button


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
        self.setWindowTitle("设置")
        self.setMinimumWidth(520)

        self.full_hotkey = ShortcutEdit(config.full_screen_hotkey)
        self.region_hotkey = ShortcutEdit(config.region_hotkey)
        self.prompt = QTextEdit(config.prompt)
        self.prompt.setMinimumHeight(160)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(QLabel("全屏截图快捷键"))
        layout.addWidget(self.full_hotkey)
        layout.addWidget(QLabel("选区截图快捷键"))
        layout.addWidget(self.region_hotkey)
        layout.addWidget(QLabel("翻译提示词"))
        layout.addWidget(self.prompt)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply_to(self, config: AppConfig) -> AppConfig:
        config.full_screen_hotkey = self.full_hotkey.text().strip()
        config.region_hotkey = self.region_hotkey.text().strip()
        config.prompt = self.prompt.toPlainText().strip()
        return config


class ChatBubble(QFrame):
    def __init__(self, pixmap: QPixmap, text: str = "") -> None:
        super().__init__()
        self.setObjectName("bubble")
        self.setFrameShape(QFrame.NoFrame)

        image = QLabel()
        image.setAlignment(Qt.AlignCenter)
        image.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        scaled = pixmap.scaled(QSize(360, 220), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        image.setPixmap(scaled)

        self.translation = QTextEdit(text)
        self.translation.setPlaceholderText("翻译结果会显示在这里，也可以直接手动修改。")
        self.translation.setMinimumHeight(120)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(image)
        layout.addWidget(self.translation)


class FloatingWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config = load_config()
        self.translator = Translator()
        self.hotkeys = GlobalHotkeyManager()
        self.drag_position: QPoint | None = None
        self.region_selector: RegionSelector | None = None
        self.current_bubble: ChatBubble | None = None
        self.expanded_geometry: QRect | None = None
        self.side_tab: QPushButton | None = None
        self.collapsed = False
        self.edge = "right"

        self.setWindowTitle("截图翻译")
        self.setWindowIcon(QIcon())
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(self.config.window_width, self.config.window_height)
        self._build_ui()
        self._apply_style()
        self._register_hotkeys()

        app = QApplication.instance()
        if app:
            app.installNativeEventFilter(self.hotkeys)

    def _build_ui(self) -> None:
        self.central_stack = QStackedWidget()
        self.setCentralWidget(self.central_stack)

        root = QWidget()
        root.setObjectName("root")
        self.central_stack.addWidget(root)

        self.title = QLabel("截图翻译")
        self.title.setObjectName("title")
        self.title.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))

        self.full_button = make_button("全屏", "截取全屏并翻译")
        self.region_button = make_button("选区", "框选屏幕区域并翻译")
        self.settings_button = make_button("设置", "修改快捷键和提示词")
        self.collapse_button = make_button("收起", "收缩成侧边栏")
        self.close_button = make_button("×", "退出")
        self.close_button.setFixedWidth(38)

        self.full_button.clicked.connect(self.capture_full_screen)
        self.region_button.clicked.connect(self.capture_region)
        self.settings_button.clicked.connect(self.open_settings)
        self.collapse_button.clicked.connect(lambda: self.collapse_to_edge())
        self.close_button.clicked.connect(QApplication.quit)

        header = QHBoxLayout()
        header.setContentsMargins(12, 10, 12, 6)
        header.setSpacing(8)
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.full_button)
        header.addWidget(self.region_button)
        header.addWidget(self.settings_button)
        header.addWidget(self.collapse_button)
        header.addWidget(self.close_button)

        self.scroll_body = QWidget()
        self.chat_layout = QVBoxLayout(self.scroll_body)
        self.chat_layout.setContentsMargins(12, 8, 12, 12)
        self.chat_layout.setSpacing(12)
        self.chat_layout.addStretch(1)

        self.empty_label = QLabel("点击“全屏”或“选区”开始截图翻译")
        self.empty_label.setObjectName("empty")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.chat_layout.insertWidget(0, self.empty_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.scroll_body)

        self.status = QLabel(
            f"快捷键: 全屏 {self.config.full_screen_hotkey}    选区 {self.config.region_hotkey}"
        )
        self.status.setObjectName("status")

        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(header)
        layout.addWidget(scroll)
        layout.addWidget(self.status)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget#root {
                background: #f8fafc;
                border: 1px solid #cbd5e1;
                border-radius: 10px;
            }
            QLabel#title {
                color: #172033;
            }
            QLabel#empty {
                color: #64748b;
                padding: 60px 16px;
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
            self.status.setText(
                f"快捷键: 全屏 {self.config.full_screen_hotkey}    选区 {self.config.region_hotkey}"
            )
        except Exception as exc:  # noqa: BLE001 - show actionable shortcut conflicts in-app.
            self.status.setText(str(exc))
            QMessageBox.warning(self, "快捷键注册失败", str(exc))

    def capture_full_screen(self) -> None:
        self.expand_from_edge()
        self.hide()
        QTimer.singleShot(180, self._capture_full_screen_after_hide)

    def _capture_full_screen_after_hide(self) -> None:
        pixmap = capture_desktop()
        self.show()
        self._translate_pixmap(pixmap)

    def capture_region(self) -> None:
        self.expand_from_edge()
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

    def _translate_pixmap(self, pixmap: QPixmap) -> None:
        if self.empty_label:
            self.empty_label.hide()

        bubble = ChatBubble(pixmap, "正在翻译...")
        self.current_bubble = bubble
        self.chat_layout.insertWidget(max(0, self.chat_layout.count() - 1), bubble)
        self.translator.translate(
            pixmap,
            self.config.prompt,
            on_started=lambda: self.status.setText("正在调用大模型 API..."),
            on_finished=self._translation_finished,
            on_failed=self._translation_failed,
        )

    def _translation_finished(self, text: str) -> None:
        if self.current_bubble:
            self.current_bubble.translation.setPlainText(text or "未返回翻译结果")
        self.status.setText("翻译完成，可直接编辑结果。")

    def _translation_failed(self, error: str) -> None:
        if self.current_bubble:
            self.current_bubble.translation.setPlainText(f"翻译失败:\n{error}")
        self.status.setText("翻译失败，请检查 .env、网络或模型是否支持图片输入。")

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.config, self)
        if dialog.exec_() == QDialog.Accepted:
            self.config = dialog.apply_to(self.config)
            save_config(self.config)
            self.hotkeys.unregister_all()
            self._register_hotkeys()

    def collapse_to_edge(self) -> None:
        if self.collapsed:
            return
        self.expanded_geometry = self.geometry()
        screen = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        center_x = self.geometry().center().x()
        self.edge = "left" if center_x < screen_geometry.center().x() else "right"
        width = 42
        height = 156
        x = screen_geometry.left() if self.edge == "left" else screen_geometry.right() - width + 1
        y = max(screen_geometry.top() + 40, min(self.y(), screen_geometry.bottom() - height))
        self.setFixedSize(width, height)
        self._set_collapsed_ui(True)
        self.move(x, y)
        self.collapsed = True

    def expand_from_edge(self) -> None:
        if not self.collapsed:
            return
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.resize(self.config.window_width, self.config.window_height)
        self._set_collapsed_ui(False)
        if self.expanded_geometry:
            self.setGeometry(self.expanded_geometry)
        self.collapsed = False

    def _set_collapsed_ui(self, collapsed: bool) -> None:
        if collapsed:
            if self.side_tab is None:
                self.side_tab = QPushButton("译\n图")
                self.side_tab.setObjectName("sideTab")
                self.side_tab.setCursor(Qt.PointingHandCursor)
                self.side_tab.clicked.connect(self.expand_from_edge)
                self.side_tab.setStyleSheet(
                    """
                    QPushButton#sideTab {
                        background: #2563eb;
                        color: white;
                        border: none;
                        border-radius: 8px;
                        font-weight: 700;
                        font-size: 15px;
                    }
                    QPushButton#sideTab:hover { background: #1d4ed8; }
                    """
                )
                self.central_stack.addWidget(self.side_tab)
            self.central_stack.setCurrentWidget(self.side_tab)
        else:
            self.central_stack.setCurrentIndex(0)

    def mouseDoubleClickEvent(self, event) -> None:
        if self.collapsed:
            self.expand_from_edge()
        super().mouseDoubleClickEvent(event)

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
        if not self.collapsed and self._touching_screen_edge():
            self.collapse_to_edge()
        super().mouseReleaseEvent(event)

    def _touching_screen_edge(self) -> bool:
        screen = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        margin = 4
        return self.x() <= screen_geometry.left() + margin or self.geometry().right() >= screen_geometry.right() - margin

    def closeEvent(self, event) -> None:
        self.config.window_width = max(320, self.width())
        self.config.window_height = max(420, self.height())
        save_config(self.config)
        self.hotkeys.unregister_all()
        super().closeEvent(event)


def run_app() -> int:
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(True)
    window = FloatingWindow()
    screen_geometry = virtual_geometry()
    window.move(screen_geometry.right() - window.width() - 80, screen_geometry.top() + 100)
    window.show()
    return app.exec_()
