import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, Update
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiohttp import web
import os

import database as db
from handlers import router
from config import BOT_TOKEN, PAYMENT_PROVIDER_TOKEN, USE_REAL_PAYMENTS

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Регистрация роутера
dp.include_router(router)

# Webhook configuration
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
# Получаем URL из переменной окружения или используем заглушку
BASE_URL = os.getenv('RENDER_EXTERNAL_URL', 'https://your-app.onrender.com')
WEBHOOK_URL = BASE_URL + WEBHOOK_PATH

# Health check endpoint
async def health_check(request):
    """Health check для Render"""
    return web.json_response({
        'status': 'ok', 
        'bot': 'running',
        'webhook': WEBHOOK_URL,
        'bot_id': (await bot.get_me()).id
    })

# WebApp API эндпоинты
async def get_content(request):
    """API для получения контента в WebApp"""
    try:
        content_type = request.query.get('type')
        user_id = request.query.get('user_id')
        
        content_list = db.get_approved_content(content_type)
        
        if user_id:
            try:
                uid = int(user_id)
                for item in content_list:
                    item['purchased'] = db.is_purchased(uid, item['id'])
            except ValueError:
                pass
        
        return web.json_response(content_list)
    except Exception as e:
        logger.error(f"Error in get_content: {e}")
        return web.json_response({'error': str(e)}, status=500)

async def get_purchases(request):
    """API для получения покупок пользователя"""
    try:
        user_id = request.query.get('user_id')
        
        if not user_id:
            return web.json_response({'error': 'user_id required'}, status=400)
        
        try:
            uid = int(user_id)
            purchases = db.get_user_purchases(uid)
            return web.json_response(purchases)
        except ValueError:
            return web.json_response({'error': 'invalid user_id'}, status=400)
    except Exception as e:
        logger.error(f"Error in get_purchases: {e}")
        return web.json_response({'error': str(e)}, status=500)

async def create_invoice(request):
    """API для создания инвойса на оплату"""
    try:
        data = await request.json()
        user_id = int(data['user_id'])
        content_id = int(data['content_id'])
        
        content = db.get_content_by_id(content_id)
        if not content:
            return web.json_response({'error': 'Content not found'}, status=404)
        
        if db.is_purchased(user_id, content_id):
            return web.json_response({'error': 'Already purchased'}, status=400)
        
        if content['price'] == 0:
            db.add_purchase(user_id, content_id)
            return web.json_response({'success': True, 'free': True})
        
        if not USE_REAL_PAYMENTS:
            logger.info(f"TEST MODE: Auto-purchasing content {content_id} for user {user_id}")
            db.add_purchase(user_id, content_id)
            return web.json_response({'success': True, 'test_mode': True})
        
        from aiogram.types import LabeledPrice
        
        prices = [LabeledPrice(label=f"Контент #{content_id}", amount=content['price'])]
        
        invoice_link = await bot.create_invoice_link(
            title=f"Покупка контента #{content_id}",
            description=f"Оплата {content['type']}",
            payload=str(content_id),
            provider_token=PAYMENT_PROVIDER_TOKEN,
            currency='XTR',
            prices=prices
        )
        
        return web.json_response({'invoice_link': invoice_link})
        
    except Exception as e:
        logger.error(f"Error creating invoice: {e}")
        return web.json_response({'error': str(e)}, status=500)

# CORS middleware
@web.middleware
async def cors_middleware(request, handler):
    """Middleware для CORS"""
    if request.method == "OPTIONS":
        response = web.Response()
    else:
        try:
            response = await handler(request)
        except Exception as e:
            logger.error(f"Handler error: {e}")
            response = web.json_response({'error': str(e)}, status=500)
    
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

async def set_bot_commands():
    """Установка команд бота"""
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="delete", description="[Админ] Удалить контент"),
        BotCommand(command="ban", description="[Админ] Забанить пользователя"),
        BotCommand(command="approve", description="[Админ] Одобрить контент"),
    ]
    await bot.set_my_commands(commands)
    logger.info("✅ Bot commands set")

async def on_startup(app):
    """Действия при запуске"""
    # Инициализация базы данных
    db.init_db()
    logger.info("✅ Database initialized")
    
    # Установка команд
    await set_bot_commands()
    
    # Получаем информацию о боте
    bot_info = await bot.get_me()
    logger.info(f"🤖 Bot: @{bot_info.username} (ID: {bot_info.id})")
    
    # Удаляем старый webhook
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🗑️ Old webhook deleted")
    
    # Устанавливаем новый webhook
    webhook_info = await bot.get_webhook_info()
    if webhook_info.url != WEBHOOK_URL:
        await bot.set_webhook(
            url=WEBHOOK_URL,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=True
        )
        logger.info(f"✅ Webhook set to: {WEBHOOK_URL}")
    else:
        logger.info(f"ℹ️ Webhook already set to: {WEBHOOK_URL}")
    
    # Показываем режим работы
    if USE_REAL_PAYMENTS:
        logger.info("💳 Payment mode: REAL PAYMENTS (Telegram Stars)")
    else:
        logger.info("🧪 Payment mode: TEST MODE (auto-purchase, no real payments)")
    
    logger.info("🚀 Bot started successfully with WEBHOOK!")
    logger.info("=" * 50)

async def on_shutdown(app):
    """Действия при остановке"""
    logger.info("⏹️ Shutting down bot...")
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.session.close()

def main():
    """Главная функция"""
    # Создаём приложение
    app = web.Application(middlewares=[cors_middleware])
    
    # API роуты (важен порядок - сначала конкретные, потом общие)
    app.router.add_get('/api/content', get_content)
    app.router.add_get('/api/purchases', get_purchases)
    app.router.add_post('/api/create_invoice', create_invoice)
    app.router.add_get('/', health_check)
    
    # Настройка webhook handler
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    
    # Startup/shutdown handlers
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    
    # Логируем информацию
    logger.info("🚀 Starting web server on 0.0.0.0:8080")
    logger.info(f"📡 Webhook path: {WEBHOOK_PATH}")
    logger.info(f"📡 Full webhook URL: {WEBHOOK_URL}")
    logger.info("📡 API Endpoints:")
    logger.info("   GET  /")
    logger.info("   GET  /api/content")
    logger.info("   GET  /api/purchases")
    logger.info("   POST /api/create_invoice")
    
    # Запуск сервера
    web.run_app(app, host='0.0.0.0', port=8080)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
