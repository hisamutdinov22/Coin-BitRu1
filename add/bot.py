import asyncio, logging, re
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery
from aiogram.utils.deep_linking import decode_payload
from .config import settings
from .db import init_db, Session, Withdrawal
from .services import *
from .keyboards import *
from sqlalchemy import select, desc

logging.basicConfig(level=logging.INFO)
bot=Bot(settings.bot_token)
dp=Dispatcher()

def money_from_coins(c): return c/settings.coins_per_usd

def home_text(u):
    return (f'🪙 <b>Coin BitRu</b> 🇷🇺\n\nБаланс: <b>{u.coins:,}</b> COIN\n≈ <b>${money_from_coins(u.coins):.2f}</b>\n\n⚡ За тап: <b>+{u.tap_level}</b> COIN\n🔋 Энергия: <b>{u.energy}/{u.max_energy}</b>\n📈 Уровень тапа: <b>{u.tap_level}</b>\n👥 Рефералов: <b>{u.referrals}</b>\n💳 Пополнено: <b>${u.topup_usd:.2f}</b>').replace(',', ' ')

@dp.message(CommandStart())
async def start(m:Message):
    ref=None
    arg=m.text.split(maxsplit=1)[1] if len(m.text.split())>1 else ''
    if arg.startswith('ref_'):
        try: ref=int(arg[4:])
        except: pass
    u=await get_or_create_user(m.from_user,ref)
    await m.answer(home_text(u),parse_mode='HTML',reply_markup=main_kb())

@dp.message(Command('id'))
async def id_cmd(m:Message): await m.answer(f'ID: <code>{m.from_user.id}</code>',parse_mode='HTML')

@dp.callback_query(F.data=='home')
async def home(c:CallbackQuery):
    u=await restore_energy(c.from_user.id); await c.message.edit_text(home_text(u),parse_mode='HTML',reply_markup=main_kb()); await c.answer()

@dp.callback_query(F.data=='tap')
async def tap_cb(c:CallbackQuery):
    gain,u=await tap(c.from_user.id); await c.message.edit_text(home_text(u)+f'\n\n⚡ <b>+{gain}</b> COIN',parse_mode='HTML',reply_markup=main_kb()); await c.answer(f'+{gain} COIN' if gain else 'Нет энергии')

@dp.callback_query(F.data=='upgrade')
async def upgrade(c:CallbackQuery):
    u=await profile(c.from_user.id); cost=int(1000*(1.8**(u.tap_level-1)))
    text=f'⚡ <b>Улучшение тапа</b>\n\nУровень: {u.tap_level}\nЗа тап: {u.tap_level} COIN → {u.tap_level+1} COIN\nЦена: <b>{cost:,} COIN</b>'.replace(',', ' ')
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f'⬆️ Улучшить за {cost:,}',callback_data='upgrade:buy'.replace(':',':'))],[InlineKeyboardButton(text='⬅️ Назад',callback_data='home')]])
    await c.message.edit_text(text,parse_mode='HTML',reply_markup=kb);await c.answer()

@dp.callback_query(F.data=='upgrade:buy')
async def upgrade_buy(c:CallbackQuery):
    ok,u=await upgrade_tap(c.from_user.id);await c.answer('Улучшено!' if ok else 'Недостаточно коинов',show_alert=True);await home(c)

@dp.callback_query(F.data=='daily')
async def daily(c:CallbackQuery):
    ok,u,reward=await daily_claim(c.from_user.id)
    txt=f'🎁 <b>7-дневный вход</b>\n\nСерия: <b>{u.streak}/7</b>\nНаграда сегодня: <b>+{reward:,} COIN</b>'.replace(',', ' ')
    await c.message.edit_text(txt,parse_mode='HTML',reply_markup=back_kb());await c.answer('Награда получена!' if ok else 'Сегодня уже получена',show_alert=not ok)

@dp.callback_query(F.data=='tasks')
async def tasks(c:CallbackQuery):
    from .db import Task
    async with Session() as s:
        ts=list((await s.execute(select(Task).where(Task.active==True).order_by(Task.id))).scalars())
    rows=[]
    for t in ts:
        done=await task_status(c.from_user.id,t.id)
        rows.append([InlineKeyboardButton(text=('✅ ' if done else '🎁 ')+f'{t.title} · {money_from_coins(t.reward_coins):.2f}$',callback_data=f'taskview:{t.id}')])
    rows.append([InlineKeyboardButton(text='⬅️ Назад',callback_data='home')])
    await c.message.edit_text('✅ <b>Задания</b>\n\nВыполняй задания и получай COIN.',parse_mode='HTML',reply_markup=InlineKeyboardMarkup(inline_keyboard=rows));await c.answer()

@dp.callback_query(F.data.startswith('taskview:'))
async def taskview(c:CallbackQuery):
    task_id=int(c.data.split(':')[1]);from .db import Task
    async with Session() as s:t=await s.get(Task,task_id)
    done=await task_status(c.from_user.id,task_id)
    txt=f'✅ <b>{t.title}</b>\n\nНаграда: <b>{t.reward_coins:,} COIN</b> ≈ ${money_from_coins(t.reward_coins):.2f}'.replace(',', ' ')
    if t.kind=='channel': txt+='\n\nПодпишись на канал и нажми «Проверить». Бот должен быть администратором канала для проверки.'
    elif t.kind=='referrals': txt+='\n\nУсловие: пригласить минимум 3 человек.'
    elif t.kind=='taps': txt+='\n\nУсловие: накопить минимум 100 коинов тапами.'
    await c.message.edit_text(txt,parse_mode='HTML',reply_markup=tasks_kb(task_id,done,t.url));await c.answer()

@dp.callback_query(F.data.startswith('task:'))
async def task_check(c:CallbackQuery):
    task_id=int(c.data.split(':')[1]);from .db import Task
    async with Session() as s:t=await s.get(Task,task_id)
    if t.kind=='channel':
        try:
            member=await bot.get_chat_member(settings.channel_username,c.from_user.id)
            if member.status in ('left','kicked'): await c.answer('Сначала подпишись на канал.',show_alert=True);return
            async with Session() as s:
                from .db import TaskCompletion
                if await s.scalar(select(TaskCompletion).where(TaskCompletion.user_id==c.from_user.id,TaskCompletion.task_id==task_id)): await c.answer('Уже выполнено',show_alert=True);return
                from .db import User
                u=await s.get(User,c.from_user.id);u.coins+=t.reward_coins;s.add(TaskCompletion(user_id=c.from_user.id,task_id=task_id));await s.commit()
            await c.answer('Задание выполнено! +50 000 COIN',show_alert=True)
        except Exception as e:
            logging.exception(e);await c.answer('Не удалось проверить подписку. Проверь права бота.',show_alert=True)
    else:
        ok,reward,status=await complete_generic_task(c.from_user.id,task_id)
        await c.answer('Задание выполнено!' if ok else ('Уже выполнено' if status=='done' else 'Условие ещё не выполнено'),show_alert=True)
    await tasks(c)

@dp.callback_query(F.data=='refs')
async def refs(c:CallbackQuery):
    u=await profile(c.from_user.id); me=await bot.get_me(); link=f'https://t.me/{me.username}?start=ref_{u.id}'
    txt=f'👥 <b>Реферальная программа</b>\n\nПриглашено: <b>{u.referrals}</b>\nЗа каждого: <b>{settings.referral_reward_coins:,} COIN</b>\nБонус за 5 приглашённых: <b>${settings.referral_5_bonus_usd}</b>\n\nТвоя ссылка:\n<code>{link}</code>'.replace(',', ' ')
    await c.message.edit_text(txt,parse_mode='HTML',reply_markup=back_kb());await c.answer()

@dp.callback_query(F.data=='leaders')
async def leaders(c:CallbackQuery):
    users=await leaderboard(10); lines=['👑 <b>Лидеры</b>\n']
    for i,u in enumerate(users,1): lines.append(f'{i}. @{u.username or u.first_name or u.id} — <b>{u.coins:,}</b> COIN'.replace(',', ' '))
    await c.message.edit_text('\n'.join(lines),parse_mode='HTML',reply_markup=back_kb());await c.answer()

@dp.callback_query(F.data=='tournament')
async def tournament_cb(c:CallbackQuery):
    users=await tournament(10);lines=[f'🏆 <b>Турнир Coin BitRu</b>\n\nПризовой фонд: <b>${settings.tournament_prize_usd}</b>\nТекущий топ:\n']
    for i,u in enumerate(users,1): lines.append(f'{i}. {u.first_name or "Player"} — {u.coins:,} COIN'.replace(',', ' '))
    lines.append('\nПобедитель определяется по таблице лидеров в момент завершения раунда; выплаты выполняются только после ручной проверки.')
    await c.message.edit_text('\n'.join(lines),parse_mode='HTML',reply_markup=back_kb());await c.answer()

@dp.callback_query(F.data=='topup')
async def topup(c:CallbackQuery):
    await c.message.edit_text('💳 <b>Пополнение</b>\n\nВыбери сумму. После успешной оплаты баланс пополнится автоматически.\n\nДоступные суммы: $1, $2, $5, $10.',parse_mode='HTML',reply_markup=topup_kb());await c.answer()

@dp.callback_query(F.data.startswith('pay:'))
async def pay(c:CallbackQuery):
    usd=int(c.data.split(':')[1])
    if not settings.payment_provider_token: await c.answer('PAYMENT_PROVIDER_TOKEN не настроен на сервере.',show_alert=True);return
    prices=[LabeledPrice(label=f'Coin BitRu ${usd}',amount=usd*100)]
    await bot.send_invoice(chat_id=c.from_user.id,title=f'Coin BitRu — пополнение ${usd}',description=f'Зачисление {usd*settings.coins_per_usd:,} COIN после подтверждения платежа.',payload=f'topup:{usd}',provider_token=settings.payment_provider_token,currency='USD',prices=prices)
    await c.answer()

@dp.pre_checkout_query()
async def pre_checkout(q:PreCheckoutQuery): await q.answer(ok=True)

@dp.message(F.successful_payment)
async def successful_payment(m:Message):
    p=m.successful_payment; usd=p.total_amount/100
    added=await add_payment(m.from_user.id,usd,p.currency,p.telegram_payment_charge_id,p.provider_payment_charge_id,p.invoice_payload)
    if added:
        u=await profile(m.from_user.id);await m.answer(f'✅ Оплата подтверждена. Зачислено <b>{int(usd*settings.coins_per_usd):,} COIN</b>.\nБаланс: {u.coins:,} COIN'.replace(',', ' '),parse_mode='HTML',reply_markup=main_kb())
    else: await m.answer('Платёж уже был обработан.')

@dp.callback_query(F.data=='withdraw')
async def withdraw(c:CallbackQuery):
    u=await profile(c.from_user.id)
    if u.topup_usd<settings.withdraw_topup_min_usd:
        await c.answer(f'Вывод доступен после пополнения на ${settings.withdraw_topup_min_usd}.',show_alert=True);return
    await c.message.edit_text(f'💸 <b>Вывод</b>\n\nКурс: {settings.coins_per_usd:,} COIN = $1\nТвой баланс: {u.coins:,} COIN\nПополнено: ${u.topup_usd:.2f}\n\nНапиши сообщение в формате:\n<code>withdraw 1 TON_АДРЕС</code>\n\nЗаявка будет отправлена администратору на ручную проверку.',parse_mode='HTML',reply_markup=back_kb());await c.answer()

@dp.message(Command('withdraw'))
async def withdraw_cmd(m:Message):
    parts=m.text.split(maxsplit=2)
    if len(parts)<3: await m.answer('Формат: /withdraw 1 TON_АДРЕС');return
    try:usd=float(parts[1])
    except:await m.answer('Сумма указана неверно.');return
    ok,msg=await create_withdrawal(m.from_user.id,usd,parts[2])
    await m.answer(('✅ '+msg) if ok else ('❌ '+msg))
    if ok:
        async with Session() as s:
            w=await s.scalar(select(Withdrawal).where(Withdrawal.user_id==m.from_user.id).order_by(desc(Withdrawal.id)))
        for admin in settings.admin_set:
            try: await bot.send_message(admin,f'💸 Новая заявка на вывод #{w.id}\nUser: {m.from_user.id}\nСумма: ${w.usd:.2f}\nCOIN: {w.coins:,}\nDestination: <code>{w.destination}</code>',parse_mode='HTML')
            except: pass

@dp.message(Command('admin'))
async def admin(m:Message):
    if m.from_user.id not in settings.admin_set:return
    async with Session() as s:
        pending=list((await s.execute(select(Withdrawal).where(Withdrawal.status=='pending').order_by(Withdrawal.id))).scalars())
    txt='🛠 <b>Админка</b>\n\nОжидающих выводов: '+str(len(pending))+'\n\n'
    for w in pending:txt+=f'#{w.id} — ${w.usd:.2f} — /approve_{w.id} или /reject_{w.id}\n'
    await m.answer(txt,parse_mode='HTML')

@dp.message(F.text.regexp(r'^/approve_\d+$'))
async def approve(m:Message):
    if m.from_user.id not in settings.admin_set:return
    wid=int(m.text.split('_')[1])
    async with Session() as s:w=await s.get(Withdrawal,wid);w.status='approved';await s.commit()
    await m.answer(f'✅ Вывод #{wid} отмечен как approved. Перевод выполните через ваш платёжный процессор/кошелёк.')

@dp.message(F.text.regexp(r'^/reject_\d+$'))
async def reject(m:Message):
    if m.from_user.id not in settings.admin_set:return
    wid=int(m.text.split('_')[1])
    async with Session() as s:w=await s.get(Withdrawal,wid);w.status='rejected';await s.commit()
    await m.answer(f'⛔ Вывод #{wid} отклонён.')

@dp.callback_query(F.data=='noop')
async def noop(c:CallbackQuery):await c.answer('Уже выполнено')

async def main():
    await init_db(); await dp.start_polling(bot)
if __name__=='__main__': asyncio.run(main())
