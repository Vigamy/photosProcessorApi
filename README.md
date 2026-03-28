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
