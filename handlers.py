from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, 
    CallbackQuery, 
    PreCheckoutQuery, 
    WebAppInfo, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    LabeledPrice
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import database as db
from config import ADMIN_ID, WEBAPP_URL, POLICY_URL, PAYMENT_PROVIDER_TOKEN
import logging

router = Router()
logger = logging.getLogger(__name__)

# Состояния для FSM
class ContentState(StatesGroup):
    waiting_for_price = State()

# Временное хранилище для file_id при добавлении контента админом
temp_admin_content = {}

@router.message(CommandStart())
async def cmd_start(message: Message):
    """Обработка команды /start"""
    user = message.from_user
    db.add_user(user.id, user.username, user.first_name)
    
    logger.info(f"User {user.id} (@{user.username}) started bot")
    
    if db.is_user_banned(user.id):
        await message.answer("⛔ Вы заблокированы и не можете использовать бота.")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🚀 Открыть WebApp",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )]
    ])
    
    await message.answer(
        f"Приветствую, *{user.first_name}*!\n\n"
        f"Здесь ты можешь просматривать и покупать фото и видео разных типов.\n"
        f"Но для начала прочти нашу [политику соглашения]({POLICY_URL}).",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

@router.message(Command("delete"))
async def cmd_delete(message: Message):
    """Удаление контента (только админ)"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет прав для этой команды.")
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer("Использование: /delete <id>")
            return
            
        content_id = int(parts[1])
        
        if db.delete_content(content_id):
            await message.answer(f"✅ Контент #{content_id} удалён.")
            logger.info(f"Admin deleted content #{content_id}")
        else:
            await message.answer(f"❌ Контент #{content_id} не найден.")
    except (IndexError, ValueError):
        await message.answer("❌ Неверный формат. Использование: /delete <id>")

@router.message(Command("ban"))
async def cmd_ban(message: Message):
    """Бан пользователя (только админ)"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет прав для этой команды.")
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer("Использование: /ban <username>")
            return
            
        username = parts[1].replace('@', '')
        
        if db.ban_user(username):
            await message.answer(f"✅ Пользователь @{username} заблокирован.")
            logger.info(f"Admin banned user @{username}")
        else:
            await message.answer(f"❌ Пользователь @{username} не найден.")
    except IndexError:
        await message.answer("❌ Неверный формат. Использование: /ban <username>")

@router.message(Command("approve"))
async def cmd_approve(message: Message):
    """Одобрение контента (только админ)"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет прав для этой команды.")
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer("Использование: /approve <id>")
            return
            
        content_id = int(parts[1])
        
        if db.approve_content(content_id):
            await message.answer(f"✅ Контент #{content_id} одобрен и опубликован.")
            logger.info(f"Admin approved content #{content_id}")
        else:
            await message.answer(f"❌ Контент #{content_id} не найден.")
    except (IndexError, ValueError):
        await message.answer("❌ Неверный формат. Использование: /approve <id>")

@router.message(F.photo | F.video | F.video_note)
async def handle_media(message: Message, state: FSMContext):
    """Обработка фото, видео и кружков"""
    user = message.from_user
    
    if db.is_user_banned(user.id):
        await message.answer("⛔ Вы заблокированы.")
        return
    
    # Определяем тип контента
    if message.photo:
        content_type = "photo"
        file_id = message.photo[-1].file_id
    elif message.video_note:
        content_type = "video_note"
        file_id = message.video_note.file_id
    elif message.video:
        content_type = "video"
        file_id = message.video.file_id
    else:
        return
    
    # Если отправил админ
    if user.id == ADMIN_ID:
        temp_admin_content[user.id] = {
            'type': content_type,
            'file_id': file_id
        }
        await state.set_state(ContentState.waiting_for_price)
        await message.answer(
            "📝 Укажи цену для этого товара (в звёздах Telegram):\n"
            "• 0 — бесплатно\n"
            "• 1 и выше — платно\n\n"
            "Например: 5"
        )
        logger.info(f"Admin uploading content, waiting for price")
    else:
        # Обычный пользователь предлагает контент
        await message.answer("✅ Благодарим за ваше предложение! Оно будет отправлено на модерацию.")
        
        # Отправляем админу на модерацию
        admin_text = (
            f"👤 Пользователь @{user.username or user.id} ({user.first_name}) "
            f"предложил новый контент на проверку.\n"
            f"Тип: {content_type}"
        )
        
        try:
            if content_type == "photo":
                await message.bot.send_photo(ADMIN_ID, file_id, caption=admin_text)
            elif content_type == "video_note":
                await message.bot.send_video_note(ADMIN_ID, file_id)
                await message.bot.send_message(ADMIN_ID, admin_text)
            else:
                await message.bot.send_video(ADMIN_ID, file_id, caption=admin_text)
        except Exception as e:
            logger.error(f"Error sending to admin: {e}")
        
        # Сохраняем в базу как не одобренный
        content_id = db.add_content(content_type, file_id, 0, user.id, approved=False)
        
        # Отправляем админу ID для одобрения
        await message.bot.send_message(
            ADMIN_ID, 
            f"📌 ID контента для модерации: {content_id}\n"
            f"Используй: /approve {content_id}"
        )
        
        logger.info(f"User {user.id} submitted content #{content_id} for moderation")

@router.message(ContentState.waiting_for_price)
async def process_price(message: Message, state: FSMContext):
    """Обработка цены от админа"""
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        price = int(message.text.strip())
        
        if price < 0:
            await message.answer("❌ Цена не может быть отрицательной. Попробуй ещё раз:")
            return
        
        content_data = temp_admin_content.get(message.from_user.id)
        if not content_data:
            await message.answer("❌ Ошибка: контент не найден. Отправь медиа заново.")
            await state.clear()
            return
        
        content_id = db.add_content(
            content_data['type'],
            content_data['file_id'],
            price,
            ADMIN_ID,
            approved=True
        )
        
        price_text = "бесплатно" if price == 0 else f"{price} ⭐"
        await message.answer(
            f"✅ Контент успешно добавлен!\n\n"
            f"📌 ID: {content_id}\n"
            f"💰 Цена: {price_text}\n"
            f"📱 Теперь доступен в WebApp"
        )
        
        logger.info(f"Admin added content #{content_id} with price {price}")
        
        del temp_admin_content[message.from_user.id]
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Введи корректное число. Например: 5")

@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    """Обработка предварительного платежа"""
    logger.info(f"Pre-checkout from user {pre_checkout_query.from_user.id}")
    await pre_checkout_query.answer(ok=True)

@router.message(F.successful_payment)
async def successful_payment(message: Message):
    """Обработка успешного платежа"""
    payment = message.successful_payment
    content_id = int(payment.invoice_payload)
    user_id = message.from_user.id
    
    logger.info(f"Successful payment: user {user_id}, content {content_id}")
    
    # Добавляем покупку в базу
    db.add_purchase(user_id, content_id)
    
    content = db.get_content_by_id(content_id)
    if content:
        await message.answer(
            f"✅ Оплата прошла успешно!\n\n"
            f"💳 Оплачено: {payment.total_amount} ⭐\n"
            f"📱 Контент теперь доступен в твоём профиле в WebApp"
        )
        
        # Отправляем купленный контент
        try:
            if content['type'] == 'photo':
                await message.answer_photo(
                    content['file_id'],
                    caption=f"📷 Твоя покупка #{content_id}"
                )
            elif content['type'] == 'video_note':
                await message.answer_video_note(content['file_id'])
            else:
                await message.answer_video(
                    content['file_id'],
                    caption=f"🎥 Твоя покупка #{content_id}"
                )
        except Exception as e:
            logger.error(f"Error sending purchased content: {e}")
            await message.answer("Контент сохранён в профиле, но произошла ошибка при отправке.")

@router.message()
async def unknown_message(message: Message):
    """Обработка неизвестных сообщений"""
    if message.from_user.id == ADMIN_ID:
        await message.answer(
            "ℹ️ Доступные команды:\n\n"
            "/start - Запустить бота\n"
            "/delete <id> - Удалить контент\n"
            "/ban @username - Забанить пользователя\n"
            "/approve <id> - Одобрить контент\n\n"
            "Отправь фото/видео для добавления контента"
        )
    else:
        await message.answer(
            "ℹ️ Отправь фото, видео или кружок для предложения контента на модерацию.\n"
            "Или нажми /start для открытия WebApp"
        )