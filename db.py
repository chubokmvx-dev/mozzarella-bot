import asyncpg

pool: asyncpg.Pool | None = None


async def init(dsn: str) -> None:
    global pool
    pool = await asyncpg.create_pool(dsn)
    await pool.execute(
        """
        CREATE TABLE IF NOT EXISTS posts (
            id          SERIAL PRIMARY KEY,
            format      TEXT NOT NULL DEFAULT 'photo',   -- photo | carousel | reel
            slot        TEXT NOT NULL DEFAULT '',        -- коли планується, напр. "Вт 12:00"
            text        TEXT NOT NULL,
            photo_idea  TEXT NOT NULL DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'draft',   -- draft | approved | rejected | published
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await pool.execute(
        "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    await pool.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS image BYTEA")


async def add_post_with_image(fmt: str, text: str, image: bytes) -> int:
    return await pool.fetchval(
        "INSERT INTO posts (format, slot, text, photo_idea, image) VALUES ($1,'',$2,'фото додано',$3) RETURNING id",
        fmt, text, image,
    )


async def set_image(post_id: int, image: bytes) -> None:
    await pool.execute("UPDATE posts SET image=$2 WHERE id=$1", post_id, image)


async def get_image(post_id: int) -> bytes | None:
    return await pool.fetchval("SELECT image FROM posts WHERE id=$1", post_id)


async def drafts_without_image(limit: int = 5) -> list[dict]:
    rows = await pool.fetch(
        "SELECT id, slot, format FROM posts WHERE status='draft' AND image IS NULL ORDER BY id LIMIT $1",
        limit,
    )
    return [dict(r) for r in rows]


async def get_setting(key: str) -> str | None:
    return await pool.fetchval("SELECT value FROM settings WHERE key=$1", key)


async def set_setting(key: str, value: str) -> None:
    await pool.execute(
        "INSERT INTO settings (key, value) VALUES ($1,$2) "
        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
        key, value,
    )


async def add_post(fmt: str, slot: str, text: str, photo_idea: str) -> int:
    return await pool.fetchval(
        "INSERT INTO posts (format, slot, text, photo_idea) VALUES ($1,$2,$3,$4) RETURNING id",
        fmt, slot, text, photo_idea,
    )


async def get_post(post_id: int) -> dict | None:
    row = await pool.fetchrow("SELECT * FROM posts WHERE id=$1", post_id)
    return dict(row) if row else None


async def set_text(post_id: int, text: str) -> None:
    await pool.execute("UPDATE posts SET text=$2 WHERE id=$1", post_id, text)


async def set_status(post_id: int, status: str) -> None:
    await pool.execute("UPDATE posts SET status=$2 WHERE id=$1", post_id, status)

async def add_post(fmt: str, slot: str, text: str, photo_idea: str) -> int:
    return await pool.fetchval(
        "INSERT INTO posts (format, slot, text, photo_idea) VALUES ($1,$2,$3,$4) RETURNING id",
        fmt, slot, text, photo_idea,
    )


async def get_post(post_id: int) -> dict | None:
    row = await pool.fetchrow("SELECT * FROM posts WHERE id=$1", post_id)
    return dict(row) if row else None


async def set_text(post_id: int, text: str) -> None:
    await pool.execute("UPDATE posts SET text=$2 WHERE id=$1", post_id, text)


async def set_status(post_id: int, status: str) -> None:
    await pool.execute("UPDATE posts SET status=$2 WHERE id=$1", post_id, status)
