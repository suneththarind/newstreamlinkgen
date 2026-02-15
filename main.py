import os
import logging
import asyncio
import mimetypes
import urllib.parse
from aiohttp import web
from telethon import TelegramClient, events
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# --- Setup & Logging ---
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configs ---
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
BIN_CHANNEL = int(os.getenv('BIN_CHANNEL'))
STREAM_URL = os.getenv('STREAM_URL', '').rstrip('/')
MONGO_URI = os.getenv('MONGO_URI')
ADMIN_PASSWORD = "Menushabaduwa"
LOGO_URL = "https://image2url.com/r2/default/images/1769709206740-5b40868a-02c0-4c63-9db9-c5e68c0733b0.jpg"

# Database & Client Setup
try:
    db_client = AsyncIOMotorClient(MONGO_URI)
    db = db_client['telegram_bot']
    links_col = db['file_links']
except Exception as e:
    logger.error(f"Database Connection Error: {e}")

client = TelegramClient('bot_session', API_ID, API_HASH)

# --- 🛰️ Ultra High-Speed Proxy Engine ---
async def stream_handler(request):
    try:
        msg_id = int(request.match_info['msg_id'])
        file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        if not file_msg or not file_msg.file:
            return web.Response(text="Asset Not Found", status=404)

        file_size = file_msg.file.size
        name = file_msg.file.name or f"data_{msg_id}.mp4"
        mime_type = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        
        range_header = request.headers.get('Range')
        start_byte = 0
        end_byte = file_size - 1

        if range_header:
            parts = range_header.replace('bytes=', '').split('-')
            start_byte = int(parts[0])
            if len(parts) > 1 and parts[1]:
                end_byte = int(parts[1])

        resp = web.StreamResponse(status=206 if range_header else 200)
        
        # --- CORS AND SPEED HEADERS ---
        resp.headers.update({
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, OPTIONS',
            'Access-Control-Allow-Headers': '*',
            'Content-Type': mime_type,
            'Content-Length': str(end_byte - start_byte + 1),
            'Accept-Ranges': 'bytes',
            'Content-Disposition': f'attachment; filename="{name}"'
        })
        
        if range_header:
            resp.headers['Content-Range'] = f'bytes {start_byte}-{end_byte}/{file_size}'
        
        await resp.prepare(request)
        async for chunk in client.iter_download(file_msg.media, offset=start_byte, limit=end_byte - start_byte + 1):
            await resp.write(chunk)
        return resp
    except Exception as e:
        logger.error(f"Stream Error: {e}")
        return web.Response(text="Source Error", status=500)

# --- UI Template ---
def get_html(content, title="CVCLOUD", is_home=False):
    anim_css = """
    @keyframes pulse { 0% { opacity: 0.7; } 50% { opacity: 1; } 100% { opacity: 0.7; } }
    .status-text { font-weight: bold; font-size: 24px; color: #ff4d4d; animation: pulse 2s infinite; }
    """ if is_home else ""
    return f"""
    <!DOCTYPE html><html><head><title>{title}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600&display=swap" rel="stylesheet">
    <style>
        body {{ background: #000; color: white; font-family: 'Poppins', sans-serif; text-align: center; padding: 20px; }}
        .box {{ background: #0a0a0a; padding: 40px; border-radius: 25px; max-width: 600px; margin: 50px auto; border: 1px solid #1a1a1a; }}
        .btn {{ display: inline-block; padding: 12px 30px; background: #e50914; color: white; text-decoration: none; border-radius: 50px; font-weight: bold; margin: 10px; border:none; cursor:pointer; }}
        input {{ width: 85%; padding: 14px; border-radius: 25px; border: 1px solid #222; margin-bottom: 15px; text-align: center; background: #050505; color: white; outline: none; }}
        .file-item {{ text-align: left; padding: 15px; border-bottom: 1px solid #1a1a1a; display: flex; justify-content: space-between; align-items: center; font-size: 13px; }}
        {anim_css}
    </style></head><body><div class="box">{content}</div></body></html>"""

# --- Page Handlers ---
async def index(request):
    content = f"<img src='{LOGO_URL}' style='width:100px; border-radius:50%;'><br><h1>CV CLOUD</h1><p class='status-text'>SYSTEM ONLINE</p><p style='color:#444; font-size:10px;'>High-Performance Proxy Active</p>"
    return web.Response(text=get_html(content, is_home=True), content_type='text/html')

async def admin_handler(request):
    if request.method == 'POST':
        data = await request.post()
        if data.get('pw') == ADMIN_PASSWORD:
            resp = web.HTTPFound('/admin'); resp.set_cookie('admin_session', 'active', max_age=86400); return resp
        return web.Response(text=get_html("<h3>Key Invalid</h3><a href='/admin' class='btn'>Try Again</a>"), content_type='text/html')

    if request.cookies.get('admin_session') == 'active':
        query = request.query.get('q', '').strip()
        results_html = ""
        if query:
            cursor = links_col.find({"file_name": {"$regex": query, "$options": "i"}})
            async for r in cursor:
                results_html += f"<div class='file-item'>📁 {r['file_name']} <a href='/view/{r['msg_id']}' class='btn' style='padding:5px 12px; font-size:10px;'>VIEW</a></div>"
        
        content = f"<h3>Cloud Manager</h3><form method='get'><input name='q' placeholder='Search assets...' value='{query}'><br><button class='btn'>SEARCH</button></form><div style='margin-top:20px; max-height:350px; overflow-y:auto;'>{results_html or '<p style=color:gray>Search for files</p>'}</div><br><a href='/logout' style='color:#333; font-size:10px;'>Logout</a>"
        return web.Response(text=get_html(content), content_type='text/html')

    return web.Response(text=get_html("<h3>Cloud Login</h3><form method='post'><input type='password' name='pw' placeholder='Security Key'><br><button class='btn'>Connect</button></form>"), content_type='text/html')

async def view_page(request):
    try:
        msg_id = int(request.match_info['msg_id'])
        file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        name = file_msg.file.name or "video.mp4"
        dl = f"{STREAM_URL}/download/{msg_id}/{urllib.parse.quote(name)}"
        content = f"<h4>{name}</h4><video controls style='width:100%; border-radius:15px; background:#000;'><source src='{dl}'></video><br><br><a href='{dl}' class='btn'>📥 DOWNLOAD</a>"
        return web.Response(text=get_html(content, title=name), content_type='text/html')
    except: return web.Response(text="Asset Not Found", status=404)

async def logout_handler(request):
    resp = web.HTTPFound('/admin'); resp.del_cookie('admin_session'); return resp

@client.on(events.NewMessage(incoming=True, func=lambda e: e.media))
async def handle_media(event):
    try:
        f_name, f_size = event.file.name or "video.mp4", event.file.size
        exist = await links_col.find_one({"file_name": f_name, "file_size": f_size})
        if exist:
            await event.respond(f"✅ **Existing Asset:**\n{STREAM_URL}/view/{exist['msg_id']}", link_preview=False)
            return
        fwd = await client.forward_messages(BIN_CHANNEL, event.message)
        await links_col.insert_one({"msg_id": fwd.id, "file_name": f_name, "file_size": f_size})
        await event.respond(f"🚀 **New Asset:**\n{STREAM_URL}/view/{fwd.id}", link_preview=False)
    except Exception as e:
        logger.error(f"Media Error: {e}")

async def main():
    await client.start(bot_token=BOT_TOKEN)
    app = web.Application()
    app.add_routes([
        web.get('/', index), web.get('/admin', admin_handler), web.post('/admin', admin_handler),
        web.get('/logout', logout_handler), web.get('/view/{msg_id}', view_page),
        web.get('/download/{msg_id}/{name}', stream_handler),
        web.route('OPTIONS', '/{tail:.*}', lambda r: web.Response(headers={
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': '*',
            'Access-Control-Allow-Headers': '*'
        }))
    ])
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', 8080).start()
    await asyncio.Event().wait()

if __name__ == '__main__':
    client.loop.run_until_complete(main())
