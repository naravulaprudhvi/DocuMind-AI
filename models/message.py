from datetime import datetime

from extensions import db


class Message(db.Model):
    __tablename__ = "messages"

    message_id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.conversation_id"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)  # user / assistant
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sources = db.relationship("MessageSource", backref="message", cascade="all, delete-orphan")

    def __init__(self, conversation_id=None, role=None, content=None, created_at=None, **kwargs):
        self.conversation_id = conversation_id
        self.role = role
        self.content = content
        if created_at is not None:
            self.created_at = created_at
        for k, v in kwargs.items():
            setattr(self, k, v)


class MessageSource(db.Model):
    __tablename__ = "message_sources"

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey("messages.message_id"), nullable=False, index=True)
    chunk_id = db.Column(db.Integer, db.ForeignKey("document_chunks.chunk_id"), nullable=False, index=True)
    relevance_score = db.Column(db.Float)

    chunk = db.relationship("DocumentChunk")

    def __init__(self, message_id=None, chunk_id=None, relevance_score=None, **kwargs):
        self.message_id = message_id
        self.chunk_id = chunk_id
        self.relevance_score = relevance_score
        for k, v in kwargs.items():
            setattr(self, k, v)

