import os
import logging
import asyncio
import mimetypes
from datetime import datetime
from aiohttp import web
from telethon import TelegramClient, events
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# --- Setup ---
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
BIN_CHANNEL = int(os.getenv('BIN_CHANNEL'))
STREAM_URL = os.getenv('STREAM_URL').rstrip('/')
MONGO_URI = os.getenv('MONGO_URI')
ADMIN_PASSWORD = "Menushabaduwa"
LOGO_URL = "https://image2url.com/r2/default/images/1769709206740-5b40868a-02c0-4c63-9db9-c5e68c0733b0.jpg"

# Database & Client
db_client = AsyncIOMotorClient(MONGO_URI)
links_col = db_client['telegram_bot']['file_links']
client = TelegramClient('bot_session', API_ID, API_HASH)

# --- 🛰️ Ultra Fast Stream Logic (The fyaz05 method) ---
async def stream_handler(request):
    msg_id = int(request.match_info['msg_id'])
    file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
    
    if not file_msg or not file_msg.file:
        return web.Response(text="File Not Found", status=404)

    file_size = file_msg.file.size
    name = file_msg.file.name or f"file_{msg_id}.mp4"
    mime_type = mimetypes.guess_type(name)[0] or 'application/octet-stream'
    
    range_header = request.headers.get('Range')
    start_byte = 0
    end_byte = file_size - 1

    if range_header:
        parts = range_header.replace('bytes=', '').split('-')
        start_byte = int(parts[0])
        if parts[1]: end_byte = int(parts[1])

    # 🛑 Direct Stream Headers (fyaz05 style)
    resp = web.StreamResponse(status=206 if range_header else 200)
    resp.headers['Content-Type'] = mime_type
    resp.headers['Content-Length'] = str(end_byte - start_byte + 1)
    resp.headers['Accept-Ranges'] = 'bytes'
    resp.headers['Content-Disposition'] = f'attachment; filename="{name}"'
    if range_header:
        resp.headers['Content-Range'] = f'bytes {start_byte}-{end_byte}/{file_size}'
    
    await resp.prepare(request)

    # High-speed data pumping
    try:
        async for chunk in client.iter_download(
            file_msg.media, 
            offset=start_byte, 
            request_size=512 * 1024, # 512KB chunks for stability
            limit=end_byte - start_byte + 1
        ):
            await resp.write(chunk)
    except Exception as e:
        logger.error(f"Stream error: {e}")
    
    return resp

# --- 🖼️ UI Helper ---
def get_html(content):
    return f"""
    <html><head><title>CineCloud</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins&display=swap" rel="stylesheet">
    <style>
        body {{ background: #050505; color: white; font-family: 'Poppins', sans-serif; text-align: center; padding: 40px; }}
        .box {{ background: #111; padding: 30px; border-radius: 20px; max-width: 500px; margin: auto; border: 1px solid #333; }}
        .btn {{ display: inline-block; padding: 12px 25px; background: #e50914; color: white; text-decoration: none; border-radius: 50px; font-weight: bold; margin: 10px; }}
        input {{ width: 80%; padding: 10px; border-radius: 20px; border: none; margin-bottom: 10px; text-align: center; }}
    </style></head><body>
    <img src="{LOGO_URL}" style="width:80px; border-radius:50%; border:2px solid #e50914; margin-bottom:15px;">
    <div class="box">{content}</div></body></html>"""

# --- Web Routes ---
async def admin_page(request):
    data = await request.post()
    if data.get('pw') == ADMIN_PASSWORD:
        resp = web.Response(text=get_html("<h2>Login Success</h2><a href='/dashboard' class='btn'>Go to Dashboard</a>"), content_type='text/html')
        resp.set_cookie('admin_session', 'active', max_age=3600)
        return resp
    
    q = request.query.get('q', '')
    if request.cookies.get('admin_session') == 'active':
        results = await links_col.find({"file_name": {"$regex": q, "$options": "i"}}).to_list(10) if q else []
        res_html = "".join([f"<p style='font-size:12px;'>🎬 <a href='{r['web_link']}' style='color:#ccc;'>{r['file_name']}</a></p>" for r in results])
        return web.Response(text=get_html(f"<h3>Search Files</h3><form><input name='q' placeholder='Search...'><br><button class='btn'>Search</button></form>{res_html}"), content_type='text/html')

    return web.Response(text=get_html(f"<h3>Admin Login</h3><form method='post'><input type='password' name='pw' placeholder='Password'><br><button class='btn'>Login</button></form>"), content_type='text/html')

async def view_page(request):
    msg_id = int(request.match_info['msg_id'])
    file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
    if not file_msg: return web.Response(text="Not Found")
    name = file_msg.file.name
    dl = f"{STREAM_URL}/download/{msg_id}/{name.replace(' ', '_')}"
    return web.Response(text=get_html(f"<h3>{name}</h3><video controls style='width:100%; border-radius:10px;'><source src='{dl}'></video><br><a href='{dl}' class='btn'>📥 STABLE DOWNLOAD</a>"), content_type='text/html')

async def index(request):
    return web.Response(text=get_html("<h1>CineCloud Online</h1><p>Send a file to bot to get links.</p><a href='/admin' class='btn'>Admin Login</a>"), content_type='text/html')

# --- Bot Logic ---
@client.on(events.NewMessage(incoming=True, func=lambda e: e.media))
async def handle_media(event):
    name = event.file.name or "file.mp4"
    fwd = await client.forward_messages(BIN_CHANNEL, event.message)
    web_link = f"{STREAM_URL}/view/{fwd.id}"
    await links_col.insert_one({"msg_id": fwd.id, "file_name": name, "web_link": web_link})
    await event.respond(f"🎬 **File:** `{name}`\n\n🌐 **Player:** {web_link}", link_preview=False)

# --- Start Everything ---
async def main():
    await client.start(bot_token=BOT_TOKEN)
    app = web.Application()
    app.add_routes([
        web.get('/', index),
        web.get('/admin', admin_page),
        web.post('/admin', admin_page),
        web.get('/view/{msg_id}', view_page),
        web.get('/download/{msg_id}/{name}', stream_handler),
        web.get('/watch/{msg_id}/{name}', stream_handler)
    ])
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', 8080)))
    await site.start()
    await asyncio.Event().wait()

if __name__ == '__main__':
    client.loop.run_until_complete(main())
