#!/usr/bin/env python3
"""Final clean single-file bot for the project (bot_end.py)

Features:
- RU-only onboarding with exact consent text: "Продолжить✅"
- Onboarding order: CONSENT -> NAME -> AGE -> GENDER -> LOOKING -> CITY -> BIO (optional) -> PHOTO
- Institutes replaced by the exact buttons list requested
- All SQL strings keep %s placeholders (db.py will translate them to SQLite '?')
- No premium/limits logic

This file is intended to be a clean replacement; it does NOT contain a bot
token. To run locally set the TOKEN or TG_BOT_TOKEN environment variable.
"""

import os
import re
import json
import logging
from typing import Optional, List
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update, InputMediaPhoto
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    PicklePersistence,
    filters,
)
import db

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize DB
db.init_db()
connection_pool = db.connection_pool

# Conversation states
CONSENT, NAME, AGE, GENDER, LOOKING, CITY, BIO, PHOTO, MATCHING, RESPOND, EDIT_BIO_STATE, EDIT_PHOTO_STATE, MESSAGE_PROFILE_STATE, VIEW_LIKERS = range(14)
AUTO_START_FLAG = 'profile_started'
LAUNCH_NOTICE_FLAG = 'launch_notice_sent'
MAX_PROFILE_PHOTOS = 5
ADMIN_IDS = {1237228404, 1589495697}
BAN_VIDEO_PATH = os.environ.get('BAN_VIDEO_PATH', 'ban_message.mp4')
BAN_TEXT = 'Ты еблан. Ты забанен блять! Я не буду тебя разбанивать, потому что ты тупой сука! (Не ну ес чё пиши в саппортm, если бан ошибочный @lovelyks_mirea_support_bot)'
KEYBOARD_STUB_TEXT = 'Нажми Погнали🚀 чтобы начать смотреть анкеты'  # Zero-width char so Telegram accepts keyboard-only replies

# UI constants (verbatim)
CONSENT_BUTTON = "Продолжить✅"
CONSENT_KB = ReplyKeyboardMarkup([[CONSENT_BUTTON]], resize_keyboard=True, one_time_keyboard=True)
GENDER_KB = ReplyKeyboardMarkup([["Я парень", "Я девушка"]], resize_keyboard=True, one_time_keyboard=True)
LOOKING_KB = ReplyKeyboardMarkup([["Парни", "Девушки", "Всех"]], resize_keyboard=True, one_time_keyboard=True)
INSTITUTES = ["ИТУ❤️","ИПТИП💛","ИИИ💚","ИКБ💙","ИРИ💜","ИТХТ🩷","ИИТ🩶"]
INSTITUTES_KB = ReplyKeyboardMarkup([
    ["ИТУ❤️", "ИПТИП💛", "ИИИ💚"],
    ["ИКБ💙", "ИРИ💜", "ИТХТ🩷"],
    ["ИИТ🩶"]
], resize_keyboard=True, one_time_keyboard=True)
SKIP_BIO_KB = ReplyKeyboardMarkup([["Пропустить"]], resize_keyboard=True, one_time_keyboard=True)
LIKE_KB = ReplyKeyboardMarkup([["❤️","💌","❌","🏡"]], resize_keyboard=True, one_time_keyboard=True)
LIKERS_KB = ReplyKeyboardMarkup([["❤️","❌","🏡"]], resize_keyboard=True, one_time_keyboard=True)
MESSAGE_REPLY_KB = ReplyKeyboardMarkup([["❤️","❌"]], resize_keyboard=True, one_time_keyboard=True)
VIEW_MUTUAL_BUTTON = "👀"
SKIP_MUTUAL_BUTTON = "🪫"
MUTUAL_PROMPT_TEXT = "У вас с кем-то взаимная симатия! Посмотрим?)"
MUTUAL_PROMPT_KB = ReplyKeyboardMarkup([[VIEW_MUTUAL_BUTTON, SKIP_MUTUAL_BUTTON]], resize_keyboard=True, one_time_keyboard=True)

# Additional start browsing button/keyboard
START_BROWSING = "Погнали🚀"
START_OVER = "Погнали🚀"
BACK_TO_PROFILE = "Вернуться к профилю"
BROWSE_KB = ReplyKeyboardMarkup([[START_BROWSING]], resize_keyboard=True, one_time_keyboard=True)
START_OVER_KB = ReplyKeyboardMarkup([[START_OVER], [BACK_TO_PROFILE]], resize_keyboard=True, one_time_keyboard=True)

# Like notification buttons

# Profile management buttons
EDIT_BIO = "Изменить описание"
EDIT_PHOTO = "Изменить фото"
REMAKE_PROFILE = "Переделать анкету"
PROFILE_KB = ReplyKeyboardMarkup([
    [START_BROWSING],
    [EDIT_BIO, EDIT_PHOTO],
    [REMAKE_PROFILE]
], resize_keyboard=True, one_time_keyboard=True)

RESPOND_LIKE = "Ответить на анкету"
RESPOND_KB = ReplyKeyboardMarkup([[RESPOND_LIKE]], resize_keyboard=True, one_time_keyboard=True)

RESPOND_MESSAGE = "Ответить на сообщение"
RESPOND_MESSAGE_KB = ReplyKeyboardMarkup([[RESPOND_MESSAGE]], resize_keyboard=True, one_time_keyboard=True)

# Message notification buttons
VIEW_MESSAGE_PROFILE = "👀"
SKIP_MESSAGE = "🪫"
MESSAGE_PROFILE_KB = ReplyKeyboardMarkup([[VIEW_MESSAGE_PROFILE, SKIP_MESSAGE]], resize_keyboard=True, one_time_keyboard=True)


def get_conn():
    return connection_pool.get_connection()


def safe_open_photo(photo_path: str):
    """Safely open photo file with proper error handling"""
    try:
        if photo_path and os.path.exists(photo_path):
            return open(photo_path, 'rb')
        return None
    except Exception as e:
        logger.error(f"Error opening photo {photo_path}: {e}")
        return None


def create_profile_caption(name, age, city, bio):
    """Create standardized profile caption"""
    caption_parts = []
    if name:
        caption_parts.append(str(name))
    if age:
        caption_parts.append(str(age))
    if city:
        caption_parts.append(str(city))
    caption = ', '.join(caption_parts)
    if bio:
        caption = f"{caption}\n{bio}" if caption else bio
    return caption


def _load_photo_paths(photo_value: Optional[str]) -> List[str]:
    if not photo_value:
        return []
    try:
        data = json.loads(photo_value)
        if isinstance(data, list):
            return [str(p) for p in data if isinstance(p, str)]
    except Exception:
        pass
    return [photo_value]


def _dump_photo_paths(paths: List[str]) -> Optional[str]:
    cleaned = [p for p in paths if p]
    if not cleaned:
        return None
    return json.dumps(cleaned[-MAX_PROFILE_PHOTOS:], ensure_ascii=False)


def _clear_user_photos(uid: int):
    folder = os.path.join('user_photos', str(uid))
    if os.path.isdir(folder):
        for entry in os.listdir(folder):
            path = os.path.join(folder, entry)
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except Exception:
                pass
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE Users SET Photo = NULL WHERE PersonID = %s", (uid,))
    conn.commit()
    cur.close(); conn.close()


async def _get_tg_username(bot, uid: int) -> Optional[str]:
    try:
        chat = await bot.get_chat(uid)
        uname = getattr(chat, 'username', None)
        if uname:
            return f'@{uname}'
    except Exception:
        pass
    return None


async def _send_ban_message(message):
    if BAN_VIDEO_PATH and os.path.exists(BAN_VIDEO_PATH):
        try:
            with open(BAN_VIDEO_PATH, 'rb') as video:
                await message.reply_video(video=video, caption=BAN_TEXT)
            return
        except Exception as exc:
            logger.warning(f"Failed to send ban video: {exc}")
    await message.reply_text(BAN_TEXT)


async def _send_ban_message_to_user(bot, user_id: int) -> None:
    """Send ban notice (video+caption if available, otherwise text) directly to user."""
    if BAN_VIDEO_PATH and os.path.exists(BAN_VIDEO_PATH):
        try:
            with open(BAN_VIDEO_PATH, 'rb') as video:
                await bot.send_video(chat_id=user_id, video=video, caption=BAN_TEXT)
            return
        except Exception as exc:
            logger.warning(f"Failed to send ban video to {user_id}: {exc}")
    try:
        await bot.send_message(chat_id=user_id, text=BAN_TEXT)
    except Exception as exc:
        logger.warning(f"Failed to send ban text to {user_id}: {exc}")


def _mark_candidate_seen(cur, viewer_id: int, candidate_id: int):
    """Remember that viewer has seen candidate to avoid repeats."""
    cur.execute(
        "INSERT OR IGNORE INTO Likes (LikeUserID, LikedUserID, MesToPerson) VALUES (%s, %s, %s)",
        (viewer_id, candidate_id, '__SHOWN__')
    )


def _existing_photo_paths(photo_value: Optional[str]) -> List[str]:
    paths = []
    for path in _load_photo_paths(photo_value):
        if path and os.path.exists(path):
            paths.append(path)
    return paths


async def _reply_with_photos(message, photo_field: Optional[str], caption: Optional[str], reply_markup=None, fallback: str = ''):
    paths = _existing_photo_paths(photo_field)
    if not paths:
        text_value = caption or fallback or (KEYBOARD_STUB_TEXT if reply_markup else None)
        if text_value is not None:
            await message.reply_text(text_value, reply_markup=reply_markup)
        return

    # If only one photo, keep single-message flow (caption + keyboard)
    if len(paths) == 1:
        photo_file = safe_open_photo(paths[0])
        if photo_file:
            try:
                await message.reply_photo(photo_file, caption=caption or fallback, reply_markup=reply_markup)
            finally:
                photo_file.close()
        else:
            text_value = caption or fallback or (KEYBOARD_STUB_TEXT if reply_markup else None)
            if text_value is not None:
                await message.reply_text(text_value, reply_markup=reply_markup)
        return

    # Multiple photos: send as a single media group (album)
    media = []
    open_files = []
    try:
        for idx, p in enumerate(paths):
            f = safe_open_photo(p)
            if not f:
                continue
            open_files.append(f)
            if idx == 0:
                media.append(InputMediaPhoto(media=f, caption=(caption or fallback) or None))
            else:
                media.append(InputMediaPhoto(media=f))

        if not media:
            # Fallback if all files failed to open
            text_value = caption or fallback or (KEYBOARD_STUB_TEXT if reply_markup else None)
            if text_value is not None:
                await message.reply_text(text_value, reply_markup=reply_markup)
            return

        await message.reply_media_group(media=media)

        # Reply keyboards cannot be attached to sendMediaGroup; send a stub to carry it
        if reply_markup is not None:
            await message.reply_text(KEYBOARD_STUB_TEXT, reply_markup=reply_markup)
    finally:
        for f in open_files:
            try:
                f.close()
            except Exception:
                pass


async def _send_photos_to_chat(bot, chat_id: int, photo_field: Optional[str], caption: Optional[str], reply_markup=None):
    paths = _existing_photo_paths(photo_field)
    if not paths:
        text_value = caption or ''
        if text_value:
            if reply_markup:
                await bot.send_message(chat_id=chat_id, text=text_value, reply_markup=reply_markup)
            else:
                await bot.send_message(chat_id=chat_id, text=text_value)
        return

    if len(paths) == 1:
        photo_file = safe_open_photo(paths[0])
        if photo_file:
            try:
                await bot.send_photo(chat_id=chat_id, photo=photo_file, caption=caption or '', reply_markup=reply_markup)
            finally:
                photo_file.close()
        else:
            text_value = caption or ''
            if text_value:
                if reply_markup:
                    await bot.send_message(chat_id=chat_id, text=text_value, reply_markup=reply_markup)
                else:
                    await bot.send_message(chat_id=chat_id, text=text_value)
        return

    media = []
    open_files = []
    try:
        for idx, p in enumerate(paths):
            f = safe_open_photo(p)
            if not f:
                continue
            open_files.append(f)
            if idx == 0:
                media.append(InputMediaPhoto(media=f, caption=(caption or '') or None))
            else:
                media.append(InputMediaPhoto(media=f))

        if not media:
            text_value = caption or ''
            if text_value:
                if reply_markup:
                    await bot.send_message(chat_id=chat_id, text=text_value, reply_markup=reply_markup)
                else:
                    await bot.send_message(chat_id=chat_id, text=text_value)
            return

        await bot.send_media_group(chat_id=chat_id, media=media)

        if reply_markup is not None:
            await bot.send_message(chat_id=chat_id, text=KEYBOARD_STUB_TEXT, reply_markup=reply_markup)
    finally:
        for f in open_files:
            try:
                f.close()
            except Exception:
                pass


def _user_is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def _is_banned(cur, uid: int) -> bool:
    cur.execute("SELECT 1 FROM banned WHERE PersonID = %s", (uid,))
    return cur.fetchone() is not None


async def _get_tg_username(bot, uid: int) -> Optional[str]:
    try:
        chat = await bot.get_chat(uid)
        uname = getattr(chat, 'username', None)
        if uname:
            return f'@{uname}'
    except Exception:
        pass
    return None


async def _ensure_admin(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    if uid is None or not _user_is_admin(uid):
        await update.message.reply_text('Нет доступа.')
        return False
    return True


def _extract_target_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    if context.args:
        try:
            return int(context.args[0])
        except ValueError:
            return None
    if update.message and update.message.reply_to_message:
        return update.message.reply_to_message.from_user.id
    return None


async def ensure_started(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Automatically trigger onboarding when bot restarts."""
    if context.chat_data.get(AUTO_START_FLAG):
        return
    context.chat_data[AUTO_START_FLAG] = True
    await start(update, context)
    raise ApplicationHandlerStop


async def start_browsing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start browsing candidates immediately"""
        # ⏳ Таймер до старта
    from datetime import datetime
    import pytz

    moscow = pytz.timezone("Europe/Moscow")
    target_time = moscow.localize(datetime(2025, 11, 13, 23, 0, 9))
    now = datetime.now(moscow)

    if now < target_time:
        remaining = target_time - now
        days = remaining.days
        hours, remainder = divmod(remaining.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)


        if os.path.exists(banner_path):
            with open(banner_path, "rb") as photo:
                await update.message.reply_photo(photo=photo, caption=text)
        else:
            await update.message.reply_text(text)

        return ConversationHandler.END
    else:
        if not context.chat_data.get(LAUNCH_NOTICE_FLAG):
            context.chat_data[LAUNCH_NOTICE_FLAG] = True
            await update.message.reply_text('Время пришло✨')

    uid = update.effective_user.id
    context.user_data['user_id'] = uid
    
    # No automatic reset - let user decide when to start over
    
    # Load first candidate
    conn = get_conn(); cur = conn.cursor()
    if _is_banned(cur, uid):
        cur.close(); conn.close()
        await _send_ban_message(update.message)
        return ConversationHandler.END
    if not _profile_is_complete(cur, uid):
        cur.close(); conn.close()
        await update.message.reply_text('Пожалуйста, заполните профиль сначала (/start).')
        return NAME

    row = _get_my_profile(cur, uid)
    if not row:
        cur.close(); conn.close()
        await update.message.reply_text('Пожалуйста, заполните профиль (/start).')
        return NAME
    gender, looking, my_age = row
    
    # First check if there are users who liked this user
    cur.execute("""
        SELECT u.PersonID, u.UserName, u.Age, u.City, u.Bio, u.Photo 
        FROM Users u 
        INNER JOIN Likes l ON u.PersonID = l.LikeUserID 
        WHERE l.LikedUserID = %s AND l.MesToPerson = '__LIKE__' AND (l.MessageText IS NULL OR l.MessageText = '')
        ORDER BY l.id DESC
    """, (uid,))
    
    likers = cur.fetchall()
    
    if likers:
        # Show likers first
        context.user_data['likers_list'] = likers
        context.user_data['likers_index'] = 0
        context.user_data.pop('allow_reset', None)
        await show_next_liker(update, context)
        cur.close(); conn.close()
        return VIEW_LIKERS
    
    # Handle "ALL" option - search for all regardless of gender
    if looking == 'ALL':
        match_gender = None  # No gender filtering
    else:
        match_gender = 'М' if looking == 'М' else 'Ж'

    # Find first candidate
    print(f"DEBUG start_browsing: Looking for candidates for user {uid}, gender={gender}, looking={looking}, age={my_age}")
    candidate = _find_candidate(cur, uid, match_gender, gender, my_age - 5, my_age + 5)
    print(f"DEBUG start_browsing: Found candidate: {candidate}")
    if not candidate:
        # No more candidates now — let user decide to start over explicitly
        # Debug: check database stats
        cur.execute("SELECT COUNT(*) FROM Users WHERE IsActive = 1 AND Photo IS NOT NULL")
        total_active = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM Users WHERE Gender = %s AND IsActive = 1 AND Photo IS NOT NULL", (match_gender,))
        gender_active = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM Likes WHERE LikeUserID = %s", (uid,))
        user_likes = cur.fetchone()[0]
        
        cur.close(); conn.close()
        print(f"DEBUG start_browsing: No candidates for user {uid}, offering START_OVER_KB")
        #debug_msg = f'Все анкеты просмотрены!✨\n\nОтладка:\n- Всего активных с фото: {total_active}\n- Подходящего пола ({match_gender}): {gender_active}\n- Ваших лайков: {user_likes}\n\nНажмите "Погнали🚀" чтобы просмотреть анкеты снова.'
        debug_msg = f'Все анкеты просмотрены!✨\n\nНажмите "Погнали🚀" чтобы просмотреть анкеты снова.'
        context.user_data['allow_reset'] = True
        await update.message.reply_text(debug_msg, reply_markup=START_OVER_KB)
        return MATCHING

    candidate_id, candidate_name, candidate_age, candidate_city, candidate_bio, candidate_photo = candidate
    context.user_data['liked_user_id'] = candidate_id
    context.user_data.pop('allow_reset', None)
    _mark_candidate_seen(cur, uid, candidate_id)
    cur.close(); conn.close()

    caption = f"{candidate_name}, {candidate_age}"
    if candidate_city:
        caption += f", {candidate_city}"
    caption += f"\n{candidate_bio or ''}"
    await _reply_with_photos(update.message, candidate_photo, caption, LIKE_KB, caption)
    return MATCHING


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    context.chat_data[AUTO_START_FLAG] = True
    # If user already consented, skip consent prompt
    conn = get_conn(); cur = conn.cursor()
    if _is_banned(cur, uid):
        cur.close(); conn.close()
        await _send_ban_message(update.message)
        return ConversationHandler.END
    cur.execute("SELECT Consent, IsActive, Photo, UserName, Age, City, Bio FROM Users WHERE PersonID = %s", (uid,))
    row = cur.fetchone()
    if row and row[0]:
        # user already consented
        is_active = row[1]
        photo = row[2]
        name = row[3] or ''
        age = row[4] or ''
        city = row[5] or ''
        bio = row[6] or ''
        caption_parts = []
        if name:
            caption_parts.append(str(name))
        if age:
            caption_parts.append(str(age))
        if city:
            caption_parts.append(str(city))
        caption = ', '.join(caption_parts)
        if bio:
            caption = f"{caption}\n{bio}" if caption else bio
        if is_active and photo:
            await _reply_with_photos(update.message, photo, caption or 'Ваш профиль сохранён.', PROFILE_KB, 'Ваш профиль сохранён.')
            cur.close(); conn.close()
            # Start browsing immediately
            return await start_browsing(update, context)
        elif is_active:
            await update.message.reply_text(caption or 'Ваш профиль сохранён.', reply_markup=PROFILE_KB)
            cur.close(); conn.close()
            # Start browsing immediately
            return await start_browsing(update, context)
        else:
            # Ask name to continue onboarding
            cur.close(); conn.close()
            await update.message.reply_text('Кто ты воин??(имя)', reply_markup=ReplyKeyboardRemove())
            return NAME
    cur.close(); conn.close()
    await update.message.reply_text('Нажимая кнопку "Продолжить✅" вы подтверждаете согласие с нашей политикой конфинденциальности (https://telegra.ph/Politika-konfidencialnosti-i-Polzovatelskoe-soglashenie-11-09-2) и пользовательским соглашением, а также, что ознакомились с нашими правилами пользования.', reply_markup=CONSENT_KB)
    return CONSENT


async def consent_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if (update.message.text or '').strip() != CONSENT_BUTTON:
        await update.message.reply_text('Пожалуйста, нажмите кнопку Продолжить✅ чтобы начать.', reply_markup=CONSENT_KB)
        return CONSENT
    uid = update.effective_user.id
    conn = get_conn(); cur = conn.cursor()
    # ensure user row exists and persist consent
    cur.execute("INSERT OR IGNORE INTO Users (PersonID) VALUES (%s)", (uid,))
    cur.execute("UPDATE Users SET Consent = %s WHERE PersonID = %s", (1, uid))
    # Now check if profile is complete and active
    cur.execute("SELECT UserName, Age, City, Bio, Photo, IsActive FROM Users WHERE PersonID = %s", (uid,))
    row = cur.fetchone()
    if row and row[5]:
        name = row[0] or ''
        age = row[1] or ''
        city = row[2] or ''
        bio = row[3] or ''
        photo = row[4]
        caption_parts = []
        if name:
            caption_parts.append(str(name))
        if age:
            caption_parts.append(str(age))
        if city:
            caption_parts.append(str(city))
        caption = ', '.join(caption_parts)
        if bio:
            caption = f"{caption}\n{bio}" if caption else bio
        cur.close(); conn.close()
        if photo:
            await _reply_with_photos(update.message, photo, caption or 'Ваш профиль сохранён.', PROFILE_KB, 'Ваш профиль сохранён.')
            return await start_browsing(update, context)
        else:
            await update.message.reply_text(caption or 'Ваш профиль сохранён.', reply_markup=PROFILE_KB)
            return await start_browsing(update, context)
    cur.close(); conn.close()
    await update.message.reply_text('Как тебя зовут?', reply_markup=ReplyKeyboardRemove())
    return NAME


async def name_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    name = (update.message.text or '').strip()
    if not name or re.search(r"[^\w\-А-Яа-яЁё ]", name):
        await update.message.reply_text('Пожалуйста, введите корректное имя без спецсимволов.')
        return NAME
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO Users (PersonID) VALUES (%s)", (uid,))
    cur.execute("UPDATE Users SET UserName = %s, IsActive = %s WHERE PersonID = %s", (name, 1, uid))
    cur.close(); conn.close()
    await update.message.reply_text('Скольк лет?')
    return AGE


async def age_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    try:
        age = int((update.message.text or '').strip())
    except Exception:
        await update.message.reply_text('Пожалуйста, введите корректный возраст (число).')
        return AGE
    if age < 16 or age > 100:
        await update.message.reply_text('Ты далбаёб?')
        return AGE
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE Users SET Age = %s WHERE PersonID = %s", (age, uid))
    cur.close(); conn.close()
    await update.message.reply_text('Укажи пол:', reply_markup=GENDER_KB)
    return GENDER


async def gender_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    txt = (update.message.text or '').strip()
    if txt == 'Я парень':
        gender = 'М'
    elif txt == 'Я девушка':
        gender = 'Ж'
    else:
        await update.message.reply_text('Пожалуйста, выберите пол кнопкой.', reply_markup=GENDER_KB)
        return GENDER
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE Users SET Gender = %s WHERE PersonID = %s", (gender, uid))
    cur.close(); conn.close()
    await update.message.reply_text('Кого ты ищешь?', reply_markup=LOOKING_KB)
    return LOOKING


async def looking_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    txt = (update.message.text or '').strip()
    if txt == 'Парни':
        looking = 'М'
    elif txt == 'Девушки':
        looking = 'Ж'
    elif txt == 'Всех':
        looking = 'ALL'  # Special marker for "search all"
    else:
        await update.message.reply_text('Пожалуйста, выбери вариант кнопкой.', reply_markup=LOOKING_KB)
        return LOOKING
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE Users SET Looking = %s WHERE PersonID = %s", (looking, uid))
    cur.close(); conn.close()
    await update.message.reply_text('Выбери институт:', reply_markup=INSTITUTES_KB)
    return CITY


async def city_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    institute = (update.message.text or '').strip()
    if institute not in INSTITUTES:
        await update.message.reply_text('Пожалуйста, выбери институт кнопкой.', reply_markup=INSTITUTES_KB)
        return CITY
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE Users SET City = %s WHERE PersonID = %s", (institute, uid))
    cur.close(); conn.close()
    await update.message.reply_text('Напишите пару слов о себе (или нажмите пропустить)✨', reply_markup=SKIP_BIO_KB)
    return BIO


async def bio_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    text = (update.message.text or '').strip()
    bio = '' if text == 'Пропустить' else text
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE Users SET Bio = %s WHERE PersonID = %s", (bio, uid))
    cur.close(); conn.close()
    await update.message.reply_text('Отправь фото для профиля (обязательно).', reply_markup=ReplyKeyboardRemove())
    return PHOTO


async def save_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    message = update.message
    if not message:
        return PHOTO

    if message.photo:
        photo = message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        os.makedirs(f'user_photos/{uid}', exist_ok=True)
        filename = f"{uid}_{photo.file_unique_id}.jpg"
        path = os.path.join('user_photos', str(uid), filename)
        await file.download_to_drive(path)

        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT Photo FROM Users WHERE PersonID = %s", (uid,))
        row = cur.fetchone()
        paths = _load_photo_paths(row[0] if row and row[0] else None)
        paths.append(path)
        photo_field = _dump_photo_paths(paths)
        cur.execute("UPDATE Users SET Photo = %s, IsActive = 1 WHERE PersonID = %s", (photo_field, uid))
        conn.commit()
        cur.close(); conn.close()

        count = len(paths)
        if count >= MAX_PROFILE_PHOTOS:
            return await _finalize_photo_collection(update, uid)

        await update.message.reply_text(
            f'Фото добавлено ({count}/{MAX_PROFILE_PHOTOS}). Отправьте ещё или напишите "Готово".',
            reply_markup=ReplyKeyboardRemove()
        )
        return PHOTO

    text = (message.text or '').strip().lower()
    if text in {'готово', 'готово!', 'готов', 'всё', 'все', 'done'}:
        return await _finalize_photo_collection(update, uid)

    await update.message.reply_text('Отправьте фото или напишите "Готово", когда закончите.', reply_markup=ReplyKeyboardRemove())
    return PHOTO


async def _finalize_photo_collection(update: Update, uid: int, success_text: str = 'Твоя анкета готова🎉') -> int:
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT UserName, Age, City, Bio, Photo FROM Users WHERE PersonID = %s", (uid,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        await update.message.reply_text('Профиль не найден.', reply_markup=PROFILE_KB)
        return MATCHING

    name = row[0] or ''
    age = row[1] or ''
    city = row[2] or ''
    bio = row[3] or ''
    photo = row[4]
    caption = create_profile_caption(name, age, city, bio)
    await _reply_with_photos(update.message, photo, caption or 'Ваш профиль.', PROFILE_KB, caption or 'Ваш профиль.')
    await update.message.reply_text(success_text, reply_markup=PROFILE_KB)
    return MATCHING


def _profile_is_complete(cur, uid: int) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM Users WHERE PersonID = %s AND UserName IS NOT NULL AND Age IS NOT NULL AND Gender IS NOT NULL AND Looking IS NOT NULL AND City IS NOT NULL AND IsActive = 1",
        (uid,)
    )
    return cur.fetchone()[0] > 0


def _get_my_profile(cur, uid: int):
    cur.execute("SELECT Gender, Looking, Age FROM Users WHERE PersonID = %s", (uid,))
    return cur.fetchone()


def _find_candidate(cur, uid: int, match_gender: str, user_gender: str, min_age: int, max_age: int):
    print(f"DEBUG _find_candidate: uid={uid}, match_gender='{match_gender}', user_gender='{user_gender}', age_range={min_age}-{max_age}")
    
    # Debug: Check what users exist in database
    cur.execute("SELECT COUNT(*) FROM Users WHERE IsActive = 1 AND Photo IS NOT NULL")
    total_active_result = cur.fetchone()
    total_active = total_active_result[0] if total_active_result else 0
    print(f"DEBUG _find_candidate: Total active users with photos: {total_active}")
    
    if match_gender is not None:
        cur.execute("SELECT COUNT(*) FROM Users WHERE Gender = %s AND IsActive = 1 AND Photo IS NOT NULL", (match_gender,))
        gender_active_result = cur.fetchone()
        gender_active = gender_active_result[0] if gender_active_result else 0
        print(f"DEBUG _find_candidate: Active users with gender {match_gender}: {gender_active}")
    
    cur.execute("SELECT COUNT(*) FROM Likes WHERE LikeUserID = %s", (uid,))
    user_likes_result = cur.fetchone()
    user_likes = user_likes_result[0] if user_likes_result else 0
    print(f"DEBUG _find_candidate: User {uid} has {user_likes} likes")
    
    # If match_gender is None, search for all users (no gender filtering)
    if match_gender is None:
        print(f"DEBUG _find_candidate: Searching for ALL users, Looking={user_gender}, Age={min_age}-{max_age}")
        cur.execute(
            "SELECT PersonID, UserName, Age, City, Bio, Photo FROM Users WHERE (Looking = %s OR Looking = 'ALL') AND IsActive = 1 AND PersonID != %s AND PersonID NOT IN (SELECT PersonID FROM banned) AND PersonID NOT IN (SELECT LikedUserID FROM Likes WHERE LikeUserID = %s AND (MesToPerson = '__LIKE__' OR MesToPerson = '__DISLIKE__' OR MesToPerson = '__MUTUAL_PENDING__' OR MesToPerson = '__SHOWN__')) AND Age BETWEEN %s AND %s AND Photo IS NOT NULL ORDER BY RANDOM() LIMIT 1",
            (user_gender, uid, uid, min_age, max_age),
        )
        candidate = cur.fetchone()
        print(f"DEBUG _find_candidate: First query result: {candidate}")
        
        # If no candidate found with age restrictions, try without age restrictions
        if not candidate:
            print(f"DEBUG _find_candidate: Second query - Looking={user_gender}, no age limit")
            cur.execute(
                "SELECT PersonID, UserName, Age, City, Bio, Photo FROM Users WHERE (Looking = %s OR Looking = 'ALL') AND IsActive = 1 AND PersonID != %s AND PersonID NOT IN (SELECT PersonID FROM banned) AND PersonID NOT IN (SELECT LikedUserID FROM Likes WHERE LikeUserID = %s AND (MesToPerson = '__LIKE__' OR MesToPerson = '__DISLIKE__' OR MesToPerson = '__MUTUAL_PENDING__' OR MesToPerson = '__SHOWN__')) AND Photo IS NOT NULL ORDER BY RANDOM() LIMIT 1",
                (user_gender, uid, uid),
            )
            candidate = cur.fetchone()
            print(f"DEBUG _find_candidate: Second query result: {candidate}")
        
        # If still no candidate found, try without mutual compatibility check (search for ANYONE looking for this user or ALL)
        if not candidate:
            print(f"DEBUG _find_candidate: Third query - no looking preference, but still only those looking for user")
            cur.execute(
                "SELECT PersonID, UserName, Age, City, Bio, Photo FROM Users WHERE (Looking = %s OR Looking = 'ALL') AND IsActive = 1 AND PersonID != %s AND PersonID NOT IN (SELECT PersonID FROM banned) AND PersonID NOT IN (SELECT LikedUserID FROM Likes WHERE LikeUserID = %s AND (MesToPerson = '__LIKE__' OR MesToPerson = '__DISLIKE__' OR MesToPerson = '__MUTUAL_PENDING__' OR MesToPerson = '__SHOWN__')) AND Photo IS NOT NULL ORDER BY RANDOM() LIMIT 1",
                (user_gender, uid, uid),
            )
            candidate = cur.fetchone()
            print(f"DEBUG _find_candidate: Third query result: {candidate}")
    else:
        # candidate's Gender must match match_gender and candidate must be looking for user's gender
        print(f"DEBUG _find_candidate: First query - looking for Gender={match_gender}, Looking={user_gender}, Age={min_age}-{max_age}")
        cur.execute(
            "SELECT PersonID, UserName, Age, City, Bio, Photo FROM Users WHERE Gender = %s AND Looking = %s AND IsActive = 1 AND PersonID != %s AND PersonID NOT IN (SELECT PersonID FROM banned) AND PersonID NOT IN (SELECT LikedUserID FROM Likes WHERE LikeUserID = %s AND (MesToPerson = '__LIKE__' OR MesToPerson = '__DISLIKE__' OR MesToPerson = '__MUTUAL_PENDING__' OR MesToPerson = '__SHOWN__')) AND Age BETWEEN %s AND %s AND Photo IS NOT NULL ORDER BY RANDOM() LIMIT 1",
            (match_gender, user_gender, uid, uid, min_age, max_age),
        )
        candidate = cur.fetchone()
        print(f"DEBUG _find_candidate: First query result: {candidate}")
        
        # If no candidate found with age restrictions, try without age restrictions
        if not candidate:
            print(f"DEBUG _find_candidate: Second query - looking for Gender={match_gender}, Looking={user_gender}, no age limit")
            cur.execute(
                "SELECT PersonID, UserName, Age, City, Bio, Photo FROM Users WHERE Gender = %s AND Looking = %s AND IsActive = 1 AND PersonID != %s AND PersonID NOT IN (SELECT PersonID FROM banned) AND PersonID NOT IN (SELECT LikedUserID FROM Likes WHERE LikeUserID = %s AND (MesToPerson = '__LIKE__' OR MesToPerson = '__DISLIKE__' OR MesToPerson = '__MUTUAL_PENDING__' OR MesToPerson = '__SHOWN__')) AND Photo IS NOT NULL ORDER BY RANDOM() LIMIT 1",
                (match_gender, user_gender, uid, uid),
            )
            candidate = cur.fetchone()
            print(f"DEBUG _find_candidate: Second query result: {candidate}")
        
        # If still no candidate found, try without mutual compatibility check
        if not candidate:
            print(f"DEBUG _find_candidate: Third query - looking for Gender={match_gender}, no looking preference")
            cur.execute(
                "SELECT PersonID, UserName, Age, City, Bio, Photo FROM Users WHERE Gender = %s AND IsActive = 1 AND PersonID != %s AND PersonID NOT IN (SELECT PersonID FROM banned) AND PersonID NOT IN (SELECT LikedUserID FROM Likes WHERE LikeUserID = %s AND (MesToPerson = '__LIKE__' OR MesToPerson = '__DISLIKE__' OR MesToPerson = '__MUTUAL_PENDING__' OR MesToPerson = '__SHOWN__')) AND Photo IS NOT NULL ORDER BY RANDOM() LIMIT 1",
                (match_gender, uid, uid),
            )
            candidate = cur.fetchone()
            print(f"DEBUG _find_candidate: Third query result: {candidate}")
    
    return candidate


async def matching(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    uid = context.user_data.get('user_id', update.effective_user.id)
    context.user_data['user_id'] = uid
    text = (update.message.text or '').strip() if update.message else ''
    print(f"DEBUG matching(): User {uid} sent text: '{text}'")

    # Handle profile management buttons
    if text == START_BROWSING:
        if context.user_data.pop('allow_reset', None):
            print(f"DEBUG: User {uid} triggered START_OVER via START_BROWSING button")
            conn = get_conn(); cur = conn.cursor()
            cur.execute("DELETE FROM Likes WHERE LikeUserID = %s", (uid,))
            cur.close(); conn.close()
            await update.message.reply_text('История просмотров сброшена! Начинаем заново.')
            return await start_browsing(update, context)

        # Check if user was viewing likers and wants to continue
        if 'likers_list' in context.user_data and 'likers_index' in context.user_data:
            # Check if there are still likers to view
            likers = context.user_data.get('likers_list', [])
            index = context.user_data.get('likers_index', 0)
            if index < len(likers):
                # Continue viewing likers from where they left off
                await show_next_liker(update, context)
                return VIEW_LIKERS
            else:
                # No more likers, clear state and start normal browsing
                context.user_data.pop('likers_list', None)
                context.user_data.pop('likers_index', None)
                context.user_data.pop('liked_user_id', None)
                return await start_browsing(update, context)
        else:
            # Start normal browsing
            return await start_browsing(update, context)
    
    if text == BACK_TO_PROFILE:
        # Clear any current candidate
        context.user_data.pop('liked_user_id', None)
        context.user_data.pop('awaiting_message', None)
        
        # Show user's profile and return to profile management
        uid = update.effective_user.id
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT UserName, Age, City, Bio, Photo FROM Users WHERE PersonID = %s", (uid,))
        row = cur.fetchone()
        cur.close(); conn.close()
        
        if row:
            name = row[0] if row[0] is not None else ''
            age = row[1] if row[1] is not None else ''
            city = row[2] if row[2] is not None else ''
            bio = row[3] if row[3] is not None else ''
            photo = row[4] if row[4] is not None else ''
            
            caption_parts = []
            if name:
                caption_parts.append(str(name))
            if age:
                caption_parts.append(str(age))
            if city:
                caption_parts.append(str(city))
            caption = ', '.join(caption_parts)
            if bio:
                caption = f"{caption}\n{bio}" if caption else bio
            
            await _reply_with_photos(update.message, photo, caption or 'Ваш профиль.', PROFILE_KB, caption or 'Ваш профиль.')
        else:
            await update.message.reply_text('Профиль не найден.', reply_markup=PROFILE_KB)
        
        return MATCHING
    
    if text == EDIT_BIO:
        await update.message.reply_text('Напишите новое описание о себе (или нажмите пропустить)✨', reply_markup=SKIP_BIO_KB)
        return EDIT_BIO_STATE
    
    if text == EDIT_PHOTO:
        uid = update.effective_user.id
        _clear_user_photos(uid)
        await update.message.reply_text('Предыдущие фото удалены. Отправьте новые снимки (до 5) и напишите "Готово" когда закончите.', reply_markup=ReplyKeyboardRemove())
        return EDIT_PHOTO_STATE
    
    if text == REMAKE_PROFILE:
        return await remake_profile_handler(update, context)
    
    
    
    # Handle message notification buttons (now also handles like notifications)
    if text == VIEW_MESSAGE_PROFILE:
        handled = await show_pending_mutual(update, context, silent=True)
        if handled is not None:
            return handled
        return await show_message_sender_profile(update, context)

    if text == SKIP_MESSAGE:
        handled = await skip_pending_mutual(update, context, silent=True)
        if handled is not None:
            return handled
        return await show_message_sender_profile(update, context)

    if text == VIEW_MUTUAL_BUTTON:
        return await show_pending_mutual(update, context)
    if text == SKIP_MUTUAL_BUTTON:
        return await skip_pending_mutual(update, context)

    # Handle message response workflow - REMOVED, using new system instead

    # Handle awaiting message workflow: if user was asked to send a message
    awaiting = context.user_data.get('awaiting_message')
    if awaiting and text and update.message and not update.message.photo:
        # send stored message to target user (store alongside like marker)
        target_id = awaiting
        msg_text = text
        conn = get_conn(); cur = conn.cursor()
        
        # Get sender's profile info for the message
        cur.execute("SELECT UserName, Age FROM Users WHERE PersonID = %s", (uid,))
        sender_info = cur.fetchone()
        sender_name = sender_info[0] if sender_info and sender_info[0] else 'Пользователь'
        sender_age = sender_info[1] if sender_info and sender_info[1] else ''
        
        # upsert message text while preserving like marker
        cur.execute(
            """
            INSERT INTO Likes (LikeUserID, LikedUserID, MesToPerson, MessageText)
            VALUES (%s, %s, '__LIKE__', %s)
            ON CONFLICT(LikeUserID, LikedUserID)
            DO UPDATE SET MesToPerson='__LIKE__', MessageText=excluded.MessageText
            """,
            (uid, target_id, msg_text)
        )
        cur.close(); conn.close()
        
        # notify sender
        await update.message.reply_text('Сообщение отправлено! Продолжаем поиск...')
        
        # notify the target user about the new message
        await send_message_notification(update, context, target_id, uid, msg_text)
        
        context.user_data.pop('awaiting_message', None)

    # Normal browsing actions
    # If user pressed like
    if text == '❤️':
        liker = uid
        liked = context.user_data.get('liked_user_id')
        
        # Check if this was a response to a message
        message_sender = context.user_data.get('current_message_sender')
        message_text = context.user_data.get('current_message_text')
        
        if liked:
            conn = get_conn(); cur = conn.cursor()
            
            # Check if this was a response to a message
            # If yes, it's automatically a mutual like (sender already liked when sending message)
            is_message_response = message_sender and message_sender == liked and message_text
            
            # If this was a response to a message, mark the message as processed
            if is_message_response:
                cur.execute(
                    "UPDATE Likes SET MessageText = NULL, MesToPerson = '__PROCESSED__' WHERE LikeUserID = %s AND LikedUserID = %s",
                    (message_sender, uid)
                )
                context.user_data.pop('current_message_sender', None)
                context.user_data.pop('current_message_text', None)
            
            # mark like; set MesToPerson='__LIKE__' to indicate simple like
            # First check if this like already exists
            cur.execute("SELECT 1 FROM Likes WHERE LikeUserID = %s AND LikedUserID = %s", (liker, liked))
            existing_like = cur.fetchone()
            if not existing_like:
                cur.execute("INSERT INTO Likes (LikeUserID, LikedUserID, MesToPerson) VALUES (%s, %s, %s)", (liker, liked, '__LIKE__'))
            else:
                # Update existing like to ensure it's marked as '__LIKE__'
                cur.execute("UPDATE Likes SET MesToPerson = '__LIKE__' WHERE LikeUserID = %s AND LikedUserID = %s", (liker, liked))
            # Debug: log the like creation
            print(f"DEBUG: Created like - From: {liker}, To: {liked}, Status: __LIKE__")
            
            # check for mutual like (or if it was a message response, it's automatically mutual)
            if is_message_response:
                # Sending a message implies a like, so response is mutual
                mutual = True
            else:
                # Check if there's a like from the other user
                cur.execute("SELECT 1 FROM Likes WHERE LikeUserID = %s AND LikedUserID = %s AND MesToPerson = '__LIKE__'", (liked, liker))
                mutual = cur.fetchone()
            
            if not mutual:
                # notify the liked user about the like (only if not mutual)
                try:
                    # Send like notification with liker info
                    await send_like_notification(update, context, liked, liker)
                except Exception:
                    # cannot send (user hasn't started bot) — just continue
                    pass
            
            if mutual:
                # Mutual like - notify both users and reveal profiles
                cur.execute("SELECT PersonID, UserName, Age, City, Bio, Photo FROM Users WHERE PersonID = %s", (uid,))
                p1 = cur.fetchone()
                
                cur.execute("SELECT PersonID, UserName, Age, City, Bio, Photo FROM Users WHERE PersonID = %s", (liked,))
                p2 = cur.fetchone()
                
                cur.close(); conn.close()
                
                # helper to build caption
                def _cap_likers(row):
                    if not row:
                        return ''
                    _, name, age, city, bio, _photo = row
                    parts = []
                    if name:
                        parts.append(str(name))
                    if age:
                        parts.append(str(age))
                    if city:
                        parts.append(str(city))
                    cap = ', '.join(parts)
                    if bio:
                        cap = f"{cap}\n{bio}" if cap else bio
                    return cap
                
                async def _tg_username(bot, uid):
                    try:
                        chat = await bot.get_chat(uid)
                        uname = getattr(chat, 'username', None)
                        if uname:
                            return f'@{uname}'
                    except Exception:
                        pass
                    return None
                
                uname_liked = await _tg_username(context.bot, liked)
                
                # Send notification to current user (the one who just liked back)
                try:
                    if p2:
                        caption = f"{_cap_likers(p2)}"
                        if uname_liked:
                            caption += f"\n\nЮзернейм: {uname_liked}"
                        await update.message.reply_text("Взаимная анкета, можете начать общение!")
                        await _reply_with_photos(update.message, p2[5], caption, None, caption)
                except Exception as e:
                    logger.error(f"Error sending mutual like notification: {e}")
                    await update.message.reply_text('Это взаимный лайк!')

                try:
                    await context.bot.send_message(
                        chat_id=liked,
                        text=MUTUAL_PROMPT_TEXT,
                        reply_markup=MUTUAL_PROMPT_KB
                    )
                except Exception:
                    pass

                # Queue the original liker for viewing and mark current user's like as processed
                try:
                    conn_mark = get_conn(); cur_mark = conn_mark.cursor()
                    cur_mark.execute(
                        "UPDATE Likes SET MesToPerson = '__MUTUAL_PENDING__', MessageText = NULL WHERE LikeUserID = %s AND LikedUserID = %s",
                        (liked, liker)
                    )
                    cur_mark.execute(
                        "UPDATE Likes SET MesToPerson = '__PROCESSED__', MessageText = NULL WHERE LikeUserID = %s AND LikedUserID = %s",
                        (liker, liked)
                    )
                    cur_mark.close(); conn_mark.close()
                except Exception as e:
                    logger.error(f"Error marking mutual likes as pending: {e}")
            else:
                cur.close(); conn.close()
                #await update.message.reply_text('Вы поставили лайк. Получатель получит приглашение ответить на анкету.')
            
            # Continue browsing after like
            return await start_browsing(update, context)

    # If user pressed dislike — record as a dislike so candidate won't be shown again
    if text == '❌':
        disliked = context.user_data.get('liked_user_id')
        
        # Check if this was a response to a message
        message_sender = context.user_data.get('current_message_sender')
        message_text = context.user_data.get('current_message_text')
        
        if disliked:
            conn = get_conn(); cur = conn.cursor()
            
            # If this was a response to a message, mark the message as processed
            if message_sender and message_sender == disliked and message_text:
                cur.execute(
                    "UPDATE Likes SET MessageText = NULL, MesToPerson = '__PROCESSED__' WHERE LikeUserID = %s AND LikedUserID = %s",
                    (message_sender, uid)
                )
                context.user_data.pop('current_message_sender', None)
                context.user_data.pop('current_message_text', None)
                cur.close(); conn.close()
                await update.message.reply_text('Письмо пропущено. Продолжаем поиск...')
                return await start_browsing(update, context)
            
            # use MesToPerson marker to indicate dislike
            cur.execute("INSERT OR REPLACE INTO Likes (LikeUserID, LikedUserID, MesToPerson) VALUES (%s, %s, %s)", (uid, disliked, '__DISLIKE__'))
            cur.execute(
                "UPDATE Likes SET MesToPerson = '__PROCESSED__', MessageText = NULL WHERE LikeUserID = %s AND LikedUserID = %s AND MesToPerson = '__LIKE__'",
                (disliked, uid)
            )
            cur.close(); conn.close()
            #await update.message.reply_text('Понял, пропускаем эту анкету. Продолжаем...')
            
            # Continue browsing after dislike
            return await start_browsing(update, context)

    # If user wants to send a message to candidate
    if text == '💌':
        liked = context.user_data.get('liked_user_id')
        if liked:
            context.user_data['awaiting_message'] = liked
            await update.message.reply_text('Введите текст сообщения для этой анкеты:')
            return MATCHING

    # If user pressed sleep - stop browsing and return to profile management
    if text == '🏡':
        # Clear any current candidate
        context.user_data.pop('liked_user_id', None)
        context.user_data.pop('awaiting_message', None)
        
        # Show user's profile and return to profile management
        uid = update.effective_user.id
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT UserName, Age, City, Bio, Photo FROM Users WHERE PersonID = %s", (uid,))
        row = cur.fetchone()
        cur.close(); conn.close()
        
        if row:
            name = row[0] if row[0] is not None else ''
            age = row[1] if row[1] is not None else ''
            city = row[2] if row[2] is not None else ''
            bio = row[3] if row[3] is not None else ''
            photo = row[4] if row[4] is not None else ''
            
            caption_parts = []
            if name:
                caption_parts.append(str(name))
            if age:
                caption_parts.append(str(age))
            if city:
                caption_parts.append(str(city))
            caption = ', '.join(caption_parts)
            if bio:
                caption = f"{caption}\n{bio}" if caption else bio
            
            await _reply_with_photos(update.message, photo, caption or 'Ваш профиль.', PROFILE_KB, caption or 'Ваш профиль.')
        else:
            await update.message.reply_text('Просмотр анкет остановлен.', reply_markup=PROFILE_KB)
        
        return MATCHING

    # If user pressed sleep/next: just move to next
    # any other text will be treated as 'next' unless awaiting_message consumed it

    # Load next candidate
    conn = get_conn(); cur = conn.cursor()
    if not _profile_is_complete(cur, uid):
        cur.close(); conn.close()
        await update.message.reply_text('Пожалуйста, заполните профиль сначала (/start).')
        return NAME

    row = _get_my_profile(cur, uid)
    if not row:
        cur.close(); conn.close()
        await update.message.reply_text('Пожалуйста, заполните профиль (/start).')
        return NAME
    gender, looking, my_age = row
    
    # Handle "ALL" option - search for all regardless of gender
    if looking == 'ALL':
        match_gender = None  # No gender filtering
    else:
        match_gender = 'М' if looking == 'М' else 'Ж'

    # pass user's own gender as user_gender so candidates are looking for this gender
    candidate = _find_candidate(cur, uid, match_gender, gender, my_age - 5, my_age + 5)
    if not candidate:
        # No more candidates found - show start over button
        cur.close(); conn.close()
        print(f"DEBUG: No candidates found for user {uid}, showing START_OVER_KB")
        await update.message.reply_text('Все анкеты просмотрены!✨ Нажмите "Погнали🚀" чтобы просмотреть анкеты снова.', reply_markup=START_OVER_KB)
        return MATCHING

    candidate_id, candidate_name, candidate_age, candidate_city, candidate_bio, candidate_photo = candidate
    context.user_data['liked_user_id'] = candidate_id
    _mark_candidate_seen(cur, uid, candidate_id)
    cur.close(); conn.close()

    caption = f"{candidate_name}, {candidate_age}"
    if candidate_city:
        caption += f", {candidate_city}"
    caption += f"\n{candidate_bio or ''}"
    await _reply_with_photos(update.message, candidate_photo, caption, LIKE_KB, caption)
    return MATCHING


async def edit_bio_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    text = (update.message.text or '').strip()
    bio = '' if text == 'Пропустить' else text
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE Users SET Bio = %s WHERE PersonID = %s", (bio, uid))
    
    # Fetch updated profile to show to user
    cur.execute("SELECT UserName, Age, City, Bio, Photo FROM Users WHERE PersonID = %s", (uid,))
    row = cur.fetchone()
    cur.close(); conn.close()
    
    name = row[0] if row and row[0] is not None else ''
    age = row[1] if row and row[1] is not None else ''
    city = row[2] if row and row[2] is not None else ''
    bio = row[3] if row and row[3] is not None else ''
    photo = row[4] if row and row[4] is not None else ''
    
    caption_parts = []
    if name:
        caption_parts.append(str(name))
    if age:
        caption_parts.append(str(age))
    if city:
        caption_parts.append(str(city))
    caption = ', '.join(caption_parts)
    if bio:
        caption = f"{caption}\n{bio}" if caption else bio
    
    await _reply_with_photos(update.message, photo, caption or 'Профиль обновлён.', PROFILE_KB, caption or 'Профиль обновлён.')
    return MATCHING


async def edit_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    message = update.message
    if not message:
        return EDIT_PHOTO_STATE

    if message.photo:
        photo = message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        os.makedirs(f'user_photos/{uid}', exist_ok=True)
        filename = f"{uid}_{photo.file_unique_id}.jpg"
        path = os.path.join('user_photos', str(uid), filename)
        await file.download_to_drive(path)

        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT Photo FROM Users WHERE PersonID = %s", (uid,))
        row = cur.fetchone()
        paths = _load_photo_paths(row[0] if row and row[0] else None)
        paths.append(path)
        photo_field = _dump_photo_paths(paths)
        cur.execute("UPDATE Users SET Photo = %s WHERE PersonID = %s", (photo_field, uid))
        conn.commit()
        cur.close(); conn.close()

        count = len(paths)
        if count >= MAX_PROFILE_PHOTOS:
            return await _finalize_photo_collection(update, uid, 'Профиль обновлён.')

        await update.message.reply_text(
            f'Фото добавлено ({count}/{MAX_PROFILE_PHOTOS}). Отправьте ещё или напишите "Готово".',
            reply_markup=ReplyKeyboardRemove()
        )
        return EDIT_PHOTO_STATE

    text = (message.text or '').strip().lower()
    if text in {'очистить', 'очистка', 'clear'}:
        _clear_user_photos(uid)
        await update.message.reply_text('Все фото удалены. Отправьте новые снимки.', reply_markup=ReplyKeyboardRemove())
        return EDIT_PHOTO_STATE

    if text in {'готово', 'готово!', 'готов', 'всё', 'все', 'done'}:
        return await _finalize_photo_collection(update, uid, 'Профиль обновлён.')

    await update.message.reply_text('Отправьте новое фото или напишите "Готово".', reply_markup=ReplyKeyboardRemove())
    return EDIT_PHOTO_STATE


async def remake_profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    _clear_user_photos(uid)
    conn = get_conn(); cur = conn.cursor()
    # Reset profile data but keep consent
    cur.execute("UPDATE Users SET UserName = NULL, Age = NULL, Gender = NULL, Looking = NULL, City = NULL, Bio = NULL, Photo = NULL, IsActive = 0 WHERE PersonID = %s", (uid,))
    cur.close(); conn.close()
    
    await update.message.reply_text('Анкета сброшена. Давайте создадим новую анкету! Кто ты воин??(Имя)', reply_markup=ReplyKeyboardRemove())
    return NAME


async def send_like_notification(update: Update, context: ContextTypes.DEFAULT_TYPE, liked_user_id: int, liker_id: int):
    """Send notification about new like to the user"""
    conn = get_conn(); cur = conn.cursor()
    
    # Unified notification text (no counters)
    notification_text = 'кому-то понравилась твоя анкета✨\nпосмотрим?)'
    
    try:
        await context.bot.send_message(
            chat_id=liked_user_id,
            text=notification_text,
            reply_markup=MESSAGE_PROFILE_KB
        )
    except Exception as e:
        # Cannot send notification (user hasn't started bot or blocked bot)
        logger.warning(f"Failed to send like notification to user {liked_user_id}: {e}")
    
    cur.close(); conn.close()


async def send_message_notification(update: Update, context: ContextTypes.DEFAULT_TYPE, recipient_id: int, sender_id: int, message_text: str):
    """Send notification about new message to the user"""
    conn = get_conn(); cur = conn.cursor()
    
    # Get sender's profile info
    cur.execute("SELECT UserName, Age FROM Users WHERE PersonID = %s", (sender_id,))
    sender_info = cur.fetchone()
    sender_name = sender_info[0] if sender_info and sender_info[0] else 'Пользователь'
    sender_age = sender_info[1] if sender_info and sender_info[1] else ''
    
    cur.close(); conn.close()
    
    # Send notification about new message
    notification_text = 'кто то прислал тебе письмо💌\nпосмотрим?)'
    #if sender_age:
        #notification_text += f', {sender_age}'
    #notification_text += f':\n\n"{message_text}"'
    
    try:
        await context.bot.send_message(
            chat_id=recipient_id,
            text=notification_text,
            reply_markup=MESSAGE_PROFILE_KB
        )
        
    except Exception as e:
        # Cannot send notification (user hasn't started bot or blocked bot)
        logger.warning(f"Failed to send message notification to user {recipient_id}: {e}")


async def show_message_sender_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle showing the profile of message sender or liker"""
    uid = update.effective_user.id
    text = (update.message.text or '').strip()

    conn = get_conn(); cur = conn.cursor()
    try:
        if text == VIEW_MESSAGE_PROFILE:
            cur.execute(
                """
                SELECT LikeUserID FROM Likes 
                WHERE LikedUserID = %s AND MesToPerson = '__LIKE__' AND (MessageText IS NULL OR MessageText = '')
                ORDER BY id DESC LIMIT 1
                """,
                (uid,)
            )
            like_row = cur.fetchone()

            if like_row:
                liker_id = like_row[0]
                cur.execute("SELECT PersonID, UserName, Age, City, Bio, Photo FROM Users WHERE PersonID = %s", (liker_id,))
                liker_profile = cur.fetchone()

                if liker_profile:
                    _, sender_name, sender_age, sender_city, sender_bio, sender_photo = liker_profile
                    caption = f"{sender_name or 'Пользователь'}"
                    if sender_age:
                        caption += f", {sender_age}"
                    if sender_city:
                        caption += f", {sender_city}"
                    if sender_bio:
                        caption += f"\\n{sender_bio}"

                    await _reply_with_photos(update.message, sender_photo, caption, LIKERS_KB, caption)

                    context.user_data['liked_user_id'] = liker_id
                    return MATCHING

                await update.message.reply_text('Профиль лайкнувшего не найден.', reply_markup=PROFILE_KB)
                return MATCHING

            # If there are no likes, show the latest letter
            cur.execute(
                """
                SELECT id, LikeUserID, MessageText, MesToPerson
                FROM Likes
                WHERE LikedUserID = %s AND (
                    (MessageText IS NOT NULL AND MessageText != '')
                    OR (MesToPerson NOT LIKE '__%' AND MesToPerson IS NOT NULL AND MesToPerson != '')
                )
                ORDER BY id DESC LIMIT 1
                """,
                (uid,)
            )
            message_row = cur.fetchone()

            if not message_row:
                await update.message.reply_text('Нет сообщений для просмотра.', reply_markup=PROFILE_KB)
                return MATCHING

            row_id, sender_id, stored_message, legacy_value = message_row
            message_text = stored_message or legacy_value or ''

            if (not stored_message) and legacy_value and not str(legacy_value).startswith('__'):
                cur.execute(
                    "UPDATE Likes SET MessageText = %s, MesToPerson = '__LIKE__' WHERE id = %s",
                    (message_text, row_id)
                )

            cur.execute("SELECT PersonID, UserName, Age, City, Bio, Photo FROM Users WHERE PersonID = %s", (sender_id,))
            sender_profile = cur.fetchone()

            if sender_profile:
                _, sender_name, sender_age, sender_city, sender_bio, sender_photo = sender_profile
                caption = f"{sender_name or 'Пользователь'}"
                if sender_age:
                    caption += f", {sender_age}"
                if sender_city:
                    caption += f", {sender_city}"
                if sender_bio:
                    caption += f"\\n{sender_bio}"

                await _reply_with_photos(update.message, sender_photo, caption, MESSAGE_REPLY_KB, caption)

                await update.message.reply_text(f'💌 Сообщение:\n\n"{message_text}"')

                context.user_data['liked_user_id'] = sender_id
                context.user_data['current_message_sender'] = sender_id
                context.user_data['current_message_text'] = message_text

                cur.execute("UPDATE Likes SET MessageText = NULL WHERE id = %s", (row_id,))
                return MATCHING

            await update.message.reply_text('Профиль отправителя не найден.', reply_markup=PROFILE_KB)
            return MATCHING

        elif text == SKIP_MESSAGE:
            cur.execute(
                """
                SELECT LikeUserID FROM Likes 
                WHERE LikedUserID = %s AND MesToPerson = '__LIKE__' AND (MessageText IS NULL OR MessageText = '')
                ORDER BY id DESC LIMIT 1
                """,
                (uid,)
            )
            like_row = cur.fetchone()
            if like_row:
                cur.execute(
                    "UPDATE Likes SET MesToPerson = '__PROCESSED__', MessageText = NULL WHERE LikeUserID = %s AND LikedUserID = %s",
                    (like_row[0], uid)
                )
                await update.message.reply_text('Лайк пропущен.', reply_markup=PROFILE_KB)
                return MATCHING

            cur.execute(
                """
                SELECT id FROM Likes
                WHERE LikedUserID = %s AND (
                    (MessageText IS NOT NULL AND MessageText != '')
                    OR (MesToPerson NOT LIKE '__%' AND MesToPerson IS NOT NULL AND MesToPerson != '')
                )
                ORDER BY id DESC LIMIT 1
                """,
                (uid,)
            )
            row = cur.fetchone()
            if row:
                cur.execute("UPDATE Likes SET MessageText = NULL, MesToPerson = '__PROCESSED__' WHERE id = %s", (row[0],))
                await update.message.reply_text('Пропущено.', reply_markup=PROFILE_KB)
            else:
                await update.message.reply_text('Нет сообщений для просмотра.', reply_markup=PROFILE_KB)
            return MATCHING
    finally:
        cur.close(); conn.close()

    return MATCHING


def _get_pending_mutual(cur, uid: int):
    cur.execute(
        """
        SELECT id, LikedUserID FROM Likes
        WHERE LikeUserID = %s AND MesToPerson = '__MUTUAL_PENDING__'
        ORDER BY id DESC LIMIT 1
        """,
        (uid,)
    )
    return cur.fetchone()


async def show_pending_mutual(update: Update, context: ContextTypes.DEFAULT_TYPE, silent: bool = False):
    uid = update.effective_user.id
    conn = get_conn(); cur = conn.cursor()
    row = _get_pending_mutual(cur, uid)
    if not row:
        cur.close(); conn.close()
        if not silent:
            await update.message.reply_text('Нет взаимных лайков для просмотра.', reply_markup=PROFILE_KB)
            return MATCHING
        return None
    like_id, other_id = row

    cur.execute("SELECT PersonID, UserName, Age, City, Bio, Photo FROM Users WHERE PersonID = %s", (other_id,))
    profile = cur.fetchone()
    cur.execute("UPDATE Likes SET MesToPerson = '__PROCESSED__', MessageText = NULL WHERE id = %s", (like_id,))
    cur.close(); conn.close()

    if not profile:
        await update.message.reply_text('Профиль не найден.', reply_markup=PROFILE_KB)
        return MATCHING

    _, name, age, city, bio, photo = profile
    caption = create_profile_caption(name, age, city, bio)

    async def _tg_username(bot, user_id):
        try:
            chat = await bot.get_chat(user_id)
            uname = getattr(chat, 'username', None)
            if uname:
                return f'@{uname}'
        except Exception:
            pass
        return None

    uname = await _tg_username(context.bot, other_id)
    if uname:
        caption = f"{caption}\n\nЮзернейм: {uname}" if caption else f"Юзернейм: {uname}"

    await update.message.reply_text('Взаимная анкета, можете начать общение')
    await _reply_with_photos(update.message, photo, caption or 'Профиль.', PROFILE_KB, caption or 'Профиль.')
    return MATCHING


async def skip_pending_mutual(update: Update, context: ContextTypes.DEFAULT_TYPE, silent: bool = False):
    uid = update.effective_user.id
    conn = get_conn(); cur = conn.cursor()
    row = _get_pending_mutual(cur, uid)
    if not row:
        cur.close(); conn.close()
        if not silent:
            await update.message.reply_text('Нет взаимных лайков для пропуска.', reply_markup=PROFILE_KB)
            return MATCHING
        return None
    like_id, _ = row
    cur.execute("UPDATE Likes SET MesToPerson = '__PROCESSED__', MessageText = NULL WHERE id = %s", (like_id,))
    cur.close(); conn.close()
    await update.message.reply_text('Хорошо, оповещение скрыто.', reply_markup=PROFILE_KB)
    return MATCHING


async def show_all_likers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show all users who liked the current user"""
    uid = update.effective_user.id
    conn = get_conn(); cur = conn.cursor()
    
    # Get all users who liked this user
    cur.execute("""
        SELECT u.PersonID, u.UserName, u.Age, u.City, u.Bio, u.Photo 
        FROM Users u 
        INNER JOIN Likes l ON u.PersonID = l.LikeUserID 
        WHERE l.LikedUserID = %s AND l.MesToPerson = '__LIKE__' AND (l.MessageText IS NULL OR l.MessageText = '')
        ORDER BY l.id DESC
    """, (uid,))
    
    likers = cur.fetchall()
    cur.close(); conn.close()
    
    if likers:
        # Store likers list and current index
        context.user_data['likers_list'] = likers
        context.user_data['likers_index'] = 0
        
        # Show first liker
        await show_next_liker(update, context)
        return VIEW_LIKERS
    else:
        await update.message.reply_text("Пока никто не лайкнул вашу анкету.", reply_markup=PROFILE_KB)
        return MATCHING




async def show_next_liker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the next liker in the queue"""
    likers = context.user_data.get('likers_list', [])
    index = context.user_data.get('likers_index', 0)
    
    if index < len(likers):
        liker = likers[index]
        liker_id, name, age, city, bio, photo = liker
        
        context.user_data['liked_user_id'] = liker_id
        # Show header with remaining count
        remaining = max(len(likers) - index - 1, 0)
        await update.message.reply_text("кому-то понравилась твоя анкета✨\nпосмотрим?)")
        
        caption = create_profile_caption(name, age, city, bio)
        
        await _reply_with_photos(update.message, photo, caption, LIKERS_KB, caption)
    else:
        # No more likers - clear the state
        context.user_data.pop('likers_list', None)
        context.user_data.pop('likers_index', None)
        context.user_data.pop('liked_user_id', None)
        await update.message.reply_text("Вы просмотрели всех, кто вас лайкнул!", reply_markup=PROFILE_KB)
        # Return to MATCHING state so user can start normal browsing
        return MATCHING


async def view_likers_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle actions when viewing likers"""
    uid = update.effective_user.id
    text = (update.message.text or '').strip()
    
    if text == '❤️':
        # User liked one of their likers - check for mutual like
        liked_user_id = context.user_data.get('liked_user_id')
        
        if liked_user_id:
            conn = get_conn(); cur = conn.cursor()
            
            # Store the like
            cur.execute("INSERT OR REPLACE INTO Likes (LikeUserID, LikedUserID, MesToPerson) VALUES (%s, %s, %s)", 
                       (uid, liked_user_id, '__LIKE__'))
            
            # Check for mutual like
            cur.execute("SELECT 1 FROM Likes WHERE LikeUserID = %s AND LikedUserID = %s AND MesToPerson = '__LIKE__'", 
                       (liked_user_id, uid))
            mutual = cur.fetchone()
            
            cur.close(); conn.close()
            
            if mutual:
                # Mutual like - notify both users and reveal profiles without like/dislike actions
                conn2 = get_conn(); cur2 = conn2.cursor()
                
                cur2.execute("SELECT PersonID, UserName, Age, City, Bio, Photo FROM Users WHERE PersonID = %s", (uid,))
                p1 = cur2.fetchone()
                
                cur2.execute("SELECT PersonID, UserName, Age, City, Bio, Photo FROM Users WHERE PersonID = %s", (liked_user_id,))
                p2 = cur2.fetchone()
                
                # helper to build caption
                def _cap_likers(row):
                    if not row:
                        return ''
                    _, name, age, city, bio, _photo = row
                    parts = []
                    if name:
                        parts.append(str(name))
                    if age:
                        parts.append(str(age))
                    if city:
                        parts.append(str(city))
                    cap = ', '.join(parts)
                    if bio:
                        cap = f"{cap}\n{bio}" if cap else bio
                    return cap
                
                async def _tg_username(bot, uid):
                    try:
                        chat = await bot.get_chat(uid)
                        uname = getattr(chat, 'username', None)
                        if uname:
                            return f'@{uname}'
                    except Exception:
                        pass
                    return None
                
                uname_liker = await _tg_username(context.bot, liked_user_id)
                
                # Send notification to current user (the one who just liked back)
                try:
                    if p2:
                        caption = f"{_cap_likers(p2)}"
                        if uname_liker:
                            caption += f"\n\nЮзернейм: {uname_liker}"
                        
                        await update.message.reply_text("Взаимная анкета, можете начать общение")
                        await _reply_with_photos(update.message, p2[5], caption, None, caption)
                except Exception as e:
                    logger.error(f"Error sending mutual like notification: {e}")
                    await update.message.reply_text('Это взаимный лайк!')
                
                # Send prompt to the original liker
                try:
                    await context.bot.send_message(
                        chat_id=liked_user_id,
                        text=MUTUAL_PROMPT_TEXT,
                        reply_markup=MUTUAL_PROMPT_KB
                    )
                except Exception:
                    pass
                
                cur2.close(); conn2.close()
            else:
                # Notify the liked user that someone liked them (non-mutual case)
                try:
                    await send_like_notification(update, context, liked_user_id, uid)
                except Exception:
                    pass
                await update.message.reply_text('Лайк отправлен. Если это взаимно, вы получите уведомление.')
            
            # Mark both likes as processed so they won't show again
            try:
                conn3 = get_conn(); cur3 = conn3.cursor()
                if mutual:
                    cur3.execute(
                        "UPDATE Likes SET MesToPerson = '__MUTUAL_PENDING__', MessageText = NULL WHERE LikeUserID = %s AND LikedUserID = %s",
                        (liked_user_id, uid)
                    )
                else:
                    cur3.execute(
                        "UPDATE Likes SET MesToPerson = '__PROCESSED__', MessageText = NULL WHERE LikeUserID = %s AND LikedUserID = %s AND MesToPerson = '__LIKE__'",
                        (liked_user_id, uid)
                    )

                cur3.execute(
                    "UPDATE Likes SET MesToPerson = '__PROCESSED__', MessageText = NULL WHERE LikeUserID = %s AND LikedUserID = %s",
                    (uid, liked_user_id)
                )
                cur3.close(); conn3.close()
            except Exception as e:
                logger.error(f"Error marking likes as processed: {e}")
            
            # Move to next liker - skip to next non-processed liker
            likers = context.user_data.get('likers_list', [])
            current_index = context.user_data.get('likers_index', 0)
            
            # Find next non-processed liker
            next_index = current_index + 1
            found_next = False
            
            # Check if there are more likers and refetch to ensure we don't show processed ones
            if next_index < len(likers):
                # Verify the next liker hasn't been processed by checking the database
                conn_check = get_conn(); cur_check = conn_check.cursor()
                while next_index < len(likers):
                    next_liker_id = likers[next_index][0]
                    cur_check.execute("SELECT 1 FROM Likes WHERE LikeUserID = %s AND LikedUserID = %s AND MesToPerson = '__LIKE__' AND (MessageText IS NULL OR MessageText = '')", (next_liker_id, uid))
                    if cur_check.fetchone():
                        # This liker still has an unprocessed like
                        found_next = True
                        break
                    next_index += 1
                cur_check.close(); conn_check.close()
            
            if found_next and next_index < len(likers):
                context.user_data['likers_index'] = next_index
                await show_next_liker(update, context)
                return VIEW_LIKERS
            else:
                # No more likers - clear the state
                context.user_data.pop('likers_list', None)
                context.user_data.pop('likers_index', None)
                context.user_data.pop('liked_user_id', None)
                await update.message.reply_text('Вы просмотрели всех, кто вас лайкнул! Начать просмотр анкет?', reply_markup=BROWSE_KB)
                return MATCHING
    
    elif text == '❌':
        # User skipped this liker - mark processed and move to next
        liked_user_id = context.user_data.get('liked_user_id')
        if liked_user_id:
            try:
                conn = get_conn(); cur = conn.cursor()
                cur.execute("UPDATE Likes SET MesToPerson = '__PROCESSED__', MessageText = NULL WHERE LikeUserID = %s AND LikedUserID = %s AND MesToPerson = '__LIKE__' AND (MessageText IS NULL OR MessageText = '')", (liked_user_id, uid))
                cur.close(); conn.close()
            except Exception:
                pass
        
        context.user_data['likers_index'] = context.user_data.get('likers_index', 0) + 1
        # If no more likers, notify and return to matching with browse keyboard
        likers = context.user_data.get('likers_list', [])
        if context.user_data['likers_index'] >= len(likers):
            context.user_data.pop('likers_list', None)
            context.user_data.pop('likers_index', None)
            context.user_data.pop('liked_user_id', None)
            await update.message.reply_text('Вы просмотрели всех, кто вас лайкнул! Начать просмотр анкет?', reply_markup=BROWSE_KB)
            return MATCHING
        await show_next_liker(update, context)
        return VIEW_LIKERS
    
    elif text == '🏡':
        # User wants to pause viewing likers - save state and return to profile
        # Don't clear likers_list and likers_index - keep them for continuation
        
        # Show profile management
        uid = update.effective_user.id
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT UserName, Age, City, Bio, Photo FROM Users WHERE PersonID = %s", (uid,))
        row = cur.fetchone()
        cur.close(); conn.close()
        
        if row:
            name = row[0] if row[0] is not None else ''
            age = row[1] if row[1] is not None else ''
            city = row[2] if row[2] is not None else ''
            bio = row[3] if row[3] is not None else ''
            photo = row[4] if row[4] is not None else ''
            
            caption = create_profile_caption(name, age, city, bio)
            await _reply_with_photos(update.message, photo, caption or 'Ваш профиль.', PROFILE_KB, caption or 'Ваш профиль.')
        else:
            await update.message.reply_text('Профиль не найден.', reply_markup=PROFILE_KB)
        
        return MATCHING
    
    return VIEW_LIKERS


# respond_to_message function removed - using new message system instead


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('Операция отменена.', reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def respond_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # User chose to respond to the profile; show the profile they were shown (if any) and ask to answer
    uid = update.effective_user.id
    # find any pending like entries where this user is LikedUserID and MesToPerson='__LIKE__'
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT LikeUserID FROM Likes WHERE LikedUserID = %s AND MesToPerson = %s", (uid, '__LIKE__'))
    row = cur.fetchone()
    if not row:
        # Debug: check what likes exist for this user
        cur.execute("SELECT LikeUserID, LikedUserID, MesToPerson FROM Likes WHERE LikedUserID = %s", (uid,))
        all_likes = cur.fetchall()
        cur.close(); conn.close()
        
        debug_info = f"Найдено лайков для пользователя {uid}: {len(all_likes)}\n"
        for like in all_likes:
            debug_info += f"От: {like[0]}, Кому: {like[1]}, Статус: {like[2]}\n"
        
        await update.message.reply_text(f'Нет ожидающих ответов на вашу анкету.\n\n{debug_info}')
        return ConversationHandler.END
    liker_id = row[0]
    # show the profile that liked this user (if available)
    cur.execute("SELECT PersonID, UserName, Age, City, Bio, Photo FROM Users WHERE PersonID = %s", (liker_id,))
    person = cur.fetchone()
    cur.close(); conn.close()
    if person:
        pid, name, age, city, bio, photo = person
        caption = create_profile_caption(name, age, city, bio)
        await _reply_with_photos(update.message, photo, caption, None, caption)
    
    # Try to get telegram usernames for both users
    try:
        # Get liker's username
        liker_chat = await context.bot.get_chat(liker_id)
        liker_username = getattr(liker_chat, 'username', None)
        
        # Get current user's username
        current_user_chat = await context.bot.get_chat(uid)
        current_username = getattr(current_user_chat, 'username', None)
        
        # Send usernames to both users
        if liker_username:
            await update.message.reply_text(f'Юзернейм лайкнувшего: @{liker_username}')
            # Also send current user's username to the liker
            if current_username:
                try:
                    await context.bot.send_message(chat_id=liker_id, text=f'Юзернейм лайкнувшего: @{current_username}')
                except Exception as e:
                    logger.warning(f"Failed to send username to liker {liker_id}: {e}")
        
        # Mark the like as processed
        conn = get_conn(); cur = conn.cursor()
        cur.execute("UPDATE Likes SET MesToPerson = '__PROCESSED__', MessageText = NULL WHERE LikeUserID = %s AND LikedUserID = %s", (liker_id, uid))
        cur.close(); conn.close()
        
    except Exception as e:
        logger.error(f"Failed to get usernames: {e}")
        await update.message.reply_text('Не удалось получить юзернеймы.')
    
    return MATCHING


async def respond_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    text = (update.message.text or '').strip()
    liker = context.user_data.get('pending_from')
    if not liker:
        await update.message.reply_text('Внутренняя ошибка: нет кандидата для ответа.')
        return ConversationHandler.END
    conn = get_conn(); cur = conn.cursor()
    # store the response as a like+message so the recipient can see it later
    cur.execute(
        """
        INSERT INTO Likes (LikeUserID, LikedUserID, MesToPerson, MessageText)
        VALUES (%s, %s, '__LIKE__', %s)
        ON CONFLICT(LikeUserID, LikedUserID)
        DO UPDATE SET MesToPerson='__LIKE__', MessageText=excluded.MessageText
        """,
        (uid, liker, text)
    )
    # fetch liker brief profile
    cur.execute("SELECT PersonID, UserName, Age FROM Users WHERE PersonID = %s", (liker,))
    lk = cur.fetchone()
    cur.close(); conn.close()
    if lk:
        pid, name, age = lk
        await update.message.reply_text(f'Этот пользователь: {name}, {age}')
    else:
        await update.message.reply_text('Пользователь, поставивший лайк, не найден.')
    # Optionally notify liker that their like was answered
    try:
        await context.bot.send_message(chat_id=liker, text=f'Пользователь ответил на вашу анкету: {text}')
    except Exception as e:
        logger.warning(f"Failed to send answer notification to user {liker}: {e}")
    context.user_data.pop('pending_from', None)
    return ConversationHandler.END


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update):
        return
    msg = (
        "Админ-панель:\n"
        "- /ban <id> — заблокировать пользователя\n"
        "- /unban <id> — снять блокировку\n"
        "- /user <id> — данные профиля\n"
        "- /userslist — таблица всех пользователей\n"
        "- /stats — общая статистика"
    )
    await update.message.reply_text(msg)
    # Extra admin commands
    await update.message.reply_text(
        "Дополнительно:\n"
        "- /idby <@username> — найти ID по Telegram-нику\n"
        "- /profile <id> — показать анкету пользователя"
    )
    await update.message.reply_text(
        "- /whois <@username> — ID и анкета по нику"
    )


async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update):
        return
    target = _extract_target_id(update, context)
    if not target:
        await update.message.reply_text('Укажите ID: /ban <id> или ответьте на сообщение.')
        return
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO banned (PersonID) VALUES (%s)", (target,))
    cur.execute("UPDATE Users SET IsActive = 0 WHERE PersonID = %s", (target,))
    conn.commit()
    cur.close(); conn.close()
    # Immediately notify the banned user
    try:
        await _send_ban_message_to_user(context.bot, target)
    except Exception as e:
        logger.warning(f"Failed to proactively send ban notice to {target}: {e}")
    await update.message.reply_text(f'Пользователь {target} заблокирован.')


async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update):
        return
    target = _extract_target_id(update, context)
    if not target:
        await update.message.reply_text('Укажите ID: /unban <id> или ответьте на сообщение.')
        return
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM banned WHERE PersonID = %s", (target,))
    conn.commit()
    cur.close(); conn.close()
    await update.message.reply_text(f'Пользователь {target} разблокирован.')


async def admin_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update):
        return
    target = _extract_target_id(update, context)
    if not target:
        await update.message.reply_text('Укажите ID: /user <id> или ответьте на сообщение.')
        return
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT PersonID, UserName, Age, Gender, Looking, City, Bio, IsActive FROM Users WHERE PersonID = %s", (target,))
    row = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM Likes WHERE LikeUserID = %s", (target,))
    likes_sent = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM Likes WHERE LikedUserID = %s AND MesToPerson = '__LIKE__'", (target,))
    likes_received = cur.fetchone()[0]
    cur.execute("SELECT 1 FROM banned WHERE PersonID = %s", (target,))
    banned = bool(cur.fetchone())
    cur.close(); conn.close()
    if not row:
        await update.message.reply_text('Пользователь не найден.')
        return
    pid, name, age, gender, looking, city, bio, active = row
    info = (
        f'ID: {pid}\n'
        f'Имя: {name}\n'
        f'Возраст: {age}\n'
        f'Пол: {gender}\n'
        f'Ищет: {looking}\n'
        f'Институт: {city}\n'
        f'Активен: {bool(active)}\n'
        f'Заблокирован: {banned}\n'
        f'Лайков отправлено: {likes_sent}\n'
        f'Лайков получено: {likes_received}\n'
        f'Био: {bio or "—"}'
    )
    await update.message.reply_text(info)


async def admin_id_by_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update):
        return
    if not context.args:
        await update.message.reply_text('Укажите @username: /idby <@username>')
        return
    query = context.args[0].strip()
    if not query:
        await update.message.reply_text('Укажите @username: /idby <@username>')
        return
    norm = query.lower()
    if norm.startswith('@'):
        norm = norm[1:]

    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT PersonID, UserName FROM Users ORDER BY PersonID ASC")
    rows = cur.fetchall()
    cur.close(); conn.close()

    matches = []
    for r in rows:
        try:
            pid = r['PersonID'] if isinstance(r, dict) else r[0]
        except Exception:
            pid = r[0]
        uname = await _get_tg_username(context.bot, pid)
        if not uname:
            continue
        if uname[1:].lower() == norm:
            name = None
            try:
                name = r['UserName'] if isinstance(r, dict) else r[1]
            except Exception:
                name = None
            matches.append((pid, uname, name))

    if not matches:
        await update.message.reply_text('Не найдено. Убедитесь, что пользователь запускал бота.')
        return

    if len(matches) == 1:
        pid, uname, name = matches[0]
        await update.message.reply_text(f"{uname} -> ID: {pid}\nИмя: {name or '—'}")
    else:
        lines = ["Найдено несколько совпадений:"]
        for pid, uname, name in matches:
            lines.append(f"{uname} -> ID: {pid} | Имя: {name or '—'}")
        await update.message.reply_text('\n'.join(lines))


async def admin_view_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update):
        return
    target = _extract_target_id(update, context)
    if not target:
        await update.message.reply_text('Укажите ID: /profile <id> или ответьте реплаем на сообщение пользователя.')
        return
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT UserName, Age, City, Bio, Photo FROM Users WHERE PersonID = %s", (target,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        await update.message.reply_text('Пользователь не найден.')
        return
    try:
        # Row may be tuple or dict depending on cursor
        name = row['UserName'] if isinstance(row, dict) else row[0]
        age = row['Age'] if isinstance(row, dict) else row[1]
        city = row['City'] if isinstance(row, dict) else row[2]
        bio = row['Bio'] if isinstance(row, dict) else row[3]
        photo = row['Photo'] if isinstance(row, dict) else row[4]
    except Exception:
        name, age, city, bio, photo = row[0], row[1], row[2], row[3], row[4]

    caption = create_profile_caption(name, age, city, bio)
    await _reply_with_photos(update.message, photo, caption or 'Анкета пользователя.', None, caption or 'Анкета пользователя.')


async def admin_whois(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update):
        return
    if not context.args:
        await update.message.reply_text('Укажите @username: /whois <@username>')
        return
    query = context.args[0].strip()
    if not query:
        await update.message.reply_text('Укажите @username: /whois <@username>')
        return
    norm = query.lower()
    if norm.startswith('@'):
        norm = norm[1:]

    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT PersonID FROM Users ORDER BY PersonID ASC")
    rows = cur.fetchall()
    cur.close(); conn.close()

    match_pid = None
    match_uname = None
    for r in rows:
        try:
            pid = r['PersonID'] if isinstance(r, dict) else r[0]
        except Exception:
            pid = r[0]
        uname = await _get_tg_username(context.bot, pid)
        if uname and uname[1:].lower() == norm:
            match_pid = pid
            match_uname = uname
            break

    if not match_pid:
        await update.message.reply_text('Не найдено. Убедитесь, что пользователь запускал бота.')
        return

    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT UserName, Age, City, Bio, Photo FROM Users WHERE PersonID = %s", (match_pid,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        await update.message.reply_text('Пользователь не найден в базе.')
        return

    try:
        name = row['UserName'] if isinstance(row, dict) else row[0]
        age = row['Age'] if isinstance(row, dict) else row[1]
        city = row['City'] if isinstance(row, dict) else row[2]
        bio = row['Bio'] if isinstance(row, dict) else row[3]
        photo = row['Photo'] if isinstance(row, dict) else row[4]
    except Exception:
        name, age, city, bio, photo = row[0], row[1], row[2], row[3], row[4]

    await update.message.reply_text(f"{match_uname} -> ID: {match_pid}")
    caption = create_profile_caption(name, age, city, bio)
    await _reply_with_photos(update.message, photo, caption or 'Анкета пользователя.', None, caption or 'Анкета пользователя.')

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update):
        return
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM Users")
    total_users = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM Users WHERE IsActive = 1")
    active_users = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM Likes WHERE MesToPerson = '__LIKE__'")
    likes_total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM banned")
    banned_total = cur.fetchone()[0]
    cur.close(); conn.close()
    msg = (
        f'Всего пользователей: {total_users}\n'
        f'Активных: {active_users}\n'
        f'Лайков: {likes_total}\n'
        f'В бане: {banned_total}'
    )
    await update.message.reply_text(msg)


async def admin_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update):
        return
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT PersonID, UserName FROM Users ORDER BY PersonID ASC")
    rows = cur.fetchall()
    cur.close(); conn.close()
    if not rows:
        await update.message.reply_text('Пользователи не найдены.')
        return
    header = "ID | Имя анкеты | Telegram"
    divider = '-' * len(header)
    lines = [header, divider]

    async def flush():
        nonlocal lines
        if len(lines) <= 2:
            return
        await update.message.reply_text('\n'.join(lines))
        lines = [header, divider]

    for r in rows:
        pid = r['PersonID']
        name = (r['UserName'] or '').replace('\n', ' ')
        uname = await _get_tg_username(context.bot, pid) or '—'
        line = f"{pid} | {name} | {uname}"
        if len('\n'.join(lines + [line])) > 3500:
            await flush()
        lines.append(line)

    if len(lines) > 2:
        await update.message.reply_text('\n'.join(lines))


def build_app():
    # SECURITY NOTE: embedding tokens in source is insecure. Use only for
    # quick local testing. Prefer setting TOKEN or TG_BOT_TOKEN in env.
    # If you want an embedded token, set BOT_TOKEN below.
    BOT_TOKEN = None  # <-- Replace None with your token string to embed it (UNSAFE)

    token = "" or os.environ.get('TOKEN') or os.environ.get('TG_BOT_TOKEN')
    if not token:
        return None

    persistence = PicklePersistence(filepath='bot_state.pickle', update_interval=5)
    app = Application.builder().token(token).persistence(persistence).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CONSENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, consent_handler)],
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_step)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, age_step)],
            GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, gender_step)],
            LOOKING: [MessageHandler(filters.TEXT & ~filters.COMMAND, looking_step)],
            CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, city_step)],
            BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, bio_step)],
            PHOTO: [MessageHandler(filters.PHOTO, save_photo), MessageHandler(filters.TEXT & ~filters.COMMAND, save_photo)],
            MATCHING: [MessageHandler(filters.TEXT & ~filters.COMMAND, matching)],
            RESPOND: [MessageHandler(filters.TEXT & ~filters.COMMAND, respond_answer)],
            EDIT_BIO_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_bio_handler)],
            EDIT_PHOTO_STATE: [MessageHandler(filters.PHOTO, edit_photo_handler), MessageHandler(filters.TEXT & ~filters.COMMAND, edit_photo_handler)],
            MESSAGE_PROFILE_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, show_message_sender_profile)],
            VIEW_LIKERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, view_likers_handler)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True,
        name='dating_conv',
        persistent=True,
    )

    # RESPOND_LIKE button removed - no longer needed

    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, ensure_started), group=0)
    app.add_handler(CommandHandler('admin', admin_panel), group=0)
    app.add_handler(CommandHandler('ban', admin_ban), group=0)
    app.add_handler(CommandHandler('unban', admin_unban), group=0)
    app.add_handler(CommandHandler('user', admin_user_info), group=0)
    app.add_handler(CommandHandler('stats', admin_stats), group=0)
    app.add_handler(CommandHandler('userslist', admin_users_list), group=0)
    app.add_handler(CommandHandler('idby', admin_id_by_username), group=0)
    app.add_handler(CommandHandler('profile', admin_view_profile), group=0)
    app.add_handler(CommandHandler('whois', admin_whois), group=0)
    app.add_handler(CommandHandler('idby', admin_id_by_username), group=0)
    app.add_handler(CommandHandler('profile', admin_view_profile), group=0)
    app.add_handler(conv, group=1)
    app.add_handler(CommandHandler('cancel', cancel))
    return app


def main() -> None:
    app = build_app()
    if app is None:
        raise RuntimeError('Please set TOKEN or TG_BOT_TOKEN environment variable to run the bot')
    app.run_polling()


if __name__ == '__main__':
    main()
