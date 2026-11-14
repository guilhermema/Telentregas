from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from flask import abort, flash, jsonify, redirect, request, url_for
from flask_login import current_user

F = TypeVar("F", bound=Callable[..., Any])


def role_required(*roles: str) -> Callable[[F], F]:
    def decorator(view: F) -> F:
        @wraps(view)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            is_json_endpoint = (
                request.path.startswith("/api/")
                or "/api/" in request.path
                or request.headers.get("X-Requested-With") == "XMLHttpRequest"
            )
            if not current_user.is_authenticated:
                if is_json_endpoint:
                    return jsonify({"erro": "Sessão expirada."}), 401
                return redirect(url_for("auth.login"))
            if not current_user.ativo:
                if is_json_endpoint:
                    return jsonify({"erro": "Sessão expirada."}), 401
                flash("Sua conta está desativada.", "error")
                return redirect(url_for("auth.login"))
            if current_user.role not in roles:
                if is_json_endpoint:
                    return jsonify({"erro": "Acesso não permitido."}), 403
                flash("Você não tem permissão para acessar esta página.", "error")
                abort(403)
            return view(*args, **kwargs)

        return wrapped  # type: ignore[return-value]

    return decorator
