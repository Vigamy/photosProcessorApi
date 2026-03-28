import filetype
import logging
import os
import secrets
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path("/tmp/photos-processor-data") if os.getenv("VERCEL") else (BASE_DIR / "data")
IMAGES_DIR = DATA_DIR / "images"
DB_PATH = DATA_DIR / "images.db"
TOKEN_PATH = DATA_DIR / "api_token.txt"

IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def load_or_create_api_token() -> str:
    env_token = os.getenv("API_BEARER_TOKEN")
    if env_token:
        return env_token

    if TOKEN_PATH.exists():
        stored_token = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if stored_token:
            return stored_token

    generated_token = secrets.token_urlsafe(32)
    if os.getenv("VERCEL"):
        logging.warning("API_BEARER_TOKEN não definido no ambiente Vercel; usando token efêmero por instância.")
        return generated_token

    TOKEN_PATH.write_text(generated_token, encoding="utf-8")
    return generated_token


API_BEARER_TOKEN = load_or_create_api_token()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    logging.info("Initializing database...")
    init_db()
    logging.info("Bearer token ativo em %s", TOKEN_PATH)
    if not os.getenv("API_BEARER_TOKEN"):
        logging.info("Token gerado automaticamente: %s", API_BEARER_TOKEN)
    logging.info("Database initialized. Starting FastAPI app.")
    yield
    logging.info("Shutting down FastAPI app.")


app = FastAPI(
    title="Photos Processor API",
    description="API para upload/listagem de imagens com autenticação Bearer.",
    version="1.0.0",
    lifespan=lifespan,
)


class ImageUploadResponse(BaseModel):
    id: str
    filename: str
    mime_type: str
    size_bytes: int
    created_at: str
    content_url: str
    gallery_url: str


class ImageItem(BaseModel):
    id: str
    filename: str
    mime_type: str
    size_bytes: int
    created_at: str
    image_url: str
    gallery_url: str


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS images (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


@app.get("/health")
def health() -> dict[str, str]:
    logging.info("Health check requested")
    return {"status": "ok"}


def require_bearer_auth(
    authorization: Annotated[Optional[str], Header()] = None,
) -> None:
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Cabeçalho Authorization ausente",
            headers={"WWW-Authenticate": "Bearer"},
        )

    auth_type, _, token = authorization.partition(" ")
    if auth_type.lower() != "bearer" or not token or token != API_BEARER_TOKEN:
        raise HTTPException(
            status_code=401,
            detail="Token Bearer inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )


def to_image_item(row: sqlite3.Row) -> ImageItem:
    return ImageItem(
        id=row["id"],
        filename=row["filename"],
        mime_type=row["mime_type"],
        size_bytes=row["size_bytes"],
        created_at=row["created_at"],
        image_url=f"/image/{row['id']}",
        gallery_url=f"/gallery/{row['id']}",
    )


def fetch_all_images() -> list[ImageItem]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, filename, mime_type, size_bytes, created_at
            FROM images
            ORDER BY created_at DESC
            """
        ).fetchall()
    return [to_image_item(row) for row in rows]


@app.post(
    "/image",
    response_model=ImageUploadResponse,
    status_code=201,
    dependencies=[Depends(require_bearer_auth)],
)
async def upload_image(file: UploadFile = File(...)) -> ImageUploadResponse:
    image_bytes = await file.read()
    kind = filetype.guess(image_bytes)
    if kind is None or not kind.mime.startswith('image/'):
        raise HTTPException(status_code=400, detail="Conteúdo não é uma imagem válida")

    ext = kind.extension
    mime_type = kind.mime
    image_id = str(uuid.uuid4())
    original_name = file.filename or f"image-{image_id[:8]}.{ext}"
    stored_name = f"{image_id}.{ext}"
    output_path = IMAGES_DIR / stored_name
    output_path.write_bytes(image_bytes)

    created_at = datetime.now(timezone.utc).isoformat()

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO images (id, filename, stored_name, mime_type, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                image_id,
                original_name,
                stored_name,
                mime_type,
                len(image_bytes),
                created_at,
            ),
        )
        conn.commit()

    logging.info(f"Image uploaded successfully: {image_id}, filename: {original_name}, size: {len(image_bytes)} bytes")

    return ImageUploadResponse(
        id=image_id,
        filename=original_name,
        mime_type=mime_type,
        size_bytes=len(image_bytes),
        created_at=created_at,
        content_url=f"/image/{image_id}",
        gallery_url=f"/gallery/{image_id}",
    )


@app.get("/images", response_model=list[ImageItem], dependencies=[Depends(require_bearer_auth)])
def list_images() -> list[ImageItem]:
    logging.info("Listing all images")
    return fetch_all_images()


def get_image_metadata(image_id: str) -> sqlite3.Row:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, filename, stored_name, mime_type, size_bytes, created_at
            FROM images
            WHERE id = ?
            """,
            (image_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Imagem não encontrada")

    return row


@app.get("/image/{image_id}", dependencies=[Depends(require_bearer_auth)])
def get_image_by_id(image_id: str) -> FileResponse:
    row = get_image_metadata(image_id)

    file_path = IMAGES_DIR / row["stored_name"]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Arquivo de imagem não encontrado")

    logging.info(f"Serving image content: {image_id}")

    return FileResponse(path=file_path, media_type=row["mime_type"], filename=row["stored_name"])


@app.get("/gallery", response_class=HTMLResponse)
def gallery() -> HTMLResponse:
    logging.info("Serving gallery page")
    images = fetch_all_images()
    cards = "".join(
        f"""
        <article style='border:1px solid #ddd;padding:12px;border-radius:8px;'>
            <h3 style='margin-top:0'>{img.filename}</h3>
            <a href='/gallery/{img.id}'>
                <img src='{img.image_url}' alt='{img.filename}' style='max-width:220px;max-height:220px;object-fit:contain;border:1px solid #eee'/>
            </a>
            <p><strong>ID:</strong> {img.id}</p>
            <p><strong>Tamanho:</strong> {img.size_bytes} bytes</p>
        </article>
        """
        for img in images
    )

    if not cards:
        cards = "<p>Nenhuma imagem enviada ainda.</p>"

    html = f"""
    <!DOCTYPE html>
    <html lang='pt-BR'>
      <head>
        <meta charset='UTF-8'/>
        <meta name='viewport' content='width=device-width, initial-scale=1.0'/>
        <title>Galeria de imagens</title>
      </head>
      <body style='font-family:Arial,sans-serif;margin:24px;'>
        <h1>Galeria de imagens</h1>
        <p><a href='/docs'>Abrir documentação Swagger</a></p>
        <section style='display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:16px;'>
            {cards}
        </section>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/gallery/{image_id}", response_class=HTMLResponse)
def gallery_single(image_id: str) -> HTMLResponse:
    row = get_image_metadata(image_id)
    img = to_image_item(row)
    logging.info(f"Serving single image page: {image_id}")
    html = f"""
    <!DOCTYPE html>
    <html lang='pt-BR'>
      <head>
        <meta charset='UTF-8'/>
        <meta name='viewport' content='width=device-width, initial-scale=1.0'/>
        <title>{img.filename}</title>
      </head>
      <body style='font-family:Arial,sans-serif;margin:24px;'>
        <p><a href='/gallery'>← Voltar para galeria</a></p>
        <h1>{img.filename}</h1>
        <img src='{img.image_url}' alt='{img.filename}' style='max-width:90vw;max-height:80vh;object-fit:contain;border:1px solid #eee'/>
        <ul>
          <li><strong>ID:</strong> {img.id}</li>
          <li><strong>Tipo:</strong> {img.mime_type}</li>
          <li><strong>Tamanho:</strong> {img.size_bytes} bytes</li>
          <li><strong>Criado em:</strong> {img.created_at}</li>
        </ul>
      </body>
    </html>
    """
    return HTMLResponse(content=html)
