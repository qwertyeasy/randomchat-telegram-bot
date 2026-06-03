Implementation Prompt for LLM
You are a senior backend engineer. Build a production-ready MVP of a Telegram bot for anonymous 1-on-1 random chat matchmaking.

1. Product goal
Create a Telegram bot that:

Starts with /start.

Asks consent for data processing once.

Asks the user’s gender once.

Asks the user’s search filter once.

Allows anonymous 1-on-1 random chat matching.

Supports /find, /next, /stop, /delete.

Supports complaints, banlist, AFK timeout, rate limiting.

Stores no chat history after a session closes.

Prepares for future monetization with a priority system.

Runs on a local Ubuntu server using Docker and is exposed externally through Cloudflare Tunnel.

2. Core product rules
User flow
User sends /start.

Bot asks for consent to data processing.

If consent is accepted, bot asks for gender.

Then bot asks for search filter.

Then bot shows the main menu.

User presses “Find chat” or sends /find.

User is placed into a matchmaking queue.

When a pair is found, the bot creates a 1-on-1 anonymous session.

Messages are relayed between the two users.

User can press:

“Next” to interrupt the current chat and search for another partner.

“Stop” to leave the current chat and stop searching.

“Report” to file a complaint.

“Settings” to manage allowed disclosure options.

Session closes automatically on AFK timeout or by user action.

Privacy rules
Users are anonymous by default.

No chat history is stored after session close.

No IP addresses are stored.

Avatars are not shown in MVP.

A user may disclose @username only if they explicitly choose to do so.

If the target user has no @username, personal contact is not available.

Matching rules
Search filter options:

male

female

any

Matching is not restricted only to the opposite sex.

The search filter determines which candidates are eligible for matching.

Gender is collected once after /start.

The user’s chosen search filter must be saved and used for matchmaking.

Commands
/start — onboarding and consent flow.

/find — start searching for a partner.

/next — stop current chat and immediately look for a new partner.

/stop — exit current chat and stop searching.

/delete — manual deletion of the bot dialog by the user if automatic removal is impossible.

/help — help text.

Buttons
Use localized Russian text on buttons, not English command names.
Recommended labels:

🔍 Найти чат

⏭ Следующий

⏹ Выйти

⚠️ Пожаловаться

⚙️ Настройки чата

3. Required stack
Use:

Python 3.12+.

FastAPI for webhook HTTP server.

aiogram 3.x for Telegram bot handling.

PostgreSQL for persistent storage.

Redis for queues, session state, AFK timers, and rate limiting.

Docker Compose for local deployment.

Cloudflare Tunnel for public access.

Do not use polling in production. Use Telegram webhook only.

4. Technical architecture
Data flow
Telegram → Cloudflare Tunnel → FastAPI webhook endpoint → aiogram handlers → Redis/PostgreSQL

Service responsibilities
FastAPI:

Accept webhook updates.

Pass updates to aiogram dispatcher.

aiogram:

Handle commands, callback buttons, and messages.

PostgreSQL:

Store users, sessions, reports, blocks.

Redis:

Store waiting queues, active sessions, TTL keys, rate-limit counters.

Cloudflare Tunnel:

Expose local service publicly via randompersonbot.trycloudflare.com.

5. Database schema
users
Fields:

user_id bigint primary key.

gender enum/string with values male, female.

search_filter enum/string with values male, female, any.

priority integer default 0.

is_banned boolean default false.

consent_given boolean default false.

created_at timestamp.

sessions
Fields:

session_id uuid primary key.

user1_id bigint.

user2_id bigint.

status enum/string: waiting, active, closed.

created_at timestamp.

closed_at timestamp nullable.

reports
Fields:

report_id serial primary key.

session_id uuid.

reporter_id bigint.

target_id bigint.

reason text.

attached_message text nullable.

created_at timestamp.

blocks
Fields:

user_id bigint unique or primary key.

reason text.

banned_at timestamp.

6. Redis design
Use Redis for volatile runtime state.

Keys
queue:male

queue:female

queue:any

session:{session_id}

user:{user_id}:session

rate_limit:{user_id}

afk:{session_id}

Purpose
Queue keys store users waiting for match.

Session keys store active session metadata.

Rate-limit key tracks user actions in a time window.

AFK key tracks last activity and triggers auto-close.

7. Matching algorithm
Implement a deterministic and race-safe matcher.

Matching logic
Validate user:

consent accepted.

not banned.

not already in active session.

not exceeding rate-limit.

Add the user to the queue corresponding to their search filter:

male

female

any

When scanning for a partner:

Match only against candidates allowed by the search filter.

Respect priority first.

If priority is equal, use FIFO.

When a match is found:

Create a new session.

Persist session in PostgreSQL.

Save runtime session state in Redis.

Notify both users.

If no partner is found within 60 seconds:

Remove user from queue.

Send localized timeout message:

Пока никого не нашлось, попробуй позже

Priority behavior
priority = 0 means normal user.

priority = 1 means paid priority in future.

The algorithm must use priority as a ranking factor.

If all users have equal priority, do not artificially slow anyone down.

The queue must remain fair among equal-priority users.

8. Chat behavior
Relay
All messages sent by one participant in an active session must be delivered to the other participant.

Do not expose internal IDs to users.

Do not store message history after session close.

AFK timeout
Close the session automatically after 120 seconds of inactivity.

Both users receive a closure notification.

Session state must be cleaned up from Redis.

Session status must be updated in PostgreSQL.

Commands in chat
/next:

end current session immediately,

put the user back into search flow.

/stop:

end current session,

stop searching.

/delete:

provide manual bot dialog cleanup guidance if Telegram cannot remove it programmatically.

If automatic deletion is not possible, document it and expose only manual behavior.

9. Complaints and moderation
Complaint flow
Add a ⚠️ Пожаловаться button inside active chat.

Complaint should create a record in reports.

Complaint should include:

session_id

reporter_id

target_id

complaint reason

optionally the last relevant message text

Admin panel is not required for MVP.

Data must be structured so that later an admin can review complaints and ban users manually.

Banlist
Check is_banned before /start flow continues and before /find.

Banned users receive a clear denial message.

Ban reason must be stored.

Rate limit
MVP rate limit: 5 chat starts per minute per user.

If exceeded:

temporarily block matching actions.

send a short explanatory message.

Use Redis for counters and TTL.

10. UX and localization
Onboarding messages
Consent screen first.

Gender selection second.

Search filter selection third.

Then main menu.

Button text
Use Russian UI labels:

🔍 Найти чат

⏭ Следующий

⏹ Выйти

⚠️ Пожаловаться

⚙️ Настройки чата

Localization rule
All user-facing messages must be in Russian for MVP.
Code comments and internal identifiers may be in English.

11. Deployment requirements
Environment
The app runs on a bare Ubuntu Server LTS with Docker installed.

Public access
Use Cloudflare Tunnel only.

Public hostname
Assume the public endpoint is:

randompersonbot.trycloudflare.com

Webhook
Set Telegram webhook to the public tunnel URL.

The bot must work with HTTPS webhook traffic through Cloudflare Tunnel.

Do not rely on a purchased domain.

Do not rely on router port forwarding for the MVP.

12. Project structure
Create a clean, modular project layout.

Suggested structure:

app/

app/bot/

app/bot/handlers/

app/bot/keyboards/

app/bot/states/

app/core/

app/db/

app/models/

app/services/

app/utils/

app/main.py

docker-compose.yml

.env.example

README.md

Keep business logic separated from Telegram handlers.

13. Coding requirements
Mandatory
Use type hints.

Use async everywhere where appropriate.

Use dependency injection or a clear service layer.

Keep Telegram handlers thin.

Encapsulate matchmaking logic in a dedicated service.

Encapsulate DB operations in repository or service classes.

Make Redis interactions isolated and testable.

Avoid hardcoded secrets.

Use config from environment variables.

Error handling
Handle Telegram API errors gracefully.

Handle Redis / PostgreSQL connection errors.

Prevent race conditions during matchmaking.

Ensure queues are cleaned up on timeout or disconnect.

Concurrency
Use locking or atomic operations so that the same user cannot be matched twice.

Avoid duplicate session creation.

Make queue updates safe under concurrent /find requests.

14. Minimum viable acceptance criteria
The implementation is done only if all of the following work:

User can complete /start.

Consent is stored.

Gender is stored.

Search filter is stored.

/find enters matchmaking.

Two users can be matched into one anonymous session.

/next works correctly.

/stop works correctly.

/delete exists as a defined behavior or manual fallback.

Complaints are stored in PostgreSQL.

Banlist is checked.

AFK timeout closes the session after 120 seconds.

Rate-limit works.

Priority field exists and is used in matching.

App is deployable through Cloudflare Tunnel.

No chat history is preserved after session closure.

15. Implementation order
Implement in this order:

Project skeleton and configuration.

PostgreSQL models and migrations.

Redis wrapper and runtime keys.

/start onboarding flow.

Search filter selection.

/find queue entry.

Matching engine.

Relay messaging.

/next, /stop, /delete.

Complaints and bans.

AFK timeout.

Rate limiting.

Priority matching.

Docker Compose and Cloudflare Tunnel integration.

Webhook registration and final testing.

16. Final output expected from the model
Produce:

Working backend code.

Working Docker Compose setup.

Webhook-based Telegram bot integration.

Database schema/migrations.

Redis runtime logic.

Minimal README with startup instructions.

No extraneous features beyond the MVP.

17. Non-goals
Do not implement:

Group chats.

Media messages in MVP.

User profiles or public profiles.

Avatar visibility.

Paid billing integration.

Admin dashboard.

Push notifications outside Telegram.

Polling mode.

Browser frontend.

18. Quality bar
The result should be:

simple enough to understand,

structured for production,

safe against race conditions,

easy to extend later,

optimized for MVP delivery.