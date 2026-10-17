#!/usr/bin/env python3
"""
EVA Bot - WebSocket CLI Launcher
Simple command line tool to run WebSocket bot

Usage:
    python ws_cli.py              # List sessions & select
    python ws_cli.py 1            # Use session #1
    python ws_cli.py email@test.com  # Use specific email
"""
import sys
import os

# Add project root
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT_DIR)

import time
import threading
from papipapi.transport.ws_bot import WSBot, load_account_session
from browser.account_session_store import load_saved_account_sessions


def main():
    print("=" * 60)
    print("EVA Bot - WebSocket CLI")
    print("=" * 60)
    
    # Load sessions
    print("\n📂 Loading saved sessions...")
    sessions = load_saved_account_sessions()
    
    if not sessions:
        print("\n❌ No saved sessions found!")
        print("   Run browser mode first to login and save an account.")
        return
    
    print(f"\n📋 Found {len(sessions)} saved session(s):\n")
    for i, s in enumerate(sessions):
        print(f"   [{i+1}] {s.get('email', 'Unknown')}")
    
    # Select session
    email = None
    
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg.isdigit():
            idx = int(arg) - 1
            if 0 <= idx < len(sessions):
                email = sessions[idx].get('email')
        else:
            email = arg
    else:
        print("\n👉 Select account number:")
        try:
            idx = int(input("> ")) - 1
            if 0 <= idx < len(sessions):
                email = sessions[idx].get('email')
        except:
            email = sessions[0].get('email')
    
    if not email:
        email = sessions[0].get('email')
    
    print(f"\n🚀 Starting WebSocket bot for: {email}")
    print("   Press Ctrl+C to stop\n")
    
    # Load session
    try:
        session = load_account_session(email)
    except Exception as e:
        print(f"❌ Error loading session: {e}")
        return
    
    # Callbacks
    def on_match(match):
        print(f"\n🎉 NEW MATCH! Chat started")
        print(f"   Conversation: {match.get('conversation', {}).get('id', 'unknown')}")
    
    def on_message(msg):
        author = msg.get('author', {}).get('username', 'Unknown')
        content = msg.get('content', '')
        print(f"\n💬 {author}: {content}")
    
    def on_disconnect(reason=None):
        print(f"\n👋 Chat ended")
    
    # Create and start bot
    bot = WSBot(
        session_data=session,
        auto_reply=True,
        on_match=on_match,
        on_message=on_message,
        on_disconnect=on_disconnect
    )
    
    print("✅ Bot initialized! Connecting to server...\n")
    
    # Start in thread
    thread = threading.Thread(target=bot.start, daemon=True)
    thread.start()
    
    # Wait
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n⏹ Stopping bot...")
        bot.stop()
        print("✅ Stopped!")


if __name__ == "__main__":
    main()
