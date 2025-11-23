# bot.py
"""Main Telegram bot entrypoint for the Secret Santa game."""

import asyncio
import logging
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import db
from config import ADMINS, BOT_TOKEN
from keyboards import (
    get_hard_reset_confirm_keyboard,
    get_know_target_keyboard,
    get_reset_confirm_keyboard,
)
from states import Registration
from texts import ADMIN_MESSAGES, BROADCAST_MESSAGES, PLAYER_MESSAGES


logging.basicConfig(level=logging.INFO)

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is not set. Please configure it via config.py or environment variable."
    )

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()
router = Router()
dp.include_router(router)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_admin(user_id: int) -> bool:
    """Return True if the Telegram user is an administrator."""

    return user_id in ADMINS


def _answer_text(message: Message, text: str, *, parse_mode: Optional[str] = None, **kwargs):
    """Send a text reply keeping code concise."""

    return message.answer(text, parse_mode=parse_mode, **kwargs)


# ---------------------------------------------------------------------------
# Player handlers
# ---------------------------------------------------------------------------


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Entry point for all players."""

    user = message.from_user
    game_state = db.get_game_state()
    player = db.get_or_create_player(user.id, user.username)

    # Registration closed
    if not game_state["registration_open"]:
        if player.get("full_name") and player.get("wish"):
            # Already registered. If pairs assigned, offer to check the target.
            text = PLAYER_MESSAGES["registration_done_info"]
            if game_state["pairs_assigned"]:
                await _answer_text(
                    message,
                    PLAYER_MESSAGES["registration_done_ask_know"],
                    reply_markup=get_know_target_keyboard(),
                )
            else:
                await _answer_text(message, text)
        else:
            await _answer_text(message, PLAYER_MESSAGES["start_after_close_new"])
        return

    await state.clear()

    if not player.get("full_name"):
        prompt = PLAYER_MESSAGES["start_new"] if player.get("wish") is None else PLAYER_MESSAGES["continue_no_name"]
        await _answer_text(message, prompt)
        await state.set_state(Registration.waiting_full_name)
    elif not player.get("wish"):
        await _answer_text(message, PLAYER_MESSAGES["ask_wish"])
        await state.set_state(Registration.waiting_wish)
    else:
        await _answer_text(message, PLAYER_MESSAGES["already_registered_waiting_draw"])


@router.message(Registration.waiting_full_name)
async def process_full_name(message: Message, state: FSMContext):
    """Handle player's full name input."""

    if not message.text:
        await _answer_text(message, PLAYER_MESSAGES["ask_full_name_invalid"])
        return

    text = message.text.strip()
    if text.startswith("/"):
        await _answer_text(message, PLAYER_MESSAGES["ask_full_name_invalid"])
        return

    db.update_full_name(message.from_user.id, text)

    await _answer_text(message, PLAYER_MESSAGES["ask_wish"])
    await state.set_state(Registration.waiting_wish)


@router.message(Registration.waiting_wish)
async def process_wish(message: Message, state: FSMContext):
    """Handle player's gift preferences."""

    if not message.text:
        await _answer_text(message, PLAYER_MESSAGES["ask_wish_invalid"])
        return

    text = message.text.strip()
    if text.startswith("/"):
        await _answer_text(message, PLAYER_MESSAGES["ask_wish_invalid"])
        return

    db.update_wish(message.from_user.id, text)
    await state.clear()

    await _answer_text(message, PLAYER_MESSAGES["registration_done_info"])


@router.callback_query(F.data == "know_target")
async def on_know_target(callback: CallbackQuery):
    """Show player's Secret Santa target after the draw."""

    user = callback.from_user
    player = db.get_player_by_tg(user.id)

    if not player or not player.get("full_name") or not player.get("wish"):
        await _answer_text(
            callback.message,
            PLAYER_MESSAGES["know_not_finished_registration"],
        )
        await callback.answer()
        return

    game_state = db.get_game_state()
    if game_state["registration_open"]:
        await _answer_text(callback.message, PLAYER_MESSAGES["know_before_draw"])
        await callback.answer()
        return

    target_id = player.get("target_id")
    if not target_id:
        await _answer_text(callback.message, PLAYER_MESSAGES["know_no_target_error"])
        await callback.answer()
        return

    receiver = db.get_player_by_id(target_id)
    if not receiver:
        await _answer_text(callback.message, PLAYER_MESSAGES["know_no_target_error"])
        await callback.answer()
        return

    text = PLAYER_MESSAGES["know_after_draw"].format(
        target_full_name=receiver.get("full_name", "Участник"),
        target_wish=receiver.get("wish", "Без пожеланий"),
    )
    await _answer_text(callback.message, text)
    await callback.answer()


# ---------------------------------------------------------------------------
# Admin handlers
# ---------------------------------------------------------------------------


@router.message(Command("players"))
async def cmd_players(message: Message):
    """List all players and their readiness status."""

    if not is_admin(message.from_user.id):
        return

    players = db.get_all_players()
    if not players:
        await _answer_text(message, ADMIN_MESSAGES["no_players"], parse_mode=None)
        return

    blocks = ["Список игроков:\n"]
    for player in players:
        statuses = []
        statuses.append("имя ок" if player.get("full_name") else "нет имени")
        statuses.append("пожелания ок" if player.get("wish") else "нет пожеланий")
        statuses.append("пара назначена" if player.get("target_id") else "пара не назначена")

        block = (
            f"id={player['id']} | tg_id={player['tg_id']} | "
            f"@{player['tg_username'] if player.get('tg_username') else '-'}\n"
            f"Имя: {player.get('full_name') or '— не указано'}\n"
            f"Статус: {' / '.join(statuses)}\n"
        )
        blocks.append(block)

    await _answer_text(message, "\n".join(blocks), parse_mode=None)


@router.message(Command("help_admin"))
async def cmd_help_admin(message: Message):
    """Show admin-only commands."""

    if not is_admin(message.from_user.id):
        return

    text = (
        "Команды администратора:\n\n"
        "/players — список игроков и их статусы\n"
        "/status — состояние игры\n"
        "/close_reg — боевая жеребьёвка\n"
        "/test_draw — тестовая жеребьёвка\n"
        "/pairs — показать, кто кому дарит (кроме самого админа)\n"
        "/reset_game — мягкий сброс\n"
        "/reset_all — полный сброс\n"
        "/help_admin — показать список команд\n"
    )

    await _answer_text(message, text, parse_mode=None)


@router.message(Command("pairs"))
async def cmd_pairs(message: Message):
    """Display all assigned pairs except the admin's own target."""

    if not is_admin(message.from_user.id):
        return

    admin_tg_id = message.from_user.id
    players_ready = db.get_all_players_ready()
    if not players_ready:
        await _answer_text(
            message,
            "Пока нет игроков с заполненными данными.",
            parse_mode=None,
        )
        return

    lines = ["Список пар Тайных Сант:\n"]
    admin_has_pair = False

    for santa in players_ready:
        target_id = santa.get("target_id")
        if not target_id:
            continue

        if santa["tg_id"] == admin_tg_id:
            admin_has_pair = True
            continue

        receiver = db.get_player_by_id(target_id)
        if not receiver:
            continue

        santa_name = santa.get("full_name") or "Без имени"
        santa_username = santa.get("tg_username") or "-"
        receiver_name = receiver.get("full_name") or "Без имени"
        receiver_wish = receiver.get("wish") or "Без пожеланий"

        lines.append(
            f"{santa_name} (@{santa_username}) → {receiver_name}\n"
            f"Пожелания получателя: {receiver_wish}\n"
        )

    if len(lines) == 1:
        await _answer_text(
            message,
            "Пары ещё не распределены или нет готовых игроков.",
            parse_mode=None,
        )
        return

    if admin_has_pair:
        lines.append(
            "\nТы тоже участвуешь как игрок 🎅\n"
            "Твоя собственная пара скрыта, чтобы сохранить сюрприз 🙂",
        )

    await _answer_text(message, "\n".join(lines), parse_mode=None)


@router.message(Command("status"))
async def cmd_status(message: Message):
    """Show overall game status to admin."""

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
    await _answer_text(message, text)


@router.message(Command("close_reg"))
async def cmd_close_reg(message: Message):
    """Run the actual draw and close registration."""

    if not is_admin(message.from_user.id):
        return

    game_state = db.get_game_state()
    if (not game_state["registration_open"]) and game_state["pairs_assigned"]:
        await _answer_text(message, ADMIN_MESSAGES["close_reg_already_closed"])
        return

    success, count = db.assign_pairs()
    if not success:
        if count < 2:
            await _answer_text(
                message,
                ADMIN_MESSAGES["close_reg_not_enough_players"].format(count=count),
            )
        else:
            await _answer_text(
                message,
                "Не удалось корректно распределить пары. Попробуй ещё раз.",
            )
        return

    await _answer_text(
        message,
        ADMIN_MESSAGES["close_reg_success"].format(players_count=count),
    )

    players_ready = db.get_all_players_ready()
    for player in players_ready:
        try:
            await bot.send_message(
                player["tg_id"], BROADCAST_MESSAGES["after_draw_notification"]
            )
            await bot.send_message(
                player["tg_id"],
                PLAYER_MESSAGES["registration_done_ask_know"],
                reply_markup=get_know_target_keyboard(),
            )
        except Exception as exc:  # pragma: no cover - network dependent
            logging.warning(
                "Не удалось отправить сообщение игроку %s: %s", player["tg_id"], exc
            )


@router.message(Command("test_draw"))
async def cmd_test_draw(message: Message):
    """Run a test draw without resetting the database."""

    if not is_admin(message.from_user.id):
        return

    game_state = db.get_game_state()
    if (not game_state["registration_open"]) and game_state["pairs_assigned"]:
        await _answer_text(
            message,
            "Пары уже распределены.\n\n"
            "Чтобы запустить тестовую жеребьёвку ещё раз, сначала сделай /reset_game или /reset_all.",
        )
        return

    success, count = db.assign_pairs()
    if not success:
        if count < 2:
            await _answer_text(
                message,
                "Тестовая жеребьёвка невозможна.\n\n"
                + ADMIN_MESSAGES["close_reg_not_enough_players"].format(count=count),
            )
        else:
            await _answer_text(
                message,
                "Не удалось корректно распределить тестовые пары. Попробуй ещё раз.",
            )
        return

    await _answer_text(
        message,
        "🧪 *Тестовая жеребьёвка завершена!*\n\n"
        f"Игроков в тесте: *{count}*.\n"
        "Пары сохранены в БД, игроки получили уведомления и могут нажимать «Узнать».\n\n"
        "Когда закончишь тест, выполни команду /reset_game или /reset_all, чтобы всё сбросить.",
    )

    players_ready = db.get_all_players_ready()
    for player in players_ready:
        try:
            await bot.send_message(
                player["tg_id"], BROADCAST_MESSAGES["after_draw_notification"]
            )
            await bot.send_message(
                player["tg_id"],
                PLAYER_MESSAGES["registration_done_ask_know"],
                reply_markup=get_know_target_keyboard(),
            )
        except Exception as exc:  # pragma: no cover - network dependent
            logging.warning(
                "[TEST DRAW] Не удалось отправить сообщение игроку %s: %s",
                player["tg_id"],
                exc,
            )


@router.message(Command("reset_game"))
async def cmd_reset_game(message: Message):
    """Soft reset: clear names, wishes, and pairs while keeping players."""

    if not is_admin(message.from_user.id):
        return

    warning = (
        "⚠ *МЯГКИЙ СБРОС ИГРЫ*\n\n"
        "Будут удалены *имена, пожелания и все пары*, но список игроков сохранится.\n"
        "Игроки смогут зарегистрироваться заново.\n\n"
        "Подтверди действие кнопкой ниже:"
    )

    await _answer_text(message, warning, reply_markup=get_reset_confirm_keyboard())


@router.callback_query(F.data == "admin_reset_game_confirm")
async def admin_reset_confirm(callback: CallbackQuery):
    """Confirm soft reset."""

    if not is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    db.reset_game()

    await _answer_text(
        callback.message,
        "♻ Мягкий сброс выполнен!\n\n"
        "Имена, пожелания и пары очищены.\n"
        "Регистрация снова открыта. 🎅",
    )
    await callback.answer()


@router.message(Command("reset_all"))
async def cmd_reset_all(message: Message):
    """Hard reset: wipe all players and restart the game."""

    if not is_admin(message.from_user.id):
        return

    warning = (
        "🗑 *ПОЛНЫЙ СБРОС ИГРЫ*\n\n"
        "Ты собираешься *полностью* удалить всех зарегистрированных игроков и начать игру с нуля.\n\n"
        "Будут удалены *все игроки, их пожелания и пары*.\n"
        "ЭТО ДЕЙСТВИЕ НЕОБРАТИМО.\n\n"
        "Если ты уверен, нажми кнопку ниже:"
    )

    await _answer_text(message, warning, reply_markup=get_hard_reset_confirm_keyboard())


@router.callback_query(F.data == "admin_hard_reset_game_confirm")
async def admin_hard_reset_confirm(callback: CallbackQuery):
    """Confirm full reset."""

    if not is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    db.hard_reset_game()

    await _answer_text(
        callback.message,
        "🗑 *Полный сброс выполнен!*\n\n"
        "Все игроки удалены, регистрация открыта.\n"
        "Можно начинать абсолютно новую игру 🎅",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Fallback handler must stay last
# ---------------------------------------------------------------------------


@router.message()
async def fallback_message(message: Message):
    """Default reply for unknown commands/messages."""

    if is_admin(message.from_user.id):
        await _answer_text(
            message,
            "Я не понимаю эту команду.\n"
            "Используй /help_admin, чтобы посмотреть доступные команды администратора.",
            parse_mode=None,
        )
        return

    await _answer_text(
        message,
        "Я пока понимаю только команды, связанные с игрой Тайный Санта 🎅\n\n"
        "Нажми /start, чтобы начать или продолжить участие в игре.",
        parse_mode=None,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    """Initialize storage and start polling."""

    db.init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
