import os
import logging
import urllib.parse
import asyncio
import psutil
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
ADMIN_PASSWORD = "Menushabaduwa"
LOGO_URL = "https://image2url.com/r2/default/images/1769709206740-5b40868a-02c0-4c63-9db9-c5e68c0733b0.jpg"

app = Quart(__name__)
app.secret_key = "secure_cinecloud_final"

# Database Setup
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client['telegram_bot']
links_col = db['file_links']

# Telethon Client
client = TelegramClient('bot', API_ID, API_HASH)

# --- UI Template (Secure Admin + Player) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title if title else 'CineCloud' }}</title>
    <link rel="stylesheet" href="https://cdn.plyr.io/3.7.8/plyr.css" />
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Poppins', sans-serif; background: #050505; color: #fff; margin: 0; padding: 20px; display: flex; flex-direction: column; align-items: center; }
        .container { background: rgba(255, 255, 255, 0.05); padding: 30px; border-radius: 25px; width: 100%; max-width: 650px; border: 1px solid #333; text-align: center; }
        .logo { width: 80px; border-radius: 50%; border: 2px solid #e50914; margin-bottom: 20px; }
        .btn { display: inline-block; padding: 12px 25px; background: #e50914; color: #fff; text-decoration: none; border-radius: 50px; font-weight: 600; margin: 10px; border: none; cursor: pointer; }
        .search-input { width: 85%; padding: 12px; border-radius: 25px; border: none; background: rgba(255,255,255,0.1); color: white; margin-bottom: 15px; text-align: center; }
        .file-list { text-align: left; margin-top: 20px; max-height: 250px; overflow-y: auto; }
        .file-item { padding: 10px; border-bottom: 1px solid #222; font-size: 14px; }
        video { width: 100%; border-radius: 15px; }
    </style>
</head>
<body>
    <img src="{{ logo }}" class="logo">
    <div class="container">
        {% if is_login %}
            <h2>🔐 Admin Login</h2>
            <form method="post"><input type="password" name="pw" class="search-input" placeholder="Password"><br><button type="submit" class="btn">Login</button></form>
        {% elif is_admin %}
            <h2>🚀 Admin Dashboard</h2>
            <form action="/admin" method="get"><input type="text" name="q" class="search-input" placeholder="Search Files..."><br><button type="submit" class="btn">Search</button></form>
            <div class="file-list">
                {% for r in results %}<div class="file-item"><a href="{{ r.web_link }}" style="color:#eee; text-decoration:none;">🎬 {{ r.file_name }}</a></div>{% endfor %}
            </div>
            <p style="font-size:12px; color:#666; margin-top:10px;">Total: {{ total_files }} | RAM: {{ ram }}%</p>
            <a href="/logout" style="color:#444; font-size:11px;">Logout</a>
        {% elif is_view %}
            <h3>{{ name }}</h3>
            <p style="color:#aaa;">{{ size }} MB</p>
            <video id="player" playsinline controls><source src="{{ stream_link }}" type="video/mp4"></video>
            <br><a href="{{ dl_link }}" class="btn">📥 High Speed Download</a>
        {% else %}
            <h1>CINECLOUD</h1>
            <p>Direct Download Server is Online!</p>
            <a href="/admin" class="btn">Admin Login</a>
        {% endif %}
    </div>
    <script src="https://cdn.plyr.io/3.7.8/plyr.js"></script>
    <script>const player = new Plyr('#player');</script>
</body>
</html>
"""

# --- උඹ දීපු ස්ථාවර Download Generator එක (එහෙමමයි) ---
async def file_generator(file_msg, start, end):
    CHUNK_SIZE = 1024 * 1024  # 1MB chunks
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

# --- Routes ---
@app.route('/download/<int:msg_id>/<path:file_name>')
@app.route('/watch/<int:msg_id>/<path:file_name>')
async def stream_handler(msg_id, file_name):
    try:
        file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        if not file_msg or not file_msg.file: return "File Not Found", 404

        file_size = file_msg.file.size
        mime_type = file_msg.file.mime_type or 'application/octet-stream'
        
        range_header = request.headers.get('Range', None)
        start_byte = 0
        end_byte = file_size - 1

        if range_header:
            range_parts = range_header.replace('bytes=', '').split('-')
            start_byte = int(range_parts[0])
            if range_parts[1]: end_byte = int(range_parts[1])

        headers = {
            'Content-Type': mime_type,
            'Accept-Ranges': 'bytes',
            'Content-Length': str(end_byte - start_byte + 1),
            'Cache-Control': 'no-cache',
            'Content-Disposition': f'attachment; filename="{file_msg.file.name}"',
        }

        status_code = 206 if range_header else 200
        if range_header: headers['Content-Range'] = f'bytes {start_byte}-{end_byte}/{file_size}'

        return Response(file_generator(file_msg, start_byte, end_byte), status=status_code, headers=headers)
    except Exception as e:
        logger.error(f"Streaming Error: {str(e)}")
        return "Internal Server Error", 500

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
    prog_msg = await event.respond("🔄 Processing Media...")
    try:
        forwarded = await client.forward_messages(BIN_CHANNEL, event.message)
        file_name = event.file.name or "video.mp4"
        clean_name = file_name.replace(" ", "_")
        
        web_link = f"{STREAM_URL}/view/{forwarded.id}"
        dl_link = f"{STREAM_URL}/download/{forwarded.id}/{clean_name}"
        
        # Save to MongoDB
        await links_col.insert_one({"msg_id": forwarded.id, "file_name": file_name, "web_link": web_link})
        
        await prog_msg.edit(f"✅ **Links Ready!**\n\n📁 **Name:** `{file_name}`\n\n📥 **Fast Download:** {dl_link}\n🌐 **Player Link:** {web_link}", link_preview=False)
    except Exception as e:
        logger.error(f"Bot Error: {e}")
        await prog_msg.edit("An error occurred.")

# --- Run ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    client.loop.create_task(app.run_task(host='0.0.0.0', port=port))
    client.run_until_disconnected()
