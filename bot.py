import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from config import BOT_TOKEN, ADMINS
from states import Registration
from keyboards import (
    get_know_target_keyboard,
    get_reset_confirm_keyboard,
    get_hard_reset_confirm_keyboard,
)
from texts import PLAYER_MESSAGES, ADMIN_MESSAGES, BROADCAST_MESSAGES
import db


logging.basicConfig(level=logging.INFO)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Please configure BOT_TOKEN in config.py or Railway Variables.")

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)
dp = Dispatcher()
router = Router()
dp.include_router(router)


# --- ХЕЛПЕР ---
def is_admin(user_id: int) -> bool:
    return user_id in ADMINS


# ╔══════════════════════════════════╗
# ║        ХЕНДЛЕРЫ ИГРОКОВ          ║
# ╚══════════════════════════════════╝

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user = message.from_user
    game_state = db.get_game_state()
    player = db.get_or_create_player(user.id, user.username)

    # ===== Регистрация уже закрыта =====
    if not game_state["registration_open"]:
        if player.get("full_name") and player.get("wish"):
            # Жеребьёвка прошла → можно нажимать «Узнать»
            await message.answer(
                PLAYER_MESSAGES["already_registered_after_draw"],
                reply_markup=get_know_target_keyboard()
            )
        else:
            # Новый человек после закрытия регистрации
            await message.answer(PLAYER_MESSAGES["start_after_close_new"])
        return

    # ===== Регистрация открыта =====
    await state.clear()

    if not player.get("full_name"):
        await message.answer(PLAYER_MESSAGES["start_new"])
        await state.set_state(Registration.waiting_full_name)
    elif not player.get("wish"):
        await message.answer(PLAYER_MESSAGES["ask_wish"])
        await state.set_state(Registration.waiting_wish)
    else:
        # Игрок уже зарегистрирован, но жеребьёвки ещё нет
        await message.answer(PLAYER_MESSAGES["already_registered_waiting_draw"])


@router.message(Registration.waiting_full_name)
async def process_full_name(message: Message, state: FSMContext):
    full_name = (message.text or "").strip()
    if not full_name:
        await message.answer(PLAYER_MESSAGES["ask_full_name_invalid"])
        return

    db.update_full_name(message.from_user.id, full_name)
    await message.answer(PLAYER_MESSAGES["ask_wish"])
    await state.set_state(Registration.waiting_wish)


@router.message(Registration.waiting_wish)
async def process_wish(message: Message, state: FSMContext):
    wish = (message.text or "").strip()
    if not wish:
        await message.answer(PLAYER_MESSAGES["ask_wish_invalid"])
        return

    db.update_wish(message.from_user.id, wish)
    await state.clear()

    # После заполнения — только подтверждение!
    await message.answer(PLAYER_MESSAGES["registration_done_info"])


@router.callback_query(F.data == "know_target")
async def on_know_target(callback: CallbackQuery):
    user = callback.from_user
    player = db.get_player_by_tg(user.id)

    if not player or not player.get("full_name") or not player.get("wish"):
        await callback.message.answer(PLAYER_MESSAGES["know_not_finished_registration"])
        await callback.answer()
        return

    game_state = db.get_game_state()

    if game_state["registration_open"]:
        await callback.message.answer(PLAYER_MESSAGES["know_before_draw"])
        await callback.answer()
        return

    target_id = player.get("target_id")
    if not target_id:
        await callback.message.answer(PLAYER_MESSAGES["know_no_target_error"])
        await callback.answer()
        return

    receiver = db.get_player_by_id(target_id)
    if not receiver:
        await callback.message.answer(PLAYER_MESSAGES["know_no_target_error"])
        await callback.answer()
        return

    text = PLAYER_MESSAGES["know_after_draw"].format(
        target_full_name=receiver.get("full_name", "Участник"),
        target_wish=receiver.get("wish", "Без пожеланий")
    )
    await callback.message.answer(text)
    await callback.answer()



# ╔══════════════════════════════════╗
# ║        ХЕНДЛЕРЫ АДМИНА           ║
# ╚══════════════════════════════════╝

@router.message(Command("players"))
async def cmd_players(message: Message):
    if not is_admin(message.from_user.id):
        return

    players = db.get_all_players()
    if not players:
        await message.answer("Игроков пока нет.")
        return

    lines = ["Список игроков:\n"]

    for p in players:
        statuses = []
        statuses.append("имя ок" if p.get("full_name") else "нет имени")
        statuses.append("пожелания ок" if p.get("wish") else "нет пожеланий")
        statuses.append(f"дарит id={p['target_id']}" if p.get("target_id") else "пара не назначена")

        block = (
            f"id={p['id']} | tg_id={p['tg_id']} | "
            f"@{p['tg_username'] or '-'}\n"
            f"Имя: {p.get('full_name') or '—'}\n"
            f"Статус: {' / '.join(statuses)}\n"
        )
        lines.append(block)

    await message.answer("\n".join(lines), parse_mode=None)


@router.message(Command("status"))
async def cmd_status(message: Message):
    if not is_admin(message.from_user.id):
        return

    state = db.get_game_state()
    all_players = db.get_all_players()
    ready_players = db.get_all_players_ready()

    reg_status = "открыта" if state["registration_open"] else "закрыта"
    pairs_status = "да" if state["pairs_assigned"] else "нет"

    text = ADMIN_MESSAGES["status_template"].format(
        reg_status=reg_status,
        total=len(all_players),
        with_wish=len(ready_players),
        pairs_status=pairs_status,
    )
    await message.answer(text)


@router.message(Command("close_reg"))
async def cmd_close_reg(message: Message):
    if not is_admin(message.from_user.id):
        return

    game_state = db.get_game_state()

    if (not game_state["registration_open"]) and game_state["pairs_assigned"]:
        await message.answer(ADMIN_MESSAGES["close_reg_already_closed"])
        return

    success, count = db.assign_pairs()

    if not success:
        if count < 2:
            await message.answer(ADMIN_MESSAGES["close_reg_not_enough_players"].format(count=count))
        else:
            await message.answer("Ошибка: невозможно распределить пары. Попробуй ещё раз.")
        return

    await message.answer(ADMIN_MESSAGES["close_reg_success"].format(players_count=count))

    # Рассылка игрокам
    players_ready = db.get_all_players_ready()
    for p in players_ready:
        try:
            await bot.send_message(p["tg_id"], BROADCAST_MESSAGES["after_draw_notification"])
            await bot.send_message(
                p["tg_id"],
                PLAYER_MESSAGES["registration_done_ask_know"],
                reply_markup=get_know_target_keyboard()
            )
        except:
            pass


@router.message(Command("test_draw"))
async def cmd_test_draw(message: Message):
    if not is_admin(message.from_user.id):
        return

    state = db.get_game_state()
    if (not state["registration_open"]) and state["pairs_assigned"]:
        await message.answer("Пары уже распределены. Сделай /reset_game или /reset_all.")
        return

    success, count = db.assign_pairs()

    if not success:
        await message.answer("Тестовая жеребьёвка невозможна: мало игроков.")
        return

    await message.answer(
        f"🧪 Тестовая жеребьёвка завершена!\n"
        f"Игроков: {count}\n\n"
        f"Не забудь после теста сделать /reset_game или /reset_all."
    )

    players_ready = db.get_all_players_ready()
    for p in players_ready:
        try:
            await bot.send_message(p["tg_id"], BROADCAST_MESSAGES["after_draw_notification"])
            await bot.send_message(
                p["tg_id"],
                PLAYER_MESSAGES["registration_done_ask_know"],
                reply_markup=get_know_target_keyboard()
            )
        except:
            pass


@router.message(Command("reset_game")))
async def cmd_reset_game(message: Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "⚠ *МЯГКИЙ СБРОС*\n\n"
        "Удаляются имена, пожелания и пары.\n"
        "Игроки остаются в системе.\n\n"
        "Подтверди действие:",
        reply_markup=get_reset_confirm_keyboard()
    )


@router.callback_query(F.data == "admin_reset_game_confirm")
async def admin_reset_game(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return

    db.reset_game()
    await callback.message.answer("♻ Мягкий сброс выполнен. Регистрация снова открыта.")
    await callback.answer()


@router.message(Command("reset_all")))
async def cmd_reset_all(message: Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "🗑 *ПОЛНЫЙ СБРОС*\n\n"
        "Удаляются ВСЕ игроки, ВСЕ данные и пары.\n"
        "Игра начнётся полностью заново.\n\n"
        "Подтверди действие:",
        reply_markup=get_hard_reset_confirm_keyboard()
    )


@router.callback_query(F.data == "admin_hard_reset_game_confirm")
async def admin_hard_reset(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return

    db.hard_reset_game()
    await callback.message.answer("🗑 Полный сброс выполнен. Можно начинать новую игру.")
    await callback.answer()


# ╔══════════════════════════════════╗
# ║       help_admin (новая)         ║
# ╚══════════════════════════════════╝

@router.message(Command("help_admin"))
async def cmd_help_admin(message: Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "*Команды администратора:*\n\n"
        "/players — список игроков\n"
        "/status — состояние игры\n"
        "/close_reg — боевая жеребьёвка\n"
        "/test_draw — тестовая жеребьёвка\n"
        "/reset_game — мягкий сброс\n"
        "/reset_all — полный сброс\n"
        "/help_admin — список команд\n"
    )


# ╔══════════════════════════════════╗
# ║              MAIN                ║
# ╚══════════════════════════════════╝

async def main():
    db.init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
