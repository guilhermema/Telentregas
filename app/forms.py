from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Length


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
