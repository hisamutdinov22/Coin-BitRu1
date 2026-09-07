import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy import desc, select

from .config import settings
from .db import Session, Task, TaskCompletion, User, Withdrawal, init_db
from .keyboards import main_kb, back_kb, tasks_kb, topup_kb
from .services import (
    add_payment,
    complete_generic_task,
    create_withdrawal,
    daily_claim,
    get_or_create_user,
    leaderboard,
    profile,
    restore_energy,
    task_status,
    tap,
    tournament,
    upgrade_tap,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('coin_bitru')

bot = Bot(settings.bot_token)
dp = Dispatcher()


def money_from_coins(coins: int) -> float:
    return coins / settings.coins_per_usd


def home_text(user: User) -> str:
    return (
        '🪙 <b>Coin BitRu</b> 🇷🇺\n\n'
        f'Баланс: <b>{user.coins:,}</b> COIN\n'
        f'≈ <b>${money_from_coins(user.coins):.2f}</b>\n\n'
        f'⚡ За тап: <b>+{user.tap_level}</b> COIN\n'
        f'🔋 Энергия: <b>{user.energy}/{user.max_energy}</b>\n'
        f'📈 Уровень тапа: <b>{user.tap_level}</b>\n'
        f'👥 Рефералов: <b>{user.referrals}</b>\n'
        f'💳 Пополнено: <b>${user.topup_usd:.2f}</b>'
    ).replace(',', ' ')


def extract_ref(text: str | None):
    if not text:
        return None
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    payload = parts[1]
    if not payload.startswith('ref_'):
        return None
    try:
        return int(payload[4:])
    except ValueError:
        return None


async def ensure_user(tg_user, referrer_id=None):
    user = await get_or_create_user(tg_user, referrer_id)
    if user is None:
        raise RuntimeError('Не удалось создать пользователя.')
    return user


@dp.message(CommandStart())
async def start(message: Message):
    user = await ensure_user(message.from_user, extract_ref(message.text))
    user = await restore_energy(user.id) or user
    await message.answer(home_text(user), parse_mode='HTML', reply_markup=main_kb())


@dp.message(Command('id'))
async def id_cmd(message: Message):
    await message.answer(f'ID: <code>{message.from_user.id}</code>', parse_mode='HTML')


@dp.callback_query(F.data == 'home')
async def home(callback: CallbackQuery):
    user = await ensure_user(callback.from_user)
    user = await restore_energy(user.id) or user
    await callback.message.edit_text(home_text(user), parse_mode='HTML', reply_markup=main_kb())
    await callback.answer()


@dp.callback_query(F.data == 'tap')
async def tap_cb(callback: CallbackQuery):
    await ensure_user(callback.from_user)
    user = await restore_energy(callback.from_user.id)
    gain, updated = await tap(callback.from_user.id)
    if not updated:
        await callback.answer('Пользователь не найден.', show_alert=True)
        return
    await callback.message.edit_text(
        home_text(updated) + f'\n\n⚡ <b>+{gain}</b> COIN',
        parse_mode='HTML',
        reply_markup=main_kb(),
    )
    await callback.answer(f'+{gain} COIN' if gain else 'Нет энергии')


@dp.callback_query(F.data == 'upgrade')
async def upgrade(callback: CallbackQuery):
    user = await ensure_user(callback.from_user)
    user = await restore_energy(user.id) or user
    cost = int(1000 * (1.8 ** (user.tap_level - 1)))
    text = (
        f'⚡ <b>Улучшение тапа</b>\n\n'
        f'Уровень: {user.tap_level}\n'
        f'За тап: {user.tap_level} COIN → {user.tap_level + 1} COIN\n'
        f'Цена: <b>{cost:,} COIN</b>'
    ).replace(',', ' ')
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f'⬆️ Улучшить за {cost:,}', callback_data='upgrade:buy')],
        [InlineKeyboardButton(text='⬅️ Назад', callback_data='home')],
    ])
    await callback.message.edit_text(text, parse_mode='HTML', reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data == 'upgrade:buy')
async def upgrade_buy(callback: CallbackQuery):
    await ensure_user(callback.from_user)
    ok, _ = await upgrade_tap(callback.from_user.id)
    await callback.answer('Улучшено!' if ok else 'Недостаточно коинов', show_alert=True)
    await home(callback)


@dp.callback_query(F.data == 'daily')
async def daily(callback: CallbackQuery):
    await ensure_user(callback.from_user)
    ok, user, reward = await daily_claim(callback.from_user.id)
    user = user or await profile(callback.from_user.id)
    txt = f'🎁 <b>7-дневный вход</b>\n\nСерия: <b>{user.streak}/7</b>\nНаграда: <b>+{reward:,} COIN</b>'.replace(',', ' ')
    await callback.message.edit_text(txt, parse_mode='HTML', reply_markup=back_kb())
    await callback.answer('Награда получена!' if ok else 'Сегодня уже получено', show_alert=not ok)


@dp.callback_query(F.data == 'tasks')
async def tasks(callback: CallbackQuery):
    user = await ensure_user(callback.from_user)
    async with Session() as s:
        task_list = list((await s.execute(select(Task).where(Task.active.is_(True)).order_by(Task.id))).scalars())
    rows = []
    for task in task_list:
        done = await task_status(user.id, task.id)
        rows.append([InlineKeyboardButton(text=('✅ ' if done else '🎁 ') + f'{task.title} · {money_from_coins(task.reward_coins):.2f}$', callback_data=f'taskview:{task.id}')])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='home')])
    await callback.message.edit_text('✅ <b>Задания</b>\n\nВыполняй задания и получай COIN.', parse_mode='HTML', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@dp.callback_query(F.data.startswith('taskview:'))
async def taskview(callback: CallbackQuery):
    task_id = int(callback.data.split(':')[1])
    async with Session() as s:
        task = await s.get(Task, task_id)
    if not task:
        await callback.answer('Задание не найдено.', show_alert=True)
        return
    done = await task_status(callback.from_user.id, task_id)
    txt = f'✅ <b>{task.title}</b>\n\nНаграда: <b>{task.reward_coins:,} COIN</b> ≈ ${money_from_coins(task.reward_coins):.2f}'.replace(',', ' ')
    if task.kind == 'channel':
        txt += '\n\nПодпишись на канал и нажми «Проверить».'
    elif task.kind == 'referrals':
        txt += '\n\nУсловие: пригласить минимум 3 человек.'
    elif task.kind == 'taps':
        txt += '\n\nУсловие: накопить минимум 100 COIN.'
    await callback.message.edit_text(txt, parse_mode='HTML', reply_markup=tasks_kb(task_id, done, task.url))
    await callback.answer()


@dp.callback_query(F.data.startswith('task:'))
async def task_check(callback: CallbackQuery):
    task_id = int(callback.data.split(':')[1])
    async with Session() as s:
        task = await s.get(Task, task_id)
    if not task:
        await callback.answer('Задание не найдено.', show_alert=True)
        return
    await ensure_user(callback.from_user)

    if task.kind == 'channel':
        try:
            member = await bot.get_chat_member(settings.channel_username, callback.from_user.id)
            if member.status in ('left', 'kicked'):
                await callback.answer('Сначала подпишись на канал.', show_alert=True)
                return
            async with Session() as s:
                completion = await s.scalar(select(TaskCompletion).where(TaskCompletion.user_id == callback.from_user.id, TaskCompletion.task_id == task_id))
                user = await s.get(User, callback.from_user.id)
                if completion:
                    await callback.answer('Уже выполнено.', show_alert=True)
                    return
                user.coins += task.reward_coins
                s.add(TaskCompletion(user_id=user.id, task_id=task_id))
                await s.commit()
            await callback.answer(f'Задание выполнено! +{task.reward_coins:,} COIN'.replace(',', ' '), show_alert=True)
        except Exception:
            logger.exception('Ошибка проверки подписки')
            await callback.answer('Не удалось проверить подписку. Проверь права бота.', show_alert=True)
    else:
        ok, reward, status = await complete_generic_task(callback.from_user.id, task_id)
        if ok:
            await callback.answer(f'Задание выполнено! +{reward:,} COIN'.replace(',', ' '), show_alert=True)
        else:
            msg = 'Уже выполнено.' if status == 'done' else 'Условие ещё не выполнено.'
            await callback.answer(msg, show_alert=True)
    await tasks(callback)


@dp.callback_query(F.data == 'refs')
async def refs(callback: CallbackQuery):
    user = await ensure_user(callback.from_user)
    me = await bot.get_me()
    link = f'https://t.me/{me.username}?start=ref_{user.id}'
    txt = (
        f'👥 <b>Реферальная программа</b>\n\n'
        f'Приглашено: <b>{user.referrals}</b>\n'
        f'За каждого: <b>{settings.referral_reward_coins:,} COIN</b>\n'
        f'Бонус за 5 приглашённых: <b>${settings.referral_5_bonus_usd}</b>\n\n'
        f'Твоя ссылка:\n<code>{link}</code>'
    ).replace(',', ' ')
    await callback.message.edit_text(txt, parse_mode='HTML', reply_markup=back_kb())
    await callback.answer()


@dp.callback_query(F.data == 'leaders')
async def leaders(callback: CallbackQuery):
    users = await leaderboard(10)
    lines = ['👑 <b>Лидеры</b>\n']
    for index, user in enumerate(users, 1):
        name = f'@{user.username}' if user.username else (user.first_name or str(user.id))
        lines.append(f'{index}. {name} — <b>{user.coins:,}</b> COIN'.replace(',', ' '))
    await callback.message.edit_text('\n'.join(lines), parse_mode='HTML', reply_markup=back_kb())
    await callback.answer()


@dp.callback_query(F.data == 'tournament')
async def tournament_cb(callback: CallbackQuery):
    users = await tournament(10)
    lines = [f'🏆 <b>Турнир Coin BitRu</b>\n\nПризовой фонд: <b>${settings.tournament_prize_usd}</b>\n']
    for index, user in enumerate(users, 1):
        lines.append(f'{index}. {user.first_name or "Player"} — {user.coins:,} COIN'.replace(',', ' '))
    lines.append('\nПобедитель определяется по таблице лидеров в конце раунда; выплаты выполняются после ручной проверки.')
    await callback.message.edit_text('\n'.join(lines), parse_mode='HTML', reply_markup=back_kb())
    await callback.answer()


@dp.callback_query(F.data == 'topup')
async def topup(callback: CallbackQuery):
    await callback.message.edit_text('💳 <b>Пополнение</b>\n\nВыбери сумму. После успешной оплаты баланс пополнится автоматически.\n\nДоступно: $1, $2, $5, $10.', parse_mode='HTML', reply_markup=topup_kb())
    await callback.answer()


@dp.callback_query(F.data.startswith('pay:'))
async def pay(callback: CallbackQuery):
    usd = int(callback.data.split(':')[1])
    if not settings.payment_provider_token:
        await callback.answer('PAYMENT_PROVIDER_TOKEN не настроен.', show_alert=True)
        return
    prices = [LabeledPrice(label=f'Coin BitRu ${usd}', amount=usd * 100)]
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f'Coin BitRu — пополнение ${usd}',
        description=f'Зачисление {usd * settings.coins_per_usd:,} COIN после подтверждения платежа.',
        payload=f'topup:{usd}',
        provider_token=settings.payment_provider_token,
        currency='USD',
        prices=prices,
    )
    await callback.answer()


@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    payment = message.successful_payment
    usd = payment.total_amount / 100
    await ensure_user(message.from_user)
    added = await add_payment(
        message.from_user.id,
        usd,
        payment.currency,
        payment.telegram_payment_charge_id,
        payment.provider_payment_charge_id,
        payment.invoice_payload,
    )
    if not added:
        await message.answer('Платёж уже был обработан или пользователь не найден.')
        return
    user = await profile(message.from_user.id)
    await message.answer(
        f'✅ Оплата подтверждена. Зачислено <b>{int(usd * settings.coins_per_usd):,} COIN</b>.\nБаланс: {user.coins:,} COIN'.replace(',', ' '),
        parse_mode='HTML',
        reply_markup=main_kb(),
    )


@dp.callback_query(F.data == 'withdraw')
async def withdraw(callback: CallbackQuery):
    user = await ensure_user(callback.from_user)
    user = await restore_energy(user.id) or user
    if user.topup_usd < settings.withdraw_topup_min_usd:
        await callback.answer(f'Вывод доступен после пополнения на ${settings.withdraw_topup_min_usd}.', show_alert=True)
        return
    await callback.message.edit_text(
        f'💸 <b>Вывод</b>\n\nКурс: {settings.coins_per_usd:,} COIN = $1\nТвой баланс: {user.coins:,} COIN\nПополнено: ${user.topup_usd:.2f}\n\nНапиши в формате:\n<code>/withdraw 1 TON_АДРЕС</code>\n\nЗаявка отправится администратору на ручную проверку.'.replace(',', ' '),
        parse_mode='HTML',
        reply_markup=back_kb(),
    )
    await callback.answer()


@dp.message(Command('withdraw'))
async def withdraw_cmd(message: Message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer('Формат: /withdraw 1 TON_АДРЕС')
        return
    try:
        usd = float(parts[1])
    except ValueError:
        await message.answer('Сумма указана неверно.')
        return
    await ensure_user(message.from_user)
    ok, msg = await create_withdrawal(message.from_user.id, usd, parts[2])
    await message.answer(('✅ ' if ok else '❌ ') + msg)
    if ok:
        async with Session() as s:
            withdrawal = await s.scalar(select(Withdrawal).where(Withdrawal.user_id == message.from_user.id).order_by(desc(Withdrawal.id)))
        for admin_id in settings.admin_set:
            try:
                await bot.send_message(
                    admin_id,
                    f'💸 Новая заявка #{withdrawal.id}\nUser: {message.from_user.id}\nСумма: ${withdrawal.usd:.2f}\nCOIN: {withdrawal.coins:,}\nDestination: <code>{withdrawal.destination}</code>',
                    parse_mode='HTML',
                )
            except Exception:
                logger.exception('Не удалось уведомить администратора %s', admin_id)


@dp.message(Command('admin'))
async def admin(message: Message):
    if message.from_user.id not in settings.admin_set:
        return
    async with Session() as s:
        pending = list((await s.execute(select(Withdrawal).where(Withdrawal.status == 'pending').order_by(Withdrawal.id))).scalars())
    text = f'🛠 <b>Админка</b>\n\nОжидающих выводов: {len(pending)}\n\n'
    for withdrawal in pending:
        text += f'#{withdrawal.id} — ${withdrawal.usd:.2f} — /approve_{withdrawal.id} или /reject_{withdrawal.id}\n'
    await message.answer(text, parse_mode='HTML')


@dp.message(F.text.regexp(r'^/approve_\d+$'))
async def approve(message: Message):
    if message.from_user.id not in settings.admin_set:
        return
    wid = int(message.text.split('_')[1])
    async with Session() as s:
        withdrawal = await s.get(Withdrawal, wid)
        if not withdrawal:
            await message.answer('Заявка не найдена.')
            return
        withdrawal.status = 'approved'
        await s.commit()
    await message.answer(f'✅ Вывод #{wid} отмечен как approved.')


@dp.message(F.text.regexp(r'^/reject_\d+$'))
async def reject(message: Message):
    if message.from_user.id not in settings.admin_set:
        return
    wid = int(message.text.split('_')[1])
    async with Session() as s:
        withdrawal = await s.get(Withdrawal, wid)
        if not withdrawal:
            await message.answer('Заявка не найдена.')
            return
        withdrawal.status = 'rejected'
        await s.commit()
    await message.answer(f'⛔ Вывод #{wid} отклонён.')


@dp.callback_query(F.data == 'noop')
async def noop(callback: CallbackQuery):
    await callback.answer('Уже выполнено')


async def main():
    # Database is initialized exactly once before polling to avoid SQLite race conditions.
    await init_db()
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
