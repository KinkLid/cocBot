# Clash of Clans Telegram Bot (one-clan)

Бот для одного клана Clash of Clans с регистрацией игроков через ЛС и сбором статистики через официальный API.

## Основные возможности
- Регистрация через /register (только в ЛС, в группе — ссылка на ЛС).
- Проверка владельца через `/players/{tag}/verifytoken`.
- Статистика игрока и админская статистика.
- Уведомления (ЛС или общий чат) + ежедневные времена (`/notify 09:00,18:00`).
- Выбор целей на подготовке КВ/ЛВК (`/targets`).
- Админская очистка данных через `/wipe`.

## Ограничения Telegram
- Бот **может** менять custom admin title только для админов Telegram, если есть права.
- Для обычных участников Telegram не позволяет менять роли/ники через бота.
- Поэтому используется команда `/whois` для отображения соответствий Telegram -> CoC.

## Требования
- Python 3.11+
- PostgreSQL
- Clash of Clans Developer API key

## Быстрый старт (Docker)
1. Скопируйте примеры конфигов:
   ```bash
   cp .env.example .env
   cp config.example.yml config.yml
   ```
2. Заполните `.env` и `config.yml`:
   - `BOT_TOKEN` — токен Telegram бота.
   - `COC_API_TOKEN` — токен Clash of Clans API.
   - `CLAN_TAG` — тег клана.
   - `MAIN_CHAT_ID` — id главного чата.
   - `ADMIN_TELEGRAM_IDS` — список Telegram user_id админов **только в конфиге**.

3. Запуск:
   ```bash
   docker-compose up --build
   ```

4. Применение миграций:
   ```bash
   docker-compose run --rm bot alembic upgrade head
   ```

## Получение токенов
### Telegram Bot Token
1. Напишите @BotFather
2. Создайте бота и получите токен

### Clash of Clans API
1. Создайте ключ: https://developer.clashofclans.com
2. Добавьте IP в allowlist (для Docker — IP хоста)
3. Сохраните `COC_API_TOKEN` в `.env`

## Права бота в чате
Для корректной работы в главном чате:
- Send messages
- Delete messages (если нужно)
- Manage chat (для изменения custom admin title)

## Команды
- `/start` — справка + кнопки
- `/register` — регистрация в ЛС
- `/me` — связь Telegram -> CoC
- `/mystats` — личная статистика
- `/stats` — админская статистика
- `/season` — список сезонов и выбор периода
- `/notify` — настройки уведомлений (время можно задать как `/notify 09:00,18:00`)
- `/targets` — выбор целей во время подготовки
- `/whois` — соответствия Telegram -> CoC
- `/wipe` — админская очистка данных

## Важно
- **Нет команды выдачи админов** — админы только в конфиге `ADMIN_TELEGRAM_IDS`.
- Секреты не логируются и не хранятся в репозитории.
