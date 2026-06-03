# Random Person Bot

Telegram bot for anonymous 1-on-1 random chat.

## Run locally

1. Copy `.env.example` to `.env`
2. Fill `BOT_TOKEN`
3. Start services:

```bash
docker compose up -d --build
```

4. Apply migrations:

```bash
docker compose exec app alembic upgrade head
```

5. Open app:

- webhook server: `http://localhost:8000`

## Cloudflare Tunnel

Expose the local app with Cloudflare Quick Tunnel:

```bash
cloudflared tunnel --url http://localhost:8000
```

Use the generated `trycloudflare.com` URL as `PUBLIC_BASE_URL`.

## Notes

- Production uses webhook mode only.
- Redis stores queue/session runtime state.
- PostgreSQL stores users, sessions, reports, blocks.