import asyncio
import base64
import io
import json
import logging

import qrcode
from aiohttp import web

from .database import db
from .userbot import LoginError, cleaners

logger = logging.getLogger(__name__)

_qr_tasks: dict[int, asyncio.Task] = {}
_qr_results: dict[int, str] = {}


def _json(data, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, dumps=lambda o: json.dumps(o, ensure_ascii=False))


def _qr_png_b64(url: str) -> str:
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _cl(user_id: int):
    return cleaners.get(user_id)


async def _qr_waiter(user_id: int) -> None:
    """Крутится в фоне: ждёт сканирования, пишет результат для этого пользователя."""
    cleaner = _cl(user_id)
    _qr_results[user_id] = "waiting"
    while True:
        try:
            status = await cleaner.qr_wait()
        except LoginError as exc:
            _qr_results[user_id] = f"error:{exc}"
            return
        if status == "ok":
            _qr_results[user_id] = "ok"
            return
        if status == "password":
            _qr_results[user_id] = "password"
            return
        # waiting — проверяем, не умер ли QR
        if cleaner.qr is None:
            return
        await asyncio.sleep(2)


def _start_waiter(user_id: int) -> None:
    task = _qr_tasks.get(user_id)
    if task and not task.done():
        task.cancel()
    _qr_tasks[user_id] = asyncio.get_event_loop().create_task(_qr_waiter(user_id))


def _uid(request: web.Request) -> int:
    return int(request.query.get("user_id", "0"))


async def api_me(request: web.Request) -> web.Response:
    cleaner = _cl(_uid(request))
    try:
        client = await cleaner.ensure_client()
    except LoginError as exc:
        return _json({"ok": False, "error": str(exc)})
    if client is None:
        return _json({"ok": True, "authed": False})
    try:
        me = await cleaner.me()
    except LoginError as exc:
        return _json({"ok": False, "error": str(exc)})
    return _json({"ok": True, "authed": True, **me})


async def api_qr_start(request: web.Request) -> web.Response:
    user_id = _uid(request)
    cleaner = _cl(user_id)
    try:
        url = await cleaner.qr_login()
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})
    _start_waiter(user_id)
    return _json({"ok": True, "qr": _qr_png_b64(url)})


async def api_qr_refresh(request: web.Request) -> web.Response:
    user_id = _uid(request)
    cleaner = _cl(user_id)
    try:
        url = await cleaner.qr_new()
    except LoginError as exc:
        return _json({"ok": False, "error": str(exc)})
    if url is None:
        _qr_results[user_id] = "password"
        return _json({"ok": True, "qr": None})
    _start_waiter(user_id)
    return _json({"ok": True, "qr": _qr_png_b64(url)})


async def api_qr_status(request: web.Request) -> web.Response:
    user_id = _uid(request)
    return _json({"ok": True, "status": _qr_results.get(user_id, "none")})


async def api_login_password(request: web.Request) -> web.Response:
    cleaner = _cl(_uid(request))
    try:
        payload = await request.json()
    except Exception:
        return _json({"ok": False, "error": "bad json"}, 400)
    try:
        await cleaner.submit_password(payload.get("password", ""))
    except LoginError as exc:
        return _json({"ok": False, "error": str(exc)})
    return _json({"ok": True})


async def api_logout(request: web.Request) -> web.Response:
    await _cl(_uid(request)).logout()
    return _json({"ok": True})


async def api_dialogs(request: web.Request) -> web.Response:
    user_id = _uid(request)
    cleaner = _cl(user_id)
    sort = request.query.get("sort", "members")
    try:
        rows = await cleaner.list_dialogs(sort)
    except LoginError as exc:
        return _json({"ok": False, "error": str(exc)})
    removed = await db.removed_ids(user_id)
    return _json({"ok": True, "rows": rows, "removed": len(removed)})


async def api_remove(request: web.Request) -> web.Response:
    user_id = _uid(request)
    cleaner = _cl(user_id)
    try:
        payload = await request.json()
    except Exception:
        return _json({"ok": False, "error": "bad json"}, 400)
    rows_all = []
    try:
        rows_all = await cleaner.list_dialogs("name")
    except Exception:
        pass
    ids = [int(x) for x in payload.get("ids", [])]
    results = []
    for chat_id in ids:
        row = next(
            (r for r in rows_all if r["id"] == chat_id),
            {"id": chat_id, "title": str(chat_id), "kind": "unknown"},
        )
        try:
            res = await cleaner.remove_chat(row)
        except Exception as exc:
            res = f"❌ {row['title']}: {exc}"
        results.append(res)
    return _json({"ok": True, "results": results})


async def api_autokill(request: web.Request) -> web.Response:
    user_id = _uid(request)
    key = db.autokill_key(user_id)
    if request.method == "POST":
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if payload is not None and "enabled" in payload:
            await db.set(key, "1" if payload["enabled"] else "0")
    enabled = await db.get(key) == "1"
    return _json({"ok": True, "enabled": enabled})


def make_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/me", api_me)
    app.router.add_get("/qr/start", api_qr_start)
    app.router.add_get("/qr/refresh", api_qr_refresh)
    app.router.add_get("/qr/status", api_qr_status)
    app.router.add_post("/login/password", api_login_password)
    app.router.add_post("/logout", api_logout)
    app.router.add_get("/dialogs", api_dialogs)
    app.router.add_post("/remove", api_remove)
    app.router.add_get("/autokill", api_autokill)
    app.router.add_post("/autokill", api_autokill)
    return app