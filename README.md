# Photos Processor API

API em **FastAPI** para receber imagens em base64, listar imagens e visualizar imagens individualmente ou em galeria.

## Funcionalidades

- Upload de imagem via `base64` (com ou sem prefixo `data:image/...;base64,`).
- Persistência local em disco (`data/images`) e metadados em SQLite (`data/images.db`).
- Listagem de imagens recebidas.
- Visualização individual e em lista no navegador.

## Como rodar

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Acesse:

- Swagger: `http://127.0.0.1:8000/docs`
- Galeria (lista): `http://127.0.0.1:8000/gallery`

## Endpoints

### `POST /images`
Envia imagem em base64.

Exemplo de payload:

```json
{
  "filename": "foto.png",
  "content_base64": "iVBORw0KGgoAAAANSUhEUgAA..."
}
```

Resposta (201):

```json
{
  "id": "uuid",
  "filename": "foto.png",
  "mime_type": "image/png",
  "size_bytes": 12345,
  "created_at": "2026-03-24T21:00:00+00:00",
  "content_url": "/images/{id}/content",
  "gallery_url": "/gallery/{id}"
}
```

### `GET /images`
Retorna lista de imagens com metadados.

### `GET /images/{id}`
Retorna detalhes de uma imagem.

### `GET /images/{id}/content`
Retorna o binário da imagem.

### `GET /gallery`
Página HTML com lista de imagens.

### `GET /gallery/{id}`
Página HTML com visualização individual da imagem.

## Observações

- Base64 é uma forma simples para começar e funciona bem para payloads menores.
- Para imagens muito grandes ou alto volume, `multipart/form-data` costuma ser mais eficiente.
