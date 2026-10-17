#!/usr/bin/env python3
"""
EVA Bot - WebSocket Mode
Browserless chat automation using WebSocket + HTTP API

This module provides a lightweight alternative to browser automation.
It uses saved account sessions to connect directly via WebSocket.

Usage:
    from transport.ws_bot import WSBot
    bot = WSBot(session_data)
    bot.start()
"""

import json
import time
import random
import threading
import requests
from pathlib import Path

# Try to import socket.io, install if needed
try:
    import socketio
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-socketio", "requests"])
    import socketio

# ============== CONFIG ==============
API_BASE = "https://api.chitchat.gg"
WS_URL = "wss://api.chitchat.gg/socket.io"
ORIGIN = "https://app.chitchat.gg"

# Default reply patterns (can be overridden)
DEFAULT_REPLIES = [
    "Hey there! 👋",
    "Hi! How are you?",
    "Hello! Nice to meet you!",
    "Hey! What's up?",
    "Hi there! 😊"
]


# ============== SESSION LOADER ==============
def load_account_session(email: str, project_root: str = None):
    """Load saved account session from account_sessions folder
    
    Extracts release token from browser storage_state.json (localStorage)
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent
    
    sessions_dir = project_root / "account_sessions"
    
    # Find session file by email hash
    import hashlib
    email_hash = hashlib.sha256(email.strip().lower().encode()).hexdigest()[:24]
    
    # Try both naming conventions
    possible_dirs = [
        sessions_dir / f"account_{email_hash}",
        sessions_dir / email_hash
    ]
    
    session_dir = None
    for d in possible_dirs:
        if d.exists():
            session_dir = d
            break
    
    if session_dir is None:
        raise FileNotFoundError(f"No saved session for {email}")
    
    # Load metadata
    metadata_file = session_dir / "metadata.json"
    with open(metadata_file, 'r') as f:
        metadata = json.load(f)
    
    # Load storage state (contains cookies + localStorage)
    storage_file = session_dir / "storage_state.json"
    if not storage_file.exists():
        raise FileNotFoundError(f"No storage_state.json in session")
    
    with open(storage_file, 'r') as f:
        storage = json.load(f)
    
    # Extract release token from localStorage
    release = None
    cookies = {}
    
    if 'cookies' in storage:
        for cookie in storage['cookies']:
            name = cookie.get('name')
            value = cookie.get('value')
            if name:
                cookies[name] = value
    
    # Look for release in localStorage (usually in origins)
    if 'origins' in storage:
        for origin, data in storage['origins'].items():
            if 'localStorage' in data:
                ls = data['localStorage']
                if 'release' in ls:
                    release = ls['release']
                    break
                # Also try different keys
                for key in ls:
                    if 'release' in key.lower():
                        release = ls[key]
                        break
    
    if not release:
        # Try to find in cookies
        for name, value in cookies.items():
            if 'release' in name.lower():
                release = value
                break
    
    if not release:
        raise ValueError(f"Could not find release token in session for {email}")
    
    # Get user_id from metadata or storage
    user_id = metadata.get('user_id')
    
    # Try to get user_id from storage if not in metadata
    if not user_id and 'origins' in storage:
        for origin, data in storage.get('origins', {}).items():
            if 'localStorage' in data:
                ls = data['localStorage']
                # Look for user id patterns
                for key, value in ls.items():
                    if 'user' in key.lower() and 'id' in key.lower():
                        user_id = value
                        break
    
    return {
        'email': metadata.get('email', email),
        'release': release,
        'user_id': user_id,
        'cookies': cookies,
        'storage': storage
    }


def list_available_sessions(project_root: str = None):
    """List all available saved sessions"""
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent
    
    sessions_dir = project_root / "account_sessions"
    
    if not sessions_dir.exists():
        return []
    
    sessions = []
    for f in sessions_dir.glob("*.json"):
        try:
            with open(f, 'r') as fp:
                data = json.load(fp)
                sessions.append({
                    'email': data.get('email', 'unknown'),
                    'file': str(f),
                    'user_id': data.get('user_id'),
                    'created': data.get('created_at')
                })
        except:
            pass
    
    return sessions


# ============== SESSION HANDLER ==============
class WSSession:
    """WebSocket session manager"""
    
    def __init__(self, session_data: dict):
        self.release = session_data.get('release')
        self.user_id = session_data.get('user_id')
        self.email = session_data.get('email')
        
        # Build cookies
        cookies = session_data.get('cookies', {})
        self.cookie_string = "; ".join([f"{k}={v}" for k,v in cookies.items()])
        
        self.conversation_id = None
        self.connected = False
        
    def get_headers(self, extra=None):
        headers = {
            "Origin": ORIGIN,
            "Referer": ORIGIN,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": self.cookie_string
        }
        if self.release:
            headers["Authorization"] = f"default:{self.release}"
        if extra:
            headers.update(extra)
        return headers


# ============== HTTP API CLIENT ==============
class WSAPI:
    """HTTP API client for Chitchat"""
    
    def __init__(self, session: WSSession):
        self.session = session
        
    def start_matching(self) -> dict:
        """POST /match - Find a new chat partner"""
        url = f"{API_BASE}/match"
        response = requests.post(url, headers=self.session.get_headers())
        
        if response.status_code == 201:
            data = response.json()
            if "match" in data and "conversation" in data["match"]:
                conv_id = data["match"]["conversation"]["id"]
                self.session.conversation_id = conv_id
                return data
        return {}
    
    def send_message(self, content: str) -> bool:
        """POST /messages - Send a message"""
        if not self.session.conversation_id:
            return False
            
        url = f"{API_BASE}/users/me/conversations/{self.session.conversation_id}/messages"
        
        response = requests.post(
            url,
            headers=self.session.get_headers(),
            data={"content": content}
        )
        
        return response.status_code == 201
    
    def send_typing(self):
        """POST /typing - Send typing indicator"""
        if not self.session.conversation_id:
            return
            
        url = f"{API_BASE}/users/me/conversations/{self.session.conversation_id}/typing"
        requests.post(url, headers=self.session.get_headers())
    
    def skip_match(self) -> bool:
        """PATCH /match/disconnect - Skip current chat"""
        url = f"{API_BASE}/match/disconnect"
        response = requests.patch(url, headers=self.session.get_headers())
        
        if response.status_code in [200, 204]:
            self.session.conversation_id = None
            return True
        return False
    
    def get_my_profile(self) -> dict:
        """GET /users/me - Get current user info"""
        url = f"{API_BASE}/users/me"
        response = requests.get(url, headers=self.session.get_headers())
        
        if response.status_code == 200:
            return response.json()
        return {}


# ============== WEBSOCKET CLIENT ==============
class WSBot:
    """
    WebSocket Bot for Chitchat
    
    This bot runs WITHOUT browser. It uses:
    - WebSocket for receiving messages, match updates
    - HTTP API for sending messages, starting matches
    """
    
    def __init__(
        self,
        session_data: dict,
        auto_reply: bool = True,
        reply_patterns: list = None,
        on_message=None,
        on_match=None,
        on_disconnect=None
    ):
        """
        Initialize WebSocket Bot
        
        Args:
            session_data: Dict with release, user_id, cookies
            auto_reply: Enable auto-reply to messages
            reply_patterns: List of reply strings (or use default)
            on_message: Callback(message_dict)
            on_match: Callback(match_dict)
            on_disconnect: Callback()
        """
        self.session = WSSession(session_data)
        self.api = WSAPI(self.session)
        
        self.auto_reply = auto_reply
        self.reply_patterns = reply_patterns or DEFAULT_REPLIES
        
        self.on_message_callback = on_message
        self.on_match_callback = on_match
        self.on_disconnect_callback = on_disconnect
        
        self.running = False
        self.sio = None
        
        # Stats
        self.chats_count = 0
        self.messages_sent = 0
        self.messages_received = 0
        
    def generate_reply(self, message: str) -> str:
        """Generate auto-reply. Override this for custom logic."""
        msg_lower = message.lower()
        
        # Simple keyword matching
        if any(w in msg_lower for w in ['hi', 'hello', 'hey']):
            return random.choice(self.reply_patterns)
        elif any(w in msg_lower for w in ['how are you', 'how r you']):
            return "I'm doing great! And you? 😊"
        elif any(w in msg_lower for w in ['age', 'old']):
            return "I'm 22! You?"
        elif any(w in msg_lower for w in ['country', 'where', 'from']):
            return "I'm from Bangladesh! You?"
        elif any(w in msg_lower for w in ['snap', 'instagram', 'ig']):
            return "Sure! Add me on snap: eva_bot_chat"
        elif any(w in msg_lower for w in ['bye', 'gtg', 'gotta go']):
            return "Nice talking! Bye! 👋"
        else:
            return random.choice([
                "Interesting! Tell me more 😊",
                "That's cool!",
                "Haha really? 😄"
            ])
    
    def connect_websocket(self):
        """Connect to WebSocket server"""
        print(f"[WS] Connecting to {WS_URL}...")
        
        self.sio = socketio.Client(reconnection=True, reconnection_attempts=5)
        
        @self.sio.on('connect')
        def on_connect():
            print("[WS] Connected!")
            self.session.connected = True
            # Send presence
            self.sio.emit('presenceSync')
        
        @self.sio.on('disconnect')
        def on_disconnect():
            print("[WS] Disconnected!")
            self.session.connected = False
        
        @self.sio.on('matchUpdate')
        def on_match_update(data):
            print(f"[WS] Match Update: {data}")
            
            if "match" not in data:
                return
                
            match = data["match"]
            
            # Chat closed
            if match.get("closure", {}).get("closed"):
                reason = match["closure"].get("closeReason", "UNKNOWN")
                print(f"[WS] Chat closed: {reason}")
                self.session.conversation_id = None
                
                if self.on_disconnect_callback:
                    self.on_disconnect_callback(match)
                return
            
            # New match
            if "conversation" in match:
                conv = match["conversation"]
                self.session.conversation_id = conv.get("id")
                self.chats_count += 1
                
                print(f"[WS] New match! Conversation: {self.session.conversation_id}")
                
                if self.on_match_callback:
                    self.on_match_callback(match)
                
                # Auto-reply to new match
                if self.auto_reply:
                    time.sleep(1)
                    reply = random.choice(self.reply_patterns)
                    self.api.send_message(reply)
        
        @self.sio.on('chatMessage')
        def on_chat_message(data):
            if "message" not in data:
                return
                
            msg = data["message"]
            author_id = msg.get("author", {}).get("id")
            content = msg.get("content", "")
            conv_id = msg.get("conversationId")
            
            # Ignore own messages
            if author_id == self.session.user_id:
                return
            
            self.messages_received += 1
            print(f"[WS] Message from {msg.get('author', {}).get('username')}: {content}")
            
            # Update conversation
            if conv_id:
                self.session.conversation_id = conv_id
            
            # Callback
            if self.on_message_callback:
                self.on_message_callback(msg)
            
            # Auto-reply
            if self.auto_reply:
                time.sleep(random.randint(2, 5))
                reply = self.generate_reply(content)
                self.api.send_typing()
                time.sleep(1)
                self.api.send_message(reply)
                self.messages_sent += 1
        
        @self.sio.on('typing')
        def on_typing(data):
            print(f"[WS] Partner typing: {data}")
        
        # Connect
        try:
            self.sio.connect(
                WS_URL,
                headers={
                    "Origin": ORIGIN,
                    "Cookie": self.session.cookie_string
                },
                auth={"release": self.session.release},
                transports=["websocket"],
                socketio_path="/socket.io/",
                wait_timeout=30
            )
        except Exception as e:
            print(f"[WS] Connection failed: {e}")
            return False
        
        return True
    
    def start(self):
        """Start the bot"""
        print("=" * 50)
        print("EVA Bot - WebSocket Mode Starting...")
        print(f"User: {self.session.email}")
        print("=" * 50)
        
        self.running = True
        
        # Connect WebSocket
        if not self.connect_websocket():
            print("[BOT] Failed to connect WebSocket")
            return
        
        # Main loop
        try:
            while self.running:
                # If no conversation, find match
                if not self.session.conversation_id:
                    print("[BOT] Looking for match...")
                    self.api.start_matching()
                    time.sleep(5)
                
                time.sleep(10)
                
        except KeyboardInterrupt:
            print("\n[BOT] Stopping...")
            self.stop()
    
    def stop(self):
        """Stop the bot"""
        self.running = False
        if self.sio:
            self.sio.disconnect()
        print("[BOT] Stopped")
        print(f"Stats: {self.chats_count} chats, {self.messages_sent} sent, {self.messages_received} received")


# ============== CLI ==============
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="EVA Bot - WebSocket Mode")
    parser.add_argument("--email", required=True, help="Account email to use session from")
    parser.add_argument("--project-root", help="Project root directory")
    parser.add_argument("--no-auto-reply", action="store_true", help="Disable auto-reply")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    # Load session
    print(f"Loading session for {args.email}...")
    session_data = load_account_session(args.email, args.project_root)
    
    # Create and start bot
    bot = WSBot(
        session_data,
        auto_reply=not args.no_auto_reply
    )
    
    bot.start()
