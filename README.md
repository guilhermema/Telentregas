# TelEntregas

Sistema Flask de gestão de entregas para farmácias, com perfis de Central,
farmácia e motoboy.

## Variáveis de ambiente

Em desenvolvimento, crie `.env` com:

```env
SECRET_KEY=troque-esta-chave
DATABASE_URL=postgresql://usuario:senha@host:5432/telentregas
CENTRAL_WHATSAPP=5547999999999
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
VAPID_CLAIM_EMAIL=mailto:admin@example.com
ADMIN_USERNAME=admin
ADMIN_PASSWORD=uma-senha-com-8-caracteres
FLASK_ENV=development
```

Em produção, use `FLASK_ENV=production`, uma `SECRET_KEY` forte e não
versione o arquivo `.env`. URLs `postgres://` e `postgresql://` são
convertidas automaticamente para o driver `postgresql+psycopg://`.

## Execução local

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/flask --app app:create_app db upgrade
.venv/bin/python seed.py
.venv/bin/flask --app app:create_app run
```

O seed é idempotente: se o administrador já existir, a senha não é
alterada.

## Deploy com Docker/Render

O [Dockerfile](./Dockerfile) instala as bibliotecas necessárias ao WeasyPrint,
executa as migrações, o seed e inicia Gunicorn. Configure as variáveis de
ambiente acima no serviço, incluindo `PORT` fornecida pelo Render.

```bash
docker build -t telentregas .
docker run --env-file .env -e PORT=8000 -p 8000:8000 telentregas
```

O manifest PWA e o service worker são servidos nas rotas `/manifest.json` e
`/sw.js`. A lista offline de municípios fica em
`app/static/data/municipios.json`.
