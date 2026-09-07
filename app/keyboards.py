from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from .config import settings

def main_kb():
    rows=[]
    if getattr(settings, 'miniapp_url', ''):
        rows.append([InlineKeyboardButton(text='🚀 Открыть Coin BitRu', web_app=WebAppInfo(url=settings.miniapp_url))])
    rows += [
        [InlineKeyboardButton(text='⚡ Заработать', callback_data='tap')],
        [InlineKeyboardButton(text='🎁 7-дневный вход', callback_data='daily'), InlineKeyboardButton(text='⚡ Улучшение тапа', callback_data='upgrade')],
        [InlineKeyboardButton(text='✅ Задания', callback_data='tasks'), InlineKeyboardButton(text='👥 Рефералы', callback_data='refs')],
        [InlineKeyboardButton(text='🏆 Лидеры', callback_data='leaders'), InlineKeyboardButton(text='🏆 Турнир $100', callback_data='tournament')],
        [InlineKeyboardButton(text='💳 Пополнение', callback_data='topup'), InlineKeyboardButton(text='💸 Вывод', callback_data='withdraw')],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def back_kb(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='⬅️ Главное меню', callback_data='home')]])

def tasks_kb(task_id: int, completed: bool, url: str):
    rows=[]
    if not completed:
        if url: rows.append([InlineKeyboardButton(text='🔗 Открыть', url=url)])
        rows.append([InlineKeyboardButton(text='✅ Проверить', callback_data=f'task:{task_id}')])
    else: rows.append([InlineKeyboardButton(text='✅ Выполнено', callback_data='noop')])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='home')])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def topup_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='$1', callback_data='pay:1'), InlineKeyboardButton(text='$2', callback_data='pay:2'), InlineKeyboardButton(text='$5', callback_data='pay:5')],
        [InlineKeyboardButton(text='$10', callback_data='pay:10')],
        [InlineKeyboardButton(text='⬅️ Назад', callback_data='home')],
    ])
