import asyncio
from concurrent.futures import ThreadPoolExecutor
import uvicorn
from app.server import app
from app.bot import main as bot_main
from app.config import settings

async def run():
    server=uvicorn.Server(uvicorn.Config(app,host=settings.web_host,port=settings.effective_web_port,log_level='info'))
    await asyncio.gather(server.serve(),bot_main())

if __name__=='__main__': asyncio.run(run())
