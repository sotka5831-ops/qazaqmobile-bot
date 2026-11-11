import json
import logging
import os
import re
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("bindbot")


def _bool(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    bot_token: str
    admin_ids: set
    secret_key: str
    sqlite_path: str = "bot.db"
    author: str = "QAZAQ MOBILE"
    pw_min: int = 6
    pw_max: int = 15
    max_attempts: int = 5
    lock_minutes: int = 15
    max_accounts: int = 5
    allow_delete_admin: bool = False
    cascade_tables: list = field(default_factory=list)  # [(table, column)]
    hash_variant: str = ""
    servers: list = field(default_factory=list)  # серверы из servers.json / .env


_IDENT = re.compile(r"^[A-Za-z0-9_]+$")


def _clean_json(text: str) -> str:
    """Чиним типичные ошибки при ручной правке с телефона/в панели: умные кавычки, невидимые символы, лишние запятые."""
    text = text.lstrip("\ufeff")
    for bad, good in (("\u201c", '"'), ("\u201d", '"'), ("\u201e", '"'), ("\u00ab", '"'), ("\u00bb", '"'),
                      ("\u00a0", " "), ("\u200b", ""), ("\u200c", ""), ("\u200d", ""), ("\u2060", "")):
        text = text.replace(bad, good)
    return re.sub(r",(\s*[}\]])", r"\1", text)  # запятая перед закрывающей скобкой


def _load_servers() -> list:
    """Игровые серверы берём из servers.json (можно несколько)."""
    items = []
    path = os.getenv("SERVERS_FILE", "servers.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                raw = f.read()
            data = json.loads(_clean_json(raw))
        except (OSError, ValueError) as e:
            line = ""
            if isinstance(e, json.JSONDecodeError):
                lines = _clean_json(raw).splitlines()
                if 0 < e.lineno <= len(lines):
                    line = f"\n  строка {e.lineno}: {lines[e.lineno - 1]!r}"
            log.error("servers.json не прочитан, серверы из файла не загружены: %s%s", e, line)
            return []
        if isinstance(data, dict):
            data = [data]
        items.extend(data)
    result = []
    for i, it in enumerate(items, 1):
        try:
            srv = {
                "name": str(it.get("name") or f"Server {i}").strip(),
                "host": str(it["host"]).strip(),
                "port": int(it.get("port") or 3306),
                "user": str(it["user"]).strip(),
                "password": str(it.get("password", "")),
                "database": str(it["database"]).strip(),
                "table": str(it.get("table") or "accounts").strip(),
                "enabled": bool(it.get("enabled", True)),
            }
        except (KeyError, TypeError, ValueError) as e:
            raise SystemExit(f"Сервер №{i} в servers.json заполнен неверно (нет поля {e}).")
        if srv["user"] == "mysql_user":  # шаблон из servers.json.example, ещё не заполнен
            continue
        if not _IDENT.match(srv["table"]):
            raise SystemExit(f"Сервер №{i}: недопустимое имя таблицы {srv['table']!r}")
        result.append(srv)
    return result


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    key = os.getenv("SECRET_KEY", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN не задан в .env")
    if not key:
        raise SystemExit("SECRET_KEY не задан в .env (см. .env.example)")
    admins = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()}
    cascade = []
    for part in os.getenv("CASCADE_TABLES", "").split(","):
        part = part.strip()
        if ":" in part:
            t, c = part.split(":", 1)
            cascade.append((t.strip(), c.strip()))
    return Config(
        bot_token=token,
        admin_ids=admins,
        secret_key=key,
        sqlite_path=os.getenv("SQLITE_PATH", "bot.db"),
        author=os.getenv("AUTHOR_NAME", "QAZAQ MOBILE"),
        pw_min=int(os.getenv("PASSWORD_MIN", "6")),
        pw_max=int(os.getenv("PASSWORD_MAX", "15")),
        max_attempts=int(os.getenv("MAX_ATTEMPTS", "5")),
        lock_minutes=int(os.getenv("LOCK_MINUTES", "15")),
        max_accounts=int(os.getenv("MAX_ACCOUNTS_PER_USER", "5")),
        allow_delete_admin=_bool(os.getenv("ALLOW_DELETE_ADMIN", "false")),
        cascade_tables=cascade,
        hash_variant=os.getenv("HASH_VARIANT", "").strip(),
        servers=_load_servers(),
  )
