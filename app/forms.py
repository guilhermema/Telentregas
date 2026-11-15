from decimal import Decimal, InvalidOperation
import re

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, ValidationError


class LoginForm(FlaskForm):
    username = StringField(
        "Usuário",
        validators=[DataRequired(message="Informe o usuário."), Length(max=80)],
    )
    password = PasswordField(
        "Senha",
        validators=[DataRequired(message="Informe a senha.")],
    )
    submit = SubmitField("Entrar")


class EntregaForm(FlaskForm):
    cpf_cliente = StringField("CPF do cliente", validators=[DataRequired(message="Informe o CPF do cliente.")])
    nome_cliente = StringField("Nome do cliente", validators=[DataRequired(message="Informe o nome do cliente."), Length(max=150)])
    telefone_cliente = StringField("Telefone", validators=[DataRequired(message="Informe o telefone."), Length(max=30)])
    endereco_entrega = StringField("Endereço de entrega", validators=[DataRequired(message="Informe o endereço."), Length(max=300)])
    bairro_entrega = SelectField("Bairro", choices=[], validators=[DataRequired(message="Selecione um bairro.")])
    forma_pagamento = SelectField(
        "Forma de pagamento",
        choices=[
            ("pix", "Pix (já pago)"),
            ("dinheiro", "Dinheiro"),
            ("cartao", "Cartão (levar maquininha)"),
            ("convenio", "Convênio (coletar assinatura)"),
            ("ja_pago", "Já pago (outro meio)"),
        ],
        validators=[DataRequired(message="Selecione a forma de pagamento.")],
    )
    valor_cobrar = StringField("Valor a cobrar", validators=[Optional()])
    precisa_troco = BooleanField("Precisa de troco")
    valor_troco = StringField("Troco para quanto?", validators=[Optional()])
    usa_maquininha = BooleanField("Usa maquininha")
    observacoes = TextAreaField("Observações", validators=[Optional(), Length(max=1000)])
    submit = SubmitField("Cadastrar entrega")

    def validate_telefone_cliente(self, field: StringField) -> None:
        from app.utils.validators import normalize_phone
        try:
            normalize_phone(field.data)
        except ValueError as error:
            raise ValidationError(str(error)) from error

    def validate_cpf_cliente(self, field: StringField) -> None:
        from app.utils.validators import normalize_cpf
        try:
            field.data = normalize_cpf(field.data)
        except ValueError as error:
            raise ValidationError(str(error)) from error

    def validate_valor_troco(self, field: StringField) -> None:
        if self.forma_pagamento.data != "dinheiro":
            field.data = None
            return
        if self.precisa_troco.data and not (field.data or "").strip():
            raise ValidationError("Informe para quanto precisa de troco.")
        if not self.precisa_troco.data:
            field.data = None

    def validate_valor_cobrar(self, field: StringField) -> None:
        if not (field.data or "").strip():
            field.data = None
            return
        try:
            valor = Decimal(field.data.replace(".", "").replace(",", ".")) if "," in field.data else Decimal(field.data)
        except (InvalidOperation, AttributeError):
            raise ValidationError("Informe um valor a cobrar válido.") from None
        if valor < 0:
            raise ValidationError("O valor a cobrar não pode ser negativo.")
        field.data = f"{valor:.2f}"

    def validate(self, extra_validators=None) -> bool:
        valido = super().validate(extra_validators=extra_validators)
        if self.forma_pagamento.data not in {"pix", "dinheiro", "cartao", "convenio", "ja_pago"}:
            self.forma_pagamento.errors.append("Selecione uma forma de pagamento válida.")
            valido = False
        if self.forma_pagamento.data != "dinheiro":
            self.precisa_troco.data = False
            self.valor_troco.data = None
        if self.forma_pagamento.data == "cartao":
            self.usa_maquininha.data = True
        elif self.forma_pagamento.data != "cartao":
            self.usa_maquininha.data = False
        if valido and self.precisa_troco.data:
            try:
                troco = Decimal(self.valor_troco.data.replace(".", "").replace(",", "."))
                cobrar = Decimal(self.valor_cobrar.data or "0")
            except (InvalidOperation, AttributeError):
                self.valor_troco.errors.append("Informe um valor de troco válido.")
                return False
            if troco <= cobrar:
                self.valor_troco.errors.append("O troco deve ser maior que o valor a cobrar.")
                return False
            self.valor_troco.data = f"{troco:.2f}"
        return valido
