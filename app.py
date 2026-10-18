from flask import Flask, Response

from config import Config
from extensions import db
from routes.auth import auth_bp, login_required
from routes.chat import chat_bp
from routes.documents import documents_bp
from routes.summaries import summaries_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(summaries_bp)

    @app.route("/")
    @login_required
    def dashboard():
        from routes.chat import chat
        return chat()

    @app.route("/favicon.ico")
    def favicon():
        # Prevent 404 favicon error in browsers
        svg_favicon = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
            <text y=".9em" font-size="90">📄</text>
        </svg>"""
        return Response(svg_favicon, mimetype="image/svg+xml")

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self' 'unsafe-inline' https:; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' data: https://cdn.jsdelivr.net https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https:;"
        )
        return response

    with app.app_context():
        db.create_all()  # creates the 8 tables if they do not exist
        from services.embedding_service import warmup_embedding_model_async
        warmup_embedding_model_async()
    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, reloader_type="stat")
