from flask import Blueprint, render_template

from app.decorators import role_required

central_bp = Blueprint("central", __name__)


@central_bp.get("/")
@role_required("admin")
def dashboard():
    return render_template("dashboard.html", titulo="Central")
