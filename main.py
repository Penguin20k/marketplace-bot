import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from aiohttp import web
import json

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

# ✅ ДОБАВЛЕН ОБРАБОТЧИК КОРНЕВОГО ПУТИ
async def health_check(request):
    """Health check endpoint"""
    return web.json_response({'status': 'ok', 'bot': 'running'})

# WebApp API эндпоинты
async def get_content(request):
    """API для получения контента в WebApp"""
    try:
        content_type = request.query.get('type')
        user_id = request.query.get('user_id')
        
        content_list = db.get_approved_content(content_type)
        
        # Добавляем информацию о покупках если передан user_id
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
        
        # Проверяем, не куплен ли уже контент
        if db.is_purchased(user_id, content_id):
            return web.json_response({'error': 'Already purchased'}, status=400)
        
        if content['price'] == 0:
            # Бесплатный контент - сразу добавляем в покупки
            db.add_purchase(user_id, content_id)
            return web.json_response({'success': True, 'free': True})
        
        # ТЕСТОВЫЙ РЕЖИМ - автоматически добавляем покупку без оплаты
        if not USE_REAL_PAYMENTS:
            logger.info(f"TEST MODE: Auto-purchasing content {content_id} for user {user_id}")
            db.add_purchase(user_id, content_id)
            return web.json_response({'success': True, 'test_mode': True})
        
        # Создаём инвойс для платной покупки (только если включены реальные платежи)
        from aiogram.types import LabeledPrice
        
        prices = [LabeledPrice(label=f"Контент #{content_id}", amount=content['price'])]
        
        invoice_link = await bot.create_invoice_link(
            title=f"Покупка контента #{content_id}",
            description=f"Оплата {content['type']}",
            payload=str(content_id),
            provider_token=PAYMENT_PROVIDER_TOKEN,
            currency='XTR',  # Telegram Stars
            prices=prices
        )
        
        return web.json_response({'invoice_link': invoice_link})
        
    except Exception as e:
        logger.error(f"Error creating invoice: {e}")
        return web.json_response({'error': str(e)}, status=500)

# CORS middleware для работы с GitHub Pages
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

async def start_webhook_server():
    """Запуск веб-сервера для API"""
    app = web.Application(middlewares=[cors_middleware])
    
    # Роуты
    app.router.add_get('/', health_check)  # ✅ ДОБАВЛЕН
    app.router.add_head('/', health_check)  # ✅ ДОБАВЛЕН для health checks
    app.router.add_get('/api/content', get_content)
    app.router.add_get('/api/purchases', get_purchases)
    app.router.add_post('/api/create_invoice', create_invoice)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    logger.info("✅ API server started on http://0.0.0.0:8080")
    logger.info("📡 Endpoints:")
    logger.info("   GET  /")
    logger.info("   GET  /api/content")
    logger.info("   GET  /api/purchases")
    logger.info("   POST /api/create_invoice")

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

async def on_startup():
    """Действия при запуске"""
    # Инициализация базы данных
    db.init_db()
    logger.info("✅ Database initialized")
    
    # Установка команд
    await set_bot_commands()
    
    # Запуск API сервера
    asyncio.create_task(start_webhook_server())
    
    # Показываем режим работы
    if USE_REAL_PAYMENTS:
        logger.info("💳 Payment mode: REAL PAYMENTS (Telegram Stars)")
    else:
        logger.info("🧪 Payment mode: TEST MODE (auto-purchase, no real payments)")
    
    logger.info("🤖 Bot started successfully!")
    logger.info("=" * 50)

async def on_shutdown():
    """Действия при остановке"""
    logger.info("⏹️ Shutting down bot...")
    await bot.session.close()

async def main():
    """Главная функция"""
    try:
        await on_startup()
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logger.error(f"Critical error: {e}")
    finally:
        await on_shutdown()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
