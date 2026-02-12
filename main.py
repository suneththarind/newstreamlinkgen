import os
import logging
import asyncio
import mimetypes
import psutil
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
STREAM_URL = os.getenv('STREAM_URL').rstrip('/')
MONGO_URI = os.getenv('MONGO_URI')
ADMIN_PASSWORD = "Menushabaduwa"
LOGO_URL = "https://image2url.com/r2/default/images/1769709206740-5b40868a-02c0-4c63-9db9-c5e68c0733b0.jpg"

# Database & Telegram Client
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client['telegram_bot']
links_col = db['file_links']
client = TelegramClient('bot_session', API_ID, API_HASH)

# --- 🛰️ High-Speed Stream Engine (fyaz05 style) ---
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
        
        # --- CORS Headers (Full Access) ---
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Range, Content-Type, Authorization'
        resp.headers['Access-Control-Expose-Headers'] = 'Content-Range, Content-Length, Accept-Ranges'
        
        resp.headers['Content-Type'] = mime_type
        resp.headers['Content-Length'] = str(end_byte - start_byte + 1)
        resp.headers['Accept-Ranges'] = 'bytes'
        resp.headers['Content-Disposition'] = f'attachment; filename="{name}"'
        
        if range_header:
            resp.headers['Content-Range'] = f'bytes {start_byte}-{end_byte}/{file_size}'
        
        await resp.prepare(request)

        # Streaming data in 512KB chunks for Heroku stability
        async for chunk in client.iter_download(
            file_msg.media, 
            offset=start_byte, 
            request_size=512 * 1024,
            limit=end_byte - start_byte + 1
        ):
            await resp.write(chunk)
        
        return resp
    except Exception as e:
        logger.error(f"Streaming error: {e}")
        return web.Response(text="Internal Server Error", status=500)

# --- 🖼️ UI Helper ---
def get_html(content):
    return f"""
    <!DOCTYPE html><html><head><title>CVCLOUD</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;800&display=swap" rel="stylesheet">
    <style>
        body {{ background: #050505; color: white; font-family: 'Poppins', sans-serif; text-align: center; padding: 20px; margin:0; }}
        .box {{ background: rgba(255,255,255,0.05); padding: 30px; border-radius: 25px; max-width: 500px; margin: 40px auto; border: 1px solid #333; backdrop-filter: blur(10px); }}
        .btn {{ display: inline-block; padding: 12px 25px; background: #e50914; color: white; text-decoration: none; border-radius: 50px; font-weight: bold; margin: 10px; border:none; cursor:pointer; font-family: 'Poppins'; }}
        input {{ width: 85%; padding: 12px; border-radius: 20px; border: none; margin-bottom: 15px; text-align: center; background: #222; color: white; font-family: 'Poppins'; }}
        .file-item {{ text-align: left; padding: 12px; border-bottom: 1px solid #222; font-size: 13px; }}
        a {{ color: #eee; text-decoration: none; }}
        .stats {{ font-size: 10px; color: #555; margin-top: 20px; }}
    </style></head><body>
    <div style="margin-top:50px;">
        <img src="{LOGO_URL}" style="width:85px; border-radius:50%; border:2px solid #e50914;">
    </div>
    <div class="box">{content}</div></body></html>"""

# --- 🛡️ Admin & Search Logic ---
async def admin_handler(request):
    # Handle Login POST
    if request.method == 'POST':
        data = await request.post()
        if data.get('pw') == ADMIN_PASSWORD:
            resp = web.HTTPFound('/admin')
            resp.set_cookie('admin_session', 'active', max_age=86400) # Valid for 1 day
            return resp
        return web.Response(text=get_html("<h3>❌ Invalid Password</h3><a href='/admin' class='btn'>Try Again</a>"), content_type='text/html')

    # Dashboard & Search
    if request.cookies.get('admin_session') == 'active':
        query = request.query.get('q', '').strip()
        results_html = ""
        
        if query:
            # සර්ච් එක නිවැරදිව සිදු කිරීම
            cursor = links_col.find({"file_name": {"$regex": query, "$options": "i"}})
            results = await cursor.to_list(length=50)
            if results:
                for r in results:
                    results_html += f"<div class='file-item'>🎬 <a href='/view/{r['msg_id']}'>{r['file_name']}</a></div>"
            else:
                results_html = "<p style='color:#777;'>No files found.</p>"
        
        total_files = await links_col.count_documents({})
        content = f"""
        <h2 style="color:#e50914; margin-bottom:20px;">Admin Dashboard</h2>
        <form method='get'>
            <input name='q' placeholder='Search movies...' value='{query}'>
            <br><button type='submit' class='btn'>Search Database</button>
        </form>
        <div style='margin-top:20px; max-height:300px; overflow-y:auto;'>
            {results_html}
        </div>
        <div class="stats">
            Total Files: {total_files} | <a href='/logout' style='color:#e50914;'>Logout</a>
        </div>
        """
        return web.Response(text=get_html(content), content_type='text/html')

    # Login Page
    return web.Response(text=get_html("""
        <h3>🔐 Admin Access</h3>
        <form method='post'>
            <input type='password' name='pw' placeholder='Enter Admin Password'>
            <br><button type='submit' class='btn'>Login</button>
        </form>
    """), content_type='text/html')

async def logout_handler(request):
    resp = web.HTTPFound('/admin')
    resp.del_cookie('admin_session')
    return resp

# --- 🏠 Home & 🎬 Player ---
async def index(request):
    return web.Response(text=get_html("""
        <h1 style='letter-spacing:5px; margin:0;'>CVCLOUD</h1>
        <p style='color:#e50914; font-weight:600; margin-top:5px;'>IS ONLINE</p>
        <p style='font-size:12px; color:#555;'>Direct high-speed streaming server.</p>
    """), content_type='text/html')

async def view_page(request):
    try:
        msg_id = int(request.match_info['msg_id'])
        file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        if not file_msg: return web.Response(text="File Not Found", status=404)
        
        name = file_msg.file.name or "video.mp4"
        size_mb = round(file_msg.file.size / (1024 * 1024), 2)
        clean_name = urllib.parse.quote(name)
        dl_url = f"{STREAM_URL}/download/{msg_id}/{clean_name}"
        
        content = f"""
        <h3 style='font-size:16px;'>{name}</h3>
        <p style='font-size:12px; color:#aaa;'>Size: {size_mb} MB</p>
        <video controls style='width:100%; border-radius:15px; background:#000; margin-top:10px;'>
            <source src='{dl_url}' type='video/mp4'>
        </video>
        <br><a href='{dl_url}' class='btn'>📥 High Speed Download</a>
        """
        return web.Response(text=get_html(content), content_type='text/html')
    except Exception as e:
        return web.Response(text=f"Error: {e}")

# --- 🤖 Bot Logic ---
@client.on(events.NewMessage(incoming=True, func=lambda e: e.media))
async def handle_media(event):
    try:
        name = event.file.name or "video.mp4"
        fwd = await client.forward_messages(BIN_CHANNEL, event.message)
        
        # URL එක සෑදීම
        web_link = f"{STREAM_URL}/view/{fwd.id}"
        
        # MongoDB හි සේව් කිරීම
        await links_col.insert_one({
            "msg_id": fwd.id, 
            "file_name": name, 
            "web_link": web_link,
            "size": event.file.size
        })
        
        await event.respond(f"🎬 **File:** `{name}`\n\n🌐 **Web Player:** {web_link}", link_preview=False)
    except Exception as e:
        logger.error(f"Bot error: {e}")

# --- 🚀 Start Server ---
async def main():
    await client.start(bot_token=BOT_TOKEN)
    app = web.Application()
    
    # Routes
    app.add_routes([
        web.get('/', index),
        web.get('/admin', admin_handler),
        web.post('/admin', admin_handler),
        web.get('/logout', logout_handler),
        web.get('/view/{msg_id}', view_page),
        web.get('/download/{msg_id}/{name}', stream_handler),
        web.get('/watch/{msg_id}/{name}', stream_handler),
        # CORS Handling
        web.route('OPTIONS', '/download/{msg_id}/{name}', lambda r: web.Response(headers={
            'Access-Control-Allow-Origin': '*', 
            'Access-Control-Allow-Methods': 'GET, OPTIONS', 
            'Access-Control-Allow-Headers': '*'
        }))
    ])
    
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    logger.info("✅ CVCLOUD Final Build is Live!")
    await asyncio.Event().wait()

if __name__ == '__main__':
    try:
        client.loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
