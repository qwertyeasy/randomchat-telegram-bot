project/
├─ app/
│  ├─ main.py
│  ├─ core/
│  │  ├─ config.py
│  │  └─ logging.py
│  ├─ bot/
│  │  ├─ router.py
│  │  ├─ handlers/
│  │  │  ├─ start.py
│  │  │  ├─ queue.py
│  │  │  ├─ chat.py
│  │  │  └─ common.py
│  │  ├─ keyboards/
│  │  │  ├─ reply.py
│  │  │  └─ inline.py
│  │  └─ states/
│  │     └─ flow.py
│  ├─ db/
│  │  ├─ session.py
│  │  ├─ models.py
│  │  └─ repositories/
│  │     ├─ users.py
│  │     ├─ sessions.py
│  │     ├─ reports.py
│  │     └─ blocks.py
│  ├─ services/
│  │  ├─ matcher.py
│  │  ├─ queue.py
│  │  ├─ chat.py
│  │  ├─ moderation.py
│  │  └─ rate_limit.py
│  └─ utils/
│     ├─ ids.py
│     └─ time.py
├─ alembic/
├─ docker-compose.yml
├─ Dockerfile
├─ .env.example
└─ README.md