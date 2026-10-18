# DocuMind AI: System Architecture Specification
**Technical Architecture, Schema Design, and Subsystem Flow**

---

## 1. High-Level Subsystems

```
+---------------------------------------------------------------------------------------------+
|                                    PRESENTATION LAYER                                       |
|  - Dashboard View (Overview, Metrics, Quick Actions)                                        |
|  - Document Management (Upload, Preview, Inspect Chunks, FAISS Query Tester, Delete)        |
|  - Chat Interface (Conversations, Multi-Doc Selector, Message History, Sources Inspector)   |
|  - Summaries View (Executive Overview, Extracted Insights, Reading Statistics)              |
|  - Evaluation Dashboard (Benchmark Metrics, Historic Runs, Performance Telemetry)          |
+---------------------------------------------------------------------------------------------+
                                              |
                                              v
+---------------------------------------------------------------------------------------------+
|                                    APPLICATION LAYER                                        |
|  - Flask Application Factory (`app.py`, `config.py`)                                        |
|  - Blueprints: `auth_bp`, `documents_bp`, `chat_bp`, `summaries_bp`                         |
|  - Security Middleware: `login_required`, Session Management, Brute-Force Rate Limiting     |
+---------------------------------------------------------------------------------------------+
                                              |
                 +----------------------------+----------------------------+
                 |                                                         |
                 v                                                         v
+-----------------------------------------------+   +-----------------------------------------------+
|             CORE DOMAIN SERVICES              |   |          PERSISTENCE & CACHE LAYER            |
| - `pdf_processor.py` (PyMuPDF parser)         |   | - MySQL 8.0 Database (8 Normalized Tables)    |
| - `ocr_service.py` (Tesseract Fallback)       |   | - FAISS Vector Store (`.index` Files)         |
| - `chunking.py` (Overlapping Sliding Window)  |   | - 3-Tier LRU Cache (`services/cache_service`) |
| - `embedding_service.py` (SentenceTransfomers)|   |   * Query Embedding Cache (384-d vectors)     |
| - `retrieval.py` (Vector Search + Reranker)   |   |   * FAISS Memory Index Cache                  |
| - `llm_service.py` (Gemini, Ollama, Fallback) |   |   * RAG Query Response Cache                  |
| - `evaluation.py` (Hit Rate, MRR, Citations)  |   | - Isolated File System (`uploads/{user_id}/`) |
+-----------------------------------------------+   +-----------------------------------------------+
```

---

## 2. Database Schema (MySQL 8.0)

DocuMind AI utilizes 8 normalized tables managed through SQLAlchemy:

```
  +------------------+             +-----------------------+
  |      users       | 1         * |       documents       |
  +------------------+-------------+-----------------------+
  | user_id (PK)     |             | document_id (PK)      |
  | email (UNIQUE)   |             | user_id (FK)          |
  | name             |             | filename              |
  | password_hash    |             | file_path             |
  | created_at       |             | status (uploaded/ready|
  +------------------+             | uploaded_at           |
           | 1                     +-----------------------+
           |                                   | 1
           | *                                 | *
  +------------------+             +-----------------------+
  |  conversations   |             |    document_chunks    |
  +------------------+             +-----------------------+
  | conversation_id  |             | chunk_id (PK)         |
  | user_id (FK)     |             | document_id (FK)      |
  | title            |             | chunk_index           |
  | created_at       |             | page_number           |
  +------------------+             | chunk_text (TEXT)     |
           | 1                     | char_length           |
           | *                     +-----------------------+
  +------------------+
  |     messages     | 1         * +-----------------------+
  +------------------+-------------+    message_sources    |
  | message_id (PK)  |             +-----------------------+
  | conversation_id  |             | source_id (PK)        |
  | role (user/asst) |             | message_id (FK)       |
  | content (TEXT)   |             | chunk_id (FK)         |
  | created_at       |             | relevance_score       |
  +------------------+             +-----------------------+

  +----------------------+         +-----------------------+
  |   processing_jobs    |         |    evaluation_runs    |
  +----------------------+         +-----------------------+
  | job_id (PK)          |         | run_id (PK)           |
  | document_id (FK)     |         | dataset_name          |
  | status               |         | metrics_json (JSON)   |
  | message              |         | created_at            |
  | started_at / ended_at|         +-----------------------+
  +----------------------+
```

---

## 3. End-to-End Request Lifecycle: Document Ingestion

1. **Client POST to `/documents`:**  
   Multipart upload received with `pdf` file stream.
2. **File Signature Inspection:**  
   Inspects first 8 bytes. For PDFs, confirms `b"%PDF-"`. Rejects forged files.
3. **Storage Isolation:**  
   Saves to `uploads/{user_id}/{uuid}_{filename}`.
4. **Document Record Creation:**  
   Inserts `Document` row with status `uploaded`.
5. **Processing Pipeline (`process_document_pipeline`):**
   - **Page Extraction:** PyMuPDF parses page streams.
   - **OCR Fallback Check:** Pages with <40 characters trigger 200 DPI image rendering and Tesseract OCR.
   - **Chunking:** Cleans whitespace and splits into 500-character segments with 100-character overlap.
   - **Persistence:** Chunks written to `document_chunks` table.
   - **Vector Indexing:** Chunks converted to 384-dimensional dense vectors via `all-MiniLM-L6-v2`, normalized via $L_2$, and indexed in FAISS `IndexFlatIP`.
   - **Index Serialization:** Written to `vector_indexes/doc_{doc_id}.index`.
   - **Status Update:** Document status set to `ready`.

---

## 4. End-to-End Request Lifecycle: Conversational RAG

1. **Client POST to `/chat/{conv_id}/send`:**  
   Payload contains `question` and optional `document_ids`.
2. **Cache Key Generation:**  
   SHA-256 hash calculated over `(user_id, sorted_doc_ids, clean_question)`.
3. **Query Response Cache Lookup:**  
   If cached, returns immediate response (<1.2ms).
4. **Dense Query Vectorization:**  
   Encodes question with `SentenceTransformer` (or retrieves from `embedding_cache`).
5. **Multi-Document FAISS Search:**  
   Queries FAISS index files for each target document; aggregates top results with inner product scores.
6. **Lexical Keyword Reranker:**  
   Computes keyword overlap score between query terms and chunk text. Reranks candidate pool to balance semantic and exact keyword intent.
7. **Prompt Construction:**  
   Formats system instructions and structured context blocks with explicit citations (`[Document: {name}, Page {page}, Chunk {id}]`).
8. **LLM Generation:**  
   Calls Google Gemini REST API (or local Ollama endpoint `http://localhost:11434/api/generate` or local extractor fallback).
9. **Persistence & Response:**  
   Stores user message, assistant message, and chunk citation links in MySQL. Populates LRU cache. Returns answer and source cards to client.
