from __future__ import annotations

from pathlib import Path
import csv
import json
import shutil
import tempfile


from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QPixmap, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.backups import make_backup
from app.core.id_database import IdDatabase, export_template
from app.core.id_coverage import build_coverage_summary, export_inventory_csv, export_reference_csv
from app.core.form_id_tools import base_reference_notes, describe_form_id, infer_plugin_name, normalize_id, resolve_xx_id
from app.core.fandom_id_importer import harvest_all_source_pages, records_to_csv_text
from app.core.mutagen_formkey_importer import harvest_mutagen_formkeys, records_to_csv_text as mutagen_records_to_csv_text
from app.core.reference_audit import audit_records, audit_to_summary_rows, write_audit_json
from app.core.raw_editor import apply_mapped_raw_edits, build_mapped_raw_fields, write_mapped_raw_edits_with_backup
from app.core.global_variables import (
    DRAGONS_ABSORBED_FORM_ID,
    DRAGONS_ABSORBED_NAME,
    patch_skyrim_dragon_souls,
    patch_skyrim_global_variables,
    read_skyrim_dragon_souls,
    read_skyrim_global_variable,
)
from app.core.inventory_lab import (
    MAX_SAFE_INVENTORY_COUNT,
    PlayerInventoryBlock,
    patch_player_inventory_counts,
    patch_player_inventory_entry_counts,
    insert_simple_player_inventory_item,
    preflight_player_inventory_insert_layout,
    build_simple_player_inventory_insert_plan,
    read_player_inventory,
    validate_inventory_amount,
)
from app.core.resources import resource_path
from app.core.quick_codes import (
    QUICK_CODE_FORMATS,
    SKYRIM_QUICK_CODE_PRESETS,
    QuickCodeDecodeError,
    decode_quick_code_text,
    generate_mass_write_code,
    generate_skyrim_quick_code_preset,
    generate_standard_write_code,
    get_skyrim_quick_code_preset,
)
from app.core.preset_patcher import (
    SKYRIM_ACTOR_VALUE_FIELDS,
    SKYRIM_ACTOR_VALUE_NAMES,
    SKYRIM_SKILL_NAMES,
    apply_skyrim_actor_value_patch,
    apply_skyrim_add_exp_patch,
    apply_skyrim_preset_patch,
    apply_skyrim_skill_patch,
    build_skyrim_actor_value_patch_plan,
    build_skyrim_add_exp_patch_plan,
    build_skyrim_preset_patch_plan,
    read_skyrim_xp_pool,
    build_skyrim_skill_patch_plan,
    read_skyrim_actor_values,
    read_skyrim_skill_values,
)
from app.core.skyrim_ess import EssDocument, EssParseError, patch_header_values, read_ess, scan_form_id_detailed
from app.core.live_player import patch_live_player_values, read_live_player_fields
from app.core.race_editor import SKYRIM_RACES, patch_skyrim_player_race, read_skyrim_race_mapping, race_from_editor_id
from app.core.console_commands import build_console_command
from app.core.magic_lab import MagicScanResult, magic_hits_to_csv, magic_kind, magic_records_from_database, scan_magic
from app.core.magic_actions import MagicCheckboxAction, build_magic_command_script
from app.core.magic_patcher import apply_magic_learned_patch, build_magic_learned_patch_plan
from app.core.shout_patcher import apply_shout_word_patch, build_shout_word_patch_plan
from app.ui.theme import THEMES
from app.ui.widgets import Card, PageHeader


class NoFocusDelegate(QStyledItemDelegate):
    """Paint list/table items without the Windows dotted text focus rectangle."""

    def paint(self, painter, option, index):  # type: ignore[override]
        clean_option = QStyleOptionViewItem(option)
        clean_option.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, clean_option, index)


class CountSpinBoxDelegate(NoFocusDelegate):
    """A bounded count editor that keeps the current value visible while editing."""

    def createEditor(self, parent, option, index):  # type: ignore[override]
        editor = QSpinBox(parent)
        editor.setFrame(False)
        editor.setRange(0, MAX_SAFE_INVENTORY_COUNT)
        editor.setKeyboardTracking(False)
        return editor

    def setEditorData(self, editor, index):  # type: ignore[override]
        text = str(index.data() or "0").replace(",", "").strip()
        try:
            value = validate_inventory_amount(int(text or "0"))
        except Exception:
            value = 0
        editor.setValue(value)
        editor.selectAll()

    def setModelData(self, editor, model, index):  # type: ignore[override]
        model.setData(index, str(editor.value()))

    def updateEditorGeometry(self, editor, option, index):  # type: ignore[override]
        editor.setGeometry(option.rect)




class RawValueDelegate(NoFocusDelegate):
    """Readable editor for Raw Editor mapped values.

    The normal table editor can become nearly invisible on selected dark rows
    because the native delegate inherits the selected-cell palette.  This
    delegate gives the inline editor a high-contrast palette and a little more
    padding so double-click edits are readable.
    """

    def createEditor(self, parent, option, index):  # type: ignore[override]
        editor = QLineEdit(parent)
        editor.setFrame(True)
        editor.setMinimumHeight(max(30, option.rect.height() + 4))
        editor.setStyleSheet(
            "QLineEdit {"
            " background: #FFFFFF;"
            " color: #111827;"
            " border: 2px solid #7EA2D6;"
            " border-radius: 6px;"
            " padding: 4px 8px;"
            " selection-background-color: #2563EB;"
            " selection-color: #FFFFFF;"
            "}"
        )
        return editor

    def setEditorData(self, editor, index):  # type: ignore[override]
        editor.setText(str(index.data(Qt.ItemDataRole.EditRole) or index.data(Qt.ItemDataRole.DisplayRole) or ""))
        editor.selectAll()

    def setModelData(self, editor, model, index):  # type: ignore[override]
        model.setData(index, editor.text().strip())

    def updateEditorGeometry(self, editor, option, index):  # type: ignore[override]
        rect = option.rect.adjusted(2, 2, -2, -2)
        editor.setGeometry(rect)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Skyrim Save Lab - synced working save build")
        icon_path = resource_path("icons", "skyrim.png")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1280, 820)
        self.current_save: Path | None = None
        self.current_doc: EssDocument | None = None
        self.working_save_bytes: bytes | None = None
        self.working_save_dirty: bool = False
        self.working_save_label: str = ""
        self.current_inventory: PlayerInventoryBlock | None = None
        self.inventory_dirty_counts: dict[int, int] = {}
        # Missing-item additions are staged here and written by Save Edits,
        # so all inventory edits follow one obvious save workflow.
        self.inventory_pending_adds: dict[str, dict[str, object]] = {}
        self.inventory_row_offsets: dict[int, int] = {}
        self.inventory_row_editable: dict[int, bool] = {}
        self.inventory_row_original_counts: dict[int, int] = {}
        self.inventory_row_entries: dict[int, object] = {}
        self.inventory_insert_layout_preflight: tuple[bool, str] | None = None
        self.inventory_selected_offset: int | None = None
        self.inventory_show_formids = False
        self.inventory_active_category = "All"
        self.inventory_categories: list[str] = []
        self.INV_COL_ITEM = 0
        self.INV_COL_COUNT = 1
        self.INV_COL_CATEGORY = 2
        self.INV_COL_STATUS = 3
        self.INV_COL_NOTE = 4
        self._loading_inventory_table = False
        self._updating_inventory_editor = False
        self.db = IdDatabase()
        self.raw_dirty_fields: dict[str, str] = {}
        self.raw_field_rows: list[object] = []
        self._loading_raw_json = False
        self._loading_raw_table = False
        self.general_inventory_widgets: dict[str, tuple[QSpinBox, QLabel]] = {}
        self.general_inventory_status: dict[str, QLabel] = {}
        self.common_global_widgets: dict[str, tuple[QSpinBox, QLabel]] = {}
        self.common_global_original: dict[str, int] = {}
        self._syncing_common_global = False
        self.skill_value_spins: dict[int, QDoubleSpinBox] = {}
        self.skill_original_values: dict[int, float] = {}
        self._loading_skill_values = False
        self.actor_value_spins: dict[int, QDoubleSpinBox] = {}
        self.actor_original_values: dict[int, float] = {}
        self._loading_actor_values = False
        self.current_magic_scan: MagicScanResult | None = None
        self.magic_pending_changes: dict[str, MagicCheckboxAction] = {}
        self._loading_magic_tables = False

        self._init_actions()
        self._init_ui()
        self._load_default_database()
        self.apply_theme("Obsidian")

    def _init_actions(self) -> None:
        self.open_action = QAction("Open Save…", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.open_save_dialog)

        self.save_inventory_action = QAction("Save Working Save", self)
        self.save_inventory_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_inventory_action.triggered.connect(self.save_working_save)

        self.save_as_action = QAction("Save Working Save As…", self)
        self.save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.save_as_action.triggered.connect(self.save_working_save_as)

        self.backup_action = QAction("Create Backup", self)
        self.backup_action.triggered.connect(self.create_backup)

        self.export_json_action = QAction("Export Parsed JSON…", self)
        self.export_json_action.triggered.connect(self.export_parsed_json)

        self.exit_action = QAction("Exit", self)
        self.exit_action.triggered.connect(self.close)

        self.theme_actions: dict[str, QAction] = {}
        for name in THEMES:
            act = QAction(name, self)
            act.triggered.connect(lambda checked=False, n=name: self.apply_theme(n))
            self.theme_actions[name] = act

        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.save_inventory_action)
        file_menu.addAction(self.save_as_action)
        file_menu.addAction(self.backup_action)
        file_menu.addSeparator()
        file_menu.addAction(self.export_json_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        view_menu = self.menuBar().addMenu("Themes")
        for act in self.theme_actions.values():
            view_menu.addAction(act)

    def _init_ui(self) -> None:
        root = QWidget()
        root.setObjectName("AppRoot")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.side = QListWidget()
        self.side.setObjectName("SideRail")
        self.side.setFixedWidth(220)
        self.side.setSpacing(2)
        self.side.setFrameShape(QFrame.Shape.NoFrame)
        self.side.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.side.setItemDelegate(NoFocusDelegate(self.side))
        self.side.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for title in ["Save / Load", "General", "Player Inventory", "Magic", "Plugins", "Reference IDs", "Raw Editor", "About"]:
            self.side.addItem(QListWidgetItem(title))
        self.side.currentRowChanged.connect(self._switch_page)
        root_layout.addWidget(self.side)

        self.stack = QStackedWidget()
        root_layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.stack.addWidget(self._build_save_page())
        self.stack.addWidget(self._build_general_page())
        self.stack.addWidget(self._build_inventory_page())
        self.stack.addWidget(self._build_magic_page())
        self.stack.addWidget(self._build_plugins_page())
        self.stack.addWidget(self._build_database_page())
        self.stack.addWidget(self._build_raw_page())
        self.stack.addWidget(self._build_about_page())
        self.side.setCurrentRow(0)

    def _page(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName("ContentPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        layout.addWidget(PageHeader(title, subtitle))
        return page, layout

    def _form_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        label.setAutoFillBackground(False)
        label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        label.setObjectName("FormLabel")
        return label

    def _confirm_long_text(self, title: str, intro: str, body: str, accept_text: str = "Continue", cancel_text: str = "Cancel") -> bool:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setModal(True)
        dialog.resize(760, 640)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        intro_label = QLabel(intro)
        intro_label.setWordWrap(True)
        layout.addWidget(intro_label)

        body_view = QPlainTextEdit()
        body_view.setReadOnly(True)
        body_view.setPlainText(body)
        body_view.setMinimumHeight(420)
        layout.addWidget(body_view, 1)

        buttons = QDialogButtonBox()
        accept_btn = buttons.addButton(accept_text, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(cancel_text, QDialogButtonBox.ButtonRole.RejectRole)
        accept_btn.setDefault(True)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        try:
            screen = QApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                max_w = max(640, int(avail.width() * 0.72))
                max_h = max(520, int(avail.height() * 0.82))
                dialog.resize(min(max_w, 900), min(max_h, 760))
        except Exception:
            pass

        return dialog.exec() == QDialog.DialogCode.Accepted

    def _clean_table_focus(self, table: QTableWidget) -> None:
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setItemDelegate(NoFocusDelegate(table))

    def _build_save_page(self) -> QWidget:
        page, layout = self._page(
            "Save / Load",
            "Open a Skyrim .ess save, inspect it safely, create backups, and export parsed metadata.",
        )
        card = Card("Current Save")
        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        open_btn = QPushButton("Open .ess")
        open_btn.clicked.connect(self.open_save_dialog)
        backup_btn = QPushButton("Backup")
        backup_btn.clicked.connect(self.create_backup)
        json_btn = QPushButton("Export JSON")
        json_btn.clicked.connect(self.export_parsed_json)
        row.addWidget(self.path_edit, 1)
        row.addWidget(open_btn)
        row.addWidget(backup_btn)
        row.addWidget(json_btn)
        card.layout.addLayout(row)
        self.summary_table = QTableWidget(0, 2)
        self.summary_table.setHorizontalHeaderLabels(["Field", "Value"])
        self.summary_table.horizontalHeader().setStretchLastSection(True)
        self.summary_table.verticalHeader().setVisible(False)
        self.summary_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._clean_table_focus(self.summary_table)
        card.layout.addWidget(self.summary_table)
        layout.addWidget(card)

        notes = Card("Safety Notes")
        label = QLabel(
            "This first pass writes only fixed-width header values when you use Save As. "
            "Strings, inventory records, quests, and change forms stay untouched until we map the exact structures."
        )
        label.setWordWrap(True)
        notes.layout.addWidget(label)
        layout.addWidget(notes)

        backups = Card("Backups / Restore", "Editor-created backups live next to the save as .bak files. Restore copies the selected backup over the loaded save after making one more safety backup.")
        backup_buttons = QHBoxLayout()
        refresh_backups = QPushButton("Refresh Backups")
        refresh_backups.clicked.connect(self.refresh_backup_table)
        restore_backup = QPushButton("Restore Selected Backup")
        restore_backup.clicked.connect(self.restore_selected_backup)
        backup_buttons.addStretch(1)
        backup_buttons.addWidget(refresh_backups)
        backup_buttons.addWidget(restore_backup)
        backups.layout.addLayout(backup_buttons)
        self.backup_table = QTableWidget(0, 3)
        self.backup_table.setHorizontalHeaderLabels(["Backup", "Modified", "Size"])
        self.backup_table.horizontalHeader().setStretchLastSection(True)
        self.backup_table.verticalHeader().setVisible(False)
        self.backup_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.backup_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.backup_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._clean_table_focus(self.backup_table)
        backups.layout.addWidget(self.backup_table)
        layout.addWidget(backups)
        layout.addStretch(1)
        return page

    def _build_general_page(self) -> QWidget:
        page, layout = self._page(
            "General",
            "Direct editable player, inventory, skill, and stat values with safer validated patches.",
        )
        layout.setSpacing(12)

        action_card = Card()
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        reload_btn = QPushButton("Reload")
        reload_btn.setToolTip("Reload General values from the currently opened save.")
        reload_btn.clicked.connect(self.reload_current_save)
        preview_btn = QPushButton("Preview")
        preview_btn.setToolTip("Preview changed General values before writing anything.")
        preview_btn.clicked.connect(self.preview_general_edits)
        save_as = QPushButton("Save Copy…")
        save_as.setToolTip("Write General edits to a new save copy.")
        save_as.clicked.connect(self.save_general_as)
        save_general = QPushButton("Save Edits")
        save_general.setToolTip("Back up the loaded save, then write General edits into it.")
        save_general.clicked.connect(self.save_general_edits)
        action_hint = QLabel("Open a save, edit a focused tab, then Save Edits or Save Copy.")
        action_hint.setObjectName("Subtle")
        action_row.addWidget(action_hint, 1)
        action_row.addWidget(reload_btn)
        action_row.addWidget(preview_btn)
        action_row.addWidget(save_as)
        action_row.addWidget(save_general)
        action_card.layout.addLayout(action_row)
        layout.addWidget(action_card)

        self.general_tabs = QTabWidget()
        self.general_tabs.setObjectName("GeneralTabs")
        self.general_tabs.setDocumentMode(True)
        try:
            self.general_tabs.tabBar().setDrawBase(False)
        except AttributeError:
            pass

        def scroll_tab() -> tuple[QWidget, QVBoxLayout]:
            tab = QWidget()
            tab.setObjectName("GeneralTabPage")
            tab.setAutoFillBackground(False)
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(0, 0, 0, 0)
            tab_layout.setSpacing(0)
            scroll = QScrollArea()
            scroll.setObjectName("GeneralTabScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setAutoFillBackground(False)
            try:
                scroll.viewport().setObjectName("GeneralTabViewport")
                scroll.viewport().setAutoFillBackground(False)
            except Exception:
                pass
            content = QWidget()
            content.setObjectName("GeneralTabContent")
            content.setAutoFillBackground(False)
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(2, 10, 2, 2)
            content_layout.setSpacing(12)
            scroll.setWidget(content)
            tab_layout.addWidget(scroll)
            return tab, content_layout

        player_tab, player_layout = scroll_tab()
        player_grid = QGridLayout()
        player_grid.setHorizontalSpacing(12)
        player_grid.setVerticalSpacing(12)

        identity_card = Card("Player")
        identity_form = QFormLayout()
        identity_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        identity_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        identity_form.setHorizontalSpacing(12)
        identity_form.setVerticalSpacing(10)
        self.name_view = QLineEdit()
        self.name_view.setPlaceholderText("Player name")
        self.name_view.textChanged.connect(self._update_name_slot_hint)
        self.name_slot_label = QLabel("")
        self.name_slot_label.setObjectName("FormHint")
        self.location_view = QLineEdit()
        self.location_view.setReadOnly(True)
        self.race_combo = QComboBox()
        for race in SKYRIM_RACES:
            self.race_combo.addItem(f"{race.display} ({race.editor_id})", race.editor_id)
        self.race_combo.setToolTip("Experimental: writes the live player race RefID pair in ChangeForm 400014, the optional 400007 mirror, and the header race text.")
        self.game_date_view = QLineEdit()
        self.game_date_view.setReadOnly(True)
        for label, widget in [
            ("Player Name", self.name_view),
            ("Name Slot", self.name_slot_label),
            ("Location", self.location_view),
            ("Race", self.race_combo),
            ("Game Date", self.game_date_view),
        ]:
            identity_form.addRow(self._form_label(label), widget)
        identity_card.layout.addLayout(identity_form)

        progress_card = Card("Progress")
        progress_form = QFormLayout()
        progress_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        progress_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        progress_form.setHorizontalSpacing(12)
        progress_form.setVerticalSpacing(10)
        self.level_spin = QSpinBox()
        self.level_spin.setRange(1, 65535)
        self.sex_combo = QComboBox()
        self.sex_combo.addItems(["Male", "Female"])
        self.cur_exp_spin = QDoubleSpinBox()
        self.cur_exp_spin.setRange(-999999999, 999999999)
        self.cur_exp_spin.setDecimals(3)
        self.need_exp_spin = QDoubleSpinBox()
        self.need_exp_spin.setRange(-999999999, 999999999)
        self.need_exp_spin.setDecimals(3)
        for label, widget in [
            ("Level", self.level_spin),
            ("Sex", self.sex_combo),
            ("XP Pool", self.cur_exp_spin),
            ("Needed XP", self.need_exp_spin),
        ]:
            progress_form.addRow(self._form_label(label), widget)
        progress_card.layout.addLayout(progress_form)

        player_grid.addWidget(identity_card, 0, 0)
        player_grid.addWidget(progress_card, 0, 1)
        player_grid.setColumnStretch(0, 3)
        player_grid.setColumnStretch(1, 2)
        player_layout.addLayout(player_grid)
        player_note = QLabel(
            "Player Name and Race use mapped live player data when found. Level writes the live field only on saves where that optional field exists; early saves may only sync the save-header level. Race changing is experimental: test on a backup first. XP Pool edits the real payload value used by the +EXP command."
        )
        player_note.setWordWrap(True)
        player_note.setObjectName("Subtle")
        player_layout.addWidget(player_note)

        player_layout.addStretch(1)
        self.general_tabs.addTab(player_tab, "Player")

        skills_tab, skills_layout = scroll_tab()
        skills_card = Card(
            "Individual Skills",
            "Directly edit each skill slot after the editor validates the 18-float skill block. The original code writes 0x12 entries, which is 18 skills.",
        )
        skill_actions = QHBoxLayout()
        skill_actions.setSpacing(8)
        reload_skills_btn = QPushButton("Reload Skills")
        reload_skills_btn.clicked.connect(self.refresh_skill_values_from_save)
        set_all_100_btn = QPushButton("Set All 100")
        set_all_100_btn.clicked.connect(lambda _checked=False: self.set_all_skill_values(100.0))
        set_all_999_btn = QPushButton("Set All 999")
        set_all_999_btn.clicked.connect(lambda _checked=False: self.set_all_skill_values(999.0))
        set_all_999999_btn = QPushButton("Set All 999,999")
        set_all_999999_btn.clicked.connect(lambda _checked=False: self.set_all_skill_values(999999.0))
        set_all_1_btn = QPushButton("Set All 1")
        set_all_1_btn.clicked.connect(lambda _checked=False: self.set_all_skill_values(1.0))
        preview_skills_btn = QPushButton("Preview Skill Edits")
        preview_skills_btn.clicked.connect(self.preview_skill_edits)
        save_skills_copy_btn = QPushButton("Save Copy…")
        save_skills_copy_btn.clicked.connect(self.save_skill_edits_as)
        apply_skills_btn = QPushButton("Apply To Save")
        apply_skills_btn.clicked.connect(self.apply_skill_edits_to_save)
        self.skill_status_label = QLabel("Open a save to detect the skill block.")
        self.skill_status_label.setObjectName("Subtle")
        self.skill_status_label.setWordWrap(True)
        skill_actions.addWidget(self.skill_status_label, 1)
        skill_actions.addWidget(reload_skills_btn)
        skill_actions.addWidget(set_all_1_btn)
        skill_actions.addWidget(set_all_100_btn)
        skill_actions.addWidget(set_all_999_btn)
        skill_actions.addWidget(set_all_999999_btn)
        skill_actions.addWidget(preview_skills_btn)
        skill_actions.addWidget(save_skills_copy_btn)
        skill_actions.addWidget(apply_skills_btn)
        skills_card.layout.addLayout(skill_actions)

        skill_grid = QGridLayout()
        skill_grid.setHorizontalSpacing(14)
        skill_grid.setVerticalSpacing(8)
        self.skill_value_spins.clear()
        for index, skill_name in enumerate(SKYRIM_SKILL_NAMES):
            group_col = index // 6
            row = index % 6
            label = self._form_label(skill_name)
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 999999.0)
            spin.setDecimals(3)
            spin.setSingleStep(1.0)
            spin.setGroupSeparatorShown(True)
            spin.setKeyboardTracking(False)
            spin.setEnabled(False)
            spin.valueChanged.connect(lambda _value, i=index: self._mark_skill_values_changed())
            self.skill_value_spins[index] = spin
            skill_grid.addWidget(label, row, group_col * 2)
            skill_grid.addWidget(spin, row, group_col * 2 + 1)
            skill_grid.setColumnStretch(group_col * 2 + 1, 1)
        skills_card.layout.addLayout(skill_grid)

        self.skill_preview_output = QPlainTextEdit()
        self.skill_preview_output.setReadOnly(True)
        self.skill_preview_output.setMinimumHeight(220)
        self.skill_preview_output.setPlaceholderText("Reload skills, change one or more values, then preview before writing.")
        skills_card.layout.addWidget(self.skill_preview_output)
        skill_note = QLabel(
            "Skill labels follow the standard Skyrim skill order used by this preset block. Normal max is 100; test max is 999,999 in this build. 1,000 was confirmed working; 999,999,999 was unstable. Make a backup first."
        )
        skill_note.setWordWrap(True)
        skill_note.setObjectName("Subtle")
        skills_card.layout.addWidget(skill_note)
        skills_layout.addWidget(skills_card)
        skills_layout.addStretch(1)
        self.general_tabs.addTab(skills_tab, "Skills")

        stats_tab, stats_layout = scroll_tab()
        stats_card = Card(
            "Actor Values",
            "Directly edit Health, Magicka, Stamina, and Carry Weight. Carry Weight is handled as a total: base ActorValue 32 plus the Save Wizard modifier slot when present.",
        )
        stats_actions = QHBoxLayout()
        stats_actions.setSpacing(8)
        reload_stats_btn = QPushButton("Reload Stats")
        reload_stats_btn.clicked.connect(self.refresh_actor_values_from_save)
        set_hms_btn = QPushButton("Set H/M/S 1000")
        set_hms_btn.clicked.connect(lambda _checked=False: self.set_vital_actor_values(1000.0))
        set_carry_btn = QPushButton("Set Carry Weight 1B")
        set_carry_btn.clicked.connect(lambda _checked=False: self.set_carry_actor_values(1_000_000_000.0))
        preview_stats_btn = QPushButton("Preview Stat Edits")
        preview_stats_btn.clicked.connect(self.preview_actor_value_edits)
        save_stats_copy_btn = QPushButton("Save Copy…")
        save_stats_copy_btn.clicked.connect(self.save_actor_value_edits_as)
        apply_stats_btn = QPushButton("Apply To Save")
        apply_stats_btn.clicked.connect(self.apply_actor_value_edits_to_save)
        self.actor_status_label = QLabel("Open a save to detect player actor values.")
        self.actor_status_label.setObjectName("Subtle")
        self.actor_status_label.setWordWrap(True)
        stats_actions.addWidget(self.actor_status_label, 1)
        stats_actions.addWidget(reload_stats_btn)
        stats_actions.addWidget(set_hms_btn)
        stats_actions.addWidget(set_carry_btn)
        stats_actions.addWidget(preview_stats_btn)
        stats_actions.addWidget(save_stats_copy_btn)
        stats_actions.addWidget(apply_stats_btn)
        stats_card.layout.addLayout(stats_actions)

        stats_grid = QGridLayout()
        stats_grid.setHorizontalSpacing(14)
        stats_grid.setVerticalSpacing(8)
        self.actor_value_spins.clear()
        for index, (actor_id, stat_name) in enumerate(SKYRIM_ACTOR_VALUE_FIELDS):
            group_col = index // 4
            row = index % 4
            label = self._form_label(stat_name)
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 2_000_000_000.0 if actor_id == 320 else 1_000_000_000.0)
            spin.setDecimals(3)
            spin.setSingleStep(10.0 if actor_id == 320 else 1.0)
            spin.setKeyboardTracking(False)
            spin.setEnabled(False)
            spin.valueChanged.connect(lambda _value, i=actor_id: self._mark_actor_values_changed())
            self.actor_value_spins[int(actor_id)] = spin
            stats_grid.addWidget(label, row, group_col * 2)
            stats_grid.addWidget(spin, row, group_col * 2 + 1)
            stats_grid.setColumnStretch(group_col * 2 + 1, 1)
        stats_card.layout.addLayout(stats_grid)

        self.actor_preview_output = QPlainTextEdit()
        self.actor_preview_output.setReadOnly(True)
        self.actor_preview_output.setMinimumHeight(220)
        self.actor_preview_output.setPlaceholderText("Reload stats, change Carry Weight / Health / Magicka / Stamina, then preview before writing.")
        stats_card.layout.addWidget(self.actor_preview_output)
        stats_note = QLabel(
            "Rate fields were removed because they were not resolving consistently. Carry Weight now displays the intended total; when a Save Wizard modifier slot exists the editor writes total minus base, otherwise it safely falls back to ActorValue 32."
        )
        stats_note.setWordWrap(True)
        stats_note.setObjectName("Subtle")
        stats_card.layout.addWidget(stats_note)
        stats_layout.addWidget(stats_card)
        stats_layout.addStretch(1)
        self.general_tabs.addTab(stats_tab, "Stats")

        common_tab, common_layout = scroll_tab()
        essentials = Card("Common Save Values", "Gold/Lockpicks sync from Player Inventory. Dragon Souls sync from the live actor-value field (ChangeForm 400014).")
        common_action_row = QHBoxLayout()
        self.common_inventory_status = QLabel("Open a save to sync Gold / Lockpicks / Dragon Souls.")
        self.common_inventory_status.setObjectName("Subtle")
        self.common_inventory_status.setWordWrap(True)
        sync_common_btn = QPushButton("Sync From Inventory")
        sync_common_btn.clicked.connect(self.sync_common_inventory_values)
        preview_common_btn = QPushButton("Preview Common Edits")
        preview_common_btn.clicked.connect(self.preview_common_inventory_edits)
        save_common_copy_btn = QPushButton("Save Common Copy…")
        save_common_copy_btn.clicked.connect(self.save_common_inventory_as)
        apply_common_btn = QPushButton("Apply Common To Save")
        apply_common_btn.clicked.connect(self.save_common_inventory_edits)
        common_action_row.addWidget(self.common_inventory_status, 1)
        common_action_row.addWidget(sync_common_btn)
        common_action_row.addWidget(preview_common_btn)
        common_action_row.addWidget(save_common_copy_btn)
        common_action_row.addWidget(apply_common_btn)
        essentials.layout.addLayout(common_action_row)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 2)
        self.general_inventory_widgets.clear()
        for row, (key, label, form_id) in enumerate(self._general_inventory_targets()):
            spin = QSpinBox()
            spin.setRange(0, MAX_SAFE_INVENTORY_COUNT)
            spin.setKeyboardTracking(False)
            status = QLabel("Open a save to detect this value.")
            status.setObjectName("Subtle")
            status.setWordWrap(True)
            spin.valueChanged.connect(lambda _value, k=key: self._general_inventory_value_changed(k))
            self.general_inventory_widgets[key] = (spin, status)
            grid.addWidget(self._form_label(label), row, 0)
            grid.addWidget(spin, row, 1)
            grid.addWidget(QLabel(form_id), row, 2)
            grid.addWidget(status, row, 3)
        essentials.layout.addLayout(grid)

        global_grid = QGridLayout()
        global_grid.setHorizontalSpacing(12)
        global_grid.setVerticalSpacing(10)
        global_grid.setColumnStretch(1, 1)
        global_grid.setColumnStretch(3, 2)
        self.common_global_widgets.clear()
        for row, (key, label, form_id) in enumerate(self._common_global_targets()):
            spin = QSpinBox()
            spin.setRange(0, MAX_SAFE_INVENTORY_COUNT)
            spin.setKeyboardTracking(False)
            status = QLabel("Open a save to detect this value.")
            status.setObjectName("Subtle")
            status.setWordWrap(True)
            spin.valueChanged.connect(lambda _value, k=key: self._common_global_value_changed(k))
            self.common_global_widgets[key] = (spin, status)
            global_grid.addWidget(self._form_label(label), row, 0)
            global_grid.addWidget(spin, row, 1)
            global_grid.addWidget(QLabel("400014 +0x49A5" if str(form_id).upper() == DRAGONS_ABSORBED_FORM_ID else form_id), row, 2)
            global_grid.addWidget(status, row, 3)
        essentials.layout.addLayout(global_grid)
        note = QLabel(
            "Gold/Lockpicks patch exact mapped inventory rows. Dragon Souls patches the live actor-value field in ChangeForm 400014. The DragonsAbsorbed global (0001C0F2 / 41 C0 F2) is not the spendable souls pool. Missing values stay disabled so the editor never guesses or inserts blind data."
        )
        note.setWordWrap(True)
        note.setObjectName("Subtle")
        essentials.layout.addWidget(note)
        common_layout.addWidget(essentials)
        common_layout.addStretch(1)
        self.general_tabs.addTab(common_tab, "Common")

        layout.addWidget(self.general_tabs, 1)
        return page

    def _build_header_page(self) -> QWidget:
        # Backward-compatible alias for older code paths; the side rail now shows this as General.
        return self._build_general_page()

    def _build_inventory_page(self) -> QWidget:
        page, layout = self._page(
            "Player Inventory",
            "Edit existing inventory counts, import/export CSVs, and find item IDs without leaving this page.",
        )

        controls = Card("Inventory Controls", "Select an item, change New Count, then save when ready.")

        action_row = QHBoxLayout()
        reload_btn = QPushButton("Reload")
        reload_btn.setToolTip("Reload the inventory from the current save.")
        reload_btn.clicked.connect(self.refresh_inventory)
        save_changes_btn = QPushButton("Save Edits")
        save_changes_btn.setToolTip("Back up the current save, then write staged existing-row count changes into this save file. Shortcut: Ctrl+S on this page.")
        save_changes_btn.clicked.connect(self.save_inventory_count_changes)
        save_as_btn = QPushButton("Save Copy…")
        save_as_btn.setToolTip("Write all staged inventory edits to a new save copy.")
        save_as_btn.clicked.connect(self.save_inventory_count_as)
        revert_btn = QPushButton("Revert Counts")
        revert_btn.clicked.connect(self.revert_inventory_count_edits)
        self.inv_queued_label = QLabel("No unsaved inventory count edits")
        self.inv_queued_label.setObjectName("Subtle")
        action_row.addWidget(reload_btn)
        action_row.addWidget(revert_btn)
        action_row.addStretch(1)
        action_row.addWidget(self.inv_queued_label)
        action_row.addWidget(save_as_btn)
        action_row.addWidget(save_changes_btn)
        controls.layout.addLayout(action_row)

        self.inv_form_edit = QLineEdit(); self.inv_form_edit.setVisible(False)
        self.inv_name_edit = QLineEdit(); self.inv_name_edit.setReadOnly(True); self.inv_name_edit.setPlaceholderText("Select an inventory row")
        self.inv_selected_formid = QLineEdit(); self.inv_selected_formid.setReadOnly(True); self.inv_selected_formid.setPlaceholderText("FormID")
        self.inv_amount_spin = QSpinBox(); self.inv_amount_spin.setRange(0, MAX_SAFE_INVENTORY_COUNT); self.inv_amount_spin.setValue(1)
        self.inv_amount_spin.setToolTip(f"Safe maximum: {MAX_SAFE_INVENTORY_COUNT:,}")
        self.inv_amount_spin.setAccelerated(True)
        self.inv_amount_spin.valueChanged.connect(self.set_selected_inventory_count)
        copy_id_btn = QPushButton("Copy ID")
        copy_id_btn.clicked.connect(self.copy_selected_inventory_id)
        copy_additem_inv_btn = QPushButton("Copy AddItem")
        copy_additem_inv_btn.clicked.connect(self.copy_selected_inventory_additem_command)

        editor_grid = QGridLayout()
        editor_grid.setHorizontalSpacing(10)
        editor_grid.setVerticalSpacing(8)
        editor_grid.addWidget(self._form_label("Selected Item"), 0, 0)
        editor_grid.addWidget(self.inv_name_edit, 0, 1, 1, 5)
        editor_grid.addWidget(self._form_label("FormID"), 0, 6)
        editor_grid.addWidget(self.inv_selected_formid, 0, 7)
        editor_grid.addWidget(copy_id_btn, 0, 8)
        editor_grid.addWidget(copy_additem_inv_btn, 0, 9)
        editor_grid.addWidget(self._form_label("New Count"), 1, 0)
        editor_grid.addWidget(self.inv_amount_spin, 1, 1)
        editor_grid.setColumnStretch(1, 2)
        editor_grid.setColumnStretch(5, 1)
        controls.layout.addLayout(editor_grid)

        quick_row = QHBoxLayout()
        for label, amount in [("Remove / Set 0", 0), ("Set 1", 1), ("Set 10", 10), ("Set 99", 99), ("Set 999", 999), ("Set 99,999", 99999)]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked=False, a=amount: self.set_selected_inventory_amount(a))
            quick_row.addWidget(btn)
        restore_selected_btn = QPushButton("Restore Selected")
        restore_selected_btn.clicked.connect(self.restore_selected_inventory_count)
        export_inv_btn = QPushButton("Export CSV")
        export_inv_btn.clicked.connect(self.export_inventory_csv_dialog)
        import_inv_btn = QPushButton("Import CSV")
        import_inv_btn.clicked.connect(self.import_inventory_csv_dialog)
        export_unknown_btn = QPushButton("Export Unknown IDs")
        export_unknown_btn.clicked.connect(self.export_unknown_inventory_ids_dialog)
        quick_row.addWidget(restore_selected_btn)
        quick_row.addStretch(1)
        quick_row.addWidget(import_inv_btn)
        quick_row.addWidget(export_inv_btn)
        quick_row.addWidget(export_unknown_btn)
        controls.layout.addLayout(quick_row)

        # Keep the preview model available for existing helper methods, but do not show another table in the main UI.
        self.inv_preview_table = QTableWidget(0, 4)
        self.inv_preview_table.setHorizontalHeaderLabels(["Item", "FormID", "New Count", "Change"])
        self.inv_preview_table.setVisible(False)

        note = self._form_label(
            f"Counts are clamped to 0–{MAX_SAFE_INVENTORY_COUNT:,}. Existing rows are safe direct edits. Dormant zero-count rows can be re-added safely. Truly missing base-game items can be staged when this save passes the direct-insert preflight; plugin/light/temp items stay blocked until FormIDArray mapping is added."
        )
        note.setObjectName("Subtle")
        note.setWordWrap(True)
        controls.layout.addWidget(note)
        layout.addWidget(controls)

        self.inventory_workspace_tabs = QTabWidget()
        self.inventory_workspace_tabs.setDocumentMode(True)
        self.inventory_workspace_tabs.setObjectName("InventoryWorkspaceTabs")

        inventory_tab = QWidget()
        inventory_layout = QVBoxLayout(inventory_tab)
        inventory_layout.setContentsMargins(0, 0, 0, 0)
        inventory_layout.setSpacing(10)

        inventory_filter_row = QHBoxLayout()
        self.inventory_filter_edit = QLineEdit()
        self.inventory_filter_edit.setPlaceholderText("Filter current inventory by item, category, FormID, or note…")
        self.inventory_filter_edit.textChanged.connect(self._apply_inventory_filter)
        inventory_filter_row.addWidget(self._form_label("Filter"))
        inventory_filter_row.addWidget(self.inventory_filter_edit, 1)
        self.inv_storage_tip_btn = QPushButton("Storage Info")
        self.inv_storage_tip_btn.setToolTip("Select an inventory row to see exact save-storage details here.")
        self.inv_storage_tip_btn.clicked.connect(self.show_inventory_storage_info_dialog)
        copy_storage_btn = QPushButton("Copy Info")
        copy_storage_btn.setToolTip("Copy exact save-storage details for the selected inventory row.")
        copy_storage_btn.clicked.connect(self.copy_inventory_storage_info)
        export_storage_btn = QPushButton("Export Storage CSV")
        export_storage_btn.setToolTip("Export storage offsets/count metadata for every decoded inventory row.")
        export_storage_btn.clicked.connect(self.export_inventory_storage_csv_dialog)
        inventory_filter_row.addWidget(self.inv_storage_tip_btn)
        inventory_filter_row.addWidget(copy_storage_btn)
        inventory_filter_row.addWidget(export_storage_btn)
        inventory_layout.addLayout(inventory_filter_row)

        self.inventory_tabs = QTabBar()
        self.inventory_tabs.setObjectName("InventoryTabs")
        self.inventory_tabs.setDrawBase(False)
        self.inventory_tabs.setUsesScrollButtons(True)
        self.inventory_tabs.setExpanding(False)
        self.inventory_tabs.currentChanged.connect(self._inventory_tab_changed)
        inventory_layout.addWidget(self.inventory_tabs)

        self.inventory_table = QTableWidget(0, 5)
        self.inventory_table.setHorizontalHeaderLabels(["Item", "New Count", "Category", "Status", "Note"])
        self.inventory_table.horizontalHeader().setStretchLastSection(True)
        self.inventory_table.verticalHeader().setVisible(False)
        self.inventory_table.verticalHeader().setDefaultSectionSize(34)
        self.inventory_table.setAlternatingRowColors(True)
        self.inventory_table.setShowGrid(False)
        self.inventory_table.setSortingEnabled(False)
        self.inventory_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.inventory_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.inventory_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.inventory_table.setItemDelegate(NoFocusDelegate(self.inventory_table))
        self.inventory_table.setItemDelegateForColumn(self.INV_COL_COUNT, CountSpinBoxDelegate(self.inventory_table))
        self.inventory_table.itemSelectionChanged.connect(self._inventory_selection_changed)
        self.inventory_table.itemChanged.connect(self._inventory_count_item_changed)
        self.inventory_table.setColumnWidth(self.INV_COL_ITEM, 390)
        self.inventory_table.setColumnWidth(self.INV_COL_COUNT, 105)
        self.inventory_table.setColumnWidth(self.INV_COL_CATEGORY, 145)
        self.inventory_table.setColumnWidth(self.INV_COL_STATUS, 110)
        self.inventory_table.setColumnWidth(self.INV_COL_NOTE, 340)
        self.inventory_table.setMinimumHeight(420)
        inventory_layout.addWidget(self.inventory_table, 8)

        # Storage details are intentionally kept out of the main layout so the inventory table stays tall.
        # They are shown on the Storage Info button tooltip and in a small pop-up dialog when needed.
        self.inv_storage_info = QPlainTextEdit()
        self.inv_storage_info.setReadOnly(True)
        self.inv_storage_info.setVisible(False)
        self.inv_storage_info.setPlaceholderText("Select an inventory row to inspect FormID bytes, offsets, raw count, displayed count, and edit safety.")

        self.inventory_workspace_tabs.addTab(inventory_tab, "Current Inventory")

        database_tab = QWidget()
        database_layout = QVBoxLayout(database_tab)
        database_layout.setContentsMargins(0, 0, 0, 0)
        database_layout.setSpacing(10)

        db_filters = QHBoxLayout()
        self.inv_db_filter_edit = QLineEdit()
        self.inv_db_filter_edit.setPlaceholderText("Search item, weapon, armor, FormID, EditorID, category…")
        self.inv_db_filter_edit.textChanged.connect(self.refresh_inventory_database_table)
        self.inv_db_category_combo = QComboBox()
        self.inv_db_category_combo.currentIndexChanged.connect(self.refresh_inventory_database_table)
        self.inv_db_status_combo = QComboBox()
        self.inv_db_status_combo.addItems(["All items", "In inventory", "Missing from inventory", "Pending add", "Preflight direct add", "Console command only"])
        self.inv_db_status_combo.currentIndexChanged.connect(self.refresh_inventory_database_table)
        self.inv_db_amount_spin = QSpinBox()
        self.inv_db_amount_spin.setRange(1, MAX_SAFE_INVENTORY_COUNT)
        self.inv_db_amount_spin.setValue(1)
        self.inv_db_amount_spin.setAccelerated(True)
        db_filters.addWidget(self._form_label("Search"))
        db_filters.addWidget(self.inv_db_filter_edit, 1)
        db_filters.addWidget(self.inv_db_category_combo)
        db_filters.addWidget(self.inv_db_status_combo)
        db_filters.addWidget(self._form_label("Amount"))
        db_filters.addWidget(self.inv_db_amount_spin)
        database_layout.addLayout(db_filters)

        db_actions = QHBoxLayout()
        add_selected_btn = QPushButton("Stage Add / Count")
        add_selected_btn.setToolTip("Existing and dormant zero-count rows add to New Count. Missing base-game rows are staged as PS4 fake/minimal rows when this save passes direct-insert preflight.")
        add_selected_btn.clicked.connect(self.add_inventory_database_item_to_save)
        preview_fake_btn = QPushButton("Preview Fake Row")
        preview_fake_btn.setToolTip("Show the exact bytes/count/insert point the editor would generate for the selected missing item.")
        preview_fake_btn.clicked.connect(self.preview_inventory_fake_row_plan)
        set_from_db_btn = QPushButton("Set Existing Count")
        set_from_db_btn.setToolTip("For items already in this save, set New Count to the amount above.")
        set_from_db_btn.clicked.connect(lambda: self.apply_inventory_database_item("set"))
        copy_db_additem_btn = QPushButton("Copy Console Command")
        copy_db_additem_btn.clicked.connect(self.copy_inventory_database_additem_command)
        find_db_item_btn = QPushButton("Find In Inventory")
        find_db_item_btn.clicked.connect(self.find_inventory_database_item_in_inventory)
        db_actions.addWidget(add_selected_btn)
        db_actions.addWidget(preview_fake_btn)
        db_actions.addWidget(set_from_db_btn)
        db_actions.addWidget(copy_db_additem_btn)
        db_actions.addWidget(find_db_item_btn)
        db_actions.addStretch(1)
        database_layout.addLayout(db_actions)
        self.inv_insert_preflight_label = QLabel("Direct missing-item insertion preflight has not run yet. Open a save to evaluate it.")
        self.inv_insert_preflight_label.setObjectName("Subtle")
        self.inv_insert_preflight_label.setWordWrap(True)
        database_layout.addWidget(self.inv_insert_preflight_label)

        self.inv_db_table = QTableWidget(0, 6)
        self.inv_db_table.setHorizontalHeaderLabels(["Item", "FormID", "Category", "Inventory", "Add Method", "Source"])
        self.inv_db_table.horizontalHeader().setStretchLastSection(True)
        self.inv_db_table.verticalHeader().setVisible(False)
        self.inv_db_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.inv_db_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.inv_db_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.inv_db_table.setAlternatingRowColors(True)
        self.inv_db_table.setShowGrid(False)
        self._clean_table_focus(self.inv_db_table)
        self.inv_db_table.itemSelectionChanged.connect(self.refresh_inventory_research_report)
        database_layout.addWidget(self.inv_db_table, 1)
        self.inventory_workspace_tabs.addTab(database_tab, "Item Database / AddItem")

        layout.addWidget(self.inventory_workspace_tabs, 1)
        return page

    def _build_magic_page(self) -> QWidget:
        page, layout = self._page(
            "Magic",
            "Unlock spells, shouts, powers, and abilities through the shared working-save flow.",
        )
        controls = Card(
            "Magic",
            "Check what you want unlocked. File > Save Working Save writes spells, powers, abilities, and existing shout-word records. Missing shout words are normally script-only; enable Experimental Missing Shouts only when testing on a backup.",
        )

        search_row = QHBoxLayout()
        self.magic_filter_edit = QLineEdit()
        self.magic_filter_edit.setPlaceholderText("Search magic by name, shout word, FormID, source, or status...")
        self.magic_filter_edit.textChanged.connect(self._populate_magic_table)
        self.magic_filter_edit.textChanged.connect(self._populate_magic_split_tables)
        search_row.addWidget(QLabel("Search"))
        search_row.addWidget(self.magic_filter_edit, 1)

        self.magic_known_only_check = QCheckBox("Show unlocked only")
        self.magic_known_only_check.setToolTip("Hide rows that are not currently unlocked and do not have a queued change.")
        self.magic_known_only_check.stateChanged.connect(self._populate_magic_split_tables)
        search_row.addWidget(self.magic_known_only_check)

        self.magic_experimental_missing_shouts_check = QCheckBox("Test missing shouts")
        self.magic_experimental_missing_shouts_check.setToolTip(
            "Try to insert missing Word-of-Power records when saving. "
            "Use on backups/test saves only."
        )
        self.magic_experimental_missing_shouts_check.stateChanged.connect(self._populate_magic_split_tables)
        self.magic_experimental_missing_shouts_check.stateChanged.connect(self._update_magic_checkbox_script_preview)
        search_row.addWidget(self.magic_experimental_missing_shouts_check)

        reload_btn = QPushButton("Reload")
        reload_btn.clicked.connect(lambda: self.refresh_magic_page(silent=False))
        search_row.addWidget(reload_btn)
        controls.layout.addLayout(search_row)

        action_row = QHBoxLayout()
        unlock_tab_btn = QPushButton("Unlock Visible Tab")
        unlock_tab_btn.setToolTip("Check every visible row in the current Magic subtab. This only queues changes.")
        unlock_tab_btn.clicked.connect(self.unlock_visible_magic_tab)

        clear_visible_btn = QPushButton("Clear Visible Tab")
        clear_visible_btn.setToolTip("Uncheck every visible row in the current Magic subtab. This only queues changes.")
        clear_visible_btn.clicked.connect(self.clear_visible_magic_tab)

        unlock_spells_btn = QPushButton("Unlock All Spells")
        unlock_spells_btn.clicked.connect(lambda: self.unlock_magic_table_rows(self.magic_spell_table, "spells"))
        unlock_shouts_btn = QPushButton("Unlock All Shouts")
        unlock_shouts_btn.setToolTip("Check every shout word row and enable experimental missing-shout insertion so File > Save Working Save can test-write them.")
        unlock_shouts_btn.clicked.connect(self.unlock_all_shouts_experimental)
        unlock_saveable_shouts_btn = QPushButton("Unlock Saveable Shouts")
        unlock_saveable_shouts_btn.setToolTip("Check only shout words that already exist in this save. Missing shout words are script-only and cannot be safely written directly yet.")
        unlock_saveable_shouts_btn.clicked.connect(lambda: self.unlock_magic_table_rows(self.magic_shout_table, "saveable shout words", direct_saveable_only=True))
        unlock_powers_btn = QPushButton("Unlock All Powers")
        unlock_powers_btn.clicked.connect(lambda: self.unlock_magic_table_rows(self.magic_power_table, "powers"))
        unlock_abilities_btn = QPushButton("Unlock All Abilities")
        unlock_abilities_btn.clicked.connect(lambda: self.unlock_magic_table_rows(self.magic_ability_table, "abilities"))
        unlock_active_effects_btn = QPushButton("Unlock All Active Effects")
        unlock_active_effects_btn.clicked.connect(lambda: self.unlock_magic_table_rows(self.magic_active_effect_table, "active effects"))
        unlock_all_btn = QPushButton("Unlock All Magic")
        unlock_all_btn.setToolTip("Check every directly saveable spell, shout word, power, and ability row. Missing shout words are script-only and are skipped for save safety.")
        unlock_all_btn.clicked.connect(self.unlock_all_magic_rows)


        clear_changes_btn = QPushButton("Clear Queued")
        clear_changes_btn.clicked.connect(self.clear_magic_checkbox_changes)

        restore_magic_backup_btn = QPushButton("Restore Latest Backup")
        restore_magic_backup_btn.clicked.connect(self.restore_latest_save_backup)

        for widget in [
            unlock_tab_btn,
            clear_visible_btn,
            unlock_spells_btn,
            unlock_shouts_btn,
            unlock_saveable_shouts_btn,
            unlock_powers_btn,
            unlock_abilities_btn,
            unlock_active_effects_btn,
            unlock_all_btn,
            clear_changes_btn,
            restore_magic_backup_btn,
        ]:
            action_row.addWidget(widget)
        action_row.addStretch(1)
        controls.layout.addLayout(action_row)

        self.magic_status_label = QLabel("Open a save to scan magic data.")
        self.magic_status_label.setObjectName("Subtle")
        self.magic_status_label.setWordWrap(True)
        controls.layout.addWidget(self.magic_status_label)

        self.magic_changes_label = QLabel("No magic checkbox changes queued.")
        self.magic_changes_label.setObjectName("Subtle")
        self.magic_changes_label.setWordWrap(True)
        controls.layout.addWidget(self.magic_changes_label)

        help_label = QLabel("Changes stay in memory while you edit. Use File > Save Working Save to write the loaded save, or Save As to make a copy.")
        help_label.setObjectName("Subtle")
        help_label.setWordWrap(True)
        controls.layout.addWidget(help_label)
        layout.addWidget(controls)

        self.magic_tabs = QTabWidget()

        def make_magic_table(headers: list[str], visible_columns: list[int]) -> tuple[QWidget, QTableWidget]:
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(0, 0, 0, 0)
            table = QTableWidget(0, len(headers))
            table.setHorizontalHeaderLabels(headers)
            table.horizontalHeader().setStretchLastSection(True)
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            for col in range(1, len(headers)):
                mode = QHeaderView.ResizeMode.Stretch if col in visible_columns else QHeaderView.ResizeMode.ResizeToContents
                table.horizontalHeader().setSectionResizeMode(col, mode)
            table.verticalHeader().setVisible(False)
            table.setAlternatingRowColors(True)
            table.verticalHeader().setDefaultSectionSize(30)
            table.setShowGrid(False)
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.itemDoubleClicked.connect(lambda item: self._copy_magic_reference_command(item))
            table.itemChanged.connect(self._magic_checkbox_changed)
            self._clean_table_focus(table)
            for col in range(len(headers)):
                table.setColumnHidden(col, col not in visible_columns)
            tab_layout.addWidget(table, 1)
            return tab, table

        spells_tab, self.magic_spell_table = make_magic_table(
            ["Unlock", "Status", "Favorite", "Spell", "EditorID", "FormID", "Resolved", "Add Spell", "Remove Spell", "Source"],
            [0, 1, 2, 3],
        )
        self.magic_tabs.addTab(spells_tab, "Spells")

        shouts_tab, self.magic_shout_table = make_magic_table(
            ["Unlock", "Status", "Favorite", "Shout", "Word", "EditorID", "FormID", "Teach Word", "Unlock Word", "Source"],
            [0, 1, 2, 3, 4],
        )
        self.magic_tabs.addTab(shouts_tab, "Shouts")

        powers_tab, self.magic_power_table = make_magic_table(
            ["Unlock", "Status", "Favorite", "Power", "EditorID", "FormID", "Resolved", "Add Power", "Remove Power", "Source"],
            [0, 1, 2, 3],
        )
        self.magic_tabs.addTab(powers_tab, "Powers")

        abilities_tab, self.magic_ability_table = make_magic_table(
            ["Unlock", "Status", "Favorite", "Ability", "EditorID", "FormID", "Resolved", "Add Ability", "Remove Ability", "Source"],
            [0, 1, 2, 3],
        )
        self.magic_tabs.addTab(abilities_tab, "Abilities")

        active_effects_tab, self.magic_active_effect_table = make_magic_table(
            ["Unlock", "Status", "Favorite", "Active Effect", "EditorID", "FormID", "Resolved", "Add Effect", "Remove Effect", "Source"],
            [0, 1, 2, 3],
        )
        self.magic_tabs.addTab(active_effects_tab, "Active Effects")

        advanced_tab = QWidget()
        advanced_layout = QVBoxLayout(advanced_tab)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_help = QLabel("Advanced read-only data for troubleshooting. Normal unlock/save work happens in Spells, Shouts, Powers, Abilities, and Active Effects.")
        advanced_help.setObjectName("Subtle")
        advanced_help.setWordWrap(True)
        advanced_layout.addWidget(advanced_help)
        self.magic_advanced_tabs = QTabWidget()

        hits_tab = QWidget()
        hits_layout = QVBoxLayout(hits_tab)
        hits_layout.setContentsMargins(0, 0, 0, 0)
        self.magic_table = QTableWidget(0, 10)
        self.magic_table.setHorizontalHeaderLabels(["Name", "Category", "FormID", "Resolved", "RefID Bytes", "Area", "Offset", "Local", "Confidence", "Source"])
        self.magic_table.horizontalHeader().setStretchLastSection(True)
        self.magic_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 9):
            self.magic_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.magic_table.verticalHeader().setVisible(False)
        self.magic_table.setAlternatingRowColors(True)
        self.magic_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.magic_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.magic_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._clean_table_focus(self.magic_table)
        self.magic_table.itemSelectionChanged.connect(self._update_magic_detail)
        hits_layout.addWidget(self.magic_table, 1)
        self.magic_detail = QPlainTextEdit()
        self.magic_detail.setReadOnly(True)
        self.magic_detail.setMaximumHeight(130)
        hits_layout.addWidget(self.magic_detail)
        self.magic_advanced_tabs.addTab(hits_tab, "Known Hits")

        fav_tab = QWidget()
        fav_layout = QVBoxLayout(fav_tab)
        fav_layout.setContentsMargins(0, 0, 0, 0)
        self.magic_favorites_table = QTableWidget(0, 7)
        self.magic_favorites_table.setHorizontalHeaderLabels(["Table", "Index", "Type", "Offset", "Length", "Candidate Refs", "Sample"])
        self.magic_favorites_table.horizontalHeader().setStretchLastSection(True)
        self.magic_favorites_table.verticalHeader().setVisible(False)
        self.magic_favorites_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.magic_favorites_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.magic_favorites_table.setAlternatingRowColors(True)
        self._clean_table_focus(self.magic_favorites_table)
        fav_layout.addWidget(self.magic_favorites_table, 1)
        self.magic_advanced_tabs.addTab(fav_tab, "Favorites Data")

        db_tab = QWidget()
        db_layout = QVBoxLayout(db_tab)
        db_layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.magic_db_filter = QLineEdit()
        self.magic_db_filter.setPlaceholderText("Filter loaded magic reference database...")
        self.magic_db_filter.textChanged.connect(self._populate_magic_database_table)
        top.addWidget(self.magic_db_filter, 1)
        db_layout.addLayout(top)
        self.magic_database_table = QTableWidget(0, 7)
        self.magic_database_table.setHorizontalHeaderLabels(["Category", "EditorID", "Name", "FormID", "Resolved", "RefID Bytes", "Source"])
        self.magic_database_table.horizontalHeader().setStretchLastSection(True)
        self.magic_database_table.verticalHeader().setVisible(False)
        self.magic_database_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.magic_database_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.magic_database_table.setAlternatingRowColors(True)
        self._clean_table_focus(self.magic_database_table)
        db_layout.addWidget(self.magic_database_table, 1)
        self.magic_advanced_tabs.addTab(db_tab, "Reference IDs")

        self.magic_script_output = QPlainTextEdit()
        self.magic_script_output.setReadOnly(True)
        self.magic_script_output.setVisible(False)

        advanced_layout.addWidget(self.magic_advanced_tabs, 1)
        self.magic_tabs.addTab(advanced_tab, "Advanced")

        layout.addWidget(self.magic_tabs, 1)
        return page

    def _build_plugins_page(self) -> QWidget:
        page, layout = self._page(
            "Plugins",
            "Read the plugin list embedded in the save so we can detect load-order and mod dependencies.",
        )
        card = Card("Plugin Info", "Full and light plugins from the loaded save. This table now expands to use the page instead of staying cramped.")

        controls = QHBoxLayout()
        self.plugin_filter_edit = QLineEdit()
        self.plugin_filter_edit.setPlaceholderText("Filter plugins by name, slot, or hex...")
        self.plugin_filter_edit.textChanged.connect(self._refresh_plugins)
        self.plugin_counts_label = QLabel("Open a save to list plugins.")
        self.plugin_counts_label.setObjectName("Subtle")
        self.plugin_counts_label.setWordWrap(True)
        controls.addWidget(self.plugin_filter_edit, 1)
        controls.addWidget(self.plugin_counts_label)
        card.layout.addLayout(controls)

        self.plugin_table = QTableWidget(0, 3)
        self.plugin_table.setHorizontalHeaderLabels(["Slot", "Hex", "Plugin"])
        self.plugin_table.horizontalHeader().setStretchLastSection(False)
        self.plugin_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.plugin_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.plugin_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.plugin_table.verticalHeader().setVisible(False)
        self.plugin_table.verticalHeader().setDefaultSectionSize(28)
        self.plugin_table.setAlternatingRowColors(True)
        self.plugin_table.setMinimumHeight(520)
        self.plugin_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._clean_table_focus(self.plugin_table)
        card.layout.addWidget(self.plugin_table, 1)
        layout.addWidget(card, 1)
        return page

    def _build_database_page(self) -> QWidget:
        page, layout = self._page(
            "Reference IDs",
            "Search the main Skyrim IDs and info groups: weapons, arrows, spells, perks, shouts, actor values, characters, factions, followers, locations, and weather.",
        )
        controls = Card("Spreadsheet Import")
        row = QHBoxLayout()
        self.db_path_edit = QLineEdit(); self.db_path_edit.setReadOnly(True)
        load_btn = QPushButton("Load CSV")
        load_btn.clicked.connect(self.load_database_dialog)
        merge_btn = QPushButton("Merge CSV")
        merge_btn.clicked.connect(self.merge_database_dialog)
        template_btn = QPushButton("Export Template")
        template_btn.clicked.connect(self.export_database_template)
        row.addWidget(self.db_path_edit, 1)
        row.addWidget(load_btn)
        row.addWidget(merge_btn)
        row.addWidget(template_btn)
        controls.layout.addLayout(row)

        sheet_row = QHBoxLayout()
        self.db_sheet_url_edit = QLineEdit()
        self.db_sheet_url_edit.setPlaceholderText("Paste Google Sheets URL here to load/export it as CSV")
        sheet_btn = QPushButton("Load Sheet URL")
        sheet_btn.clicked.connect(self.load_database_sheet_url)
        harvest_btn = QPushButton("Fetch Linked Fandom Pages")
        harvest_btn.clicked.connect(self.harvest_fandom_pages)
        mutagen_btn = QPushButton("Fetch Mutagen FormKeys")
        mutagen_btn.clicked.connect(self.harvest_mutagen_formkeys)
        audit_btn = QPushButton("Run Reference Audit")
        audit_btn.clicked.connect(self.run_reference_audit)
        sheet_row.addWidget(self.db_sheet_url_edit, 1)
        sheet_row.addWidget(sheet_btn)
        sheet_row.addWidget(harvest_btn)
        sheet_row.addWidget(mutagen_btn)
        sheet_row.addWidget(audit_btn)
        controls.layout.addLayout(sheet_row)

        hint = QLabel("Reference data is CSV-backed. Load CSV replaces the table; Merge CSV appends/de-dupes extra packs or spreadsheet exports. Google Sheets links are converted to CSV export URLs.")
        hint.setObjectName("Subtle")
        hint.setWordWrap(True)
        controls.layout.addWidget(hint)
        self.reference_manifest_label = QLabel("")
        self.reference_manifest_label.setObjectName("Subtle")
        self.reference_manifest_label.setWordWrap(True)
        controls.layout.addWidget(self.reference_manifest_label)
        layout.addWidget(controls)

        coverage = Card("Coverage / Export")
        cov_row = QHBoxLayout()
        self.coverage_table = QTableWidget(0, 2)
        self.coverage_table.setHorizontalHeaderLabels(["Metric", "Value"])
        self.coverage_table.horizontalHeader().setStretchLastSection(True)
        self.coverage_table.verticalHeader().setVisible(False)
        self.coverage_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._clean_table_focus(self.coverage_table)
        cov_btn_col = QVBoxLayout()
        export_db_btn = QPushButton("Export Current Reference CSV")
        export_db_btn.clicked.connect(self.export_current_reference_database)
        export_unknown_btn2 = QPushButton("Export Current Unknown Inventory IDs")
        export_unknown_btn2.clicked.connect(self.export_unknown_inventory_ids_dialog)
        export_audit_btn = QPushButton("Export Audit JSON")
        export_audit_btn.clicked.connect(self.export_reference_audit_json)
        cov_btn_col.addWidget(export_db_btn)
        cov_btn_col.addWidget(export_unknown_btn2)
        cov_btn_col.addWidget(export_audit_btn)
        cov_btn_col.addStretch(1)
        cov_row.addWidget(self.coverage_table, 1)
        cov_row.addLayout(cov_btn_col)
        coverage.layout.addLayout(cov_row)
        layout.addWidget(coverage)

        search_card = Card("Search")
        filter_row = QHBoxLayout()
        self.db_search = QLineEdit(); self.db_search.setPlaceholderText("Search name, FormID, EditorID, source, notes…")
        self.db_search.textChanged.connect(self.refresh_database_table)
        self.db_category = QComboBox(); self.db_category.addItem("All categories")
        self.db_category.currentIndexChanged.connect(self.refresh_database_table)
        filter_row.addWidget(self.db_search, 1)
        filter_row.addWidget(self.db_category)
        search_card.layout.addLayout(filter_row)
        helper_row = QHBoxLayout()
        self.db_command_count = QSpinBox()
        self.db_command_count.setRange(1, MAX_SAFE_INVENTORY_COUNT)
        self.db_command_count.setValue(1)
        copy_ref_id_btn = QPushButton("Copy FormID")
        copy_ref_id_btn.clicked.connect(self.copy_selected_reference_id)
        copy_additem_btn = QPushButton("Copy player.additem")
        copy_additem_btn.clicked.connect(self.copy_selected_additem_command)
        find_inventory_btn = QPushButton("Find In Inventory")
        find_inventory_btn.clicked.connect(self.find_selected_reference_in_inventory)
        helper_row.addWidget(self._form_label("Command Count"))
        helper_row.addWidget(self.db_command_count)
        helper_row.addStretch(1)
        helper_row.addWidget(copy_ref_id_btn)
        helper_row.addWidget(copy_additem_btn)
        helper_row.addWidget(find_inventory_btn)
        search_card.layout.addLayout(helper_row)
        self.db_table = QTableWidget(0, 8)
        self.db_table.setHorizontalHeaderLabels(["Category", "EditorID", "FormID", "Resolved", "Name", "Value", "Source", "Notes"])
        self.db_table.horizontalHeader().setStretchLastSection(True)
        self.db_table.verticalHeader().setVisible(False)
        self.db_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.db_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._clean_table_focus(self.db_table)
        self.db_table.itemSelectionChanged.connect(self._database_selection_changed)
        search_card.layout.addWidget(self.db_table)
        layout.addWidget(search_card, 1)
        return page

    def _build_formid_page(self) -> QWidget:
        page, layout = self._page(
            "Form ID Tools",
            "Decode base IDs, reference-style IDs, load-order prefixes, and XX placeholders against the current save plugin list.",
        )
        info = Card("Base ID vs Reference ID")
        txt = QLabel(base_reference_notes())
        txt.setWordWrap(True)
        info.layout.addWidget(txt)
        layout.addWidget(info)

        tool = Card("ID Analyzer")
        row = QHBoxLayout()
        self.formid_input = QLineEdit(); self.formid_input.setPlaceholderText("Example: 0000000F, XX02B06B, 0402B06B, carryweight")
        self.formid_plugin_combo = QComboBox(); self.formid_plugin_combo.addItem("No plugin selected")
        analyze_btn = QPushButton("Analyze")
        analyze_btn.clicked.connect(self.analyze_form_id)
        row.addWidget(self._form_label("ID"))
        row.addWidget(self.formid_input, 1)
        row.addWidget(self._form_label("Plugin"))
        row.addWidget(self.formid_plugin_combo)
        row.addWidget(analyze_btn)
        tool.layout.addLayout(row)

        self.formid_table = QTableWidget(0, 2)
        self.formid_table.setHorizontalHeaderLabels(["Field", "Value"])
        self.formid_table.horizontalHeader().setStretchLastSection(True)
        self.formid_table.verticalHeader().setVisible(False)
        self.formid_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._clean_table_focus(self.formid_table)
        tool.layout.addWidget(self.formid_table)

        self.formid_notes = QPlainTextEdit()
        self.formid_notes.setReadOnly(True)
        self.formid_notes.setPlainText(
            "Use Reference IDs for targeted world objects/NPC instances. Use Base/Form IDs for records such as inventory items, perks, spells, shouts, factions, weather, and most reference table lookups.\n\n"
            "DLC/mod records may be written as XX123456 in online tables. XX is not literal; it is the plugin's load-order byte in the current save."
        )
        tool.layout.addWidget(self.formid_notes)
        layout.addWidget(tool, 1)
        return page

    def _build_scanner_page(self) -> QWidget:
        page, layout = self._page(
            "Scanner",
            "Search the raw save for a selected form ID. This is a safe discovery tool, not an auto-patcher yet.",
        )
        card = Card("Form ID Search")
        row = QHBoxLayout()
        self.scan_form_edit = QLineEdit(); self.scan_form_edit.setPlaceholderText("Example: 0000000F")
        scan_btn = QPushButton("Scan Current Save")
        scan_btn.clicked.connect(self.scan_current_save)
        row.addWidget(QLabel("Form ID"))
        row.addWidget(self.scan_form_edit, 1)
        row.addWidget(scan_btn)
        card.layout.addLayout(row)
        self.scan_output = QPlainTextEdit(); self.scan_output.setReadOnly(True)
        card.layout.addWidget(self.scan_output, 1)
        layout.addWidget(card, 1)
        return page

    def _build_raw_page(self) -> QWidget:
        page, layout = self._page(
            "Raw Editor",
            "Mapped raw fields from the actual save bytes. Double-click Value for a readable editor; structural rows stay read-only.",
        )

        self.raw_tabs = QTabWidget()
        self.raw_tabs.setDocumentMode(True)
        # QTabWidget does not expose setDrawBase in PyQt6; QTabBar does.
        # Keep this guarded so older/newer Qt bindings launch cleanly.
        try:
            self.raw_tabs.tabBar().setDrawBase(False)
        except AttributeError:
            pass

        mapped_tab = QWidget()
        mapped_layout = QVBoxLayout(mapped_tab)
        mapped_layout.setContentsMargins(0, 0, 0, 0)
        mapped_layout.setSpacing(10)

        controls = Card("Mapped Raw Fields")
        top = QHBoxLayout()
        self.raw_filter_edit = QLineEdit(); self.raw_filter_edit.setPlaceholderText("Filter fields, offsets, FormIDs, notes...")
        self.raw_filter_edit.textChanged.connect(self.refresh_raw_mapped_table)
        self.raw_group_combo = QComboBox()
        self.raw_group_combo.addItems(["All groups", "Header", "Player Inventory", "Player Change Form", "Global Variables", "Payload", "File Location Table", "Global Data"])
        self.raw_group_combo.currentTextChanged.connect(self.refresh_raw_mapped_table)
        reload_btn = QPushButton("Reload Map")
        reload_btn.clicked.connect(self.refresh_raw_editor)
        save_btn = QPushButton("Save Raw Edits")
        save_btn.clicked.connect(self.save_raw_edits)
        copy_btn = QPushButton("Save Raw Copy...")
        copy_btn.clicked.connect(self.save_raw_copy)
        top.addWidget(self.raw_filter_edit, 2)
        top.addWidget(self.raw_group_combo)
        top.addWidget(reload_btn)
        top.addWidget(save_btn)
        top.addWidget(copy_btn)
        controls.layout.addLayout(top)
        self.raw_status_label = QLabel("Open a save to map raw fields.")
        self.raw_status_label.setWordWrap(True)
        controls.layout.addWidget(self.raw_status_label)

        selected_edit_row = QHBoxLayout()
        self.raw_selected_field_label = QLabel("Selected: none")
        self.raw_selected_field_label.setObjectName("Subtle")
        self.raw_selected_new_edit = QLineEdit()
        self.raw_selected_new_edit.setPlaceholderText("Select an editable row, type the replacement value here, or double-click the Value cell...")
        self.raw_selected_new_edit.returnPressed.connect(self.apply_selected_raw_new_value)
        self.raw_selected_new_edit.setEnabled(False)
        apply_selected_btn = QPushButton("Set Selected Value")
        apply_selected_btn.clicked.connect(self.apply_selected_raw_new_value)
        popup_edit_btn = QPushButton("Big Edit…")
        popup_edit_btn.clicked.connect(self.open_raw_value_popup)
        use_current_btn = QPushButton("Revert To Current")
        use_current_btn.clicked.connect(self.use_current_raw_value_for_selected)
        clear_selected_btn = QPushButton("Clear/Revert Selected")
        clear_selected_btn.clicked.connect(self.clear_selected_raw_edit)
        clear_all_btn = QPushButton("Clear/Revert All")
        clear_all_btn.clicked.connect(self.clear_all_raw_edits)
        self.raw_selected_apply_btn = apply_selected_btn
        self.raw_selected_popup_btn = popup_edit_btn
        self.raw_selected_use_current_btn = use_current_btn
        self.raw_selected_clear_btn = clear_selected_btn
        for btn in (apply_selected_btn, popup_edit_btn, use_current_btn, clear_selected_btn):
            btn.setEnabled(False)
        selected_edit_row.addWidget(self.raw_selected_field_label, 1)
        selected_edit_row.addWidget(self.raw_selected_new_edit, 2)
        selected_edit_row.addWidget(apply_selected_btn)
        selected_edit_row.addWidget(popup_edit_btn)
        selected_edit_row.addWidget(use_current_btn)
        selected_edit_row.addWidget(clear_selected_btn)
        selected_edit_row.addWidget(clear_all_btn)
        controls.layout.addLayout(selected_edit_row)
        mapped_layout.addWidget(controls)

        self.raw_fields_table = QTableWidget(0, 7)
        self.raw_fields_table.setHorizontalHeaderLabels(["Group", "Field", "Storage", "Offset", "Type", "Value", "Safety / Notes"])
        self.raw_fields_table.itemChanged.connect(self._raw_field_item_changed)
        self.raw_fields_table.itemSelectionChanged.connect(self._raw_field_selection_changed)
        self.raw_fields_table.itemDoubleClicked.connect(self.open_raw_value_popup_from_item)
        self._clean_table_focus(self.raw_fields_table)
        self.raw_fields_table.setItemDelegateForColumn(5, RawValueDelegate(self.raw_fields_table))
        self.raw_fields_table.setEditTriggers(
            QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.raw_fields_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.raw_fields_table.setAlternatingRowColors(True)
        self.raw_fields_table.verticalHeader().setDefaultSectionSize(34)
        mapped_layout.addWidget(self.raw_fields_table, 1)

        self.raw_hex_preview = QPlainTextEdit()
        self.raw_hex_preview.setReadOnly(True)
        self.raw_hex_preview.setMaximumHeight(120)
        self.raw_hex_preview.setPlaceholderText("Select a mapped field to preview nearby bytes.")
        mapped_layout.addWidget(self.raw_hex_preview)
        self.raw_tabs.addTab(mapped_tab, "Mapped Fields")

        change_tab = QWidget()
        change_layout = QVBoxLayout(change_tab)
        change_layout.setContentsMargins(0, 0, 0, 0)
        change_layout.setSpacing(10)
        row = QHBoxLayout()
        self.raw_change_filter_edit = QLineEdit(); self.raw_change_filter_edit.setPlaceholderText("Filter change forms by index, RefID, FormID, type, flags, sample...")
        self.raw_change_filter_edit.textChanged.connect(self.refresh_raw_change_forms_table)
        row.addWidget(self.raw_change_filter_edit, 1)
        change_layout.addLayout(row)
        self.raw_change_table = QTableWidget(0, 8)
        self.raw_change_table.setHorizontalHeaderLabels(["Index", "RefID", "FormID Guess", "Type", "Flags", "Len", "Data Offset", "Sample"])
        self._clean_table_focus(self.raw_change_table)
        self.raw_change_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.raw_change_table.setAlternatingRowColors(True)
        change_layout.addWidget(self.raw_change_table, 1)
        self.raw_tabs.addTab(change_tab, "Change Forms")

        format_tab = QWidget()
        format_layout = QVBoxLayout(format_tab)
        format_layout.setContentsMargins(0, 0, 0, 0)
        format_layout.setSpacing(10)
        format_controls = Card("UESP Save Format Reference")
        format_controls.layout.addWidget(QLabel("Reference map from the UESP Skyrim save-file format notes. This is documentation inside the editor; mapped editable bytes are still on the Mapped Fields tab."))
        format_filter_row = QHBoxLayout()
        self.raw_format_filter_edit = QLineEdit(); self.raw_format_filter_edit.setPlaceholderText("Filter by section, field, type, or notes...")
        self.raw_format_filter_edit.textChanged.connect(self.refresh_raw_format_reference_table)
        format_filter_row.addWidget(self.raw_format_filter_edit, 1)
        format_controls.layout.addLayout(format_filter_row)
        format_layout.addWidget(format_controls)
        self.raw_format_table = QTableWidget(0, 4)
        self.raw_format_table.setHorizontalHeaderLabels(["Section", "Name", "Type / Size", "Notes"] )
        self._clean_table_focus(self.raw_format_table)
        self.raw_format_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.raw_format_table.setAlternatingRowColors(True)
        format_layout.addWidget(self.raw_format_table, 1)
        self.raw_tabs.addTab(format_tab, "Format Reference")

        self.raw_tabs.addTab(self._build_quick_code_formats_tab(), "Quick Codes")

        json_tab = QWidget()
        json_layout = QVBoxLayout(json_tab)
        json_layout.setContentsMargins(0, 0, 0, 0)
        json_layout.setSpacing(10)

        json_controls = Card("Parsed JSON Editor", "Search, validate, format, and export the parsed save model. This JSON is a research/export view; save-byte edits still use Mapped Fields or the dedicated pages.")
        json_search_row = QHBoxLayout()
        self.raw_json_search_edit = QLineEdit(); self.raw_json_search_edit.setPlaceholderText("Search parsed JSON keys/values/offsets...")
        self.raw_json_search_edit.returnPressed.connect(self.find_next_raw_json)
        self.raw_json_case_check = QCheckBox("Case sensitive")
        find_prev_btn = QPushButton("Find Previous")
        find_prev_btn.clicked.connect(self.find_previous_raw_json)
        find_next_btn = QPushButton("Find Next")
        find_next_btn.clicked.connect(self.find_next_raw_json)
        json_search_row.addWidget(self.raw_json_search_edit, 1)
        json_search_row.addWidget(self.raw_json_case_check)
        json_search_row.addWidget(find_prev_btn)
        json_search_row.addWidget(find_next_btn)
        json_controls.layout.addLayout(json_search_row)

        json_action_row = QHBoxLayout()
        validate_btn = QPushButton("Validate Syntax")
        validate_btn.clicked.connect(self.validate_raw_json_editor)
        format_btn = QPushButton("Format JSON")
        format_btn.clicked.connect(self.format_raw_json_editor)
        compact_btn = QPushButton("Compact JSON")
        compact_btn.clicked.connect(self.compact_raw_json_editor)
        undo_btn = QPushButton("Undo")
        undo_btn.clicked.connect(self.undo_raw_json_editor)
        reload_json_btn = QPushButton("Reload Parsed")
        reload_json_btn.clicked.connect(self.reload_raw_json_editor)
        export_json_btn = QPushButton("Export Edited JSON…")
        export_json_btn.clicked.connect(self.export_raw_json_editor_text)
        json_action_row.addWidget(validate_btn)
        json_action_row.addWidget(format_btn)
        json_action_row.addWidget(compact_btn)
        json_action_row.addWidget(undo_btn)
        json_action_row.addWidget(reload_json_btn)
        json_action_row.addWidget(export_json_btn)
        json_action_row.addStretch(1)
        json_controls.layout.addLayout(json_action_row)
        self.raw_json_status_label = QLabel("Open a save to load parsed JSON.")
        self.raw_json_status_label.setWordWrap(True)
        self.raw_json_status_label.setObjectName("Subtle")
        json_controls.layout.addWidget(self.raw_json_status_label)
        json_layout.addWidget(json_controls)

        self.raw_json = QPlainTextEdit()
        self.raw_json.setReadOnly(False)
        self.raw_json.setUndoRedoEnabled(True)
        self.raw_json.setPlaceholderText("Open a save to view parsed JSON.")
        self.raw_json.textChanged.connect(self.validate_raw_json_editor_quiet)
        json_layout.addWidget(self.raw_json, 1)
        self.raw_tabs.addTab(json_tab, "Parsed JSON")

        help_tab = QWidget()
        help_layout = QVBoxLayout(help_tab)
        help_layout.setContentsMargins(0, 0, 0, 0)
        help = QPlainTextEdit()
        help.setReadOnly(True)
        help.setPlainText(
            "Mapped Raw Editor notes:\n\n"
            "- Player Inventory rows edit the actual count field inside the player ACHR change form, not the visual header.\n"
            "- Editable rows are fixed-size only. The editor refuses edits that would resize a string, row, or structure.\n"
            "- Read-only structural fields are shown so we can map the save format without hand-patching dangerous offsets.\n"
            "- Use Save Raw Copy first when trying a newly mapped field. Use Save Raw Edits only after the copy loads in-game.\n"
            "- This page is for mapped bytes. Direct missing-item insertion remains experimental and separate from fixed-size raw edits.\n"
            "- The Format Reference tab summarizes the UESP save-file layout so we can map new editable fields methodically instead of guessing."
        )
        help_layout.addWidget(help, 1)
        self.raw_tabs.addTab(help_tab, "Notes")

        layout.addWidget(self.raw_tabs, 1)
        self.refresh_raw_format_reference_table()
        return page

    def _build_quick_code_formats_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        intro_card = Card(
            "Quick Codes",
            "Cleaner workspace for decoding and generating Save Wizard custom quick-code text.",
        )
        intro = QLabel(
            "Use this as a code-format helper only. Real save edits belong in General, Player Inventory, or Mapped Fields where the editor knows the exact save bytes."
        )
        intro.setWordWrap(True)
        intro.setObjectName("Subtle")
        intro_card.layout.addWidget(intro)
        layout.addWidget(intro_card)

        quick_tabs = QTabWidget()
        quick_tabs.setDocumentMode(True)
        try:
            quick_tabs.tabBar().setDrawBase(False)
        except AttributeError:
            pass

        builder_tab = QWidget()
        builder_layout = QVBoxLayout(builder_tab)
        builder_layout.setContentsMargins(0, 0, 0, 0)
        builder_layout.setSpacing(10)
        builder = Card("Builder", "Generate copy-ready Type 0/1/2 standard writes or Type A mass writes.")
        builder_grid = QGridLayout()
        self.quick_code_build_type_combo = QComboBox()
        self.quick_code_build_type_combo.addItem("1 byte write — Type 0", 1)
        self.quick_code_build_type_combo.addItem("2 byte write — Type 1", 2)
        self.quick_code_build_type_combo.addItem("4 byte write — Type 2", 4)
        self.quick_code_build_type_combo.addItem("Mass write bytes — Type A", "A")
        self.quick_code_offset_combo = QComboBox()
        self.quick_code_offset_combo.addItem("Normal offset", "0")
        self.quick_code_offset_combo.addItem("Pointer-relative offset", "8")
        self.quick_code_address_edit = QLineEdit()
        self.quick_code_address_edit.setPlaceholderText("Address, 6 hex digits. Example: 000250")
        self.quick_code_value_edit = QLineEdit()
        self.quick_code_value_edit.setPlaceholderText("Value hex, or mass-write bytes like 1122334455667788")
        self.quick_code_decimal_checkbox = QCheckBox("Value is decimal")
        self.quick_code_decimal_checkbox.setToolTip("For Type 0/1/2 only. Mass write data is always raw hex bytes.")
        builder_grid.addWidget(self._form_label("Type"), 0, 0)
        builder_grid.addWidget(self.quick_code_build_type_combo, 0, 1)
        builder_grid.addWidget(self._form_label("Offset"), 0, 2)
        builder_grid.addWidget(self.quick_code_offset_combo, 0, 3)
        builder_grid.addWidget(self._form_label("Address"), 1, 0)
        builder_grid.addWidget(self.quick_code_address_edit, 1, 1)
        builder_grid.addWidget(self._form_label("Value / Bytes"), 1, 2)
        builder_grid.addWidget(self.quick_code_value_edit, 1, 3)
        builder_grid.addWidget(self.quick_code_decimal_checkbox, 2, 1)
        builder_grid.setColumnStretch(1, 1)
        builder_grid.setColumnStretch(3, 1)
        builder.layout.addLayout(builder_grid)
        build_buttons = QHBoxLayout()
        generate_btn = QPushButton("Generate")
        generate_btn.clicked.connect(self.generate_quick_code_builder)
        copy_btn = QPushButton("Copy Generated")
        copy_btn.clicked.connect(self.copy_generated_quick_code)
        build_buttons.addStretch(1)
        build_buttons.addWidget(copy_btn)
        build_buttons.addWidget(generate_btn)
        builder.layout.addLayout(build_buttons)
        self.quick_code_generated_output = QPlainTextEdit()
        self.quick_code_generated_output.setReadOnly(True)
        self.quick_code_generated_output.setPlaceholderText("Generated quick code will appear here.")
        self.quick_code_generated_output.setMaximumHeight(140)
        builder.layout.addWidget(self.quick_code_generated_output)
        builder_layout.addWidget(builder)
        builder_layout.addStretch(1)
        quick_tabs.addTab(builder_tab, "Builder")

        decoder_tab = QWidget()
        decoder_layout = QVBoxLayout(decoder_tab)
        decoder_layout.setContentsMargins(0, 0, 0, 0)
        decoder_layout.setSpacing(10)
        decoder = Card("Decoder", "Paste one or more custom quick-code lines and convert them into readable operations.")
        self.quick_code_input = QPlainTextEdit()
        self.quick_code_input.setPlaceholderText("Paste raw codes or a whole table with labels/credits. The decoder ignores non-code text.\nExample:\nCarry Weight 1000000000:\n8001000C 05000000\n00000000 06000000\n88020004 20000000\n28000004 4E6E6B23")
        self.quick_code_input.setMinimumHeight(130)
        self.quick_code_output = QPlainTextEdit()
        self.quick_code_output.setReadOnly(True)
        self.quick_code_output.setPlaceholderText("Decoded notes will appear here.")
        self.quick_code_output.setMinimumHeight(130)
        decoder.layout.addWidget(self.quick_code_input)
        decoder_buttons = QHBoxLayout()
        decode_btn = QPushButton("Decode")
        decode_btn.clicked.connect(self.decode_quick_code_input)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_quick_code_decoder)
        decoder_buttons.addStretch(1)
        decoder_buttons.addWidget(clear_btn)
        decoder_buttons.addWidget(decode_btn)
        decoder.layout.addLayout(decoder_buttons)
        decoder.layout.addWidget(self.quick_code_output)
        decoder_layout.addWidget(decoder)
        quick_tabs.addTab(decoder_tab, "Decoder")

        reference_tab = QWidget()
        reference_layout = QVBoxLayout(reference_tab)
        reference_layout.setContentsMargins(0, 0, 0, 0)
        reference_layout.setSpacing(10)
        formats = Card("Format Reference", "Searchable line-type reference kept out of the main builder view.")
        filter_row = QHBoxLayout()
        self.quick_code_format_filter_edit = QLineEdit()
        self.quick_code_format_filter_edit.setPlaceholderText("Filter by type, name, layout, meaning, notes, or example…")
        self.quick_code_format_filter_edit.textChanged.connect(self.refresh_quick_code_format_table)
        filter_row.addWidget(self._form_label("Filter"))
        filter_row.addWidget(self.quick_code_format_filter_edit, 1)
        formats.layout.addLayout(filter_row)
        self.quick_code_format_table = QTableWidget(0, 6)
        self.quick_code_format_table.setHorizontalHeaderLabels(["Type", "Name", "Layout", "Meaning", "Notes", "Example"])
        self.quick_code_format_table.verticalHeader().setVisible(False)
        self.quick_code_format_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.quick_code_format_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.quick_code_format_table.setAlternatingRowColors(True)
        self.quick_code_format_table.setShowGrid(False)
        self._clean_table_focus(self.quick_code_format_table)
        formats.layout.addWidget(self.quick_code_format_table, 1)
        reference_layout.addWidget(formats, 1)
        quick_tabs.addTab(reference_tab, "Reference")

        layout.addWidget(quick_tabs, 1)
        self.refresh_quick_code_format_table()
        return tab

    def _build_about_page(self) -> QWidget:
        page, layout = self._page("About", "Project status, supported workflows, sources, and community links.")

        card = Card("Skyrim Save Lab created by ProtoBuffers")
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(14)
        icon_label = QLabel()
        icon_label.setFixedSize(88, 88)
        icon_label.setScaledContents(False)
        icon_path = resource_path("icons", "skyrim.png")
        if icon_path.exists():
            icon_pixmap = QPixmap(str(icon_path))
            if not icon_pixmap.isNull():
                icon_label.setPixmap(icon_pixmap.scaled(88, 88, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        header_row.addWidget(icon_label, 0)
        title = QLabel("Skyrim Save Lab created by ProtoBuffers")
        title.setObjectName("SectionTitle")
        title.setWordWrap(True)
        header_row.addWidget(title, 1)
        card.layout.addLayout(header_row)

        info = QLabel(
            "<p><b>PS4 Skyrim save editor ready for public testing.</b><br>"
            "PC / PS3 / Xbox 360 / Switch support may work in places, but PS4 is the main target right now. "
            "<b>Please make a backup of your save first.</b></p>"
            "<p><b>Based on:</b><br>"
            "<a href='https://en.uesp.net/wiki/Skyrim_Mod:Save_File_Format'>"
            "UESP: Skyrim Mod Save File Format</a></p>"
            "<p><b>Originally intended to fix Save Wizard saves:</b><br>"
            "<a href='https://docs.google.com/spreadsheets/d/1pln64WRA8QhhrW1QBDEn97HEbp4gdvBNd3GnrC4Bg5c/edit?gid=1795290740#gid=1795290740'>"
            "Skyrim Save Wizard / Save Research Spreadsheet</a></p>"
            "<p><b>Free PS4 save decryption:</b><br>"
            "<a href='https://discord.gg/protobuffers'>discord.gg/protobuffers</a></p>"
        )
        info.setWordWrap(True)
        info.setOpenExternalLinks(True)
        info.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        card.layout.addWidget(info)
        layout.addWidget(card)

        features = Card("Current editor abilities")
        feature_text = QLabel(
            "<h3>General Tab</h3>"
            "<ul>"
            "<li>Player Name — mapped, still under testing / not fully working.</li>"
            "<li>Level — mapped, still under testing / not fully working.</li>"
            "<li>XP / XP Pool editor.</li>"
            "<li>Individual skill editor: One-Handed, Lockpicking, Sneak, and the other Skyrim skills.</li>"
            "<li>Stat editor: Health, Magicka, Stamina, Carry Weight.</li>"
            "<li>Gold, Lockpick, and Dragon Souls editor. Dragon Souls now uses the live actor-value field, not the DragonsAbsorbed global.</li>"
            "</ul>"
            "<h3>Player Inventory</h3>"
            "<p><b>DLC / Creation Club / plugin inventory may be broken or incomplete.</b> Send saves if you want those mapped.</p>"
            "<ul>"
            "<li>Current Inventory editor: edit counts for items already on hand.</li>"
            "<li>Item Database / Add Item: add base-game items from the bundled database.</li>"
            "</ul>"
            "<h3>Magic Tab</h3>"
            "<ul><li>Safe spell, shout, power, and ability checkbox workflow that generates Skyrim console batch scripts.</li><li>Experimental add/unlock-only save copy workflow for testing without overwriting the original save.</li></ul>"
            "<h3>Plugin Detector Tab</h3>"
            "<ul><li>Shows detected plugin/save metadata used while mapping FormIDs.</li></ul>"
            "<h3>Raw Editor Tab</h3>"
            "<ul>"
            "<li>Mapped Fields: faster fixed-size value editing from known save offsets.</li>"
            "<li>Change Forms: low-level save records for inspection.</li>"
            "<li>Format Reference: save format notes based on the UESP reference.</li>"
            "<li>Quick Codes: Save Wizard-style helper/reference based on "
            "<a href='https://playersquared.com/threads/save-wizard-custom-quick-code-formats.1607/'>PlayerSquared quick-code format notes</a>.</li>"
            "<li>Parsed JSON: readable parsed-save view with search, syntax validation, formatting, compacting, undo, and export.</li>"
            "</ul>"
        )
        feature_text.setWordWrap(True)
        feature_text.setOpenExternalLinks(True)
        feature_text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        features.layout.addWidget(feature_text)
        layout.addWidget(features)

        safety = Card("Testing warning")
        warning = QLabel(
            "This is public-testing software. Always keep a clean backup, use Save Copy for first tests, "
            "and verify the edited save loads before overwriting your only working file."
        )
        warning.setWordWrap(True)
        safety.layout.addWidget(warning)
        layout.addWidget(safety)
        layout.addStretch(1)
        return page

    def _switch_page(self, row: int) -> None:
        self.stack.setCurrentIndex(row)

    def apply_theme(self, name: str) -> None:
        QApplication.instance().setStyleSheet(THEMES.get(name, THEMES["Obsidian"]))

    def open_save_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Skyrim Save", "", "Skyrim Saves (*.ess *.ESS *.dat *.DAT);;All Files (*)")
        if path:
            self.open_save(Path(path))

    def open_save(self, path: Path) -> None:
        try:
            doc = read_ess(path)
        except (OSError, EssParseError, ValueError) as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return
        self.current_save = path
        self.current_doc = doc
        try:
            self.working_save_bytes = path.read_bytes()
        except OSError:
            self.working_save_bytes = None
        self.working_save_dirty = False
        self.working_save_label = path.name
        self.inventory_pending_adds.clear()
        self.magic_pending_changes.clear()
        self.path_edit.setText(str(path))
        self._refresh_all_from_doc()
        self.statusBar().showMessage(f"Loaded {path.name}", 5000)

    def reload_current_save(self) -> None:
        if not self.current_save:
            return
        self.open_save(self.current_save)

    def _refresh_all_from_doc(self) -> None:
        if not self.current_doc:
            return
        self._refresh_summary()
        self._refresh_header_editor()
        self.refresh_skill_values_from_save(silent=True)
        self.refresh_actor_values_from_save(silent=True)
        self.refresh_inventory(silent=True)
        self.refresh_magic_page(silent=True)
        self._refresh_general_inventory_values()
        self._refresh_common_global_values()
        self._refresh_plugins()
        self.load_raw_json_from_doc()
        self.refresh_raw_editor()
        self.refresh_backup_table()
        self.refresh_coverage()

    def _refresh_summary(self) -> None:
        assert self.current_doc is not None
        h = self.current_doc.header
        rows = [
            ("Loaded File", str(self.current_save) if self.current_save else str(self.current_doc.path)),
            ("Working Copy", "Modified in memory" if self.working_save_dirty else "Synced with loaded file"),
            ("File Size", f"{self.current_doc.file_size:,} bytes"),
            ("Version", str(h.version)),
            ("Save Number", str(h.save_number)),
            ("Player", h.player_name),
            ("Level", str(h.player_level)),
            ("Location", h.player_location),
            ("Race", h.player_race),
            ("Sex", h.sex_text),
            ("Game Date", h.game_date),
            ("Screenshot", f"{h.screenshot_width} x {h.screenshot_height}"),
            ("Compression", h.compression_text),
            ("Screenshot BPP", str(h.screenshot_bpp)),
            ("Payload", f"{self.current_doc.payload.uncompressed_size:,} bytes decompressed" if self.current_doc.payload else "Unavailable"),
            ("Form Version", str(self.current_doc.payload.form_version) if self.current_doc.payload else "Unknown"),
            ("Plugins", str(len(self.current_doc.plugin_info.plugins) if self.current_doc.plugin_info else 0)),
            ("Light Plugins", str(len(self.current_doc.plugin_info.light_plugins) if self.current_doc.plugin_info else 0)),
            ("Change Forms", str(self.current_doc.file_location_table.change_form_count) if self.current_doc.file_location_table else "Unknown"),
        ]
        if self.current_doc.warnings:
            rows.append(("Warnings", " | ".join(self.current_doc.warnings)))
        self.summary_table.setRowCount(len(rows))
        for row, (field, value) in enumerate(rows):
            self.summary_table.setItem(row, 0, QTableWidgetItem(field))
            self.summary_table.setItem(row, 1, QTableWidgetItem(value))
        self.summary_table.resizeColumnsToContents()

    def _refresh_header_editor(self) -> None:
        if not self.current_doc or not hasattr(self, "name_view"):
            return
        h = self.current_doc.header
        live = None
        try:
            live = read_live_player_fields(self.current_save) if self.current_save else None
        except Exception:
            live = None
        self._live_player_fields = live
        self.name_view.setText(live.name if live and live.name else h.player_name)
        self.location_view.setText(h.player_location)
        self._race_mapping = None
        try:
            self._race_mapping = read_skyrim_race_mapping(self.current_save) if self.current_save else None
        except Exception:
            self._race_mapping = None
        race_id = (self._race_mapping.active_race.editor_id if self._race_mapping and self._race_mapping.active_race else h.player_race)
        if hasattr(self, "race_combo"):
            idx = self.race_combo.findData(race_id)
            if idx < 0:
                idx = self.race_combo.findText(race_id)
            self.race_combo.setCurrentIndex(max(0, idx))
        self.game_date_view.setText(h.game_date)
        level_value = live.level if live and live.level is not None else h.player_level
        self.level_spin.setValue(max(1, min(65535, int(level_value))))
        self.sex_combo.setCurrentIndex(1 if h.player_sex == 1 else 0)
        self.need_exp_spin.setValue(float(h.player_needed_exp))
        if hasattr(self, "cur_exp_spin"):
            try:
                xp_pool, _searches, _payload_size = read_skyrim_xp_pool(self.current_save) if self.current_save else (0.0, [], 0)
                self.cur_exp_spin.setEnabled(True)
                self.cur_exp_spin.setValue(float(xp_pool))
                self.cur_exp_spin.setToolTip("Editable XP Pool payload value used by the +EXP command.")
            except Exception as exc:
                self.cur_exp_spin.setEnabled(False)
                self.cur_exp_spin.setValue(0.0)
                self.cur_exp_spin.setToolTip(f"XP Pool could not be located in this save: {exc}")
        self._update_name_slot_hint()

    def _update_name_slot_hint(self) -> None:
        if not hasattr(self, "name_slot_label"):
            return
        capacity = self.current_doc.header.player_name_capacity if self.current_doc else 0
        used = len(self.name_view.text().encode("utf-8")) if hasattr(self, "name_view") else 0
        if capacity <= 0:
            self.name_slot_label.setText("Open a save to detect the editable name slot.")
            return
        remaining = capacity - used
        if remaining < 0:
            self.name_slot_label.setText(f"{used}/{capacity} bytes — too long for this save")
        else:
            live = getattr(self, "_live_player_fields", None)
            if live and live.name_length is not None:
                self.name_slot_label.setText(f"{used} bytes typed — live ChangeForm name length currently {live.name_length} byte(s); header slot {capacity} byte(s)")
            else:
                self.name_slot_label.setText(f"{used}/{capacity} bytes used — header slot only; live name not mapped")

    def refresh_inventory(self, silent: bool = False) -> None:
        if not self.current_save:
            if not silent:
                QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        try:
            block = read_player_inventory(self.current_save)
        except Exception as exc:
            self.current_inventory = None
            self.inventory_dirty_counts.clear()
            self.inventory_pending_adds.clear()
            self.inventory_row_offsets.clear()
            self.inventory_row_editable.clear()
            self.inventory_row_original_counts.clear()
            self.inventory_row_entries.clear()
            self.inventory_insert_layout_preflight = None
            self.inventory_selected_offset = None
            if hasattr(self, "inventory_table"):
                self.inventory_table.setRowCount(0)
            self._refresh_general_inventory_values()
            self._update_inventory_storage_info()
            if not silent:
                QMessageBox.critical(self, "Inventory parse failed", str(exc))
            return
        self.current_inventory = block
        self.inventory_dirty_counts.clear()
        self.inventory_pending_adds.clear()
        self.inventory_row_offsets.clear()
        self.inventory_row_editable.clear()
        self.inventory_row_original_counts.clear()
        self.inventory_row_entries.clear()
        self.inventory_insert_layout_preflight = None
        self.inventory_selected_offset = None
        self.inventory_active_category = getattr(self, "inventory_active_category", "All") or "All"
        self.inventory_categories = []
        self._loading_inventory_table = True
        self.inventory_table.blockSignals(True)
        self.inventory_table.setRowCount(len(block.entries))
        for row, entry in enumerate(block.entries):
            display_name, category = self._inventory_display_name(entry.form_id, entry.name)
            if entry.editable and int(entry.displayed_count) == 0:
                status = "Dormant/Re-add"
            else:
                status = "Editable" if entry.editable else "Read-only"
            values = [
                display_name,
                str(entry.displayed_count),
                category,
                status,
                entry.note,
            ]
            self.inventory_row_offsets[row] = entry.payload_offset
            self.inventory_row_editable[row] = entry.editable
            self.inventory_row_original_counts[row] = entry.displayed_count
            self.inventory_row_entries[row] = entry
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == self.INV_COL_ITEM:
                    item.setData(Qt.ItemDataRole.UserRole, entry.form_id)
                    item.setToolTip(f"FormID: {entry.form_id} | Row: {entry.row} | Payload offset: 0x{entry.payload_offset:X}")
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                elif col == self.INV_COL_COUNT:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    if entry.editable:
                        item.setToolTip(f"Double-click to edit. Safe maximum: {MAX_SAFE_INVENTORY_COUNT:,}.")
                    else:
                        item.setToolTip("This detected row is not editable yet.")
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col == self.INV_COL_STATUS:
                    if status in ("Editable", "Dormant/Re-add"):
                        item.setForeground(self.palette().brush(self.foregroundRole()))
                    else:
                        item.setForeground(self.palette().mid())
                self.inventory_table.setItem(row, col, item)
        self.inventory_table.blockSignals(False)
        self._loading_inventory_table = False
        self.inventory_table.resizeRowsToContents()
        self.inventory_table.setColumnWidth(self.INV_COL_ITEM, max(280, self.inventory_table.columnWidth(self.INV_COL_ITEM)))
        self._refresh_general_inventory_values()
        self.inventory_table.setColumnWidth(self.INV_COL_COUNT, 90)
        self.inventory_table.setColumnWidth(self.INV_COL_NOTE, 340)
        self._rebuild_inventory_tabs()
        if hasattr(self, "inventory_filter_edit"):
            self._apply_inventory_filter()
        if block.warning and not silent:
            self.statusBar().showMessage(block.warning, 7000)
        elif not silent:
            self.statusBar().showMessage(f"Loaded {len(block.entries)} inventory rows. Use category tabs to sort the view; Save Changes writes after backup.", 5000)
        self.refresh_coverage()
        self.refresh_inventory_database_table()
        self._update_inventory_storage_info()
        self.refresh_inventory_research_report()

    def _rebuild_inventory_tabs(self) -> None:
        if not hasattr(self, "inventory_tabs") or not hasattr(self, "inventory_table"):
            return
        counts: dict[str, int] = {}
        for row in range(self.inventory_table.rowCount()):
            item = self.inventory_table.item(row, self.INV_COL_CATEGORY)
            category = item.text().strip() if item and item.text().strip() else "Other"
            counts[category] = counts.get(category, 0) + 1
        categories = sorted(counts, key=lambda c: (c.casefold()))
        previous = self.inventory_active_category if self.inventory_active_category in counts or self.inventory_active_category == "All" else "All"
        self.inventory_tabs.blockSignals(True)
        while self.inventory_tabs.count():
            self.inventory_tabs.removeTab(0)
        self.inventory_tabs.addTab(f"All ({self.inventory_table.rowCount()})")
        for category in categories:
            self.inventory_tabs.addTab(f"{category} ({counts[category]})")
        wanted = 0
        if previous != "All":
            for i in range(1, self.inventory_tabs.count()):
                label = self.inventory_tabs.tabText(i)
                if label.rsplit(" (", 1)[0] == previous:
                    wanted = i
                    break
        self.inventory_tabs.setCurrentIndex(wanted)
        self.inventory_tabs.blockSignals(False)
        self.inventory_active_category = previous if wanted != 0 else "All"

    def _inventory_tab_changed(self, index: int) -> None:
        if not hasattr(self, "inventory_tabs"):
            return
        label = self.inventory_tabs.tabText(index) if index >= 0 else "All"
        self.inventory_active_category = label.rsplit(" (", 1)[0] if label else "All"
        self._apply_inventory_filter()

    def _apply_inventory_filter(self) -> None:
        if not hasattr(self, "inventory_table") or not hasattr(self, "inventory_filter_edit"):
            return
        needle = self.inventory_filter_edit.text().strip().casefold()
        active_category = getattr(self, "inventory_active_category", "All") or "All"
        for row in range(self.inventory_table.rowCount()):
            category_item = self.inventory_table.item(row, self.INV_COL_CATEGORY)
            category = category_item.text().strip() if category_item and category_item.text().strip() else "Other"
            category_match = active_category == "All" or category == active_category
            text_match = True
            if needle:
                parts: list[str] = []
                for col in range(self.inventory_table.columnCount()):
                    item = self.inventory_table.item(row, col)
                    if item:
                        parts.append(item.text())
                        if col == self.INV_COL_ITEM:
                            parts.append(str(item.data(Qt.ItemDataRole.UserRole) or ""))
                haystack = " ".join(parts).casefold()
                text_match = needle in haystack
            self.inventory_table.setRowHidden(row, not (category_match and text_match))

    def _active_plugin_list(self) -> list[str]:
        if self.current_doc and self.current_doc.plugin_info:
            return list(self.current_doc.plugin_info.plugins)
        return []

    def _record_sort_score(self, rec, active_id: str = "") -> tuple[int, int, int, int]:
        score = 0
        src = (getattr(rec, "source", "") or "").casefold()
        if (getattr(rec, "source", "") or "").strip().lower().endswith((".esm", ".esp", ".esl")):
            score += 60
        if infer_plugin_name(getattr(rec, "source", ""), getattr(rec, "editor_id", ""), getattr(rec, "name", ""), getattr(rec, "notes", "")):
            score += 20
        if active_id and active_id[:2] != "XX":
            score += 10
        if getattr(rec, "editor_id", ""):
            score += 6
        if getattr(rec, "name", ""):
            score += 6
        if "curated" in src or "uesp" in src:
            score += 4
        return (score, len(getattr(rec, "name", "") or ""), len(getattr(rec, "editor_id", "") or ""), -len(getattr(rec, "source", "") or ""))

    def _db_record_for_form_id(self, form_id: str):
        plugins = self._active_plugin_list()
        rec = self.db.by_form_id(form_id, plugins) if hasattr(self.db, "by_form_id") else None
        if rec:
            return rec
        wanted = normalize_id(form_id)
        if not wanted or len(wanted) != 8:
            return None
        candidates = []
        for cand in getattr(self.db, "records", []):
            if not cand.form_id:
                continue
            active = self._resolve_record_form_id(cand.form_id, cand.source, cand.editor_id, cand.name, cand.notes) or cand.form_id
            if normalize_id(active) == wanted:
                candidates.append((self._record_sort_score(cand, active), cand))
        if candidates:
            return sorted(candidates, key=lambda x: x[0], reverse=True)[0][1]
        return None

    def _inventory_display_name(self, form_id: str, fallback: str = "") -> tuple[str, str]:
        rec = self._db_record_for_form_id(form_id)
        if rec and rec.name and rec.name.casefold() != "unknown item":
            return rec.name, rec.category or "Item"
        if fallback:
            return fallback, rec.category if rec and rec.category else "Item"
        return "Unknown item", rec.category if rec and rec.category else "Unknown"

    def _inventory_database_allowed_categories(self) -> set[str]:
        return {
            "currency", "arrows", "blades", "blunts", "bows", "staves", "weapons",
            "heavy armor", "light armor", "armor", "clothing", "jewelry",
            "books", "keys", "scrolls", "spell tomes", "soul gems",
            "alchemy", "poisons", "food", "beverages", "ingredients",
            "misc", "crafting", "ores and ingots", "building materials", "gems",
            "detectedcandidate",
        }

    def _inventory_database_records(self):
        allowed = self._inventory_database_allowed_categories()
        best: dict[tuple[str, str, str], object] = {}
        for rec in self.db.records:
            if not rec.form_id:
                continue
            if rec.category.casefold() not in allowed:
                continue
            if not rec.name and not rec.editor_id:
                continue
            active_id = self._resolve_record_form_id(rec.form_id, rec.source, rec.editor_id, rec.name, rec.notes) or rec.form_id
            norm_active = normalize_id(active_id)
            # Item Database is an add/edit database, so one resolved FormID should
            # appear once. If sources disagree on the name/category, keep the
            # highest-scoring source row and hide the duplicate/conflict row.
            key = (norm_active,)
            old = best.get(key)
            if old is None or self._record_sort_score(rec, norm_active) > self._record_sort_score(old, norm_active):
                best[key] = rec
        return list(best.values())

    def _normalize_lookup_form_id(self, value: str) -> str:
        raw = (value or "").strip().replace("0x", "").replace("0X", "").upper()
        if raw.startswith("XX") and len(raw) <= 8:
            return "XX" + "".join(ch for ch in raw[2:] if ch in "0123456789ABCDEF").zfill(6)
        raw = "".join(ch for ch in raw if ch in "0123456789ABCDEF")
        if not raw:
            return ""
        return raw.zfill(8)[-8:]

    def _find_inventory_row_by_form_id(self, form_id: str) -> int:
        target = self._normalize_lookup_form_id(form_id)
        if not target or not hasattr(self, "inventory_table"):
            return -1
        suffix = ""
        if target.startswith("XX") and len(target) == 8:
            suffix = target[2:]
        for row in range(self.inventory_table.rowCount()):
            item = self.inventory_table.item(row, self.INV_COL_ITEM)
            row_id = str(item.data(Qt.ItemDataRole.UserRole) or "").upper() if item else ""
            if not row_id:
                continue
            if row_id == target:
                return row
            if suffix and row_id.endswith(suffix):
                return row
        return -1

    def _inventory_database_status_for_id(self, form_id: str) -> str:
        clean = (form_id or "").strip().upper().zfill(8)[-8:]
        if clean in getattr(self, "inventory_pending_adds", {}):
            return "Pending add"
        if not self.current_inventory:
            return "No save loaded"
        row = self._find_inventory_row_by_form_id(form_id)
        if row < 0:
            return "Missing"
        original = int(self.inventory_row_original_counts.get(row, 0))
        return "Dormant row" if original == 0 else "In inventory"

    def _direct_insert_support(self, form_id: str) -> tuple[bool, str]:
        clean = (form_id or "").strip().replace("0x", "").replace("0X", "").upper()
        if not clean:
            return False, "No FormID."
        if clean.startswith(("XX", "FE", "FF")):
            return False, "Plugin/light/temp FormIDs still need FormIDArray mapping before PS4 direct insertion is safe."
        if len(clean) > 8 or any(ch not in "0123456789ABCDEF" for ch in clean):
            return False, "Invalid or placeholder FormID."
        clean = clean.zfill(8)[-8:]
        try:
            value = int(clean, 16)
        except ValueError:
            return False, "Invalid hexadecimal FormID."
        if value <= 0 or value > 0x3FFFFF:
            return False, "This FormID range needs FormIDArray/plugin insertion mapping before PS4 direct insertion is safe."
        if not self.current_save:
            return False, "Open a save first."
        if self.inventory_insert_layout_preflight is None:
            self.inventory_insert_layout_preflight = preflight_player_inventory_insert_layout(self.current_save)
        ok, reason = self.inventory_insert_layout_preflight
        if not ok:
            return False, f"Direct missing-item insertion disabled: {reason}"
        return True, reason

    def _refresh_inventory_database_categories(self) -> None:
        if not hasattr(self, "inv_db_category_combo"):
            return
        current = self.inv_db_category_combo.currentText()
        cats = sorted({rec.category for rec in self._inventory_database_records() if rec.category}, key=lambda c: c.casefold())
        self.inv_db_category_combo.blockSignals(True)
        self.inv_db_category_combo.clear()
        self.inv_db_category_combo.addItem("All item categories")
        for cat in cats:
            self.inv_db_category_combo.addItem(cat)
        idx = self.inv_db_category_combo.findText(current)
        if idx >= 0:
            self.inv_db_category_combo.setCurrentIndex(idx)
        self.inv_db_category_combo.blockSignals(False)

    def refresh_inventory_database_table(self) -> None:
        if not hasattr(self, "inv_db_table"):
            return
        self._refresh_inventory_database_categories()
        needle = self.inv_db_filter_edit.text().strip().casefold() if hasattr(self, "inv_db_filter_edit") else ""
        category = self.inv_db_category_combo.currentText() if hasattr(self, "inv_db_category_combo") else "All item categories"
        status_filter = self.inv_db_status_combo.currentText() if hasattr(self, "inv_db_status_combo") else "All items"
        category_filter = "" if category in ("", "All item categories") else category.casefold()
        rows = []
        for rec in self._inventory_database_records():
            resolved = self._resolve_record_form_id(rec.form_id, rec.source, rec.editor_id, rec.name, rec.notes)
            active_id = resolved or rec.form_id
            status = self._inventory_database_status_for_id(active_id)
            can_direct, reason = self._direct_insert_support(active_id)
            if status == "In inventory":
                add_method = "Edit count"
            elif status == "Dormant row":
                add_method = "Re-add exact row"
            elif status == "Pending add":
                add_method = "Save Edits"
            else:
                add_method = "Preflight direct add" if can_direct else "Console only"
            if category_filter and rec.category.casefold() != category_filter:
                continue
            if status_filter == "In inventory" and status not in ("In inventory", "Dormant row"):
                continue
            if status_filter == "Missing from inventory" and status != "Missing":
                continue
            if status_filter == "Pending add" and status != "Pending add":
                continue
            if status_filter == "Preflight direct add" and not (status == "Missing" and can_direct):
                continue
            if status_filter == "Console command only" and not (status == "Missing" and not can_direct):
                continue
            haystack = " ".join([rec.name, rec.editor_id, rec.form_id, active_id, rec.category, rec.source, rec.notes, status, add_method, reason]).casefold()
            if needle and needle not in haystack:
                continue
            rows.append((rec, active_id, status, add_method, reason))
            if len(rows) >= 750:
                break
        if hasattr(self, "inv_insert_preflight_label"):
            if not self.current_save:
                self.inv_insert_preflight_label.setText("Direct missing-item insertion: open a save to run preflight. Base-game missing items can be staged only if the layout is mapped.")
            else:
                if self.inventory_insert_layout_preflight is None:
                    self.inventory_insert_layout_preflight = preflight_player_inventory_insert_layout(self.current_save)
                ok, reason = self.inventory_insert_layout_preflight
                state = "ENABLED for simple base-game stacks" if ok else "disabled"
                self.inv_insert_preflight_label.setText(f"Direct missing-item insertion is {state}. {reason} Dormant rows re-add through exact count edits. Truly missing items that do not pass this stay blocked for PS4 safety.")
        self.inv_db_table.setRowCount(len(rows))
        for row, (rec, active_id, status, add_method, reason) in enumerate(rows):
            name = rec.name or rec.editor_id or "Unknown item"
            values = [name, active_id or rec.form_id, rec.category, status, add_method, rec.source]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, active_id or rec.form_id)
                    plugin_hint = infer_plugin_name(rec.source, rec.editor_id, rec.name, rec.notes) or rec.source
                    item.setToolTip(f"EditorID: {rec.editor_id}\nOriginal FormID: {rec.form_id}\nResolved/FormID: {active_id or rec.form_id}\nPlugin hint: {plugin_hint}\nAdd method: {add_method}\nReason: {reason}\nNotes: {rec.notes}")
                if col == 4:
                    item.setToolTip(reason)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.inv_db_table.setItem(row, col, item)
        self.inv_db_table.resizeColumnsToContents()
        if self.inv_db_table.columnWidth(0) < 260:
            self.inv_db_table.setColumnWidth(0, 260)

    def _selected_inventory_database_item(self) -> tuple[str, str, str]:
        if not hasattr(self, "inv_db_table"):
            return "", "", ""
        row = self.inv_db_table.currentRow()
        if row < 0:
            return "", "", ""
        name_item = self.inv_db_table.item(row, 0)
        id_item = self.inv_db_table.item(row, 1)
        status_item = self.inv_db_table.item(row, 3)
        form_id = id_item.text().strip() if id_item and id_item.text() else ""
        name = name_item.text().strip() if name_item and name_item.text() else "Selected item"
        status = status_item.text().strip() if status_item and status_item.text() else ""
        return form_id, name, status

    def copy_inventory_database_additem_command(self) -> None:
        form_id, name, _status = self._selected_inventory_database_item()
        if not form_id:
            QMessageBox.information(self, "No database item selected", "Select an item in the Item Database first.")
            return
        amount = self.inv_db_amount_spin.value() if hasattr(self, "inv_db_amount_spin") else 1
        command = f"player.additem {form_id} {amount}"
        QApplication.clipboard().setText(command)
        self.statusBar().showMessage(f"Copied additem command for {name}: {command}", 3500)

    def add_inventory_database_item_to_save(self) -> None:
        """End-user add action from the Item Database tab.

        Existing rows and supported missing simple rows are staged into the same
        inventory edit workflow. The Save Edits button performs the actual write
        after creating a backup.
        """
        form_id, name, _status = self._selected_inventory_database_item()
        if not form_id:
            QMessageBox.information(self, "No database item selected", "Select an item in the Item Database first.")
            return
        amount = self.inv_db_amount_spin.value() if hasattr(self, "inv_db_amount_spin") else 1
        row = self._find_inventory_row_by_form_id(form_id)
        if row >= 0:
            if not self.inventory_row_editable.get(row, False):
                QMessageBox.information(self, "Read-only row", "That inventory row is detected but is not editable yet.")
                return
            current = self._inventory_table_count(row)
            try:
                new_count = validate_inventory_amount(current + amount)
            except Exception as exc:
                QMessageBox.warning(self, "Invalid count", str(exc))
                return
            self.inventory_workspace_tabs.setCurrentIndex(0)
            self.inventory_active_category = "All"
            if hasattr(self, "inventory_tabs"):
                self.inventory_tabs.setCurrentIndex(0)
            if hasattr(self, "inventory_filter_edit"):
                self.inventory_filter_edit.clear()
            self.inventory_table.selectRow(row)
            count_item = self.inventory_table.item(row, self.INV_COL_COUNT)
            if count_item:
                count_item.setText(str(new_count))
            action_word = "Re-added" if current == 0 else "Staged"
            self.statusBar().showMessage(f"{action_word} {name}: New Count {new_count:,}. Press Save Edits to write it.", 4500)
            self.refresh_inventory_database_table()
            self.refresh_inventory_research_report()
            return
        self.add_missing_inventory_database_item_to_save()

    def add_missing_inventory_database_item_to_save(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "Open a save first", "Open a Skyrim save before adding a missing item.")
            return
        form_id, name, status = self._selected_inventory_database_item()
        if not form_id:
            QMessageBox.information(self, "No database item selected", "Select an item in the Item Database first.")
            return
        clean = form_id.strip().upper().zfill(8)[-8:]
        amount = self.inv_db_amount_spin.value() if hasattr(self, "inv_db_amount_spin") else 1
        existing_row = self._find_inventory_row_by_form_id(clean)
        if existing_row >= 0:
            QMessageBox.information(
                self,
                "Item already exists",
                f"{name} already has an inventory row. Use Add Selected To Save to add to its New Count, or Set Existing Count to replace it."
            )
            return
        can_direct, reason = self._direct_insert_support(clean)
        if can_direct:
            self.inventory_pending_adds[clean] = {"name": name, "amount": amount}
            self._refresh_inventory_queue_label()
            self.refresh_inventory_database_table()
            self.refresh_inventory_research_report()
            QMessageBox.information(
                self,
                "Item staged",
                f"Staged missing item for PS4 fake/minimal direct add:\n\n{name}\n{clean}\nAmount: {amount:,}\n\nPress Save Edits to write it at the mapped inventory-list boundary. A backup will be created first. Use Preview Fake Row to see the exact generated bytes."
            )
            self.statusBar().showMessage(f"Staged {name} for direct add. Press Save Edits to write it.", 4500)
            return
        command = f"player.additem {form_id} {amount}"
        QApplication.clipboard().setText(command)
        QMessageBox.warning(
            self,
            "Direct add not safe for this item yet",
            f"This item is not mapped for direct save insertion yet.\n\nItem: {name}\nFormID: {form_id}\nReason: {reason}\n\nFor PC/testing only, I copied this fallback command:\n{command}\n\nFor PS4, use a save where this item already has a dormant zero-count row or send a controlled normal/add/remove pair for this exact item type. The editor will only write brand-new rows when the save passes the direct-insert preflight."
        )
        self.statusBar().showMessage(f"Direct add is not safe for {name} on this save yet.", 3500)
        return


    def preview_inventory_fake_row_plan(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "Open a save first", "Open a Skyrim save before previewing generated item data.")
            return
        form_id, name, _status = self._selected_inventory_database_item()
        if not form_id:
            QMessageBox.information(self, "No database item selected", "Select an item in the Item Database first.")
            return
        amount = self.inv_db_amount_spin.value() if hasattr(self, "inv_db_amount_spin") else 1
        try:
            text = build_simple_player_inventory_insert_plan(self.current_save, form_id, amount)
        except Exception as exc:
            QMessageBox.warning(self, "Fake row preview blocked", str(exc))
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Fake Row / Direct Add Plan - {name}")
        dlg.resize(860, 560)
        layout = QVBoxLayout(dlg)
        box = QPlainTextEdit()
        box.setReadOnly(True)
        box.setPlainText(text)
        layout.addWidget(box, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        copy_btn = buttons.addButton("Copy Plan", QDialogButtonBox.ButtonRole.ActionRole)
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(text))
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        dlg.exec()

    def find_inventory_database_item_in_inventory(self) -> None:
        form_id, name, _status = self._selected_inventory_database_item()
        if not form_id:
            QMessageBox.information(self, "No database item selected", "Select an item in the Item Database first.")
            return
        row = self._find_inventory_row_by_form_id(form_id)
        if row < 0:
            QMessageBox.information(self, "Missing from inventory", f"{name} is not an existing inventory row in this save yet. Use Stage Add / Count for PS4 fake-row insertion if this save passes preflight, or send a clean controlled pair for this item type.")
            return
        self.inventory_active_category = "All"
        if hasattr(self, "inventory_tabs"):
            self.inventory_tabs.setCurrentIndex(0)
        if hasattr(self, "inventory_filter_edit"):
            self.inventory_filter_edit.clear()
        self.inventory_table.selectRow(row)
        self.inventory_table.scrollToItem(self.inventory_table.item(row, self.INV_COL_ITEM))

    def apply_inventory_database_item(self, mode: str) -> None:
        form_id, name, _status = self._selected_inventory_database_item()
        if not form_id:
            QMessageBox.information(self, "No database item selected", "Select an item in the Item Database first.")
            return
        amount = self.inv_db_amount_spin.value() if hasattr(self, "inv_db_amount_spin") else 1
        row = self._find_inventory_row_by_form_id(form_id)
        if row < 0:
            QMessageBox.information(
                self,
                "Item is missing from this save",
                f"{name} does not have an inventory row yet. Use Stage Add / Count for PS4 fake-row insertion if this save passes preflight, or send a clean controlled add/remove pair for this item type."
            )
            return
        if not self.inventory_row_editable.get(row, False):
            QMessageBox.information(self, "Read-only row", "That inventory row is detected but is not editable yet.")
            return
        current = self._inventory_table_count(row)
        try:
            new_count = validate_inventory_amount(amount if mode == "set" else current + amount)
        except Exception as exc:
            QMessageBox.warning(self, "Invalid count", str(exc))
            return
        self.inventory_table.selectRow(row)
        count_item = self.inventory_table.item(row, self.INV_COL_COUNT)
        if count_item:
            count_item.setText(str(new_count))
        self.statusBar().showMessage(f"Updated {name}: New Count {new_count:,}", 3000)
        self.refresh_inventory_database_table()
        self.refresh_inventory_research_report()

    def _inventory_selection_changed(self) -> None:
        items = self.inventory_table.selectedItems()
        if not items:
            return
        row = items[0].row()
        name_item = self.inventory_table.item(row, self.INV_COL_ITEM)
        count_item = self.inventory_table.item(row, self.INV_COL_COUNT)
        self.inventory_selected_offset = None
        if name_item:
            form_id = name_item.data(Qt.ItemDataRole.UserRole) or ""
            self.inventory_selected_offset = self.inventory_row_offsets.get(row)
            self.inv_form_edit.setText(str(form_id))
            self.inv_selected_formid.setText(str(form_id))
            self.inv_name_edit.setText(name_item.text())
        if count_item:
            try:
                self._updating_inventory_editor = True
                self.inv_amount_spin.setValue(int(count_item.text()))
            except ValueError:
                pass
            finally:
                self._updating_inventory_editor = False
        self._update_inventory_storage_info()

    def _format_inventory_storage_info(self, row: int) -> str:
        entry = self.inventory_row_entries.get(row)
        if not entry:
            return "No decoded storage info for this row."
        effective = self.inventory_dirty_counts.get(int(entry.payload_offset), int(entry.displayed_count))
        sign_style = "negative/raw absolute count" if int(entry.raw_count) < 0 else "normal positive count"
        compression = "compressed" if getattr(self.current_inventory, "player_data_compressed", False) else "uncompressed"
        lines = [
            f"Item: {self.inventory_table.item(row, self.INV_COL_ITEM).text() if self.inventory_table.item(row, self.INV_COL_ITEM) else entry.name or entry.form_id}",
            f"FormID: {entry.form_id}",
            f"Encoded RefID bytes: {entry.refid_hex}",
            f"Reference type/value: type {entry.ref_type}, value 0x{entry.ref_value:X}",
            f"Player-data row offset: 0x{entry.player_data_offset:X}",
            f"Payload offset: 0x{entry.payload_offset:X}",
            f"Virtual offset: 0x{entry.virtual_offset:X}",
            f"Raw signed count: {entry.raw_count:,}",
            f"Displayed count: {entry.displayed_count:,}",
            f"Pending/new count: {int(effective):,}",
            f"Count sign style: {sign_style}",
            f"Extra/flag byte: 0x{entry.extra:02X}",
            f"Confidence: {entry.confidence}",
            f"Editable: {'yes' if entry.editable else 'no'}",
            f"Player ChangeForm storage: {compression} ({getattr(self.current_inventory, 'player_data_compression', 'none')})",
            f"Note: {entry.note}",
        ]
        if not entry.editable:
            lines.append("Safety: this row is shown for research but count editing is disabled.")
        elif int(entry.displayed_count) == 0:
            lines.append("Safety: dormant row. Setting New Count above 0 re-adds this existing row; no new bytes are inserted.")
            if entry.form_id not in ("0000000F", "0000000A"):
                lines.append("Write style: controlled add/remove saves showed these dormant rows should revive with a negative raw count.")
        elif int(entry.payload_offset) in self.inventory_dirty_counts:
            lines.append("Safety: exact existing-row count edit is staged; no new row will be inserted.")
        else:
            lines.append("Safety: existing-row count edits patch only the signed int32 count at row offset + 3.")
        return "\n".join(lines)

    def _update_inventory_storage_info(self) -> None:
        if not hasattr(self, "inv_storage_info"):
            return
        row = self.inventory_table.currentRow() if hasattr(self, "inventory_table") else -1
        if row < 0 or row not in self.inventory_row_entries:
            if self.current_inventory and getattr(self.current_inventory, "player_data_compressed", False):
                text = "Player ChangeForm is compressed; existing-row edits are handled by decompress/recompress support. Select a row to inspect exact storage."
            else:
                text = "Select an inventory row to inspect its exact save storage. Missing items should be added in-game with player.additem, then edited here after reopening the save."
        else:
            text = self._format_inventory_storage_info(row)
        self.inv_storage_info.setPlainText(text)
        if hasattr(self, "inv_storage_tip_btn"):
            self.inv_storage_tip_btn.setToolTip(text)
            if row >= 0 and row in self.inventory_row_entries:
                self.inv_storage_tip_btn.setText("Storage Info ✓")
            else:
                self.inv_storage_tip_btn.setText("Storage Info")

    def show_inventory_storage_info_dialog(self) -> None:
        if not hasattr(self, "inv_storage_info"):
            return
        text = self.inv_storage_info.toPlainText().strip()
        if not text:
            text = "Select an inventory row first."
        dlg = QDialog(self)
        dlg.setWindowTitle("Selected Inventory Storage Info")
        dlg.resize(760, 520)
        layout = QVBoxLayout(dlg)
        info = QPlainTextEdit()
        info.setReadOnly(True)
        info.setPlainText(text)
        layout.addWidget(info, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dlg.reject)
        buttons.accepted.connect(dlg.accept)
        layout.addWidget(buttons)
        dlg.exec()

    def copy_inventory_storage_info(self) -> None:
        if not hasattr(self, "inv_storage_info"):
            return
        text = self.inv_storage_info.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Nothing to copy", "Select an inventory row first.")
            return
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("Copied selected inventory storage info.", 2500)

    def export_inventory_storage_csv_dialog(self) -> None:
        if not self.current_inventory:
            QMessageBox.information(self, "No inventory loaded", "Open a save first.")
            return
        default = "skyrim_inventory_storage.csv"
        if self.current_save:
            default = str(self.current_save.with_suffix(".inventory-storage.csv"))
        target, _ = QFileDialog.getSaveFileName(self, "Export Inventory Storage CSV", default, "CSV Files (*.csv)")
        if not target:
            return
        try:
            with Path(target).open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Item", "FormID", "EncodedRefID", "RefType", "RefValueHex",
                    "PlayerDataOffsetHex", "PayloadOffsetHex", "VirtualOffsetHex",
                    "RawSignedCount", "DisplayedCount", "PendingNewCount", "ExtraFlagHex",
                    "Confidence", "Editable", "Compression", "Note"
                ])
                for row in range(self.inventory_table.rowCount()):
                    entry = self.inventory_row_entries.get(row)
                    if not entry:
                        continue
                    item = self.inventory_table.item(row, self.INV_COL_ITEM)
                    effective = self.inventory_dirty_counts.get(int(entry.payload_offset), int(entry.displayed_count))
                    writer.writerow([
                        item.text() if item else entry.name or entry.form_id,
                        entry.form_id,
                        entry.refid_hex,
                        entry.ref_type,
                        f"0x{entry.ref_value:X}",
                        f"0x{entry.player_data_offset:X}",
                        f"0x{entry.payload_offset:X}",
                        f"0x{entry.virtual_offset:X}",
                        entry.raw_count,
                        entry.displayed_count,
                        int(effective),
                        f"0x{entry.extra:02X}",
                        entry.confidence,
                        "yes" if entry.editable else "no",
                        getattr(self.current_inventory, "player_data_compression", "none"),
                        entry.note,
                    ])
        except Exception as exc:
            QMessageBox.critical(self, "Storage export failed", str(exc))
            return
        QMessageBox.information(self, "Storage exported", f"Inventory storage CSV written:\n{target}")

    def _build_inventory_research_report(self) -> str:
        lines: list[str] = []
        lines.append("Inventory research / direct-add preflight")
        lines.append("=" * 44)
        if not self.current_save:
            lines.append("No save loaded.")
            lines.append("Open a save first, then refresh this report.")
            return "\n".join(lines)
        lines.append(f"Save: {self.current_save}")
        if not self.current_inventory:
            lines.append("Inventory parser has not loaded a Player Inventory block yet.")
            return "\n".join(lines)
        block = self.current_inventory
        lines.append(f"Player ChangeForm: {block.player_change_form.refid_hex}")
        lines.append(f"Player ChangeForm storage: {block.player_data_compression} ({'compressed' if block.player_data_compressed else 'uncompressed'})")
        lines.append(f"Detected inventory rows: {len(block.entries):,}")
        editable_count = sum(1 for entry in block.entries if entry.editable)
        lines.append(f"Editable existing rows: {editable_count:,}")
        lines.append(f"Read-only/research rows: {len(block.entries) - editable_count:,}")
        if block.entries:
            first = min(block.entries, key=lambda e: e.player_data_offset)
            last = max(block.entries, key=lambda e: e.player_data_offset)
            lines.append(f"First detected row: {first.form_id} at player-data 0x{first.player_data_offset:X}")
            lines.append(f"Last detected row:  {last.form_id} at player-data 0x{last.player_data_offset:X}")
        if block.warning:
            lines.append(f"Parser note: {block.warning}")

        lines.append("")
        lines.append("Common row checks")
        lines.append("-" * 17)
        for target, label in (("0000000F", "Gold"), ("0000000A", "Lockpicks")):
            matches = [entry for entry in block.entries if entry.form_id.upper() == target]
            if not matches:
                lines.append(f"{label}: not detected")
                continue
            for entry in matches:
                lines.append(
                    f"{label}: {entry.displayed_count:,} "
                    f"(raw {entry.raw_count:,}, player-data 0x{entry.player_data_offset:X}, "
                    f"payload 0x{entry.payload_offset:X}, extra 0x{entry.extra:02X}, {entry.confidence})"
                )

        lines.append("")
        lines.append("Direct missing-item insertion preflight")
        lines.append("-" * 40)
        try:
            if self.inventory_insert_layout_preflight is None:
                self.inventory_insert_layout_preflight = preflight_player_inventory_insert_layout(self.current_save)
            ok, reason = self.inventory_insert_layout_preflight
        except Exception as exc:
            ok, reason = False, str(exc)
        lines.append(f"Status: {'ENABLED for narrow simple base-game stacks' if ok else 'DISABLED'}")
        lines.append(f"Reason: {reason}")
        lines.append("Policy: existing rows are direct-editable; dormant zero-count rows can be re-added by editing New Count; truly missing base-game rows can be inserted only when direct-insert preflight passes.")
        lines.append("Controlled add/remove finding: the uploaded saves showed Iron War Axe stayed at the same row offset and changed raw count 0 -> -1 when re-added. The editor now treats zero-count rows as safe reactivation targets instead of trying to insert new bytes.")
        lines.append("Direct insertion remains fail-closed for unmapped layouts because Skyrim inventory rows can include extra data, ownership, enchantment, tempering, poison, equipped state, and list/count fields.")

        form_id, name, status = self._selected_inventory_database_item() if hasattr(self, "inv_db_table") else ("", "", "")
        if form_id:
            amount = self.inv_db_amount_spin.value() if hasattr(self, "inv_db_amount_spin") else 1
            can_direct, direct_reason = self._direct_insert_support(form_id)
            lines.append("")
            lines.append("Selected Item Database row")
            lines.append("-" * 26)
            lines.append(f"Item: {name}")
            lines.append(f"FormID: {form_id}")
            lines.append(f"Inventory status: {status or self._inventory_database_status_for_id(form_id)}")
            lines.append(f"Requested amount: {amount:,}")
            lines.append(f"Direct add support: {'yes' if can_direct else 'no'}")
            lines.append(f"Reason: {direct_reason}")
            lines.append(f"PC fallback command: player.additem {form_id} {amount}")

        queued = self._queued_inventory_rows() if hasattr(self, "inventory_table") else []
        pending = self._pending_add_rows()
        lines.append("")
        lines.append("Unsaved inventory queue")
        lines.append("-" * 24)
        if not queued and not pending:
            lines.append("No unsaved inventory edits staged.")
        for _table_row, offset, form_id, name, old, new in queued[:25]:
            lines.append(f"Count edit: {name} ({form_id}) payload 0x{offset:X}: {old:,} -> {new:,} ({new - old:+,})")
        if len(queued) > 25:
            lines.append(f"... {len(queued) - 25:,} more count edits")
        for form_id, name, amount in pending:
            lines.append(f"Pending experimental missing-row add: {name} ({form_id}) x{amount:,}")

        lines.append("")
        lines.append("Confirmed existing-row shape")
        lines.append("-" * 28)
        lines.append("3 bytes encoded RefID + 4 bytes signed little-endian count + 1 byte extra/flag")
        lines.append("Existing-row edits patch only the count field at player-data offset + 3 and preserve negative-count sign style.")
        return "\n".join(lines)

    def refresh_inventory_research_report(self) -> None:
        if not hasattr(self, "inv_research_output"):
            return
        try:
            self.inv_research_output.setPlainText(self._build_inventory_research_report())
        except Exception as exc:
            self.inv_research_output.setPlainText(f"Inventory research report failed: {exc}")

    def copy_inventory_research_report(self) -> None:
        text = self.inv_research_output.toPlainText().strip() if hasattr(self, "inv_research_output") else ""
        if not text:
            text = self._build_inventory_research_report()
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("Copied inventory research report.", 2500)

    def export_inventory_research_report_dialog(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        default = str(self.current_save.with_suffix(".inventory-preflight.txt"))
        target, _ = QFileDialog.getSaveFileName(self, "Export Inventory Research Report", default, "Text Files (*.txt);;All Files (*)")
        if not target:
            return
        try:
            text = self._build_inventory_research_report()
            Path(target).write_text(text, encoding="utf-8")
            if hasattr(self, "inv_research_output"):
                self.inv_research_output.setPlainText(text)
        except Exception as exc:
            QMessageBox.critical(self, "Report export failed", str(exc))
            return
        QMessageBox.information(self, "Report exported", f"Inventory research report written:\n{target}")

    def _inventory_count_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading_inventory_table or item.column() != self.INV_COL_COUNT:
            return
        row = item.row()
        name_item = self.inventory_table.item(row, self.INV_COL_ITEM)
        if not name_item:
            return
        offset = self.inventory_row_offsets.get(row)
        editable = self.inventory_row_editable.get(row, False)
        original = self.inventory_row_original_counts.get(row, 0)
        if offset is None or not editable:
            return
        text = item.text().strip().replace(",", "")
        try:
            value = validate_inventory_amount(int(text))
        except Exception:
            self._loading_inventory_table = True
            item.setText(str(original))
            self._loading_inventory_table = False
            QMessageBox.warning(self, "Invalid count", f"Inventory counts must be whole numbers from 0 to {MAX_SAFE_INVENTORY_COUNT:,}.")
            return
        payload_offset = int(offset)
        original_value = int(original)
        if value == original_value:
            self.inventory_dirty_counts.pop(payload_offset, None)
        else:
            self.inventory_dirty_counts[payload_offset] = value
        if self.inventory_table.currentRow() == row:
            self._updating_inventory_editor = True
            self.inv_amount_spin.setValue(value)
            self._updating_inventory_editor = False
        self.inventory_selected_offset = payload_offset
        self._refresh_inventory_queue_label()
        self._refresh_general_inventory_values()
        self._update_inventory_storage_info()
        self.refresh_coverage()
        self.statusBar().showMessage(f"Unsaved inventory count edits: {len(self.inventory_dirty_counts)}", 3000)

    def set_selected_inventory_count(self, *_args) -> None:
        if getattr(self, "_updating_inventory_editor", False):
            return
        row = self.inventory_table.currentRow() if hasattr(self, "inventory_table") else -1
        if row < 0:
            return
        count_item = self.inventory_table.item(row, self.INV_COL_COUNT)
        if not count_item:
            return
        editable = self.inventory_row_editable.get(row, False)
        if not editable:
            self.statusBar().showMessage("That detected row is not editable yet.", 2500)
            return
        try:
            value = validate_inventory_amount(self.inv_amount_spin.value())
        except Exception as exc:
            QMessageBox.warning(self, "Invalid count", str(exc))
            return
        if count_item.text().replace(",", "").strip() != str(value):
            count_item.setText(str(value))


    def revert_inventory_count_edits(self) -> None:
        if not hasattr(self, "inventory_table"):
            return
        self._loading_inventory_table = True
        self.inventory_table.blockSignals(True)
        for row in range(self.inventory_table.rowCount()):
            item = self.inventory_table.item(row, self.INV_COL_COUNT)
            if not item:
                continue
            original = self.inventory_row_original_counts.get(row, 0)
            item.setText(str(original))
        self.inventory_table.blockSignals(False)
        self._loading_inventory_table = False
        self.inventory_dirty_counts.clear()
        self._refresh_inventory_queue_label()
        self.refresh_coverage()
        self.statusBar().showMessage("Inventory count edits reverted.", 3000)

    def _set_inventory_target(self, form_id: str, amount: int) -> None:
        if not hasattr(self, "inventory_table"):
            return
        try:
            amount = validate_inventory_amount(amount)
        except Exception as exc:
            QMessageBox.warning(self, "Invalid count", str(exc))
            return
        target = form_id.strip().replace("0x", "").replace("0X", "").upper().zfill(8)[-8:]
        for row in range(self.inventory_table.rowCount()):
            name_item = self.inventory_table.item(row, self.INV_COL_ITEM)
            count_item = self.inventory_table.item(row, self.INV_COL_COUNT)
            if not name_item or not count_item:
                continue
            if str(name_item.data(Qt.ItemDataRole.UserRole)).upper() != target:
                continue
            self.inventory_table.selectRow(row)
            self.inv_form_edit.setText(target)
            self.inv_name_edit.setText(name_item.text())
            self.inv_amount_spin.setValue(amount)
            editable = self.inventory_row_editable.get(row, False)
            if editable:
                count_item.setText(str(amount))
                self.statusBar().showMessage(f"Changed: {name_item.text()} → {amount}", 3000)
            else:
                self.statusBar().showMessage(f"{name_item.text()} exists but this row is not editable yet.", 5000)
            return
        display_name, _ = self._inventory_display_name(target, "")
        self.inv_form_edit.setText(target)
        self.inv_selected_formid.setText(target)
        self.inv_name_edit.setText(display_name)
        self.inv_amount_spin.setValue(amount)
        QMessageBox.information(self, "Item not found", f"{display_name} is not an existing inventory row in this save yet, so this build cannot add it from zero.")


    def set_selected_inventory_amount(self, amount: int) -> None:
        if not hasattr(self, "inv_amount_spin"):
            return
        try:
            value = validate_inventory_amount(amount)
        except Exception as exc:
            QMessageBox.warning(self, "Invalid count", str(exc))
            return
        self.inv_amount_spin.setValue(value)


    def restore_selected_inventory_count(self) -> None:
        row = self.inventory_table.currentRow() if hasattr(self, "inventory_table") else -1
        if row < 0:
            QMessageBox.information(self, "No item selected", "Select an inventory row first.")
            return
        item = self.inventory_table.item(row, self.INV_COL_COUNT)
        if not item:
            return
        original = self.inventory_row_original_counts.get(row, 0)
        item.setText(str(original))
        self.statusBar().showMessage("Selected item restored to its original loaded count.", 2500)

    def remove_selected_queued_inventory_edit(self) -> None:
        if not hasattr(self, "inv_preview_table"):
            return
        row = self.inv_preview_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "No queued edit selected", "Select a row in the queued edits preview first.")
            return
        item = self.inv_preview_table.item(row, 0)
        if not item:
            return
        offset = item.data(Qt.ItemDataRole.UserRole)
        if offset is None:
            return
        self.inventory_dirty_counts.pop(int(offset), None)
        for inv_row, inv_offset in self.inventory_row_offsets.items():
            if int(inv_offset) == int(offset):
                count_item = self.inventory_table.item(inv_row, self.INV_COL_COUNT)
                if count_item:
                    self._loading_inventory_table = True
                    count_item.setText(str(self.inventory_row_original_counts.get(inv_row, 0)))
                    self._loading_inventory_table = False
                break
        self._refresh_inventory_queue_label()
        self.refresh_coverage()

    def _queued_inventory_rows(self) -> list[tuple[int, int, str, str, int, int]]:
        """Return queued rows as (table_row, offset, formid, name, old, new)."""
        rows: list[tuple[int, int, str, str, int, int]] = []
        for table_row, offset in self.inventory_row_offsets.items():
            if offset not in self.inventory_dirty_counts:
                continue
            name_item = self.inventory_table.item(table_row, self.INV_COL_ITEM)
            form_id = str(name_item.data(Qt.ItemDataRole.UserRole) or "") if name_item else ""
            name = name_item.text() if name_item else "Unknown item"
            old = int(self.inventory_row_original_counts.get(table_row, 0))
            new = int(self.inventory_dirty_counts[offset])
            rows.append((table_row, int(offset), form_id, name, old, new))
        return rows

    def _refresh_inventory_preview_table(self) -> None:
        if not hasattr(self, "inv_preview_table"):
            return
        rows = self._queued_inventory_rows()
        self.inv_preview_table.setRowCount(len(rows))
        for out_row, (_table_row, offset, form_id, name, old, new) in enumerate(rows):
            values = [name, form_id, f"{new:,}", f"{new - old:+,}"]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, offset)
                if col in {2, 3}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.inv_preview_table.setItem(out_row, col, item)
        self.inv_preview_table.resizeColumnsToContents()

    def _pending_add_rows(self) -> list[tuple[str, str, int]]:
        rows: list[tuple[str, str, int]] = []
        for form_id, data in sorted(getattr(self, "inventory_pending_adds", {}).items(), key=lambda kv: str(kv[1].get("name", kv[0])).casefold()):
            rows.append((form_id, str(data.get("name") or form_id), int(data.get("amount") or 0)))
        return rows

    def _has_inventory_edits(self) -> bool:
        return bool(self.inventory_dirty_counts or getattr(self, "inventory_pending_adds", {}))

    def _write_inventory_edits_to_target(self, target: Path, updates: dict[int, int], adds: dict[str, dict[str, object]]) -> None:
        if not self.current_save:
            raise ValueError("No save is loaded.")
        working_source = self.current_save
        temp_paths: list[Path] = []
        final_tmp: Path | None = None
        step = 0
        try:
            if updates:
                step += 1
                temp_counts = self.current_save.with_suffix(self.current_save.suffix + f".tmp-{step}-counts-save-lab")
                if temp_counts.exists():
                    temp_counts.unlink()
                patch_player_inventory_entry_counts(working_source, temp_counts, updates)
                if working_source != self.current_save and working_source.exists():
                    temp_paths.append(working_source)
                working_source = temp_counts
            for form_id, data in adds.items():
                step += 1
                temp_add = self.current_save.with_suffix(self.current_save.suffix + f".tmp-{step}-add-save-lab")
                if temp_add.exists():
                    temp_add.unlink()
                amount = validate_inventory_amount(int(data.get("amount") or 0))
                insert_simple_player_inventory_item(working_source, temp_add, form_id, amount)
                if working_source != self.current_save and working_source.exists():
                    temp_paths.append(working_source)
                working_source = temp_add
            if working_source == self.current_save:
                raise ValueError("No inventory edits were supplied.")
            final_tmp = working_source
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(final_tmp), str(target))
            final_tmp = None
        finally:
            for temp in temp_paths:
                try:
                    if temp.exists():
                        temp.unlink()
                except Exception:
                    pass
            if final_tmp is not None:
                try:
                    if final_tmp.exists():
                        final_tmp.unlink()
                except Exception:
                    pass


    def _verify_inventory_adds_written(self, target: Path, adds: dict[str, dict[str, object]]) -> None:
        if not adds:
            return
        block = read_player_inventory(target)
        by_form: dict[str, list[object]] = {}
        for entry in block.entries:
            by_form.setdefault(entry.form_id.upper(), []).append(entry)
        missing: list[str] = []
        for form_id, data in adds.items():
            clean = form_id.strip().upper().zfill(8)[-8:]
            amount = int(data.get("amount") or 0)
            hits = [e for e in by_form.get(clean, []) if int(getattr(e, "displayed_count", 0)) >= amount]
            if not hits:
                missing.append(f"{data.get('name') or clean} ({clean})")
        if missing:
            raise ValueError("The save was written, but these added rows were not found on reload: " + "; ".join(missing))

    def _format_inventory_update_preview(self, updates: dict[int, int], common_global_lines: list[str] | None = None) -> str:
        lines = ["Unsaved save edits preview:"]
        queued = self._queued_inventory_rows()
        shown = 0
        for _table_row, offset, form_id, name, old, new in queued:
            if offset in updates:
                lines.append(f"- Set {name} ({form_id}): New Count {int(updates[offset]):,} ({int(updates[offset]) - old:+,})")
                shown += 1
                if shown >= 12:
                    break
        add_rows = self._pending_add_rows()
        for form_id, name, amount in add_rows[: max(0, 12 - shown)]:
            lines.append(f"- Add {name} ({form_id}): +{amount:,} new stack")
        for line in common_global_lines or []:
            lines.append(line)
        total = len(queued) + len(add_rows) + len(common_global_lines or [])
        if total > 12:
            lines.append(f"- …plus {total - 12} more")
        if len(lines) == 1:
            return "No unsaved inventory or common global edits."
        return "\n".join(lines)

    def _pending_common_global_update_lines(self) -> tuple[dict[str, int], list[str]]:
        try:
            return self._collect_common_global_updates()
        except Exception:
            return {}, []

    def _patch_common_global_updates(self, path: Path, updates: dict[str, int]) -> None:
        if not updates:
            return
        other_globals: dict[str, int] = {}
        for form_id, value in updates.items():
            if str(form_id).upper() == DRAGONS_ABSORBED_FORM_ID:
                patch_skyrim_dragon_souls(path, path, value)
            else:
                other_globals[form_id] = value
        if other_globals:
            patch_skyrim_global_variables(path, path, other_globals)

    def _verify_common_global_updates_written(self, path: Path, expected_updates: dict[str, int]) -> None:
        problems: list[str] = []
        for form_id, expected_value in expected_updates.items():
            if str(form_id).upper() == DRAGONS_ABSORBED_FORM_ID:
                try:
                    hit = read_skyrim_dragon_souls(path)
                except Exception as exc:
                    problems.append(f"Dragon Souls could not be read back: {exc}")
                    continue
                if not hit:
                    problems.append("Dragon Souls actor-value field was not found after saving")
                    continue
                if int(round(float(hit.value))) != int(expected_value):
                    problems.append(f"Dragon Souls read back as {float(hit.value):g}, expected {int(expected_value):,}")
                continue
            try:
                hit = read_skyrim_global_variable(path, form_id, name=DRAGONS_ABSORBED_NAME)
            except Exception as exc:
                problems.append(f"{form_id} could not be read back: {exc}")
                continue
            if not hit:
                problems.append(f"{form_id} was not found after saving")
                continue
            if int(round(float(hit.value))) != int(expected_value):
                problems.append(f"{form_id} read back as {float(hit.value):g}, expected {int(expected_value):,}")
        if problems:
            raise ValueError("Common values were written, but verification failed:\n" + "\n".join(f"- {item}" for item in problems))

    def copy_selected_inventory_additem_command(self) -> None:
        form_id = self.inv_selected_formid.text().strip() if hasattr(self, "inv_selected_formid") else ""
        if not form_id:
            QMessageBox.information(self, "No item selected", "Select an inventory row first.")
            return
        count = self.inv_amount_spin.value() if hasattr(self, "inv_amount_spin") else 1
        command = f"player.additem {form_id} {count}"
        QApplication.clipboard().setText(command)
        self.statusBar().showMessage(f"Copied: {command}", 3000)

    def save_inventory_count_changes(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        updates = dict(self.inventory_dirty_counts)
        adds = dict(getattr(self, "inventory_pending_adds", {}))
        common_globals, common_global_lines = self._pending_common_global_update_lines()
        if not updates and not adds and not common_globals:
            QMessageBox.information(self, "No save edits", "Change an inventory New Count, stage a direct-addable item, or change a Common value like Dragon Souls first.")
            return
        try:
            updates = {int(k): validate_inventory_amount(v) for k, v in updates.items()}
            for form_id, data in adds.items():
                data["amount"] = validate_inventory_amount(int(data.get("amount") or 0))
        except Exception as exc:
            QMessageBox.warning(self, "Invalid inventory edit", str(exc))
            return
        preview = self._format_inventory_update_preview(updates, common_global_lines)
        result = QMessageBox.question(
            self,
            "Save inventory/common edits",
            f"This will create a backup, then write {len(updates)} existing-row count change(s), {len(adds)} missing-item add(s), and {len(common_globals)} common global change(s) into the currently loaded save:\n\n{self.current_save}\n\n{preview}\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            make_backup(self.current_save)
            if updates or adds:
                self._write_inventory_edits_to_target(self.current_save, updates, adds)
                if updates:
                    self._verify_inventory_updates_written(self.current_save, updates)
                if adds:
                    self._verify_inventory_adds_written(self.current_save, adds)
            if common_globals:
                self._patch_common_global_updates(self.current_save, common_globals)
                self._verify_common_global_updates_written(self.current_save, common_globals)
            new_doc = read_ess(self.current_save)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self.current_doc = new_doc
        self.inventory_dirty_counts.clear()
        self.inventory_pending_adds.clear()
        self._refresh_inventory_queue_label()
        self._refresh_all_from_doc()
        QMessageBox.information(self, "Saved", f"Inventory/common edits saved with a backup:\n{self.current_save}")

    def save_inventory_count_as(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        updates = dict(self.inventory_dirty_counts)
        adds = dict(getattr(self, "inventory_pending_adds", {}))
        common_globals, common_global_lines = self._pending_common_global_update_lines()
        if not updates and self.inventory_selected_offset is not None:
            updates[self.inventory_selected_offset] = validate_inventory_amount(self.inv_amount_spin.value())
        if not updates and not adds and not common_globals:
            QMessageBox.information(self, "No save edits", "Change an inventory New Count, stage a direct-addable item, or change a Common value like Dragon Souls first.")
            return
        try:
            updates = {int(k): validate_inventory_amount(v) for k, v in updates.items()}
            for form_id, data in adds.items():
                data["amount"] = validate_inventory_amount(int(data.get("amount") or 0))
        except Exception as exc:
            QMessageBox.warning(self, "Invalid inventory edit", str(exc))
            return
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save Inventory/Common Edited Copy",
            str(self.current_save.with_suffix(".inventory-common-edited" + self.current_save.suffix)),
            "Skyrim Saves (*.ess *.ESS *.dat *.DAT);;All Files (*)",
        )
        if not target:
            return
        target_path = Path(target)
        preview = self._format_inventory_update_preview(updates, common_global_lines)
        result = QMessageBox.question(
            self,
            "Save inventory/common edited copy",
            f"This will write {len(updates)} existing-row count change(s), {len(adds)} missing-item add(s), and {len(common_globals)} common global change(s) to a new save copy:\n\n{target_path}\n\n{preview}\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            make_backup(self.current_save)
            if updates or adds:
                self._write_inventory_edits_to_target(target_path, updates, adds)
                if updates:
                    self._verify_inventory_updates_written(target_path, updates)
                if adds:
                    self._verify_inventory_adds_written(target_path, adds)
            else:
                shutil.copy2(self.current_save, target_path)
            if common_globals:
                self._patch_common_global_updates(target_path, common_globals)
                self._verify_common_global_updates_written(target_path, common_globals)
            new_doc = read_ess(target_path)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self.current_save = target_path
        self.current_doc = new_doc
        self.path_edit.setText(str(target_path))
        self.inventory_dirty_counts.clear()
        self.inventory_pending_adds.clear()
        self._refresh_inventory_queue_label()
        self._refresh_all_from_doc()
        QMessageBox.information(self, "Saved", f"Inventory/common edited copy written:\n{target_path}")

    def _refresh_inventory_queue_label(self) -> None:
        if not hasattr(self, "inv_queued_label"):
            return
        count_changes = len(self.inventory_dirty_counts)
        add_changes = len(getattr(self, "inventory_pending_adds", {}))
        common_globals, _lines = self._pending_common_global_update_lines()
        global_changes = len(common_globals)
        parts = []
        if count_changes:
            parts.append(f"{count_changes} count change{'s' if count_changes != 1 else ''}")
        if add_changes:
            parts.append(f"{add_changes} staged add{'s' if add_changes != 1 else ''}")
        if global_changes:
            parts.append(f"{global_changes} common/global change{'s' if global_changes != 1 else ''}")
        if parts:
            self.inv_queued_label.setText("Unsaved: " + ", ".join(parts))
        else:
            self.inv_queued_label.setText("No unsaved inventory/common edits")
        self._refresh_inventory_preview_table()

    def copy_selected_inventory_id(self) -> None:
        form_id = self.inv_selected_formid.text().strip() if hasattr(self, "inv_selected_formid") else ""
        if not form_id:
            QMessageBox.information(self, "No item selected", "Select an inventory row first.")
            return
        QApplication.clipboard().setText(form_id)
        self.statusBar().showMessage(f"Copied {form_id}", 2500)

    def import_inventory_csv_dialog(self) -> None:
        if not self.current_inventory or not hasattr(self, "inventory_table"):
            QMessageBox.information(self, "No inventory loaded", "Open a save first.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import Inventory CSV", "", "CSV Files (*.csv);;All Files (*)")
        if not path:
            return
        try:
            imported = self._read_inventory_import_csv(path)
        except Exception as exc:
            QMessageBox.critical(self, "Inventory CSV import failed", str(exc))
            return
        if not imported:
            QMessageBox.information(self, "No importable rows", "No rows with FormID/PayloadOffset and Count/New Count were found.")
            return

        mode = self._choose_inventory_import_mode()
        if not mode:
            return

        offset_to_row = {int(offset): row for row, offset in self.inventory_row_offsets.items()}
        formid_to_rows: dict[str, list[int]] = {}
        for row in range(self.inventory_table.rowCount()):
            item = self.inventory_table.item(row, self.INV_COL_ITEM)
            if not item:
                continue
            form_id = str(item.data(Qt.ItemDataRole.UserRole) or "").upper()
            formid_to_rows.setdefault(form_id, []).append(row)

        matched_rows: set[int] = set()
        applied_rows: set[int] = set()
        applied = unchanged = missing = readonly = invalid = zeroed = 0

        for rowdata in imported:
            try:
                import_value = validate_inventory_amount(rowdata["count"])
            except Exception:
                invalid += 1
                continue

            rows: list[int] = []
            payload_offset = rowdata.get("payload_offset")
            form_id = str(rowdata.get("form_id") or "").upper()
            if payload_offset is not None and int(payload_offset) in offset_to_row:
                rows = [offset_to_row[int(payload_offset)]]
            elif form_id:
                rows = formid_to_rows.get(form_id, [])

            if not rows:
                missing += 1
                continue

            for table_row in rows:
                if table_row in applied_rows:
                    continue
                matched_rows.add(table_row)
                if not self.inventory_row_editable.get(table_row, False):
                    readonly += 1
                    continue
                count_item = self.inventory_table.item(table_row, self.INV_COL_COUNT)
                if not count_item:
                    missing += 1
                    continue

                current_value = self._inventory_table_count(table_row)
                if mode == "add":
                    try:
                        target_value = validate_inventory_amount(current_value + import_value)
                    except Exception:
                        invalid += 1
                        continue
                else:
                    target_value = import_value

                if current_value == target_value:
                    unchanged += 1
                else:
                    count_item.setText(str(target_value))
                    applied += 1
                applied_rows.add(table_row)

        if mode == "replace":
            for table_row in range(self.inventory_table.rowCount()):
                if table_row in matched_rows:
                    continue
                if not self.inventory_row_editable.get(table_row, False):
                    continue
                count_item = self.inventory_table.item(table_row, self.INV_COL_COUNT)
                if not count_item:
                    continue
                current_value = self._inventory_table_count(table_row)
                if current_value != 0:
                    count_item.setText("0")
                    zeroed += 1

        self._refresh_inventory_queue_label()
        self.refresh_coverage()
        mode_label = "Replace inventory" if mode == "replace" else "Add to current"
        extra = f"\nRows set to 0 because they were not in the CSV: {zeroed}" if mode == "replace" else ""
        QMessageBox.information(
            self,
            "Inventory CSV imported",
            f"{mode_label} import complete.\n\n"
            f"Applied changes: {applied}\n"
            f"Unchanged rows: {unchanged}\n"
            f"Missing rows: {missing}\n"
            f"Read-only rows skipped: {readonly}\n"
            f"Invalid count rows: {invalid}"
            f"{extra}\n\n"
            "Review the unsaved changes preview, then use Save Changes or Save Changes As…"
        )

    def _choose_inventory_import_mode(self) -> str | None:
        box = QMessageBox(self)
        box.setWindowTitle("Inventory CSV import mode")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("How should the CSV be applied?")
        box.setInformativeText(
            "Replace Inventory sets matching rows to the CSV counts and sets editable rows not found in the CSV to 0.\n\n"
            "Add To Current adds each CSV count onto the currently shown New Count for matching existing rows.\n\n"
            "This still only changes items already present in the save; brand-new row insertion is not enabled yet."
        )
        replace_btn = box.addButton("Replace Inventory", QMessageBox.ButtonRole.AcceptRole)
        add_btn = box.addButton("Add To Current", QMessageBox.ButtonRole.ActionRole)
        cancel_btn = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(add_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked == replace_btn:
            return "replace"
        if clicked == add_btn:
            return "add"
        if clicked == cancel_btn:
            return None
        return None

    def _inventory_table_count(self, table_row: int) -> int:
        item = self.inventory_table.item(table_row, self.INV_COL_COUNT) if hasattr(self, "inventory_table") else None
        if item:
            try:
                return validate_inventory_amount(int(item.text().replace(",", "").strip() or "0"))
            except Exception:
                pass
        return int(self.inventory_row_original_counts.get(table_row, 0))

    def _read_inventory_import_csv(self, path: str | Path) -> list[dict[str, object]]:
        def norm(value: str) -> str:
            return "".join(ch for ch in value.casefold() if ch.isalnum())

        def parse_offset(value: str) -> int | None:
            value = (value or "").strip()
            if not value:
                return None
            try:
                if value.lower().startswith("0x"):
                    return int(value, 16)
                return int(value)
            except Exception:
                return None

        def parse_formid(value: str) -> str:
            raw = (value or "").strip().replace("0x", "").replace("0X", "").upper()
            raw = "".join(ch for ch in raw if ch in "0123456789ABCDEF")
            if not raw:
                return ""
            return raw.zfill(8)[-8:]

        rows: list[dict[str, object]] = []
        with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return rows
            fields = {norm(name): name for name in reader.fieldnames}

            form_key = next((fields[k] for k in ("formid", "id", "itemid") if k in fields), None)
            offset_key = next((fields[k] for k in ("payloadoffset", "offset", "inventoryoffset") if k in fields), None)
            count_key = next((fields[k] for k in ("newcount", "count", "queued", "amount", "quantity", "qty") if k in fields), None)
            if not count_key:
                return rows

            for source_row in reader:
                form_id = parse_formid(source_row.get(form_key, "") if form_key else "")
                payload_offset = parse_offset(source_row.get(offset_key, "") if offset_key else "")
                raw_count = (source_row.get(count_key, "") or "").strip().replace(",", "")
                if not raw_count:
                    continue
                try:
                    count = int(raw_count)
                except Exception:
                    rows.append({"form_id": form_id, "payload_offset": payload_offset, "count": raw_count})
                    continue
                if not form_id and payload_offset is None:
                    continue
                rows.append({"form_id": form_id, "payload_offset": payload_offset, "count": count})
        return rows

    def export_inventory_csv_dialog(self) -> None:
        if not self.current_inventory:
            QMessageBox.information(self, "No inventory loaded", "Open a save first.")
            return
        default = "skyrim_inventory_export.csv"
        if self.current_save:
            default = str(self.current_save.with_suffix(".inventory.csv"))
        target, _ = QFileDialog.getSaveFileName(self, "Export Inventory CSV", default, "CSV Files (*.csv)")
        if not target:
            return
        try:
            export_inventory_csv(target, self.current_inventory, self.db, only_unknown=False)
        except Exception as exc:
            QMessageBox.critical(self, "Inventory export failed", str(exc))
            return
        QMessageBox.information(self, "Inventory exported", f"Inventory CSV written:\n{target}")

    def export_unknown_inventory_ids_dialog(self) -> None:
        if not self.current_inventory:
            QMessageBox.information(self, "No inventory loaded", "Open a save first.")
            return
        default = "skyrim_unknown_inventory_ids.csv"
        if self.current_save:
            default = str(self.current_save.with_suffix(".unknown-ids.csv"))
        target, _ = QFileDialog.getSaveFileName(self, "Export Unknown Inventory IDs", default, "CSV Files (*.csv)")
        if not target:
            return
        try:
            export_inventory_csv(target, self.current_inventory, self.db, only_unknown=True)
        except Exception as exc:
            QMessageBox.critical(self, "Unknown ID export failed", str(exc))
            return
        QMessageBox.information(self, "Unknown IDs exported", f"Unknown inventory ID CSV written:\n{target}")

    def export_current_reference_database(self) -> None:
        if not self.db.records:
            QMessageBox.information(self, "No reference database", "Load or open the built-in reference database first.")
            return
        target, _ = QFileDialog.getSaveFileName(self, "Export Current Reference CSV", "skyrim_reference_ids_export.csv", "CSV Files (*.csv)")
        if not target:
            return
        try:
            export_reference_csv(target, self.db.records)
        except Exception as exc:
            QMessageBox.critical(self, "Reference export failed", str(exc))
            return
        QMessageBox.information(self, "Reference IDs exported", f"Reference CSV written:\n{target}")

    def refresh_coverage(self) -> None:
        if not hasattr(self, "coverage_table"):
            return
        summary = build_coverage_summary(self.db, self.current_inventory, len(self.inventory_dirty_counts))
        rows = summary.to_rows()
        self.coverage_table.setRowCount(len(rows))
        for row, (field, value) in enumerate(rows):
            self.coverage_table.setItem(row, 0, QTableWidgetItem(field))
            self.coverage_table.setItem(row, 1, QTableWidgetItem(value))
        self.coverage_table.resizeColumnsToContents()
        self._refresh_inventory_queue_label()

    def refresh_magic_page(self, silent: bool = False) -> None:
        if not hasattr(self, "magic_table"):
            return
        if not self.current_save:
            self.current_magic_scan = None
            self.magic_status_label.setText("Open a save to scan magic data.")
            self._populate_magic_table()
            self._populate_magic_split_tables()
            self._populate_magic_favorites_table()
            self._populate_magic_database_table()
            return
        try:
            self.current_magic_scan = scan_magic(self.current_save, self.db.records)
        except Exception as exc:
            self.current_magic_scan = None
            self.magic_status_label.setText(f"Magic scan failed: {exc}")
            if not silent:
                QMessageBox.warning(self, "Magic scan failed", str(exc))
            self._populate_magic_table()
            self._populate_magic_split_tables()
            self._populate_magic_favorites_table()
            return
        scan = self.current_magic_scan
        note = " ".join(scan.notes[:2]) if scan.notes else "Read-only magic scan complete."
        learned_text = ""
        if getattr(scan, "learned_magic", None):
            lm = scan.learned_magic
            learned_text = f" Learned list: {lm.count:,} entries at 0x{lm.start_offset:X} ({lm.confidence})."
        self.magic_status_label.setText(
            f"Known magic hits: {len(scan.hits):,}. Magic Favorites block(s): {len(scan.favorite_blocks):,}.{learned_text} {note}"
        )
        self._populate_magic_table()
        self._populate_magic_split_tables()
        self._populate_magic_favorites_table()
        self._populate_magic_database_table()

    def _populate_magic_table(self) -> None:
        if not hasattr(self, "magic_table"):
            return
        scan = self.current_magic_scan
        query = self.magic_filter_edit.text().casefold().strip() if hasattr(self, "magic_filter_edit") else ""
        hits = list(scan.hits if scan else [])
        if query:
            hits = [h for h in hits if query in " ".join([
                h.name, h.category, h.form_id, h.resolved_form_id, h.encoded_refid_hex, h.area, h.confidence, h.source, h.notes
            ]).casefold()]
        self.magic_table.setRowCount(len(hits))
        for row, h in enumerate(hits):
            values = [
                h.name,
                h.category,
                h.form_id,
                h.resolved_form_id,
                h.encoded_refid_hex,
                h.area,
                f"0x{h.offset:X}",
                "" if h.local_offset is None else f"0x{h.local_offset:X}",
                h.confidence,
                h.source,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, h)
                self.magic_table.setItem(row, col, item)
        self.magic_table.resizeColumnsToContents()
        self._update_magic_detail()

    def _magic_status_by_resolved_id(self) -> dict[str, dict[str, object]]:
        status: dict[str, dict[str, object]] = {}
        scan = self.current_magic_scan
        if not scan:
            return status
        for hit in scan.hits:
            key = hit.resolved_form_id.upper()
            entry = status.setdefault(key, {"player": False, "favorite": False, "areas": []})
            area = hit.area or ""
            if "Player ChangeForm" in area or "learned magic" in area.casefold():
                entry["player"] = True
            if "Magic Favorites" in area:
                entry["favorite"] = True
            cast_areas = entry["areas"]
            if isinstance(cast_areas, list):
                cast_areas.append(area)
        for state in list(getattr(scan, "shout_words", None) or []):
            key = state.resolved_form_id.upper()
            entry = status.setdefault(key, {"player": False, "favorite": False, "areas": []})
            entry["shout_present"] = bool(state.present)
            entry["shout_unlocked"] = bool(state.unlocked)
            entry["shout_data"] = state.data_hex
            entry["shout_notes"] = state.notes
            cast_areas = entry["areas"]
            if isinstance(cast_areas, list):
                if state.present:
                    cast_areas.append("Word-of-Power ChangeForm unlocked" if state.unlocked else "Word-of-Power ChangeForm known/locked")
                else:
                    cast_areas.append("No Word-of-Power ChangeForm")
        return status

    def _magic_reference_status_text(self, resolved_form_id: str, status_map: dict[str, dict[str, object]]) -> tuple[str, str]:
        if not self.current_save:
            return "No save loaded", ""
        entry = status_map.get(resolved_form_id.upper())
        if not entry:
            return "Not detected", "No"
        favorite = bool(entry.get("favorite"))
        if "shout_unlocked" in entry or "shout_present" in entry:
            if bool(entry.get("shout_unlocked")):
                return "Unlocked word" + (" + favorite" if favorite else ""), "Yes" if favorite else "No"
            if bool(entry.get("shout_present")):
                return "Known/locked word" + (" + favorite" if favorite else ""), "Yes" if favorite else "No"
            if favorite:
                return "Favorite only", "Yes"
            return "Not in save", "No"
        player = bool(entry.get("player"))
        if player and favorite:
            return "Detected + favorite", "Yes"
        if player:
            return "Detected in player", "No"
        if favorite:
            return "Favorite only", "Yes"
        return "Detected", "No"

    def _magic_row_matches_query(self, values: list[str], query: str) -> bool:
        if not query:
            return True
        return query in " ".join(values).casefold()

    def _populate_magic_reference_rows(self, table: QTableWidget, row_specs: list[dict[str, object]]) -> None:
        self._loading_magic_tables = True
        table.blockSignals(True)
        try:
            table.setRowCount(len(row_specs))
            for row_idx, spec in enumerate(row_specs):
                values = list(spec.get("values") or [])
                data = dict(spec.get("data") or {})
                checked = bool(spec.get("checked"))
                command = str(spec.get("copy") or "")
                for col, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    item.setToolTip(str(value))
                    role_data = {**data, "copy": command, "row": values}
                    item.setData(Qt.ItemDataRole.UserRole, role_data)
                    if col == 0:
                        direct_disabled = bool(data.get("direct_disabled"))
                        flags = (
                            item.flags()
                            | Qt.ItemFlag.ItemIsSelectable
                            | Qt.ItemFlag.ItemIsUserCheckable
                            | Qt.ItemFlag.ItemIsEnabled
                        )
                        item.setFlags(flags)
                        if direct_disabled:
                            # Missing shout words are still checkable so Unlock All Shouts
                            # can queue them for the safe console-script route. They are
                            # skipped only by the direct-save writer because inserting
                            # synthetic Word-of-Power records previously corrupted saves.
                            item.setToolTip(str(data.get("direct_disabled_reason") or "Script-only row; direct save will skip it."))
                        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                        item.setText("Unlocked" if checked else "Unlock")
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    table.setItem(row_idx, col, item)
            table.resizeColumnsToContents()
            table.setColumnWidth(0, 86)
        finally:
            table.blockSignals(False)
            self._loading_magic_tables = False

    def _magic_pending_key(self, kind: str, form_id: str, editor_id: str) -> str:
        return f"{kind}|{form_id.upper()}|{editor_id.casefold()}"

    def _magic_reference_current_flags(self, resolved_form_id: str, status_map: dict[str, dict[str, object]]) -> tuple[bool, bool]:
        entry = status_map.get(resolved_form_id.upper())
        if not entry:
            return False, False
        favorite = bool(entry.get("favorite"))
        if "shout_unlocked" in entry or "shout_present" in entry:
            # Shouts are Word-of-Power records.  Presence alone means the word is
            # known/seen; the checkbox represents the unlock flag specifically.
            return bool(entry.get("shout_unlocked")), favorite
        player = bool(entry.get("player"))
        # A favorite entry should only exist for usable magic; treat it as known
        # for checkbox display even when the player ChangeForm byte scan missed it.
        return bool(player or favorite), favorite

    def _populate_magic_split_tables(self) -> None:
        if not hasattr(self, "magic_spell_table"):
            return
        plugins = self.current_doc.plugin_info.plugins if self.current_doc and self.current_doc.plugin_info else []
        records = magic_records_from_database(self.db.records, plugins)
        status_map = self._magic_status_by_resolved_id()
        query = self.magic_filter_edit.text().casefold().strip() if hasattr(self, "magic_filter_edit") else ""
        known_only = bool(getattr(self, "magic_known_only_check", None) and self.magic_known_only_check.isChecked())

        split_rows: dict[str, list[dict[str, object]]] = {"Spells": [], "Shouts": [], "Powers": [], "Abilities": [], "Active Effects": []}

        for rec in records:
            kind = magic_kind(rec.category)
            if kind not in split_rows:
                continue
            status_text, favorite_text = self._magic_reference_status_text(rec.resolved_form_id, status_map)
            current_unlocked, current_favorite = self._magic_reference_current_flags(rec.resolved_form_id, status_map)
            favorite_text = "Yes" if current_favorite else favorite_text
            key = self._magic_pending_key(kind, rec.resolved_form_id, rec.editor_id)
            pending = self.magic_pending_changes.get(key)
            desired_unlocked = pending.desired_unlocked if pending else current_unlocked

            display_status = status_text
            if pending:
                display_status = f"Queued: {pending.action_label}"
                if pending.unsupported_reason(self._magic_script_mode()):
                    display_status += " (script skipped)"

            direct_disabled = False
            direct_disabled_reason = ""
            if kind == "Shouts":
                teach_cmd = build_console_command("player.teachword", rec.resolved_form_id, None)
                unlock_cmd = build_console_command("player.unlockword", rec.resolved_form_id, None)
                shout_name = rec.notes or "Unknown shout"
                shout_entry = status_map.get(rec.resolved_form_id.upper()) or {}
                if not bool(shout_entry.get("shout_present")):
                    direct_disabled = True
                    direct_disabled_reason = (
                        "This shout word is missing from the save, so direct saving cannot add it safely yet. "
                        "Use the console command shown in this row: player.teachword + player.unlockword."
                    )
                    if not pending:
                        display_status = "Script only - missing word record"
                values = [
                    "",
                    display_status,
                    favorite_text,
                    shout_name,
                    rec.name,
                    rec.editor_id,
                    rec.resolved_form_id,
                    teach_cmd,
                    unlock_cmd,
                    rec.source,
                ]
                command = teach_cmd + "\n" + unlock_cmd
                action_name = f"{shout_name} - {rec.name}" if shout_name and shout_name != rec.name else rec.name
            else:
                add_cmd = build_console_command("player.addspell", rec.resolved_form_id, None)
                remove_cmd = build_console_command("player.removespell", rec.resolved_form_id, None)
                values = [
                    "",
                    display_status,
                    favorite_text,
                    rec.name,
                    rec.editor_id,
                    rec.form_id,
                    rec.resolved_form_id,
                    add_cmd,
                    remove_cmd,
                    rec.source,
                ]
                command = add_cmd if desired_unlocked else remove_cmd
                action_name = rec.name

            action = MagicCheckboxAction(
                kind=kind,
                name=action_name,
                editor_id=rec.editor_id,
                form_id=rec.resolved_form_id,
                desired_unlocked=bool(desired_unlocked),
                currently_unlocked=bool(current_unlocked),
                favorite=bool(current_favorite),
                source=rec.source,
                direct_save_supported=not bool(direct_disabled),
            )
            searchable = [*values, rec.category, rec.notes, rec.encoded_refid_hex, "checked" if desired_unlocked else "unchecked"]
            if known_only and not (current_unlocked or desired_unlocked or pending):
                continue
            if self._magic_row_matches_query(searchable, query):
                split_rows[kind].append({
                    "values": values,
                    "checked": desired_unlocked,
                    "copy": command,
                    "data": {
                        "key": key,
                        "kind": kind,
                        "name": action_name,
                        "editor_id": rec.editor_id,
                        "form_id": rec.resolved_form_id,
                        "currently_unlocked": bool(current_unlocked),
                        "favorite": bool(current_favorite),
                        "source": rec.source,
                        "current_status": status_text,
                        "direct_disabled": direct_disabled,
                        "direct_disabled_reason": direct_disabled_reason,
                        "action": action,
                    },
                })

        self._populate_magic_reference_rows(self.magic_spell_table, split_rows["Spells"])
        self._populate_magic_reference_rows(self.magic_shout_table, split_rows["Shouts"])
        self._populate_magic_reference_rows(self.magic_power_table, split_rows["Powers"])
        if hasattr(self, "magic_ability_table"):
            self._populate_magic_reference_rows(self.magic_ability_table, split_rows["Abilities"])
        if hasattr(self, "magic_active_effect_table"):
            self._populate_magic_reference_rows(self.magic_active_effect_table, split_rows["Active Effects"])
        self._update_magic_checkbox_script_preview()

    def _magic_checkbox_changed(self, item: QTableWidgetItem) -> None:
        if getattr(self, "_loading_magic_tables", False):
            return
        if item.column() != 0:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        key = str(data.get("key") or "")
        if not key:
            return
        direct_disabled = bool(data.get("direct_disabled"))
        desired = item.checkState() == Qt.CheckState.Checked
        item.setText("Unlocked" if desired else "Unlock")
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        current = bool(data.get("currently_unlocked"))
        action = MagicCheckboxAction(
            kind=str(data.get("kind") or ""),
            name=str(data.get("name") or ""),
            editor_id=str(data.get("editor_id") or ""),
            form_id=str(data.get("form_id") or ""),
            desired_unlocked=desired,
            currently_unlocked=current,
            favorite=bool(data.get("favorite")),
            source=str(data.get("source") or ""),
            direct_save_supported=not direct_disabled,
        )
        if desired == current:
            self.magic_pending_changes.pop(key, None)
        else:
            self.magic_pending_changes[key] = action
        table = item.tableWidget()
        if table is not None:
            status_item = table.item(item.row(), 1)
            if status_item is not None:
                if desired == current:
                    status_item.setText(str(data.get("current_status") or ""))
                else:
                    label = f"Queued: {action.action_label}"
                    if action.unsupported_reason(self._magic_script_mode()):
                        label += " (script skipped)"
                    status_item.setText(label)
        self._update_magic_checkbox_script_preview()

    def _magic_script_mode(self) -> str:
        if hasattr(self, "magic_script_mode_combo"):
            value = self.magic_script_mode_combo.currentData()
            if value in {"add_only", "match"}:
                return str(value)
        return "add_only"

    def _magic_checkbox_script_text(self) -> str:
        return build_magic_command_script(self.magic_pending_changes.values(), mode=self._magic_script_mode())

    def _update_magic_checkbox_script_preview(self) -> None:
        count = len(self.magic_pending_changes)
        mode = self._magic_script_mode()
        unsupported = sum(1 for action in self.magic_pending_changes.values() if action.unsupported_reason(mode))
        if hasattr(self, "magic_changes_label"):
            if count:
                mode_label = "Safe Add/Unlock Only" if mode == "add_only" else "Match Checkboxes"
                runnable = 0
                for action in self.magic_pending_changes.values():
                    if action.desired_unlocked != action.currently_unlocked and not action.unsupported_reason(mode):
                        runnable += len(action.command_lines())
                extra = f" {unsupported} queued change(s) will be commented as skipped in this mode." if unsupported else ""
                self.magic_changes_label.setText(f"{count} magic checkbox change(s) pending. They will sync automatically when you use File > Save Working Save. Mode: {mode_label}. Runnable console command lines: {runnable}.{extra}")
            else:
                self.magic_changes_label.setText("No pending Magic checkbox changes.")
        if hasattr(self, "magic_script_output"):
            self.magic_script_output.setPlainText(self._magic_checkbox_script_text())

    def preview_magic_checkbox_script(self) -> None:
        self._update_magic_checkbox_script_preview()
        if hasattr(self, "magic_tabs") and hasattr(self, "magic_script_output"):
            idx = self.magic_tabs.indexOf(self.magic_script_output.parentWidget())
            if idx >= 0:
                self.magic_tabs.setCurrentIndex(idx)

    def copy_magic_checkbox_script(self) -> None:
        script = self._magic_checkbox_script_text()
        QApplication.clipboard().setText(script)
        self._update_magic_checkbox_script_preview()
        self.statusBar().showMessage("Safe magic script copied.", 3000)

    def save_magic_checkbox_script(self) -> None:
        default_name = "skyrim_magic_changes.txt"
        target, _ = QFileDialog.getSaveFileName(self, "Save Console Magic Script (.txt)", default_name, "Text Files (*.txt);;All Files (*)")
        if not target:
            return
        target_path = Path(target)
        try:
            target_path.write_text(self._magic_checkbox_script_text(), encoding="utf-8", newline="\n")
        except OSError as exc:
            QMessageBox.critical(self, "Magic script save failed", str(exc))
            return
        bat_name = target_path.stem
        QMessageBox.information(
            self,
            "Safe magic script saved",
            f"Safe script written:\n{target_path}\n\nRun in Skyrim console with:\nbat {bat_name}\n\nThen wait a few seconds, open the magic menu to let Skyrim refresh, and make a new in-game save. The editor did not directly edit the save file.",
        )


    def _allow_experimental_missing_shout_save(self) -> bool:
        return bool(
            getattr(self, "magic_experimental_missing_shouts_check", None)
            and self.magic_experimental_missing_shouts_check.isChecked()
        )


    def _magic_direct_patch_ids(self, *, add_only: bool = True) -> tuple[list[str], list[str], list[str], list[str]]:
        magic_unlock_ids: list[str] = []
        magic_lock_ids: list[str] = []
        shout_unlock_ids: list[str] = []
        shout_lock_ids: list[str] = []
        for action in self.magic_pending_changes.values():
            if action.desired_unlocked == action.currently_unlocked:
                continue
            is_shout = action.kind == "Shouts"
            if is_shout and not getattr(action, "direct_save_supported", True) and not self._allow_experimental_missing_shout_save():
                # Missing shout Word-of-Power rows are script-only by default.
                # When Experimental Missing Shouts is enabled, include them so the
                # patcher can insert Word-of-Power ChangeForms for backup-only testing.
                continue
            if action.desired_unlocked:
                (shout_unlock_ids if is_shout else magic_unlock_ids).append(action.form_id)
            elif not add_only:
                (shout_lock_ids if is_shout else magic_lock_ids).append(action.form_id)
        return magic_unlock_ids, magic_lock_ids, shout_unlock_ids, shout_lock_ids

    def _magic_direct_skipped_remove_count(self) -> int:
        return sum(
            1
            for action in self.magic_pending_changes.values()
            if action.desired_unlocked != action.currently_unlocked and not action.desired_unlocked
        )

    def _magic_direct_skipped_script_only_count(self) -> int:
        if self._allow_experimental_missing_shout_save():
            return 0
        return sum(
            1
            for action in self.magic_pending_changes.values()
            if action.desired_unlocked != action.currently_unlocked
            and action.kind == "Shouts"
            and not getattr(action, "direct_save_supported", True)
        )

    def _magic_direct_patch_preview_text(self) -> str:
        if not self.current_save:
            return "No save loaded. Open a save first."
        magic_unlock_ids, magic_lock_ids, shout_unlock_ids, shout_lock_ids = self._magic_direct_patch_ids(add_only=True)
        skipped_removes = self._magic_direct_skipped_remove_count()
        if not any([magic_unlock_ids, magic_lock_ids, shout_unlock_ids, shout_lock_ids]):
            if skipped_removes:
                return (
                    "No add/unlock changes are queued for Experimental Save Copy.\n\n"
                    f"Skipped unchecked/remove requests: {skipped_removes}. Experimental direct save copy is add/unlock-only. "
                    "Use Save Safe Script with Match Checkboxes if you need removal commands."
                )
            script_only = self._magic_direct_skipped_script_only_count()
            if script_only:
                return (
                    "No directly saveable magic changes are queued.\n\n"
                    f"Missing shout word requests: {script_only}. These cannot be written safely into the save yet. "
                    "Use the console script route for those shout words."
                )
            return "No magic checkbox changes are queued for Experimental Save Copy."
        texts: list[str] = [
            "Experimental Save Copy plan",
            "- Writes to a new save file only; the loaded/original save is not overwritten.",
            "- Adds spell/power/ability IDs to the detected learned-magic list.",
            ("- Experimental Missing Shouts is ON: missing shout Word-of-Power records will be inserted for testing." if self._allow_experimental_missing_shout_save() else "- Unlocks only shout words that already have Word-of-Power ChangeForms."),
            ("- Keep backups; inserted shout records still need in-game testing." if self._allow_experimental_missing_shout_save() else "- Skips removals and missing-shout insertion for safety."),
        ]
        if skipped_removes:
            texts.append(f"- Skipped unchecked/remove requests: {skipped_removes}.")
        texts.append("")
        if magic_unlock_ids or magic_lock_ids:
            texts.append(build_magic_learned_patch_plan(
                self.current_save,
                self.db.records,
                magic_unlock_ids,
                magic_lock_ids,
                allow_lock=False,
            ).to_text())
        if shout_unlock_ids or shout_lock_ids:
            texts.append(build_shout_word_patch_plan(
                self.current_save,
                self.db.records,
                shout_unlock_ids,
                shout_lock_ids,
                allow_insert_missing=self._allow_experimental_missing_shout_save(),
                allow_lock=False,
            ).to_text())
        return "\n\n".join(texts)

    def _magic_direct_patch_has_changes(self, preview_text: str) -> bool:
        if (
            not preview_text.strip()
            or "No magic checkbox changes are queued" in preview_text
            or "No add/unlock changes" in preview_text
            or "No directly saveable magic changes are queued" in preview_text
        ):
            return False
        change_markers = (
            "Add/unlock in learned list:",
            "Set existing word(s) unlocked:",
            "Insert new unlocked word ChangeForm(s):",
        )
        return any(marker in preview_text for marker in change_markers)


    def _magic_direct_patch_summary_text(self) -> str:
        magic_unlock_ids, magic_lock_ids, shout_unlock_ids, shout_lock_ids = self._magic_direct_patch_ids(add_only=True)
        skipped_removes = self._magic_direct_skipped_remove_count()
        skipped_script_only = self._magic_direct_skipped_script_only_count()
        total = len(magic_unlock_ids) + len(magic_lock_ids) + len(shout_unlock_ids) + len(shout_lock_ids)
        return (
            f"Queued experimental add/unlock changes: {total}\n"
            f"- Spell/power/ability add/unlock entries: {len(magic_unlock_ids)}\n"
            f"- Shout Word-of-Power unlock entries: {len(shout_unlock_ids)}\n"
            f"- Skipped unchecked/remove entries: {skipped_removes}\n"
            + (f"- Script-only missing shout entries skipped for direct save: {skipped_script_only}\n" if not self._allow_experimental_missing_shout_save() else "- Experimental missing shout insertion: ENABLED\n") + "\n"
            "Experimental Save Copy writes to a new save file only. It skips direct removals. "
            "The full patch plan is shown in the scrollable box below and is also copied into the Magic preview panel."
        )

    def _confirm_scrollable_patch_plan(self, title: str, summary: str, details: str, accept_text: str) -> bool:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setModal(True)
        dialog.resize(820, 620)
        dialog.setMinimumSize(640, 420)

        layout = QVBoxLayout(dialog)
        intro = QLabel(summary)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        details_box = QPlainTextEdit()
        details_box.setReadOnly(True)
        details_box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        details_box.setPlainText(details)
        details_box.setMinimumHeight(300)
        layout.addWidget(details_box, 1)

        buttons = QDialogButtonBox(dialog)
        accept_button = buttons.addButton(accept_text, QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_button = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        cancel_button.setDefault(True)
        cancel_button.setAutoDefault(True)
        accept_button.setAutoDefault(False)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        return dialog.exec() == QDialog.DialogCode.Accepted

    def _direct_magic_disabled_message(self) -> str:
        return (
            "Direct overwrite of the loaded save is disabled.\n\n"
            "Use Save Experimental Copy for direct add/unlock testing, or Save Safe Script for the safest in-game route. "
            "The original loaded save is never overwritten by the experimental path.\n\n"
            "Safe workflow:\n"
            "1. Check the spells, powers, abilities, or shouts you want.\n"
            "2. Click Save Safe Script.\n"
            "3. Put the script where Skyrim can run it and use: bat <scriptname>\n"
            "4. Save in-game normally.\n\n"
            "Test-copy workflow:\n"
            "Use Save Edited Save Copy (.ess/.DAT). Load that copy in-game. Keep the original until the copy loads and behaves correctly."
        )

    def preview_magic_direct_patch(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        try:
            preview_text = self._magic_direct_patch_preview_text()
        except Exception as exc:
            QMessageBox.warning(self, "Experimental copy preview failed", str(exc))
            return
        if hasattr(self, "magic_script_output"):
            self.magic_script_output.setPlainText(preview_text)
        if hasattr(self, "magic_tabs") and hasattr(self, "magic_script_output"):
            idx = self.magic_tabs.indexOf(self.magic_script_output.parentWidget())
            if idx >= 0:
                self.magic_tabs.setCurrentIndex(idx)

    def _apply_direct_magic_and_shout_patch(self, source: Path, target: Path, *, in_place: bool) -> str:
        magic_unlock_ids, magic_lock_ids, shout_unlock_ids, shout_lock_ids = self._magic_direct_patch_ids(add_only=True)
        if not any([magic_unlock_ids, magic_lock_ids, shout_unlock_ids, shout_lock_ids]):
            raise ValueError("No magic checkbox changes are queued.")
        texts: list[str] = []
        working_source = source
        if magic_unlock_ids or magic_lock_ids:
            magic_plan = apply_magic_learned_patch(working_source, target, self.db.records, magic_unlock_ids, magic_lock_ids, allow_lock=False)
            texts.append(magic_plan.to_text())
            working_source = target
        elif not in_place and source != target:
            # Leave copying to the first real patcher.  If only shout changes are
            # queued, shout patcher reads source and writes target directly below.
            working_source = source
        if shout_unlock_ids or shout_lock_ids:
            shout_plan = apply_shout_word_patch(working_source, target, self.db.records, shout_unlock_ids, shout_lock_ids, allow_insert_missing=self._allow_experimental_missing_shout_save(), allow_lock=False)
            texts.append(shout_plan.to_text())
        return "\n\n".join(texts)

    def apply_magic_direct_patch_to_save(self) -> None:
        QMessageBox.warning(self, "Direct magic patch disabled", self._direct_magic_disabled_message())
        self.preview_magic_checkbox_script()
        return
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        try:
            preview_text = self._magic_direct_patch_preview_text()
        except Exception as exc:
            QMessageBox.warning(self, "Direct magic patch preview failed", str(exc))
            return
        if hasattr(self, "magic_script_output"):
            self.magic_script_output.setPlainText(preview_text)
        if not self._magic_direct_patch_has_changes(preview_text):
            QMessageBox.information(self, "No direct changes", preview_text)
            return
        summary = (
            "This will create a backup, then patch spell/power/ability learned-list entries "
            "and shout Word-of-Power records in the loaded save.\n\n"
            f"{self._magic_direct_patch_summary_text()}"
        )
        if not self._confirm_scrollable_patch_plan(
            "Apply direct magic/shout patch",
            summary,
            preview_text,
            "Apply Patch",
        ):
            return
        try:
            make_backup(self.current_save)
            applied_text = self._apply_direct_magic_and_shout_patch(self.current_save, self.current_save, in_place=True)
            self.current_doc = read_ess(self.current_save)
            self.magic_pending_changes.clear()
            self._refresh_all_from_doc()
        except Exception as exc:
            QMessageBox.critical(self, "Direct magic/shout patch failed", str(exc))
            return
        if hasattr(self, "magic_script_output"):
            self.magic_script_output.setPlainText(applied_text)
        QMessageBox.information(self, "Magic/shout patch applied", f"Magic/shout patch applied with a backup:\n{self.current_save}")

    def _default_magic_save_copy_path(self) -> Path:
        if not self.current_save:
            return Path("magic-test.ess")
        source = Path(self.current_save)
        suffix = source.suffix or ".ess"
        return source.with_name(f"{source.stem}.magic-test{suffix}")

    def _normalize_magic_save_copy_target(self, raw_target: str) -> Path:
        if not self.current_save:
            raise ValueError("Open a save first.")
        source = Path(self.current_save)
        source_suffix = source.suffix or ".ess"
        source_suffix_lower = source_suffix.lower()
        if source_suffix_lower not in {".ess", ".dat"}:
            source_suffix = ".ess"
            source_suffix_lower = ".ess"
        target = Path(raw_target)
        if target.suffix.lower() == ".txt":
            target = target.with_suffix(source_suffix)
            QMessageBox.information(
                self,
                "Changed .txt to save extension",
                f"The edited-save button writes a Skyrim save, not a text script.\n\n"
                f"I changed the target extension to:\n{target.name}",
            )
        elif target.suffix.lower() not in {".ess", ".dat"}:
            # File dialogs on Windows can return names without an extension when
            # All Files is selected.  Force the same save extension as the source.
            target = target.with_suffix(source_suffix)
        if source.resolve() == target.resolve():
            raise ValueError("Refusing to overwrite the loaded save. Choose a different output name for the edited test copy.")
        return target

    def save_magic_direct_patch_as(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        try:
            preview_text = self._magic_direct_patch_preview_text()
        except Exception as exc:
            QMessageBox.warning(self, "Direct magic patch preview failed", str(exc))
            return
        if not self._magic_direct_patch_has_changes(preview_text):
            QMessageBox.information(self, "No direct changes", preview_text)
            return
        default_name = str(self._default_magic_save_copy_path())
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save Edited Skyrim Save Copy",
            default_name,
            "Skyrim Save Files (*.ess *.ESS *.dat *.DAT);;All Files (*)",
        )
        if not target:
            return
        try:
            target_path = self._normalize_magic_save_copy_target(target)
        except Exception as exc:
            QMessageBox.warning(self, "Invalid edited-save target", str(exc))
            return
        if hasattr(self, "magic_script_output"):
            self.magic_script_output.setPlainText(preview_text)
        summary = (
            "Write the experimental add/unlock-only magic patch to this new save copy?\n\n"
            f"Target:\n{target_path}\n\n"
            f"{self._magic_direct_patch_summary_text()}"
        )
        if not self._confirm_scrollable_patch_plan(
            "Save edited Skyrim save copy",
            summary,
            preview_text,
            "Save Edited Save Copy",
        ):
            return
        try:
            if target_path.exists():
                make_backup(target_path)
            applied_text = self._apply_direct_magic_and_shout_patch(self.current_save, target_path, in_place=False)
            applied_text += "\n\n" + self._validate_experimental_magic_copy(target_path)
            self.current_save = target_path
            self.current_doc = read_ess(target_path)
            self.path_edit.setText(str(target_path))
            self.magic_pending_changes.clear()
            self._refresh_all_from_doc()
        except Exception as exc:
            QMessageBox.critical(self, "Magic/shout copy save failed", str(exc))
            return
        if hasattr(self, "magic_script_output"):
            self.magic_script_output.setPlainText(applied_text)
        QMessageBox.information(self, "Experimental magic copy saved", f"Experimental magic test copy written:\n{target_path}\n\nLoad this copy in Skyrim to test. Keep your original save untouched until the copy loads successfully.")

    def _validate_experimental_magic_copy(self, target_path: Path) -> str:
        magic_unlock_ids, _magic_lock_ids, shout_unlock_ids, _shout_lock_ids = self._magic_direct_patch_ids(add_only=True)
        lines = ["Experimental copy validation"]
        try:
            scan = scan_magic(target_path, self.db.records)
        except Exception as exc:
            lines.append(f"- Could not re-scan edited copy: {exc}")
            return "\n".join(lines)

        learned_found = {h.resolved_form_id.upper() for h in scan.hits if "learned magic" in h.area.casefold()}
        shout_found = {s.resolved_form_id.upper() for s in (scan.shout_words or []) if s.unlocked}
        if magic_unlock_ids:
            ok = sum(1 for fid in magic_unlock_ids if fid.upper() in learned_found)
            lines.append(f"- Spell/power/ability learned-list check: {ok}/{len(magic_unlock_ids)} requested IDs detected after write.")
        if shout_unlock_ids:
            ok = sum(1 for fid in shout_unlock_ids if fid.upper() in shout_found)
            missing = len(shout_unlock_ids) - ok
            lines.append(f"- Existing shout-word unlock check: {ok}/{len(shout_unlock_ids)} requested IDs detected unlocked after write.")
            if missing:
                lines.append("- Some shout IDs were not written because they were missing from the save; use the safe console script for those.")
        if not magic_unlock_ids and not shout_unlock_ids:
            lines.append("- No add/unlock IDs were queued for direct copy validation.")
        lines.append("- Parser re-opened the edited copy successfully.")
        return "\n".join(lines)


    def _write_working_bytes_to_temp(self) -> Path:
        if not self.current_save or self.working_save_bytes is None:
            raise ValueError("Open a save first.")
        suffix = self.current_save.suffix or ".ess"
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="skyrim_lab_working_")
        temp_path = Path(handle.name)
        try:
            handle.write(self.working_save_bytes)
            handle.close()
        except Exception:
            try:
                handle.close()
            finally:
                temp_path.unlink(missing_ok=True)
            raise
        return temp_path

    def _load_working_bytes_from_path(self, path: Path) -> None:
        if not self.current_save:
            raise ValueError("Open a save first.")
        self.working_save_bytes = path.read_bytes()
        doc = read_ess(path)
        # Keep the UI anchored to the real loaded save path even though the parser
        # validated the in-memory bytes through a temporary file.
        try:
            doc.path = self.current_save
        except Exception:
            pass
        self.current_doc = doc
        self.working_save_dirty = True
        self.inventory_pending_adds.clear()
        self.magic_pending_changes.clear()
        self._refresh_all_from_doc()

    def stage_magic_changes_to_working_copy(self, confirm: bool = True, notify: bool = True) -> bool:
        """Apply queued magic changes to the shared in-memory save buffer only.

        Returns True when there is no work to do or when the working bytes were
        successfully patched and re-opened. Returns False when staging failed or
        the user cancelled an explicit manual sync.
        """
        if not self.current_save:
            if notify:
                QMessageBox.information(self, "No save loaded", "Open a save first.")
            return False
        if self.working_save_bytes is None:
            if notify:
                QMessageBox.warning(self, "No working copy", "The loaded save was not copied into memory. Reload the save and try again.")
            return False
        try:
            preview_text = self._magic_direct_patch_preview_text()
        except Exception as exc:
            if notify:
                QMessageBox.warning(self, "Working patch preview failed", str(exc))
            return False
        if not self._magic_direct_patch_has_changes(preview_text):
            if notify:
                QMessageBox.information(self, "No saveable Magic changes", preview_text)
            return False if getattr(self, "magic_pending_changes", None) else True
        if hasattr(self, "magic_script_output"):
            self.magic_script_output.setPlainText(preview_text)
        summary = (
            "Stage these magic/shout changes into the shared in-memory working save?\n\n"
            "This does not overwrite your original file. After staging, the editor re-opens the working bytes. "
            "Use File > Save Working Save only after the staged copy looks correct.\n\n"
            f"{self._magic_direct_patch_summary_text()}"
        )
        if confirm and not self._confirm_scrollable_patch_plan(
            "Sync magic changes to working save",
            summary,
            preview_text,
            "Sync Changes",
        ):
            return False
        source_tmp = target_tmp = None
        try:
            source_tmp = self._write_working_bytes_to_temp()
            target_tmp = source_tmp.with_name(source_tmp.stem + "_patched" + source_tmp.suffix)
            applied_text = self._apply_direct_magic_and_shout_patch(source_tmp, target_tmp, in_place=False)
            # Hard validation: if the parser cannot re-open the patched bytes, keep
            # the previous working buffer and report the failure.
            validation_doc = read_ess(target_tmp)
            validation_text = self._validate_experimental_magic_copy(target_tmp)
            script_only_pending = {} if self._allow_experimental_missing_shout_save() else {
                key: action
                for key, action in self.magic_pending_changes.items()
                if action.desired_unlocked != action.currently_unlocked
                and action.kind == "Shouts"
                and not getattr(action, "direct_save_supported", True)
            }
            self._load_working_bytes_from_path(target_tmp)
            # Keep script-only shout requests visible instead of silently dropping them.
            # They are not direct-saveable; the user can export/run the console script.
            self.magic_pending_changes.update(script_only_pending)
            self._update_magic_checkbox_script_preview()
        except Exception as exc:
            if notify:
                QMessageBox.critical(self, "Sync magic changes failed", str(exc))
            return False
        finally:
            for tmp in (source_tmp, target_tmp):
                try:
                    if tmp:
                        Path(tmp).unlink(missing_ok=True)
                except Exception:
                    pass
        if hasattr(self, "magic_script_output"):
            self.magic_script_output.setPlainText(applied_text + "\n\n" + validation_text)
        if notify:
            skipped_script_only = self._magic_direct_skipped_script_only_count()
            if skipped_script_only:
                self.statusBar().showMessage(f"Magic changes synced. {skipped_script_only} script-only shout word(s) were skipped.", 7000)
            else:
                self.statusBar().showMessage("Magic changes synced into the working save.", 5000)
        return True

    def _sync_pending_edits_before_disk_save(self) -> bool:
        """Push pending per-page edits into the shared working save before disk save.

        Magic checkboxes are intentionally lightweight while editing. This method
        makes Save the single commit point: pending Magic changes are patched into
        the working bytes and validated automatically before the file is written.
        """
        if getattr(self, "magic_pending_changes", None):
            return self.stage_magic_changes_to_working_copy(confirm=False, notify=False)
        return True

    def save_working_save(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        if self.working_save_bytes is None:
            QMessageBox.warning(self, "No working copy", "No in-memory working save is available. Reload the save and try again.")
            return
        if not self._sync_pending_edits_before_disk_save():
            return
        if not self.working_save_dirty:
            self.statusBar().showMessage("Nothing to save; the working save is already synced.", 5000)
            return
        try:
            make_backup(self.current_save)
            self.current_save.write_bytes(self.working_save_bytes)
            self.current_doc = read_ess(self.current_save)
            self.working_save_bytes = self.current_save.read_bytes()
            self.working_save_dirty = False
            self._refresh_all_from_doc()
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self.statusBar().showMessage(f"Saved working save with backup: {self.current_save}", 7000)

    def save_working_save_as(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        if self.working_save_bytes is None:
            QMessageBox.warning(self, "No working copy", "No in-memory working save is available. Reload the save and try again.")
            return
        if not self._sync_pending_edits_before_disk_save():
            return
        default = self.current_save.with_name(f"{self.current_save.stem}.edited{self.current_save.suffix or '.ess'}")
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save Working Skyrim Save As",
            str(default),
            "Skyrim Save Files (*.ess *.ESS *.dat *.DAT);;All Files (*)",
        )
        if not target:
            return
        try:
            target_path = self._normalize_magic_save_copy_target(target)
            if target_path.exists():
                make_backup(target_path)
            target_path.write_bytes(self.working_save_bytes)
            # Keep editing the saved-as target so every tab remains synced with the file the user just wrote.
            self.current_save = target_path
            self.path_edit.setText(str(target_path))
            self.current_doc = read_ess(target_path)
            self.working_save_bytes = target_path.read_bytes()
            self.working_save_dirty = False
            self._refresh_all_from_doc()
        except Exception as exc:
            QMessageBox.critical(self, "Save As failed", str(exc))
            return
        self.statusBar().showMessage(f"Saved working copy: {target_path}", 7000)

    def restore_latest_save_backup(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open the corrupted save first, then click Restore Latest Backup.")
            return
        save_path = Path(self.current_save)
        backups = sorted(
            [p for p in save_path.parent.glob(f"{save_path.name}.*.bak") if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not backups:
            QMessageBox.warning(
                self,
                "No backup found",
                f"No automatic backup was found beside:\n{save_path}\n\nExpected a file named like:\n{save_path.name}.YYYYMMDD_HHMMSS.bak",
            )
            return
        backup = backups[0]
        summary = (
            "Restore the newest automatic backup over the currently loaded save?\n\n"
            f"Current save to replace:\n{save_path}\n\n"
            f"Backup to restore:\n{backup}\n\n"
            "The current corrupted file will be backed up again before restore."
        )
        if QMessageBox.question(self, "Restore latest save backup", summary) != QMessageBox.StandardButton.Yes:
            return
        try:
            corrupt_backup = make_backup(save_path)
            shutil.copy2(backup, save_path)
            self.current_doc = read_ess(save_path)
            self.magic_pending_changes.clear()
            self._refresh_all_from_doc()
        except Exception as exc:
            QMessageBox.critical(self, "Backup restore failed", str(exc))
            return
        QMessageBox.information(
            self,
            "Backup restored",
            f"Restored:\n{backup}\n\nRe-backed up the replaced corrupted file as:\n{corrupt_backup}",
        )

    def clear_magic_checkbox_changes(self) -> None:
        self.magic_pending_changes.clear()
        self._populate_magic_split_tables()
        self._update_magic_checkbox_script_preview()
        self.statusBar().showMessage("Magic checkbox queue cleared.", 3000)

    def _set_magic_table_unlocked(self, table: QTableWidget, checked: bool = True, *, direct_saveable_only: bool = False) -> int:
        changed = 0
        skipped_script_only = 0
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is None or not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                continue
            data = item.data(Qt.ItemDataRole.UserRole)
            if direct_saveable_only and isinstance(data, dict) and bool(data.get("direct_disabled")):
                skipped_script_only += 1
                continue
            target_state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            if item.checkState() == target_state:
                continue
            item.setCheckState(target_state)
            # Some Qt builds do not reliably emit itemChanged when a check state
            # is changed programmatically inside bulk actions.  Queue the desired
            # MagicCheckboxAction explicitly so Unlock All -> File Save always has
            # real pending data to write.  If the signal did fire, this is
            # idempotent and simply refreshes the same pending action.
            self._magic_checkbox_changed(item)
            changed += 1
        if skipped_script_only:
            self.statusBar().showMessage(f"Skipped {skipped_script_only} script-only shout word(s); direct save cannot safely add missing Word-of-Power records.", 7000)
        return changed

    def unlock_visible_magic_tab(self) -> None:
        if not hasattr(self, "magic_tabs"):
            return
        current = self.magic_tabs.currentWidget()
        if current is None:
            return
        changed = 0
        for table in current.findChildren(QTableWidget):
            if table in {
                getattr(self, "magic_spell_table", None),
                getattr(self, "magic_shout_table", None),
                getattr(self, "magic_power_table", None),
                getattr(self, "magic_ability_table", None),
                getattr(self, "magic_active_effect_table", None),
            }:
                changed += self._set_magic_table_unlocked(table, True)
        self._update_magic_checkbox_script_preview()
        self.statusBar().showMessage(f"Unlocked/queued {changed} visible magic row(s).", 4000)


    def clear_visible_magic_tab(self) -> None:
        if not hasattr(self, "magic_tabs"):
            return
        current = self.magic_tabs.currentWidget()
        if current is None:
            return
        changed = 0
        for table in current.findChildren(QTableWidget):
            if table in {
                getattr(self, "magic_spell_table", None),
                getattr(self, "magic_shout_table", None),
                getattr(self, "magic_power_table", None),
                getattr(self, "magic_ability_table", None),
                getattr(self, "magic_active_effect_table", None),
            }:
                changed += self._set_magic_table_unlocked(table, False)
        self._update_magic_checkbox_script_preview()
        self.statusBar().showMessage(f"Cleared/queued {changed} visible magic row(s).", 4000)

    def unlock_all_shouts_experimental(self) -> None:
        """Queue every shout word and make the experimental insert path explicit.

        The earlier UI let users check script-only missing shouts but then skipped
        them at Save time unless a separate checkbox was enabled. For testing, the
        dedicated Unlock All Shouts button should mean exactly that: queue every
        shout word and allow Save Working Save to insert missing Word-of-Power
        records into the working save, with the normal backup-on-save protection.
        """
        if getattr(self, "magic_experimental_missing_shouts_check", None) is not None:
            self.magic_experimental_missing_shouts_check.setChecked(True)
        self.unlock_magic_table_rows(self.magic_shout_table, "shout words")

    def unlock_magic_table_rows(self, table: QTableWidget, label: str = "magic rows", *, direct_saveable_only: bool = False) -> None:
        changed = self._set_magic_table_unlocked(table, True, direct_saveable_only=direct_saveable_only)
        self._update_magic_checkbox_script_preview()
        self.statusBar().showMessage(f"Unlocked/queued {changed} {label}.", 4000)

    def unlock_all_magic_rows(self) -> None:
        if not hasattr(self, "magic_spell_table"):
            return
        changed = 0
        for table in [
            self.magic_spell_table,
            self.magic_power_table,
            getattr(self, "magic_ability_table", None),
            getattr(self, "magic_active_effect_table", None),
        ]:
            if table is not None:
                changed += self._set_magic_table_unlocked(table, True)
        experimental_missing = self._allow_experimental_missing_shout_save()
        if getattr(self, "magic_shout_table", None) is not None:
            changed += self._set_magic_table_unlocked(
                self.magic_shout_table,
                True,
                direct_saveable_only=not experimental_missing,
            )
        self._update_magic_checkbox_script_preview()
        if experimental_missing:
            self.statusBar().showMessage(f"Unlocked/queued {changed} magic row(s). Experimental missing shout insertion is enabled for Save Working Save.", 7000)
        else:
            self.statusBar().showMessage(f"Unlocked/queued {changed} directly saveable magic row(s). Script-only missing shout words were skipped.", 7000)

    def _selected_magic_reference_meta(self) -> dict[str, object] | None:
        if not hasattr(self, "magic_tabs"):
            return None
        current = self.magic_tabs.currentWidget()
        if not current:
            return None
        for table in current.findChildren(QTableWidget):
            items = table.selectedItems()
            if not items:
                continue
            data = items[0].data(Qt.ItemDataRole.UserRole)
            if isinstance(data, dict):
                return data
        return None

    def _copy_magic_reference_command(self, item: QTableWidgetItem | None = None) -> bool:
        data = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(data, dict):
            data = self._selected_magic_reference_meta()
        if not isinstance(data, dict):
            return False
        command = str(data.get("copy") or "").strip()
        if not command:
            action = data.get("action")
            if isinstance(action, MagicCheckboxAction):
                command = "\n".join(action.command_lines())
        if not command:
            return False
        QApplication.clipboard().setText(command)
        self.statusBar().showMessage("Magic command copied.", 3000)
        return True

    def _populate_magic_favorites_table(self) -> None:
        if not hasattr(self, "magic_favorites_table"):
            return
        blocks = self.current_magic_scan.favorite_blocks if self.current_magic_scan else []
        self.magic_favorites_table.setRowCount(len(blocks))
        for row, block in enumerate(blocks):
            values = [
                str(block.table),
                str(block.index),
                "109 / Magic Favorites",
                f"0x{block.data_offset:X}",
                str(block.length),
                f"{block.candidate_count}: {block.candidate_hex}",
                block.sample_hex,
            ]
            for col, value in enumerate(values):
                self.magic_favorites_table.setItem(row, col, QTableWidgetItem(value))
        self.magic_favorites_table.resizeColumnsToContents()

    def _populate_magic_database_table(self) -> None:
        if not hasattr(self, "magic_database_table"):
            return
        plugins = self.current_doc.plugin_info.plugins if self.current_doc and self.current_doc.plugin_info else []
        records = magic_records_from_database(self.db.records, plugins)
        query = self.magic_db_filter.text().casefold().strip() if hasattr(self, "magic_db_filter") else ""
        if query:
            records = [r for r in records if query in " ".join([r.category, r.editor_id, r.name, r.form_id, r.resolved_form_id, r.encoded_refid_hex, r.source, r.notes]).casefold()]
        self.magic_database_table.setRowCount(len(records))
        for row, rec in enumerate(records):
            for col, value in enumerate([rec.category, rec.editor_id, rec.name, rec.form_id, rec.resolved_form_id, rec.encoded_refid_hex, rec.source]):
                self.magic_database_table.setItem(row, col, QTableWidgetItem(str(value)))
        self.magic_database_table.resizeColumnsToContents()

    def _selected_magic_hit(self):
        if not hasattr(self, "magic_table"):
            return None
        items = self.magic_table.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.ItemDataRole.UserRole)

    def _update_magic_detail(self) -> None:
        if not hasattr(self, "magic_detail"):
            return
        h = self._selected_magic_hit()
        if not h:
            self.magic_detail.setPlainText("Select a magic hit to view details.")
            return
        self.magic_detail.setPlainText(
            f"{h.name}\n"
            f"Category: {h.category}\n"
            f"FormID: {h.form_id} resolved {h.resolved_form_id}; encoded RefID bytes {h.encoded_refid_hex}\n"
            f"Area: {h.area}\n"
            f"Offset: 0x{h.offset:X}" + (f" / local 0x{h.local_offset:X}" if h.local_offset is not None else "") + "\n"
            f"Confidence: {h.confidence}\n"
            f"Source: {h.source}\n"
            f"Notes: {h.notes}"
        )

    def copy_selected_magic_hit(self) -> None:
        if self._copy_magic_reference_command():
            return
        h = self._selected_magic_hit()
        if not h:
            QMessageBox.information(self, "No magic selected", "Select a row in Spells, Shouts, Powers, Abilities, Active Effects, or Known Magic Hits first.")
            return
        text = (
            f"{h.name}\nCategory: {h.category}\nFormID: {h.form_id}\nResolved: {h.resolved_form_id}\n"
            f"RefID bytes: {h.encoded_refid_hex}\nArea: {h.area}\nOffset: 0x{h.offset:X}\nNotes: {h.notes}"
        )
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("Magic hit copied.", 3000)

    def export_magic_csv(self) -> None:
        if not self.current_magic_scan:
            QMessageBox.information(self, "No magic scan", "Open a save and run Reload Magic first.")
            return
        default = str((self.current_save or Path("magic_scan")).with_suffix(".magic.csv"))
        target, _ = QFileDialog.getSaveFileName(self, "Export Magic CSV", default, "CSV (*.csv)")
        if not target:
            return
        try:
            Path(target).write_text(magic_hits_to_csv(self.current_magic_scan.hits), encoding="utf-8", newline="")
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        QMessageBox.information(self, "Exported", f"Magic CSV written:\n{target}")

    def _refresh_plugins(self) -> None:
        full_count = 0
        light_count = 0
        if self.current_doc and self.current_doc.plugin_info:
            full_count = len(self.current_doc.plugin_info.plugins)
            light_count = len(self.current_doc.plugin_info.light_plugins)
            rows = [(f"Full {i}", f"{i:02X}", plugin) for i, plugin in enumerate(self.current_doc.plugin_info.plugins)]
            rows += [(f"Light {i}", f"FE{i:03X}", plugin) for i, plugin in enumerate(self.current_doc.plugin_info.light_plugins)]
        else:
            rows = []

        query = ""
        if hasattr(self, "plugin_filter_edit"):
            query = self.plugin_filter_edit.text().strip().casefold()
        if query:
            rows = [
                row
                for row in rows
                if query in row[0].casefold() or query in row[1].casefold() or query in row[2].casefold()
            ]

        if hasattr(self, "plugin_counts_label"):
            if self.current_doc and self.current_doc.plugin_info:
                self.plugin_counts_label.setText(f"Full: {full_count}  |  Light: {light_count}  |  Showing: {len(rows)}")
            else:
                self.plugin_counts_label.setText("Open a save to list plugins.")

        self.plugin_table.setRowCount(len(rows))
        for i, (slot, hex_slot, plugin) in enumerate(rows):
            slot_item = QTableWidgetItem(slot)
            hex_item = QTableWidgetItem(hex_slot)
            plugin_item = QTableWidgetItem(plugin)
            plugin_item.setToolTip(plugin)
            self.plugin_table.setItem(i, 0, slot_item)
            self.plugin_table.setItem(i, 1, hex_item)
            self.plugin_table.setItem(i, 2, plugin_item)
        self._refresh_formid_plugin_combo()

    def _refresh_formid_plugin_combo(self) -> None:
        if not hasattr(self, "formid_plugin_combo"):
            return
        current = self.formid_plugin_combo.currentText()
        self.formid_plugin_combo.blockSignals(True)
        self.formid_plugin_combo.clear()
        self.formid_plugin_combo.addItem("No plugin selected")
        if self.current_doc and self.current_doc.plugin_info:
            for i, plugin in enumerate(self.current_doc.plugin_info.plugins):
                self.formid_plugin_combo.addItem(f"{i:02X} - {plugin}", plugin)
            for i, plugin in enumerate(self.current_doc.plugin_info.light_plugins):
                self.formid_plugin_combo.addItem(f"FE{i:03X} - {plugin}", plugin)
        idx = self.formid_plugin_combo.findText(current)
        if idx >= 0:
            self.formid_plugin_combo.setCurrentIndex(idx)
        self.formid_plugin_combo.blockSignals(False)

    def analyze_form_id(self) -> None:
        if not hasattr(self, "formid_table"):
            return
        plugins = self.current_doc.plugin_info.plugins if self.current_doc and self.current_doc.plugin_info else []
        plugin_name = ""
        if hasattr(self, "formid_plugin_combo") and self.formid_plugin_combo.currentIndex() > 0:
            plugin_name = self.formid_plugin_combo.currentData() or ""
        info = describe_form_id(self.formid_input.text(), plugin_name, plugins)
        rows = info.to_rows()
        self.formid_table.setRowCount(len(rows))
        for row, (field, value) in enumerate(rows):
            self.formid_table.setItem(row, 0, QTableWidgetItem(field))
            self.formid_table.setItem(row, 1, QTableWidgetItem(value))
        self.formid_table.resizeColumnsToContents()
        if info.resolved_id and hasattr(self, "scan_form_edit"):
            self.scan_form_edit.setText(info.resolved_id)




    def _uesp_format_reference_rows(self) -> list[tuple[str, str, str, str]]:
        """Reference rows distilled from UESP Skyrim_Mod:Save_File_Format notes.

        These rows are intentionally documentation-only. The writable byte map is
        generated separately by build_mapped_raw_fields(), using offsets found in
        the currently loaded save.
        """
        rows: list[tuple[str, str, str, str]] = []

        def add(section: str, name: str, typ: str, notes: str) -> None:
            rows.append((section, name, typ, notes))

        add("File", "magic", "char[13]", 'Constant string "TESV_SAVEGAME".')
        add("File", "headerSize", "uint32", "Size of the Header block.")
        add("File", "header", "Header", "Header struct with visual save metadata and screenshot dimensions.")
        add("File", "screenshotData", "uint8[]", "LE saves use RGB pixels; SE saves use RGBA pixels.")
        add("File", "uncompressedLen", "uint32", "SE only; present when compression is enabled.")
        add("File", "compressedLen", "uint32", "SE only; compressed payload byte count.")
        add("File", "formVersion", "uint8", "Current LE value is 9; SE commonly uses 74.")
        add("File", "pluginInfoSize", "uint32", "Size of the plugin-info block.")
        add("File", "pluginInfo", "Plugin Info", "Full/load-order plugin list.")
        add("File", "lightPluginInfo", "Light Plugin Info", "SE only when formVersion >= 78; ESL plugin information.")
        add("File", "fileLocationTable", "File Location Table", "Offset/count table for the following sections.")
        add("File", "globalDataTable1", "Global Data[]", "Global data types 0 to 8.")
        add("File", "globalDataTable2", "Global Data[]", "Global data types 100 to 114.")
        add("File", "changeForms", "Change Form[]", "Per-reference/object changed data.")
        add("File", "globalDataTable3", "Global Data[]", "Global data types 1000 to 1005.")
        add("File", "formIdArrayCount", "uint32", "Count for the four-byte little-endian FormID array; not RefIDs.")
        add("File", "formIdArray", "formID[]", "FormIDs referenced by save RefIDs.")
        add("File", "visitedWorldspaceArrayCount", "uint32", "Count for visited worldspace FormIDs.")
        add("File", "visitedWorldspaceArray", "formID[]", "Worldspaces visited by the player.")
        add("File", "unknown3TableSize", "uint32", "Byte size of Unknown 3 table.")
        add("File", "unknown3Table", "Unknown 3 Table", "Unknown table at the tail of the save structure.")

        add("Header", "version", "uint32", "Current LE header version is 9; SE support detection can use this with formVersion.")
        add("Header", "saveNumber", "uint32", "Save counter/default filename counter.")
        add("Header", "playerName", "wstring", "Visual player name displayed on save screen.")
        add("Header", "playerLevel", "uint32", "Visual player level displayed on save screen.")
        add("Header", "playerLocation", "wstring", "Visual location text; not actual player position.")
        add("Header", "gameDate", "wstring", "In-game date string at save time.")
        add("Header", "playerRaceEditorId", "wstring", "Visual race editor ID text.")
        add("Header", "playerSex", "uint16", "0 = male, 1 = female.")
        add("Header", "playerCurExp", "float32", "Header/display experience gathered for level-up.")
        add("Header", "playerLvlUpExp", "float32", "Header/display experience required for level-up.")
        add("Header", "filetime", "FILETIME", "Windows FILETIME timestamp.")
        add("Header", "shotWidth", "uint32", "Screenshot width in pixels.")
        add("Header", "shotHeight", "uint32", "Screenshot height in pixels.")
        add("Header", "compressionType", "uint16", "0 none, 1 zlib, 2 LZ4 block format.")

        add("Plugin Info", "pluginCount", "uint8", "Number of full plugins.")
        add("Plugin Info", "plugins", "wstring[pluginCount]", "Plugin filenames in load order.")
        add("Light Plugin Info", "lightPluginCount", "uint16", "SE ESL/light-plugin count.")
        add("Light Plugin Info", "lightPlugins", "wstring[lightPluginCount]", "Light plugin filenames.")

        add("File Location Table", "formIDArrayCountOffset", "uint32", "Absolute offset to File.formIdArrayCount.")
        add("File Location Table", "unknownTable3Offset", "uint32", "Absolute offset to File.unknown3TableSize.")
        add("File Location Table", "globalDataTable1Offset", "uint32", "Absolute offset to File.globalDataTable1.")
        add("File Location Table", "globalDataTable2Offset", "uint32", "Absolute offset to File.globalDataTable2.")
        add("File Location Table", "changeFormsOffset", "uint32", "Absolute offset to File.changeForms.")
        add("File Location Table", "globalDataTable3Offset", "uint32", "Absolute offset to File.globalDataTable3.")
        add("File Location Table", "globalDataTable1Count", "uint32", "Number of Global Data entries in table 1.")
        add("File Location Table", "globalDataTable2Count", "uint32", "Number of Global Data entries in table 2.")
        add("File Location Table", "globalDataTable3Count", "uint32", "Number of Global Data entries in table 3. UESP notes this count can be bugged for type 1001.")
        add("File Location Table", "changeFormCount", "uint32", "Number of Change Forms.")
        add("File Location Table", "unused", "uint32[15]", "Unused/reserved table values.")

        global_types = [
            (0, "Misc Stats"), (1, "Player Location"), (2, "TES"), (3, "Global Variables"),
            (4, "Created Objects"), (5, "Effects"), (6, "Weather"), (7, "Audio"), (8, "SkyCells"),
            (100, "Process Lists"), (101, "Combat"), (102, "Interface"), (103, "Actor Causes"),
            (104, "Unknown 104"), (105, "Detection Manager"), (106, "Location Meta Data"),
            (107, "Quest Static Data"), (108, "Story Teller"), (109, "Magic Favorites"),
            (110, "Player Controls"), (111, "Story Event Manager"), (112, "Ingredient Shared"),
            (113, "MenuControls"), (114, "MenuTopicManager"), (1000, "Temp Effects"),
            (1001, "Papyrus"), (1002, "Anim Objects"), (1003, "Timer"),
            (1004, "Synchronized Animations"), (1005, "Main"),
        ]
        for number, name in global_types:
            add("Global Data Types", str(number), "Global Data type", name)

        add("Global Data", "type", "uint32", "Global data type selector.")
        add("Global Data", "length", "uint32", "Length of the following global-data payload.")
        add("Global Data", "data", "uint8[length]", "Payload format depends on type.")

        add("RefID", "byte0 high bits", "2-bit selector", "0 = index into FormID array, 1 = default Skyrim.esm form, 2 = created/0xFF plugin index, 3 = unknown/reserved.")
        add("RefID", "byte0..byte2", "uint8[3]", "Three-byte save RefID. It is not the same layout as a normal four-byte FormID.")

        add("Change Form", "formID", "RefID", "Save RefID for the changed reference/object.")
        add("Change Form", "changeFlags", "uint32", "Bitset indicating which fields are present in the change-form data.")
        add("Change Form", "type", "uint8", "Upper 2 bits select length field size; lower 6 bits select record type.")
        add("Change Form", "version", "uint8", "Current form version commonly 74 for SE, older values are also valid.")
        add("Change Form", "length1", "depends on type byte", "Uncompressed data length.")
        add("Change Form", "length2", "depends on flags", "Compressed length when nonzero/compressed.")
        add("Change Form", "data", "uint8[length1]", "Record-specific payload. Layout is a work in progress per UESP.")

        change_types = [
            (0, "REFR"), (1, "ACHR"), (2, "PMIS"), (3, "PGRE"), (4, "PBEA"), (5, "PFLA"),
            (6, "CELL"), (7, "INFO"), (8, "QUST"), (9, "NPC_"), (10, "ACTI"), (11, "TACT"),
            (12, "ARMO"), (13, "BOOK"), (14, "CONT"), (15, "DOOR"), (16, "INGR"), (17, "LIGH"),
            (18, "MISC"), (19, "APPA"), (20, "STAT"), (21, "MSTT"), (22, "FURN"), (23, "WEAP"),
            (24, "AMMO"), (25, "KEYM"), (26, "ALCH"), (27, "IDLM"), (28, "NOTE"), (29, "ECZN"),
            (30, "CLAS"), (31, "FACT"), (32, "PACK"), (33, "NAVM"), (34, "WOOP"), (35, "MGEF"),
            (36, "SMQN"), (37, "SCEN"), (38, "LCTN"), (39, "RELA"), (40, "PHZD"), (41, "PBAR"),
            (42, "PCON"), (43, "FLST"), (44, "LVLN"), (45, "LVLI"), (46, "LVSP"), (47, "PARW"),
            (48, "ENCH"),
        ]
        for number, name in change_types:
            add("Change Form Types", str(number), "lower 6 bits", name)

        add("Unknown 3 Table", "count", "uint32", "Count of unknown strings/entries.")
        add("Unknown 3 Table", "unknown", "wstring[count]", "Unknown table entries.")
        return rows

    def load_raw_json_from_doc(self) -> None:
        if not hasattr(self, "raw_json"):
            return
        self._loading_raw_json = True
        try:
            text = self.current_doc.to_json() if self.current_doc else ""
            self.raw_json.setPlainText(text)
            self.raw_json.document().clearUndoRedoStacks()
        finally:
            self._loading_raw_json = False
        self.validate_raw_json_editor_quiet()

    def validate_raw_json_editor_quiet(self) -> None:
        if getattr(self, "_loading_raw_json", False):
            return
        if not hasattr(self, "raw_json_status_label") or not hasattr(self, "raw_json"):
            return
        text = self.raw_json.toPlainText()
        if not text.strip():
            self.raw_json_status_label.setText("Parsed JSON is empty.")
            return
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            self.raw_json_status_label.setText(
                f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}. "
                "Use Undo or Reload Parsed before exporting."
            )
            return
        root_type = type(data).__name__
        count = len(data) if hasattr(data, "__len__") else 1
        self.raw_json_status_label.setText(
            f"Valid JSON ({root_type}, {count:,} top-level item(s)). "
            "This is an editable/exportable parsed view; it does not write back to save bytes directly."
        )

    def validate_raw_json_editor(self) -> None:
        self.validate_raw_json_editor_quiet()
        if hasattr(self, "raw_json_status_label"):
            self.statusBar().showMessage(self.raw_json_status_label.text(), 5000)

    def _set_raw_json_text_preserve_undo(self, text: str) -> None:
        if not hasattr(self, "raw_json"):
            return
        self.raw_json.setPlainText(text)
        self.validate_raw_json_editor_quiet()

    def format_raw_json_editor(self) -> None:
        if not hasattr(self, "raw_json"):
            return
        try:
            data = json.loads(self.raw_json.toPlainText())
        except json.JSONDecodeError as exc:
            QMessageBox.warning(self, "JSON syntax error", f"Cannot format invalid JSON:\nline {exc.lineno}, column {exc.colno}: {exc.msg}")
            return
        self._set_raw_json_text_preserve_undo(json.dumps(data, indent=2, ensure_ascii=False))
        self.statusBar().showMessage("Formatted parsed JSON", 3000)

    def compact_raw_json_editor(self) -> None:
        if not hasattr(self, "raw_json"):
            return
        try:
            data = json.loads(self.raw_json.toPlainText())
        except json.JSONDecodeError as exc:
            QMessageBox.warning(self, "JSON syntax error", f"Cannot compact invalid JSON:\nline {exc.lineno}, column {exc.colno}: {exc.msg}")
            return
        self._set_raw_json_text_preserve_undo(json.dumps(data, separators=(",", ":"), ensure_ascii=False))
        self.statusBar().showMessage("Compacted parsed JSON", 3000)

    def undo_raw_json_editor(self) -> None:
        if hasattr(self, "raw_json"):
            self.raw_json.undo()
            self.validate_raw_json_editor_quiet()

    def reload_raw_json_editor(self) -> None:
        if not self.current_doc:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        if hasattr(self, "raw_json") and self.raw_json.document().isModified():
            result = QMessageBox.question(
                self,
                "Reload parsed JSON",
                "Reload the parsed JSON from the currently loaded save and discard JSON text edits?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if result != QMessageBox.StandardButton.Yes:
                return
        self.load_raw_json_from_doc()
        self.statusBar().showMessage("Reloaded parsed JSON", 3000)

    def _find_raw_json(self, backwards: bool = False) -> None:
        if not hasattr(self, "raw_json") or not hasattr(self, "raw_json_search_edit"):
            return
        needle = self.raw_json_search_edit.text()
        if not needle:
            self.statusBar().showMessage("Type a JSON search term first", 3000)
            return
        text = self.raw_json.toPlainText()
        haystack = text if self.raw_json_case_check.isChecked() else text.casefold()
        query = needle if self.raw_json_case_check.isChecked() else needle.casefold()
        cursor = self.raw_json.textCursor()
        if backwards:
            start_pos = max(0, cursor.selectionStart() - 1)
            idx = haystack.rfind(query, 0, start_pos + 1)
            if idx < 0:
                idx = haystack.rfind(query)
        else:
            start_pos = cursor.selectionEnd()
            idx = haystack.find(query, start_pos)
            if idx < 0:
                idx = haystack.find(query)
        if idx < 0:
            self.statusBar().showMessage(f"No match for {needle!r}", 4000)
            return
        new_cursor = self.raw_json.textCursor()
        new_cursor.setPosition(idx)
        new_cursor.setPosition(idx + len(needle), QTextCursor.MoveMode.KeepAnchor)
        self.raw_json.setTextCursor(new_cursor)
        self.raw_json.setFocus()
        line = text.count("\n", 0, idx) + 1
        col = idx - text.rfind("\n", 0, idx)
        self.statusBar().showMessage(f"Found {needle!r} at line {line}, column {col}", 4000)

    def find_next_raw_json(self) -> None:
        self._find_raw_json(backwards=False)

    def find_previous_raw_json(self) -> None:
        self._find_raw_json(backwards=True)

    def export_raw_json_editor_text(self) -> None:
        if not hasattr(self, "raw_json"):
            return
        text = self.raw_json.toPlainText()
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            result = QMessageBox.question(
                self,
                "Export invalid JSON?",
                f"The JSON text is invalid at line {exc.lineno}, column {exc.colno}: {exc.msg}\n\nExport it anyway as text?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if result != QMessageBox.StandardButton.Yes:
                return
        default_name = "parsed-edited.json"
        if self.current_save:
            default_name = str(self.current_save.with_suffix(".parsed-edited.json"))
        target, _ = QFileDialog.getSaveFileName(self, "Export Edited Parsed JSON", default_name, "JSON (*.json);;All Files (*)")
        if not target:
            return
        try:
            Path(target).write_text(text, encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.statusBar().showMessage(f"Exported edited parsed JSON to {target}", 5000)

    def refresh_raw_format_reference_table(self) -> None:
        if not hasattr(self, "raw_format_table"):
            return
        needle = self.raw_format_filter_edit.text().strip().casefold() if hasattr(self, "raw_format_filter_edit") else ""
        rows = []
        for row in self._uesp_format_reference_rows():
            haystack = " ".join(row).casefold()
            if needle and needle not in haystack:
                continue
            rows.append(row)
        self.raw_format_table.setRowCount(len(rows))
        for r, row_values in enumerate(rows):
            for c, value in enumerate(row_values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.raw_format_table.setItem(r, c, item)
        self.raw_format_table.resizeColumnsToContents()
        if self.raw_format_table.columnWidth(0) < 180:
            self.raw_format_table.setColumnWidth(0, 180)
        if self.raw_format_table.columnWidth(1) < 220:
            self.raw_format_table.setColumnWidth(1, 220)
        if self.raw_format_table.columnWidth(3) < 520:
            self.raw_format_table.setColumnWidth(3, 520)


    def _save_wizard_code_reference_rows(self) -> list[dict[str, str]]:
        """Old Save Wizard-style code snippets as research hints, not auto-patches."""
        return [
            {
                "code": "All Skills Level 100",
                "search": "05 00 00 00 00 00 00 00 06 00 00 00",
                "write": "42 C8 00 00 = float32 100.0; repeated skill fields",
                "target": "Likely player skill actor-value block / skill data, not save header level text.",
                "status": "Research only. Need exact table/record mapping before enabling writes.",
            },
            {
                "code": "Carry Weight 1,000,000,000",
                "search": "05 00 00 00 00 00 00 00 06 00 00 00",
                "write": "4E 6E 6B 23 = float32 ~1,000,000,000",
                "target": "Likely actor value data near player stats.",
                "status": "Research only. We should expose it as a named mapped stat once located per save.",
            },
            {
                "code": "Health / Magicka / Stamina 1,000,000,000",
                "search": "05 00 00 00 00 00 00 00 06 00 00 00",
                "write": "4E 6E 6B 28 = very large float32; repeated 6 values at 8-byte stride",
                "target": "Likely player actor-value/current/base stat fields.",
                "status": "Research only. Needs before/after tests for one stat at a time.",
            },
            {
                "code": "+100,000 EXP",
                "search": "80 BF 00 00 00 00 80 BF 00 00",
                "write": "47 C3 50 00 = float32 100000.0 at relative +0x34; zero at +0x38",
                "target": "Likely real level/experience structure, separate from visual header XP.",
                "status": "Candidate for next safe editor after a controlled before/after XP save pair.",
            },
            {
                "code": "Max Perk Points",
                "search": "00 00 00 41 37 46 41 37 00 00 00 00",
                "write": "000000FF at relative +0x0C after second-stage search",
                "target": "Likely perk-points field in player/global data.",
                "status": "Research only. Pattern may be brittle; map field before writing.",
            },
            {
                "code": "Skyrim Item Swap / Iron Arrow marker",
                "search": "41 39 7D 01",
                "write": "01 xx xx 4x reversed-ish FormID bytes used by the code note",
                "target": "Inventory stack FormID bytes. We now prefer mapped inventory rows over blind swaps.",
                "status": "Use as inventory-row discovery hint only; direct row insertion remains test-gated.",
            },
        ]

    def refresh_raw_code_reference_table(self) -> None:
        if not hasattr(self, "raw_code_table"):
            return
        needle = self.raw_code_filter_edit.text().strip().casefold() if hasattr(self, "raw_code_filter_edit") else ""
        rows = []
        for row in self._save_wizard_code_reference_rows():
            haystack = " ".join(row.values()).casefold()
            if needle and needle not in haystack:
                continue
            rows.append(row)
        hits_map = getattr(self, "raw_code_hits", {})
        self.raw_code_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            hit_text = hits_map.get(row["code"], "Not scanned")
            values = [row["code"], row["search"], row["write"], row["target"], hit_text, row["status"]]
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if c in (1, 2, 5):
                    item.setToolTip(str(value))
                self.raw_code_table.setItem(r, c, item)
        self.raw_code_table.resizeColumnsToContents()
        if self.raw_code_table.columnWidth(0) < 220:
            self.raw_code_table.setColumnWidth(0, 220)
        if self.raw_code_table.columnWidth(3) < 360:
            self.raw_code_table.setColumnWidth(3, 360)
        if self.raw_code_table.columnWidth(5) < 420:
            self.raw_code_table.setColumnWidth(5, 420)

    def refresh_quick_code_format_table(self) -> None:
        if not hasattr(self, "quick_code_format_table"):
            return
        needle = self.quick_code_format_filter_edit.text().strip().casefold() if hasattr(self, "quick_code_format_filter_edit") else ""
        rows = []
        for fmt in QUICK_CODE_FORMATS:
            values = [fmt.code_type, fmt.name, fmt.layout, fmt.meaning, fmt.notes, fmt.example]
            haystack = " ".join(values).casefold()
            if needle and needle not in haystack:
                continue
            rows.append(values)
        self.quick_code_format_table.setRowCount(len(rows))
        for r, values in enumerate(rows):
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if c in (2, 3, 4, 5):
                    item.setToolTip(str(value))
                self.quick_code_format_table.setItem(r, c, item)
        self.quick_code_format_table.resizeColumnsToContents()
        minimums = {0: 52, 1: 190, 2: 230, 3: 330, 4: 360, 5: 230}
        for col, width in minimums.items():
            if self.quick_code_format_table.columnWidth(col) < width:
                self.quick_code_format_table.setColumnWidth(col, width)

    def decode_quick_code_input(self) -> None:
        if not hasattr(self, "quick_code_input"):
            return
        text = self.quick_code_input.toPlainText()
        try:
            decoded = decode_quick_code_text(text)
        except QuickCodeDecodeError as exc:
            decoded = f"Decode failed: {exc}"
        except Exception as exc:
            decoded = f"Decode failed unexpectedly: {exc}"
        self.quick_code_output.setPlainText(decoded)

    def clear_quick_code_decoder(self) -> None:
        if hasattr(self, "quick_code_input"):
            self.quick_code_input.clear()
        if hasattr(self, "quick_code_output"):
            self.quick_code_output.clear()

    def generate_quick_code_builder(self) -> None:
        if not hasattr(self, "quick_code_generated_output"):
            return
        code_type = self.quick_code_build_type_combo.currentData()
        address = self.quick_code_address_edit.text().strip()
        value = self.quick_code_value_edit.text().strip()
        offset = str(self.quick_code_offset_combo.currentData() or "0")
        try:
            if code_type == "A":
                generated = generate_mass_write_code(address, value, offset)
            else:
                generated = generate_standard_write_code(
                    address,
                    value,
                    int(code_type),
                    offset,
                    value_is_decimal=self.quick_code_decimal_checkbox.isChecked(),
                )
        except Exception as exc:
            QMessageBox.warning(self, "Generate failed", str(exc))
            return
        self.quick_code_generated_output.setPlainText(generated)
        self.statusBar().showMessage("Generated quick code", 3000)

    def copy_generated_quick_code(self) -> None:
        if not hasattr(self, "quick_code_generated_output"):
            return
        text = self.quick_code_generated_output.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Nothing to copy", "Generate a quick code first.")
            return
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("Copied generated quick code", 3000)

    def _find_pattern_offsets(self, data: bytes, pattern: bytes, limit: int = 12) -> tuple[int, list[int]]:
        offsets: list[int] = []
        total = 0
        start = 0
        while True:
            idx = data.find(pattern, start)
            if idx < 0:
                break
            total += 1
            if len(offsets) < limit:
                offsets.append(idx)
            start = idx + 1
        return total, offsets

    def scan_raw_code_patterns(self) -> None:
        if not self.current_save or not self.current_doc:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        raw_file = self.current_save.read_bytes()
        payload = self.current_doc.payload.data if self.current_doc.payload else b""
        hits: dict[str, str] = {}
        for row in self._save_wizard_code_reference_rows():
            try:
                pattern = bytes.fromhex(row["search"])
            except ValueError:
                hits[row["code"]] = "Invalid pattern"
                continue
            payload_count, payload_offsets = self._find_pattern_offsets(payload, pattern)
            file_count, file_offsets = self._find_pattern_offsets(raw_file, pattern)
            parts = []
            if payload_count:
                shown = ", ".join(f"0x{o:X}" for o in payload_offsets)
                parts.append(f"payload {payload_count} hit(s): {shown}")
            if file_count:
                shown = ", ".join(f"0x{o:X}" for o in file_offsets)
                parts.append(f"file {file_count} hit(s): {shown}")
            hits[row["code"]] = " | ".join(parts) if parts else "No hits"
        self.raw_code_hits = hits
        QMessageBox.information(self, "Code scan complete", "Scanned the loaded save for old code byte patterns. Check the Hits column.")

    def refresh_raw_editor(self) -> None:
        if not hasattr(self, "raw_fields_table"):
            return
        self.raw_dirty_fields.clear()
        self.refresh_raw_mapped_table()
        self.refresh_raw_change_forms_table()
        self.refresh_raw_format_reference_table()
        self.refresh_quick_code_format_table()
        self._refresh_raw_status_label()

    def _refresh_raw_status_label(self) -> None:
        if not hasattr(self, "raw_status_label"):
            return
        if not self.current_save:
            self.raw_status_label.setText("Open a save to map raw fields.")
            return
        editable = sum(1 for field in getattr(self, "raw_field_rows", []) if getattr(field, "editable", False))
        pending = len(getattr(self, "raw_dirty_fields", {}))
        self.raw_status_label.setText(
            f"Mapped {len(getattr(self, 'raw_field_rows', [])):,} raw fields. "
            f"Editable fixed-size fields: {editable:,}. Pending raw edits: {pending:,}."
        )

    def refresh_raw_mapped_table(self) -> None:
        if not hasattr(self, "raw_fields_table"):
            return
        if not self.current_save:
            self.raw_fields_table.setRowCount(0)
            self.raw_field_rows = []
            self._refresh_raw_status_label()
            return
        try:
            fields = build_mapped_raw_fields(self.current_save)
        except Exception as exc:
            self.raw_fields_table.setRowCount(0)
            self.raw_field_rows = []
            if hasattr(self, "raw_status_label"):
                self.raw_status_label.setText(f"Raw field mapping failed: {exc}")
            return
        self.raw_field_rows = fields
        needle = self.raw_filter_edit.text().strip().casefold() if hasattr(self, "raw_filter_edit") else ""
        group_filter = self.raw_group_combo.currentText() if hasattr(self, "raw_group_combo") else "All groups"
        visible = []
        for field in fields:
            if group_filter not in ("", "All groups") and field.group != group_filter:
                continue
            pending = self.raw_dirty_fields.get(field.field_id, "")
            haystack = " ".join([
                field.group, field.field, field.storage, f"0x{field.offset:X}", field.value_type,
                field.current_value, pending, field.safety, field.notes, field.raw_value or "",
                f"0x{field.virtual_offset:X}" if field.virtual_offset is not None else "",
            ]).casefold()
            if needle and needle not in haystack:
                continue
            visible.append(field)
        self._loading_raw_table = True
        self.raw_fields_table.blockSignals(True)
        self.raw_fields_table.setRowCount(len(visible))
        for row, field in enumerate(visible):
            offset_text = f"0x{field.offset:X}"
            if field.virtual_offset is not None:
                offset_text += f" / virt 0x{field.virtual_offset:X}"
            pending = self.raw_dirty_fields.get(field.field_id)
            display_value = pending if pending is not None else field.current_value
            notes = f"{field.safety} — {field.notes}"
            if pending is not None and str(pending) != str(field.current_value):
                notes = f"PENDING: original {field.current_value} → {pending}. " + notes
            values = [field.group, field.field, field.storage, offset_text, field.value_type, display_value, notes]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, field.field_id)
                if col == 5 and field.editable:
                    item.setToolTip("Double-click for a readable editor, or edit this cell directly. Save Raw Copy is recommended before Save Raw Edits.")
                else:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col == 6:
                    item.setToolTip(notes)
                self.raw_fields_table.setItem(row, col, item)
        self.raw_fields_table.blockSignals(False)
        self._loading_raw_table = False
        self.raw_fields_table.resizeColumnsToContents()
        if self.raw_fields_table.columnWidth(1) < 320:
            self.raw_fields_table.setColumnWidth(1, 320)
        if self.raw_fields_table.columnWidth(5) < 240:
            self.raw_fields_table.setColumnWidth(5, 240)
        if self.raw_fields_table.columnWidth(6) < 520:
            self.raw_fields_table.setColumnWidth(6, 520)
        self._refresh_raw_status_label()

    def refresh_raw_change_forms_table(self) -> None:
        if not hasattr(self, "raw_change_table"):
            return
        rows = self.current_doc.change_forms_preview if self.current_doc else []
        needle = self.raw_change_filter_edit.text().strip().casefold() if hasattr(self, "raw_change_filter_edit") else ""
        visible = []
        for cf in rows:
            haystack = " ".join([
                str(cf.index), cf.refid_hex, cf.form_id_guess, str(cf.form_type), f"0x{cf.change_flags:X}",
                str(cf.length1), f"0x{cf.data_offset:X}", cf.sample_hex,
            ]).casefold()
            if needle and needle not in haystack:
                continue
            visible.append(cf)
        self.raw_change_table.setRowCount(len(visible))
        for row, cf in enumerate(visible):
            values = [
                str(cf.index), cf.refid_hex, cf.form_id_guess, str(cf.form_type), f"0x{cf.change_flags:08X}",
                f"{cf.length1:,}", f"0x{cf.data_offset:X}", cf.sample_hex,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.raw_change_table.setItem(row, col, item)
        self.raw_change_table.resizeColumnsToContents()
        if self.raw_change_table.columnWidth(7) < 360:
            self.raw_change_table.setColumnWidth(7, 360)


    def open_raw_value_popup_from_item(self, item: QTableWidgetItem) -> None:
        """Open a readable popup editor when the mapped Value cell is double-clicked."""
        if not item or item.column() != 5:
            return
        field_id = item.data(Qt.ItemDataRole.UserRole)
        field = self._raw_field_lookup().get(str(field_id)) if field_id else None
        if not field:
            return
        if not getattr(field, "editable", False):
            self.statusBar().showMessage("That mapped field is read-only.", 2500)
            return
        self.open_raw_value_popup(field)

    def open_raw_value_popup(self, field=None) -> None:
        field = field or self._current_raw_field()
        if not field:
            QMessageBox.information(self, "No raw field selected", "Select a mapped field first.")
            return
        if not getattr(field, "editable", False):
            QMessageBox.information(self, "Read-only field", "This mapped row is structural/read-only. Use a dedicated editor for fields that resize data.")
            return
        field_id = getattr(field, "field_id", "")
        current = str(getattr(field, "current_value", ""))
        pending = self.raw_dirty_fields.get(field_id, current)

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Edit Raw Value - {getattr(field, 'field', 'Mapped Field')}")
        dlg.resize(720, 220)
        layout = QVBoxLayout(dlg)
        title = QLabel(f"{getattr(field, 'group', '')} / {getattr(field, 'field', '')}")
        title.setObjectName("CardTitle")
        layout.addWidget(title)
        hint = QLabel(
            f"Type: {getattr(field, 'value_type', '')}    "
            f"Storage: {getattr(field, 'storage', '')}    "
            f"Offset: 0x{int(getattr(field, 'offset', 0)):X}\n"
            f"Current/original: {current}"
        )
        hint.setWordWrap(True)
        hint.setObjectName("Subtle")
        layout.addWidget(hint)
        edit = QLineEdit()
        edit.setText(str(pending))
        edit.selectAll()
        edit.setMinimumHeight(38)
        edit.setStyleSheet(
            "QLineEdit { background: #FFFFFF; color: #111827; border: 2px solid #7EA2D6; "
            "border-radius: 8px; padding: 8px 10px; selection-background-color: #2563EB; selection-color: #FFFFFF; }"
        )
        layout.addWidget(edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        revert_btn = buttons.addButton("Revert To Current", QDialogButtonBox.ButtonRole.ActionRole)
        copy_btn = buttons.addButton("Copy Current", QDialogButtonBox.ButtonRole.ActionRole)
        revert_btn.clicked.connect(lambda: edit.setText(current))
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(current))
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        value = edit.text().strip()
        if value == current.strip():
            self.raw_dirty_fields.pop(field_id, None)
        else:
            self.raw_dirty_fields[field_id] = value
        self.refresh_raw_mapped_table()
        self._refresh_raw_status_label()
        self.statusBar().showMessage(f"Staged raw value edit for {getattr(field, 'field', '')}.", 3000)

    def _raw_field_item_changed(self, item: QTableWidgetItem) -> None:
        if getattr(self, "_loading_raw_table", False) or item.column() != 5:
            return
        field_id = item.data(Qt.ItemDataRole.UserRole)
        if not field_id:
            return
        field = self._raw_field_lookup().get(str(field_id))
        if not field or not getattr(field, "editable", False):
            return
        value = item.text().strip()
        current = str(getattr(field, "current_value", "")).strip()
        if value == current:
            self.raw_dirty_fields.pop(str(field_id), None)
        else:
            self.raw_dirty_fields[str(field_id)] = value
        self._refresh_raw_status_label()
        self._sync_raw_selected_editor(field)

    def _raw_field_lookup(self) -> dict[str, object]:
        return {getattr(field, "field_id", ""): field for field in getattr(self, "raw_field_rows", [])}

    def _raw_edits_preview(self) -> str:
        lookup = self._raw_field_lookup()
        lines = ["Raw edits preview:"]
        for field_id, new_value in self.raw_dirty_fields.items():
            field = lookup.get(field_id)
            if not field:
                lines.append(f"- {field_id}: {new_value} (field will be re-mapped before save)")
                continue
            lines.append(f"- {getattr(field, 'group', '')} / {getattr(field, 'field', '')}: {getattr(field, 'current_value', '')} → {new_value}")
        return "\n".join(lines) if len(lines) > 1 else "No raw edits are staged."

    def save_raw_edits(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        if not self.raw_dirty_fields:
            QMessageBox.information(self, "No raw edits", "Edit values in the Value column first.")
            return
        preview = self._raw_edits_preview()
        result = QMessageBox.question(
            self,
            "Save raw edits",
            f"This will create a backup, then write fixed-size mapped raw edits into the loaded save:\n\n{self.current_save}\n\n{preview}\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            new_doc = write_mapped_raw_edits_with_backup(self.current_save, dict(self.raw_dirty_fields))
        except Exception as exc:
            QMessageBox.critical(self, "Raw save failed", str(exc))
            return
        self.current_doc = new_doc
        self.raw_dirty_fields.clear()
        self._refresh_all_from_doc()
        QMessageBox.information(self, "Saved", f"Raw edits saved with a backup:\n{self.current_save}")

    def save_raw_copy(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        if not self.raw_dirty_fields:
            QMessageBox.information(self, "No raw edits", "Edit values in the Value column first.")
            return
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save Raw Edited Copy",
            str(self.current_save.with_suffix(".raw-edited" + self.current_save.suffix)),
            "Skyrim Saves (*.ess *.ESS *.dat *.DAT);;All Files (*)",
        )
        if not target:
            return
        target_path = Path(target)
        preview = self._raw_edits_preview()
        result = QMessageBox.question(
            self,
            "Save raw edited copy",
            f"This will write a copy with fixed-size mapped raw edits:\n\n{target_path}\n\n{preview}\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            new_doc = apply_mapped_raw_edits(self.current_save, target_path, dict(self.raw_dirty_fields))
        except Exception as exc:
            QMessageBox.critical(self, "Raw copy save failed", str(exc))
            return
        self.current_save = target_path
        self.current_doc = new_doc
        self.path_edit.setText(str(target_path))
        self.raw_dirty_fields.clear()
        self._refresh_all_from_doc()
        QMessageBox.information(self, "Saved", f"Raw edited copy written:\n{target_path}")


    def _current_raw_field(self):
        if not hasattr(self, "raw_fields_table"):
            return None
        row = self.raw_fields_table.currentRow()
        if row < 0:
            return None
        item = self.raw_fields_table.item(row, 0)
        field_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not field_id:
            return None
        return self._raw_field_lookup().get(str(field_id))

    def _sync_raw_selected_editor(self, field=None) -> None:
        if field is None:
            field = self._current_raw_field()
        if not hasattr(self, "raw_selected_new_edit"):
            return
        if not field:
            self.raw_selected_field_label.setText("Selected: none")
            self.raw_selected_new_edit.setText("")
            self.raw_selected_new_edit.setEnabled(False)
            for btn_name in ("raw_selected_apply_btn", "raw_selected_popup_btn", "raw_selected_use_current_btn", "raw_selected_clear_btn"):
                if hasattr(self, btn_name):
                    getattr(self, btn_name).setEnabled(False)
            return
        field_id = getattr(field, "field_id", "")
        editable = bool(getattr(field, "editable", False))
        label = f"Selected: {getattr(field, 'group', '')} / {getattr(field, 'field', '')}"
        label += f"  ({getattr(field, 'value_type', '')}, {getattr(field, 'storage', '')} 0x{int(getattr(field, 'offset', 0)):X})"
        if not editable:
            label += " — read-only"
        self.raw_selected_field_label.setText(label)
        self.raw_selected_new_edit.setEnabled(editable)
        if editable:
            value = self.raw_dirty_fields.get(field_id, str(getattr(field, "current_value", "")))
            self.raw_selected_new_edit.setText(value)
            self.raw_selected_new_edit.setPlaceholderText("Edit here, press Enter/Set Selected Value, or double-click the Value cell for a bigger editor.")
        else:
            self.raw_selected_new_edit.setText("")
            self.raw_selected_new_edit.setPlaceholderText("This row is read-only. Structural fields require a dedicated editor.")
        for btn_name in ("raw_selected_apply_btn", "raw_selected_popup_btn", "raw_selected_use_current_btn", "raw_selected_clear_btn"):
            if hasattr(self, btn_name):
                getattr(self, btn_name).setEnabled(editable)

    def apply_selected_raw_new_value(self) -> None:
        field = self._current_raw_field()
        if not field:
            QMessageBox.information(self, "No raw field selected", "Select a mapped field first.")
            return
        if not getattr(field, "editable", False):
            QMessageBox.information(self, "Read-only field", "This mapped row is structural/read-only. Use a dedicated editor for fields that resize data.")
            return
        value = self.raw_selected_new_edit.text().strip() if hasattr(self, "raw_selected_new_edit") else ""
        field_id = getattr(field, "field_id", "")
        current = str(getattr(field, "current_value", "")).strip()
        if value == current:
            self.raw_dirty_fields.pop(field_id, None)
        else:
            self.raw_dirty_fields[field_id] = value
        self.refresh_raw_mapped_table()
        self._refresh_raw_status_label()

    def use_current_raw_value_for_selected(self) -> None:
        field = self._current_raw_field()
        if not field or not getattr(field, "editable", False):
            return
        self.raw_dirty_fields.pop(getattr(field, "field_id", ""), None)
        if hasattr(self, "raw_selected_new_edit"):
            self.raw_selected_new_edit.setText(str(getattr(field, "current_value", "")))
        self.refresh_raw_mapped_table()
        self._refresh_raw_status_label()

    def clear_selected_raw_edit(self) -> None:
        field = self._current_raw_field()
        if not field:
            return
        self.raw_dirty_fields.pop(getattr(field, "field_id", ""), None)
        if hasattr(self, "raw_selected_new_edit"):
            self.raw_selected_new_edit.setText(str(getattr(field, "current_value", "")))
        self.refresh_raw_mapped_table()
        self._refresh_raw_status_label()

    def clear_all_raw_edits(self) -> None:
        self.raw_dirty_fields.clear()
        if hasattr(self, "raw_selected_new_edit"):
            self.raw_selected_new_edit.setText("")
        self.refresh_raw_mapped_table()
        self._refresh_raw_status_label()

    def _raw_field_selection_changed(self) -> None:
        field = self._current_raw_field()
        self._sync_raw_selected_editor(field)
        if not hasattr(self, "raw_hex_preview") or not self.current_doc or not self.current_save:
            return
        if not field:
            if hasattr(self, "raw_hex_preview"):
                self.raw_hex_preview.setPlainText("")
            return
        storage = getattr(field, "storage", "")
        offset = int(getattr(field, "offset", 0))
        size = int(getattr(field, "size", 0))
        try:
            if storage == "payload" and self.current_doc.payload:
                data = self.current_doc.payload.data
                label = "decoded payload"
            elif storage == "file":
                data = self.current_save.read_bytes()
                label = "raw file"
            else:
                self.raw_hex_preview.setPlainText("No byte preview for this mapping row.")
                return
            start = max(0, offset - 24)
            end = min(len(data), offset + max(size, 1) + 24)
            chunk = data[start:end]
            hex_pairs = " ".join(f"{b:02X}" for b in chunk)
            caret = "   " * (offset - start) + "^^ " * max(size, 1)
            self.raw_hex_preview.setPlainText(
                f"{getattr(field, 'field', '')}\n{label} offset 0x{offset:X}, size {size} byte(s)\n"
                f"window 0x{start:X}-0x{end:X}\n{hex_pairs}\n{caret}"
            )
        except Exception as exc:
            self.raw_hex_preview.setPlainText(f"Could not render byte preview: {exc}")

    def _backup_candidates(self) -> list[Path]:
        if not self.current_save:
            return []
        pattern = f"{self.current_save.name}.*.bak"
        return sorted(self.current_save.parent.glob(pattern), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)

    def refresh_backup_table(self) -> None:
        if not hasattr(self, "backup_table"):
            return
        backups = self._backup_candidates()
        self.backup_table.setRowCount(len(backups))
        for row, path in enumerate(backups):
            try:
                st = path.stat()
                from datetime import datetime
                modified = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                size = f"{st.st_size:,} bytes"
            except OSError:
                modified = "Unknown"
                size = "Unknown"
            name_item = QTableWidgetItem(path.name)
            name_item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.backup_table.setItem(row, 0, name_item)
            self.backup_table.setItem(row, 1, QTableWidgetItem(modified))
            self.backup_table.setItem(row, 2, QTableWidgetItem(size))
        self.backup_table.resizeColumnsToContents()

    def restore_selected_backup(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        if not hasattr(self, "backup_table"):
            return
        row = self.backup_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "No backup selected", "Select a backup row first.")
            return
        item = self.backup_table.item(row, 0)
        backup_path = Path(str(item.data(Qt.ItemDataRole.UserRole))) if item else None
        if not backup_path or not backup_path.exists():
            QMessageBox.warning(self, "Backup missing", "The selected backup no longer exists.")
            self.refresh_backup_table()
            return
        result = QMessageBox.question(
            self,
            "Restore backup",
            f"This will create one more backup of the current save, then restore:\n\n{backup_path}\n\nover:\n\n{self.current_save}\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            make_backup(self.current_save)
            shutil.copy2(backup_path, self.current_save)
            self.open_save(self.current_save)
        except Exception as exc:
            QMessageBox.critical(self, "Restore failed", str(exc))
            return
        QMessageBox.information(self, "Backup restored", f"Restored backup:\n{backup_path}")

    def save_active_edits(self) -> None:
        """Legacy page-specific save helper. File > Save Working Save now writes the shared working copy."""
        page_index = self.stack.currentIndex() if hasattr(self, "stack") else -1
        if page_index == 1:
            tab_text = self.general_tabs.tabText(self.general_tabs.currentIndex()) if hasattr(self, "general_tabs") else ""
            if tab_text == "Player":
                self.save_general_edits()
            elif tab_text == "Skills":
                self.apply_skill_edits_to_save()
            elif tab_text == "Stats":
                self.apply_actor_value_edits_to_save()
            else:
                self.save_general_edits()
            return
        if page_index == 2:
            self.save_inventory_count_changes()
            return
        if page_index == 3:
            self.save_working_save()
            return
        if page_index == 5:
            self.save_raw_edits()
            return
        QMessageBox.information(
            self,
            "Choose an editor page",
            "Use the page Apply/Stage button first, then File > Save Working Save.",
        )

    def save_active_copy(self) -> None:
        """Legacy page-specific save-as helper. File > Save Working Save As now writes the shared working copy."""
        page_index = self.stack.currentIndex() if hasattr(self, "stack") else -1
        if page_index == 1:
            tab_text = self.general_tabs.tabText(self.general_tabs.currentIndex()) if hasattr(self, "general_tabs") else ""
            if tab_text == "Player":
                self.save_general_as()
            elif tab_text == "Skills":
                self.save_skill_edits_as()
            elif tab_text == "Stats":
                self.save_actor_value_edits_as()
            else:
                self.save_general_as()
            return
        if page_index == 2:
            self.save_inventory_count_as()
            return
        if page_index == 3:
            self.save_working_save_as()
            return
        if page_index == 5:
            self.save_raw_copy()
            return
        QMessageBox.information(
            self,
            "Choose an editor page",
            "Use File > Save Working Save As… to write the shared working copy.",
        )

    def refresh_skill_values_from_save(self, silent: bool = False) -> None:
        if not hasattr(self, "skill_value_spins"):
            return
        if not self.current_save:
            self.skill_original_values.clear()
            for spin in self.skill_value_spins.values():
                spin.setEnabled(False)
                spin.setValue(0.0)
            if hasattr(self, "skill_status_label"):
                self.skill_status_label.setText("Open a save to detect the skill block.")
            if hasattr(self, "skill_preview_output") and not silent:
                self.skill_preview_output.setPlainText("No save loaded. Open a save first.")
            return
        try:
            slots, searches, _payload_size = read_skyrim_skill_values(self.current_save)
        except Exception as exc:
            self.skill_original_values.clear()
            for spin in self.skill_value_spins.values():
                spin.setEnabled(False)
                spin.setValue(0.0)
            message = f"Skill block not detected: {exc}"
            if hasattr(self, "skill_status_label"):
                self.skill_status_label.setText(message)
            if hasattr(self, "skill_preview_output") and not silent:
                self.skill_preview_output.setPlainText(message)
            return
        self._loading_skill_values = True
        self.skill_original_values.clear()
        for slot in slots:
            spin = self.skill_value_spins.get(slot.index)
            if not spin:
                continue
            spin.blockSignals(True)
            spin.setEnabled(True)
            if slot.value < spin.minimum():
                spin.setMinimum(slot.value - 1.0)
            if slot.value > spin.maximum():
                spin.setMaximum(slot.value + 1.0)
            spin.setValue(float(slot.value))
            spin.blockSignals(False)
            self.skill_original_values[slot.index] = float(slot.value)
        self._loading_skill_values = False
        anchor_text = ", ".join(f"payload 0x{hit.offset:X}" for hit in searches)
        if hasattr(self, "skill_status_label"):
            self.skill_status_label.setText(f"Detected {len(slots)} skill slots at {anchor_text}.")
        if hasattr(self, "skill_preview_output"):
            lines = ["Current detected skill values:"]
            for slot in slots:
                lines.append(f"- {slot.index + 1:02d}. {slot.name}: {slot.value:g} at payload 0x{slot.offset:X}")
            self.skill_preview_output.setPlainText("\n".join(lines))

    def _mark_skill_values_changed(self) -> None:
        if getattr(self, "_loading_skill_values", False):
            return
        if hasattr(self, "skill_preview_output"):
            self.skill_preview_output.setPlainText("Skill value changed. Click Preview Skill Edits to resolve and review exact payload writes.")

    def set_all_skill_values(self, value: float) -> None:
        if not hasattr(self, "skill_value_spins"):
            return
        if not self.skill_original_values and self.current_save:
            self.refresh_skill_values_from_save(silent=True)
        for spin in self.skill_value_spins.values():
            spin.setEnabled(True)
            spin.setValue(float(value))
        self._mark_skill_values_changed()

    def _collect_skill_patch_values(self) -> dict[int, float]:
        values: dict[int, float] = {}
        for index, spin in getattr(self, "skill_value_spins", {}).items():
            if not spin.isEnabled():
                continue
            original = self.skill_original_values.get(index)
            if original is None:
                continue
            current = float(spin.value())
            if abs(current - original) > 0.00001:
                values[int(index)] = current
        return values

    def _build_skill_preview_text(self) -> str:
        if not self.current_save:
            return "No save loaded. Open a save first, then edit skill values."
        values = self._collect_skill_patch_values()
        plan, _payload = build_skyrim_skill_patch_plan(self.current_save, values)
        return plan.to_text()

    def preview_skill_edits(self) -> None:
        if not hasattr(self, "skill_preview_output"):
            return
        try:
            preview = self._build_skill_preview_text()
        except Exception as exc:
            preview = f"Skill preview failed: {exc}"
        self.skill_preview_output.setPlainText(preview)

    def apply_skill_edits_to_save(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        try:
            values = self._collect_skill_patch_values()
            plan, _payload = build_skyrim_skill_patch_plan(self.current_save, values)
        except Exception as exc:
            QMessageBox.warning(self, "Skill preview failed", str(exc))
            return
        if not plan.writes:
            QMessageBox.information(self, "No skill changes", plan.to_text())
            if hasattr(self, "skill_preview_output"):
                self.skill_preview_output.setPlainText(plan.to_text())
            return
        if hasattr(self, "skill_preview_output"):
            self.skill_preview_output.setPlainText(plan.to_text())
        result = QMessageBox.question(
            self,
            "Apply skill edits to save",
            "Apply the skill edits shown in the Skills preview box?\n\nA backup will be created first.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            make_backup(self.current_save)
            applied_plan = apply_skyrim_skill_patch(self.current_save, self.current_save, values)
            self.current_doc = read_ess(self.current_save)
            self.inventory_dirty_counts.clear()
            self.inventory_pending_adds.clear()
            self._refresh_all_from_doc()
        except Exception as exc:
            QMessageBox.critical(self, "Skill apply failed", str(exc))
            return
        if hasattr(self, "skill_preview_output"):
            self.skill_preview_output.setPlainText(applied_plan.to_text())
        QMessageBox.information(self, "Skill edits applied", f"Skill edits were applied with a backup:\n{self.current_save}")

    def save_skill_edits_as(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        try:
            values = self._collect_skill_patch_values()
            plan, _payload = build_skyrim_skill_patch_plan(self.current_save, values)
        except Exception as exc:
            QMessageBox.warning(self, "Skill preview failed", str(exc))
            return
        if not plan.writes:
            QMessageBox.information(self, "No skill changes", plan.to_text())
            if hasattr(self, "skill_preview_output"):
                self.skill_preview_output.setPlainText(plan.to_text())
            return
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save Skill Edited Copy",
            str(self.current_save.with_suffix(".skills-edited" + self.current_save.suffix)),
            "Skyrim Saves (*.ess *.ESS *.dat *.DAT);;All Files (*)",
        )
        if not target:
            return
        target_path = Path(target)
        if hasattr(self, "skill_preview_output"):
            self.skill_preview_output.setPlainText(plan.to_text())
        result = QMessageBox.question(
            self,
            "Save skill edited copy",
            f"Write the skill edits shown in the Skills preview box to this copy?\n\nTarget:\n{target_path}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            applied_plan = apply_skyrim_skill_patch(self.current_save, target_path, values)
            self.current_save = target_path
            self.current_doc = read_ess(target_path)
            self.path_edit.setText(str(target_path))
            self.inventory_dirty_counts.clear()
            self.inventory_pending_adds.clear()
            self._refresh_all_from_doc()
        except Exception as exc:
            QMessageBox.critical(self, "Skill copy failed", str(exc))
            return
        if hasattr(self, "skill_preview_output"):
            self.skill_preview_output.setPlainText(applied_plan.to_text())
        QMessageBox.information(self, "Skill copy saved", f"Skill edited copy written:\n{target_path}")

    def _general_preset_changed(self) -> None:
        if not hasattr(self, "general_preset_combo") or not hasattr(self, "general_preset_value_spin"):
            return
        preset_id = str(self.general_preset_combo.currentData() or "")
        try:
            preset = get_skyrim_quick_code_preset(preset_id)
        except Exception:
            return
        spin = self.general_preset_value_spin
        spin.blockSignals(True)
        spin.setDecimals(int(preset.decimals))
        spin.setRange(float(preset.minimum), float(preset.maximum))
        spin.setSingleStep(1.0 if preset.value_kind == "int" else max(1.0, (preset.maximum - preset.minimum) / 100.0))
        spin.setValue(float(preset.default_value))
        spin.blockSignals(False)
        if hasattr(self, "general_preset_warning"):
            safety = (
                "Safety: this is not a confirmed direct ESS field. It is a Save Wizard search-pattern port. "
                "After a crash report, in-place writing is disabled; only experimental copies are allowed. "
                "For skills, use the validated Skills tab instead."
            )
            self.general_preset_warning.setText(f"{preset.description}\n{preset.warning}\n\n{safety}")
        self._mark_general_preset_needs_preview()

    def refresh_actor_values_from_save(self, silent: bool = False) -> None:
        if not hasattr(self, "actor_value_spins"):
            return
        if not self.current_save:
            self.actor_original_values.clear()
            for spin in self.actor_value_spins.values():
                spin.setEnabled(False)
                spin.setValue(0.0)
            if hasattr(self, "actor_status_label"):
                self.actor_status_label.setText("Open a save to detect player actor values.")
            if hasattr(self, "actor_preview_output") and not silent:
                self.actor_preview_output.setPlainText("No save loaded. Open a save first.")
            return
        try:
            slots, searches, _payload_size = read_skyrim_actor_values(self.current_save)
        except Exception as exc:
            self.actor_original_values.clear()
            for spin in self.actor_value_spins.values():
                spin.setEnabled(False)
            message = f"Actor value detection failed: {exc}"
            if hasattr(self, "actor_status_label"):
                self.actor_status_label.setText(message)
            if hasattr(self, "actor_preview_output") and not silent:
                self.actor_preview_output.setPlainText(message)
            return
        self._loading_actor_values = True
        self.actor_original_values.clear()
        found_ids = {slot.actor_id for slot in slots}
        try:
            for actor_id, spin in self.actor_value_spins.items():
                spin.blockSignals(True)
                spin.setEnabled(False)
                if actor_id not in found_ids:
                    spin.setValue(0.0)
                spin.blockSignals(False)
            for slot in slots:
                spin = self.actor_value_spins.get(slot.actor_id)
                if not spin:
                    continue
                spin.blockSignals(True)
                spin.setEnabled(True)
                spin.setValue(float(slot.value))
                spin.blockSignals(False)
                self.actor_original_values[slot.actor_id] = float(slot.value)
        finally:
            self._loading_actor_values = False
        anchor_text = ", ".join(f"0x{hit.offset:X}" for hit in searches)
        missing_names = [SKYRIM_ACTOR_VALUE_NAMES.get(actor_id, f"ActorValue {actor_id}") for actor_id, _name in SKYRIM_ACTOR_VALUE_FIELDS if actor_id not in found_ids]
        if hasattr(self, "actor_status_label"):
            suffix = f" Missing/disabled: {', '.join(missing_names)}." if missing_names else ""
            self.actor_status_label.setText(f"Detected {len(slots)} editable actor-value slot(s) at {anchor_text}.{suffix}")
        if hasattr(self, "actor_preview_output"):
            lines = ["Detected editable player actor values:"]
            for slot in slots:
                lines.append(f"- {slot.name}: {slot.value:g} at payload 0x{slot.value_offset:X} (ActorValue {slot.actor_id})")
            if missing_names:
                lines.append("")
                lines.append("Missing values are disabled for this save so the editor will not guess or patch blind bytes:")
                for name in missing_names:
                    lines.append(f"- {name}")
            self.actor_preview_output.setPlainText("\n".join(lines))

    def _mark_actor_values_changed(self) -> None:
        if getattr(self, "_loading_actor_values", False):
            return
        if hasattr(self, "actor_preview_output"):
            self.actor_preview_output.setPlainText("Actor value changed. Click Preview Stat Edits to resolve and review exact payload writes.")

    def set_vital_actor_values(self, value: float) -> None:
        if not hasattr(self, "actor_value_spins"):
            return
        if not self.actor_original_values and self.current_save:
            self.refresh_actor_values_from_save(silent=True)
        for actor_id in (24, 25, 26):
            spin = self.actor_value_spins.get(actor_id)
            if spin and spin.isEnabled():
                spin.setValue(float(value))
        self._mark_actor_values_changed()

    def set_carry_actor_values(self, value: float) -> None:
        if not hasattr(self, "actor_value_spins"):
            return
        if not self.actor_original_values and self.current_save:
            self.refresh_actor_values_from_save(silent=True)
        for actor_id in (320,):
            spin = self.actor_value_spins.get(actor_id)
            if spin and spin.isEnabled():
                spin.setValue(float(value))
        self._mark_actor_values_changed()

    def _collect_actor_value_patch_values(self) -> dict[int, float]:
        values: dict[int, float] = {}
        for actor_id, spin in getattr(self, "actor_value_spins", {}).items():
            if not spin.isEnabled():
                continue
            current = float(spin.value())
            original = self.actor_original_values.get(actor_id)
            if original is None or abs(current - original) > 0.00001:
                values[int(actor_id)] = current
        return values

    def _build_actor_value_preview_text(self) -> str:
        if not self.current_save:
            return "No save loaded. Open a save first, then edit actor values."
        values = self._collect_actor_value_patch_values()
        plan, _payload = build_skyrim_actor_value_patch_plan(self.current_save, values)
        return plan.to_text()

    def preview_actor_value_edits(self) -> None:
        if not hasattr(self, "actor_preview_output"):
            return
        try:
            preview = self._build_actor_value_preview_text()
        except Exception as exc:
            preview = f"Actor value preview failed: {exc}"
        self.actor_preview_output.setPlainText(preview)

    def apply_actor_value_edits_to_save(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        try:
            values = self._collect_actor_value_patch_values()
            plan, _payload = build_skyrim_actor_value_patch_plan(self.current_save, values)
        except Exception as exc:
            QMessageBox.warning(self, "Actor value preview failed", str(exc))
            return
        if not plan.writes:
            QMessageBox.information(self, "No actor value changes", plan.to_text())
            if hasattr(self, "actor_preview_output"):
                self.actor_preview_output.setPlainText(plan.to_text())
            return
        if hasattr(self, "actor_preview_output"):
            self.actor_preview_output.setPlainText(plan.to_text())
        result = QMessageBox.question(
            self,
            "Apply actor value edits",
            "Apply the Health / Magicka / Stamina / Carry Weight edits shown in the Stats preview box?\n\nA backup will be created first.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            make_backup(self.current_save)
            applied_plan = apply_skyrim_actor_value_patch(self.current_save, self.current_save, values)
            self.current_doc = read_ess(self.current_save)
            self.inventory_dirty_counts.clear()
            self.inventory_pending_adds.clear()
            self._refresh_all_from_doc()
        except Exception as exc:
            QMessageBox.critical(self, "Actor value apply failed", str(exc))
            return
        if hasattr(self, "actor_preview_output"):
            self.actor_preview_output.setPlainText(applied_plan.to_text())
        QMessageBox.information(self, "Actor values applied", f"Actor value edits were applied with a backup:\n{self.current_save}")

    def save_actor_value_edits_as(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        try:
            values = self._collect_actor_value_patch_values()
            plan, _payload = build_skyrim_actor_value_patch_plan(self.current_save, values)
        except Exception as exc:
            QMessageBox.warning(self, "Actor value preview failed", str(exc))
            return
        if not plan.writes:
            QMessageBox.information(self, "No actor value changes", plan.to_text())
            if hasattr(self, "actor_preview_output"):
                self.actor_preview_output.setPlainText(plan.to_text())
            return
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save Actor Value Edited Copy",
            str(self.current_save.with_suffix(".stats-edited" + self.current_save.suffix)),
            "Skyrim Saves (*.ess *.ESS *.dat *.DAT);;All Files (*)",
        )
        if not target:
            return
        target_path = Path(target)
        if hasattr(self, "actor_preview_output"):
            self.actor_preview_output.setPlainText(plan.to_text())
        result = QMessageBox.question(
            self,
            "Save actor value edited copy",
            f"Write the actor value edits shown in the Stats preview box to this copy?\n\nTarget:\n{target_path}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            applied_plan = apply_skyrim_actor_value_patch(self.current_save, target_path, values)
            self.current_save = target_path
            self.current_doc = read_ess(target_path)
            self.path_edit.setText(str(target_path))
            self.inventory_dirty_counts.clear()
            self.inventory_pending_adds.clear()
            self._refresh_all_from_doc()
        except Exception as exc:
            QMessageBox.critical(self, "Actor value copy failed", str(exc))
            return
        if hasattr(self, "actor_preview_output"):
            self.actor_preview_output.setPlainText(applied_plan.to_text())
        QMessageBox.information(self, "Actor value copy saved", f"Actor value edited copy written:\n{target_path}")

    def _current_general_preset_request(self) -> tuple[str, object, str]:
        preset_id = str(self.general_preset_combo.currentData() or "")
        preset = get_skyrim_quick_code_preset(preset_id)
        raw_value = self.general_preset_value_spin.value() if hasattr(self, "general_preset_value_spin") else preset.default_value
        value = int(round(raw_value)) if preset.value_kind == "int" else float(raw_value)
        return preset_id, value, preset.name

    def _mark_general_preset_needs_preview(self) -> None:
        if hasattr(self, "general_preset_output"):
            self.general_preset_output.setPlainText("Preset value changed. Preview will resolve search anchors only. Writing is limited to experimental save copies; in-place preset apply is disabled.")

    def _build_general_preset_preview_text(self) -> str:
        if not self.current_save:
            return "No save loaded. Open a save first, then preview the preset patch."
        preset_id, value, _name = self._current_general_preset_request()
        plan, _payload = build_skyrim_preset_patch_plan(self.current_save, preset_id, value)
        return plan.to_text()

    def preview_general_preset_patch(self) -> None:
        if not hasattr(self, "general_preset_output"):
            return
        try:
            preview = self._build_general_preset_preview_text()
        except Exception as exc:
            preview = f"Preset preview failed: {exc}"
        self.general_preset_output.setPlainText(preview)

    def apply_general_preset_to_save(self) -> None:
        QMessageBox.warning(
            self,
            "Preset in-place apply disabled",
            "Save Wizard-pattern preset writes are disabled for the opened save after crash reports. "
            "Use General > Skills for validated skill edits, Common for mapped inventory values, or save an experimental preset copy for testing."
        )

    def save_general_preset_as(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        if not getattr(self, "experimental_preset_checkbox", None) or not self.experimental_preset_checkbox.isChecked():
            QMessageBox.warning(
                self,
                "Experimental copy disabled",
                "These presets are Save Wizard search-pattern ports and may still make a save crash. "
                "Enable the experimental preset copy checkbox first, then save only to a new test file."
            )
            return
        try:
            preset_id, value, name = self._current_general_preset_request()
            plan, _payload = build_skyrim_preset_patch_plan(self.current_save, preset_id, value)
        except Exception as exc:
            QMessageBox.warning(self, "Preset preview failed", str(exc))
            return
        if not plan.writes:
            QMessageBox.information(self, "No preset changes", plan.to_text())
            if hasattr(self, "general_preset_output"):
                self.general_preset_output.setPlainText(plan.to_text())
            return
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save Preset Edited Copy",
            str(self.current_save.with_suffix(".preset-edited" + self.current_save.suffix)),
            "Skyrim Saves (*.ess *.ESS *.dat *.DAT);;All Files (*)",
        )
        if not target:
            return
        target_path = Path(target)
        if hasattr(self, "general_preset_output"):
            self.general_preset_output.setPlainText(plan.to_text())
        result = QMessageBox.question(
            self,
            "Save preset edited copy",
            f"Write the preset edits shown in the preset preview box to this test copy?\n\nTarget:\n{target_path}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            applied_plan = apply_skyrim_preset_patch(self.current_save, target_path, preset_id, value, allow_experimental=True)
            self.current_save = target_path
            self.current_doc = read_ess(target_path)
            self.path_edit.setText(str(target_path))
            self.inventory_dirty_counts.clear()
            self.inventory_pending_adds.clear()
            self._refresh_all_from_doc()
        except Exception as exc:
            QMessageBox.critical(self, "Preset copy failed", str(exc))
            return
        if hasattr(self, "general_preset_output"):
            self.general_preset_output.setPlainText(applied_plan.to_text())
        QMessageBox.information(self, "Preset copy saved", f"{name} edited copy written:\n{target_path}")

    # Backward-compatible names for older signal wiring/tests.
    def generate_general_preset_code(self, checked: bool = False, *, silent: bool = False) -> None:
        self.preview_general_preset_patch()

    def copy_general_preset_code(self) -> None:
        if hasattr(self, "general_preset_output"):
            QApplication.clipboard().setText(self.general_preset_output.toPlainText().strip())
            self.statusBar().showMessage("Copied current preset preview", 3000)

    def sync_common_inventory_values(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        try:
            # Do not blindly call refresh_inventory() here: that reloads from disk and
            # clears staged Player Inventory edits.  Sync should mirror the current
            # effective inventory state, including unsaved dirty counts.
            if self.current_inventory is None:
                self.refresh_inventory(silent=True)
            self._refresh_general_inventory_values()
            self._refresh_common_global_values()
            self._refresh_inventory_queue_label()
        except Exception as exc:
            QMessageBox.warning(self, "Common inventory sync failed", str(exc))
            return
        if hasattr(self, "common_inventory_status"):
            self.common_inventory_status.setText("Synced Gold / Lockpicks from Player Inventory and Dragon Souls from the live actor-value field.")
        self.statusBar().showMessage("Common values synced.", 4000)

    def _general_inventory_targets(self) -> list[tuple[str, str, str]]:
        return [
            ("gold", "Gold", "0000000F"),
            ("lockpicks", "Lockpicks", "0000000A"),
        ]

    def _common_global_targets(self) -> list[tuple[str, str, str]]:
        return [
            ("dragon_souls", "Dragon Souls", DRAGONS_ABSORBED_FORM_ID),
        ]

    def _common_global_value_changed(self, key: str) -> None:
        if getattr(self, "_syncing_common_global", False):
            return
        widgets = self.common_global_widgets.get(key) if hasattr(self, "common_global_widgets") else None
        if not widgets:
            return
        spin, status = widgets
        if not spin.isEnabled():
            return
        original = int(self.common_global_original.get(key, int(spin.value())))
        value = int(spin.value())
        if value == original:
            status.setText(f"Synced with live Dragon Souls field; saved value {value:,}.")
        else:
            status.setText(f"Pending Dragon Souls edit: {original:,} → {value:,}.")
        if hasattr(self, "common_inventory_status"):
            pending_globals = len(self._collect_common_global_updates()[0])
            self.common_inventory_status.setText(f"Common values synced. Pending Dragon Souls edits: {pending_globals}.")
        self._refresh_inventory_queue_label()

    def _safe_common_spin_value(self, raw_value: float | int | None, spin: QSpinBox) -> int | None:
        """Return a QSpinBox-safe integer, or None for invalid/sentinel save values."""
        if raw_value is None:
            return None
        try:
            value_float = float(raw_value)
        except Exception:
            return None
        if value_float != value_float or value_float in (float("inf"), float("-inf")):
            return None
        if value_float < spin.minimum() or value_float > spin.maximum():
            return None
        value = int(round(value_float))
        if value < spin.minimum() or value > spin.maximum():
            return None
        return value

    def _refresh_common_global_values(self) -> None:
        if not hasattr(self, "common_global_widgets"):
            return
        self._syncing_common_global = True
        found = 0
        try:
            for key, label, form_id in self._common_global_targets():
                widgets = self.common_global_widgets.get(key)
                if not widgets:
                    continue
                spin, status = widgets
                spin.blockSignals(True)
                try:
                    if str(form_id).upper() == DRAGONS_ABSORBED_FORM_ID:
                        hit = read_skyrim_dragon_souls(self.current_save) if self.current_save else None
                        if hit:
                            value = self._safe_common_spin_value(hit.value, spin)
                            if value is None:
                                spin.setEnabled(False)
                                spin.setValue(0)
                                self.common_global_original.pop(key, None)
                                status.setText(
                                    f"{label} candidate was found at ChangeForm {hit.change_form_refid_hex} +0x{hit.relative_offset:X}, "
                                    f"but decoded value {float(hit.value):g} is outside the safe editable range. "
                                    "This save likely has the Dragon Souls actor-value slot uninitialized; the editor will not guess/write it yet."
                                )
                            else:
                                found += 1
                                self.common_global_original[key] = value
                                spin.setEnabled(True)
                                spin.setValue(value)
                                status.setText(
                                    f"Synced with live Dragon Souls at payload 0x{hit.value_payload_offset:X} / virt 0x{hit.value_virtual_offset:X}; "
                                    f"ChangeForm {hit.change_form_refid_hex} +0x{hit.relative_offset:X}; saved value {value:,}."
                                )
                        else:
                            spin.setEnabled(False)
                            spin.setValue(0)
                            self.common_global_original.pop(key, None)
                            status.setText(f"{label} live actor-value field was not found in ChangeForm 400014 for this save.")
                    else:
                        hit = read_skyrim_global_variable(self.current_save, form_id, name=DRAGONS_ABSORBED_NAME) if self.current_save else None
                        if hit:
                            value = self._safe_common_spin_value(hit.value, spin)
                            if value is None:
                                spin.setEnabled(False)
                                spin.setValue(0)
                                self.common_global_original.pop(key, None)
                                status.setText(f"{label} was found, but decoded value {float(hit.value):g} is outside the safe editable range.")
                            else:
                                found += 1
                                self.common_global_original[key] = value
                                spin.setEnabled(True)
                                spin.setValue(value)
                                status.setText(
                                    f"Synced with {hit.name} at payload 0x{hit.value_payload_offset:X} / virt 0x{hit.value_virtual_offset:X}; "
                                    f"encoded {hit.encoded_refid_hex}; saved value {value:,}."
                                )
                        else:
                            spin.setEnabled(False)
                            spin.setValue(0)
                            self.common_global_original.pop(key, None)
                            status.setText(f"{label} global {form_id} was not found in Global Data type 3 for this save.")
                finally:
                    spin.blockSignals(False)
        finally:
            self._syncing_common_global = False
        if hasattr(self, "common_inventory_status") and self.current_save:
            # Do not overwrite a more specific inventory sync message when there are no global widgets yet.
            if found:
                self.common_inventory_status.setText("Common values synced from Player Inventory and live Dragon Souls.")

    def _collect_common_global_updates(self) -> tuple[dict[str, int], list[str]]:
        updates: dict[str, int] = {}
        lines: list[str] = []
        for key, label, form_id in self._common_global_targets():
            widgets = self.common_global_widgets.get(key) if hasattr(self, "common_global_widgets") else None
            if not widgets:
                continue
            spin, _status = widgets
            if not spin.isEnabled() or key not in self.common_global_original:
                continue
            new_value = int(spin.value())
            old_value = int(self.common_global_original[key])
            if new_value != old_value:
                updates[form_id] = new_value
                lines.append(f"- {label}: {old_value:,} → {new_value:,}")
        return updates, lines

    def _find_inventory_entry_by_form_id(self, form_id: str):
        target = form_id.strip().replace("0x", "").replace("0X", "").upper().zfill(8)[-8:]
        name_aliases = {
            "0000000F": ("gold",),
            "0000000A": ("lockpick", "lockpicks"),
        }.get(target, ())

        def collect_matches() -> list[object]:
            if not self.current_inventory:
                return []
            matches = [entry for entry in self.current_inventory.entries if str(entry.form_id).upper() == target]
            if not matches and name_aliases:
                for entry in self.current_inventory.entries:
                    hay = f"{getattr(entry, 'name', '')} {getattr(entry, 'form_id', '')}".casefold()
                    if any(alias in hay for alias in name_aliases):
                        matches.append(entry)
            return matches

        matches = collect_matches()
        if not matches and self.current_save:
            # Last-chance reparse without disturbing staged dirty counts. This helps
            # if the Common page is opened before the Inventory tab finishes loading.
            try:
                self.current_inventory = read_player_inventory(self.current_save)
                matches = collect_matches()
            except Exception:
                matches = []
        if not matches:
            return None

        # Prefer the exact editable row already being staged from either tab,
        # then the editable row with the largest saved count. This avoids syncing
        # to a zero-count duplicate Lockpick/Gold reference when a real stack is
        # also present in the same player ChangeForm.
        for entry in matches:
            if getattr(entry, 'editable', False) and int(entry.payload_offset) in self.inventory_dirty_counts:
                return entry
        editable_matches = [entry for entry in matches if getattr(entry, 'editable', False)]
        if editable_matches:
            return max(editable_matches, key=lambda entry: int(getattr(entry, 'displayed_count', 0)))
        return matches[0]

    def _inventory_effective_count(self, entry) -> int:
        payload_offset = int(entry.payload_offset)
        if payload_offset in self.inventory_dirty_counts:
            return int(self.inventory_dirty_counts[payload_offset])
        return int(entry.displayed_count)

    def _inventory_table_row_for_payload_offset(self, payload_offset: int) -> int | None:
        for row, off in self.inventory_row_offsets.items():
            if int(off) == int(payload_offset):
                return int(row)
        return None

    def _set_inventory_table_count_silent(self, payload_offset: int, value: int) -> None:
        row = self._inventory_table_row_for_payload_offset(payload_offset)
        if row is None or not hasattr(self, "inventory_table"):
            return
        count_item = self.inventory_table.item(row, self.INV_COL_COUNT)
        if count_item and count_item.text().replace(",", "").strip() != str(int(value)):
            old_loading = self._loading_inventory_table
            self._loading_inventory_table = True
            try:
                count_item.setText(str(int(value)))
            finally:
                self._loading_inventory_table = old_loading
        if self.inventory_table.currentRow() == row and hasattr(self, "inv_amount_spin"):
            self._updating_inventory_editor = True
            try:
                self.inv_amount_spin.setValue(int(value))
            finally:
                self._updating_inventory_editor = False

    def _general_inventory_value_changed(self, key: str) -> None:
        if getattr(self, "_syncing_general_inventory", False):
            return
        widgets = self.general_inventory_widgets.get(key) if hasattr(self, "general_inventory_widgets") else None
        if not widgets:
            return
        spin, status = widgets
        if not spin.isEnabled():
            return
        target_map = {target_key: (label, form_id) for target_key, label, form_id in self._general_inventory_targets()}
        label, form_id = target_map.get(key, (key, ""))
        entry = self._find_inventory_entry_by_form_id(form_id)
        if not entry or not entry.editable:
            return
        try:
            value = validate_inventory_amount(int(spin.value()))
        except Exception as exc:
            status.setText(str(exc))
            return
        payload_offset = int(entry.payload_offset)
        original_value = int(entry.displayed_count)
        if value == original_value:
            self.inventory_dirty_counts.pop(payload_offset, None)
        else:
            self.inventory_dirty_counts[payload_offset] = value
        self._set_inventory_table_count_silent(payload_offset, value)
        status.setText(f"Synced with Player Inventory row at payload 0x{payload_offset:X}; pending value {value:,}.")
        self._refresh_inventory_queue_label()
        self.refresh_coverage()
        if hasattr(self, "common_inventory_status"):
            pending = sum(1 for target_key, _label, _fid in self._general_inventory_targets()
                          if self.general_inventory_widgets.get(target_key)
                          and self.general_inventory_widgets[target_key][0].isEnabled()
                          and self._find_inventory_entry_by_form_id(_fid)
                          and int(self._find_inventory_entry_by_form_id(_fid).payload_offset) in self.inventory_dirty_counts)
            self.common_inventory_status.setText(f"Common values are synced with Player Inventory. Pending common edits: {pending}.")

    def _refresh_general_inventory_values(self) -> None:
        if not hasattr(self, "general_inventory_widgets"):
            return
        synced_count = 0
        enabled_count = 0
        self._syncing_general_inventory = True
        try:
            for key, label, form_id in self._general_inventory_targets():
                widgets = self.general_inventory_widgets.get(key)
                if not widgets:
                    continue
                spin, status = widgets
                entry = self._find_inventory_entry_by_form_id(form_id)
                spin.blockSignals(True)
                if entry and entry.editable:
                    synced_count += 1
                    enabled_count += 1
                    effective = self._inventory_effective_count(entry)
                    spin.setEnabled(True)
                    spin.setValue(int(effective))
                    self._set_inventory_table_count_silent(int(entry.payload_offset), int(effective))
                    pending = int(entry.payload_offset) in self.inventory_dirty_counts
                    if pending:
                        status.setText(f"Synced with Player Inventory row at payload 0x{entry.payload_offset:X}; pending value {effective:,}.")
                    else:
                        status.setText(f"Synced with Player Inventory row at payload 0x{entry.payload_offset:X}; saved value {effective:,}.")
                elif entry:
                    synced_count += 1
                    spin.setEnabled(False)
                    spin.setValue(int(entry.displayed_count))
                    status.setText("Found in Player Inventory, but this detected row is not editable yet.")
                else:
                    spin.setEnabled(False)
                    spin.setValue(0)
                    status.setText("Not present in this save as an editable Player Inventory row.")
                spin.blockSignals(False)
        finally:
            self._syncing_general_inventory = False
        if hasattr(self, "common_inventory_status"):
            if self.current_inventory:
                self.common_inventory_status.setText(f"Synced {synced_count}/{len(self._general_inventory_targets())} common values from Player Inventory; {enabled_count} editable.")
            else:
                self.common_inventory_status.setText("Open a save to sync Gold / Lockpicks / Dragon Souls.")

    def _collect_general_inventory_updates(self) -> tuple[dict[int, int], list[str]]:
        updates: dict[int, int] = {}
        lines: list[str] = []
        for key, label, form_id in self._general_inventory_targets():
            widgets = self.general_inventory_widgets.get(key) if hasattr(self, "general_inventory_widgets") else None
            if not widgets:
                continue
            spin, _status = widgets
            if not spin.isEnabled():
                continue
            entry = self._find_inventory_entry_by_form_id(form_id)
            if not entry or not entry.editable:
                continue
            new_value = validate_inventory_amount(int(spin.value()))
            saved_value = int(entry.displayed_count)
            current_value = self._inventory_effective_count(entry)
            if new_value != saved_value:
                updates[int(entry.payload_offset)] = new_value
                if current_value != saved_value:
                    lines.append(f"- {label}: saved {saved_value:,} → pending {new_value:,}")
                else:
                    lines.append(f"- {label}: {saved_value:,} → {new_value:,}")
        return updates, lines

    def _verify_inventory_updates_written(self, path: Path, expected_updates: dict[int, int]) -> None:
        if not expected_updates:
            return
        block = read_player_inventory(path)
        by_offset = {int(entry.payload_offset): entry for entry in block.entries}
        problems: list[str] = []
        for payload_offset, expected_value in expected_updates.items():
            entry = by_offset.get(int(payload_offset))
            if not entry:
                problems.append(f"payload 0x{int(payload_offset):X} was not found after saving")
                continue
            if int(entry.displayed_count) != int(expected_value):
                name = entry.name or entry.form_id
                problems.append(f"{name} at payload 0x{int(payload_offset):X} read back as {entry.displayed_count:,}, expected {int(expected_value):,}")
        if problems:
            raise ValueError("Inventory values were written, but verification failed:\n" + "\n".join(f"- {item}" for item in problems))

    def _verify_header_values_written(self, doc: EssDocument, expected: dict[str, object]) -> None:
        h = doc.header
        problems: list[str] = []
        if "player_name" in expected and h.player_name != str(expected["player_name"]):
            problems.append(f"Player Name read back as {h.player_name!r}, expected {expected['player_name']!r}")
        if "player_level" in expected and int(h.player_level) != int(expected["player_level"]):
            problems.append(f"Level read back as {h.player_level}, expected {expected['player_level']}")
        if "player_sex" in expected and int(h.player_sex) != int(expected["player_sex"]):
            problems.append(f"Sex read back as {h.player_sex}, expected {expected['player_sex']}")
        # Race header text is a fixed-size visual slot and may be too short for
        # a different editor ID. Live race readback is verified separately.
        if "current_exp" in expected and abs(float(h.player_current_exp) - float(expected["current_exp"])) > 0.01:
            problems.append(f"Current XP read back as {h.player_current_exp:.3f}, expected {float(expected['current_exp']):.3f}")
        if "needed_exp" in expected and abs(float(h.player_needed_exp) - float(expected["needed_exp"])) > 0.01:
            problems.append(f"Needed XP read back as {h.player_needed_exp:.3f}, expected {float(expected['needed_exp']):.3f}")
        if problems:
            raise ValueError("Player/header values were written, but verification failed:\n" + "\n".join(f"- {item}" for item in problems))


    def _verify_live_player_values_written(self, target: Path, expected: dict[str, object]) -> None:
        live_expected = {k: v for k, v in expected.items() if k in ("player_name", "player_level", "player_race")}
        if not live_expected:
            return
        try:
            live = read_live_player_fields(target)
        except Exception as exc:
            raise ValueError(f"Live player values were written, but ChangeForm 400007 could not be read back: {exc}") from exc
        problems: list[str] = []
        if "player_name" in live_expected and live.name != str(live_expected["player_name"]):
            problems.append(f"Live Player Name read back as {live.name!r}, expected {live_expected['player_name']!r}")
        if "player_level" in live_expected:
            if live.level is None:
                # Early-game saves may not have the mapped live level slot yet.
                # Header verification handles the displayed save-menu level; do
                # not block unrelated Player edits over an absent optional field.
                pass
            elif int(live.level) != int(live_expected["player_level"]):
                problems.append(f"Live Level read back as {live.level}, expected {live_expected['player_level']}")
        if "player_race" in live_expected:
            try:
                race_map = read_skyrim_race_mapping(target)
                active_id = race_map.active_race.editor_id if race_map.active_race else None
                if active_id != str(live_expected["player_race"]):
                    problems.append(f"Live Race read back as {active_id}, expected {live_expected['player_race']}")
            except Exception as exc:
                problems.append(f"Live Race could not be read back: {exc}")
        if problems:
            raise ValueError("Live player values were written, but verification failed:\n" + "\n".join(f"- {item}" for item in problems))

    def preview_player_header_edits(self) -> None:
        try:
            preview = self._header_values_preview()
        except Exception as exc:
            preview = f"Player preview failed: {exc}"
        if hasattr(self, "player_header_preview"):
            self.player_header_preview.setPlainText(preview)
        if hasattr(self, "general_preview"):
            self.general_preview.setPlainText(preview)

    def _write_player_header_to_target(self, target: Path, values: dict[str, object], xp_pool_value: float | None = None) -> EssDocument:
        if not self.current_save:
            raise ValueError("No save is loaded.")
        new_doc = self._write_general_edits_to_target(target, values, {})
        if xp_pool_value is not None:
            apply_skyrim_add_exp_patch(target, target, xp_pool_value)
            readback, _searches, _payload_size = read_skyrim_xp_pool(target)
            if abs(float(readback) - float(xp_pool_value)) > 0.01:
                raise ValueError(f"XP Pool read back as {readback:.3f}, expected {float(xp_pool_value):.3f}")
            new_doc = read_ess(target)
        self._verify_header_values_written(new_doc, values)
        return new_doc

    def save_player_header_edits(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        try:
            values = self._collect_header_values()
            xp_pool_value = self._collect_xp_pool_value()
            preview = self._header_values_preview()
        except Exception as exc:
            QMessageBox.warning(self, "Invalid player edit", str(exc))
            return
        if preview.startswith("No player changes"):
            QMessageBox.information(self, "No player changes", preview)
            if hasattr(self, "player_header_preview"):
                self.player_header_preview.setPlainText(preview)
            return
        if hasattr(self, "player_header_preview"):
            self.player_header_preview.setPlainText(preview)
        result = QMessageBox.question(
            self,
            "Apply player edits",
            "Apply the Player changes shown in the preview box?\n\nA backup will be created first.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            make_backup(self.current_save)
            new_doc = self._write_player_header_to_target(self.current_save, values, xp_pool_value)
        except Exception as exc:
            QMessageBox.critical(self, "Player save failed", str(exc))
            return
        self.current_doc = new_doc
        self._refresh_all_from_doc()
        if hasattr(self, "player_header_preview"):
            self.player_header_preview.setPlainText(self._header_values_preview())
        QMessageBox.information(self, "Saved", f"Player / XP Pool edits saved with a backup:\n{self.current_save}")

    def save_player_header_as(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        try:
            values = self._collect_header_values()
            xp_pool_value = self._collect_xp_pool_value()
            preview = self._header_values_preview()
        except Exception as exc:
            QMessageBox.warning(self, "Invalid player edit", str(exc))
            return
        if preview.startswith("No player changes"):
            QMessageBox.information(self, "No player changes", preview)
            if hasattr(self, "player_header_preview"):
                self.player_header_preview.setPlainText(preview)
            return
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save Player Edited Copy",
            str(self.current_save.with_suffix(".player-edited" + self.current_save.suffix)),
            "Skyrim Saves (*.ess *.ESS *.dat *.DAT);;All Files (*)",
        )
        if not target:
            return
        target_path = Path(target)
        if hasattr(self, "player_header_preview"):
            self.player_header_preview.setPlainText(preview)
        result = QMessageBox.question(
            self,
            "Save player edited copy",
            f"Write the Player header changes shown in the preview box to this copy?\n\nTarget:\n{target_path}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            new_doc = self._write_player_header_to_target(target_path, values, xp_pool_value)
        except Exception as exc:
            QMessageBox.critical(self, "Player copy save failed", str(exc))
            return
        self.current_save = target_path
        self.current_doc = new_doc
        self.path_edit.setText(str(target_path))
        self.inventory_dirty_counts.clear()
        self.inventory_pending_adds.clear()
        self._refresh_all_from_doc()
        if hasattr(self, "player_header_preview"):
            self.player_header_preview.setPlainText(self._header_values_preview())
        QMessageBox.information(self, "Saved", f"Player / XP Pool edited copy written:\n{target_path}")

    def _current_add_exp_amount(self) -> float:
        if not hasattr(self, "add_exp_amount_spin"):
            return 100_000.0
        return float(self.add_exp_amount_spin.value())

    def _current_xp_pool_plus_add_amount(self) -> tuple[float, float, float]:
        if not self.current_save:
            raise ValueError("No save is loaded.")
        current_pool, _searches, _payload_size = read_skyrim_xp_pool(self.current_save)
        add_amount = self._current_add_exp_amount()
        target_pool = float(current_pool) + float(add_amount)
        if target_pool < 0.0 or target_pool > 100_000_000.0:
            raise ValueError("Resulting XP Pool must be from 0 to 100,000,000.")
        return float(current_pool), float(add_amount), float(target_pool)

    def _build_add_exp_preview_text(self) -> str:
        if not self.current_save:
            return "No save loaded. Open a save first, then choose an add amount."
        current_pool, add_amount, target_pool = self._current_xp_pool_plus_add_amount()
        plan, _payload = build_skyrim_add_exp_patch_plan(self.current_save, target_pool)
        return (
            f"XP Pool add preview:\n"
            f"- Current XP Pool: {current_pool:g}\n"
            f"- Add Amount: {add_amount:g}\n"
            f"- New XP Pool: {target_pool:g}\n\n"
            + plan.to_text()
        )

    def _mark_add_exp_changed(self) -> None:
        if hasattr(self, "add_exp_preview"):
            self.add_exp_preview.setPlainText("Add amount changed. Click Preview XP Add to resolve the current XP Pool and review exact payload writes.")

    def preview_add_exp_command(self) -> None:
        try:
            preview = self._build_add_exp_preview_text()
        except Exception as exc:
            preview = f"XP Pool preview failed: {exc}"
        if hasattr(self, "add_exp_preview"):
            self.add_exp_preview.setPlainText(preview)

    def apply_add_exp_to_save(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        try:
            current_pool, amount, target_pool = self._current_xp_pool_plus_add_amount()
            plan, _payload = build_skyrim_add_exp_patch_plan(self.current_save, target_pool)
        except Exception as exc:
            QMessageBox.warning(self, "XP Pool preview failed", str(exc))
            return
        if hasattr(self, "add_exp_preview"):
            self.add_exp_preview.setPlainText(plan.to_text())
        result = QMessageBox.question(
            self,
            "Apply XP Pool change",
            f"Apply the XP Pool change shown in the Player preview box?\n\n{current_pool:g} + {amount:g} = {target_pool:g}\nA backup will be created first.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            make_backup(self.current_save)
            applied_plan = apply_skyrim_add_exp_patch(self.current_save, self.current_save, target_pool)
            self.current_doc = read_ess(self.current_save)
            self.inventory_dirty_counts.clear()
            self.inventory_pending_adds.clear()
            self._refresh_all_from_doc()
        except Exception as exc:
            QMessageBox.critical(self, "XP Pool apply failed", str(exc))
            return
        if hasattr(self, "add_exp_preview"):
            self.add_exp_preview.setPlainText(applied_plan.to_text())
        QMessageBox.information(self, "XP Pool applied", f"XP Pool was updated with a backup:\n{self.current_save}")

    def save_add_exp_as(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        try:
            current_pool, amount, target_pool = self._current_xp_pool_plus_add_amount()
            plan, _payload = build_skyrim_add_exp_patch_plan(self.current_save, target_pool)
        except Exception as exc:
            QMessageBox.warning(self, "XP Pool preview failed", str(exc))
            return
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save XP Pool Edited Copy",
            str(self.current_save.with_suffix(".xp-pool" + self.current_save.suffix)),
            "Skyrim Saves (*.ess *.ESS *.dat *.DAT);;All Files (*)",
        )
        if not target:
            return
        target_path = Path(target)
        if hasattr(self, "add_exp_preview"):
            self.add_exp_preview.setPlainText(plan.to_text())
        result = QMessageBox.question(
            self,
            "Save XP Pool edited copy",
            f"Write the XP Pool change shown in the Player preview box to this copy?\n\n{current_pool:g} + {amount:g} = {target_pool:g}\nTarget:\n{target_path}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            applied_plan = apply_skyrim_add_exp_patch(self.current_save, target_path, target_pool)
            self.current_save = target_path
            self.current_doc = read_ess(target_path)
            self.path_edit.setText(str(target_path))
            self.inventory_dirty_counts.clear()
            self.inventory_pending_adds.clear()
            self._refresh_all_from_doc()
        except Exception as exc:
            QMessageBox.critical(self, "XP Pool copy failed", str(exc))
            return
        if hasattr(self, "add_exp_preview"):
            self.add_exp_preview.setPlainText(applied_plan.to_text())
        QMessageBox.information(self, "XP Pool copy saved", f"XP Pool edited copy written:\n{target_path}")

    def _common_inventory_preview(self) -> tuple[str, dict[int, int], dict[str, int]]:
        if not self.current_save:
            return "No save loaded.", {}, {}
        inventory_updates, inventory_lines = self._collect_general_inventory_updates()
        global_updates, global_lines = self._collect_common_global_updates()
        lines = inventory_lines + global_lines
        if not lines:
            return "No common value changes are different from the loaded save.", inventory_updates, global_updates
        return "Common value edits preview:\n" + "\n".join(lines), inventory_updates, global_updates

    def preview_common_inventory_edits(self) -> None:
        try:
            preview, _inventory_updates, _global_updates = self._common_inventory_preview()
        except Exception as exc:
            preview = f"Common inventory preview failed: {exc}"
        if hasattr(self, "general_preview"):
            self.general_preview.setPlainText(preview)
        if hasattr(self, "common_inventory_status"):
            self.common_inventory_status.setText(preview.splitlines()[0])

    def save_common_inventory_edits(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        try:
            preview, updates, global_updates = self._common_inventory_preview()
        except Exception as exc:
            QMessageBox.warning(self, "Invalid common inventory edit", str(exc))
            return
        if not updates and not global_updates:
            QMessageBox.information(self, "No common value edits", preview)
            return
        result = QMessageBox.question(
            self,
            "Apply common inventory edits",
            f"This will create a backup, then write Gold / Lockpick / Dragon Souls edits into the loaded save:\n\n{self.current_save}\n\n{preview}\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            make_backup(self.current_save)
            if updates:
                patch_player_inventory_entry_counts(self.current_save, self.current_save, updates)
                self._verify_inventory_updates_written(self.current_save, updates)
            if global_updates:
                self._patch_common_global_updates(self.current_save, global_updates)
            self.current_doc = read_ess(self.current_save)
            self.inventory_dirty_counts.clear()
            self.inventory_pending_adds.clear()
            self._refresh_all_from_doc()
        except Exception as exc:
            QMessageBox.critical(self, "Common inventory save failed", str(exc))
            return
        if hasattr(self, "general_preview"):
            self.general_preview.setPlainText(preview)
        QMessageBox.information(self, "Saved", f"Common inventory edits saved with a backup:\n{self.current_save}")

    def save_common_inventory_as(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        try:
            preview, updates, global_updates = self._common_inventory_preview()
        except Exception as exc:
            QMessageBox.warning(self, "Invalid common inventory edit", str(exc))
            return
        if not updates and not global_updates:
            QMessageBox.information(self, "No common value edits", preview)
            return
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save Common Inventory Edited Copy",
            str(self.current_save.with_suffix(".common-inventory-edited" + self.current_save.suffix)),
            "Skyrim Saves (*.ess *.ESS *.dat *.DAT);;All Files (*)",
        )
        if not target:
            return
        target_path = Path(target)
        result = QMessageBox.question(
            self,
            "Save common inventory edited copy",
            f"This will write a new save copy with Gold / Lockpick / Dragon Souls edits:\n\nTarget:\n{target_path}\n\n{preview}\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            shutil.copy2(self.current_save, target_path)
            if updates:
                patch_player_inventory_entry_counts(target_path, target_path, updates)
                self._verify_inventory_updates_written(target_path, updates)
            if global_updates:
                self._patch_common_global_updates(target_path, global_updates)
            self.current_save = target_path
            self.current_doc = read_ess(target_path)
            self.path_edit.setText(str(target_path))
            self.inventory_dirty_counts.clear()
            self.inventory_pending_adds.clear()
            self._refresh_all_from_doc()
        except Exception as exc:
            QMessageBox.critical(self, "Common inventory copy failed", str(exc))
            return
        if hasattr(self, "general_preview"):
            self.general_preview.setPlainText(preview)
        QMessageBox.information(self, "Saved", f"Common inventory edited copy written:\n{target_path}")

    def _general_values_preview(self) -> tuple[str, dict[str, object], dict[int, int], dict[str, int]]:
        if not self.current_doc:
            return "No save loaded.", {}, {}, {}
        header_values = self._collect_header_values()
        header_preview = self._header_values_preview()
        inventory_updates, inventory_lines = self._collect_general_inventory_updates()
        common_global_updates, common_global_lines = self._collect_common_global_updates()
        lines = ["General edits preview:"]
        changed = False
        if not header_preview.startswith("No player changes"):
            for line in header_preview.splitlines()[1:]:
                lines.append(line)
                changed = True
        if inventory_lines:
            lines.extend(inventory_lines)
            changed = True
        if common_global_lines:
            lines.extend(common_global_lines)
            changed = True
        if not changed:
            return "No General changes are different from the loaded save.", header_values, inventory_updates, common_global_updates
        return "\n".join(lines), header_values, inventory_updates, common_global_updates

    def preview_general_edits(self) -> None:
        try:
            preview, _header_values, _inventory_updates, _common_globals = self._general_values_preview()
        except Exception as exc:
            preview = f"Preview failed: {exc}"
        if hasattr(self, "general_preview"):
            self.general_preview.setPlainText(preview)
        else:
            self.statusBar().showMessage(preview.splitlines()[0] if preview else "Preview complete", 8000)
            QMessageBox.information(self, "General preview", preview)

    def _write_general_edits_to_target(self, target: Path, header_values: dict[str, object], inventory_updates: dict[int, int], xp_pool_value: float | None = None, common_global_updates: dict[str, int] | None = None) -> EssDocument:
        if not self.current_save:
            raise ValueError("No save is loaded.")
        source = Path(self.current_save)
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        working = target
        try:
            if source.resolve() == target.resolve():
                temp_path = target.with_suffix(target.suffix + ".tmp-general-save-lab")
                if temp_path.exists():
                    temp_path.unlink()
                shutil.copy2(source, temp_path)
                working = temp_path
            else:
                shutil.copy2(source, target)
                working = target
            header_fixed_values = {k: v for k, v in header_values.items() if k != "player_race"}
            if header_fixed_values:
                patch_header_values(working, working, **header_fixed_values)
            if "player_race" in header_values:
                patch_skyrim_player_race(working, working, str(header_values["player_race"]), patch_header=True)
            live_kwargs = {k: v for k, v in header_values.items() if k in ("player_name", "player_level")}
            if live_kwargs:
                patch_live_player_values(working, working, **live_kwargs)
            if inventory_updates:
                patch_player_inventory_entry_counts(working, working, inventory_updates)
            if common_global_updates:
                self._patch_common_global_updates(working, common_global_updates)
            if xp_pool_value is not None:
                apply_skyrim_add_exp_patch(working, working, xp_pool_value)
            if temp_path is not None:
                shutil.move(str(temp_path), str(target))
                temp_path = None
            new_doc = read_ess(target)
            if header_values:
                self._verify_header_values_written(new_doc, header_values)
                self._verify_live_player_values_written(target, header_values)
            if inventory_updates:
                self._verify_inventory_updates_written(target, inventory_updates)
            if common_global_updates:
                self._verify_common_global_updates_written(target, common_global_updates)
            if xp_pool_value is not None:
                readback, _searches, _payload_size = read_skyrim_xp_pool(target)
                if abs(float(readback) - float(xp_pool_value)) > 0.01:
                    raise ValueError(f"XP Pool read back as {readback:.3f}, expected {float(xp_pool_value):.3f}")
            return new_doc
        finally:
            if temp_path is not None:
                try:
                    if temp_path.exists():
                        temp_path.unlink()
                except Exception:
                    pass

    def save_general_edits(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        try:
            preview, header_values, inventory_updates, common_global_updates = self._general_values_preview()
            xp_pool_value = self._collect_xp_pool_value()
        except Exception as exc:
            QMessageBox.warning(self, "Invalid general edit", str(exc))
            return
        if preview.startswith("No General changes"):
            QMessageBox.information(self, "No general edits", preview)
            return
        result = QMessageBox.question(
            self,
            "Save general edits",
            f"This will create a backup, then write these General edits into the loaded save:\n\n{self.current_save}\n\n{preview}\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            make_backup(self.current_save)
            new_doc = self._write_general_edits_to_target(self.current_save, header_values, inventory_updates, xp_pool_value, common_global_updates)
        except Exception as exc:
            QMessageBox.critical(self, "General save failed", str(exc))
            return
        self.current_doc = new_doc
        self.inventory_dirty_counts.clear()
        self.inventory_pending_adds.clear()
        self._refresh_all_from_doc()
        if hasattr(self, "general_preview"):
            self.general_preview.setPlainText(preview)
        QMessageBox.information(self, "Saved", f"General edits saved with a backup:\n{self.current_save}")

    def save_general_as(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        try:
            preview, header_values, inventory_updates, common_global_updates = self._general_values_preview()
            xp_pool_value = self._collect_xp_pool_value()
        except Exception as exc:
            QMessageBox.warning(self, "Invalid general edit", str(exc))
            return
        if preview.startswith("No General changes"):
            QMessageBox.information(self, "No general edits", preview)
            return
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save General Edited Copy",
            str(self.current_save.with_suffix(".general-edited" + self.current_save.suffix)),
            "Skyrim Saves (*.ess *.ESS *.dat *.DAT);;All Files (*)",
        )
        if not target:
            return
        target_path = Path(target)
        result = QMessageBox.question(
            self,
            "Save general edited copy",
            f"This will write General edits to a new save copy:\n\n{target_path}\n\n{preview}\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            make_backup(self.current_save)
            new_doc = self._write_general_edits_to_target(target_path, header_values, inventory_updates, xp_pool_value, common_global_updates)
        except Exception as exc:
            QMessageBox.critical(self, "General copy save failed", str(exc))
            return
        self.current_save = target_path
        self.current_doc = new_doc
        self.path_edit.setText(str(target_path))
        self.inventory_dirty_counts.clear()
        self.inventory_pending_adds.clear()
        self._refresh_all_from_doc()
        if hasattr(self, "general_preview"):
            self.general_preview.setPlainText(preview)
        QMessageBox.information(self, "Saved", f"General edited copy written:\n{target_path}")

    def _xp_pool_current_value(self) -> float | None:
        if not self.current_save:
            return None
        try:
            value, _searches, _payload_size = read_skyrim_xp_pool(self.current_save)
            return float(value)
        except Exception:
            return None

    def _xp_pool_requested_value(self) -> float | None:
        if not hasattr(self, "cur_exp_spin") or not self.cur_exp_spin.isEnabled():
            return None
        return float(self.cur_exp_spin.value())

    def _header_values_preview(self) -> str:
        if not self.current_doc:
            return "No save loaded."
        h = self.current_doc.header
        new_name = self.name_view.text() if hasattr(self, "name_view") else h.player_name
        new_level = self.level_spin.value() if hasattr(self, "level_spin") else h.player_level
        new_sex = self.sex_combo.currentIndex() if hasattr(self, "sex_combo") else h.player_sex
        new_race = self.race_combo.currentData() if hasattr(self, "race_combo") else h.player_race
        new_need_xp = self.need_exp_spin.value() if hasattr(self, "need_exp_spin") else h.player_needed_exp
        new_xp_pool = self._xp_pool_requested_value()
        current_xp_pool = self._xp_pool_current_value()
        lines = ["Player edits preview:"]
        changes = 0

        def add_change(label: str, old: object, new: object) -> None:
            nonlocal changes
            if old != new:
                lines.append(f"- {label}: {old} → {new}")
                changes += 1

        live = getattr(self, "_live_player_fields", None)
        live_name = live.name if live and live.name else h.player_name
        live_level = live.level if live and live.level is not None else h.player_level
        add_change("Player Name", live_name, new_name)
        add_change("Level", int(live_level), int(new_level))
        add_change("Sex", h.sex_text, "Female" if int(new_sex) == 1 else "Male")
        current_race = getattr(self, "_race_mapping", None).active_race.editor_id if getattr(self, "_race_mapping", None) and getattr(self, "_race_mapping", None).active_race else h.player_race
        if str(new_race) != str(current_race) or str(new_race) != str(h.player_race):
            try:
                new_race_label = race_from_editor_id(str(new_race)).display
            except Exception:
                new_race_label = str(new_race)
            lines.append(f"- Race: {current_race} → {new_race_label} ({new_race})")
            changes += 1
        if abs(float(h.player_needed_exp) - float(new_need_xp)) > 0.0005:
            lines.append(f"- Needed XP: {float(h.player_needed_exp):.3f} → {float(new_need_xp):.3f}")
            changes += 1
        if new_xp_pool is not None and current_xp_pool is not None and abs(float(current_xp_pool) - float(new_xp_pool)) > 0.0005:
            lines.append(f"- XP Pool: {float(current_xp_pool):.3f} → {float(new_xp_pool):.3f}")
            changes += 1
        elif new_xp_pool is None:
            lines.append("- XP Pool: unavailable for this save; it will not be written.")
        if changes == 0:
            return "No player changes are different from the loaded save."
        return "\n".join(lines)

    def _collect_header_values(self) -> dict[str, object]:
        if not self.current_doc:
            raise ValueError("No save is loaded.")
        h = self.current_doc.header
        player_name = self.name_view.text() if hasattr(self, "name_view") else h.player_name
        encoded_len = len(player_name.encode("utf-8"))
        if encoded_len > h.player_name_capacity:
            raise ValueError(
                f"Player name is too long for this save's fixed header slot: {encoded_len}/{h.player_name_capacity} bytes. "
                "The live ChangeForm can resize names, but the public-test UI keeps the save-header name within its existing slot."
            )
        live = getattr(self, "_live_player_fields", None)
        live_name = live.name if live and live.name else h.player_name
        live_level = live.level if live and live.level is not None else h.player_level
        values: dict[str, object] = {}
        race_id = self.race_combo.currentData() if hasattr(self, "race_combo") else h.player_race
        mapping = getattr(self, "_race_mapping", None)
        active_race_id = mapping.active_race.editor_id if mapping and mapping.active_race else h.player_race
        if race_id and (str(race_id) != str(active_race_id) or str(race_id) != str(h.player_race)):
            race = race_from_editor_id(str(race_id))
            values["player_race"] = race.editor_id
        if player_name != live_name or player_name != h.player_name:
            values["player_name"] = player_name
        if int(self.level_spin.value()) != int(live_level) or int(self.level_spin.value()) != int(h.player_level):
            values["player_level"] = int(self.level_spin.value())
        if int(self.sex_combo.currentIndex()) != int(h.player_sex):
            values["player_sex"] = int(self.sex_combo.currentIndex())
        if abs(float(self.need_exp_spin.value()) - float(h.player_needed_exp)) > 0.0005:
            values["needed_exp"] = float(self.need_exp_spin.value())
        return values

    def _collect_xp_pool_value(self) -> float | None:
        requested = self._xp_pool_requested_value()
        current = self._xp_pool_current_value()
        if requested is None or current is None:
            return None
        if abs(float(requested) - float(current)) <= 0.0005:
            return None
        if not 0.0 <= float(requested) <= 100_000_000.0:
            raise ValueError("XP Pool must be from 0 to 100,000,000.")
        return float(requested)

    def save_header_edits(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        try:
            values = self._collect_header_values()
        except Exception as exc:
            QMessageBox.warning(self, "Invalid header edit", str(exc))
            return
        preview = self._header_values_preview()
        if preview.startswith("No player changes"):
            QMessageBox.information(self, "No header edits", preview)
            return
        result = QMessageBox.question(
            self,
            "Save header edits",
            f"This will create a backup, then write header edits into the currently loaded save:\n\n{self.current_save}\n\n{preview}\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            make_backup(self.current_save)
            new_doc = self._write_general_edits_to_target(self.current_save, values, {})
        except Exception as exc:
            QMessageBox.critical(self, "Header save failed", str(exc))
            return
        self.current_doc = new_doc
        self._refresh_all_from_doc()
        self.statusBar().showMessage("Header edits saved with a backup.", 5000)
        QMessageBox.information(self, "Saved", f"Header edits saved with a backup:\n{self.current_save}")

    def create_backup(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        try:
            backup = make_backup(self.current_save)
        except OSError as exc:
            QMessageBox.critical(self, "Backup failed", str(exc))
            return
        self.refresh_backup_table()
        QMessageBox.information(self, "Backup created", f"Backup written:\n{backup}")

    def save_header_as(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        try:
            values = self._collect_header_values()
        except Exception as exc:
            QMessageBox.warning(self, "Invalid header edit", str(exc))
            return
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save Header Edited Copy",
            str(self.current_save.with_suffix(".header-edited" + self.current_save.suffix)),
            "Skyrim Saves (*.ess *.ESS *.dat *.DAT);;All Files (*)",
        )
        if not target:
            return
        target_path = Path(target)
        preview = self._header_values_preview()
        result = QMessageBox.question(
            self,
            "Save header edited copy",
            f"This will write the header fields to a new save copy:\n\n{target_path}\n\n{preview}\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            make_backup(self.current_save)
            new_doc = self._write_general_edits_to_target(target_path, values, {})
        except Exception as exc:
            QMessageBox.critical(self, "Header copy save failed", str(exc))
            return
        self.current_save = target_path
        self.current_doc = new_doc
        self.path_edit.setText(str(target_path))
        self._refresh_all_from_doc()
        QMessageBox.information(self, "Saved", f"Header edited copy written:\n{target_path}")

    def export_parsed_json(self) -> None:
        if not self.current_doc:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        target, _ = QFileDialog.getSaveFileName(self, "Export Parsed JSON", str(self.current_doc.path.with_suffix(".parsed.json")), "JSON (*.json)")
        if not target:
            return
        try:
            Path(target).write_text(self.current_doc.to_json(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        QMessageBox.information(self, "Exported", f"JSON written:\n{target}")

    def _load_default_database(self) -> None:
        sample = resource_path("database", "skyrim_ids_sample.csv")
        if sample.exists():
            try:
                self.db.load_csv(sample)
                powers = resource_path("database", "skyrim_powers_abilities_seed_rows.csv")
                if powers.exists():
                    self.db.merge_csv(powers)
                self.db_path_edit.setText(str(self.db.path or sample))
                self._refresh_database_categories()
                self.refresh_database_table()
                self.refresh_coverage()
                self._refresh_reference_manifest_label()
                self.refresh_magic_page(silent=True)
                self.run_reference_audit(silent=True)
            except Exception:
                pass


    def merge_database_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Merge ID CSV", "", "CSV Files (*.csv);;All Files (*)")
        if path:
            try:
                before = len(self.db.records)
                self.db.merge_csv(path)
            except Exception as exc:
                QMessageBox.critical(self, "Database merge failed", str(exc))
                return
            self.db_path_edit.setText(str(self.db.path or path))
            self._refresh_database_categories()
            self.refresh_database_table()
            self.refresh_inventory(silent=True)
            self.refresh_coverage()
            self._refresh_reference_manifest_label()
            self.refresh_magic_page(silent=True)
            QMessageBox.information(self, "Reference IDs merged", f"Merged {len(self.db.records)-before:,} new reference rows. Total: {len(self.db.records):,}")

    def _refresh_reference_manifest_label(self) -> None:
        if not hasattr(self, "reference_manifest_label"):
            return
        try:
            import json
            manifest_path = resource_path("database", "reference_manifest.json")
            data = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
            if data:
                self.reference_manifest_label.setText(
                    f"Built-in reference pack: {data.get('total_rows', len(self.db.records)):,} rows / "
                    f"{len(data.get('category_counts', {})):,} categories. "
                    f"Last ID pass added {data.get('added_rows_this_pass', 0):,} curated rows. "
                    f"Registered Fandom pages: {len(data.get('registered_source_pages', [])):,}."
                )
            else:
                self.reference_manifest_label.setText(f"Reference rows loaded: {len(self.db.records):,}")
        except Exception:
            self.reference_manifest_label.setText(f"Reference rows loaded: {len(self.db.records):,}")


    def harvest_fandom_pages(self) -> None:
        answer = QMessageBox.question(
            self,
            "Fetch linked Fandom pages?",
            "This will try to download and parse the linked Skyrim console-command pages, then merge/de-dupe the IDs into the active Reference IDs table. It needs internet access.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = harvest_all_source_pages()
            csv_text = records_to_csv_text(result.records)
            before = len(self.db.records)
            self.db.merge_csv_text(csv_text, label="Fandom linked pages")
        except Exception as exc:
            QMessageBox.critical(self, "Fandom harvest failed", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.db_path_edit.setText(str(self.db.path or "Merged + Fandom linked pages"))
        self._refresh_database_categories()
        self.refresh_database_table()
        self.refresh_inventory(silent=True)
        self.refresh_coverage()
        self._refresh_reference_manifest_label()
        self.refresh_magic_page(silent=True)
        added = len(self.db.records) - before
        extra = ""
        if result.errors:
            extra = "\n\nSome pages failed:\n" + "\n".join(result.errors[:8])
            if len(result.errors) > 8:
                extra += f"\n…plus {len(result.errors)-8} more."
        QMessageBox.information(
            self,
            "Fandom pages merged",
            f"Pages parsed: {result.pages_ok}\nPages failed: {result.pages_failed}\nExtracted rows before de-dupe: {len(result.records):,}\nNew rows added to active DB: {added:,}\nActive total: {len(self.db.records):,}" + extra,
        )


    def harvest_mutagen_formkeys(self) -> None:
        answer = QMessageBox.question(
            self,
            "Fetch Mutagen FormKeys?",
            "This will download generated SkyrimSE FormKey files from Mutagen.Bethesda.FormKeys and merge/de-dupe the parsed records. It can add thousands of editor-ID based records, but display names are generated from EditorIDs where no Fandom/xEdit name is present.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = harvest_mutagen_formkeys()
            csv_text = mutagen_records_to_csv_text(result.records)
            before = len(self.db.records)
            self.db.merge_csv_text(csv_text, label="Mutagen SkyrimSE FormKeys")
        except Exception as exc:
            QMessageBox.critical(self, "Mutagen import failed", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.db_path_edit.setText(str(self.db.path or "Merged + Mutagen FormKeys"))
        self._refresh_database_categories()
        self.refresh_database_table()
        self.refresh_inventory(silent=True)
        self.refresh_coverage()
        self._refresh_reference_manifest_label()
        self.refresh_magic_page(silent=True)
        self.run_reference_audit(silent=True)
        added = len(self.db.records) - before
        extra = ""
        if result.errors:
            extra = "\n\nSome FormKey files failed:\n" + "\n".join(result.errors[:8])
            if len(result.errors) > 8:
                extra += f"\n…plus {len(result.errors)-8} more."
        QMessageBox.information(
            self,
            "Mutagen FormKeys merged",
            f"Files parsed: {result.files_ok}\nFiles failed: {result.files_failed}\nExtracted rows before de-dupe: {len(result.records):,}\nNew rows added to active DB: {added:,}\nActive total: {len(self.db.records):,}" + extra,
        )

    def run_reference_audit(self, silent: bool = False) -> None:
        if not hasattr(self, "coverage_table"):
            return
        audit = audit_records(self.db.records)
        rows = audit_to_summary_rows(audit)
        self.coverage_table.setRowCount(len(rows))
        for row, (field, value) in enumerate(rows):
            self.coverage_table.setItem(row, 0, QTableWidgetItem(field))
            self.coverage_table.setItem(row, 1, QTableWidgetItem(value))
        self.coverage_table.resizeColumnsToContents()
        if not silent:
            weak = [p for p in audit.get("source_page_checklist", []) if p.get("status") in {"missing", "thin", "partial"}]
            preview = "\n".join(f"- {p['page']}: {p['local_rows_in_related_categories']} rows ({p['status']})" for p in weak[:12])
            QMessageBox.information(
                self,
                "Reference audit complete",
                f"Rows: {audit.get('total_rows', 0):,}\nUnique FormIDs/tokens: {audit.get('unique_form_ids', 0):,}\nMalformed rows: {len(audit.get('malformed_form_id_rows', [])):,}\nDuplicate FormIDs: {len(audit.get('duplicate_form_ids', {})):,}\nXX placeholders: {audit.get('xx_placeholder_rows', 0):,}" + ("\n\nLower-coverage source groups:\n" + preview if preview else ""),
            )

    def export_reference_audit_json(self) -> None:
        audit = audit_records(self.db.records)
        target, _ = QFileDialog.getSaveFileName(self, "Export Reference Audit JSON", "skyrim_reference_audit.json", "JSON (*.json)")
        if not target:
            return
        try:
            write_audit_json(target, audit)
        except OSError as exc:
            QMessageBox.critical(self, "Audit export failed", str(exc))
            return
        QMessageBox.information(self, "Audit exported", f"Audit written:\n{target}")

    def load_database_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load ID CSV", "", "CSV Files (*.csv);;All Files (*)")
        if path:
            try:
                self.db.load_csv(path)
            except Exception as exc:
                QMessageBox.critical(self, "Database load failed", str(exc))
                return
            self.db_path_edit.setText(path)
            self._refresh_database_categories()
            self.refresh_database_table()
            self.refresh_inventory(silent=True)
            self.refresh_coverage()
            self._refresh_reference_manifest_label()
            self.refresh_magic_page(silent=True)

    def load_database_sheet_url(self) -> None:
        url = self.db_sheet_url_edit.text().strip() if hasattr(self, "db_sheet_url_edit") else ""
        if not url:
            QMessageBox.information(self, "No Sheet URL", "Paste your Google Sheets URL first.")
            return
        try:
            self.db.load_google_sheet_url(url)
        except Exception as exc:
            QMessageBox.critical(self, "Sheet load failed", str(exc))
            return
        self.db_path_edit.setText("Google Sheet CSV")
        self._refresh_database_categories()
        self.refresh_database_table()
        self.refresh_inventory(silent=True)
        self.refresh_coverage()
        self._refresh_reference_manifest_label()
        self.refresh_magic_page(silent=True)
        QMessageBox.information(self, "Reference IDs loaded", f"Loaded {len(self.db.records):,} reference rows from the sheet.")

    def export_database_template(self) -> None:
        target, _ = QFileDialog.getSaveFileName(self, "Export CSV Template", "skyrim_ids_template.csv", "CSV Files (*.csv)")
        if not target:
            return
        try:
            export_template(target)
        except Exception as exc:
            QMessageBox.critical(self, "Template export failed", str(exc))
            return
        QMessageBox.information(self, "Template exported", f"Template written:\n{target}")

    def _refresh_database_categories(self) -> None:
        current = self.db_category.currentText()
        self.db_category.blockSignals(True)
        self.db_category.clear()
        self.db_category.addItem("All categories")
        for cat in self.db.categories():
            self.db_category.addItem(cat)
        idx = self.db_category.findText(current)
        if idx >= 0:
            self.db_category.setCurrentIndex(idx)
        self.db_category.blockSignals(False)

    def refresh_database_table(self) -> None:
        category = "" if self.db_category.currentIndex() <= 0 else self.db_category.currentText()
        records = self.db.search(self.db_search.text(), category)
        self.db_table.setRowCount(len(records))
        for row, rec in enumerate(records):
            resolved = self._resolve_record_form_id(rec.form_id, rec.source, rec.editor_id, rec.name, rec.notes)
            values = [rec.category, rec.editor_id, rec.form_id, resolved, rec.name, rec.value, rec.source, rec.notes]
            for col, value in enumerate(values):
                self.db_table.setItem(row, col, QTableWidgetItem(value))
        self.db_table.resizeColumnsToContents()
        self.refresh_inventory_database_table()


    def _selected_reference_values(self) -> tuple[str, str, str]:
        if not hasattr(self, "db_table"):
            return "", "", ""
        row = self.db_table.currentRow()
        if row < 0:
            return "", "", ""
        form_item = self.db_table.item(row, 2)
        resolved_item = self.db_table.item(row, 3)
        name_item = self.db_table.item(row, 4)
        form_id = form_item.text().strip() if form_item and form_item.text() else ""
        resolved = resolved_item.text().strip() if resolved_item and resolved_item.text().strip() else form_id
        name = name_item.text().strip() if name_item and name_item.text() else "Selected reference"
        return form_id, resolved, name

    def copy_selected_reference_id(self) -> None:
        form_id, resolved, _name = self._selected_reference_values()
        value = resolved or form_id
        if not value:
            QMessageBox.information(self, "No reference selected", "Select a Reference IDs row first.")
            return
        QApplication.clipboard().setText(value)
        self.statusBar().showMessage(f"Copied {value}", 2500)

    def copy_selected_additem_command(self) -> None:
        form_id, resolved, name = self._selected_reference_values()
        value = resolved or form_id
        if not value:
            QMessageBox.information(self, "No reference selected", "Select a Reference IDs row first.")
            return
        count = self.db_command_count.value() if hasattr(self, "db_command_count") else 1
        command = f"player.additem {value} {count}"
        QApplication.clipboard().setText(command)
        self.statusBar().showMessage(f"Copied additem command for {name}: {command}", 3500)

    def find_selected_reference_in_inventory(self) -> None:
        form_id, resolved, name = self._selected_reference_values()
        target = (resolved or form_id).strip().upper()
        if not target:
            QMessageBox.information(self, "No reference selected", "Select a Reference IDs row first.")
            return
        if not hasattr(self, "inventory_table"):
            return
        suffix = target[-6:] if len(target) >= 6 else target
        for row in range(self.inventory_table.rowCount()):
            item = self.inventory_table.item(row, self.INV_COL_ITEM)
            row_id = str(item.data(Qt.ItemDataRole.UserRole) or "").upper() if item else ""
            if row_id == target or (suffix and row_id.endswith(suffix)):
                self.side.setCurrentRow(2)
                self.inventory_active_category = "All"
                if hasattr(self, "inventory_tabs"):
                    self.inventory_tabs.setCurrentIndex(0)
                if hasattr(self, "inventory_filter_edit"):
                    self.inventory_filter_edit.clear()
                self.inventory_table.selectRow(row)
                self.inventory_table.scrollToItem(item)
                return
        QMessageBox.information(self, "Not in inventory", f"{name} is not currently present as an existing inventory row in this save.")

    def _database_selection_changed(self) -> None:
        items = self.db_table.selectedItems()
        if not items:
            return
        row = items[0].row()
        form_item = self.db_table.item(row, 2)
        resolved_item = self.db_table.item(row, 3)
        value_item = self.db_table.item(row, 5)
        source_item = self.db_table.item(row, 6)
        chosen = ""
        if form_item and form_item.text():
            chosen = form_item.text().strip()
            active = resolved_item.text().strip() if resolved_item and resolved_item.text().strip() else chosen
            self.scan_form_edit.setText(active)
            if hasattr(self, "formid_input"):
                self.formid_input.setText(chosen)
                if source_item and hasattr(self, "formid_plugin_combo"):
                    self._select_formid_plugin(source_item.text())
                self.analyze_form_id()
        elif value_item and value_item.text():
            chosen = value_item.text().strip()
            if hasattr(self, "formid_input"):
                self.formid_input.setText(chosen)
                self.analyze_form_id()
        if chosen and hasattr(self, "inv_form_edit"):
            self.inv_form_edit.setText(chosen)

    def _resolve_record_form_id(self, form_id: str, source: str, editor_id: str = "", name: str = "", notes: str = "") -> str:
        if not form_id:
            return ""
        plugins = self._active_plugin_list() if hasattr(self, "_active_plugin_list") else []
        hint = infer_plugin_name(source, editor_id, name, notes) or source
        resolved = resolve_xx_id(form_id, hint, plugins)
        norm = normalize_id(form_id)
        return "" if resolved == norm else resolved

    def _select_formid_plugin(self, plugin_name: str) -> None:
        if not hasattr(self, "formid_plugin_combo"):
            return
        wanted = plugin_name.strip().casefold()
        if not wanted:
            return
        for i in range(1, self.formid_plugin_combo.count()):
            data = self.formid_plugin_combo.itemData(i)
            text = self.formid_plugin_combo.itemText(i)
            if (data and str(data).casefold() == wanted) or wanted in text.casefold():
                self.formid_plugin_combo.setCurrentIndex(i)
                return

    def scan_current_save(self) -> None:
        if not self.current_save:
            QMessageBox.information(self, "No save loaded", "Open a save first.")
            return
        form_id = self.scan_form_edit.text().strip()
        if not form_id:
            QMessageBox.information(self, "Missing Form ID", "Enter a form ID first.")
            return
        try:
            hits = scan_form_id_detailed(self.current_save, form_id)
        except Exception as exc:
            QMessageBox.critical(self, "Scan failed", str(exc))
            return
        if not hits:
            self.scan_output.setPlainText(f"No hits for {form_id} in {self.current_save.name}.")
            return
        lines = [f"Found {len(hits)} hit(s) for {form_id} in {self.current_save.name}:", ""]
        for hit in hits[:500]:
            if hit.virtual_offset is None:
                lines.append(f"{hit.area:22} physical=0x{hit.offset:08X}  {hit.pattern}")
            else:
                lines.append(f"{hit.area:22} body=0x{hit.offset:08X} virtual=0x{hit.virtual_offset:08X}  {hit.pattern}")
        if len(hits) > 500:
            lines.append(f"... truncated {len(hits) - 500} more hit(s)")
        self.scan_output.setPlainText("\n".join(lines))


    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in (".ess", ".dat"):
                self.open_save(path)
                return

    def showEvent(self, event) -> None:  # type: ignore[override]
        self.setAcceptDrops(True)
        super().showEvent(event)
