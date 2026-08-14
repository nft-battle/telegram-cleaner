import re
from datetime import datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery

from ..config import PAGE_SIZE
from ..database import db
from ..keyboards import (
    KIND_ICON,
    confirm_kb,
    dlg_page_kb,
    dlg_sort_kb,
)
from ..texts import BULK_CONFIRM, BULK_DONE, DLG_HEADER, DLG_ROW, NOT_AUTORIZED
from ..userbot import cleaners

router = Router()

SORT_LABELS = {
    "members": "👥 по участникам",
    "unread": "🔔 по непрочитанным",
    "activity": "🕒 по активности",
    "name": "🔤 по алфавиту",
    "type": "🗂 по типу",
}

_selected: dict[int, set[int]] = {}


def _fmt_date(ts: int) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%d.%m %H:%M")


def _cl(c: CallbackQuery):
    return cleaners.get(c.from_user.id)


async def _ensure(c: CallbackQuery) -> bool:
    if not await _cl(c).ensure_client():
        await c.answer(NOT_AUTORIZED, show_alert=True)
        return False
    return True


async def _send_list(c: CallbackQuery, sort: str, page: int):
    rows = await _cl(c).list_dialogs(sort)
    total_pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(1, page), total_pages)
    start = (page - 1) * PAGE_SIZE
    chunk = rows[start : start + PAGE_SIZE]
    sel = _selected.get(c.from_user.id, set())
    lines = [DLG_HEADER.format(sort_label=SORT_LABELS.get(sort, sort), page=page, total=total_pages, sel=len(sel))]
    page_ids = []
    for r in chunk:
        mark = "☑️" if r["id"] in sel else "⬜️"
        title = r["title"] or f"id {r['id']}"
        lines.append(
            DLG_ROW.format(
                icon=KIND_ICON.get(r["kind"], "❓"),
                title=(mark + " " + title),
                members=r["members"],
                unread=r["unread"],
                date=_fmt_date(r["date"]),
            )
        )
        page_ids.append(r["id"])
    text = "".join(lines)
    if not chunk:
        text = "📋 <b>Диалоги</b>\n\nПусто — чатов нет."
    kb = dlg_page_kb(sort, page, total_pages, sel, page_ids)
    await c.message.edit_text(text, reply_markup=kb)
    await c.answer()


@router.callback_query(F.data.startswith("dlg:list:"))
async def cb_list(c: CallbackQuery):
    if not await _ensure(c):
        return
    _, _, sort, page = c.data.split(":")
    await _send_list(c, sort, int(page))


@router.callback_query(F.data.startswith("dlg:sort:"))
async def cb_sort(c: CallbackQuery):
    if not await _ensure(c):
        return
    sort = c.data.split(":", 2)[2]
    await c.message.edit_text(
        "↩️ <b>Сортировка</b>",
        reply_markup=dlg_sort_kb(sort),
    )
    await c.answer()


@router.callback_query(F.data.startswith("dlg:toggle:"))
async def cb_toggle(c: CallbackQuery):
    parts = c.data.split(":")
    chat_id = int(parts[2])
    sort = parts[3] if len(parts) > 3 else "members"
    sel = _selected.setdefault(c.from_user.id, set())
    if chat_id in sel:
        sel.discard(chat_id)
    else:
        sel.add(chat_id)
    await c.answer("Выбрано: %d" % len(sel))
    await _send_list(c, sort, 1)


@router.callback_query(F.data.startswith("dlg:one:"))
async def cb_one(c: CallbackQuery):
    if not await _ensure(c):
        return
    chat_id = int(c.data.split(":")[2])
    kb = confirm_kb("one", [chat_id])
    name = ""
    try:
        rows = await _cl(c).list_dialogs("name")
        name = next((r["title"] for r in rows if r["id"] == chat_id), "")
    except Exception:
        pass
    await c.message.edit_text(
        BULK_CONFIRM.format(n=1, names=f"• {name or chat_id}"),
        reply_markup=kb,
    )
    await c.answer()


@router.callback_query(F.data.startswith("dlg:bulk:"))
async def cb_bulk(c: CallbackQuery):
    if not await _ensure(c):
        return
    sel = _selected.get(c.from_user.id, set())
    if not sel:
        await c.answer("Нет выбранных чатов", show_alert=True)
        return
    if c.data == "dlg:bulk:confirm":
        rows = await _cl(c).list_dialogs("name")
        names = []
        for r in rows:
            if r["id"] in sel:
                names.append(f"• {r['title']}")
        await c.message.edit_text(
            BULK_CONFIRM.format(n=len(sel), names="\n".join(names) if names else "(без названий)"),
            reply_markup=confirm_kb("bulk", list(sel)),
        )
        await c.answer()
        return
    await c.answer()


@router.callback_query(F.data.startswith("dlg:do:"))
async def cb_do(c: CallbackQuery):
    if not await _ensure(c):
        return
    parts = c.data.split(":", 3)
    mode = parts[2]
    ids = [int(x) for x in parts[3].split(",") if x]
    await c.message.edit_text("⏳ Чистим...")
    await c.answer()
    results = []
    for chat_id in ids:
        row = None
        try:
            rows = await _cl(c).list_dialogs("name")
            row = next((r for r in rows if r["id"] == chat_id), {"id": chat_id, "title": str(chat_id), "kind": "unknown"})
        except Exception:
            row = {"id": chat_id, "title": str(chat_id), "kind": "unknown"}
        try:
            res = await _cl(c).remove_chat(row)
        except Exception as exc:
            res = f"❌ {row['title']}: {exc}"
        results.append(res)
    if mode == "bulk":
        _selected[c.from_user.id] = set()
    await c.message.edit_text(BULK_DONE.format(results="\n".join(results)))


@router.callback_query(F.data == "noop")
async def cb_noop(c: CallbackQuery):
    await c.answer()


@router.callback_query(F.data == "dlg:list")
async def cb_list_default(c: CallbackQuery):
    if not await _ensure(c):
        return
    await _send_list(c, "members", 1)