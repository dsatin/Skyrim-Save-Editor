from __future__ import annotations

# Shared QSS goals:
# - Avoid painting every QLabel/QWidget, which caused black label boxes in some Qt builds.
# - Remove native dotted focus rectangles.
# - Keep tab/category controls readable in both dark and light themes.

_SHARED = """
    * { outline: 0; }
    QLabel, QLabel#Title, QLabel#CardTitle, QLabel#Subtle, QLabel#FormHint, QLabel#FormLabel, QFrame QLabel, QWidget QLabel {
        background: transparent;
        background-color: transparent;
        border: 0px solid transparent;
        outline: 0;
        padding: 0;
    }
    QLabel:focus, QLabel#FormLabel:focus {
        background: transparent;
        background-color: transparent;
        outline: 0;
        border: 0px solid transparent;
    }
    QFrame, QWidget, QAbstractScrollArea, QHeaderView, QTabBar, QTabWidget { outline: 0; }
    QToolTip { border-radius: 8px; padding: 6px; }
    QMessageBox { border-radius: 12px; }
    QMessageBox QLabel { background: transparent; border: none; padding: 2px; }
    QMessageBox QPushButton { min-width: 96px; padding: 8px 14px; }
    QMenuBar { border: none; padding: 2px; }
    QMenuBar::item { background: transparent; padding: 6px 10px; border-radius: 6px; }
    QMenu { padding: 6px; border-radius: 10px; }
    QStatusBar, QStackedWidget, QWidget#AppRoot, QWidget#ContentPage { border: none; }
    QScrollArea, QScrollArea > QWidget, QAbstractScrollArea { border: none; background: transparent; }
    QWidget#GeneralTabPage, QWidget#GeneralTabContent, QWidget#GeneralTabViewport { background: transparent; border: none; }
    QTabWidget#GeneralTabs::pane { border: none; background: transparent; }

    QListWidget#SideRail { border: none; outline: 0; }
    QListWidget#SideRail::item { border: none; outline: 0; }
    QListWidget#SideRail::item:focus,
    QListWidget#SideRail::item:selected:active,
    QListWidget#SideRail::item:selected:!active { border: none; outline: 0; }

    QPushButton:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QTableWidget:focus,
    QTableView:focus, QListWidget:focus, QTabBar:focus {
        outline: 0;
    }
    QTableWidget::item:focus, QTableView::item:focus, QListWidget::item:focus { outline: 0; border: none; }
    QTableCornerButton::section { border: none; }
    QHeaderView::section { font-weight: 600; }

    QScrollBar:vertical { width: 12px; margin: 0; border: none; }
    QScrollBar::handle:vertical { min-height: 24px; border-radius: 6px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; border: none; }
    QScrollBar:horizontal { height: 12px; margin: 0; border: none; }
    QScrollBar::handle:horizontal { min-width: 24px; border-radius: 6px; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; border: none; }

    QTabWidget::pane { border: none; background: transparent; }
    QTabBar::tab {
        padding: 7px 12px;
        margin-right: 6px;
        border-radius: 9px;
        min-height: 18px;
    }
    QTabBar::tab:selected { font-weight: 600; }

    QTableWidget, QTreeWidget {
        border-radius: 12px;
    }
    QTableWidget::item, QTreeWidget::item {
        padding: 7px 10px;
        border-bottom: 1px solid transparent;
    }
    QTreeWidget::branch { background: transparent; }
"""

THEMES: dict[str, str] = {
    "Obsidian": _SHARED + """
        QWidget { color: #E9EDF3; font-family: Segoe UI, Arial; font-size: 10pt; }
        QMainWindow, QWidget#AppRoot, QWidget#ContentPage, QStackedWidget, QStatusBar { background: #121318; }
        QMessageBox, QDialog { background: #1A1D26; color: #E9EDF3; }
        QMessageBox QLabel { color: #E9EDF3; }
        QMenuBar { background: #0D0F14; color: #E9EDF3; }
        QMenuBar::item:selected { background: #232936; }
        QMenu { background: #161A22; color: #E9EDF3; border: 1px solid #2B3140; }
        QMenu::item { padding: 7px 26px 7px 12px; border-radius: 6px; }
        QMenu::item:selected { background: #2B3140; }

        QListWidget#SideRail { background: #0B0C10; padding: 10px; }
        QListWidget#SideRail::item { padding: 12px 14px; margin: 4px 2px; border-radius: 10px; color: #B7C0CD; }
        QListWidget#SideRail::item:hover { background: #1B202B; color: #E9EDF3; }
        QListWidget#SideRail::item:selected { background: #2F3950; color: white; }

        QLabel#Title { font-size: 20pt; font-weight: 700; color: white; }
        QLabel#CardTitle { font-size: 13pt; font-weight: 700; color: #F2F5F8; }
        QLabel#Subtle { color: #A8B2C2; }
        QLabel#FormHint { color: #A8B2C2; }

        QFrame#Card { background: #1A1D26; border: 1px solid #2B3140; border-radius: 14px; }
        QPushButton {
            background: #2B3140;
            border: 1px solid #3B4355;
            padding: 8px 12px;
            border-radius: 9px;
            color: #F2F5F8;
        }
        QPushButton:hover { background: #384155; }
        QPushButton:pressed { background: #242A38; }
        QPushButton:disabled { color: #697386; background: #20232C; }
        QPushButton:focus { border: 1px solid #5E7397; }

        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {
            background: #0F1117;
            border: 1px solid #303746;
            border-radius: 9px;
            padding: 7px;
            selection-background-color: #53637E;
        }
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {
            border: 1px solid #5E7397;
        }
        QLineEdit:read-only { color: #D6DCE6; background: #11151D; }
        QComboBox::drop-down { border: none; width: 28px; }

        QTableWidget, QTreeWidget {
            background: #0F1117;
            alternate-background-color: #171A22;
            gridline-color: #2A3040;
            border: 1px solid #303746;
            border-radius: 12px;
        }
        QTableWidget::item, QTreeWidget::item {
            background: transparent;
            color: #E9EDF3;
            min-height: 24px;
        }
        QTableWidget::item:alternate, QTreeWidget::item:alternate { background: #171A22; }
        QTableWidget::item:selected, QTreeWidget::item:selected { background: #2F3950; color: white; }
        QTreeWidget::branch:selected { background: #2F3950; }
        QHeaderView::section {
            background: #202431;
            color: #E9EDF3;
            padding: 8px;
            border: none;
            border-bottom: 1px solid #303746;
        }
        QTabBar::tab {
            background: #141821;
            border: 1px solid #2B3140;
            color: #C6CEDB;
        }
        QTabBar::tab:hover { background: #202735; color: #F2F5F8; }
        QTabBar::tab:selected { background: #2F3950; color: white; border: 1px solid #4A5C7C; }

        QScrollBar::handle { background: #303746; }
        QScrollBar::handle:hover { background: #3B4355; }
    """,
    "Nord": _SHARED + """
        QWidget { color: #2E3440; font-family: Segoe UI, Arial; font-size: 10pt; }
        QMainWindow, QWidget#AppRoot, QWidget#ContentPage, QStackedWidget, QStatusBar { background: #ECEFF4; }
        QMessageBox, QDialog { background: #F8F9FB; color: #2E3440; }
        QMessageBox QLabel { color: #2E3440; }
        QMenuBar { background: #E5E9F0; color: #2E3440; }
        QMenuBar::item:selected { background: #D8DEE9; }
        QMenu { background: #F8F9FB; color: #2E3440; border: 1px solid #C8D0DC; }
        QMenu::item { padding: 7px 26px 7px 12px; border-radius: 6px; }
        QMenu::item:selected { background: #D8DEE9; }

        QListWidget#SideRail { background: #D8DEE9; padding: 10px; }
        QListWidget#SideRail::item { padding: 12px 14px; margin: 4px 2px; border-radius: 10px; color: #3B4252; }
        QListWidget#SideRail::item:hover { background: #E5E9F0; }
        QListWidget#SideRail::item:selected { background: #4C6B92; color: white; }

        QLabel#Title { font-size: 20pt; font-weight: 700; color: #2E3440; }
        QLabel#CardTitle { font-size: 13pt; font-weight: 700; color: #2E3440; }
        QLabel#Subtle, QLabel#FormHint { color: #4C566A; }

        QFrame#Card { background: #F8F9FB; border: 1px solid #D8DEE9; border-radius: 14px; }
        QPushButton {
            background: #E5E9F0;
            border: 1px solid #C8D0DC;
            padding: 8px 12px;
            border-radius: 9px;
            color: #2E3440;
        }
        QPushButton:hover { background: #D8DEE9; }
        QPushButton:pressed { background: #CBD3DF; }
        QPushButton:focus { border: 1px solid #4C6B92; }

        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {
            background: white;
            border: 1px solid #C8D0DC;
            border-radius: 9px;
            padding: 7px;
            selection-background-color: #88A5CC;
        }
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {
            border: 1px solid #4C6B92;
        }
        QLineEdit:read-only { color: #3E4758; background: #F2F4F8; }
        QComboBox::drop-down { border: none; width: 28px; }

        QTableWidget, QTreeWidget {
            background: white;
            alternate-background-color: #F4F6F9;
            gridline-color: #D8DEE9;
            border: 1px solid #C8D0DC;
            border-radius: 12px;
        }
        QTableWidget::item, QTreeWidget::item { background: transparent; color: #2E3440; min-height: 24px; }
        QTableWidget::item:selected, QTreeWidget::item:selected { background: #4C6B92; color: white; }
        QHeaderView::section {
            background: #E5E9F0;
            color: #2E3440;
            padding: 8px;
            border: none;
            border-bottom: 1px solid #C8D0DC;
        }
        QTabBar::tab {
            background: #EEF2F7;
            border: 1px solid #D1D8E2;
            color: #3B4252;
        }
        QTabBar::tab:hover { background: #E0E7F0; }
        QTabBar::tab:selected { background: #4C6B92; color: white; border: 1px solid #4C6B92; }

        QScrollBar::handle { background: #C8D0DC; }
        QScrollBar::handle:hover { background: #B6C1CF; }
    """,
    "Dwemer": _SHARED + """
        QWidget { color: #F1E5C9; font-family: Segoe UI, Arial; font-size: 10pt; }
        QMainWindow, QWidget#AppRoot, QWidget#ContentPage, QStackedWidget, QStatusBar { background: #17130D; }
        QMessageBox, QDialog { background: #211A11; color: #F1E5C9; }
        QMessageBox QLabel { color: #F1E5C9; }
        QMenuBar { background: #0E0B08; color: #F1E5C9; }
        QMenuBar::item:selected { background: #2A2014; }
        QMenu { background: #211A11; color: #F1E5C9; border: 1px solid #4A3920; }
        QMenu::item { padding: 7px 26px 7px 12px; border-radius: 6px; }
        QMenu::item:selected { background: #3A2A18; }

        QListWidget#SideRail { background: #0E0B08; padding: 10px; }
        QListWidget#SideRail::item { padding: 12px 14px; margin: 4px 2px; border-radius: 10px; color: #CBB88C; }
        QListWidget#SideRail::item:hover { background: #2A2014; color: #FFE7B2; }
        QListWidget#SideRail::item:selected { background: #8A6A37; color: #FFF4D1; }

        QLabel#Title { font-size: 20pt; font-weight: 700; color: #FFE7B2; }
        QLabel#CardTitle { font-size: 13pt; font-weight: 700; color: #FFE7B2; }
        QLabel#Subtle, QLabel#FormHint { color: #C9B791; }

        QFrame#Card { background: #211A11; border: 1px solid #4A3920; border-radius: 14px; }
        QPushButton {
            background: #3A2A18;
            border: 1px solid #6D5228;
            padding: 8px 12px;
            border-radius: 9px;
            color: #FFE7B2;
        }
        QPushButton:hover { background: #4A3920; }
        QPushButton:pressed { background: #2A2014; }
        QPushButton:focus { border: 1px solid #C09A4A; }

        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {
            background: #100D09;
            border: 1px solid #4A3920;
            border-radius: 9px;
            padding: 7px;
            selection-background-color: #6D5228;
        }
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {
            border: 1px solid #C09A4A;
        }
        QLineEdit:read-only { color: #E8D8B5; background: #18120C; }
        QComboBox::drop-down { border: none; width: 28px; }

        QTableWidget, QTreeWidget {
            background: #100D09;
            alternate-background-color: #1B150E;
            gridline-color: #4A3920;
            border: 1px solid #4A3920;
            border-radius: 12px;
        }
        QTableWidget::item, QTreeWidget::item { background: transparent; color: #F1E5C9; min-height: 24px; }
        QTableWidget::item:selected, QTreeWidget::item:selected { background: #7A5B2E; color: white; }
        QHeaderView::section {
            background: #2A2014;
            color: #FFE7B2;
            padding: 8px;
            border: none;
            border-bottom: 1px solid #4A3920;
        }
        QTabBar::tab {
            background: #19130D;
            border: 1px solid #4A3920;
            color: #D7C397;
        }
        QTabBar::tab:hover { background: #2B2116; color: #FFE7B2; }
        QTabBar::tab:selected { background: #7A5B2E; color: #FFF7DD; border: 1px solid #C09A4A; }

        QScrollBar::handle { background: #4A3920; }
        QScrollBar::handle:hover { background: #6D5228; }
    """,

    "Nightingale": _SHARED + """
        QWidget { color: #E8EAF6; font-family: Segoe UI, Arial; font-size: 10pt; }
        QMainWindow, QWidget#AppRoot, QWidget#ContentPage, QStackedWidget, QStatusBar { background: #0B0D14; }
        QMessageBox, QDialog { background: #151827; color: #E8EAF6; }
        QMessageBox QLabel { color: #E8EAF6; }
        QMenuBar { background: #070911; color: #E8EAF6; }
        QMenuBar::item:selected { background: #20243A; }
        QMenu { background: #151827; color: #E8EAF6; border: 1px solid #303652; }
        QMenu::item { padding: 7px 26px 7px 12px; border-radius: 6px; }
        QMenu::item:selected { background: #272E50; }

        QListWidget#SideRail { background: #070911; padding: 10px; }
        QListWidget#SideRail::item { padding: 12px 14px; margin: 4px 2px; border-radius: 10px; color: #AAB2D5; }
        QListWidget#SideRail::item:hover { background: #171B2C; color: #F2F4FF; }
        QListWidget#SideRail::item:selected { background: #33406F; color: white; }

        QLabel#Title { font-size: 20pt; font-weight: 700; color: #F2F4FF; }
        QLabel#CardTitle { font-size: 13pt; font-weight: 700; color: #F2F4FF; }
        QLabel#Subtle, QLabel#FormHint { color: #AAB2D5; }

        QFrame#Card { background: #151827; border: 1px solid #303652; border-radius: 14px; }
        QPushButton {
            background: #242A45;
            border: 1px solid #43507D;
            padding: 8px 12px;
            border-radius: 9px;
            color: #F2F4FF;
        }
        QPushButton:hover { background: #30385F; }
        QPushButton:pressed { background: #1A1F35; }
        QPushButton:disabled { color: #697193; background: #1A1D2C; }
        QPushButton:focus { border: 1px solid #7C8FE0; }

        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {
            background: #0D101B;
            border: 1px solid #333B5B;
            border-radius: 9px;
            padding: 7px;
            selection-background-color: #4B5FA8;
        }
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {
            border: 1px solid #7C8FE0;
        }
        QLineEdit:read-only { color: #D8DCF2; background: #101424; }
        QComboBox::drop-down { border: none; width: 28px; }

        QTableWidget, QTreeWidget {
            background: #0D101B;
            alternate-background-color: #14182A;
            gridline-color: #303652;
            border: 1px solid #333B5B;
            border-radius: 12px;
        }
        QTableWidget::item, QTreeWidget::item { background: transparent; color: #E8EAF6; min-height: 24px; }
        QTableWidget::item:selected, QTreeWidget::item:selected { background: #33406F; color: white; }
        QHeaderView::section {
            background: #20243A;
            color: #E8EAF6;
            padding: 8px;
            border: none;
            border-bottom: 1px solid #333B5B;
        }
        QTabBar::tab {
            background: #111522;
            border: 1px solid #303652;
            color: #C5CBE8;
        }
        QTabBar::tab:hover { background: #202641; color: #F2F4FF; }
        QTabBar::tab:selected { background: #33406F; color: white; border: 1px solid #7C8FE0; }

        QScrollBar::handle { background: #303652; }
        QScrollBar::handle:hover { background: #43507D; }
    """,
    "Daedric": _SHARED + """
        QWidget { color: #F5E8E8; font-family: Segoe UI, Arial; font-size: 10pt; }
        QMainWindow, QWidget#AppRoot, QWidget#ContentPage, QStackedWidget, QStatusBar { background: #100B0C; }
        QMessageBox, QDialog { background: #1B1113; color: #F5E8E8; }
        QMessageBox QLabel { color: #F5E8E8; }
        QMenuBar { background: #080506; color: #F5E8E8; }
        QMenuBar::item:selected { background: #2A171A; }
        QMenu { background: #1B1113; color: #F5E8E8; border: 1px solid #4E242A; }
        QMenu::item { padding: 7px 26px 7px 12px; border-radius: 6px; }
        QMenu::item:selected { background: #4A1E26; }

        QListWidget#SideRail { background: #080506; padding: 10px; }
        QListWidget#SideRail::item { padding: 12px 14px; margin: 4px 2px; border-radius: 10px; color: #D6AEB4; }
        QListWidget#SideRail::item:hover { background: #241316; color: #FFEDEF; }
        QListWidget#SideRail::item:selected { background: #7A2430; color: white; }

        QLabel#Title { font-size: 20pt; font-weight: 700; color: #FFEDEF; }
        QLabel#CardTitle { font-size: 13pt; font-weight: 700; color: #FFEDEF; }
        QLabel#Subtle, QLabel#FormHint { color: #D6AEB4; }

        QFrame#Card { background: #1B1113; border: 1px solid #4E242A; border-radius: 14px; }
        QPushButton {
            background: #3A1A20;
            border: 1px solid #7A2D38;
            padding: 8px 12px;
            border-radius: 9px;
            color: #FFEDEF;
        }
        QPushButton:hover { background: #4E242A; }
        QPushButton:pressed { background: #2A1418; }
        QPushButton:disabled { color: #7E6165; background: #24181A; }
        QPushButton:focus { border: 1px solid #D14A5A; }

        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {
            background: #0D0809;
            border: 1px solid #4E242A;
            border-radius: 9px;
            padding: 7px;
            selection-background-color: #7A2430;
        }
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {
            border: 1px solid #D14A5A;
        }
        QLineEdit:read-only { color: #EBD1D5; background: #140D0F; }
        QComboBox::drop-down { border: none; width: 28px; }

        QTableWidget, QTreeWidget {
            background: #0D0809;
            alternate-background-color: #171012;
            gridline-color: #4E242A;
            border: 1px solid #4E242A;
            border-radius: 12px;
        }
        QTableWidget::item, QTreeWidget::item { background: transparent; color: #FFEDEF; min-height: 24px; }
        QTableWidget::item:selected, QTreeWidget::item:selected { background: #7A2430; color: white; }
        QHeaderView::section {
            background: #2A171A;
            color: #FFEDEF;
            padding: 8px;
            border: none;
            border-bottom: 1px solid #4E242A;
        }
        QTabBar::tab {
            background: #160D0F;
            border: 1px solid #4E242A;
            color: #D6AEB4;
        }
        QTabBar::tab:hover { background: #2A171A; color: #FFEDEF; }
        QTabBar::tab:selected { background: #7A2430; color: white; border: 1px solid #D14A5A; }

        QScrollBar::handle { background: #4E242A; }
        QScrollBar::handle:hover { background: #7A2D38; }
    """,
    "Frostfall": _SHARED + """
        QWidget { color: #EAF6FA; font-family: Segoe UI, Arial; font-size: 10pt; }
        QMainWindow, QWidget#AppRoot, QWidget#ContentPage, QStackedWidget, QStatusBar { background: #0D151A; }
        QMessageBox, QDialog { background: #152229; color: #EAF6FA; }
        QMessageBox QLabel { color: #EAF6FA; }
        QMenuBar { background: #081014; color: #EAF6FA; }
        QMenuBar::item:selected { background: #20323B; }
        QMenu { background: #152229; color: #EAF6FA; border: 1px solid #2E4A56; }
        QMenu::item { padding: 7px 26px 7px 12px; border-radius: 6px; }
        QMenu::item:selected { background: #2D5362; }

        QListWidget#SideRail { background: #081014; padding: 10px; }
        QListWidget#SideRail::item { padding: 12px 14px; margin: 4px 2px; border-radius: 10px; color: #ACCCD5; }
        QListWidget#SideRail::item:hover { background: #17272E; color: #F3FCFF; }
        QListWidget#SideRail::item:selected { background: #2B6578; color: white; }

        QLabel#Title { font-size: 20pt; font-weight: 700; color: #F3FCFF; }
        QLabel#CardTitle { font-size: 13pt; font-weight: 700; color: #F3FCFF; }
        QLabel#Subtle, QLabel#FormHint { color: #ACCCD5; }

        QFrame#Card { background: #152229; border: 1px solid #2E4A56; border-radius: 14px; }
        QPushButton {
            background: #253D48;
            border: 1px solid #3F6B7C;
            padding: 8px 12px;
            border-radius: 9px;
            color: #F3FCFF;
        }
        QPushButton:hover { background: #315464; }
        QPushButton:pressed { background: #1B2D35; }
        QPushButton:disabled { color: #6F8790; background: #1B2A31; }
        QPushButton:focus { border: 1px solid #7FCBE3; }

        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {
            background: #0A1115;
            border: 1px solid #2E4A56;
            border-radius: 9px;
            padding: 7px;
            selection-background-color: #2B6578;
        }
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {
            border: 1px solid #7FCBE3;
        }
        QLineEdit:read-only { color: #D7EDF3; background: #0F1A20; }
        QComboBox::drop-down { border: none; width: 28px; }

        QTableWidget, QTreeWidget {
            background: #0A1115;
            alternate-background-color: #111D23;
            gridline-color: #2E4A56;
            border: 1px solid #2E4A56;
            border-radius: 12px;
        }
        QTableWidget::item, QTreeWidget::item { background: transparent; color: #EAF6FA; min-height: 24px; }
        QTableWidget::item:selected, QTreeWidget::item:selected { background: #2B6578; color: white; }
        QHeaderView::section {
            background: #20323B;
            color: #EAF6FA;
            padding: 8px;
            border: none;
            border-bottom: 1px solid #2E4A56;
        }
        QTabBar::tab {
            background: #101A20;
            border: 1px solid #2E4A56;
            color: #BFE0E8;
        }
        QTabBar::tab:hover { background: #20323B; color: #F3FCFF; }
        QTabBar::tab:selected { background: #2B6578; color: white; border: 1px solid #7FCBE3; }

        QScrollBar::handle { background: #2E4A56; }
        QScrollBar::handle:hover { background: #3F6B7C; }
    """,
    "Whiterun": _SHARED + """
        QWidget { color: #342C21; font-family: Segoe UI, Arial; font-size: 10pt; }
        QMainWindow, QWidget#AppRoot, QWidget#ContentPage, QStackedWidget, QStatusBar { background: #E8DDC7; }
        QMessageBox, QDialog { background: #F5EBD7; color: #342C21; }
        QMessageBox QLabel { color: #342C21; }
        QMenuBar { background: #D8C7A8; color: #342C21; }
        QMenuBar::item:selected { background: #CBB791; }
        QMenu { background: #F5EBD7; color: #342C21; border: 1px solid #BCA57C; }
        QMenu::item { padding: 7px 26px 7px 12px; border-radius: 6px; }
        QMenu::item:selected { background: #D8C7A8; }

        QListWidget#SideRail { background: #D8C7A8; padding: 10px; }
        QListWidget#SideRail::item { padding: 12px 14px; margin: 4px 2px; border-radius: 10px; color: #4B3F2E; }
        QListWidget#SideRail::item:hover { background: #E3D4BA; }
        QListWidget#SideRail::item:selected { background: #886E45; color: white; }

        QLabel#Title { font-size: 20pt; font-weight: 700; color: #342C21; }
        QLabel#CardTitle { font-size: 13pt; font-weight: 700; color: #342C21; }
        QLabel#Subtle, QLabel#FormHint { color: #6E5F48; }

        QFrame#Card { background: #F5EBD7; border: 1px solid #CDBA96; border-radius: 14px; }
        QPushButton {
            background: #D8C7A8;
            border: 1px solid #BCA57C;
            padding: 8px 12px;
            border-radius: 9px;
            color: #342C21;
        }
        QPushButton:hover { background: #CBB791; }
        QPushButton:pressed { background: #BCA57C; }
        QPushButton:focus { border: 1px solid #886E45; }

        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {
            background: #FFF8EA;
            border: 1px solid #BCA57C;
            border-radius: 9px;
            padding: 7px;
            selection-background-color: #B89761;
        }
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {
            border: 1px solid #886E45;
        }
        QLineEdit:read-only { color: #4B3F2E; background: #EFE2CA; }
        QComboBox::drop-down { border: none; width: 28px; }

        QTableWidget, QTreeWidget {
            background: #FFF8EA;
            alternate-background-color: #F2E6CF;
            gridline-color: #CDBA96;
            border: 1px solid #BCA57C;
            border-radius: 12px;
        }
        QTableWidget::item, QTreeWidget::item { background: transparent; color: #342C21; min-height: 24px; }
        QTableWidget::item:selected, QTreeWidget::item:selected { background: #886E45; color: white; }
        QHeaderView::section {
            background: #D8C7A8;
            color: #342C21;
            padding: 8px;
            border: none;
            border-bottom: 1px solid #BCA57C;
        }
        QTabBar::tab {
            background: #EEE1C9;
            border: 1px solid #CDBA96;
            color: #4B3F2E;
        }
        QTabBar::tab:hover { background: #E3D4BA; }
        QTabBar::tab:selected { background: #886E45; color: white; border: 1px solid #886E45; }

        QScrollBar::handle { background: #BCA57C; }
        QScrollBar::handle:hover { background: #A78F66; }
    """,
}
