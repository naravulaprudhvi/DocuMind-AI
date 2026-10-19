"""
DocuMind AI - Seamless MySQL to Supabase PostgreSQL Migration Utility
Migrates user account, documents, chunks, conversations, and chat history into Supabase.
"""

import sys
import os
import pymysql
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def migrate():
    print("=" * 70)
    print("  DocuMind AI — Migrating Local MySQL Data into Cloud Supabase")
    print("=" * 70)

    # 1. Connect to MySQL source (from env or default local params)
    mysql_host = os.environ.get("MYSQL_HOST", "localhost")
    mysql_user = os.environ.get("MYSQL_USER", "documind_user")
    mysql_password = os.environ.get("MYSQL_PASSWORD", "")
    mysql_db = os.environ.get("MYSQL_DATABASE", "documind_db")

    mysql_conn = pymysql.connect(
        host=mysql_host,
        user=mysql_user,
        password=mysql_password,
        database=mysql_db,
        cursorclass=pymysql.cursors.DictCursor
    )
    m_cur = mysql_conn.cursor()

    # 2. Connect to Supabase target (from DATABASE_URL)
    supabase_url = os.environ.get("DATABASE_URL")
    if not supabase_url:
        print("[-] Error: DATABASE_URL not found in environment. Please set it before running migration.")
        return
    pg_conn = psycopg2.connect(supabase_url)
    p_cur = pg_conn.cursor()

    try:
        # A. Migrate Users
        m_cur.execute("SELECT * FROM users;")
        users = m_cur.fetchall()
        print(f"[*] Found {len(users)} users in MySQL to migrate...")

        for u in users:
            p_cur.execute("""
                INSERT INTO users (user_id, name, email, password_hash, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE 
                SET name = EXCLUDED.name, email = EXCLUDED.email, password_hash = EXCLUDED.password_hash;
            """, (u["user_id"], u["name"], u["email"], u["password_hash"], u["created_at"]))

        pg_conn.commit()
        print(f"[+] Successfully migrated {len(users)} user accounts into Supabase.")

        # Update users sequence
        p_cur.execute("SELECT setval(pg_get_serial_sequence('users', 'user_id'), coalesce(max(user_id), 1)) FROM users;")
        pg_conn.commit()

        # B. Migrate Documents
        m_cur.execute("SELECT * FROM documents;")
        docs = m_cur.fetchall()
        print(f"[*] Found {len(docs)} documents to migrate...")

        for d in docs:
            p_cur.execute("""
                INSERT INTO documents (document_id, user_id, filename, file_path, status, uploaded_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (document_id) DO UPDATE 
                SET status = EXCLUDED.status;
            """, (d["document_id"], d["user_id"], d["filename"], d["file_path"], d["status"], d["uploaded_at"]))

        pg_conn.commit()
        print(f"[+] Successfully migrated {len(docs)} documents.")

        p_cur.execute("SELECT setval(pg_get_serial_sequence('documents', 'document_id'), coalesce(max(document_id), 1)) FROM documents;")
        pg_conn.commit()

        # C. Migrate Document Chunks
        m_cur.execute("SELECT * FROM document_chunks;")
        chunks = m_cur.fetchall()
        print(f"[*] Found {len(chunks)} chunks to migrate...")

        for c in chunks:
            p_cur.execute("""
                INSERT INTO document_chunks (chunk_id, document_id, page_number, chunk_text, vector_id)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (chunk_id) DO NOTHING;
            """, (c["chunk_id"], c["document_id"], c["page_number"], c["chunk_text"], c["vector_id"]))

        pg_conn.commit()
        print(f"[+] Successfully migrated {len(chunks)} chunks.")

        p_cur.execute("SELECT setval(pg_get_serial_sequence('document_chunks', 'chunk_id'), coalesce(max(chunk_id), 1)) FROM document_chunks;")
        pg_conn.commit()

        # D. Migrate Conversations
        m_cur.execute("SELECT * FROM conversations;")
        convs = m_cur.fetchall()
        print(f"[*] Found {len(convs)} conversations to migrate...")

        for cv in convs:
            p_cur.execute("""
                INSERT INTO conversations (conversation_id, user_id, title, attached_doc_ids, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (conversation_id) DO NOTHING;
            """, (cv["conversation_id"], cv["user_id"], cv["title"], cv.get("attached_doc_ids", ""), cv["created_at"]))

        pg_conn.commit()
        print(f"[+] Successfully migrated {len(convs)} conversations.")

        p_cur.execute("SELECT setval(pg_get_serial_sequence('conversations', 'conversation_id'), coalesce(max(conversation_id), 1)) FROM conversations;")
        pg_conn.commit()

        # E. Migrate Messages
        m_cur.execute("SELECT * FROM messages;")
        msgs = m_cur.fetchall()
        print(f"[*] Found {len(msgs)} messages to migrate...")

        for m in msgs:
            p_cur.execute("""
                INSERT INTO messages (message_id, conversation_id, role, content, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (message_id) DO NOTHING;
            """, (m["message_id"], m["conversation_id"], m["role"], m["content"], m["created_at"]))

        pg_conn.commit()
        print(f"[+] Successfully migrated {len(msgs)} messages.")

        p_cur.execute("SELECT setval(pg_get_serial_sequence('messages', 'message_id'), coalesce(max(message_id), 1)) FROM messages;")
        pg_conn.commit()

        print("\n[+] MIGRATION TO SUPABASE COMPLETED 100% SUCCESSFULLY!")
        return 0
    except Exception as e:
        pg_conn.rollback()
        print(f"[-] Migration error: {e}")
        return 1
    finally:
        mysql_conn.close()
        pg_conn.close()

if __name__ == "__main__":
    sys.exit(migrate())
