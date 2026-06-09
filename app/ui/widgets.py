from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


def _clean_label(label: QLabel) -> QLabel:
    label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    label.setAutoFillBackground(False)
    label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return label


class Card(QFrame):
    def __init__(self, title: str | None = None, subtitle: str | None = None) -> None:
        super().__init__()
        self.setObjectName("Card")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(16, 16, 16, 16)
        self.layout.setSpacing(10)
        if title:
            label = _clean_label(QLabel(title))
            label.setObjectName("CardTitle")
            self.layout.addWidget(label)
        if subtitle:
            sub = _clean_label(QLabel(subtitle))
            sub.setObjectName("Subtle")
            sub.setWordWrap(True)
            self.layout.addWidget(sub)


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.setObjectName("PageHeader")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title_label = _clean_label(QLabel(title))
        title_label.setObjectName("Title")
        layout.addWidget(title_label)
        if subtitle:
            sub = _clean_label(QLabel(subtitle))
            sub.setObjectName("Subtle")
            sub.setWordWrap(True)
            layout.addWidget(sub)


class Row(QWidget):
    def __init__(self, *widgets: QWidget) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for widget in widgets:
            layout.addWidget(widget)
