import asyncio
import io

import qrcode
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message, ReplyKeyboardRemove

from ..database import db
from ..keyboards import autokill_kb, login_kb, main_kb, phone_kb
from ..texts import (
    ASK_CODE,
    ASK_PASSWORD,
    ASK_PHONE,
    CANCELED,
    LOGIN_FAIL,
    LOGIN_METHOD,
    LOGIN_OK,
    ME_TEXT,
    NOT_AUTORIZED,
    QR_NEED_PASSWORD,
    QR_WAIT,
    WELCOME,
)
from ..states import LoginFSM
from ..userbot import LoginError, cleaners

router = Router()


def _uid(m: Message | CallbackQuery) -> int:
    return m.from_user.id


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    cleaner = cleaners.get(_uid(message))
    authed = bool(await cleaner.ensure_client())
    autokill = await db.get(db.autokill_key(_uid(message))) == "1"
    await message.answer(WELCOME, reply_markup=main_kb(authed, autokill))


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    await cmd_start(message, state)


@router.callback_query(F.data == "home")
async def cb_home(c: CallbackQuery, state: FSMContext):
    await state.clear()
    cleaner = cleaners.get(_uid(c))
    authed = bool(await cleaner.ensure_client())
    autokill = await db.get(db.autokill_key(_uid(c))) == "1"
    await c.message.edit_text(WELCOME, reply_markup=main_kb(authed, autokill))
    await c.answer()


@router.callback_query(F.data == "cancel")
async def cb_cancel(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.edit_text(CANCELED, reply_markup=main_kb(False, False))
    await c.message.answer("✖️", reply_markup=ReplyKeyboardRemove())
    await c.answer()


@router.callback_query(F.data == "login")
async def cb_login(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.edit_text(LOGIN_METHOD, reply_markup=login_kb())
    await c.answer()


@router.callback_query(F.data == "login:phone")
async def cb_login_phone(c: CallbackQuery, state: FSMContext):
    await state.set_state(LoginFSM.phone)
    await c.message.answer("📞 Введите номер телефона:", reply_markup=phone_kb())
    await c.answer()


def _qr_png(url: str) -> BufferedInputFile:
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return BufferedInputFile(buf.read(), filename="qr.png")


@router.callback_query(F.data == "login:qr")
async def cb_login_qr(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    cleaner = cleaners.get(_uid(c))
    try:
        url = await cleaner.qr_login()
    except LoginError as exc:
        await c.message.answer(LOGIN_FAIL.format(error=exc))
        return
    photo = await c.message.answer_photo(_qr_png(url), caption=QR_WAIT)
    while True:
        status = await cleaner.qr_wait()
        if status == "ok":
            me = await cleaner.me()
            await photo.edit_caption(
                LOGIN_OK.format(
                    info=f"👤 {me['first']} {me['last']} · @{me['username']} · {me['phone']}"
                )
            )
            return
        if status == "password":
            await state.set_state(LoginFSM.password)
            await c.message.answer(QR_NEED_PASSWORD, reply_markup=login_kb())
            return
        # waiting: QR мог истечь (30 сек) — обновляем
        await asyncio.sleep(2)
        try:
            url = await cleaner.qr_new()
        except LoginError as exc:
            await c.message.answer(LOGIN_FAIL.format(error=exc))
            return
        if url is None:
            await state.set_state(LoginFSM.password)
            await c.message.answer(QR_NEED_PASSWORD, reply_markup=login_kb())
            return
        from aiogram.types import InputMediaPhoto

        await photo.edit_media(InputMediaPhoto(media=_qr_png(url)))


@router.message(LoginFSM.phone, F.contact)
async def on_contact(message: Message, state: FSMContext):
    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone
    await state.update_data(phone=phone)
    await _request_code(message, state, phone)


async def _request_code(message: Message, state: FSMContext, phone: str):
    await message.answer("📲 Код отправлен!", reply_markup=ReplyKeyboardRemove())
    cleaner = cleaners.get(_uid(message))
    try:
        await cleaner.send_code(phone)
    except LoginError as exc:
        await message.answer(LOGIN_FAIL.format(error=exc))
        return
    await state.set_state(LoginFSM.code)
    await message.answer(ASK_CODE, reply_markup=login_kb())


@router.message(LoginFSM.phone, F.text)
async def on_phone(message: Message, state: FSMContext):
    phone = message.text.strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+"):
        await message.answer("❌ Номер должен начинаться с + (например +79991234567).")
        return
    await state.update_data(phone=phone)
    await _request_code(message, state, phone)


@router.message(LoginFSM.code, F.text)
async def on_code(message: Message, state: FSMContext):
    data = await state.get_data()
    code = message.text.strip().replace(" ", "")
    cleaner = cleaners.get(_uid(message))
    try:
        need_password = await cleaner.submit_code(data["phone"], code)
    except LoginError as exc:
        await message.answer(LOGIN_FAIL.format(error=exc))
        return
    if need_password:
        await state.set_state(LoginFSM.password)
        await message.answer(ASK_PASSWORD, reply_markup=login_kb())
        return
    await _finish_login(message, state)


async def _finish_login(message: Message, state: FSMContext):
    await state.clear()
    me = await cleaners.get(_uid(message)).me()
    await message.answer(
        LOGIN_OK.format(
            info=f"👤 {me['first']} {me['last']} · @{me['username']} · {me['phone']}"
        ),
        reply_markup=main_kb(
            authed=True,
            autokill=await db.get(db.autokill_key(_uid(message))) == "1",
        ),
    )


@router.message(LoginFSM.password, F.text)
async def on_password(message: Message, state: FSMContext):
    try:
        await cleaners.get(_uid(message)).submit_password(message.text)
    except LoginError as exc:
        await message.answer(LOGIN_FAIL.format(error=exc))
        return
    await _finish_login(message, state)


@router.callback_query(F.data == "me")
async def cb_me(c: CallbackQuery):
    cleaner = cleaners.get(_uid(c))
    if not await cleaner.ensure_client():
        await c.answer(NOT_AUTORIZED, show_alert=True)
        return
    me = await cleaner.me()
    await c.message.edit_text(
        ME_TEXT.format(
            name=f"{me['first']} {me['last']}".strip() or "—",
            phone=me["phone"] or "—",
            username=me["username"] or "—",
        ),
        reply_markup=main_kb(True, await db.get(db.autokill_key(_uid(c))) == "1"),
    )
    await c.answer()


@router.callback_query(F.data.startswith("autokill"))
async def cb_autokill(c: CallbackQuery):
    uid = _uid(c)
    key = db.autokill_key(uid)
    data = c.data
    enabled = await db.get(key) == "1"
    if "on" in data:
        await db.set(key, "1")
        enabled = True
    elif "off" in data:
        await db.set(key, "0")
        enabled = False
    await c.message.edit_text(
        f"🧹 <b>Авто-уборка</b>\n\nСейчас: {'✅ ВКЛ' if enabled else '❌ ВЫКЛ'}",
        reply_markup=autokill_kb(enabled),
    )
    await c.answer()