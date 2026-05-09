from __future__ import annotations

from PyQt5.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QApplication, QWidget


def virtual_geometry() -> QRect:
    geometry = QRect()
    for screen in QApplication.screens():
        geometry = geometry.united(screen.geometry())
    return geometry


def capture_desktop() -> QPixmap:
    geometry = virtual_geometry()
    result = QPixmap(geometry.size())
    result.fill(Qt.transparent)

    painter = QPainter(result)
    for screen in QApplication.screens():
        screen_geometry = screen.geometry()
        pixmap = screen.grabWindow(0)
        target = screen_geometry.translated(-geometry.topLeft())
        painter.drawPixmap(target.topLeft(), pixmap)
    painter.end()
    return result


def crop_virtual_pixmap(pixmap: QPixmap, selection: QRect) -> QPixmap:
    geometry = virtual_geometry()
    normalized = selection.normalized()
    relative = normalized.translated(-geometry.topLeft())
    return pixmap.copy(relative)


class RegionSelector(QWidget):
    selected = pyqtSignal(QPixmap)
    canceled = pyqtSignal()

    def __init__(self, desktop_pixmap: QPixmap) -> None:
        super().__init__(None)
        self.desktop_pixmap = desktop_pixmap
        self.start_point = QPoint()
        self.end_point = QPoint()
        self.selecting = False

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        self.setGeometry(virtual_geometry())

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.start_point = event.globalPos()
            self.end_point = event.globalPos()
            self.selecting = True
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self.selecting:
            self.end_point = event.globalPos()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.selecting:
            self.selecting = False
            rect = QRect(self.start_point, self.end_point).normalized()
            self.hide()
            if rect.width() > 6 and rect.height() > 6:
                self.selected.emit(crop_virtual_pixmap(self.desktop_pixmap, rect))
            else:
                self.canceled.emit()
            self.close()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.canceled.emit()
            self.close()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.desktop_pixmap)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))

        if self.selecting:
            rect = QRect(
                self.mapFromGlobal(self.start_point),
                self.mapFromGlobal(self.end_point),
            ).normalized()
            painter.drawPixmap(rect, self.desktop_pixmap, rect)
            painter.setPen(QPen(QColor("#4da3ff"), 2))
            painter.drawRect(rect)
            painter.fillRect(rect.adjusted(1, 1, -1, -1), QColor(77, 163, 255, 28))

