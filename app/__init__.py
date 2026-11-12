from flask import Flask, redirect, url_for
from flask_login import current_user

from config import Config
from app.extensions import csrf, db, login_manager, migrate


def create_app(config_class: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

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

    return app


@login_manager.user_loader
def load_user(user_id: str):
    from app.models import User

    return db.session.get(User, int(user_id))
