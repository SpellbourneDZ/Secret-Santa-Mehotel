from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from texts import BUTTONS


def get_know_target_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=BUTTONS["know_target"],
                    callback_data="know_target"
                )
            ]
        ]
    )
    return kb


def get_reset_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚠ Подтвердить сброс (мягкий)",
                    callback_data="admin_reset_game_confirm"
                )
            ]
        ]
    )


def get_hard_reset_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 Полный сброс игры",
                    callback_data="admin_hard_reset_game_confirm"
                )
            ]
        ]
    )
