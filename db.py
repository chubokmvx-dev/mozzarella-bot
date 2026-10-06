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
    await pool.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS video BYTEA")
    await pool.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS ig_media_id TEXT")
    await pool.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ")
    await pool.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS planned_date DATE")
    await pool.execute(
        """
        CREATE TABLE IF NOT EXISTS post_metrics (
            post_id      INT NOT NULL,
            period       TEXT NOT NULL,            -- latest | 24h | 7d
            collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            data         JSONB NOT NULL,
            PRIMARY KEY (post_id, period)
        )
        """
    )


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
        "SELECT id, slot, format FROM posts WHERE status='draft' AND image IS NULL "
        "ORDER BY (planned_date IS NULL), abs(planned_date - CURRENT_DATE), id LIMIT $1",
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


async def add_post(fmt: str, slot: str, text: str, photo_idea: str, planned_date=None) -> int:
    return await pool.fetchval(
        "INSERT INTO posts (format, slot, text, photo_idea, planned_date) VALUES ($1,$2,$3,$4,$5) RETURNING id",
        fmt, slot, text, photo_idea, planned_date,
    )


async def get_post(post_id: int) -> dict | None:
    row = await pool.fetchrow(
        "SELECT id, format, slot, text, photo_idea, status, created_at, ig_media_id, published_at "
        "FROM posts WHERE id=$1",
        post_id,
    )
    return dict(row) if row else None


async def set_text(post_id: int, text: str) -> None:
    await pool.execute("UPDATE posts SET text=$2 WHERE id=$1", post_id, text)


async def set_status(post_id: int, status: str) -> None:
    await pool.execute("UPDATE posts SET status=$2 WHERE id=$1", post_id, status)


async def set_video(post_id: int, video: bytes) -> None:
    await pool.execute("UPDATE posts SET video=$2 WHERE id=$1", post_id, video)


async def get_video(post_id: int) -> bytes | None:
    return await pool.fetchval("SELECT video FROM posts WHERE id=$1", post_id)


async def set_format(post_id: int, fmt: str) -> None:
    await pool.execute("UPDATE posts SET format=$2 WHERE id=$1", post_id, fmt)


async def set_published(post_id: int, media_id: str) -> None:
    await pool.execute(
        "UPDATE posts SET status='published', ig_media_id=$2, published_at=now() WHERE id=$1",
        post_id, media_id,
    )


async def recent_published_formats(limit: int = 5) -> list[str]:
    rows = await pool.fetch(
        "SELECT format FROM posts WHERE status='published' ORDER BY published_at DESC LIMIT $1", limit
    )
    return [r["format"] for r in rows]


# ---------- метрики ----------

async def posts_due_metrics(period: str, hours: int) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT p.id, p.ig_media_id, p.format FROM posts p
        WHERE p.status='published' AND p.ig_media_id IS NOT NULL
          AND p.published_at <= now() - make_interval(hours => $1)
          AND NOT EXISTS (SELECT 1 FROM post_metrics m WHERE m.post_id=p.id AND m.period=$2)
        """,
        hours, period,
    )
    return [dict(r) for r in rows]


async def posts_needing_latest(days: int = 14, stale_minutes: int = 60) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT p.id, p.ig_media_id, p.format FROM posts p
        LEFT JOIN post_metrics m ON m.post_id=p.id AND m.period='latest'
        WHERE p.status='published' AND p.ig_media_id IS NOT NULL
          AND p.published_at >= now() - make_interval(days => $1)
          AND (m.collected_at IS NULL OR m.collected_at < now() - make_interval(mins => $2))
        """,
        days, stale_minutes,
    )
    return [dict(r) for r in rows]


async def save_metrics(post_id: int, period: str, data: dict) -> None:
    import json

    await pool.execute(
        """
        INSERT INTO post_metrics (post_id, period, data) VALUES ($1,$2,$3::jsonb)
        ON CONFLICT (post_id, period) DO UPDATE SET data=EXCLUDED.data, collected_at=now()
        """,
        post_id, period, json.dumps(data),
    )


async def published_with_metrics(limit: int = 60) -> list[dict]:
    import json

    rows = await pool.fetch(
        """
        SELECT p.id, p.format, p.text, p.published_at,
               (SELECT data FROM post_metrics WHERE post_id=p.id AND period='latest') AS latest,
               (SELECT data FROM post_metrics WHERE post_id=p.id AND period='24h') AS m24,
               (SELECT data FROM post_metrics WHERE post_id=p.id AND period='7d') AS m7
        FROM posts p WHERE p.status='published' ORDER BY p.published_at DESC LIMIT $1
        """,
        limit,
    )
    out = []
    for r in rows:
        d = dict(r)
        for k in ("latest", "m24", "m7"):
            d[k] = json.loads(d[k]) if d[k] else None
        out.append(d)
    return out


# ---------- нагадування ----------

async def planned_pending_for(day) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT id, format, slot, text, photo_idea, status FROM posts
        WHERE planned_date=$1 AND status IN ('draft','approved') AND image IS NULL ORDER BY id
        """,
        day,
    )
    return [dict(r) for r in rows]


async def has_post_for_day(day) -> bool:
    """Чи є на цей день пост у плані або вже опублікований (за київською датою)."""
    return bool(
        await pool.fetchval(
            """
            SELECT EXISTS (
              SELECT 1 FROM posts
              WHERE status <> 'rejected'
                AND (planned_date = $1
                     OR (published_at AT TIME ZONE 'Europe/Kyiv')::date = $1)
            )
            """,
            day,
        )
    )


async def upcoming_posts(back_days: int = 1) -> list[dict]:
    """Пости для календаря: заплановані від (сьогодні - back_days), плюс підтверджені/чернетки без дати."""
    rows = await pool.fetch(
        "SELECT id, format, slot, text, status, planned_date, "
        "(image IS NOT NULL) AS has_img, (video IS NOT NULL) AS has_vid "
        "FROM posts WHERE status <> 'rejected' AND "
        "(planned_date >= CURRENT_DATE - $1::int OR (planned_date IS NULL AND status IN ('draft','approved') "
        "AND created_at > now() - interval '14 days')) "
        "ORDER BY planned_date NULLS LAST, slot, id",
        back_days,
    )
    return [dict(r) for r in rows]
