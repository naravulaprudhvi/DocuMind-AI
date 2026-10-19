from __future__ import annotations

import os
import uuid
from typing import Any, Optional

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

from extensions import db
from models.document import Document, DocumentChunk
from models.message import MessageSource
from routes.auth import login_required
from services.document_service import process_document_pipeline
from services.vector_store import (
    delete_document_index,
    is_document_indexed,
    search_document_index,
)

documents_bp = Blueprint("documents", __name__)


@documents_bp.route("/documents", methods=["GET", "POST"])
@login_required
def library():
    user_id = session.get("user_id")

    if request.method == "POST":
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json
        try:
            file = request.files.get("pdf") or request.files.get("document") or request.files.get("file")
            if not file or file.filename == "":
                if is_ajax:
                    return jsonify({"success": False, "error": "Please choose a file to upload."}), 400
                flash("Please choose a file to upload.", "danger")
                return redirect(url_for("documents.library"))

            allowed_extensions = {".pdf", ".docx", ".doc"}
            ext = os.path.splitext(file.filename.lower())[1]
            if ext not in allowed_extensions:
                err_msg = "Only PDF files are allowed (PDF and Word DOC/DOCX supported)."
                if is_ajax:
                    return jsonify({"success": False, "error": err_msg}), 400
                flash(err_msg, "danger")
                return redirect(url_for("documents.library"))

            # Magic bytes verification for binary formats
            header = file.stream.read(8)
            file.stream.seek(0)
            if ext == ".pdf" and not header.startswith(b"%PDF-"):
                err_msg = "File verification failed: Content does not match valid PDF file structure."
                if is_ajax:
                    return jsonify({"success": False, "error": err_msg}), 400
                flash(err_msg, "danger")
                return redirect(url_for("documents.library"))
            if ext == ".docx" and not header.startswith(b"PK\x03\x04"):
                err_msg = "File verification failed: Content does not match valid DOCX file structure."
                if is_ajax:
                    return jsonify({"success": False, "error": err_msg}), 400
                flash(err_msg, "danger")
                return redirect(url_for("documents.library"))

            original = secure_filename(os.path.basename(file.filename))
            stored = f"{uuid.uuid4().hex}_{original}"
            from services.security_service import (
                compute_file_sha256,
                get_secure_user_upload_dir,
                log_security_event,
            )
            user_dir = get_secure_user_upload_dir(current_app.config["UPLOAD_FOLDER"], user_id)
            path = os.path.join(user_dir, stored)
            file.save(path)
            sha_checksum = compute_file_sha256(path)
            log_security_event("DOCUMENT_UPLOADED", user_id, {"filename": original, "sha256": sha_checksum})

            new_doc: Any = Document(
                user_id=user_id,
                filename=original,
                file_path=path,
                status="uploaded",
            )
            db.session.add(new_doc)
            db.session.commit()

            # Automatically trigger extraction & chunking pipeline
            success, msg, chunk_count = process_document_pipeline(new_doc.document_id)
            if success:
                flash(f"Document / PDF uploaded and processed successfully! ({chunk_count} chunks ready)", "success")
            else:
                flash(f"Document uploaded, but processing notice: {msg}", "warning")

            if is_ajax:
                return jsonify({
                    "success": success,
                    "message": msg if not success else f"{original} uploaded successfully! ({chunk_count} chunks ready)",
                    "document_id": new_doc.document_id,
                    "filename": original,
                    "status": new_doc.status,
                    "chunks": chunk_count,
                    "error": None if success else msg,
                })

            redirect_to = request.form.get("redirect_to")
            if redirect_to == "chat":
                return redirect(url_for("chat.chat"))

            return redirect(url_for("documents.library"))

        except Exception as e:
            db.session.rollback()
            import logging
            import traceback
            logging.error(f"Error during document upload: {e}\n{traceback.format_exc()}")
            if is_ajax:
                return jsonify({"success": False, "error": f"Upload failed: {str(e)}"}), 500
            flash(f"Upload failed: {str(e)}", "danger")
            return redirect(url_for("documents.library"))

    # SECURITY: only this user's documents
    docs = Document.query.filter_by(user_id=user_id).order_by(Document.uploaded_at.desc()).all()
    return render_template("documents.html", docs=docs)


@documents_bp.route("/documents/<int:doc_id>/process", methods=["POST"])
@login_required
def process(doc_id):
    user_id = session.get("user_id")
    doc: Any = Document.query.filter_by(document_id=doc_id, user_id=user_id).first_or_404()
    success, msg, chunk_count = process_document_pipeline(doc.document_id)
    if success:
        flash(f"Document '{doc.filename}' processed successfully! ({chunk_count} chunks ready)", "success")
    else:
        flash(f"Processing failed for '{doc.filename}': {msg}", "danger")
    return redirect(url_for("documents.library"))


@documents_bp.route("/documents/<int:doc_id>/chunks", methods=["GET"])
@login_required
def view_chunks(doc_id):
    user_id = session.get("user_id")
    doc: Any = Document.query.filter_by(document_id=doc_id, user_id=user_id).first_or_404()
    query = request.args.get("q", "").strip()
    indexed = is_document_indexed(doc.document_id)
    search_results = []

    if query and indexed:
        raw_results = search_document_index(doc.document_id, query, top_k=5)
        chunk_ids = [r["chunk_id"] for r in raw_results]
        chunks_by_id = {c.chunk_id: c for c in DocumentChunk.query.filter(DocumentChunk.chunk_id.in_(chunk_ids)).all()} if chunk_ids else {}
        for r in raw_results:
            c: Any = chunks_by_id.get(r["chunk_id"])
            if c:
                search_results.append({
                    "chunk": c,
                    "score": round(r["score"], 4),
                })

    chunks = DocumentChunk.query.filter_by(document_id=doc.document_id).order_by(DocumentChunk.page_number, DocumentChunk.chunk_id).all()
    return render_template(
        "document_chunks.html",
        doc=doc,
        chunks=chunks,
        indexed=indexed,
        query=query,
        search_results=search_results,
    )


def resolve_document_file_path(doc) -> Optional[str]:
    """
    Finds the physical document file on disk through multiple fallback strategies:
    1. doc.file_path directly
    2. Upload folder by base filename
    3. Upload folder by original doc.filename
    4. Suffix / fuzzy match in user's upload directory (e.g. UUID prefix variations)
    5. Legacy paths (C:\\Projects\\DocuMind-AI\\uploads\\<user_id>)
    6. Self-healing: if found, updates doc.file_path in DB so future lookups are immediate.
    """
    if doc.file_path and os.path.exists(doc.file_path):
        return doc.file_path

    candidates = []
    user_upload_dir = os.path.join(current_app.config.get("UPLOAD_FOLDER", "uploads"), str(doc.user_id))

    if user_upload_dir and os.path.exists(user_upload_dir):
        if doc.file_path:
            candidates.append(os.path.join(user_upload_dir, os.path.basename(doc.file_path)))
        candidates.append(os.path.join(user_upload_dir, doc.filename))

        try:
            for fname in os.listdir(user_upload_dir):
                if fname.endswith(doc.filename) or (doc.filename.lower() in fname.lower()):
                    candidates.append(os.path.join(user_upload_dir, fname))
        except OSError:
            pass

    # Check optional legacy directory if configured or present locally
    legacy_base = current_app.config.get("LEGACY_UPLOAD_FOLDER") or (
        r"C:\Projects\DocuMind-AI\uploads" if os.name == "nt" and os.path.exists(r"C:\Projects\DocuMind-AI\uploads") else None
    )
    if legacy_base and os.path.exists(legacy_base):
        legacy_user_dir = os.path.join(legacy_base, str(doc.user_id))
        if os.path.exists(legacy_user_dir):
            if doc.file_path:
                candidates.append(os.path.join(legacy_user_dir, os.path.basename(doc.file_path)))
            candidates.append(os.path.join(legacy_user_dir, doc.filename))
            try:
                for fname in os.listdir(legacy_user_dir):
                    if fname.endswith(doc.filename) or (doc.filename.lower() in fname.lower()):
                        candidates.append(os.path.join(legacy_user_dir, fname))
            except OSError:
                pass

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            try:
                doc.file_path = candidate
                db.session.commit()
            except Exception:
                pass
            return candidate

    return None


def convert_document_to_html(file_path: Optional[str], doc_id: int) -> str:
    """
    Converts a Word (.docx / .doc) or text document into styled HTML for browser viewing.
    Falls back gracefully to python-docx or indexed database chunks.
    """
    ext = os.path.splitext(file_path.lower())[1] if file_path else ""

    # 1. DOCX using python-docx / optional mammoth
    if ext == ".docx" and file_path and os.path.exists(file_path):
        # Optional high-fidelity mammoth conversion (loaded dynamically so linters never complain)
        try:
            import importlib
            if importlib.util.find_spec("mammoth"):
                mammoth = importlib.import_module("mammoth")
                with open(file_path, "rb") as fp:
                    result = mammoth.convert_to_html(fp)
                    if result.value and result.value.strip():
                        return result.value
        except Exception:
            pass

        # Native python-docx conversion preserving bold, italics, headings, and tables
        try:
            import docx
            doc_obj = docx.Document(file_path)
            html_parts = []
            for p in doc_obj.paragraphs:
                p_text = p.text.strip()
                if not p_text:
                    continue
                style_name = p.style.name.lower() if p.style and p.style.name else ""
                runs_html = []
                for run in p.runs:
                    r_text = run.text
                    if not r_text:
                        continue
                    if run.bold:
                        r_text = f"<strong>{r_text}</strong>"
                    if run.italic:
                        r_text = f"<em>{r_text}</em>"
                    runs_html.append(r_text)
                inner = "".join(runs_html) if runs_html else p_text

                if "heading 1" in style_name or "title" in style_name:
                    html_parts.append(f"<h2 class='mt-4 mb-2 fw-bold text-dark'>{inner}</h2>")
                elif "heading 2" in style_name:
                    html_parts.append(f"<h3 class='mt-3 mb-2 fw-bold text-dark'>{inner}</h3>")
                elif "heading 3" in style_name:
                    html_parts.append(f"<h4 class='mt-3 mb-2 fw-semibold text-dark'>{inner}</h4>")
                else:
                    html_parts.append(f"<p class='mb-2'>{inner}</p>")

            for table in doc_obj.tables:
                html_parts.append("<div class='table-responsive my-3'><table class='table table-bordered table-striped'><tbody>")
                for row in table.rows:
                    html_parts.append("<tr>")
                    for cell in row.cells:
                        cell_text = cell.text.strip()
                        html_parts.append(f"<td class='p-2'>{cell_text}</td>")
                    html_parts.append("</tr>")
                html_parts.append("</tbody></table></div>")

            if html_parts:
                return "\n".join(html_parts)
        except Exception:
            pass

    # 2. Plain text / Markdown
    if ext in (".txt", ".md") and file_path and os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as fp:
                content = fp.read()
                paragraphs = [f"<p>{p.strip()}</p>" for p in content.split("\n\n") if p.strip()]
                return "\n".join(paragraphs) if paragraphs else "<p class='text-muted'>Document is empty.</p>"
        except Exception:
            pass

    # 3. Fallback: Use extracted DocumentChunks from database
    chunks = DocumentChunk.query.filter_by(document_id=doc_id).order_by(DocumentChunk.page_number, DocumentChunk.chunk_id).all()
    if chunks:
        html_parts = []
        current_page = None
        for c in chunks:
            if c.page_number != current_page:
                current_page = c.page_number
                html_parts.append(f"<div class='page-divider text-muted small my-3 border-top pt-2'><i class='bi bi-file-earmark-text me-1'></i> Section / Page {current_page}</div>")
            p_tags = "".join(f"<p>{p.strip()}</p>" for p in c.chunk_text.split("\n\n") if p.strip())
            html_parts.append(p_tags or f"<p>{c.chunk_text}</p>")
        return "\n".join(html_parts)

    return "<p class='text-muted'>No readable content could be previewed for this file. Please use the Download option to view it in Microsoft Word.</p>"


@documents_bp.route("/documents/<int:doc_id>/view", methods=["GET"])
@documents_bp.route("/documents/<int:doc_id>/file", methods=["GET"])
@login_required
def view_document(doc_id):
    """
    Serves or displays the original document:
    - Word (.docx, .doc) documents are rendered in a clean, readable browser document viewer.
    - PDFs open directly in the browser's built-in PDF viewer tab.
    - Passing ?raw=1 or ?download=1 directly serves the binary file.
    """
    user_id = session.get("user_id")
    doc: Any = Document.query.filter_by(document_id=doc_id, user_id=user_id).first_or_404()
    file_path = resolve_document_file_path(doc)

    ext = os.path.splitext(doc.filename.lower())[1]
    raw_requested = request.args.get("raw") == "1" or request.args.get("download") in ("1", "true")

    # If raw binary file is explicitly requested, send file directly (synthesize from chunks if missing)
    if raw_requested:
        if not file_path or not os.path.exists(file_path):
            if ext in (".docx", ".doc"):
                chunks = DocumentChunk.query.filter_by(document_id=doc.document_id).order_by(DocumentChunk.page_number, DocumentChunk.chunk_id).all()
                if chunks:
                    try:
                        import docx
                        d_obj = docx.Document()
                        d_obj.add_heading(doc.filename, 0)
                        for c in chunks:
                            for p in c.chunk_text.split("\n\n"):
                                if p.strip():
                                    d_obj.add_paragraph(p.strip())
                        user_dir = os.path.join(current_app.config.get("UPLOAD_FOLDER", "uploads"), str(doc.user_id))
                        os.makedirs(user_dir, exist_ok=True)
                        save_path = os.path.join(user_dir, doc.filename)
                        d_obj.save(save_path)
                        file_path = save_path
                        doc.file_path = save_path
                        db.session.commit()
                    except Exception:
                        pass

        if not file_path or not os.path.exists(file_path):
            flash(f"Original file '{doc.filename}' is not available for direct download.", "warning")
            return redirect(url_for("documents.library"))

        mimetype = None
        if ext == ".pdf":
            mimetype = "application/pdf"
        elif ext in (".docx",):
            mimetype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif ext in (".doc",):
            mimetype = "application/msword"
        elif ext in (".txt", ".md"):
            mimetype = "text/plain; charset=utf-8"

        as_attachment = request.args.get("download") in ("1", "true")
        return send_file(
            file_path,
            mimetype=mimetype,
            as_attachment=as_attachment,
            download_name=doc.filename,
        )

    # Word documents: ALWAYS render in high-fidelity browser document viewer
    if ext in (".docx", ".doc"):
        doc_html = convert_document_to_html(file_path, doc.document_id)
        return render_template(
            "document_viewer.html",
            doc=doc,
            content_html=doc_html,
            is_word=True,
        )

    # Text / Markdown documents: render in document viewer
    if ext in (".txt", ".md"):
        doc_html = convert_document_to_html(file_path, doc.document_id)
        return render_template(
            "document_viewer.html",
            doc=doc,
            content_html=doc_html,
            is_word=False,
        )

    # PDF documents: browser natively renders PDF with application/pdf
    if ext == ".pdf":
        if not file_path or not os.path.exists(file_path):
            doc_html = convert_document_to_html(None, doc.document_id)
            return render_template(
                "document_viewer.html",
                doc=doc,
                content_html=doc_html,
                is_word=False,
            )
        return send_file(
            file_path,
            mimetype="application/pdf",
            as_attachment=False,
            download_name=doc.filename,
        )

    # Fallback to direct send_file if file exists on disk
    if file_path and os.path.exists(file_path):
        return send_file(
            file_path,
            as_attachment=False,
            download_name=doc.filename,
        )

    # Ultimate fallback: render available chunks in document viewer
    doc_html = convert_document_to_html(None, doc.document_id)
    return render_template(
        "document_viewer.html",
        doc=doc,
        content_html=doc_html,
        is_word=False,
    )


@documents_bp.route("/documents/<int:doc_id>/delete", methods=["POST"])
@login_required
def delete(doc_id):
    user_id = session.get("user_id")
    doc: Any = Document.query.filter_by(document_id=doc_id, user_id=user_id).first_or_404()
    if os.path.exists(doc.file_path):
        try:
            os.remove(doc.file_path)
        except OSError:
            pass
    delete_document_index(doc.document_id)
    from services.cache_service import summary_cache
    summary_cache.delete(f"doc_summary_{doc.document_id}")

    chunk_ids = [c[0] for c in db.session.query(DocumentChunk.chunk_id).filter_by(document_id=doc.document_id).all()]
    if chunk_ids:
        MessageSource.query.filter(MessageSource.chunk_id.in_(chunk_ids)).delete(synchronize_session=False)

    from services.security_service import log_security_event
    log_security_event("DOCUMENT_DELETED", user_id, {"document_id": doc_id, "filename": doc.filename})

    db.session.delete(doc)
    db.session.commit()
    flash("Document removed.", "success")
    if request.form.get("redirect_to") == "chat" or (request.referrer and "chat" in request.referrer):
        return redirect(url_for("dashboard"))
    return redirect(url_for("documents.library"))
