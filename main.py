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
    # Search speed එක වැඩි කිරීමට Index එකක් හදමු
    asyncio.get_event_loop().create_task(links_col.create_index([("file_name", "text")]))
except Exception as e:
    logger.error(f"MongoDB Error: {e}")

client = TelegramClient('bot_session', API_ID, API_HASH)

# --- 🛰️ High-Speed Stream Engine ---
async def stream_handler(request):
    try:
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
            if len(parts) > 1 and parts[1]:
                end_byte = int(parts[1])

        resp = web.StreamResponse(status=206 if range_header else 200)
        
        # Headers for Speed & CORS
        resp.headers.update({
            'Access-Control-Allow-Origin': '*',
            'Content-Type': mime_type,
            'Content-Length': str(end_byte - start_byte + 1),
            'Accept-Ranges': 'bytes',
            'Content-Disposition': f'attachment; filename="{name}"'
        })
        
        if range_header:
            resp.headers['Content-Range'] = f'bytes {start_byte}-{end_byte}/{file_size}'
        
        await resp.prepare(request)
        
        # 1MB Chunk size for high-speed transfer
        async for chunk in client.iter_download(
            file_msg.media, 
            offset=start_byte, 
            request_size=1024*1024, 
            limit=end_byte - start_byte + 1
        ):
            await resp.write(chunk)
        return resp
    except Exception as e:
        logger.error(f"Stream Error: {e}")
        return web.Response(text="Stream Error", status=500)

# --- UI Template ---
def get_html(content, title="CVCLOUD"):
    return f"""
    <!DOCTYPE html><html><head><title>{title}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600&display=swap" rel="stylesheet">
    <style>
        body {{ background: #050505; color: white; font-family: 'Poppins', sans-serif; text-align: center; padding: 20px; }}
        .box {{ background: rgba(255,255,255,0.05); padding: 30px; border-radius: 25px; max-width: 600px; margin: 40px auto; border: 1px solid #333; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }}
        .btn {{ display: inline-block; padding: 12px 25px; background: #e50914; color: white; text-decoration: none; border-radius: 50px; font-weight: bold; margin: 10px; border:none; cursor:pointer; transition: 0.3s; }}
        .btn:hover {{ background: #b20710; transform: scale(1.05); }}
        input {{ width: 85%; padding: 12px; border-radius: 20px; border: 1px solid #444; margin-bottom: 15px; text-align: center; background: #222; color: white; outline: none; }}
        .file-item {{ text-align: left; padding: 15px; border-bottom: 1px solid #222; font-size: 14px; display: flex; justify-content: space-between; align-items: center; }}
        .file-item a {{ color: #eee; text-decoration: none; }}
        .file-item a:hover {{ color: #e50914; }}
        .stats {{ font-size: 12px; color: #888; margin-top: 10px; }}
    </style></head><body>
    <a href="/"><img src="{LOGO_URL}" style="width:80px; border-radius:50%; border:2px solid #e50914; cursor:pointer;"></a>
    <div class="box">{content}</div></body></html>"""

# --- Admin & Search Handler ---
async def admin_handler(request):
    if request.method == 'POST':
        data = await request.post()
        if data.get('pw') == ADMIN_PASSWORD:
            resp = web.HTTPFound('/admin')
            resp.set_cookie('admin_session', 'active', max_age=86400)
            return resp
        return web.Response(text=get_html("<h3>❌ Invalid Password</h3><a href='/admin' class='btn'>Try Again</a>"), content_type='text/html')

    if request.cookies.get('admin_session') == 'active':
        query = request.query.get('q', '').strip()
        results_html = ""
        
        if query:
            # Improved Regex Search (Case-insensitive)
            cursor = links_col.find({"file_name": {"$regex": query, "$options": "i"}})
            results = await cursor.to_list(length=100)
            if results:
                for r in results:
                    m_id = r.get('msg_id')
                    f_name = r.get('file_name', 'Unknown File')
                    results_html += f"<div class='file-item'><span>🎬 {f_name}</span> <a href='/view/{m_id}' class='btn' style='padding: 5px 15px; font-size:12px;'>VIEW</a></div>"
            else:
                results_html = "<p>No movies found for your search.</p>"
        
        total = await links_col.count_documents({})
        content = f"""
            <h3>Movie Dashboard</h3>
            <form method='get'>
                <input name='q' placeholder='Search movie name...' value='{query}'>
                <br><button class='btn'>SEARCH NOW</button>
            </form>
            <div style='margin-top:20px; max-height: 400px; overflow-y: auto;'>{results_html}</div>
            <div class='stats'>Total Files in DB: {total} | <a href='/logout' style='color:#e50914;'>Logout</a></div>
        """
        return web.Response(text=get_html(content), content_type='text/html')

    return web.Response(text=get_html("<h3>Admin Login</h3><form method='post'><input type='password' name='pw' placeholder='Password'><br><button class='btn'>Login</button></form>"), content_type='text/html')

async def logout_handler(request):
    resp = web.HTTPFound('/admin'); resp.del_cookie('admin_session'); return resp

async def index(request):
    return web.Response(text=get_html("<h1>CVCLOUD</h1><p style='color:#e50914; font-weight:bold;'>ULTRA HIGH SPEED STREAMING</p><a href='/admin' class='btn'>GO TO DASHBOARD</a>"), content_type='text/html')

async def view_page(request):
    try:
        msg_id = int(request.match_info['msg_id'])
        file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        if not file_msg: return web.Response(text="404 Not Found", status=404)
        name = file_msg.file.name or "video.mp4"
        encoded_name = urllib.parse.quote(name)
        dl = f"{STREAM_URL}/download/{msg_id}/{encoded_name}"
        
        content = f"""
            <h3 style='font-size:16px;'>{name}</h3>
            <video controls controlsList="nodownload" style='width:100%; border-radius:15px; background:#000; box-shadow: 0 5px 15px rgba(0,0,0,0.5);'>
                <source src='{dl}' type='video/mp4'>
                Your browser does not support video.
            </video>
            <br><br>
            <a href='{dl}' class='btn'>📥 DOWNLOAD NOW</a>
            <p style='font-size:11px; color:#666;'>High-speed link generated by CVCLOUD</p>
        """
        return web.Response(text=get_html(content, title=name), content_type='text/html')
    except: return web.Response(text="Error loading player")

# --- Telegram Media Handler (Duplicate Protection Enabled) ---
@client.on(events.NewMessage(incoming=True, func=lambda e: e.media))
async def handle_media(event):
    try:
        file_name = event.file.name or "video.mp4"
        file_size = event.file.size

        # 🔍 Step 1: Check if file exists by Name and Size
        existing_file = await links_col.find_one({"file_name": file_name, "file_size": file_size})

        if existing_file:
            msg_id = existing_file['msg_id']
            web_link = f"{STREAM_URL}/view/{msg_id}"
            await event.respond(f"♻️ **File already in Database:**\n\n**Name:** `{file_name}`\n**Link:** {web_link}", link_preview=False)
            return

        # 🆕 Step 2: If not exists, forward to bin channel
        fwd = await client.forward_messages(BIN_CHANNEL, event.message)
        
        # 💾 Step 3: Save to MongoDB
        await links_col.insert_one({
            "msg_id": fwd.id, 
            "file_name": file_name,
            "file_size": file_size
        })
        
        web_link = f"{STREAM_URL}/view/{fwd.id}"
        await event.respond(f"✅ **Successfully Uploaded:**\n\n**Name:** `{file_name}`\n**Link:** {web_link}", link_preview=False)
    except Exception as e:
        logger.error(f"Media Handler Error: {e}")

async def main():
    await client.start(bot_token=BOT_TOKEN)
    app = web.Application()
    app.add_routes([
        web.get('/', index), 
        web.get('/admin', admin_handler), 
        web.post('/admin', admin_handler),
        web.get('/logout', logout_handler), 
        web.get('/view/{msg_id}', view_page),
        web.get('/download/{msg_id}/{name}', stream_handler),
        web.get('/watch/{msg_id}/{name}', stream_handler),
        web.route('OPTIONS', '/{tail:.*}', lambda r: web.Response(headers={
            'Access-Control-Allow-Origin': '*', 
            'Access-Control-Allow-Methods': '*', 
            'Access-Control-Allow-Headers': '*'
        }))
    ])
    
    port = int(os.environ.get('PORT', 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', port).start()
    logger.info(f"CVCLOUD Bot Started on port {port}")
    await asyncio.Event().wait()

if __name__ == '__main__':
    try:
        client.loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
