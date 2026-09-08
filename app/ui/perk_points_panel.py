from pathlib import Path

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSpinBox, QPushButton, QFileDialog, QMessageBox

from app.core.perk_points import read_perk_points, patch_perk_points_copy


class PerkPointsPanel(QWidget):
    """Copy-only workflow while the observed layout awaits in-game validation."""

    def __init__(self, source_getter, parent=None):
        super().__init__(parent)
        self.source_getter = source_getter
        layout = QVBoxLayout(self)
        note = QLabel(
            "Available perk points (0–255). This edits one byte in a supported Skyrim SE save. "
            "The layout was checked against 0-point and 80-point saves; an in-game reload test is still required. "
            "Use File > Save first to include other pending edits in the test copy."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel("Open a save to read available perk points.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.value = QSpinBox()
        self.value.setRange(0, 255)
        self.value.setEnabled(False)
        layout.addWidget(self.value)
        reload_button = QPushButton("Reload points")
        reload_button.clicked.connect(self.refresh)
        layout.addWidget(reload_button)
        self.save_button = QPushButton("Save point-edited test copy…")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_copy)
        layout.addWidget(self.save_button)
        layout.addStretch()

    def refresh(self):
        self.value.setEnabled(False)
        self.save_button.setEnabled(False)
        source = self.source_getter()
        if not source:
            self.status.setText("Open a save to read available perk points.")
            return
        try:
            field = read_perk_points(source)
        except Exception as exc:
            self.status.setText(f"Perk points unavailable: {exc}")
            return
        self.value.setValue(field.value)
        self.status.setText(f"Current points: {field.value}. Choose the desired total for the copy.")
        self.value.setEnabled(True)
        self.save_button.setEnabled(True)

    def save_copy(self):
        source = self.source_getter()
        if not source:
            self.refresh()
            return
        source = Path(source)
        target, _ = QFileDialog.getSaveFileName(
            self, "Save perk-point test copy",
            str(source.with_name(source.stem + ".perks-test" + source.suffix)),
            "Skyrim Saves (*.ess);;All Files (*)",
        )
        if not target:
            return
        try:
            before = patch_perk_points_copy(source, target, self.value.value())
        except Exception as exc:
            QMessageBox.warning(self, "Perk-point copy failed", str(exc))
            return
        self.status.setText(
            f"Copy saved: {target}\nPoints: {before.value} → {self.value.value()}. "
            "Load the copy in Skyrim to confirm the displayed points."
        )
