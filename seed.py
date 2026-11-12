import os
import sys

from app import create_app
from app.extensions import db
from app.models import User


def main() -> None:
    username = os.getenv("ADMIN_USERNAME")
    password = os.getenv("ADMIN_PASSWORD")

    if not username or not password:
        raise SystemExit(
            "Defina ADMIN_USERNAME e ADMIN_PASSWORD antes de executar o seed."
        )

    app = create_app()
    with app.app_context():
        if User.query.filter_by(username=username).first():
            raise SystemExit(f"O usuário '{username}' já existe.")

        admin = User(username=username, role="admin", ativo=True)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        print(f"Admin '{username}' criado com sucesso.")


if __name__ == "__main__":
    main()
