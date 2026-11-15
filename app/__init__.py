from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user
from flask_wtf.csrf import CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from app.extensions import csrf, db, limiter, login_manager, migrate


def create_app(config_class: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)
    if app.config.get("FLASK_ENV") == "production":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
    claim_email = app.config.get("VAPID_CLAIM_EMAIL", "")
    app.logger.info(
        "Configuração VAPID carregada: claim_email=%s",
        "válido" if claim_email.lower().startswith("mailto:") else "inválido ou ausente",
    )

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    @app.errorhandler(403)
    def forbidden(error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template("errors/500.html"), 500

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error: CSRFError):
        is_ajax = (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or request.is_json
            or request.path.startswith("/motoboy/entregas/")
        )
        if is_ajax:
            return jsonify({"ok": False, "mensagem": "A sessão expirou. Atualize a página e tente novamente."}), 400
        return error.description, 400

    from app import models  # noqa: F401
    from app.blueprints.api import api_bp
    from app.blueprints.auth import ROLE_ENDPOINTS, auth_bp
    from app.blueprints.central import central_bp
    from app.blueprints.farmacia import farmacia_bp
    from app.blueprints.motoboy import motoboy_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(central_bp, url_prefix="/central")
    app.register_blueprint(farmacia_bp, url_prefix="/farmacia")
    app.register_blueprint(motoboy_bp, url_prefix="/motoboy")
    app.register_blueprint(api_bp, url_prefix="/api")

    @app.get("/")
    def index():
        if not current_user.is_authenticated or not current_user.ativo:
            return redirect(url_for("auth.login"))
        return redirect(url_for(ROLE_ENDPOINTS[current_user.role]))

    @app.get("/manifest.json")
    def manifest():
        return send_from_directory(app.static_folder, "manifest.json")

    @app.get("/sw.js")
    def service_worker():
        return send_from_directory(app.static_folder, "sw.js")

    return app


@login_manager.user_loader
def load_user(user_id: str):
    from app.models import User

    return db.session.get(User, int(user_id))
