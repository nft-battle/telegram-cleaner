from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..config import WEBAPP_URL
from .userbot import KIND_BOT, KIND_CHANNEL, KIND_GROUP, KIND_PRIVATE

KIND_ICON = {
    KIND_PRIVATE: "💬",
    KIND_BOT: "🤖",
    KIND_GROUP: "👥",
    KIND_CHANNEL: "📢",
}


def main_kb(authed: bool, autokill: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(
            text="🚀 Открыть приложение",
            web_app=WebAppInfo(url=WEBAPP_URL),
        )
    )
    if authed:
        b.row(
            InlineKeyboardButton(text="📋 Список диалогов", callback_data="dlg:list:members:1"),
            InlineKeyboardButton(text="🧹 Авто-уборка: " + ("ВКЛ" if autokill else "ВЫКЛ"), callback_data="autokill"),
        )
        b.row(InlineKeyboardButton(text="👤 Мой аккаунт", callback_data="me"))
    else:
        b.row(InlineKeyboardButton(text="🔑 Войти в аккаунт", callback_data="login"))
    return b.as_markup()


def login_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📱 Войти по номеру", callback_data="login:phone"))
    b.row(InlineKeyboardButton(text="🖼 Войти по QR-коду", callback_data="login:qr"))
    b.row(InlineKeyboardButton(text="✖️ Отмена", callback_data="cancel"))
    return b.as_markup()


def phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def autokill_kb(enabled: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(
            text="✅ Включить" if not enabled else "❌ Выключить",
            callback_data="autokill:" + ("on" if not enabled else "off"),
        )
    )
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="home"))
    return b.as_markup()


def dlg_sort_kb(sort: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    cur = {
        "members": "📊 По участникам",
        "unread": "🔔 По непрочитанным",
        "activity": "🕒 По активности",
        "name": "🔤 По алфавиту",
        "type": "🗂 По типу",
    }
    for key, label in cur.items():
        mark = "●" if key == sort else "○"
        b.add(InlineKeyboardButton(text=f"{mark} {label}", callback_data=f"dlg:list:{key}:1"))
    b.adjust(1)
    return b.as_markup()


def dlg_page_kb(sort: str, page: int, total_pages: int, selected: set[int], chat_ids: list[int]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for cid in chat_ids:
        sel = "☑️" if cid in selected else "⬜️"
        b.row(
            InlineKeyboardButton(text=f"{sel} Выбрать", callback_data=f"dlg:toggle:{cid}:{sort}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"dlg:one:{cid}"),
        )
    b.row(InlineKeyboardButton(text="↩️ Сортировка", callback_data=f"dlg:sort:{sort}"))
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"dlg:list:{sort}:{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"dlg:list:{sort}:{page+1}"))
        b.row(*nav)
    if selected:
        b.row(
            InlineKeyboardButton(
                text=f"🗑 Удалить выбранные ({len(selected)})",
                callback_data="dlg:bulk:confirm",
            )
        )
    b.row(InlineKeyboardButton(text="🏠 Меню", callback_data="home"))
    return b.as_markup()


def confirm_kb(action: str, chat_ids: list[int]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    ids = ",".join(str(x) for x in chat_ids)
    b.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"dlg:do:{action}:{ids}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="dlg:list:members:1"),
    )
    return b.as_markup()