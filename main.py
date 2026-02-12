import os
import logging
import urllib.parse
import asyncio
import psutil
import time
from telethon import TelegramClient, events
from quart import Quart, Response, request, render_template_string, redirect, session
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# --- Config ---
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
BIN_CHANNEL = int(os.getenv('BIN_CHANNEL'))
STREAM_URL = os.getenv('STREAM_URL').rstrip('/')
MONGO_URI = os.getenv('MONGO_URI')
ADMIN_PASSWORD = "Menushabaduwa" # මෙය අවශ්‍ය නම් වෙනස් කරන්න
LOGO_URL = "https://image2url.com/r2/default/images/1769709206740-5b40868a-02c0-4c63-9db9-c5e68c0733b0.jpg"

app = Quart(__name__)
app.secret_key = "secure_cinecloud_final_fixed"

# Database Setup
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client['telegram_bot']
links_col = db['file_links']

# Telethon Client
client = TelegramClient('bot_session', API_ID, API_HASH)

# --- UI Template ---
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
        body { font-family: 'Poppins', sans-serif; background: var(--deep-dark); color: #fff; margin: 0; padding: 20px; display: flex; flex-direction: column; align-items: center; min-height: 100vh; }
        .logo { width: 85px; border-radius: 50%; margin-bottom: 20px; border: 2px solid var(--primary-red); }
        .container { background: rgba(255, 255, 255, 0.06); backdrop-filter: blur(15px); padding: 30px; border-radius: 30px; width: 100%; max-width: 650px; border: 1px solid rgba(255, 255, 255, 0.1); text-align: center; }
        .btn { padding: 13px 25px; border-radius: 50px; text-decoration: none; font-weight: 600; cursor: pointer; border: none; color: #fff; display: inline-block; margin: 10px; transition: 0.3s; background: var(--primary-red); }
        .search-input { width: 85%; padding: 12px; border-radius: 25px; border: none; background: rgba(255,255,255,0.1); color: white; margin-bottom: 15px; text-align: center; }
        .file-list { text-align: left; margin-top: 20px; max-height: 300px; overflow-y: auto; }
        .file-item { padding: 12px; border-bottom: 1px solid #333; }
        .file-item a { color: #ddd; text-decoration: none; font-size: 14px; }
        video { width: 100%; border-radius: 18px; }
    </style>
</head>
<body>
    <img src="{{ logo }}" class="logo">
    <div class="container">
        {% if is_login %}
            <h2 style="color:var(--primary-red)">🔐 Admin Login</h2>
            <form method="post"><input type="password" name="pw" class="search-input" placeholder="Password"><br><button type="submit" class="btn">Login</button></form>
        {% elif is_admin %}
            <h2 style="color:var(--primary-red)">🚀 Admin Dashboard</h2>
            <form action="/admin" method="get"><input type="text" name="q" class="search-input" placeholder="Search Files..."><br><button type="submit" class="btn">Search</button></form>
            <div class="file-list">
                {% for r in results %}<div class="file-item"><a href="{{ r.web_link }}">🎬 {{ r.file_name }}</a></div>{% endfor %}
            </div>
            <p style="font-size: 12px; color: #777; margin-top: 15px;">Total Files: {{ total_files }} | RAM: {{ ram }}%</p>
            <a href="/logout" style="color:#555; font-size: 12px;">Logout</a>
        {% elif is_view %}
            <h3>{{ name }}</h3>
            <p style="color:#aaa;">Size: {{ size }} MB</p>
            <video id="player" playsinline controls><source src="{{ stream_link }}" type="video/mp4"></video>
            <br><a href="{{ dl_link }}" class="btn">📥 Stable High Speed Download</a>
        {% else %}
            <h1 style="letter-spacing: 5px; color: var(--primary-red);">CINECLOUD</h1>
            <p>Direct Download Server is Online!</p>
            <a href="/admin" class="btn">Admin Login</a>
        {% endif %}
    </div>
    <script src="https://cdn.plyr.io/3.7.8/plyr.js"></script>
    <script>const player = new Plyr('#player');</script>
</body>
</html>
"""

# --- 🛠️ Optimized Stable Generator ---
async def file_generator(file_msg, start, end):
    CHUNK_SIZE = 1024 * 1024  # 1MB
    offset = start
    while offset <= end:
        remaining = end - offset + 1
        current_limit = min(CHUNK_SIZE, remaining)
        try:
            async for chunk in client.iter_download(
                file_msg.media,
                offset=offset,
                limit=current_limit,
                request_size=CHUNK_SIZE
            ):
                yield chunk
                offset += len(chunk)
            if current_limit == 0: break
        except Exception as e:
            logger.error(f"Error while generating chunks: {e}")
            break

# --- Web Routes ---
@app.route('/download/<int:msg_id>/<path:file_name>')
@app.route('/watch/<int:msg_id>/<path:file_name>')
async def stream_handler(msg_id, file_name):
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
            'Cache-Control': 'no-cache',
            'Content-Disposition': f'attachment; filename="{file_msg.file.name}"',
        }

        status = 206 if range_header else 200
        if range_header: headers['Content-Range'] = f'bytes {start_byte}-{end_byte}/{file_size}'

        return Response(file_generator(file_msg, start_byte, end_byte), status=status, headers=headers)
    except Exception as e:
        logger.error(f"Streaming Error: {e}")
        return "Internal Error", 500

@app.route('/view/<int:msg_id>')
async def view_page(msg_id):
    file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
    if not file_msg: return redirect('/')
    name = file_msg.file.name
    clean_name = name.replace(" ", "_")
    size = round(file_msg.file.size / (1024 * 1024), 2)
    return await render_template_string(HTML_TEMPLATE, is_view=True, name=name, size=size, logo=LOGO_URL,
                                       dl_link=f"{STREAM_URL}/download/{msg_id}/{clean_name}",
                                       stream_link=f"{STREAM_URL}/watch/{msg_id}/{clean_name}")

@app.route('/admin', methods=['GET', 'POST'])
async def admin():
    if request.method == 'POST':
        form = await request.form
        if form.get('pw') == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect('/admin')
    if not session.get('admin'): return await render_template_string(HTML_TEMPLATE, is_login=True, logo=LOGO_URL)
    
    query = request.args.get('q', '')
    results = await links_col.find({"file_name": {"$regex": query, "$options": "i"}}).to_list(20) if query else []
    total = await links_col.count_documents({})
    return await render_template_string(HTML_TEMPLATE, is_admin=True, results=results, total_files=total, ram=psutil.virtual_memory().percent, logo=LOGO_URL)

@app.route('/logout')
async def logout():
    session.pop('admin', None)
    return redirect('/')

@app.route('/')
async def index(): return await render_template_string(HTML_TEMPLATE, logo=LOGO_URL)

# --- Bot Events ---
@client.on(events.NewMessage(incoming=True, func=lambda e: e.media))
async def handle_media(event):
    prog = await event.respond("🔄 Processing...")
    try:
        forwarded = await client.forward_messages(BIN_CHANNEL, event.message)
        file_name = event.file.name or "video.mp4"
        web_link = f"{STREAM_URL}/view/{forwarded.id}"
        dl_link = f"{STREAM_URL}/download/{forwarded.id}/{file_name.replace(' ', '_')}"
        
        await links_col.insert_one({"msg_id": forwarded.id, "file_name": file_name, "web_link": web_link})
        await prog.edit(f"🎬 **File:** `{file_name}`\n\n📥 **Download:** {dl_link}\n🌐 **Web Player:** {web_link}", link_preview=False)
    except Exception as e:
        logger.error(f"Bot Error: {e}")

# --- Main Run (FIXED FOR HEROKU CONNECTION) ---
async def start_everything():
    # 1. Start Telethon
    await client.start(bot_token=BOT_TOKEN)
    logger.info("✅ Telegram Bot Connected!")
    
    # 2. Start Web Server in Background
    port = int(os.environ.get('PORT', 8080))
    loop = asyncio.get_event_loop()
    loop.create_task(app.run_task(host='0.0.0.0', port=port))
    logger.info(f"✅ Web Server running on port {port}")
    
    # 3. Keep running
    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(start_everything())
    except KeyboardInterrupt:
        pass
