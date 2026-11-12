from flask import Blueprint, render_template

from app.decorators import role_required

motoboy_bp = Blueprint("motoboy", __name__)


@motoboy_bp.get("/")
@role_required("motoboy")
def dashboard():
    return render_template("dashboard.html", titulo="Motoboy")
