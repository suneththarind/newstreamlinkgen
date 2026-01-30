import os
import logging
import urllib.parse
import asyncio
import time
import psutil
from datetime import datetime
from telethon import TelegramClient, events
from quart import Quart, Response, request, render_template_string, redirect, url_for, session
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# --- Config ---
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
BIN_CHANNEL = int(os.getenv('BIN_CHANNEL'))
STREAM_URL = os.getenv('STREAM_URL', '').rstrip('/')
MONGO_URI = os.getenv('MONGO_URI')
LOGO_URL = "https://image2url.com/r2/default/images/1769709206740-5b40868a-02c0-4c63-9db9-c5e68c0733b0.jpg"
ADMIN_PASSWORD = "Menushabaduwa"
START_TIME = time.time()

# Database Setup
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client['telegram_bot']
links_col = db['file_links']

app = Quart(__name__)
app.secret_key = "cinecloud_ultra_stable_v3"
client = TelegramClient('bot', API_ID, API_HASH)

# --- UI HTML ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title if title else 'CineCloud' }}</title>
    <link rel="stylesheet" href="https://cdn.plyr.io/3.7.8/plyr.css" />
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;800&display=swap" rel="stylesheet">
    <style>
        :root { --primary-red: #e50914; --deep-dark: #050505; }
        body { font-family: 'Poppins', sans-serif; background: var(--deep-dark); background-image: radial-gradient(circle at top right, #2a0202, transparent); color: #fff; margin: 0; padding: 20px; display: flex; flex-direction: column; align-items: center; min-height: 100vh; }
        .logo { width: 85px; height: 85px; border-radius: 50%; margin-bottom: 20px; border: 2px solid var(--primary-red); box-shadow: 0 0 20px rgba(229, 9, 20, 0.5); }
        .container { background: rgba(255, 255, 255, 0.06); backdrop-filter: blur(15px); -webkit-backdrop-filter: blur(15px); padding: 30px; border-radius: 30px; width: 100%; max-width: 650px; border: 1px solid rgba(255, 255, 255, 0.1); text-align: center; }
        .search-box { width: 100%; max-width: 500px; margin-bottom: 25px; display: {{ 'block' if show_search else 'none' }}; }
        .search-box input { width: 100%; padding: 12px 20px; border-radius: 50px; border: 1px solid rgba(255,255,255,0.1); background: rgba(255,255,255,0.08); color: #fff; outline: none; text-align: center; font-family: inherit; }
        .home-msg { font-weight: 800; font-size: 26px; text-transform: uppercase; letter-spacing: 3px; text-shadow: 0 0 15px var(--primary-red); margin: 60px 0; }
        .btn-group { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 20px; }
        .btn { padding: 13px; border-radius: 50px; text-decoration: none; font-weight: 600; font-size: 13px; cursor: pointer; border: none; color: #fff; transition: 0.3s; text-align: center; }
        .btn-dl { background: rgba(229, 9, 20, 0.6); border: 1px solid rgba(255, 255, 255, 0.1); }
        .btn-cp { background: rgba(255, 255, 255, 0.12); border: 1px solid rgba(255, 255, 255, 0.05); }
        .btn-vlc { background: rgba(255, 136, 0, 0.35); grid-column: span 2; border: 1px solid rgba(255, 136, 0, 0.1); }
        .btn:hover { transform: translateY(-3px); background: var(--primary-red); }
        .stat-box { background: rgba(255,255,255,0.05); padding: 15px; border-radius: 15px; border: 1px solid rgba(229, 9, 20, 0.2); min-width: 120px; }
        .plyr--full-ui.plyr--video { --plyr-color-main: var(--primary-red); }
    </style>
</head>
<body>
    <img src="{{ logo }}" class="logo">
    <div class="search-box"><form action="/search" method="get"><input type="text" name="q" placeholder="Search Movies..." autocomplete="off"></form></div>
    <div class="container">
        {% if is_login %}
            <h2 style="color:var(--primary-red)">🔐 Admin Login</h2>
            <form method="post"><input type="password" name="pw" style="width:80%; padding:10px; border-radius:20px; border:none; margin-bottom:10px;" placeholder="Password"><br><button type="submit" class="btn btn-dl">Login</button></form>
            {% if err %}<p style="color:red">{{ err }}</p>{% endif %}
        {% elif is_admin %}
            <h2 style="color:var(--primary-red)">🚀 Admin Dashboard</h2>
            <div style="display:flex; justify-content:center; gap:10px; flex-wrap:wrap;">
                <div class="stat-box"><h3>{{ total_files }}</h3><p>Files</p></div>
                <div class="stat-box"><h3>{{ ping }}ms</h3><p>Ping</p></div>
                <div class="stat-box"><h3>{{ cpu }}%</h3><p>CPU</p></div>
                <div class="stat-box"><h3>{{ ram }}%</h3><p>RAM</p></div>
            </div>
            <p>Uptime: {{ uptime }}</p><br><a href="/logout" style="color:#888;">Logout</a>
        {% elif is_search %}
            <h3>🔍 Search Results</h3>
            {% for r in results %}<div style="text-align:left; padding:12px; border-bottom:1px solid #333;"><a href="{{ r.web_link }}" style="color:#ddd; text-decoration:none;">🎬 {{ r.file_name }}</a></div>{% else %}<p>No files found.</p>{% endfor %}
            <br><a href="/" class="btn btn-cp">Back Home</a>
        {% elif is_view %}
            <h3>{{ name }}</h3><div style="font-size:11px; color:#aaa; margin-bottom:15px;">{{ size }} MB</div>
            <div style="margin:20px 0; border-radius:18px; overflow:hidden; background:#000; border:1px solid rgba(255,255,255,0.05);">
                <video id="player" playsinline controls><source src="{{ stream_link }}" type="video/mp4"></video>
            </div>
            <div class="btn-group">
                <a href="{{ dl_link }}" class="btn btn-dl">📥 Download Now</a>
                <button onclick="cp('{{ dl_link }}', this)" class="btn btn-cp">📋 Copy Link</button>
                <a href="intent:{{ stream_link }}#Intent;package=org.videolan.vlc;end" class="btn btn-vlc">🧡 Play in VLC Player</a>
            </div>
        {% else %}
            <div class="home-msg">CINECLOUD IS ONLINE</div>
        {% endif %}
    </div>
    <script src="https://cdn.plyr.io/3.7.8/plyr.js"></script>
    <script>
        const player = new Plyr('#player');
        function cp(u,b){
            navigator.clipboard.writeText(u);
            const originalText = b.innerText;
            b.innerText="✅ Copied!";
            setTimeout(()=>b.innerText=originalText, 2000);
        }
    </script>
</body>
</html>
"""

# --- ස්ථාවර Generator එක (High Speed & Resume Support) ---
async def file_generator(file_msg, start, end):
    CHUNK_SIZE = 1024 * 1024  # 1MB
    offset = start
    while offset <= end:
        remaining = end - offset + 1
        current_limit = min(CHUNK_SIZE, remaining)
        try:
            async for chunk in client.iter_download(file_msg.media, offset=offset, limit=current_limit, request_size=CHUNK_SIZE):
                yield chunk
                offset += len(chunk)
            if current_limit == 0: break
        except Exception as e:
            logger.error(f"Generator Error: {e}")
            break

# --- Web Routes ---
@app.route('/')
async def index():
    return await render_template_string(HTML_TEMPLATE, is_view=False, show_search=False, logo=LOGO_URL)

@app.route('/admin', methods=['GET', 'POST'])
async def admin():
    if request.method == 'POST':
        form = await request.form
        if form.get('pw') == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect('/admin')
        return await render_template_string(HTML_TEMPLATE, is_login=True, err="Wrong Password", logo=LOGO_URL)
    if not session.get('admin'): return await render_template_string(HTML_TEMPLATE, is_login=True, logo=LOGO_URL)
    
    start_p = time.time()
    await links_col.find_one()
    ping = round((time.time() - start_p) * 1000)
    uptime = str(datetime.now() - datetime.fromtimestamp(START_TIME)).split('.')[0]
    total = await links_col.count_documents({})
    return await render_template_string(HTML_TEMPLATE, is_admin=True, total_files=total, ping=ping, cpu=psutil.cpu_percent(), ram=psutil.virtual_memory().percent, uptime=uptime, logo=LOGO_URL)

@app.route('/logout')
async def logout():
    session.pop('admin', None)
    return redirect('/')

@app.route('/search')
async def search():
    q = request.args.get('q', '')
    res = await links_col.find({"file_name": {"$regex": q, "$options": "i"}}).limit(20).to_list(20) if q else []
    return await render_template_string(HTML_TEMPLATE, is_search=True, results=res, show_search=True, logo=LOGO_URL)

@app.route('/view/<int:msg_id>')
async def view_page(msg_id):
    try:
        file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        if not file_msg or not file_msg.file: return redirect('/')
        name = file_msg.file.name or "video.mp4"
        size = round(file_msg.file.size / (1024 * 1024), 2)
        return await render_template_string(HTML_TEMPLATE, is_view=True, title=name, name=name, size=size, show_search=True, dl_link=f"{STREAM_URL}/download/{msg_id}", stream_link=f"{STREAM_URL}/watch/{msg_id}", logo=LOGO_URL)
    except: return redirect('/')

@app.route('/download/<int:msg_id>')
@app.route('/watch/<int:msg_id>')
async def stream_handler(msg_id):
    try:
        file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        if not file_msg or not file_msg.file: return "File Not Found", 404

        file_size = file_msg.file.size
        range_header = request.headers.get('Range', None)
        start_byte = 0
        end_byte = file_size - 1

        if range_header:
            range_parts = range_header.replace('bytes=', '').split('-')
            start_byte = int(range_parts[0])
            if range_parts[1]: end_byte = int(range_parts[1])

        headers = {
            'Content-Type': file_msg.file.mime_type or 'application/octet-stream',
            'Accept-Ranges': 'bytes',
            'Content-Length': str(end_byte - start_byte + 1),
            'Content-Disposition': f'attachment; filename="{file_msg.file.name}"' if 'download' in request.path else f'inline; filename="{file_msg.file.name}"',
        }

        status_code = 200
        if range_header:
            headers['Content-Range'] = f'bytes {start_byte}-{end_byte}/{file_size}'
            status_code = 206

        return Response(file_generator(file_msg, start_byte, end_byte), status=status_code, headers=headers)
    except Exception as e:
        logger.error(f"Streaming Error: {str(e)}")
        return "Internal Server Error", 500

# --- Bot Events ---
@client.on(events.NewMessage(incoming=True, func=lambda e: e.media))
async def handle_media(event):
    file_id = event.file.id
    existing = await links_col.find_one({"file_id": file_id})
    if existing:
        return await event.respond(f"✅ **කලින් සකස් කළ Link එක:**\n🔗 {existing['web_link']}", link_preview=False)

    prog = await event.respond("🔄 **Link එක සකසමින් පවතී...**")
    forwarded = await client.forward_messages(BIN_CHANNEL, event.message)
    web_link = f"{STREAM_URL}/view/{forwarded.id}"
    
    await links_col.insert_one({"file_id": file_id, "file_name": event.file.name, "web_link": web_link})
    await prog.edit(f"✅ **සූදානම්!**\n🔗 {web_link}", link_preview=False)

# --- Start Up Sequence (Fix for Disconnected Error) ---
async def start_services():
    await client.start(bot_token=BOT_TOKEN)
    logger.info("✅ Telegram Bot Started!")

    from hypercorn.asyncio import serve
    from hypercorn.config import Config
    
    config = Config()
    config.bind = [f"0.0.0.0:{os.environ.get('PORT', 8080)}"]
    
    logger.info("🚀 Web Server Starting on Hypercorn...")
    await serve(app, config)

if __name__ == '__main__':
    try:
        asyncio.run(start_services())
    except KeyboardInterrupt:
        pass
