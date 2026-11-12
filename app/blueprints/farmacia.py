from flask import Blueprint, render_template

from app.decorators import role_required

farmacia_bp = Blueprint("farmacia", __name__)


@farmacia_bp.get("/")
@role_required("farmacia")
def dashboard():
    return render_template("dashboard.html", titulo="Farmácia")
