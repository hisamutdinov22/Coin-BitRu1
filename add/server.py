from fastapi import FastAPI
from fastapi.responses import JSONResponse
from .db import init_db
from .config import settings
app=FastAPI(title='Coin BitRu Server', version='1.0.0')

@app.on_event('startup')
async def startup(): await init_db()

@app.get('/')
async def root(): return {'service':'Coin BitRu','status':'ok'}

@app.get('/health')
async def health(): return JSONResponse({'status':'healthy'})
