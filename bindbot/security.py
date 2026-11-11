"""Работа с паролями игры.

Мод хранит пароль как SHA256_PassHash(пароль, соль) -> 64 hex-символа, соль - 10 символов
(коды 47..125). Точный порядок склейки зависит от плагина, поэтому при проверке
перебираем варианты и запоминаем, какой подошёл (он потом используется при смене пароля).
Проверить схему вручную: python tools/check_hash.py
"""
import hashlib
import hmac
import secrets

VARIANTS = {
    "pw_salt_upper": lambda p, s: hashlib.sha256((p + s).encode("cp1251", "replace")).hexdigest().upper(),
    "pw_salt_lower": lambda p, s: hashlib.sha256((p + s).encode("cp1251", "replace")).hexdigest().lower(),
    "salt_pw_upper": lambda p, s: hashlib.sha256((s + p).encode("cp1251", "replace")).hexdigest().upper(),
    "salt_pw_lower": lambda p, s: hashlib.sha256((s + p).encode("cp1251", "replace")).hexdigest().lower(),
}
DEFAULT_VARIANT = "pw_salt_upper"


def make_hash(password: str, salt: str, variant: str = DEFAULT_VARIANT) -> str:
    return VARIANTS.get(variant, VARIANTS[DEFAULT_VARIANT])(password, salt)


def random_salt(length: int = 10) -> str:
    # так же, как в моде: random(79) + 47 -> символы с кодами 47..125
    return "".join(chr(47 + secrets.randbelow(79)) for _ in range(length))


def verify_password(password: str, salt: str, stored: str, forced_variant: str = ""):
    """Возвращает имя схемы, под которую подошёл пароль, или None.

    Регистр hex-строки не важен при сравнении, но запоминается: при смене пароля новый
    хеш записывается в том же регистре, что и старый.
    """
    stored = (stored or "").strip()
    names = [forced_variant] if forced_variant in VARIANTS else ["pw_salt_upper", "salt_pw_upper"]
    for name in names:
        digest = make_hash(password, salt, name)
        if hmac.compare_digest(digest.lower(), stored.lower()):
            if forced_variant in VARIANTS:
                return forced_variant
            has_letters = any(c.isalpha() for c in stored)
            lower = has_letters and stored == stored.lower()
            return name.replace("_upper", "_lower") if lower else name
    return None


def valid_password(password: str, pw_min: int, pw_max: int):
    """Возвращает текст ошибки или None, если пароль подходит."""
    if " " in password or "\n" in password:
        return "Пароль не должен содержать пробелов."
    if not (pw_min <= len(password) <= pw_max):
        return f"Длина пароля должна быть от {pw_min} до {pw_max} символов."
    try:
        password.encode("cp1251")
    except UnicodeEncodeError:
        return "Используйте только латиницу, кириллицу, цифры и обычные символы."
    return None


def valid_pin(pin: str):
    if not (pin.isdigit() and len(pin) == 4):
        return "PIN-код — ровно 4 цифры."
    return None


def valid_admin_pass(value: str):
    if not (value.isdigit() and len(value) == 4 and 1000 <= int(value) <= 9999):
        return "Админ-пароль — 4 цифры, от 1000 до 9999."
    return None
