from decimal import Decimal
import re

from flask_wtf import FlaskForm
from wtforms import BooleanField, DecimalField, PasswordField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional, ValidationError


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
    nome_cliente = StringField("Nome do cliente", validators=[DataRequired(message="Informe o nome do cliente."), Length(max=150)])
    telefone_cliente = StringField("Telefone", validators=[DataRequired(message="Informe o telefone."), Length(max=30)])
    endereco_entrega = StringField("Endereço de entrega", validators=[DataRequired(message="Informe o endereço."), Length(max=300)])
    bairro_entrega = SelectField("Bairro", choices=[], validators=[DataRequired(message="Selecione um bairro.")])
    precisa_troco = BooleanField("Precisa de troco")
    valor_troco = DecimalField(
        "Troco para quanto?",
        places=2,
        validators=[Optional(), NumberRange(min=Decimal("0.01"), message="Informe um valor de troco válido.")],
    )
    usa_maquininha = BooleanField("Usa maquininha")
    observacoes = TextAreaField("Observações", validators=[Optional(), Length(max=1000)])
    submit = SubmitField("Cadastrar entrega")

    def validate_telefone_cliente(self, field: StringField) -> None:
        digits = re.sub(r"\D", "", field.data or "")
        if len(digits) not in (10, 11):
            raise ValidationError("Informe um telefone válido com DDD.")

    def validate_valor_troco(self, field: DecimalField) -> None:
        if self.precisa_troco.data and field.data is None:
            raise ValidationError("Informe para quanto precisa de troco.")
        if not self.precisa_troco.data and field.data is not None:
            field.data = None
