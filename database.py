import sqlite3
from datetime import datetime
from typing import Optional, List, Dict
from config import DATABASE_PATH

def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    
    # Таблица пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        banned INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Таблица контента
    c.execute('''CREATE TABLE IF NOT EXISTS content (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        file_id TEXT NOT NULL,
        price INTEGER DEFAULT 0,
        author_id INTEGER,
        approved INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (author_id) REFERENCES users(id)
    )''')
    
    # Таблица покупок
    c.execute('''CREATE TABLE IF NOT EXISTS purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        content_id INTEGER NOT NULL,
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (content_id) REFERENCES content(id)
    )''')
    
    conn.commit()
    conn.close()

def add_user(user_id: int, username: str = None, first_name: str = None):
    """Добавить или обновить пользователя"""
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO users (id, username, first_name) 
                 VALUES (?, ?, ?)''', (user_id, username, first_name))
    conn.commit()
    conn.close()

def is_user_banned(user_id: int) -> bool:
    """Проверить, забанен ли пользователь"""
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('SELECT banned FROM users WHERE id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    return result and result[0] == 1

def ban_user(username: str) -> bool:
    """Забанить пользователя по username"""
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET banned = 1 WHERE username = ?', (username,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def add_content(content_type: str, file_id: str, price: int, author_id: int, approved: bool = False) -> int:
    """Добавить контент в базу"""
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO content (type, file_id, price, author_id, approved) 
                 VALUES (?, ?, ?, ?, ?)''', 
              (content_type, file_id, price, author_id, 1 if approved else 0))
    content_id = c.lastrowid
    conn.commit()
    conn.close()
    return content_id

def approve_content(content_id: int) -> bool:
    """Одобрить контент"""
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('UPDATE content SET approved = 1 WHERE id = ?', (content_id,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def delete_content(content_id: int) -> bool:
    """Удалить контент"""
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM content WHERE id = ?', (content_id,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def get_approved_content(content_type: Optional[str] = None) -> List[Dict]:
    """Получить одобренный контент"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if content_type:
        c.execute('SELECT * FROM content WHERE approved = 1 AND type = ? ORDER BY id DESC', (content_type,))
    else:
        c.execute('SELECT * FROM content WHERE approved = 1 ORDER BY id DESC')
    
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_content_by_id(content_id: int) -> Optional[Dict]:
    """Получить контент по ID"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM content WHERE id = ?', (content_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def add_purchase(user_id: int, content_id: int):
    """Добавить покупку"""
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO purchases (user_id, content_id) VALUES (?, ?)', (user_id, content_id))
    conn.commit()
    conn.close()

def is_purchased(user_id: int, content_id: int) -> bool:
    """Проверить, куплен ли контент пользователем"""
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('SELECT 1 FROM purchases WHERE user_id = ? AND content_id = ?', (user_id, content_id))
    result = c.fetchone()
    conn.close()
    return result is not None

def get_user_purchases(user_id: int) -> List[Dict]:
    """Получить все покупки пользователя"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('''SELECT c.* FROM content c 
                 JOIN purchases p ON c.id = p.content_id 
                 WHERE p.user_id = ? ORDER BY p.timestamp DESC''', (user_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]