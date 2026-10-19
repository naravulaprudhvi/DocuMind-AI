"""
DocuMind AI - Database Persistence Verification Utility
Validates connection to the active application database (PostgreSQL/Supabase, MySQL, or SQLite).
Run with: python scripts/test_db_connection.py
"""

import sys
import os

# Add root directory to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app, db
from config import Config
from models.user import User
from models.document import Document
from models.conversation import Conversation

def main():
    print("=" * 70)
    print("  DocuMind AI - Application Database Persistence Diagnostic")
    print("=" * 70)

    telemetry = Config.get_db_telemetry()
    print(f"[*] Detected Provider: {telemetry['type']} ({telemetry['label']})")
    print(f"[*] Persistent Storage: {'YES (Rock Solid)' if telemetry['is_persistent'] else 'NO (Ephemeral / Temporary)'}")
    if telemetry.get('warning'):
        print(f"[!] WARNING: {telemetry['warning']}")

    app = create_app()
    with app.app_context():
        engine = db.engine
        print(f"[*] Dialect: {engine.dialect.name}")
        print(f"[*] Safe URI: {repr(engine.url)}")

        try:
            with engine.connect() as conn:
                res = conn.execute(db.text("SELECT 1;")).scalar()
                print(f"[+] Ping Test: Success (SELECT 1 -> {res})")
        except Exception as e:
            print(f"[-] Ping Test FAILED: {e}")
            return 1

        try:
            user_count = User.query.count()
            doc_count = Document.query.count()
            conv_count = Conversation.query.count()
            print(f"[+] Database Record Counts:")
            print(f"    - Registered Users: {user_count}")
            print(f"    - Indexed Documents: {doc_count}")
            print(f"    - Conversations: {conv_count}")
            print("\n[+] Database health test completed successfully!")
            return 0
        except Exception as e:
            print(f"[-] Record Query FAILED: {e}")
            return 1

if __name__ == "__main__":
    sys.exit(main())
