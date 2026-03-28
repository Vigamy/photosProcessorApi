# Photos Processor API

API em **FastAPI** para receber imagens via `multipart/form-data`, listar imagens e baixar imagem individual com autenticação Bearer.

## Funcionalidades

- Upload de imagem via `multipart/form-data` (campo `file`).
- Persistência local em disco (`data/images`) e metadados em SQLite (`data/images.db`).
- Autenticação por token Bearer.
- Listagem de imagens recebidas e download por ID.

## Como rodar

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Você pode definir o token Bearer da API antes de iniciar:

```bash
export API_BEARER_TOKEN="seu-token-aqui"
```

Se `API_BEARER_TOKEN` não for definido, a API gera automaticamente um token e persiste em `data/api_token.txt` (também aparece no log de startup).

Acesse:

- Swagger: `http://127.0.0.1:8000/docs`
- Galeria (lista): `http://127.0.0.1:8000/gallery`

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
Página HTML com lista de imagens.

### `GET /gallery/{id}`
Página HTML com visualização individual da imagem.

## Exemplo com `curl` (Bearer + upload)

```bash
curl -sS -X POST "http://127.0.0.1:8000/image" \
  -H "Authorization: Bearer $API_BEARER_TOKEN" \
  -F "file=@/caminho/arquivo.png"
```

## Deploy na Vercel

Este repositório já está preparado para deploy com Vercel usando função Python (`api/index.py`) e roteamento completo via `vercel.json`. O runtime Python é detectado automaticamente pela Vercel (sem fixar versão no `vercel.json`).

### 1) Pré-requisitos

- Conta na Vercel
- Vercel CLI instalada (`npm i -g vercel`)

### 2) Definir variável de ambiente obrigatória

No projeto da Vercel, configure:

- `API_BEARER_TOKEN` = um token forte para autenticação

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

No ambiente serverless da Vercel, o filesystem é efêmero. Nesta API, os uploads e o SQLite ficam em `/tmp/photos-processor-data`, ou seja, os dados podem ser perdidos entre execuções/cold starts.

Se você quiser persistência real em produção, troque armazenamento local/SQLite por serviços externos (ex.: Vercel Blob, S3, Postgres, Supabase etc.).

## CI para deploy automático em PR (Vercel Preview)

Foi adicionado um workflow do GitHub Actions em `.github/workflows/vercel-preview.yml` que publica um preview a cada PR (`opened`, `synchronize`, `reopened`) e comenta a URL no próprio PR.

### Secrets necessários no GitHub

No repositório, configure em **Settings → Secrets and variables → Actions**:

- `VERCEL_TOKEN`
- `VERCEL_ORG_ID`
- `VERCEL_PROJECT_ID`

### Como obter os valores

- `VERCEL_TOKEN`: em Vercel → Account Settings → Tokens
- `VERCEL_ORG_ID` e `VERCEL_PROJECT_ID`: após rodar localmente `vercel link`/`vercel pull`, eles ficam no arquivo `.vercel/project.json`

Com isso, toda atualização no PR dispara deploy de preview automaticamente.
