import asyncio
import logging

from telethon import TelegramClient
from telethon.errors import (
    AuthKeyUnregisteredError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession
from telethon.tl.functions.channels import DeleteChannelRequest, LeaveChannelRequest
from telethon.tl.functions.messages import (
    DeleteChatRequest,
    DeleteHistoryRequest,
)
from telethon.tl.types import (
    Channel,
    Chat,
    Dialog,
    User,
)

from .config import API_HASH, API_ID
from .database import db

logger = logging.getLogger(__name__)

KIND_PRIVATE = "private"
KIND_GROUP = "group"
KIND_CHANNEL = "channel"
KIND_BOT = "bot"
KIND_UNKNOWN = "unknown"


class LoginError(Exception):
    pass


class Cleaner:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.client = None
        self._login_lock = asyncio.Lock()
        self._entities: dict[int, object] = {}

    @property
    def _session_key(self) -> str:
        return db.session_key(self.user_id)

    async def ensure_client(self) -> TelegramClient | None:
        if self.client and self.client.is_connected():
            try:
                if await self.client.is_user_authorized():
                    return self.client
            except AuthKeyUnregisteredError:
                self.client = None
        session_str = await db.get(self._session_key)
        if not session_str:
            return None
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise LoginError("Сессия недействительна — войдите заново")
        except AuthKeyUnregisteredError:
            await db.set(self._session_key, "")
            await client.disconnect()
            raise LoginError("Сессия недействительна — войдите заново")
        except Exception:
            await client.disconnect()
            raise
        self.client = client
        return client

    async def send_code(self, phone: str) -> TelegramClient:
        async with self._login_lock:
            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()
            try:
                await client.send_code_request(phone)
            except Exception as exc:
                await client.disconnect()
                raise LoginError(f"Не удалось отправить код: {exc}")
            self.client = client
            return client

    async def qr_login(self) -> str:
        """Запускает QR-вход, возвращает URL для рисования QR-кода."""
        async with self._login_lock:
            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()
            qr = await client.qr_login()
            self.client = client
            self._qr = qr
            return qr.url

    @property
    def qr(self):
        return getattr(self, "_qr", None)

    async def qr_wait(self) -> str:
        """Ждёт сканирования QR (до 25 сек). 'ok' | 'password' | 'waiting'."""
        qr = self.qr
        if qr is None:
            raise LoginError("QR-вход не начат")
        try:
            user = await qr.wait(timeout=25)
        except SessionPasswordNeededError:
            return "password"
        except asyncio.TimeoutError:
            return "waiting"
        except Exception as exc:
            raise LoginError(f"Ошибка QR: {exc}")
        await self._persist()
        return "ok"

    async def qr_new(self) -> str | None:
        """Генерирует свежий QR, возвращает URL или None, если нужен пароль 2FA."""
        qr = self.qr
        if qr is None:
            raise LoginError("QR-вход не начат")
        try:
            await qr.recreate()
        except SessionPasswordNeededError:
            return None
        except Exception:
            qr = await self.client.qr_login()
            self._qr = qr
        return qr.url

    async def submit_code(self, phone: str, code: str) -> bool:
        """True = нужен пароль 2FA, False = вошли."""
        if not self.client:
            raise LoginError("Нет активного входа")
        try:
            await self.client.sign_in(phone=phone, code=code)
            await self._persist()
            return False
        except SessionPasswordNeededError:
            return True
        except PhoneCodeExpiredError:
            raise LoginError("Код истёк, запросите новый")
        except Exception as exc:
            raise LoginError(f"Неверный код: {exc}")

    async def submit_password(self, password: str) -> None:
        if not self.client:
            raise LoginError("Нет активного входа")
        try:
            await self.client.sign_in(password=password)
            await self._persist()
        except PasswordHashInvalidError:
            raise LoginError("Неверный пароль 2FA")

    async def _persist(self):
        await db.set(self._session_key, self.client.session.save())

    async def logout(self) -> None:
        if self.client:
            try:
                await self.client.log_out()
            except Exception:
                pass
            await self.client.disconnect()
            self.client = None
        await db.set(self._session_key, "")

    async def me(self) -> dict:
        client = await self.ensure_client()
        if client is None:
            raise LoginError("Нет активной сессии — войдите заново")
        try:
            me = await client.get_me()
        except AuthKeyUnregisteredError:
            await db.set(self._session_key, "")
            self.client = None
            raise LoginError("Сессия недействительна — войдите заново")
        if me is None:
            await db.set(self._session_key, "")
            self.client = None
            raise LoginError("Сессия недействительна — войдите заново")
        return {
            "first": me.first_name or "",
            "last": me.last_name or "",
            "username": me.username or "",
            "phone": me.phone or "",
        }

    async def list_dialogs(self, sort: str = "members") -> list[dict]:
        client = await self.ensure_client()
        if client is None:
            raise LoginError("Нет активной сессии — войдите заново")
        try:
            dialogs: list[Dialog] = await client.get_dialogs(limit=200)
        except AuthKeyUnregisteredError:
            await db.set(self._session_key, "")
            self.client = None
            raise LoginError("Сессия недействительна — войдите заново")
        rows = []
        for d in dialogs:
            entity = d.entity
            self._entities[d.id] = entity
            if isinstance(entity, Channel) and getattr(entity, "megagroup", False):
                kind = KIND_GROUP
                title = entity.title or ""
                members = entity.participants_count or 0
            elif isinstance(entity, Channel):
                kind = KIND_CHANNEL
                title = entity.title or ""
                members = entity.participants_count or 0
            elif isinstance(entity, Chat):
                kind = KIND_GROUP
                title = entity.title or ""
                members = entity.participants_count or 0
            elif isinstance(entity, User):
                kind = KIND_BOT if getattr(entity, "bot", False) else KIND_PRIVATE
                title = d.name or (entity.first_name or "") + " " + (entity.last_name or "")
                members = 0
            else:
                kind = KIND_UNKNOWN
                title = d.name or str(d.id)
                members = 0
            rows.append(
                {
                    "id": d.id,
                    "title": title.strip(),
                    "kind": kind,
                    "members": members,
                    "unread": d.unread_count or 0,
                    "date": int(d.date.timestamp()) if d.date else 0,
                }
            )
        if sort == "members":
            rows.sort(key=lambda r: r["members"], reverse=True)
        elif sort == "unread":
            rows.sort(key=lambda r: r["unread"], reverse=True)
        elif sort == "activity":
            rows.sort(key=lambda r: r["date"], reverse=True)
        elif sort == "name":
            rows.sort(key=lambda r: r["title"].lower())
        elif sort == "type":
            rows.sort(key=lambda r: r["kind"])
        return rows

    async def resolve(self, chat_id: int):
        client = await self.ensure_client()
        entity = self._entities.get(chat_id)
        if entity is None:
            dialogs = await client.get_dialogs(limit=200)
            for d in dialogs:
                self._entities[d.id] = d.entity
            entity = self._entities.get(chat_id)
        if entity is None:
            raise ValueError(f"Чат {chat_id} не найден")
        return await client.get_input_entity(entity)

    async def remove_chat(self, row: dict) -> str:
        """Удаляет/покидает чат. Возвращает описание результата."""
        client = await self.ensure_client()
        peer = await self.resolve(row["id"])
        kind = row["kind"]
        try:
            if kind == KIND_CHANNEL:
                try:
                    await client(DeleteChannelRequest(peer))
                except Exception:
                    await client(LeaveChannelRequest(peer))
            elif kind == KIND_GROUP:
                try:
                    await client(DeleteChatRequest(peer))
                except Exception:
                    await client.kick_participant(peer, "me")
            elif kind == KIND_PRIVATE or kind == KIND_BOT:
                try:
                    await client(DeleteHistoryRequest(peer, max_id=0, revoke=True, just_clear=False))
                except Exception:
                    try:
                        await client(DeleteChatRequest(peer))
                    except Exception:
                        await client(DeleteHistoryRequest(peer, max_id=0, just_clear=True))
            else:
                await client(DeleteHistoryRequest(peer, max_id=0, just_clear=True))
        except Exception as exc:
            logger.exception("Не удалось удалить чат %s", row["id"])
            return f"❌ {row['title']}: {exc}"
        await db.add_removed(self.user_id, row["id"])
        return f"✅ {row['title']}"

    async def sweep_removed(self) -> list[str]:
        """Авто-уборка: чаты из списка removed удаляются снова, если вернулись."""
        if not await self.ensure_client():
            return []
        removed = await db.removed_ids(self.user_id)
        if not removed:
            return []
        dialogs = await self.list_dialogs("activity")
        results = []
        for row in dialogs:
            if row["id"] in removed:
                try:
                    results.append(await self.remove_chat(row))
                except Exception as exc:
                    results.append(f"❌ {row['title']}: {exc}")
        return results


class CleanerPool:
    """По одному Cleaner на пользователя бота."""

    def __init__(self):
        self._items: dict[int, Cleaner] = {}

    def get(self, user_id: int) -> Cleaner:
        if user_id not in self._items:
            self._items[user_id] = Cleaner(user_id)
        return self._items[user_id]


cleaners = CleanerPool()