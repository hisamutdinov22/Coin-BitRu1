const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); tg.setHeaderColor('#07111d'); tg.setBackgroundColor('#07111d'); }
const state = { user:null };
const $ = id => document.getElementById(id);
const toast = msg => { const el=$('toast'); el.textContent=msg; el.classList.add('show'); setTimeout(()=>el.classList.remove('show'),1800); };
function initData(){ return tg?.initData || ''; }
async function api(path, opts={}){
  const headers={'Content-Type':'application/json','X-Telegram-Init-Data':initData(),...(opts.headers||{})};
  const r=await fetch(path,{...opts,headers});
  if(!r.ok){let m='Ошибка';try{const x=await r.json();m=x.detail||m}catch{};throw new Error(m)}
  return r.json();
}
function fmt(n){return new Intl.NumberFormat('ru-RU').format(n||0)}
function render(){
  const u=state.user;if(!u)return;
  $('username').textContent=u.username ? '@'+u.username : (u.first_name||'User');
  $('userId').textContent='ID: '+u.id;$('avatarLetter').textContent=(u.first_name||u.username||'C')[0].toUpperCase();
  $('balance').textContent=fmt(u.coins);$('balanceUsd').textContent='≈ $'+Number(u.usd).toFixed(2);
  $('perTap').textContent='+'+u.tap_level;$('energy').textContent=`${u.energy}/${u.max_energy}`;$('tapLevel').textContent=u.tap_level;
  $('bonusCount').textContent=`Доступно: ${u.daily_available ? 1 : 0}`;$('levelPill').textContent='Уровень '+u.tap_level;
}
async function refresh(){try{state.user=await api('/api/me');render()}catch(e){toast(e.message)}}
function openModal(html){$('modalContent').innerHTML=html;$('modal').hidden=false}
$('closeModal').onclick=()=>{$('modal').hidden=true};$('modal').addEventListener('click',e=>{if(e.target.id==='modal')$('modal').hidden=true});
async function openView(view){
  if(view==='home'){window.scrollTo({top:0,behavior:'smooth'});return}
  if(view==='topup') return openModal(`<div class="panel-title">Пополнение</div><div class="muted">Оплата проходит через Telegram Payments.</div><div class="modal-list" style="margin-top:12px">${[1,2,5,10].map(x=>`<div class="modal-item row"><span>$${x} → ${fmt(x*100000)} COIN</span><button onclick="pay(${x})">Оплатить</button></div>`).join('')}</div>`);
  if(view==='withdraw') return openWithdraw();
  if(view==='exchange') return openModal(`<div class="panel-title">Обмен</div><div class="modal-item">Внутренний курс: <b>100 000 COIN = $1</b>. В этой сборке обмен не списывает реальные деньги автоматически.</div>`);
  if(view==='bonuses' || view==='daily') return openDaily();
  if(view==='upgrade') return openUpgrade();
  if(view==='tasks') return openTasks(); if(view==='refs') return openRefs(); if(view==='leaders') return openLeaders(); if(view==='tournament') return openTournament();
  if(view==='profile') return openProfile();
}
async function pay(usd){
  toast('Счёт готовится…');
  try{const x=await api('/api/pay',{method:'POST',body:JSON.stringify({usd})}); tg?.openTelegramLink?.(x.url); if(x.url) location.href=x.url; }catch(e){toast(e.message)}
}
async function openDaily(){try{const d=await api('/api/daily');openModal(`<div class="panel-title">7-дневный вход</div><div class="modal-item"><b>Серия: ${d.streak}/7</b><br><span class="muted">Сегодняшняя награда: ${fmt(d.reward)} COIN</span></div><div style="margin-top:12px"><button class="modal-item" style="width:100%;color:#fff;background:#1e9f86;border:0" onclick="claimDaily()">${d.available?'Забрать награду':'Уже получено сегодня'}</button></div>`)}catch(e){toast(e.message)}}
async function claimDaily(){try{const x=await api('/api/daily/claim',{method:'POST'});toast(x.message);await refresh();await openDaily()}catch(e){toast(e.message)}}
async function openUpgrade(){const u=state.user;const cost=Math.floor(1000*Math.pow(1.8,u.tap_level-1));openModal(`<div class="panel-title">Улучшение тапа</div><div class="modal-item">Текущий уровень: <b>${u.tap_level}</b><br>За тап: <b>+${u.tap_level} COIN</b><br>Цена: <b>${fmt(cost)} COIN</b></div><div style="margin-top:12px"><button class="modal-item" style="width:100%;color:#fff;background:#1e9f86;border:0" onclick="buyUpgrade()">Улучшить</button></div>`)}
async function buyUpgrade(){try{const x=await api('/api/upgrade',{method:'POST'});toast(x.message);await refresh();await openUpgrade()}catch(e){toast(e.message)}}
async function openTasks(){try{const d=await api('/api/tasks');openModal(`<div class="panel-title">Задания</div><div class="modal-list">${d.tasks.map(t=>`<div class="modal-item"><b>${t.title}</b><div class="muted">Награда: ${fmt(t.reward_coins)} COIN</div>${t.done?'<div style="margin-top:8px;color:#3fe0bd">✓ Выполнено</div>':`<div style="margin-top:9px;display:flex;gap:8px">${t.url?`<button onclick="openLink('${t.url}')">Открыть</button>`:''}<button onclick="claimTask(${t.id})">Проверить</button></div>`}</div>`).join('')}</div>`)}catch(e){toast(e.message)}}
function openLink(u){tg?.openTelegramLink?tg.openTelegramLink(u):window.open(u,'_blank')}
async function claimTask(id){try{const x=await api('/api/tasks/'+id+'/claim',{method:'POST'});toast(x.message);await refresh();await openTasks()}catch(e){toast(e.message)}}
async function openRefs(){try{const d=await api('/api/refs');openModal(`<div class="panel-title">Рефералы</div><div class="modal-item">Приглашено: <b>${d.referrals}</b><br>Награда за каждого: <b>${fmt(d.reward_coins)} COIN</b><br>Бонус за 5 приглашённых: <b>$${d.bonus_usd}</b></div><div class="modal-item" style="margin-top:10px">Твоя ссылка<div class="muted" style="word-break:break-all;margin-top:6px">${d.link}</div></div><div style="margin-top:12px"><button class="modal-item" style="width:100%;color:#fff;background:#1e9f86;border:0" onclick="shareRef('${d.link}')">Поделиться</button></div>`)}catch(e){toast(e.message)}}
function shareRef(link){const url='https://t.me/share/url?url='+encodeURIComponent(link);openLink(url)}
async function openLeaders(){try{const d=await api('/api/leaders');openModal(`<div class="panel-title">Лидеры</div><div class="modal-list">${d.users.map((u,i)=>`<div class="modal-item row"><span><b>#${i+1} ${u.name}</b><br><span class="muted">${fmt(u.coins)} COIN</span></span><span>${i<3?['🥇','🥈','🥉'][i]:''}</span></div>`).join('')}</div>`)}catch(e){toast(e.message)}}
async function openTournament(){try{const d=await api('/api/tournament');openModal(`<div class="panel-title">Турнир $${d.prize_usd}</div><div class="modal-item">Рейтинг строится по заработанным COIN. Победитель определяется по данным сервера, выплаты — после проверки.</div><div class="modal-list" style="margin-top:10px">${d.users.map((u,i)=>`<div class="modal-item row"><span>#${i+1} ${u.name}</span><b>${fmt(u.coins)}</b></div>`).join('')}</div>`)}catch(e){toast(e.message)}}
async function openProfile(){const u=state.user;openModal(`<div class="panel-title">Профиль</div><div class="modal-item">Пользователь: <b>${u.username?'@'+u.username:(u.first_name||'User')}</b><br>ID: ${u.id}<br>Рефералы: ${u.referrals}<br>Пополнено: $${Number(u.topup_usd).toFixed(2)}</div>`)}
async function openWithdraw(){const u=state.user;openModal(`<div class="panel-title">Вывод</div>${u.topup_usd<2?`<div class="modal-item">Вывод откроется после пополнения минимум на <b>$2</b>.</div>`:`<div class="modal-item">Курс: <b>100 000 COIN = $1</b><br>Баланс: <b>${fmt(u.coins)} COIN</b></div><input id="wUsd" class="field" type="number" min="1" step="1" placeholder="Сумма в $"/><input id="wDest" class="field" placeholder="Адрес кошелька"/><button class="modal-item" style="width:100%;color:#fff;background:#1e9f86;border:0;margin-top:8px" onclick="requestWithdraw()">Создать заявку</button>`}`)}
async function requestWithdraw(){try{const usd=Number($('wUsd').value), destination=$('wDest').value.trim();const x=await api('/api/withdraw',{method:'POST',body:JSON.stringify({usd,destination})});toast(x.message);await refresh();await openWithdraw()}catch(e){toast(e.message)}}
$('tapBtn').onclick=async()=>{try{const x=await api('/api/tap',{method:'POST'});state.user=x.user;render();toast('+'+x.gain+' COIN')}catch(e){toast(e.message)}};
$('refreshBtn').onclick=refresh;$('topupBtn').onclick=()=>openView('topup');$('upgradeBtn').onclick=()=>openView('upgrade');
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{const v=b.dataset.view;document.querySelectorAll('.nav-btn').forEach(x=>x.classList.toggle('active',x.dataset.view===v));openView(v)}));
refresh();
