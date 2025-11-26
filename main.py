# bot.py
import logging
import sqlite3
import random
from typing import List, Set, Tuple

import asyncio

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.utils.formatting import Text, Bold, Code, Italic

# ---------------------------
# Настройки
# ---------------------------
API_TOKEN = "6302312900:AAH_4TYzdtgMDera9VbYLIxd6h0yGsKtG_k"  # <- вставь сюда токен
DB_PATH = "bot.db"
logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# ---------------------------
# Инициализация SQLite
# ---------------------------
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# Создаём таблицы
cursor.executescript("""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER,
    name TEXT NOT NULL,
    age INTEGER,
    city TEXT,
    gender TEXT,
    about TEXT,
    hobby TEXT
);

CREATE TABLE IF NOT EXISTS interests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS user_interests (
    user_id INTEGER,
    interest_id INTEGER,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(interest_id) REFERENCES interests(id) ON DELETE CASCADE,
    UNIQUE(user_id, interest_id)
);

-- Друзья (двунаправленные записи — для простоты храним пару записей)
CREATE TABLE IF NOT EXISTS friends (
    user_id INTEGER,
    friend_id INTEGER,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(friend_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(user_id, friend_id)
);

-- Избранное
CREATE TABLE IF NOT EXISTS favorites (
    user_id INTEGER,
    fav_user_id INTEGER,
    added_at DATETIME DEFAULT (DATETIME('now')),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(fav_user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(user_id, fav_user_id)
);

-- Группы
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    city TEXT,
    description TEXT,
    private INTEGER,
    code INTEGER
);

CREATE TABLE IF NOT EXISTS group_members (
    group_id INTEGER,
    user_id INTEGER,
    admin INTEGER,
    FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(group_id, user_id, admin)
);

CREATE TABLE IF NOT EXISTS group_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER,
    user_id INTEGER,
    message TEXT,
    FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Мероприятия
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    city TEXT,
    description TEXT,
    datetime TEXT,
    private INTEGER,
    code INTEGER
);

CREATE TABLE IF NOT EXISTS event_members (
    event_id INTEGER,
    user_id INTEGER,
    admin INTEGER,
    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(event_id, user_id, admin)
);
""")
conn.commit()

# ---------------------------
# Утилиты: работа с БД
# ---------------------------

def add_interest(title: str):
    cursor.execute("INSERT OR IGNORE INTO interests (title) VALUES (?)", (title,))
    conn.commit()

def get_interest_id(title: str):
    cursor.execute("SELECT id FROM interests WHERE title = ?", (title,))
    r = cursor.fetchone()
    return r[0] if r else None

def add_user(tg_id, name, age, city, gender, about, hobby):
    cursor.execute("INSERT INTO users (tg_id, name, age, city, gender, about, hobby) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (tg_id, name, age, city, gender, about, hobby))
    conn.commit()
    return cursor.lastrowid

def add_user_interest(user_id, interest_title):
    add_interest(interest_title)
    iid = get_interest_id(interest_title)
    cursor.execute("INSERT OR IGNORE INTO user_interests (user_id, interest_id) VALUES (?, ?)", (user_id, iid))
    conn.commit()

def user_interests(user_id) -> Set[str]:
    cursor.execute("""
    SELECT i.title FROM interests i
    JOIN user_interests ui ON i.id = ui.interest_id
    WHERE ui.user_id = ?
    """, (user_id,))
    return {r[0] for r in cursor.fetchall()}

def user_profile_dict(uid: int) -> dict:
    cursor.execute("SELECT id, name, age, city, gender, about FROM users WHERE id = ?", (uid,))
    r = cursor.fetchone()
    if not r:
        return {}
    interests = sorted(user_interests(r[0]))
    return {
        "id": r[0],
        "name": r[1],
        "age": r[2],
        "city": r[3],
        "gender": r[4],
        "about": r[5] or "",
        "interests": interests
    }

#otpravka soobsheniy
@dp.callback_query(lambda c: c.data.startswith("group_messages"))
async def cb_group_messages(call: types.CallbackQuery, state: FSMContext):
    gid = call.data.strip("group_messages_")
    messages = cursor.execute("SELECT user_id, message FROM group_messages WHERE group_id = ? ORDER BY id DESC LIMIT 10", (gid,)).fetchall()
    end_message = Text()

    for message in messages:
        id, msg = message
        uname = cursor.execute("SELECT name FROM users WHERE id = ?", (id,)).fetchone()[0]
        txt = Text(Bold(uname), ": ", Code(msg), "\n\n")
        end_message = Text(end_message, txt)

    kb = InlineKeyboardBuilder()
    kb.button(text="💬 Написать сообщение", callback_data="send_message_"+str(gid),)

    if len(end_message) == 0: end_message = Text("В этой группе пока нет сообщений, напишите первое!")

    await call.message.edit_text(reply_markup=kb.as_markup(), **end_message.as_kwargs())

class SendMessage(StatesGroup):
    waiting_for_message = State()

@dp.callback_query(lambda c: c.data.startswith("send_message"))
async def cb_send_message(call: types.CallbackQuery, state: FSMContext):
    gid = call.data.strip("send_message_")
    await state.update_data(group_id=gid)
    await call.message.answer("Введите сообщение:")
    await state.set_state(SendMessage.waiting_for_message)

@dp.message(SendMessage.waiting_for_message)
async def send_message(message: types.Message, state: FSMContext):
    data = await state.get_data()
    gid = data["group_id"]
    my_id = get_user_id_by_tg(message.from_user.id)
    cursor.execute("INSERT INTO group_messages (group_id, user_id, message) VALUES (?, ?, ?)", (gid, my_id, message.text))
    all_members = cursor.execute("SELECT user_id FROM group_members WHERE group_id = ?", (gid,)).fetchall()
    username = cursor.execute("SELECT name FROM users WHERE tg_id = ?", (message.from_user.id,)).fetchone()[0]
    group_name = cursor.execute("SELECT title FROM groups WHERE id = ?", (gid,)).fetchone()[0][0]
    msg = Text("Новое сообщение из группы {group_name}!\n\n", Bold(username), ": ", Code(message.text))

    for mem in all_members:
        uid = mem[0]
        
        if uid == my_id: continue

        tg_id = cursor.execute("SELECT tg_id FROM users WHERE id = ?", (uid,)).fetchone()[0][0]
        await bot.send_message(tg_id, **msg.as_kwargs())
    
    await state.clear()


# Состояния для создания группы
class CreateGroup(StatesGroup):
    waiting_for_title = State()
    waiting_for_city = State()
    waiting_for_description = State()
    waiting_for_privacy = State()

@dp.callback_query(lambda c: c.data == "create_group")
async def cb_create_group(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Введите название группы:")
    await state.set_state(CreateGroup.waiting_for_title)

@dp.message(CreateGroup.waiting_for_title)
async def group_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("Введите город группы:")
    await state.set_state(CreateGroup.waiting_for_city)

@dp.message(CreateGroup.waiting_for_city)
async def group_city(message: types.Message, state: FSMContext):
    await state.update_data(city=message.text)
    await message.answer("Будет ли группа приватной? Если да, введите 1, в противном случае 0:")
    await state.set_state(CreateGroup.waiting_for_privacy)

@dp.message(CreateGroup.waiting_for_privacy)
async def group_privacy(message: types.Message, state: FSMContext):
    priv = 1 if message.text == "1" else 0
    await state.update_data(privacy=priv)
    await message.answer("Введите описание группы:")
    await state.set_state(CreateGroup.waiting_for_description)

@dp.message(CreateGroup.waiting_for_description)
async def group_description(message: types.Message, state: FSMContext):
    data = await state.get_data()
    title = data['title']
    city = data['city']
    privacy = data["privacy"]
    description = message.text
    my_id = get_user_id_by_tg(message.from_user.id)

    code = 0 if privacy == 0 else random.randint(1000000, 10000000)

    # Добавляем группу в БД
    cursor.execute("INSERT INTO groups (title, city, description, private, code) VALUES (?, ?, ?, ?, ?)", (title, city, description, privacy, code))
    gid = cursor.lastrowid
    cursor.execute("INSERT INTO group_members (group_id, user_id, admin) VALUES (?, ?, ?)", (gid, my_id, 1))
    conn.commit()

    await message.answer(f"✅ Группа '{title}' успешно создана в городе {city}!")
    await state.clear()

class JoinGroupStates(StatesGroup):
    waiting_for_group_name = State()
    waiting_for_group_code = State()

# Запуск вступления в группу
@dp.callback_query(lambda c: c.data == "join_group")
async def cb_join_group(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Введите название группы, в которую хотите вступить:")
    await state.set_state(JoinGroupStates.waiting_for_group_name)

# Получение названия группы
@dp.message(JoinGroupStates.waiting_for_group_name)
async def process_group_name(message: types.Message, state: FSMContext):
    group_name = message.text.strip()
    cursor.execute("SELECT id, private FROM groups WHERE title = ?", (group_name,))
    r = cursor.fetchone()

    if not r:
        await message.answer("❌ Группа с таким названием не найдена.")
        await state.clear()
        return
    
    gid, is_private = r
    my_id = get_user_id_by_tg(message.from_user.id)

    if is_private == 1:
        # Сохраняем id группы и переходим к запросу кода
        await state.update_data(group_id=gid, user_id=my_id)
        await message.answer("Эта группа приватная. Введите код доступа:")
        await state.set_state(JoinGroupStates.waiting_for_group_code)
    else:
        # Простое вступление

        gids = cursor.execute("SELECT group_id FROM group_members WHERE user_id = ?", (my_id,)).fetchall()
        for i in gids:
            if gid == i[0]:
                await message.answer("Вы уже состоите в этой группе")
                await state.clear()
                return

        cursor.execute("INSERT OR IGNORE INTO group_members (group_id, user_id, admin) VALUES (?, ?, ?)", (gid, my_id, 0))
        conn.commit()
        await message.answer(f"✅ Вы успешно присоединились к группе '{group_name}'!")
        await state.clear()

# Получение кода для приватной группы
@dp.message(JoinGroupStates.waiting_for_group_code)
async def process_group_code(message: types.Message, state: FSMContext):
    data = await state.get_data()
    gid = data['group_id']
    my_id = data['user_id']
    code = message.text.strip()

    cursor.execute("SELECT code, title FROM groups WHERE id = ?", (gid,))
    r = cursor.fetchone()
    if r and r[0] == code:
        cursor.execute("INSERT OR IGNORE INTO group_members (group_id, user_id, admin) VALUES (?, ?, ?)", (gid, my_id, 0))
        conn.commit()
        await message.answer(f"✅ Код верный! Вы присоединились к группе '{r[1]}'.")
    else:
        await message.answer("❌ Неверный код. Попробуйте снова или обратитесь к владельцу группы.")
        return

    await state.clear()

# такой же какеш для мероприятий

class CreateEvent(StatesGroup):
    waiting_for_title = State()
    waiting_for_city = State()
    waiting_for_description = State()
    waiting_for_privacy = State()

@dp.callback_query(lambda c: c.data == "create_group")
async def cb_create_group(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Введите название мероприятия:")
    await state.set_state(CreateGroup.waiting_for_title)

@dp.message(CreateEvent.waiting_for_title)
async def group_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("Введите город мероприятия:")
    await state.set_state(CreateEvent.waiting_for_city)

@dp.message(CreateEvent.waiting_for_city)
async def group_city(message: types.Message, state: FSMContext):
    await state.update_data(city=message.text)
    await message.answer("Будет ли мероприятие приватным? Если да, введите 1, в противном случае 0:")
    await state.set_state(CreateEvent.waiting_for_privacy)

@dp.message(CreateEvent.waiting_for_privacy)
async def group_privacy(message: types.Message, state: FSMContext):
    priv = 1 if message.text == "1" else 0
    await state.update_data(privacy=priv)
    await message.answer("Введите описание мероприятия:")
    await state.set_state(CreateEvent.waiting_for_description)

@dp.message(CreateEvent.waiting_for_description)
async def group_description(message: types.Message, state: FSMContext):
    data = await state.get_data()
    title = data['title']
    city = data['city']
    privacy = data["privacy"]
    description = message.text
    my_id = get_user_id_by_tg(message.from_user.id)

    code = 0 if privacy == 0 else random.randint(1000000, 10000000)

    # Добавляем группу в БД
    cursor.execute("INSERT INTO events (title, city, description, private, code) VALUES (?, ?, ?, ?, ?)", (title, city, description, privacy, code))
    gid = cursor.lastrowid
    cursor.execute("INSERT INTO event_members (event_id, user_id, admin) VALUES (?, ?, ?)", (gid, my_id, 1))
    conn.commit()

    await message.answer(f"✅ Мероприятие '{title}' успешно создано в городе {city}!")
    await state.clear()

class JoinEventStates(StatesGroup):
    waiting_for_group_name = State()
    waiting_for_group_code = State()

# Запуск вступления в группу
@dp.callback_query(lambda c: c.data == "join_group")
async def cb_join_group(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Введите название мероприятия, в котором хотите участвовать:")
    await state.set_state(JoinEventStates.waiting_for_group_name)

# Получение названия группы
@dp.message(JoinEventStates.waiting_for_group_name)
async def process_group_name(message: types.Message, state: FSMContext):
    group_name = message.text.strip()
    cursor.execute("SELECT id, private FROM events WHERE title = ?", (group_name,))
    r = cursor.fetchone()

    if not r:
        await message.answer("❌ Мероприятие с таким названием не найдено.")
        await state.clear()
        return
    
    gid, is_private = r
    my_id = get_user_id_by_tg(message.from_user.id)

    if is_private == 1:
        # Сохраняем id группы и переходим к запросу кода
        await state.update_data(group_id=gid, user_id=my_id)
        await message.answer("Это мероприятие приватное. Введите код доступа:")
        await state.set_state(JoinEventStates.waiting_for_group_code)
    else:
        # Простое вступление

        gids = cursor.execute("SELECT event_id FROM event_members WHERE user_id = ?", (my_id,)).fetchall()
        for i in gids:
            if gid == i[0]:
                await message.answer("Вы уже участвуете в этом мероприятии.")
                await state.clear()
                return

        cursor.execute("INSERT OR IGNORE INTO event_members (event_id, user_id, admin) VALUES (?, ?, ?)", (gid, my_id, 0))
        conn.commit()
        await message.answer(f"✅ Вы успешно присоединились к мероприятию '{group_name}'!")
        await state.clear()

@dp.message(JoinGroupStates.waiting_for_group_code)
async def process_group_code(message: types.Message, state: FSMContext):
    data = await state.get_data()
    gid = data['group_id']
    my_id = data['user_id']
    code = message.text.strip()

    cursor.execute("SELECT code, title FROM groups WHERE id = ?", (gid,))
    r = cursor.fetchone()
    if r and r[0] == code:
        cursor.execute("INSERT OR IGNORE INTO group_members (group_id, user_id, admin) VALUES (?, ?, ?)", (gid, my_id, 0))
        conn.commit()
        await message.answer(f"✅ Код верный! Вы присоединились к группе '{r[1]}'.")
    else:
        await message.answer("❌ Неверный код. Попробуйте снова или обратитесь к владельцу группы.")
        return

    await state.clear()

# ---------------------------
# Логика совпадения (score)
# ---------------------------

def check_matches(h1, h2):
    matches = 0

    higher: list = h1 if len(h1) > len(h2) else h2
    lower: list = h1 if len(h1) < len(h2) else h2

    for i in range(len(lower)):
        lower[i] = str.lower(lower[i])

    for i in higher:
        if lower.count(str.lower(i)) > 0: matches+=1
    
    return matches

def compare(tg_id1, tg_id2):
    hobby_raw1 = cursor.execute("SELECT hobby FROM users WHERE tg_id = ?", (tg_id1,)).fetchone()[0]
    hobby_raw2 = cursor.execute("SELECT hobby FROM users WHERE tg_id = ?", (tg_id2,)).fetchone()[0]

    h1 = hobby_raw1.replace(" ", "").split(",")
    h2 = hobby_raw2.replace(" ", "").split(",")

    all = len(h1) + len(h2)
    matches = check_matches(h1,h2)

    comp = int(matches*100/all)

    return comp

def append_match(matched: list, user: tuple, p: int):
    min = matched[0] if len(matched) > 0 else None

    if not min: return

    for m in matched:
        if m[0] < min[0]: min = m

    if p > m[0]:
        matched.remove(min)
        matched.append({p, user})

def find_matching_users(tg_id, limit=10):
    all_users = cursor.execute("SELECT name, hobby, tg_id FROM users").fetchall()
    matched = []

    for user in all_users:
        p = compare(tg_id, user[2])
        append_match(matched, user, p)

    return matched

# получение айди

def get_user_id_by_tg(tg_id: int) -> int:
    cursor.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
    r = cursor.fetchone()
    if r:
        return r[0]
    add_user(tg_id, "Аноним", 18, "Не указан", "Не указан", "Не указано", "Не указано")
    return cursor.lastrowid

# ---------------------------
# Клавиатуры (inline)
# ---------------------------
def main_menu_kb():
    builder = InlineKeyboardBuilder()

    builder.button(text="💫 Поиск людей", callback_data="search_menu")
    builder.button(text="😀 Мой профиль", callback_data="profile")
    builder.button(text="👥 Группы и события", callback_data="groups_events")
    builder.button(text="⭐ Избранное", callback_data="favorites")

    builder.adjust(2,2,1)

    return builder.as_markup()

def profile_actions_kb(user_id: int, my_id_placeholder=999):
    # my_id_placeholder — id текущего пользователя, тут для примера используется 999
    builder = InlineKeyboardBuilder()

    builder.button(text="💌 Написать", callback_data=f"write_{user_id}")
    builder.button(text="❤️ В избранное", callback_data=f"fav_{user_id}")
    builder.button(text="😐 Пропустить", callback_data=f"skip_{user_id}")

    return builder.as_markup()

def pager_kb(prev_token: str = None, next_token: str = None):
    builder = InlineKeyboardBuilder()

    if prev_token:
        builder.button(text="⬅️ Назад", callback_data=f"page_{prev_token}")
    if next_token:
        builder.button(text="Вперёд ➡️", callback_data=f"page_{next_token}")

    builder.button(text="🔄 Обновить", callback_data="refresh")
    return builder.as_markup()
    
def profile_kb():
    builder = InlineKeyboardBuilder()

    builder.button(text="🟢 Изменить пол", callback_data="change_gender", )
    builder.button(text="🏙️ Изменить город", callback_data="change_city")
    builder.button(text="🗒️ Изменить информацию о себе", callback_data="change_about")
    builder.button(text="📝 Изменить имя", callback_data="change_name")
    builder.button(text="🌻 Изменить возраст",callback_data="change_age")
    builder.button(text="🏓 Изменить хобби", callback_data="change_hobby")
    builder.button(text="⬅️ Назад", callback_data="start")

    builder.adjust(2,2,1)

    return builder.as_markup()

def search_kb():
    builder = InlineKeyboardBuilder()

    builder.button(text="⭐ Начать поиск", callback_data="search")
    builder.button(text="⬅️ Назад", callback_data="start")

    return builder.as_markup()

def match_kb(id):
    builder = InlineKeyboardBuilder()

    builder.button(text="📒 Посмотреть профиль", callback_data=f"check_profile_{id}")
    builder.button(text="⬅️ В меню", callback_data="start")

    return builder.as_markup()

# ---------------------------
# Обработчики команд / callback
# ---------------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Можно связать message.from_user.id -> текущий пользователь; для этого нужен mapping tg_id->user_id
    await message.answer(
        "💫 Добро пожаловать! Выберите раздел:",
        reply_markup=main_menu_kb()
    )

@dp.callback_query(lambda c: c.data == "search_menu")
async def cb_search_menu(call: types.CallbackQuery):
    hobby = cursor.execute("SELECT hobby FROM users WHERE tg_id = ?", (call.from_user.id,)).fetchone()[0]
    msg = Text("💫 ", Bold("Поиск людей"), "\n\n", "Ваши хобби: ", Italic(str(hobby)))

    await call.message.edit_text(reply_markup=search_kb(), **msg.as_kwargs())

@dp.callback_query(lambda c: c.data == "search")
async def cb_search(call: types.CallbackQuery):
    await call.message.edit_text(text="Ищем...")
    matches = find_matching_users(call.from_user.id)

    if len(matches) == 0:
        await call.message.edit_text(text="Люди не были найдены :(", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="start").as_markup())
        return
    
    choice = random.choice(matches)[1]
    id = choice[2]

    msg = Text(Bold("✅ Поиск завершился успешно!\n\n"), "◦ Имя: ", Italic(choice[0]), "\n◦ Хобби: ", Italic(choice[1]))

    await call.message.edit_text(reply_markup=match_kb(id), **msg.as_kwargs())

@dp.callback_query(lambda c: c.data.startswith("check_profile"))
async def cb_check_profile(call: types.CallbackQuery):
    tg_id = call.data.strip("check_profile_")
    data = cursor.execute("SELECT name, age, city, gender, about, hobby FROM users WHERE id = ?", (tg_id,)).fetchone()

    name = data[0]
    age = data[1]
    city = data[2]
    gender = data[3]
    about = data[4]
    hobby = data[5]

    msg = Text(Bold(f"Профиль \"{name}\":\n\n"), "◦ Имя: ", Italic(name), "\n◦ Возраст: ", Italic(str(age)), "\n◦ Город: ", Italic(city), "\n◦ Пол: ", Italic(gender), "\n◦ Обо мне: ", Italic(about), "\n◦ Хобби: ", Italic(hobby))

    await call.message.edit_text(**msg.as_kwargs())

@dp.callback_query(lambda c: c.data == "start")
async def cb_start(call: types.CallbackQuery):
    await call.message.edit_text(text=
        "💫 Добро пожаловать! Выберите раздел:",
        reply_markup=main_menu_kb()
    )

@dp.callback_query(lambda c: c.data == "group_info")
async def cb_group_info(call: types.CallbackQuery, state: FSMContext):
    my_id = get_user_id_by_tg(call.from_user.id)

class ChangeState(StatesGroup):
    wait_for_message = State()

@dp.message(ChangeState.wait_for_message)
async def change_msg(message: types.Message, state: FSMContext):
    data = await state.get_data()
    query = data["query"]
    msg = data["msg"]
    id = get_user_id_by_tg(message.from_user.id)
    edit = message.text

    cursor.execute(f"UPDATE users SET {query} = ? WHERE id = ?", (edit, id,))
    conn.commit()

    await message.answer(msg)

@dp.callback_query(lambda c: c.data == "profile")
async def cb_profile(call: types.CallbackQuery):
    id = get_user_id_by_tg(call.from_user.id)
    data = cursor.execute("SELECT name, age, city, gender, about, hobby FROM users WHERE id = ?", (id,)).fetchone()

    name = data[0]
    age = data[1]
    city = data[2]
    gender = data[3]
    about = data[4]
    hobby = data[5]

    msg = Text(Bold("Ваш профиль:\n\n"), "◦ Имя: ", Italic(name), "\n◦ Возраст: ", Italic(str(age)), "\n◦ Город: ", Italic(city), "\n◦ Пол: ", Italic(gender), "\n◦ Обо мне: ", Italic(about), "\n◦ Хобби: ", Italic(hobby))

    await call.message.edit_text(reply_markup=profile_kb(), **msg.as_kwargs())

@dp.callback_query(lambda c: c.data == "change_gender")
async def cb_change_gender(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Введите ваш пол")
    await state.update_data(query="gender")
    await state.update_data(msg="Ваш пол был успешно изменен!")
    await state.set_state(ChangeState.wait_for_message)

@dp.callback_query(lambda c: c.data == "change_city")
async def cb_change_city(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Введите ваш город")
    await state.update_data(query="city")
    await state.update_data(msg="Ваш город был успешно изменен!")
    await state.set_state(ChangeState.wait_for_message)

@dp.callback_query(lambda c: c.data == "change_name")
async def cb_change_name(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Введите ваше имя")
    await state.update_data(query="name")
    await state.update_data(msg="Ваше имя было успешно изменено!")
    await state.set_state(ChangeState.wait_for_message)

@dp.callback_query(lambda c: c.data == "change_age")
async def cb_change_age(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Введите ваш возраст")
    await state.update_data(query="age")
    await state.update_data(msg="Ваш возраст был успешно изменен!")
    await state.set_state(ChangeState.wait_for_message)

@dp.callback_query(lambda c: c.data == "change_about")
async def cb_change_about(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Введите информацию о себе")
    await state.update_data(query="about")
    await state.update_data(msg="Информация о вас была успешно изменена!")
    await state.set_state(ChangeState.wait_for_message)

@dp.callback_query(lambda c: c.data == "change_hobby")
async def cb_change_about(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Введите хобби через запятую: ")
    await state.update_data(query="hobby")
    await state.update_data(msg="Ваше хобби было успешно изменено!")
    await state.set_state(ChangeState.wait_for_message)

@dp.callback_query(lambda c: c.data == "modes_menu")
async def cb_modes_menu(call: types.CallbackQuery):
    txt = "💫 РЕЖИМЫ ПОИСКА\n──────────────\n\n"
    txt += "🎯 Быстрый поиск — случайные люди по 1-2 интересам\n[🔀 Начать просмотр]\n\n"
    txt += "🎯 Точный поиск — подбор по фильтрам и интересам\n[🔍 Настроить фильтры]\n\n"
    txt += "🎯 Совпадение дня — 1 лучший матч специально для вас\n[💖 Посмотреть]\n\n"
    txt += "📍 Люди рядом — карта/список\n[🗺 На карте] [👥 Списком]\n"
    await call.message.edit_text(txt)

@dp.callback_query(lambda c: c.data == "groups_events")
async def cb_groups_events(call: types.CallbackQuery):
    """# Выводим группы и ближайшие мероприятия
    cursor.execute("SELECT id, title, city, description FROM groups WHERE city = ?", ("Москва",))
    groups = cursor.fetchall()
    cursor.execute("SELECT id, title, city, description, datetime FROM events WHERE city = ? ORDER BY datetime LIMIT 10", ("Москва",))
    events = cursor.fetchall()
    txt = "👥 ГРУППЫ\n──────────────\n"
    for g in groups:
        gid, title, city, desc = g
        # count members
        cursor.execute("SELECT COUNT(*) FROM group_members WHERE group_id = ?", (gid,))
        count = cursor.fetchone()[0]
        txt += f"• {title} · {count} участников\n  {desc}\n"
        txt += f"  [Присоединиться] (cb: group_join_{gid})\n\n"
    txt += "📅 МЕРОПРИЯТИЯ\n──────────────\n"
    for e in events:
        eid, title, city, desc, dt = e
        cursor.execute("SELECT COUNT(*) FROM event_members WHERE event_id = ?", (eid,))
        count = cursor.fetchone()[0]
        txt += f"• {title} — {dt} · {count} участников\n  {desc}\n"
        txt += f"  [Участвовать] (cb: event_join_{eid})\n\n"
    await call.message.edit_text(txt)"""
    cursor.execute("SELECT id, title, city, description FROM groups")
    groups = cursor.fetchall()
    cursor.execute("SELECT id, title, city, description, datetime FROM events ORDER BY datetime LIMIT 10")
    events = cursor.fetchall()

    # Текст
    txt = "👥 ГРУППЫ\n──────────────\n"
    for g in groups:
        gid, title, city, desc = g
        cursor.execute("SELECT COUNT(*) FROM group_members WHERE group_id = ?", (gid,))
        count = cursor.fetchone()[0]
        txt += f"• {title} · {count} участников\n  {desc}\n"
        #txt += f"  [Присоединиться] (cb: group_join_{gid})\n\n"

    txt += "📅 МЕРОПРИЯТИЯ\n──────────────\n"
    for e in events:
        eid, title, city, desc, dt = e
        cursor.execute("SELECT COUNT(*) FROM event_members WHERE event_id = ?", (eid,))
        count = cursor.fetchone()[0]
        txt += f"• {title} — {dt} · {count} участников\n  {desc}\n"
        #txt += f"  [Участвовать] (cb: event_join_{eid})\n\n"

    # Кнопки
    kb = InlineKeyboardBuilder()
    kb.button(text="🌻 Мои группы", callback_data="my_groups")
    kb.button(text="➕ Создать группу", callback_data="create_group")
    kb.button(text="➕ Создать мероприятие", callback_data="create_event")
    kb.button(text="🤖 Присоединиться к группе", callback_data="join_group")
    kb.button(text="🤖 Присоединиться к мероприятию", callback_data="join_event")
    kb.button(text="⬅️ Назад", callback_data="start")
    kb.adjust(1)

    await call.message.edit_text(txt, reply_markup=kb.as_markup())

@dp.callback_query(lambda c: c.data == "my_groups")
async def cb_my_groups(call: types.CallbackQuery):
    my_id = get_user_id_by_tg(call.from_user.id)
    data = cursor.execute("SELECT group_id FROM group_members WHERE user_id = ?", (my_id,)).fetchall()
    msg = ""
    kb = InlineKeyboardBuilder()

    for i in data:
        gid = i[0]
        data2 = cursor.execute("SELECT title, city, description, private FROM groups WHERE id = ?", (gid,)).fetchone()
        title = data2[0]
        city = data2[1]
        desc = data2[2]
        private = data2[3]
        txt = title + " | " + city + " | " + ("🔒" if private else "🔓") + "\n" + desc
        msg += txt + "\n\n"

        kb.button(text="💬 " + title, callback_data="group_messages_"+str(gid),)
    
    kb.button(text="⬅️ Menu", callback_data="start")

    await call.message.edit_text(txt, reply_markup=kb.as_markup())

@dp.callback_query(lambda c: c.data.startswith("group_join_"))
async def cb_group_join(call: types.CallbackQuery):
    gid = int(call.data.split("_")[-1])
    my_id = get_user_id_by_tg(call.from_user.id)
    gdata = cursor.execute("SELECT title FROM groups WHERE id = ?", (gid)).fetchone()[0]

    cursor.execute("INSERT OR IGNORE INTO group_members (group_id, user_id) VALUES (?, ?)", (gid, my_id))
    conn.commit()
    await call.answer(f"Вы присоединились к группе {gdata[0]}.", show_alert=True)

@dp.callback_query(lambda c: c.data.startswith("event_join_"))
async def cb_event_join(call: types.CallbackQuery):
    eid = int(call.data.split("_")[-1])
    my_id = get_user_id_by_tg(call.from_user.id)
    edata = cursor.execute("SELECT title FROM events WHERE id = ?", (eid)).fetchone()[0]

    cursor.execute("INSERT OR IGNORE INTO event_members (event_id, user_id) VALUES (?, ?)", (eid, my_id))
    conn.commit()
    await call.answer(f"Вы зарегистрированы на событие {edata[0]}.", show_alert=True)

@dp.callback_query(lambda c: c.data == "favorites")
async def cb_favorites(call: types.CallbackQuery):
    my_id = get_user_id_by_tg(call.from_user.id)
    cursor.execute("""
    SELECT u.id, u.name, u.age, u.city
    FROM users u JOIN favorites f ON u.id = f.fav_user_id
    WHERE f.user_id = ?
    ORDER BY f.added_at DESC
    """, (my_id,))
    rows = cursor.fetchall()
    if not rows:
        await call.message.edit_text("⭐ ИЗБРАННОЕ\n──────────────\nСписок пуст.")
        return
    txt = "⭐ ИЗБРАННОЕ\n──────────────\n"
    for r in rows:
        uid, name, age, city, dist, online = r
        ints = user_interests(uid)
        txt += f"👤 {name}, {age} лет\n"
        txt += f"✅ {', '.join(sorted(ints)) if ints else '—'}\n"
        txt += f"📍 {dist} км · {'Онлайн' if online else 'Не в сети'}\n\n"
    txt += "[✏️ Редактировать] [❌ Очистить]"
    await call.message.edit_text(txt)

async def main():
    await dp.start_polling(bot)

# ---------------------------
# Завершающие замечания
# ---------------------------
if __name__ == "__main__":
    print("Bot starting...")
    asyncio.run(main())