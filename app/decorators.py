from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from flask import abort, flash, redirect, url_for
from flask_login import current_user, login_required

F = TypeVar("F", bound=Callable[..., Any])


def role_required(*roles: str) -> Callable[[F], F]:
    def decorator(view: F) -> F:
        @wraps(view)
        @login_required
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if not current_user.ativo:
                flash("Sua conta está desativada.", "error")
                return redirect(url_for("auth.login"))
            if current_user.role not in roles:
                flash("Você não tem permissão para acessar esta página.", "error")
                abort(403)
            return view(*args, **kwargs)

        return wrapped  # type: ignore[return-value]

    return decorator
