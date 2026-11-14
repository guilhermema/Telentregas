"""Cria dados de teste locais para desenvolvimento. Não usar em produção."""

from app import create_app
from app.extensions import db
from app.models import BairroPreco, Farmacia, Motoboy, User

SENHA_TESTE = "senha123"


def obter_usuario(username: str, role: str) -> User:
    user = User.query.filter_by(username=username).first()
    if user is None:
        user = User(username=username, role=role, ativo=True)
        user.set_password(SENHA_TESTE)
        db.session.add(user)
        db.session.flush()
    return user


def main() -> None:
    app = create_app()
    with app.app_context():
        admin = obter_usuario("admin-teste", "admin")
        farmacia_user = obter_usuario("farmacia1", "farmacia")
        farmacia = Farmacia.query.filter_by(user_id=farmacia_user.id).first()
        if farmacia is None:
            farmacia = Farmacia(
                user_id=farmacia_user.id,
                razao_social="Farmácia Teste",
                cnpj_cpf="00.000.000/0001-00",
                endereco_fixo="Rua de Teste, 100",
                cidade="Itajaí",
                uf="SC",
                telefone="11999999999",
                responsavel_financeiro="Responsável Teste",
            )
            db.session.add(farmacia)
            db.session.flush()
        else:
            farmacia.cidade = farmacia.cidade or "Itajaí"
            farmacia.uf = farmacia.uf or "SC"

        for bairro, valor in (("Centro", "8.00"), ("Jardins", "10.00"), ("Vila Nova", "12.50")):
            if not BairroPreco.query.filter_by(farmacia_id=farmacia.id, bairro=bairro).first():
                db.session.add(BairroPreco(farmacia_id=farmacia.id, bairro=bairro, valor_taxa=valor))

        for username, nome, telefone, placa in (
            ("motoboy1", "Motoboy Teste 1", "11988881111", "ABC1D23"),
            ("motoboy2", "Motoboy Teste 2", "11988882222", "DEF4G56"),
        ):
            user = obter_usuario(username, "motoboy")
            if not Motoboy.query.filter_by(user_id=user.id).first():
                db.session.add(Motoboy(user_id=user.id, nome=nome, telefone=telefone, placa_moto=placa))

        db.session.commit()
        print("Dados de teste criados. Usuários: admin-teste, farmacia1, motoboy1 e motoboy2.")
        print(f"Senha dos usuários de teste: {SENHA_TESTE}")


if __name__ == "__main__":
    main()
