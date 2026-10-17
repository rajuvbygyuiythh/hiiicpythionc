#!/usr/bin/env python3
"""
EVA Bot - WebSocket Mode Launcher

Simple launcher that uses saved browser sessions to run the WebSocket bot.
Can be called from the dashboard or command line.

Usage:
    python run_ws_bot.py <email>
    
Or for GUI integration, just import and use:
    from transport.ws_bot import WSBot, load_account_session
    
    session = load_account_session("email@example.com")
    bot = WSBot(session)
    bot.start()
"""

import sys
import os

# Add project root to path
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

import argparse
from papipapi.transport.ws_bot import WSBot, load_account_session, list_available_sessions


def main():
    parser = argparse.ArgumentParser(description="EVA Bot - WebSocket Mode")
    parser.add_argument("email", nargs="?", help="Email of account to use")
    parser.add_argument("--list", action="store_true", help="List available sessions")
    parser.add_argument("--project-root", help="Project root directory")
    parser.add_argument("--debug", action="store_true", help="Enable debug")
    
    args = parser.parse_args()
    
    if args.list:
        print("Available sessions:")
        sessions = list_available_sessions(args.project_root)
        for s in sessions:
            print(f"  - {s['email']} (created: {s.get('created', 'unknown')})")
        return
    
    if not args.email:
        print("Usage: python run_ws_bot.py <email>")
        print("\nAvailable sessions:")
        sessions = list_available_sessions(args.project_root)
        for s in sessions:
            print(f"  - {s['email']}")
        return
    
    # Load session
    print(f"Loading session for {args.email}...")
    
    try:
        session = load_account_session(args.email, args.project_root)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("\nAvailable sessions:")
        sessions = list_available_sessions(args.project_root)
        for s in sessions:
            print(f"  - {s['email']}")
        return
    except Exception as e:
        print(f"Error loading session: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Create and start bot
    print(f"Starting WebSocket bot for {session.get('email', args.email)}...")
    print(f"User ID: {session.get('user_id', 'unknown')}")
    print(f"Release: {session.get('release', 'unknown')[:20]}...")
    
    bot = WSBot(session, auto_reply=True)
    
    try:
        bot.start()
    except KeyboardInterrupt:
        print("\nStopping...")
        bot.stop()


if __name__ == "__main__":
    main()
