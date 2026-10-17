#!/usr/bin/env python3
"""
EVA Bot - Professional Dashboard (Fixed)
With Accounts File & Proxy Support
"""
import sys
import os
import argparse
import threading
import time

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QTextEdit, QLabel,
                             QGroupBox, QCheckBox, QComboBox, QListWidget,
                             QFrame, QLineEdit, QFileDialog)
from PyQt6.QtCore import QTimer, Qt
import psutil
import datetime

# Theme
C_BG = "#0B0E14"
C_PANEL = "#11151F"
C_PANEL_2 = "#161B28"
C_BORDER = "#232B3A"
C_TEXT = "#E6EAF2"
C_TEXT_DIM = "#8A93A6"
C_ACCENT = "#8B5CF6"
C_GREEN = "#00D68F"
C_RED = "#FF5555"
C_AMBER = "#FFC107"
C_BLUE = "#4DA3FF"

QSS = f"""
* {{ font-family: 'Segoe UI', sans-serif; }}
QMainWindow, QWidget {{ background-color: {C_BG}; color: {C_TEXT}; }}
QLabel {{ color: {C_TEXT}; background: transparent; }}
QGroupBox {{
    font-size: 13px; font-weight: 700; color: {C_TEXT};
    border: 1px solid {C_BORDER}; border-radius: 14px;
    margin-top: 14px; padding: 14px;
    background-color: {C_PANEL};
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    padding: 0 10px; color: {C_TEXT_DIM};
}}
QLineEdit, QComboBox {{
    background-color: #1A2130; border: 1px solid {C_BORDER};
    border-radius: 9px; padding: 8px; color: {C_TEXT};
}}
QPushButton {{
    background-color: {C_PANEL_2}; color: {C_TEXT}; border: 1px solid {C_BORDER};
    border-radius: 9px; padding: 9px 16px; font-size: 13px; font-weight: 600;
}}
QPushButton:hover {{ background-color: #1D2434; }}
QPushButton#startBtn {{
    background: linear-gradient(90deg, #00B383, #00D68F);
    color: white; border: none; border-radius: 12px;
    font-size: 17px; font-weight: 800; padding: 15px;
}}
QPushButton#stopBtn {{
    background: linear-gradient(90deg, #D64550, #FF5555);
    color: white; border: none; border-radius: 12px;
    font-size: 15px; font-weight: 800; padding: 12px;
}}
QCheckBox {{ color: {C_TEXT}; spacing: 10px; }}
QListWidget {{
    background-color: #0D1117; border: 1px solid {C_BORDER};
    border-radius: 12px; padding: 6px;
}}
QTextEdit {{
    background-color: #0D1117; border: 1px solid {C_BORDER};
    border-radius: 12px; padding: 10px; color: {C_TEXT};
}}
"""


class EVABotPro(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EVA Bot Pro")
        self.setGeometry(100, 100, 1100, 780)
        self.setStyleSheet(QSS)
        
        self.thread_manager = None
        self.ws_bot = None
        self.running = False
        
        self._build_ui()
        self._refresh_accounts()
        
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        
        # Sidebar
        sidebar = QFrame()
        sidebar.setFixedWidth(200)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(15, 20, 15, 20)
        
        brand = QLabel("🤖 EVA BOT")
        brand.setStyleSheet("font-size: 20px; font-weight: 800;")
        sb.addWidget(brand)
        sb.addSpacing(10)
        
        # Mode
        mode_group = QGroupBox("MODE")
        ml = QVBoxLayout(mode_group)
        self.ws_check = QCheckBox("🚀 WebSocket")
        self.browser_check = QCheckBox("🌐 Browser")
        self.browser_check.setChecked(True)
        self.ws_check.toggled.connect(lambda: self.browser_check.setChecked(not self.ws_check.isChecked()))
        ml.addWidget(self.ws_check)
        ml.addWidget(self.browser_check)
        sb.addWidget(mode_group)
        
        sb.addStretch()
        
        # Stats
        self.cpu_lbl = QLabel("CPU: 0%")
        self.ram_lbl = QLabel("RAM: 0%")
        self.cpu_lbl.setStyleSheet("color: #FB923C; font-size: 11px;")
        self.ram_lbl.setStyleSheet("color: #4DA3FF; font-size: 11px;")
        sb.addWidget(self.cpu_lbl)
        sb.addWidget(self.ram_lbl)
        
        self.start_btn = QPushButton("▶ START")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.clicked.connect(self.start_bot)
        sb.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("■ STOP")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_bot)
        sb.addWidget(self.stop_btn)
        
        layout.addWidget(sidebar)
        
        # Content
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(20, 20, 20, 20)
        
        header = QLabel("Dashboard")
        header.setStyleSheet("font-size: 22px; font-weight: 700;")
        cl.addWidget(header)
        
        self.status_lbl = QLabel("● Ready")
        self.status_lbl.setStyleSheet(f"color: {C_GREEN}; font-size: 14px;")
        cl.addWidget(self.status_lbl)
        cl.addSpacing(10)
        
        # Account Mode
        acc_mode_group = QGroupBox("Account Mode")
        aml = QHBoxLayout(acc_mode_group)
        
        self.login_radio = QCheckBox("Login (email:pass file)")
        self.login_radio.setChecked(True)
        self.restore_radio = QCheckBox("Restore (saved session)")
        
        self.login_radio.toggled.connect(lambda: self.restore_radio.setChecked(not self.login_radio.isChecked()))
        self.restore_radio.toggled.connect(lambda: self.login_radio.setChecked(not self.restore_radio.isChecked()))
        
        aml.addWidget(self.login_radio)
        aml.addWidget(self.restore_radio)
        cl.addWidget(acc_mode_group)
        
        # Accounts File
        file_group = QGroupBox("Accounts File")
        fgl = QHBoxLayout(file_group)
        
        self.accounts_file = QLineEdit()
        self.accounts_file.setPlaceholderText("email:password format - one per line")
        fgl.addWidget(QLabel("File:"))
        fgl.addWidget(self.accounts_file, 1)
        
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.browse_accounts)
        fgl.addWidget(browse_btn)
        cl.addWidget(file_group)
        
        # Saved Sessions
        session_group = QGroupBox("Saved Sessions")
        sgl = QHBoxLayout(session_group)
        
        self.acc_combo = QComboBox()
        sgl.addWidget(QLabel("Session:"))
        sgl.addWidget(self.acc_combo, 1)
        
        ref_btn = QPushButton("↻")
        ref_btn.setFixedWidth(40)
        ref_btn.clicked.connect(self._refresh_accounts)
        sgl.addWidget(ref_btn)
        cl.addWidget(session_group)
        
        # Proxy
        proxy_group = QGroupBox("Proxy (Optional)")
        pgl = QHBoxLayout(proxy_group)
        
        self.proxy_file = QLineEdit()
        self.proxy_file.setPlaceholderText("host:port:user:pass - one per line")
        pgl.addWidget(QLabel("File:"))
        pgl.addWidget(self.proxy_file, 1)
        
        proxy_browse = QPushButton("Browse")
        proxy_browse.clicked.connect(self.browse_proxy)
        pgl.addWidget(proxy_browse)
        cl.addWidget(proxy_group)
        
        # Settings
        settings_group = QGroupBox("Settings")
        sgl = QHBoxLayout(settings_group)
        
        sgl.addWidget(QLabel("Threads:"))
        self.threads_input = QComboBox()
        for i in range(1, 11):
            self.threads_input.addItem(str(i))
        sgl.addWidget(self.threads_input)
        
        sgl.addWidget(QLabel("Max Replies:"))
        self.max_replies = QComboBox()
        for i in range(1, 21):
            self.max_replies.addItem(str(i))
        self.max_replies.setCurrentText("8")
        sgl.addWidget(self.max_replies)
        
        self.show_browser = QCheckBox("Show Browser")
        sgl.addWidget(self.show_browser)
        
        self.headless = QCheckBox("Headless")
        self.headless.setChecked(True)
        sgl.addWidget(self.headless)
        
        cl.addWidget(settings_group)
        
        # Status
        status_group = QGroupBox("Thread Status")
        sl = QHBoxLayout(status_group)
        self.thread_list = QListWidget()
        sl.addWidget(self.thread_list, 1)
        cl.addWidget(status_group)
        
        # Log
        log_group = QGroupBox("Live Log")
        ll = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(150)
        ll.addWidget(self.log_text)
        cl.addWidget(log_group)
        
        layout.addWidget(content, 1)
        
        # Timer
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_stats)
        self.timer.start(2000)
        
    def browse_accounts(self):
        file, _ = QFileDialog.getOpenFileName(self, "Select Accounts File", "", "Text Files (*.txt)")
        if file:
            self.accounts_file.setText(file)
    
    def browse_proxy(self):
        file, _ = QFileDialog.getOpenFileName(self, "Select Proxy File", "", "Text Files (*.txt)")
        if file:
            self.proxy_file.setText(file)
    
    def _refresh_accounts(self):
        from browser.account_session_store import load_saved_account_sessions
        self.acc_combo.clear()
        sessions = load_saved_account_sessions()
        for s in sessions:
            self.acc_combo.addItem(s.get('email', 'Unknown'))
    
    def _log(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{ts}] {msg}")
    
    def _update_stats(self):
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        self.cpu_lbl.setText(f"CPU: {cpu}%")
        self.ram_lbl.setText(f"RAM: {ram}%")
        
        if self.thread_manager and self.thread_manager.is_running:
            self.thread_list.clear()
            for tid, status in self.thread_manager.active_threads.items():
                self.thread_list.addItem(f"Thread {tid}: {status}")
    
    def load_accounts_from_file(self, filepath):
        """Load accounts from email:password file"""
        accounts = []
        if not filepath or not os.path.exists(filepath):
            return accounts
        
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and ':' in line:
                    parts = line.split(':')
                    if len(parts) >= 2:
                        email = parts[0].strip()
                        password = ':'.join(parts[1:]).strip()
                        accounts.append({'email': email, 'password': password})
        return accounts
    
    def load_proxies_from_file(self, filepath):
        """Load proxies from file"""
        proxies = []
        if not filepath or not os.path.exists(filepath):
            return proxies
        
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    proxies.append(line)
        return proxies
    
    def start_bot(self):
        if self.ws_check.isChecked():
            self._start_ws()
        else:
            self._start_browser()
    
    def _start_ws(self):
        email = self.acc_combo.currentText()
        if not email:
            self._log("No account selected!")
            return
        
        self._log(f"Starting WebSocket for {email}...")
        
        try:
            from papipapi.transport.ws_bot import WSBot, load_account_session
            session = load_account_session(email)
            
            self.ws_bot = WSBot(session, auto_reply=True)
            
            thread = threading.Thread(target=self._run_ws, daemon=True)
            thread.start()
            
            self.running = True
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.status_lbl.setText("● Running (WS)")
            self._log("✅ WebSocket bot started!")
            
        except Exception as e:
            self._log(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
    
    def _run_ws(self):
        try:
            self.ws_bot.start()
        except Exception as e:
            self._log(f"WS Error: {e}")
    
    def _start_browser(self):
        self._log("Starting Browser mode...")
        
        try:
            from entry.thread_manager import ThreadManager
            from browser.account_session_store import load_saved_account_sessions
            
            # Determine account mode
            if self.login_radio.isChecked():
                # Login mode - use accounts file
                accounts_file = self.accounts_file.text()
                if not accounts_file:
                    self._log("Please select accounts file!")
                    return
                
                accounts = self.load_accounts_from_file(accounts_file)
                if not accounts:
                    self._log("No accounts loaded from file!")
                    return
                
                account_mode = "login"
                self._log(f"Loaded {len(accounts)} account(s) from file")
                
            else:
                # Restore mode - use saved session
                email = self.acc_combo.currentText()
                if not email:
                    self._log("Please select a saved session!")
                    return
                
                sessions = load_saved_account_sessions()
                account = None
                for s in sessions:
                    if s.get('email') == email:
                        account = s
                        break
                
                if not account:
                    self._log("Account not found!")
                    return
                
                accounts = [{
                    'email': email,
                    'session_dir': account.get('session_dir')
                }]
                account_mode = "restore"
                self._log(f"Using saved session: {email}")
            
            # Load proxy
            proxy_file = self.proxy_file.text()
            proxy_configs = None
            if proxy_file:
                proxy_configs = self.load_proxies_from_file(proxy_file)
                self._log(f"Loaded {len(proxy_configs)} proxy(ies)")
            
            # Settings
            thread_count = int(self.threads_input.currentText())
            max_replies = int(self.max_replies.currentText())
            headless = self.headless.isChecked()
            show_browser = self.show_browser.isChecked()
            
            self._log(f"Starting {thread_count} thread(s), max {max_replies} replies...")
            
            # Create ThreadManager
            self.thread_manager = ThreadManager(
                accounts=accounts,
                headless=headless,
                chat_timeout=max_replies,
                hide_after_login=not show_browser,
                account_mode=account_mode,
                proxy_configs=proxy_configs
            )
            
            # Connect signals
            self.thread_manager.thread_started.connect(lambda tid, msg: self._log(f"T{tid}: {msg}"))
            self.thread_manager.thread_log.connect(lambda tid, msg: self._log(f"T{tid}: {msg}"))
            self.thread_manager.chat_message.connect(lambda tid, who, text: self._log(f"T{tid} {who}: {text}"))
            self.thread_manager.thread_status.connect(lambda tid, s: self._log(f"T{tid}: {s}"))
            self.thread_manager.thread_finished.connect(lambda tid: self._log(f"Thread {tid} finished"))
            self.thread_manager.all_threads_finished.connect(lambda: self._log("All finished"))
            
            # Start
            self.thread_manager.start_threads(thread_count)
            
            self.running = True
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.status_lbl.setText("● Running (Browser)")
            self._log("✅ Browser bot started!")
            
        except Exception as e:
            self._log(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
    
    def stop_bot(self):
        self.running = False
        
        if self.ws_bot:
            try:
                self.ws_bot.stop()
            except:
                pass
            self.ws_bot = None
        
        if self.thread_manager:
            self.thread_manager.stop()
            self.thread_manager = None
        
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_lbl.setText("● Ready")
        self._log("⏹ Bot stopped!")


def main():
    app = QApplication(sys.argv)
    window = EVABotPro()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
