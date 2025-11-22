# db.py

import sqlite3
import random
from datetime import datetime
from typing import List, Dict, Tuple, Optional

from config import DB_PATH


def _dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


def get_conn(dict_rows: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    if dict_rows:
        conn.row_factory = _dict_factory
    return conn


# --- ИНИЦИАЛИЗАЦИЯ БД ---


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER UNIQUE NOT NULL,
            tg_username TEXT,
            full_name TEXT,
            wish TEXT,
            target_id INTEGER,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS game_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            registration_open INTEGER NOT NULL,
            pairs_assigned INTEGER NOT NULL
        )
        """
    )

    # создаём одну строку состояния, если её нет
    c.execute("SELECT COUNT(*) FROM game_state")
    count = c.fetchone()[0]
    if count == 0:
        c.execute(
            "INSERT INTO game_state (id, registration_open, pairs_assigned) VALUES (1, 1, 0)"
        )

    conn.commit()
    conn.close()


# --- ИГРОКИ ---


def get_or_create_player(tg_id: int, tg_username: Optional[str]) -> Dict:
    conn = get_conn(dict_rows=True)
    c = conn.cursor()

    c.execute("SELECT * FROM players WHERE tg_id = ?", (tg_id,))
    row = c.fetchone()

    if row:
        conn.close()
        return row

    now = datetime.utcnow().isoformat()
    c.execute(
        """
        INSERT INTO players (tg_id, tg_username, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        (tg_id, tg_username, now, now),
    )
    conn.commit()

    c.execute("SELECT * FROM players WHERE tg_id = ?", (tg_id,))
    row = c.fetchone()

    conn.close()
    return row


def update_full_name(tg_id: int, full_name: str):
    conn = get_conn()
    c = conn.cursor()

    now = datetime.utcnow().isoformat()
    c.execute(
        """
        UPDATE players
        SET full_name = ?, updated_at = ?
        WHERE tg_id = ?
        """,
        (full_name, now, tg_id),
    )
    conn.commit()
    conn.close()


def update_wish(tg_id: int, wish: str):
    conn = get_conn()
    c = conn.cursor()

    now = datetime.utcnow().isoformat()
    c.execute(
        """
        UPDATE players
        SET wish = ?, updated_at = ?
        WHERE tg_id = ?
        """,
        (wish, now, tg_id),
    )
    conn.commit()
    conn.close()


def get_player_by_tg(tg_id: int) -> Optional[Dict]:
    conn = get_conn(dict_rows=True)
    c = conn.cursor()

    c.execute("SELECT * FROM players WHERE tg_id = ?", (tg_id,))
    row = c.fetchone()
    conn.close()
    return row


def get_player_by_id(player_id: int) -> Optional[Dict]:
    conn = get_conn(dict_rows=True)
    c = conn.cursor()

    c.execute("SELECT * FROM players WHERE id = ?", (player_id,))
    row = c.fetchone()
    conn.close()
    return row


def set_player_target(santa_id: int, receiver_id: int):
    conn = get_conn()
    c = conn.cursor()

    now = datetime.utcnow().isoformat()
    c.execute(
        """
        UPDATE players
        SET target_id = ?, updated_at = ?
        WHERE id = ?
        """,
        (receiver_id, now, santa_id),
    )
    conn.commit()
    conn.close()


def get_all_players() -> List[Dict]:
    conn = get_conn(dict_rows=True)
    c = conn.cursor()

    c.execute("SELECT * FROM players")
    rows = c.fetchall()
    conn.close()
    return rows


def get_all_players_ready() -> List[Dict]:
    """
    Игроки, у которых есть и full_name, и wish.
    """
    conn = get_conn(dict_rows=True)
    c = conn.cursor()

    c.execute(
        """
        SELECT * FROM players
        WHERE full_name IS NOT NULL
          AND wish IS NOT NULL
        """
    )
    rows = c.fetchall()
    conn.close()
    return rows


# --- СОСТОЯНИЕ ИГРЫ ---


def get_game_state() -> Dict:
    conn = get_conn(dict_rows=True)
    c = conn.cursor()

    c.execute("SELECT * FROM game_state WHERE id = 1")
    row = c.fetchone()
    conn.close()
    return row


def set_registration_open(value: bool):
    conn = get_conn()
    c = conn.cursor()

    c.execute(
        "UPDATE game_state SET registration_open = ? WHERE id = 1",
        (1 if value else 0,),
    )
    conn.commit()
    conn.close()


def set_pairs_assigned(value: bool):
    conn = get_conn()
    c = conn.cursor()

    c.execute(
        "UPDATE game_state SET pairs_assigned = ? WHERE id = 1",
        (1 if value else 0,),
    )
    conn.commit()
    conn.close()


# --- ЖЕРЕБЬЁВКА ---


def _create_derangement(ids: List[int]) -> Optional[List[Tuple[int, int]]]:
    """
    Строим перестановку без совпадений:
    для каждого i: ids[i] != shuffled[i]
    Возвращает список пар (santa_id, receiver_id).
    """
    if len(ids) < 2:
        return None

    max_attempts = 100
    for _ in range(max_attempts):
        shuffled = ids[:]
        random.shuffle(shuffled)
        if all(a != b for a, b in zip(ids, shuffled)):
            return list(zip(ids, shuffled))
    return None


def assign_pairs() -> Tuple[bool, int]:
    """
    Распределяет пары между игроками.
    Возвращает (успех, количество игроков).
    """
    players = get_all_players_ready()

    if len(players) < 2:
        return False, len(players)

    ids = [p["id"] for p in players]
    pairs = _create_derangement(ids)

    if not pairs:
        return False, 0

    for santa_id, receiver_id in pairs:
        set_player_target(santa_id, receiver_id)

    # закрываем регистрацию и помечаем, что пары распределены
    set_registration_open(False)
    set_pairs_assigned(True)

    return True, len(players)

def reset_game():
    conn = get_conn()
    c = conn.cursor()

    # удаляем имя, пожелания и target
    c.execute("""
        UPDATE players
        SET full_name = NULL,
            wish = NULL,
            target_id = NULL,
            updated_at = ?
    """, (datetime.utcnow().isoformat(),))

    # сбрасываем состояние игры
    c.execute("""
        UPDATE game_state
        SET registration_open = 1,
            pairs_assigned = 0
        WHERE id = 1
    """)

    conn.commit()
    conn.close()

def build_test_pairs():
    """
    Тестовая жеребьёвка:
    - использует тех же готовых игроков, что и настоящая (get_all_players_ready)
    - строит дерранжмент
    - НЕ сохраняет результат в БД

    Возвращает (успех: bool, количество игроков: int, список пар (santa_player, receiver_player)).
    """
    players = get_all_players_ready()

    if len(players) < 2:
        return False, len(players), []

    ids = [p["id"] for p in players]
    pairs_ids = _create_derangement(ids)

    if not pairs_ids:
        return False, len(players), []

    id_to_player = {p["id"]: p for p in players}
    pairs = [(id_to_player[santa_id], id_to_player[receiver_id]) for santa_id, receiver_id in pairs_ids]

    return True, len(players), pairs

def hard_reset_game():
    """
    Полный сброс игры:
    - удаляем всех игроков
    - открываем регистрацию
    - помечаем, что пары не распределены
    """
    conn = get_conn()
    c = conn.cursor()

    # Удаляем всех игроков
    c.execute("DELETE FROM players")

    # Сбрасываем состояние игры
    c.execute(
        """
        UPDATE game_state
        SET registration_open = 1,
            pairs_assigned = 0
        WHERE id = 1
        """
    )

    conn.commit()
    conn.close()
