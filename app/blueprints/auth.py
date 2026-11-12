from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_user, logout_user

from app.forms import LoginForm
from app.models import User

auth_bp = Blueprint("auth", __name__)


ROLE_ENDPOINTS = {
    "admin": "central.dashboard",
    "farmacia": "farmacia.dashboard",
    "motoboy": "motoboy.dashboard",
}


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for(ROLE_ENDPOINTS[current_user.role]))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data.strip()).first()
        if user is None or not user.check_password(form.password.data):
            flash("Usuário ou senha inválidos.", "error")
        elif not user.ativo:
            flash("Esta conta está desativada. Fale com a Central.", "error")
        else:
            login_user(user)
            flash("Login realizado com sucesso.", "success")
            return redirect(url_for(ROLE_ENDPOINTS[user.role]))
    elif form.is_submitted():
        flash("Corrija os campos destacados e tente novamente.", "error")

    return render_template("auth/login.html", form=form)


@auth_bp.post("/logout")
def logout():
    logout_user()
    flash("Você saiu da sua conta.", "success")
    return redirect(url_for("auth.login"))
