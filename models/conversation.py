from datetime import datetime

from extensions import db


class Conversation(db.Model):
    __tablename__ = "conversations"

    conversation_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.user_id"), nullable=False, index=True)
    title = db.Column(db.String(200), default="New chat")
    attached_doc_ids = db.Column(db.String(255), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    messages = db.relationship("Message", backref="conversation", cascade="all, delete-orphan")

    def __init__(self, user_id=None, title="New chat", attached_doc_ids="", created_at=None, **kwargs):
        self.user_id = user_id
        self.title = title
        self.attached_doc_ids = attached_doc_ids or ""
        if created_at is not None:
            self.created_at = created_at
        for k, v in kwargs.items():
            setattr(self, k, v)

    def get_attached_doc_ids(self) -> list[int]:
        """Returns list of document IDs attached to this conversation."""
        ids: list[int] = []
        raw = getattr(self, "attached_doc_ids", "") or ""
        for part in str(raw).split(","):
            part = part.strip()
            if part.isdigit():
                ids.append(int(part))

        # Fallback: if not set in attached_doc_ids, check previous message sources
        if not ids and self.conversation_id:
            try:
                from models.document import DocumentChunk
                from models.message import Message, MessageSource
                rows = (
                    db.session.query(DocumentChunk.document_id)
                    .join(MessageSource, MessageSource.chunk_id == DocumentChunk.chunk_id)
                    .join(Message, Message.message_id == MessageSource.message_id)
                    .filter(Message.conversation_id == self.conversation_id)
                    .distinct()
                    .all()
                )
                ids = [r[0] for r in rows if r[0]]
            except Exception:
                pass
        return ids

    def set_attached_doc_ids(self, doc_ids: list[int]) -> None:
        """Sets and persists unique attached document IDs for this conversation."""
        valid_ids = sorted({int(d) for d in doc_ids if d is not None and str(d).isdigit()})
        self.attached_doc_ids = ",".join(str(d) for d in valid_ids)


