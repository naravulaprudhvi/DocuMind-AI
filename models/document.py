from datetime import datetime

from extensions import db


class Document(db.Model):
    __tablename__ = "documents"

    document_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.user_id"), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(30), default="uploaded")  # uploaded/processing/ready/failed
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    chunks = db.relationship("DocumentChunk", backref="document", cascade="all, delete-orphan")
    jobs = db.relationship("ProcessingJob", backref="document", cascade="all, delete-orphan")

    def __init__(
        self,
        user_id=None,
        filename=None,
        file_path=None,
        status="uploaded",
        uploaded_at=None,
        **kwargs,
    ):
        self.user_id = user_id
        self.filename = filename
        self.file_path = file_path
        self.status = status
        if uploaded_at is not None:
            self.uploaded_at = uploaded_at
        for k, v in kwargs.items():
            setattr(self, k, v)


class DocumentChunk(db.Model):
    __tablename__ = "document_chunks"

    chunk_id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.document_id"), nullable=False, index=True)
    page_number = db.Column(db.Integer, nullable=False)
    chunk_text = db.Column(db.Text, nullable=False)
    vector_id = db.Column(db.Integer)  # position of this chunk inside the FAISS index

    def __init__(self, document_id=None, page_number=None, chunk_text=None, vector_id=None, **kwargs):
        self.document_id = document_id
        self.page_number = page_number
        self.chunk_text = chunk_text
        self.vector_id = vector_id
        for k, v in kwargs.items():
            setattr(self, k, v)


class ProcessingJob(db.Model):
    __tablename__ = "processing_jobs"

    job_id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.document_id"), nullable=False)
    status = db.Column(db.String(30), default="pending")
    error_message = db.Column(db.Text)
    completed_at = db.Column(db.DateTime)

    def __init__(self, document_id=None, status="pending", error_message=None, completed_at=None, **kwargs):
        self.document_id = document_id
        self.status = status
        self.error_message = error_message
        if completed_at is not None:
            self.completed_at = completed_at
        for k, v in kwargs.items():
            setattr(self, k, v)


