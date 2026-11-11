"""Определяет, как мод хешировал пароль.

Использование:
    python tools/check_hash.py <пароль> <salt> <hash из колонки password>
Достаньте salt и password любого тестового аккаунта из таблицы accounts. Если ни одна схема
не подошла - напишите автору идеи/разработчику мода: нужна точная формула SHA256_PassHash.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bindbot.security import VARIANTS, verify_password  # noqa: E402

if len(sys.argv) != 4:
    raise SystemExit(__doc__)
password, salt, stored = sys.argv[1:4]
variant = verify_password(password, salt, stored)
if variant:
    print(f"Подошла схема: {variant}\nМожно задать в .env: HASH_VARIANT={variant}")
else:
    print("Ни одна из схем не подошла:", ", ".join(VARIANTS))
