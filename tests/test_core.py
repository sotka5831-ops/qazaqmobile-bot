import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.fernet import Fernet  # noqa: E402

from bindbot.crypto import Crypto  # noqa: E402
from bindbot.security import (VARIANTS, make_hash, random_salt, valid_admin_pass,  # noqa: E402
                              valid_password, valid_pin, verify_password)
from bindbot.storage import Storage  # noqa: E402


class SecurityTests(unittest.TestCase):
    def test_roundtrip_all_variants(self):
        for name in VARIANTS:
            salt = random_salt()
            stored = make_hash("Qwerty12", salt, name)
            self.assertEqual(len(stored), 64)
            self.assertEqual(verify_password("Qwerty12", salt, stored), name)
            self.assertIsNone(verify_password("wrong", salt, stored))

    def test_salt_matches_game_charset(self):
        for _ in range(200):
            s = random_salt()
            self.assertEqual(len(s), 10)
            self.assertTrue(all(47 <= ord(c) <= 125 for c in s))

    def test_forced_variant(self):
        salt = "abcdefghij"
        stored = make_hash("pass123", salt, "salt_pw_lower")
        self.assertIsNone(verify_password("pass123", salt, stored, "pw_salt_upper"))
        self.assertEqual(verify_password("pass123", salt, stored, "salt_pw_lower"), "salt_pw_lower")

    def test_validators(self):
        self.assertIsNone(valid_password("abc123", 6, 15))
        self.assertIsNotNone(valid_password("abc", 6, 15))
        self.assertIsNotNone(valid_password("a" * 16, 6, 15))
        self.assertIsNotNone(valid_password("has space", 6, 15))
        self.assertIsNone(valid_pin("0123"))
        self.assertIsNotNone(valid_pin("123"))
        self.assertIsNotNone(valid_pin("12a4"))
        self.assertIsNone(valid_admin_pass("1000"))
        self.assertIsNone(valid_admin_pass("9999"))
        self.assertIsNotNone(valid_admin_pass("0999"))
        self.assertIsNotNone(valid_admin_pass("10000"))


class CryptoTests(unittest.TestCase):
    def test_any_string_as_secret(self):
        c = Crypto("ekhFaNXABnuS")  # не Fernet-ключ - ключ выводится из строки
        self.assertEqual(c.decrypt(c.encrypt("pass")), "pass")
        self.assertEqual(Crypto("ekhFaNXABnuS").decrypt(c.encrypt("x")), "x")  # стабильно между запусками

    def test_real_fernet_key(self):
        k = Fernet.generate_key().decode()
        self.assertEqual(Crypto(k).decrypt(Crypto(k).encrypt("p")), "p")


class StorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Storage(os.path.join(self.tmp.name, "t.db"), Crypto(Fernet.generate_key().decode()))

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_servers(self):
        sid = await self.db.add_server("Main", "127.0.0.1", 3306, "u", "secret-pass", "game")
        s = await self.db.get_server(sid)
        self.assertEqual(s.db_pass, "secret-pass")
        raw = self.db._sync("SELECT db_pass FROM servers WHERE id=?", (sid,), "one")["db_pass"]
        self.assertNotIn("secret-pass", raw)  # пароль БД хранится зашифрованным
        self.assertEqual(len(await self.db.list_servers(only_enabled=True)), 1)
        await self.db.toggle_server(sid)
        self.assertEqual(len(await self.db.list_servers(only_enabled=True)), 0)

    async def test_upsert_server(self):
        sid, created = await self.db.upsert_server("Main", "h", 3306, "u", "p1", "d", "accounts")
        self.assertTrue(created)
        sid2, created2 = await self.db.upsert_server("Main", "h2", 3307, "u", "p2", "d", "accounts")
        self.assertEqual((sid2, created2), (sid, False))
        s = await self.db.get_server(sid)
        self.assertEqual((s.host, s.port, s.db_pass), ("h2", 3307, "p2"))
        self.assertEqual(len(await self.db.list_servers()), 1)

    async def test_binding_unique_and_owner(self):
        sid = await self.db.add_server("Main", "h", 3306, "u", "p", "d")
        bid = await self.db.add_binding(1, sid, 77, "Nick_Name", "pw_salt_upper")
        with self.assertRaises(Exception):  # один аккаунт - один Telegram
            await self.db.add_binding(2, sid, 77, "Nick_Name", "pw_salt_upper")
        b = await self.db.find_binding(sid, 77)
        self.assertEqual((b.id, b.tg_id), (bid, 1))
        await self.db.delete_binding(bid)  # после отвязки можно привязать заново
        await self.db.add_binding(2, sid, 77, "Nick_Name", "pw_salt_upper")

    async def test_delete_server_removes_bindings(self):
        sid = await self.db.add_server("Main", "h", 3306, "u", "p", "d")
        await self.db.add_binding(1, sid, 5, "A_B", "")
        await self.db.delete_server(sid)
        self.assertEqual(await self.db.list_bindings(1), [])

    async def test_failures(self):
        for _ in range(3):
            await self.db.note_failure(10)
        self.assertEqual(await self.db.failures_recent(10, 900), 3)
        self.assertEqual(await self.db.failures_recent(11, 900), 0)
        await self.db.clear_failures(10)
        self.assertEqual(await self.db.failures_recent(10, 900), 0)


if __name__ == "__main__":
    unittest.main()
