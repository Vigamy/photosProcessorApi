# Photos Processor API

API em **FastAPI** para receber imagens via `multipart/form-data`, listar imagens e baixar imagem individual com autenticação Bearer.

## Funcionalidades

- Upload de imagem via `multipart/form-data` (campo `file`).
- Persistência local em disco (`data/images`) e metadados em PostgreSQL.
- Autenticação por token Bearer.
- Listagem de imagens recebidas e download por ID.

## Como rodar

### Opção recomendada: Docker Compose (API + Postgres)

```bash
docker compose up --build
```

Serviços disponíveis:

- API: `http://127.0.0.1:8000`
- Swagger: `http://127.0.0.1:8000/docs`
- Postgres: `localhost:5432` (`postgres/postgres`, DB `photos_processor`)

### 1) Subir Postgres local (desenvolvimento)

Opção rápida com Docker:

```bash
docker run --name photos-postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=photos_processor \
  -p 5432:5432 \
  -d postgres:16
```

### 2) Configurar variáveis de ambiente

```bash
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/photos_processor"
export API_BEARER_TOKEN="seu-token-aqui"
```

> Em produção, basta mudar o host/credenciais no `DATABASE_URL` para seu banco hospedado.

### 3) Rodar a aplicação

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Se `API_BEARER_TOKEN` não for definido, a API gera automaticamente um token e persiste em `data/api_token.txt` (também aparece no log de startup).

Acesse:

- Swagger: `http://127.0.0.1:8000/docs`
- Galeria (lista): `http://127.0.0.1:8000/gallery`
- Login da galeria: `http://127.0.0.1:8000/login`

### Login da galeria (sem register)

A galeria HTML exige autenticação por formulário de login (somente login, sem registro). Configure:

```bash
export GALLERY_LOGIN_USERNAME="seu-usuario"
export GALLERY_LOGIN_PASSWORD="sua-senha-forte"
export GALLERY_SESSION_SECRET="um-segredo-diferente-do-token"
```

Se `GALLERY_LOGIN_PASSWORD` não for definido, a API usa o valor de `API_BEARER_TOKEN` como senha de fallback.

## Endpoints

### `POST /image`
Envia imagem no formato `multipart/form-data`, com campo `file`.

Resposta (201):

```json
{
  "id": "uuid",
  "filename": "foto.png",
  "mime_type": "image/png",
  "size_bytes": 12345,
  "created_at": "2026-03-24T21:00:00+00:00",
  "content_url": "/image/{id}",
  "gallery_url": "/gallery/{id}"
}
```

### `GET /images`
Retorna lista de imagens com metadados.

### `GET /image/{id}`
Retorna o binário da imagem por ID.

### `GET /gallery`
Página HTML com lista de imagens (protegida por login).

### `GET /gallery/{id}`
Página HTML com visualização individual da imagem (protegida por login).

### `GET /login` e `POST /login`
Tela e submissão de login da galeria.

### `GET /logout`
Encerra a sessão de login da galeria.

## Exemplo com `curl` (Bearer + upload)

```bash
curl -sS -X POST "http://127.0.0.1:8000/image" \
  -H "Authorization: Bearer $API_BEARER_TOKEN" \
  -F "file=@/caminho/arquivo.png"
```

## Deploy na Vercel

Este repositório já está preparado para deploy com Vercel usando função Python (`api/index.py`) e rewrite global no `vercel.json` para enviar todas as rotas para `/api/index`. O runtime Python é detectado automaticamente pela Vercel (sem fixar versão no `vercel.json`).

### 1) Pré-requisitos

- Conta na Vercel
- Vercel CLI instalada (`npm i -g vercel`)

### 2) Definir variáveis de ambiente

No projeto da Vercel, configure:

- `API_BEARER_TOKEN` = um token forte para autenticação
- `DATABASE_URL` = string de conexão Postgres hospedado (**obrigatório**)

> Sem essa variável, a API ainda sobe, mas usa token efêmero por instância no ambiente serverless.

### 3) Fazer o deploy

```bash
vercel
```

Para produção:

```bash
vercel --prod
```

### 4) Observações importantes sobre persistência

No ambiente serverless da Vercel, o filesystem é efêmero. Nesta API, os uploads ficam em `/tmp/photos-processor-data`, ou seja, os arquivos podem ser perdidos entre execuções/cold starts.

Para produção, use armazenamento de imagens externo (ex.: Vercel Blob, S3) e Postgres hospedado para metadados.

## CI para deploy automático (Preview em PR + Produção na main)

Foi adicionado um workflow do GitHub Actions em `.github/workflows/vercel-preview.yml` que publica um preview a cada PR (`opened`, `synchronize`, `reopened`) e comenta a URL no próprio PR. Além disso, em `push` para `main`, ele faz deploy de produção automaticamente.

### Secrets necessários no GitHub

No repositório, configure em **Settings → Secrets and variables → Actions**:

- `VERCEL_TOKEN`
- `VERCEL_ORG_ID`
- `VERCEL_PROJECT_ID`

### Como obter os valores

- `VERCEL_TOKEN`: em Vercel → Account Settings → Tokens
- `VERCEL_ORG_ID` e `VERCEL_PROJECT_ID`: após rodar localmente `vercel link`/`vercel pull`, eles ficam no arquivo `.vercel/project.json`

Com isso, toda atualização no PR dispara deploy de preview automaticamente, e cada atualização na branch `main` dispara deploy de produção.

> Se algum secret estiver ausente, o workflow não falha por credencial: ele comenta no PR quais secrets faltam e pula o deploy.
