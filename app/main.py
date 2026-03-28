import filetype
import logging
import os
import secrets
import uuid
from io import BytesIO
from urllib.parse import urlencode
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

from dotenv import load_dotenv
import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel
from PIL import Image, ImageOps
from psycopg.rows import dict_row
from psycopg import sql

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
IS_VERCEL = bool(os.getenv("VERCEL"))
DATA_DIR = Path("/tmp/photos-processor-data") if IS_VERCEL else (BASE_DIR / "data")
IMAGES_DIR = DATA_DIR / "images"
TOKEN_PATH = DATA_DIR / "api_token.txt"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_POOL_MAX_SIZE = int(os.getenv("DB_POOL_MAX_SIZE", "3"))
USE_DB_POOL = os.getenv("USE_DB_POOL", "").lower() in {"1", "true", "yes"}
db_pool: Optional[ConnectionPool] = None

IMAGE_MAX_DIMENSION = int(os.getenv("IMAGE_MAX_DIMENSION", "1920"))
IMAGE_JPEG_QUALITY = int(os.getenv("IMAGE_JPEG_QUALITY", "72"))

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
    global db_pool
    logging.basicConfig(level=logging.INFO)
    logging.info("Initializing database...")
    if DATABASE_URL and USE_DB_POOL:
        db_pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=0,
            max_size=max(1, DB_POOL_MAX_SIZE),
            kwargs={"connect_timeout": 5},
            open=False,
            timeout=2,
        )
    db_ready = init_db()
    logging.info("Bearer token ativo em %s", TOKEN_PATH)
    if not os.getenv("API_BEARER_TOKEN"):
        logging.info("Token gerado automaticamente: %s", API_BEARER_TOKEN)
    if db_ready:
        logging.info("Database initialized. Starting FastAPI app.")
    else:
        logging.warning("Database unavailable on startup. API started with degraded mode (DB endpoints may return 503).")
    yield
    if db_pool is not None:
        db_pool.close()
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
    username: Optional[str] = None
    image_url: str
    gallery_url: str


@contextmanager
def get_conn():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL não definido. Configure um Postgres válido, por exemplo: "
            "postgresql://postgres:postgres@localhost:5432/photos_processor"
        )
    try:
        if db_pool is not None:
            with db_pool.connection() as conn:
                yield conn
            return
        with psycopg.connect(DATABASE_URL, connect_timeout=5) as conn:
            yield conn
    except (psycopg.OperationalError, PoolTimeout) as exc:
        raise RuntimeError("Banco de dados indisponível no momento") from exc


def database_unavailable_http_exception() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="Banco de dados indisponível no momento. Tente novamente em instantes.",
    )


def init_db() -> bool:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS images (
                        id VARCHAR(64) PRIMARY KEY,
                        filename TEXT NOT NULL,
                        stored_name TEXT NOT NULL,
                        mime_type TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        client_ip TEXT NULL,
                        username TEXT NULL,
                        image_data BYTEA NULL
                    )
                    """
                )
                cur.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS client_ip TEXT NULL")
                cur.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS username TEXT NULL")
                cur.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS image_data BYTEA NULL")
            conn.commit()
        return True
    except RuntimeError:
        logging.exception("Não foi possível inicializar o banco de dados")
        return False


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


def compress_image_for_storage(image_bytes: bytes) -> tuple[bytes, str, str]:
    """Reduz a resolução/qualidade para aliviar armazenamento e tráfego no banco."""
    input_buffer = BytesIO(image_bytes)
    try:
        with Image.open(input_buffer) as img:
            img = ImageOps.exif_transpose(img)
            width, height = img.size
            if max(width, height) > IMAGE_MAX_DIMENSION:
                img.thumbnail((IMAGE_MAX_DIMENSION, IMAGE_MAX_DIMENSION), Image.Resampling.LANCZOS)

            # Para comprimir agressivamente e manter previsível, salva sempre em JPEG.
            output = BytesIO()
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            img.save(
                output,
                format="JPEG",
                quality=max(20, min(95, IMAGE_JPEG_QUALITY)),
                optimize=True,
                progressive=True,
            )
            return output.getvalue(), "jpg", "image/jpeg"
    except Exception as exc:  # noqa: BLE001
        logging.warning("Falha ao comprimir imagem; usando original. Erro: %s", exc)
        kind = filetype.guess(image_bytes)
        ext = kind.extension if kind else "bin"
        mime = kind.mime if kind else "application/octet-stream"
        return image_bytes, ext, mime




def serialize_created_at(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value


def to_image_item(row: dict) -> ImageItem:
    return ImageItem(
        id=row["id"],
        filename=row["filename"],
        mime_type=row["mime_type"],
        size_bytes=row["size_bytes"],
        created_at=serialize_created_at(row["created_at"]),
        username=row.get("username"),
        image_url=f"/image/{row['id']}",
        gallery_url=f"/gallery/{row['id']}",
    )


def fetch_images_paginated(
    page: int = 1,
    page_size: int = 24,
    filename: Optional[str] = None,
    mime_type: Optional[str] = None,
    username: Optional[str] = None,
) -> tuple[list[ImageItem], int]:
    where_clauses: list[sql.Composed] = []
    params: list = []

    if filename:
        where_clauses.append(sql.SQL("filename ILIKE %s"))
        params.append(f"%{filename}%")
    if mime_type:
        where_clauses.append(sql.SQL("mime_type = %s"))
        params.append(mime_type)
    if username:
        where_clauses.append(sql.SQL("username ILIKE %s"))
        params.append(f"%{username}%")

    where_sql = sql.SQL("")
    if where_clauses:
        where_sql = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(where_clauses)

    safe_page_size = max(1, min(page_size, 96))
    safe_page = max(1, page)
    offset = (safe_page - 1) * safe_page_size

    try:
        with get_conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                rows = cur.execute(
                    sql.SQL(
                        """
                        SELECT id, filename, mime_type, size_bytes, created_at, username
                        FROM images
                        {where_sql}
                        ORDER BY created_at DESC
                        LIMIT %s OFFSET %s
                        """
                    ).format(where_sql=where_sql),
                    [*params, safe_page_size, offset],
                ).fetchall()
                count_row = cur.execute(
                    sql.SQL(
                        """
                        SELECT COUNT(*) AS total
                        FROM images
                        {where_sql}
                        """
                    ).format(where_sql=where_sql),
                    params,
                ).fetchone()
    except RuntimeError as exc:
        raise database_unavailable_http_exception() from exc
    total_items = int(count_row["total"]) if count_row else 0
    return [to_image_item(row) for row in rows], total_items


@app.post(
    "/image",
    response_model=ImageUploadResponse,
    status_code=201,
    dependencies=[Depends(require_bearer_auth)],
)
async def upload_image(
    request: Request,
    file: UploadFile = File(...),
    username: Optional[str] = Form(default=None),
) -> ImageUploadResponse:
    uploaded_bytes = await file.read()
    kind = filetype.guess(uploaded_bytes)
    if kind is None or not kind.mime.startswith('image/'):
        raise HTTPException(status_code=400, detail="Conteúdo não é uma imagem válida")

    image_bytes, ext, mime_type = compress_image_for_storage(uploaded_bytes)
    image_id = str(uuid.uuid4())
    original_name = file.filename or f"image-{image_id[:8]}.{ext}"
    stored_name = f"{image_id}.{ext}"
    if not IS_VERCEL:
        output_path = IMAGES_DIR / stored_name
        output_path.write_bytes(image_bytes)

    created_at = datetime.now(timezone.utc).isoformat()
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip() or None
    else:
        client_ip = request.client.host if request.client else None

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO images (
                        id,
                        filename,
                        stored_name,
                        mime_type,
                        size_bytes,
                        created_at,
                        client_ip,
                        username,
                        image_data
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        image_id,
                        original_name,
                        stored_name,
                        mime_type,
                        len(image_bytes),
                        created_at,
                        client_ip,
                        username,
                        image_bytes,
                    ),
                )
            conn.commit()
    except RuntimeError as exc:
        raise database_unavailable_http_exception() from exc

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
def list_images(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    filename: Optional[str] = Query(default=None),
    mime_type: Optional[str] = Query(default=None),
    username: Optional[str] = Query(default=None),
) -> list[ImageItem]:
    logging.info("Listing all images")
    items, _ = fetch_images_paginated(
        page=page,
        page_size=page_size,
        filename=filename,
        mime_type=mime_type,
        username=username,
    )
    return items


def get_image_metadata(image_id: str) -> dict:
    try:
        with get_conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                row = cur.execute(
                    """
                    SELECT id, filename, stored_name, mime_type, size_bytes, created_at, image_data
                    FROM images
                    WHERE id = %s
                    """,
                    (image_id,),
                ).fetchone()
    except RuntimeError as exc:
        raise database_unavailable_http_exception() from exc

    if row is None:
        raise HTTPException(status_code=404, detail="Imagem não encontrada")

    return row


@app.get("/image/{image_id}")
def get_image_by_id(image_id: str) -> Response:
    row = get_image_metadata(image_id)

    file_path = IMAGES_DIR / row["stored_name"]
    if not file_path.exists():
        image_data = row.get("image_data")
        if image_data is None:
            raise HTTPException(status_code=404, detail="Arquivo de imagem não encontrado")
        return Response(content=image_data, media_type=row["mime_type"])

    logging.info(f"Serving image content: {image_id}")

    return FileResponse(path=file_path, media_type=row["mime_type"], filename=row["stored_name"])


@app.get("/gallery", response_class=HTMLResponse)
def gallery(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=18, ge=1, le=60),
    filename: Optional[str] = Query(default=None),
    mime_type: Optional[str] = Query(default=None),
    username: Optional[str] = Query(default=None),
) -> HTMLResponse:
    logging.info("Serving gallery page")
    images, total_items = fetch_images_paginated(
        page=page,
        page_size=page_size,
        filename=filename,
        mime_type=mime_type,
        username=username,
    )
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    if page > total_pages:
        page = total_pages
        images, total_items = fetch_images_paginated(
            page=page,
            page_size=page_size,
            filename=filename,
            mime_type=mime_type,
            username=username,
        )

    def build_query(target_page: int) -> str:
        params: dict[str, str | int] = {"page": target_page, "page_size": page_size}
        if filename:
            params["filename"] = filename
        if mime_type:
            params["mime_type"] = mime_type
        if username:
            params["username"] = username
        return urlencode(params)

    prev_page = page - 1 if page > 1 else 1
    next_page = page + 1 if page < total_pages else total_pages

    cards = "".join(
        f"""
        <article class='card'>
            <h3 class='title'>{img.filename}</h3>
            <a href='/gallery/{img.id}'>
                <img src='{img.image_url}' alt='{img.filename}' class='thumb'/>
            </a>
            <p><strong>Usuário:</strong> {img.username or "-"}</p>
            <p><strong>ID:</strong> {img.id}</p>
            <p><strong>Tamanho:</strong> {img.size_bytes} bytes</p>
            <p><strong>Criado em:</strong> {img.created_at}</p>
            <p><a href='/gallery/{img.id}'>Abrir em detalhes</a></p>
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
        <style>
          body {{
            font-family: Inter, Arial, sans-serif;
            margin: 0;
            background: linear-gradient(180deg, #f6f8fb 0%, #eef2ff 100%);
            color: #1f2937;
          }}
          .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 24px;
          }}
          .header {{
            background: #111827;
            color: #fff;
            border-radius: 14px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 8px 20px rgba(17, 24, 39, 0.2);
          }}
          .header a {{
            color: #93c5fd;
          }}
          .filters {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 10px;
            margin: 16px 0 20px 0;
            background: #fff;
            border: 1px solid #dbe5ff;
            border-radius: 12px;
            padding: 12px;
          }}
          .filters input, .filters select {{
            width: 100%;
            box-sizing: border-box;
            border: 1px solid #cbd5e1;
            border-radius: 10px;
            padding: 10px;
            background: #fff;
          }}
          .filters button, .filters a {{
            display: inline-flex;
            justify-content: center;
            align-items: center;
            border-radius: 10px;
            border: none;
            padding: 10px 12px;
            text-decoration: none;
            font-weight: 600;
          }}
          .filters button {{
            background: #2563eb;
            color: white;
            cursor: pointer;
          }}
          .filters a {{
            background: #e2e8f0;
            color: #0f172a;
          }}
          .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
            gap: 16px;
          }}
          .card {{
            border: 1px solid #e5e7eb;
            padding: 12px;
            border-radius: 12px;
            background: white;
            box-shadow: 0 8px 18px rgba(15, 23, 42, 0.08);
          }}
          .title {{
            margin-top: 0;
            overflow-wrap: anywhere;
          }}
          .thumb {{
            width: 100%;
            max-height: 260px;
            object-fit: contain;
            border: 1px solid #eee;
            border-radius: 6px;
            background: #f4f4f4;
          }}
          .pagination {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 18px;
            background: #fff;
            padding: 10px 14px;
            border: 1px solid #dbe5ff;
            border-radius: 12px;
          }}
          .pagination .actions {{
            display: flex;
            gap: 8px;
          }}
          .pagination a {{
            text-decoration: none;
            color: #1d4ed8;
            border: 1px solid #bfdbfe;
            border-radius: 8px;
            padding: 6px 10px;
            background: #eff6ff;
          }}
        </style>
      </head>
      <body>
        <main class='container'>
          <header class='header'>
            <h1>Galeria de imagens</h1>
            <p>Visualize e filtre os uploads com paginação.</p>
            <p><a href='/docs'>Abrir documentação Swagger</a></p>
          </header>

          <form method='get' action='/gallery' class='filters'>
            <input type='text' name='filename' value='{filename or ""}' placeholder='Filtrar por nome do arquivo'/>
            <input type='text' name='username' value='{username or ""}' placeholder='Filtrar por usuário'/>
            <select name='mime_type'>
              <option value=''>Todos os tipos</option>
              <option value='image/jpeg' {"selected" if mime_type == "image/jpeg" else ""}>JPEG</option>
              <option value='image/png' {"selected" if mime_type == "image/png" else ""}>PNG</option>
              <option value='image/webp' {"selected" if mime_type == "image/webp" else ""}>WEBP</option>
            </select>
            <input type='number' min='1' max='60' name='page_size' value='{page_size}' placeholder='Itens por página'/>
            <button type='submit'>Aplicar filtros</button>
            <a href='/gallery'>Limpar filtros</a>
          </form>

          <section class='grid'>
              {cards}
          </section>

          <nav class='pagination'>
            <div>
              Página <strong>{page}</strong> de <strong>{total_pages}</strong> • Total: <strong>{total_items}</strong> imagens
            </div>
            <div class='actions'>
              <a href='/gallery?{build_query(prev_page)}'>← Anterior</a>
              <a href='/gallery?{build_query(next_page)}'>Próxima →</a>
            </div>
          </nav>
        </main>
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
        <style>
          body {{
            font-family: Arial, sans-serif;
            margin: 24px;
            background: #fafafa;
          }}
          .panel {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border: 1px solid #ddd;
            border-radius: 12px;
            padding: 16px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
          }}
          .full-image {{
            width: 100%;
            max-height: 80vh;
            object-fit: contain;
            border: 1px solid #eee;
            border-radius: 8px;
            background: #f5f5f5;
          }}
        </style>
      </head>
      <body>
        <div class='panel'>
          <p><a href='/gallery'>← Voltar para galeria</a></p>
          <h1>{img.filename}</h1>
          <img src='{img.image_url}' alt='{img.filename}' class='full-image'/>
          <ul>
            <li><strong>ID:</strong> {img.id}</li>
            <li><strong>Tipo:</strong> {img.mime_type}</li>
            <li><strong>Tamanho:</strong> {img.size_bytes} bytes</li>
            <li><strong>Criado em:</strong> {img.created_at}</li>
          </ul>
        </div>
      </body>
    </html>
    """
    return HTMLResponse(content=html)
