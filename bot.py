# bot.py

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
    raise RuntimeError("BOT_TOKEN is not set. Please configure it via config.py or environment variable.")

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


# --- ХЕНДЛЕРЫ ДЛЯ ИГРОКОВ ---


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """
    Старт игры / продолжение регистрации / поведение до и после жеребьёвки.
    """
    user = message.from_user
    game_state = db.get_game_state()
    player = db.get_or_create_player(user.id, user.username)

    # --- Регистрация уже ЗАКРЫТА ---
    if not game_state["registration_open"]:
        # Игрок успел зарегистрироваться (есть имя и пожелания)
        if player.get("full_name") and player.get("wish"):
            # После жеребьёвки — можно ещё раз "Узнать"
            await message.answer(
                PLAYER_MESSAGES["already_registered_after_draw"],
                reply_markup=get_know_target_keyboard()
            )
        else:
            # Новый человек после закрытия регистрации
            await message.answer(PLAYER_MESSAGES["start_after_close_new"])
        return

    # --- Регистрация ОТКРЫТА ---
    await state.clear()

    if not player.get("full_name"):
        # Нет имени — начало регистрации
        await message.answer(PLAYER_MESSAGES["start_new"])
        await state.set_state(Registration.waiting_full_name)
    elif not player.get("wish"):
        # Есть имя, но нет пожеланий — продолжаем регистрацию
        await message.answer(PLAYER_MESSAGES["ask_wish"])
        await state.set_state(Registration.waiting_wish)
    else:
        # Уже всё заполнено, жеребьёвка ещё не проводилась — просто ждём
        await message.answer(PLAYER_MESSAGES["already_registered_waiting_draw"])


@router.message(Registration.waiting_full_name)
async def process_full_name(message: Message, state: FSMContext):
    """
    Обработка имени и фамилии.
    """
    full_name = (message.text or "").strip()
    if not full_name:
        await message.answer(PLAYER_MESSAGES["ask_full_name_invalid"])
        return

    db.update_full_name(message.from_user.id, full_name)
    await message.answer(PLAYER_MESSAGES["ask_wish"])
    await state.set_state(Registration.waiting_wish)


@router.message(Registration.waiting_wish)
async def process_wish(message: Message, state: FSMContext):
    """
    Обработка пожеланий.
    """
    wish = (message.text or "").strip()
    if not wish:
        await message.answer(PLAYER_MESSAGES["ask_wish_invalid"])
        return

    db.update_wish(message.from_user.id, wish)
    await state.clear()

    # Только подтверждаем сохранение данных.
    # Сообщение "Пришло время узнать..." придёт уже после жеребьёвки.
    await message.answer(PLAYER_MESSAGES["registration_done_info"])


@router.callback_query(F.data == "know_target")
async def on_know_target(callback: CallbackQuery):
    """
    Кнопка «Узнать» — узнать, кому даришь подарок.
    Поведение зависит от стадии игры и наличия target_id.
    """
    user = callback.from_user
    player = db.get_player_by_tg(user.id)

    if not player or not player.get("full_name") or not player.get("wish"):
        await callback.message.answer(PLAYER_MESSAGES["know_not_finished_registration"])
        await callback.answer()
        return

    game_state = db.get_game_state()

    # Ещё не провели жеребьёвку
    if game_state["registration_open"]:
        await callback.message.answer(PLAYER_MESSAGES["know_before_draw"])
        await callback.answer()
        return

    # Жеребьёвка завершена, ищем target
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


# --- ХЕНДЛЕРЫ ДЛЯ АДМИНА ---


@router.message(Command("players"))
async def cmd_players(message: Message):
    """
    Список всех игроков и их статусов (для админа).
    Без Markdown, чтобы ничего не падало из-за форматирования.
    """
    if not is_admin(message.from_user.id):
        return

    players = db.get_all_players()
    if not players:
        await message.answer("Игроков пока нет.")
        return

    lines = []
    lines.append("Список игроков:\n")

    for p in players:
        statuses = []

        if p.get("full_name"):
            statuses.append("имя ок")
        else:
            statuses.append("нет имени")

        if p.get("wish"):
            statuses.append("пожелания ок")
        else:
            statuses.append("нет пожеланий")

        if p.get("target_id"):
            statuses.append(f"дарит id={p['target_id']}")
        else:
            statuses.append("пара не назначена")

        block = (
            f"id={p['id']} | tg_id={p['tg_id']} | "
            f"@{p['tg_username'] if p.get('tg_username') else '-'}\n"
            f"Имя: {p.get('full_name') or '— не указано'}\n"
            f"Статус: " + " / ".join(statuses) + "\n"
        )
        lines.append(block)

    text = "\n".join(lines)

    # Отправляем БЕЗ parse_mode, чтобы Telegram не пытался парсить Markdown
    await message.answer(text, parse_mode=None)


@router.message(Command("help_admin"))
async def cmd_help_admin(message: Message):
    """
    Показать список всех админских команд.
    """
    if not is_admin(message.from_user.id):
        return

    text = (
        "*Команды администратора:*\n\n"
        "/players — список игроков и их статусы\n"
        "/status — состояние игры\n"
        "/close_reg — провести боевую жеребьёвку (закрыть регистрацию)\n"
        "/test_draw — тестовая жеребьёвка\n"
        "/reset_game — мягкий сброс (очистка пожеланий/имён/пар)\n"
        "/reset_all — полный сброс игры (удаление всех игроков)\n"
        "/help_admin — показать список команд\n"
    )

    await message.answer(text)


@router.message(Command("status"))
async def cmd_status(message: Message):
    """
    Статус игры: регистрация, количество игроков, распределены ли пары.
    """
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
    """
    Основная (боевая) жеребьёвка + закрытие регистрации.
    """
    if not is_admin(message.from_user.id):
        return

    game_state = db.get_game_state()
    # если уже закрыли и пары распределены
    if (not game_state["registration_open"]) and game_state["pairs_assigned"]:
        await message.answer(ADMIN_MESSAGES["close_reg_already_closed"])
        return

    # пытаемся распределить пары
    success, count = db.assign_pairs()
    if not success:
        if count < 2:
            text = ADMIN_MESSAGES["close_reg_not_enough_players"].format(count=count)
            await message.answer(text)
        else:
            await message.answer("Не удалось корректно распределить пары. Попробуй ещё раз.")
        return

    # успех
    await message.answer(
        ADMIN_MESSAGES["close_reg_success"].format(players_count=count)
    )

    # рассылаем уведомление всем участникам с пожеланиями:
    # 1) "жеребьёвка завершена"
    # 2) "Пришло время узнать." + кнопка "Узнать"
    players_ready = db.get_all_players_ready()
    for p in players_ready:
        try:
            await bot.send_message(
                p["tg_id"],
                BROADCAST_MESSAGES["after_draw_notification"]
            )
            await bot.send_message(
                p["tg_id"],
                PLAYER_MESSAGES["registration_done_ask_know"],
                reply_markup=get_know_target_keyboard()
            )
        except Exception as e:
            logging.warning(f"Не удалось отправить сообщение игроку {p['tg_id']}: {e}")


@router.message(Command("test_draw"))
async def cmd_test_draw(message: Message):
    """
    Тестовая жеребьёвка:
    - ведёт себя как настоящая (записывает target_id, закрывает регистрацию),
    - шлёт уведомления игрокам,
    - после теста можно сделать /reset_game или /reset_all.
    """
    if not is_admin(message.from_user.id):
        return

    game_state = db.get_game_state()
    # если уже проводили боевую жеребьёвку
    if (not game_state["registration_open"]) and game_state["pairs_assigned"]:
        await message.answer(
            "Пары уже распределены.\n\n"
            "Чтобы запустить тестовую жеребьёвку ещё раз, сначала сделай /reset_game или /reset_all."
        )
        return

    success, count = db.assign_pairs()
    if not success:
        if count < 2:
            text = ADMIN_MESSAGES["close_reg_not_enough_players"].format(count=count)
            await message.answer("Тестовая жеребьёвка невозможна.\n\n" + text)
        else:
            await message.answer("Не удалось корректно распределить тестовые пары. Попробуй ещё раз.")
        return

    # уведомление админу
    await message.answer(
        "🧪 *Тестовая жеребьёвка завершена!*\n\n"
        f"Игроков в тесте: *{count}*.\n"
        "Пары сохранены в БД, игроки получили уведомления и могут нажимать «Узнать».\n\n"
        "Когда закончишь тест, выполни команду /reset_game или /reset_all, чтобы всё сбросить."
    )

    # шлём игрокам уведомление + кнопку «Узнать» (как в боевой жеребьёвке)
    players_ready = db.get_all_players_ready()
    for p in players_ready:
        try:
            await bot.send_message(
                p["tg_id"],
                BROADCAST_MESSAGES["after_draw_notification"]
            )
            await bot.send_message(
                p["tg_id"],
                PLAYER_MESSAGES["registration_done_ask_know"],
                reply_markup=get_know_target_keyboard()
            )
        except Exception as e:
            logging.warning(
                f"[TEST DRAW] Не удалось отправить сообщение игроку {p['tg_id']}: {e}"
            )


@router.message(Command("reset_game"))
async def cmd_reset_game(message: Message):
    """
    Мягкий сброс игры:
    - очищаем имена, пожелания и пары,
    - но сохраняем самих игроков (tg_id и username),
    - заново открываем регистрацию.
    Требует подтверждения через inline-кнопку.
    """
    if not is_admin(message.from_user.id):
        return

    warning = (
        "⚠ *МЯГКИЙ СБРОС ИГРЫ*\n\n"
        "Будут удалены *имена, пожелания и все пары*, но список игроков сохранится.\n"
        "Игроки смогут зарегистрироваться заново.\n\n"
        "Подтверди действие кнопкой ниже:"
    )

    await message.answer(
        warning,
        reply_markup=get_reset_confirm_keyboard()
    )


@router.callback_query(F.data == "admin_reset_game_confirm")
async def admin_reset_confirm(callback: CallbackQuery):
    """
    Подтверждение мягкого сброса игры.
    """
    if not is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    db.reset_game()

    await callback.message.answer(
        "♻ Мягкий сброс выполнен!\n\n"
        "Имена, пожелания и пары очищены.\n"
        "Регистрация снова открыта. 🎅"
    )
    await callback.answer()


@router.message(Command("reset_all"))
async def cmd_reset_all(message: Message):
    """
    Полный сброс игры:
    - удаляем всех игроков,
    - сбрасываем состояние игры,
    - начинаем абсолютно новую игру.
    Требует подтверждения через отдельную inline-кнопку.
    """
    if not is_admin(message.from_user.id):
        return

    warning = (
        "🗑 *ПОЛНЫЙ СБРОС ИГРЫ*\n\n"
        "Ты собираешься *полностью* удалить всех зарегистрированных игроков "
        "и начать игру с нуля.\n\n"
        "Будут удалены *все игроки, их пожелания и пары*.\n"
        "ЭТО ДЕЙСТВИЕ НЕОБРАТИМО.\n\n"
        "Если ты уверен, нажми кнопку ниже:"
    )

    await message.answer(
        warning,
        reply_markup=get_hard_reset_confirm_keyboard()
    )


@router.callback_query(F.data == "admin_hard_reset_game_confirm")
async def admin_hard_reset_confirm(callback: CallbackQuery):
    """
    Подтверждение полного сброса игры.
    """
    if not is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    db.hard_reset_game()

    await callback.message.answer(
        "🗑 *Полный сброс выполнен!*\n\n"
        "Все игроки удалены, регистрация открыта.\n"
        "Можно начинать абсолютно новую игру 🎅"
    )
    await callback.answer()


# --- MAIN ---


async def main():
    db.init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
