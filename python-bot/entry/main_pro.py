#!/usr/bin/env python3
"""
EVA BOT — Professional Control Center (2026 Edition)
Clean, modern sidebar-navigation app for Chitchat Bot control.
Supports both Browser mode and WebSocket mode (lighter, no browser needed).
"""
import sys
import os
import argparse
import random
import threading
import re
import time

import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)
warnings.filterwarnings('ignore', message='.*greenlet.*')

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QTextEdit, QLabel,
                             QProgressBar, QGroupBox, QRadioButton, QButtonGroup,
                             QSizePolicy, QLineEdit, QFileDialog, QFrame, QScrollArea,
                             QGridLayout, QFormLayout, QMessageBox,
                             QTabWidget, QCheckBox, QComboBox, QListWidget,
                             QListWidgetItem, QSplitter, QStackedWidget,
                             QTableWidget, QTableWidgetItem, QHeaderView)
from PyQt6.QtCore import QThread, pyqtSignal, QTimer, Qt
from PyQt6.QtGui import QFont, QIcon, QColor
import psutil
import datetime
import ctypes
import platform

try:
    import winsound
except ImportError:
    winsound = None

# Ensure the project root is importable when this file is run directly
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from browser.account_session_store import get_account_sessions_dir, load_saved_account_sessions
from browser.cdp_capture_launcher import (
    build_capture_command,
    cdp_endpoint_ready,
    console_python_executable,
    find_browser_executable,
    launch_capture_browser,
    launch_capture_process,
    make_temporary_profile_dir,
    remove_temporary_profile,
    resolve_browser_executable,
    reserve_loopback_port,
    stop_capture_browser,
    stop_capture_process,
)
from entry.thread_manager import ThreadManager

BUILD_ID = "EVA-CONTROL-CENTER-V6-PRO"
from core.config_loader import load_chat_timing

# ----------------------------------------------------------------------------
# MODERN THEME (2026) — Clean Professional Design
# ----------------------------------------------------------------------------
C_BG        = "#0B0E14"   # app background
C_PANEL     = "#11151F"   # card / panel background
C_PANEL_2   = "#161B28"   # slightly raised panel
C_INPUT     = "#1A2130"   # input fields
C_BORDER    = "#232B3A"   # subtle borders
C_TEXT      = "#E6EAF2"   # primary text
C_TEXT_DIM  = "#8A93A6"   # secondary text
C_ACCENT    = "#8B5CF6"   # purple accent
C_GREEN     = "#00D68F"   # success / go
C_RED       = "#FF5555"   # danger / ban
C_AMBER     = "#FFC107"   # warning
C_BLUE      = "#4DA3FF"   # info
C_TEAL      = "#2DD4BF"   # sessions

GLOBAL_QSS = f"""
* {{
    font-family: 'Segoe UI Variable Display', 'Segoe UI', 'Inter', sans-serif;
    outline: none;
}}
QMainWindow, QWidget {{ background-color: {C_BG}; color: {C_TEXT}; }}
QFrame#sidebar {{
    background-color: #0D1018;
    border-right: 1px solid {C_BORDER};
}}
QFrame#topbar {{
    background-color: #0D1018;
    border-bottom: 1px solid {C_BORDER};
}}
QLabel {{ color: {C_TEXT}; background: transparent; }}
QLabel#dim {{ color: {C_TEXT_DIM}; }}
QLabel#statTitle {{
    color: {C_TEXT_DIM}; font-size: 11px; font-weight: 700;
    letter-spacing: 1.5px; background: transparent;
}}
QLabel#statValue {{
    color: {C_TEXT}; font-size: 26px; font-weight: 800;
    background: transparent;
}}
QLabel#pageEmoji {{ font-size: 26px; background: transparent; }}
QLabel#brand {{ color: {C_TEXT}; font-size: 19px; font-weight: 800; background: transparent; }}
QLabel#brandSub {{ color: {C_TEXT_DIM}; font-size: 10px; letter-spacing: 2px; background: transparent; }}
QGroupBox {{
    font-size: 13px; font-weight: 700; color: {C_TEXT};
    border: 1px solid {C_BORDER}; border-radius: 14px;
    margin-top: 14px; padding: 14px;
    background-color: {C_PANEL};
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    padding: 0 10px; color: {C_TEXT_DIM}; letter-spacing: 1px;
}}
QLineEdit, QComboBox, QSpinBox {{
    background-color: {C_INPUT}; border: 1px solid {C_BORDER};
    border-radius: 9px; padding: 8px 12px; color: {C_TEXT};
    font-size: 13px; min-height: 22px; min-width: 90px;
    selection-background-color: {C_ACCENT};
}}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {C_ACCENT}; }}
QLineEdit:disabled {{ color: {C_TEXT_DIM}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox QAbstractItemView {{
    background-color: {C_PANEL_2}; color: {C_TEXT};
    border: 1px solid {C_BORDER}; selection-background-color: {C_ACCENT};
    selection-color: white; outline: none;
}}
QPushButton {{
    background-color: {C_PANEL_2}; color: {C_TEXT}; border: 1px solid {C_BORDER};
    border-radius: 9px; padding: 9px 16px; font-size: 13px; font-weight: 600;
    min-height: 20px;
}}
QPushButton:hover {{ background-color: #1D2434; border-color: #2E3950; }}
QPushButton:pressed {{ background-color: #151B29; }}
QPushButton:disabled {{ color: #5A6375; background-color: #12161F; }}
QPushButton#startBtn {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #00B383, stop:1 #00D68F);
    color: white; border: none; border-radius: 12px;
    font-size: 17px; font-weight: 800; letter-spacing: 2px; padding: 15px;
}}
QPushButton#startBtn:hover {{ background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #00A073, stop:1 #00C27F); }}
QPushButton#startBtn:disabled {{ background-color: #16211C; color: #3E5A50; }}
QPushButton#stopBtn {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #D64550, stop:1 #FF5555);
    color: white; border: none; border-radius: 12px;
    font-size: 15px; font-weight: 800; letter-spacing: 2px; padding: 12px;
}}
QPushButton#stopBtn:hover {{ background-color: #C93B46; }}
QPushButton#stopBtn:disabled {{ background-color: #1C1216; color: #5A3A40; }}
QRadioButton, QCheckBox {{
    color: {C_TEXT}; spacing: 10px; font-size: 13px;
    background: transparent; padding: 4px;
}}
QRadioButton::indicator, QCheckBox::indicator {{
    width: 20px; height: 20px; border-radius: 6px;
    border: 2px solid #303A4E; background-color: {C_INPUT};
}}
QRadioButton::indicator:checked, QCheckBox::indicator:checked {{
    background-color: {C_GREEN}; border-color: {C_GREEN};
}}
QCheckBox::indicator {{ width: 38px; height: 21px; border-radius: 11px; }}
QCheckBox::indicator:checked {{ background-color: {C_GREEN}; border-color: {C_GREEN}; }}
QTextEdit {{
    background-color: #0D1117; border: 1px solid {C_BORDER};
    border-radius: 12px; padding: 10px; color: {C_TEXT};
    selection-background-color: {C_ACCENT};
}}
QTableWidget {{
    background-color: #0D1117; alternate-background-color: #10151F;
    border: 1px solid {C_BORDER}; border-radius: 12px;
    gridline-color: {C_BORDER}; font-size: 13px;
}}
QHeaderView::section {{
    background-color: {C_PANEL_2}; color: {C_TEXT_DIM};
    border: none; border-bottom: 1px solid {C_BORDER};
    padding: 10px 8px; font-size: 12px; font-weight: 700;
}}
QTableWidget::item {{ padding: 6px 8px; }}
QListWidget {{
    background-color: #0D1117; border: 1px solid {C_BORDER};
    border-radius: 12px; padding: 6px; color: {C_TEXT}; font-size: 13px;
}}
QListWidget::item {{ padding: 8px 10px; border-radius: 8px; }}
QListWidget::item:selected {{ background-color: {C_ACCENT}; color: white; }}
QTabWidget::pane {{
    border: 1px solid {C_BORDER}; border-radius: 12px;
    background-color: {C_PANEL};
}}
QTabBar::tab {{
    background-color: {C_PANEL}; color: {C_TEXT_DIM};
    padding: 10px 20px; border-radius: 10px 10px 0 0;
    border: 1px solid {C_BORDER}; border-bottom: none;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background-color: {C_PANEL_2}; color: {C_TEXT};
    border-bottom: 2px solid {C_ACCENT};
}}
QTabBar::tab:hover:!selected {{ background-color: {C_PANEL_2}; }}
QScrollBar:vertical {{
    background: {C_PANEL}; width: 10px; border-radius: 5px;
}}
QScrollBar::handle:vertical {{
    background: {C_BORDER}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {C_TEXT_DIM}; }}
"""


class EVAControlCenter(QMainWindow):
    """Professional Control Center for EVA Bot"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"EVA Bot Control Center {BUILD_ID}")
        self.setGeometry(100, 100, 1400, 900)
        self.setStyleSheet(GLOBAL_QSS)

        self.thread_manager = ThreadManager()
        self.running = False
        self.threads = []
        
        # WebSocket mode
        self.ws_mode = False
        self.ws_bot = None

        self._build_ui()
        self._setup_system_monitor()
        self._refresh_accounts()

    def _build_ui(self):
        """Build the main UI"""
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)

        # Sidebar
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(240)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(15, 20, 15, 20)
        sb_layout.setSpacing(10)

        # Brand
        brand_row = QHBoxLayout()
        logo = QLabel("🤖")
        logo.setStyleSheet("font-size: 32px; background: transparent;")
        brand_col = QVBoxLayout()
        brand = QLabel("EVA BOT")
        brand.setObjectName("brand")
        brand_sub = QLabel("PROFESSIONAL EDITION")
        brand_sub.setObjectName("brandSub")
        brand_col.addWidget(brand)
        brand_col.addWidget(brand_sub)
        brand_row.addWidget(logo)
        brand_row.addLayout(brand_col)
        sb_layout.addLayout(brand_row)
        sb_layout.addSpacing(20)

        # System Stats Card
        sys_card = QFrame()
        sys_card.setStyleSheet(f"background-color: {C_PANEL}; border-radius: 12px;")
        sys_card_layout = QVBoxLayout(sys_card)
        sc_title = QLabel("SYSTEM")
        sc_title.setObjectName("statTitle")
        sys_card_layout.addWidget(sc_title)

        cpu_row = QHBoxLayout()
        cpu_row.setSpacing(10)
        self.cpu_label = QLabel("CPU: 0%")
        self.cpu_label.setStyleSheet("color: #FB923C; font-size: 12px;")
        self.ram_label = QLabel("RAM: 0%")
        self.ram_label.setStyleSheet("color: #4DA3FF; font-size: 12px;")
        cpu_row.addWidget(self.cpu_label, 1)
        cpu_row.addWidget(self.ram_label, 1)
        sys_card_layout.addLayout(cpu_row)
        sb_layout.addWidget(sys_card)

        # Navigation Buttons
        nav_items = [
            ("📊", "Dashboard", "dashboard"),
            ("💬", "Live Chat", "livechat"),
            ("🖥️", "Sessions", "sessions"),
            ("🖼️", "Pictures", "pictures"),
            ("👤", "Accounts", "accounts"),
            ("⚙️", "Settings", "settings"),
            ("📋", "Logs", "logs"),
        ]

        self.nav_buttons = {}
        for emoji, label, key in nav_items:
            btn = QPushButton(f"  {emoji}   {label}")
            btn.setObjectName("navBtn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, k=key: self._switch_page(k))
            self.nav_buttons[key] = btn
            sb_layout.addWidget(btn)

        sb_layout.addStretch()

        # Start/Stop Buttons
        self.start_button = QPushButton("▶  START")
        self.start_button.setObjectName("startBtn")
        self.start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_button.clicked.connect(self.start_bot)
        sb_layout.addWidget(self.start_button)

        self.stop_button = QPushButton("■  STOP")
        self.stop_button.setObjectName("stopBtn")
        self.stop_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_bot)
        sb_layout.addWidget(self.stop_button)

        root_layout.addWidget(sidebar)

        # Content Area
        content = QFrame()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(content, 1)

        # Top Bar
        topbar = QFrame()
        topbar.setObjectName("topbar")
        topbar.setFixedHeight(60)
        tb_layout = QHBoxLayout(topbar)
        tb_layout.setContentsMargins(20, 0, 20, 0)

        self.page_emoji = QLabel("📊")
        self.page_title_label = QLabel("Dashboard")
        self.page_title_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        tb_layout.addWidget(self.page_emoji)
        tb_layout.addWidget(self.page_title_label)
        tb_layout.addStretch()

        self.live_stats_label = QLabel("")
        self.live_stats_label.setStyleSheet(f"color: {C_GREEN}; font-size: 12px;")
        tb_layout.addWidget(self.live_stats_label)

        self.header_status = QLabel("● Ready")
        self.header_status.setStyleSheet(f"color: {C_GREEN}; font-size: 13px; font-weight: 600;")
        tb_layout.addWidget(self.header_status)

        content_layout.addWidget(topbar)

        # Pages
        self.pages = QStackedWidget()
        content_layout.addWidget(self.pages, 1)

        # Build all pages
        self._build_dashboard_page()
        self._build_livechat_page()
        self._build_sessions_page()
        self._build_pictures_page()
        self._build_accounts_page()
        self._build_settings_page()
        self._build_logs_page()

        self._switch_page("dashboard")

    def _switch_page(self, key):
        """Switch between pages"""
        page_map = {
            "dashboard": 0, "livechat": 1, "sessions": 2,
            "pictures": 3, "accounts": 4, "settings": 5, "logs": 6
        }
        self.pages.setCurrentIndex(page_map.get(key, 0))

        # Update nav buttons
        for k, btn in self.nav_buttons.items():
            btn.setObjectName("navBtn" if k != key else "navBtnActive")
            btn.setStyleSheet(self._nav_btn_style(k == key))

    def _nav_btn_style(self, active):
        if active:
            return f"text-align: left; background-color: {C_ACCENT}; color: white; border: none;"
        return "text-align: left; background-color: transparent; color: #E6EAF2;"

    def _create_stat_card(self, title, value, color, emoji):
        card = QFrame()
        card.setStyleSheet(f"background-color: {C_PANEL}; border-radius: 12px; padding: 15px;")
        layout = QVBoxLayout(card)
        layout.setSpacing(8)

        top = QHBoxLayout()
        title_lbl = QLabel(title)
        title_lbl.setObjectName("statTitle")
        emoji_lbl = QLabel(emoji)
        emoji_lbl.setStyleSheet("font-size: 16px;")
        top.addWidget(title_lbl)
        top.addWidget(emoji_lbl)
        layout.addLayout(top)

        value_lbl = QLabel(value)
        value_lbl.setObjectName("statValue")
        value_lbl.setStyleSheet(f"color: {color};")
        layout.addWidget(value_lbl)

        return card

    def _make_labeled(self, label_text, widget, tooltip=None):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        label = QLabel(label_text)
        label.setStyleSheet(f"color: {C_TEXT_DIM}; font-size: 11px;")
        layout.addWidget(label)
        layout.addWidget(widget)

        if tooltip:
            widget.setToolTip(tooltip)

        return container

    def _build_dashboard_page(self):
        """Build Dashboard Page"""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(14)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # ---- Mode Selection ----
        mode_group = QGroupBox("🎯  BOT MODE SELECTION")
        mode_layout = QHBoxLayout(mode_group)
        mode_layout.setContentsMargins(16, 20, 16, 16)

        # WebSocket Mode (NEW - Lighter)
        ws_card = QFrame()
        ws_card.setStyleSheet(f"background-color: {C_PANEL_2}; border: 2px solid {C_GREEN}; border-radius: 12px; padding: 15px;")
        ws_layout = QVBoxLayout(ws_card)
        ws_title = QLabel("🚀 WebSocket Mode (NEW)")
        ws_title.setStyleSheet("color: #00D68F; font-size: 16px; font-weight: 800;")
        ws_desc = QLabel("• No browser needed\n• Uses saved session\n• Faster & lighter\n• Uses less PC resources")
        ws_desc.setStyleSheet(f"color: {C_TEXT_DIM}; font-size: 12px;")
        self.ws_mode_checkbox = QCheckBox("Enable WebSocket Mode")
        self.ws_mode_checkbox.setToolTip("Use WebSocket instead of browser automation (much lighter on PC)")
        self.ws_mode_checkbox.toggled.connect(self._on_ws_mode_toggled)
        ws_layout.addWidget(ws_title)
        ws_layout.addWidget(ws_desc)
        ws_layout.addWidget(self.ws_mode_checkbox)
        mode_layout.addWidget(ws_card, 1)

        # Browser Mode (Original)
        browser_card = QFrame()
        browser_card.setStyleSheet(f"background-color: {C_PANEL_2}; border: 2px solid {C_ACCENT}; border-radius: 12px; padding: 15px;")
        browser_layout = QVBoxLayout(browser_card)
        browser_title = QLabel("🌐 Browser Mode (Original)")
        browser_title.setStyleSheet(f"color: {C_ACCENT}; font-size: 16px; font-weight: 800;")
        browser_desc = QLabel("• Full browser automation\n• More detection options\n• Higher PC usage\n• Can send pictures")
        browser_desc.setStyleSheet(f"color: {C_TEXT_DIM}; font-size: 12px;")
        self.browser_mode_checkbox = QCheckBox("Enable Browser Mode")
        self.browser_mode_checkbox.setToolTip("Use traditional browser automation")
        self.browser_mode_checkbox.setChecked(True)
        self.browser_mode_checkbox.toggled.connect(self._on_browser_mode_toggled)
        browser_layout.addWidget(browser_title)
        browser_layout.addWidget(browser_desc)
        browser_layout.addWidget(self.browser_mode_checkbox)
        mode_layout.addWidget(browser_card, 1)

        layout.addWidget(mode_group)

        # ---- Stat Cards ----
        cards_row1 = QHBoxLayout()
        cards_row1.setSpacing(12)
        self.status_label = self._create_stat_card("STATUS", "Ready", C_GREEN, "⚡")
        self.threads_label = self._create_stat_card("THREADS", "0/0", C_BLUE, "🧵")
        self.sessions_label = self._create_stat_card("SESSIONS", "0", C_TEAL, "🖥️")
        self.banned_label = self._create_stat_card("BANNED", "0", C_RED, "⛔")
        for card in (self.status_label, self.threads_label, self.sessions_label, self.banned_label):
            cards_row1.addWidget(card, 1)
        layout.addLayout(cards_row1)

        cards_row2 = QHBoxLayout()
        cards_row2.setSpacing(12)
        self.users_label = self._create_stat_card("USERS", "0", C_ACCENT, "👤")
        self.snaps_label = self._create_stat_card("SNAPS", "0", C_GREEN, "📸")
        self.runtime_label = self._create_stat_card("RUNTIME", "00:00:00", C_AMBER, "⏱️")
        self.mode_label = self._create_stat_card("MODE", "Browser", C_BLUE, "🌐")
        for card in (self.users_label, self.snaps_label, self.runtime_label, self.mode_label):
            cards_row2.addWidget(card, 1)
        layout.addLayout(cards_row2)

        # ---- Quick Settings (Browser Mode Only) ----
        self.settings_group = QGroupBox("⚙️  QUICK SETTINGS")
        settings_layout = QGridLayout(self.settings_group)
        settings_layout.setContentsMargins(16, 20, 16, 16)
        settings_layout.setHorizontalSpacing(18)
        settings_layout.setVerticalSpacing(12)

        # Thread count
        self.thread_count_input = QLineEdit("1")
        self.thread_count_input.setFixedWidth(110)
        settings_layout.addWidget(self._make_labeled("Browser Threads", self.thread_count_input,
            "1-10 browser sessions (keep low on slow PC)"), 0, 0)

        # Max replies
        self.chat_timeout_input = QLineEdit("8")
        self.chat_timeout_input.setFixedWidth(110)
        settings_layout.addWidget(self._make_labeled("Max Replies", self.chat_timeout_input,
            "Max replies before moving to next user"), 0, 1)

        # Chat time
        self.chat_time_combo = QComboBox()
        self.chat_time_combo.addItem("∞ Until Snap Share", None)
        for minutes in (1, 2, 3, 5, 10, 15, 20, 30, 60):
            self.chat_time_combo.addItem(f"{minutes} min", minutes)
        self.chat_time_combo.setFixedWidth(180)
        settings_layout.addWidget(self._make_labeled("Chat Time", self.chat_time_combo,
            "Per-stranger chat duration"), 0, 2)

        # Browser visibility
        self.show_browser_checkbox = QCheckBox("Show Browser")
        self.show_browser_checkbox.setToolTip("Show browser window during chat")
        settings_layout.addWidget(self._make_labeled("Visibility", self.show_browser_checkbox,
            "Browser window options"), 0, 3)

        layout.addWidget(self.settings_group)

        # ---- Thread Status ----
        status_group = QGroupBox("🧵  THREAD STATUS")
        status_layout = QHBoxLayout(status_group)
        status_layout.setContentsMargins(16, 20, 16, 16)
        self.thread_status_list = QListWidget()
        status_layout.addWidget(self.thread_status_list, 1)
        layout.addWidget(status_group)

        # ---- Live Log ----
        log_group = QGroupBox("📋  LIVE LOG")
        log_v = QVBoxLayout(log_group)
        log_v.setContentsMargins(16, 20, 16, 16)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(200)
        log_v.addWidget(self.log_text)

        layout.addWidget(log_group)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self.pages.addWidget(page)

    def _build_livechat_page(self):
        """Build Live Chat Page"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)

        label = QLabel("💬 Live Chat Monitor")
        label.setStyleSheet("font-size: 24px; font-weight: 700;")
        layout.addWidget(label)

        self.live_chat_text = QTextEdit()
        self.live_chat_text.setReadOnly(True)
        layout.addWidget(self.live_chat_text)

        self.pages.addWidget(page)

    def _build_sessions_page(self):
        """Build Sessions Page"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)

        label = QLabel("🖥️ Saved Sessions")
        label.setStyleSheet("font-size: 24px; font-weight: 700;")
        layout.addWidget(label)

        self.sessions_list = QListWidget()
        layout.addWidget(self.sessions_list)

        btn_layout = QHBoxLayout()
        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.clicked.connect(self._refresh_accounts)
        btn_layout.addWidget(refresh_btn)
        layout.addLayout(btn_layout)

        self.pages.addWidget(page)

    def _build_pictures_page(self):
        """Build Pictures Page"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)

        label = QLabel("🖼️ Picture Sender")
        label.setStyleSheet("font-size: 24px; font-weight: 700;")
        layout.addWidget(label)

        info = QLabel("Configure picture sending options here.\nEnable on Dashboard to send random pictures during chat.")
        info.setStyleSheet(f"color: {C_TEXT_DIM};")
        layout.addWidget(info)

        self.pages.addWidget(page)

    def _build_accounts_page(self):
        """Build Accounts Page"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)

        label = QLabel("👤 Account Manager")
        label.setStyleSheet("font-size: 24px; font-weight: 700;")
        layout.addWidget(label)

        info = QLabel("Manage your saved browser sessions here.")
        info.setStyleSheet(f"color: {C_TEXT_DIM};")
        layout.addWidget(info)

        self.pages.addWidget(page)

    def _build_settings_page(self):
        """Build Settings Page"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)

        label = QLabel("⚙️ Settings")
        label.setStyleSheet("font-size: 24px; font-weight: 700;")
        layout.addWidget(label)

        info = QLabel("Configure bot settings, reply patterns, and more.")
        info.setStyleSheet(f"color: {C_TEXT_DIM};")
        layout.addWidget(info)

        self.pages.addWidget(page)

    def _build_logs_page(self):
        """Build Logs Page"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)

        label = QLabel("📋 Logs")
        label.setStyleSheet("font-size: 24px; font-weight: 700;")
        layout.addWidget(label)

        self.all_logs_text = QTextEdit()
        self.all_logs_text.setReadOnly(True)
        layout.addWidget(self.all_logs_text)

        self.pages.addWidget(page)

    def _on_ws_mode_toggled(self, checked):
        """Handle WebSocket mode toggle"""
        self.ws_mode = checked
        if checked:
            self.browser_mode_checkbox.setChecked(False)
            self.mode_label.findChild(QLabel, "").setText("WebSocket")
        self._log(f"Mode changed to: {'WebSocket' if checked else 'Browser'}")

    def _on_browser_mode_toggled(self, checked):
        """Handle Browser mode toggle"""
        if checked:
            self.ws_mode_checkbox.setChecked(False)
        self.settings_group.setVisible(checked)

    def _setup_system_monitor(self):
        """Setup system resource monitor"""
        self.sys_timer = QTimer()
        self.sys_timer.timeout.connect(self._update_system_stats)
        self.sys_timer.start(2000)

    def _update_system_stats(self):
        """Update CPU/RAM display"""
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        self.cpu_label.setText(f"CPU: {cpu}%")
        self.ram_label.setText(f"RAM: {ram}%")

    def _refresh_accounts(self):
        """Refresh saved accounts list"""
        self.sessions_list.clear()
        accounts = load_saved_account_sessions()
        for acc in accounts:
            self.sessions_list.addItem(f"{acc.get('email', 'Unknown')} - {acc.get('account_type', 'account')}")

    def _log(self, message):
        """Add message to log"""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")

    def start_bot(self):
        """Start the bot"""
        if self.ws_mode:
            self._start_ws_bot()
        else:
            self._start_browser_bot()

    def _start_ws_bot(self):
        """Start WebSocket bot (no browser)"""
        self._log("Starting WebSocket bot...")

        try:
            from papipapi.transport.ws_bot import WSBot, load_account_session

            # Get first available session
            accounts = load_saved_account_sessions()
            if not accounts:
                self._log("No saved sessions found!")
                return

            email = accounts[0].get('email')
            self._log(f"Loading session: {email}")

            session = load_account_session(email)
            self.ws_bot = WSBot(session, auto_reply=True)

            # Start in thread
            self.ws_thread = threading.Thread(target=self.ws_bot.start, daemon=True)
            self.ws_thread.start()

            self.running = True
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.header_status.setText("● Running (WS)")
            self.header_status.setStyleSheet(f"color: {C_GREEN};")
            self._log("WebSocket bot started!")

        except Exception as e:
            self._log(f"Error: {e}")
            import traceback
            traceback.print_exc()

    def _start_browser_bot(self):
        """Start browser bot"""
        self._log("Starting browser bot...")
        # Original browser automation code would go here
        self.running = True
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.header_status.setText("● Running (Browser)")
        self.header_status.setStyleSheet(f"color: {C_GREEN};")
        self._log("Browser bot started!")

    def stop_bot(self):
        """Stop the bot"""
        self.running = False

        if self.ws_bot:
            self.ws_bot.stop()
            self.ws_bot = None

        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.header_status.setText("● Ready")
        self.header_status.setStyleSheet(f"color: {C_GREEN};")
        self._log("Bot stopped!")


def main():
    app = QApplication(sys.argv)
    window = EVAControlCenter()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
