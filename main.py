import os
import asyncio
import logging
import urllib.parse
from telethon import TelegramClient, events
from quart import Quart, Response, request, render_template_string
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# --- Configs ---
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
BIN_CHANNEL = int(os.getenv('BIN_CHANNEL'))
STREAM_URL = os.getenv('STREAM_URL', '').rstrip('/')
MONGO_URI = os.getenv('MONGO_URI')
LOGO_URL = "https://image2url.com/r2/default/images/1769709206740-5b40868a-02c0-4c63-9db9-c5e68c0733b0.jpg"

# --- Database ---
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client['telegram_bot']
links_col = db['file_links']

app = Quart(__name__)
client = TelegramClient('bot', API_ID, API_HASH)

# --- Deep Dark & Red Glassy UI ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ name }} - Enusha Streaming</title>
    <link rel="stylesheet" href="https://cdn.plyr.io/3.7.8/plyr.css" />
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600&display=swap" rel="stylesheet">
    <style>
        :root { --primary-red: #e50914; --deep-dark: #050505; }
        body { 
            font-family: 'Poppins', sans-serif; background-color: var(--deep-dark); 
            background-image: radial-gradient(circle at top right, #2a0202, transparent);
            color: #fff; margin: 0; padding: 20px; display: flex; flex-direction: column; align-items: center; min-height: 100vh;
        }
        .logo { width: 90px; height: 90px; border-radius: 50%; margin-bottom: 15px; border: 2px solid var(--primary-red); box-shadow: 0 0 20px rgba(229, 9, 20, 0.4); }
        .container { 
            background: rgba(255, 255, 255, 0.06); backdrop-filter: blur(15px); -webkit-backdrop-filter: blur(15px);
            padding: 30px; border-radius: 30px; width: 100%; max-width: 600px; border: 1px solid rgba(255, 255, 255, 0.1); text-align: center;
        }
        .player-wrapper { margin: 25px 0; border-radius: 20px; overflow: hidden; background: #000; border: 1px solid rgba(229, 9, 20, 0.2); }
        .plyr--full-ui.plyr--video { --plyr-color-main: var(--primary-red); }
        .btn-group { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 25px; }
        .btn { 
            padding: 14px; border-radius: 50px; text-decoration: none; font-weight: 600; font-size: 14px; 
            transition: 0.3s; cursor: pointer; border: none; color: #fff; backdrop-filter: blur(5px);
        }
        .btn-dl { background: rgba(229, 9, 20, 0.6); border: 1px solid rgba(255, 255, 255, 0.1); }
        .btn-cp { background: rgba(255, 255, 255, 0.1); border: 1px solid rgba(255, 255, 255, 0.05); }
        .btn-vlc { background: rgba(255, 136, 0, 0.3); grid-column: span 2; border: 1px solid rgba(255, 136, 0, 0.2); }
        .btn:hover { transform: translateY(-3px); box-shadow: 0 5px 15px rgba(229, 9, 20, 0.4); background: var(--primary-red); }
        h3 { margin-bottom: 5px; font-size: 18px; word-wrap: break-word; }
        .info { font-size: 12px; color: #aaa; margin-bottom: 10px; }
    </style>
</head>
<body>
    <img src="{{ logo }}" class="logo">
    <div class="container">
        <h3>{{ name }}</h3>
        <div class="info">{{ size }} MB • {{ mime }}</div>
        <div class="player-wrapper">
            <video id="player" playsinline controls data-poster="{{ logo }}">
                <source src="{{ stream_link }}" type="video/mp4" />
                <source src="{{ stream_link }}" type="video/x-matroska" />
            </video>
        </div>
        <div class="btn-group">
            <a href="{{ dl_link }}" class="btn btn-dl">📥 Download Now</a>
            <button onclick="copyLink('{{ dl_link }}', this)" class="btn btn-cp">📋 Copy DL Link</button>
            <button onclick="copyLink('{{ stream_link }}', this)" class="btn btn-cp">🔗 Copy Stream Link</button>
            <a href="intent:{{ stream_link }}#Intent;package=org.videolan.vlc;end" class="btn btn-vlc">🧡 Play in VLC Player</a>
        </div>
    </div>
    <script src="https://cdn.plyr.io/3.7.8/plyr.js"></script>
    <script>
        const player = new Plyr('#player');
        function copyLink(url, btn) {
            navigator.clipboard.writeText(url);
            const oldText = btn.innerText;
            btn.innerText = "✅ Copied!";
            setTimeout(() => { btn.innerText = oldText; }, 2000);
        }
    </script>
</body>
</html>
"""

# --- Streaming Engine ---
async def file_generator(file_msg, start, end):
    chunk_size = 1024 * 1024  # 1MB chunks for speed
    async for chunk in client.iter_download(file_msg.media, offset=start, limit=(end - start + 1), request_size=chunk_size):
        yield chunk

@app.route('/view/<int:msg_id>')
async def view_page(msg_id):
    try:
        file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        name = file_msg.file.name or "Unknown File"
        size = round(file_msg.file.size / (1024*1024), 2)
        mime = file_msg.file.mime_type or 'video/mp4'
        is_mkv = name.lower().endswith('.mkv')
        return await render_template_string(HTML_TEMPLATE, name=name, size=size, mime=mime, is_mkv=is_mkv,
                                            dl_link=f"{STREAM_URL}/download/{msg_id}", 
                                            stream_link=f"{STREAM_URL}/watch/{msg_id}", logo=LOGO_URL)
    except Exception as e: return str(e)

@app.route('/download/<int:msg_id>')
@app.route('/watch/<int:msg_id>')
async def stream_handler(msg_id):
    file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
    file_size = file_msg.file.size
    range_header = request.headers.get('Range', None)
    start, end = 0, file_size - 1
    if range_header:
        parts = range_header.replace('bytes=', '').split('-')
        start = int(parts[0])
        if len(parts) > 1 and parts[1]: end = int(parts[1])
    headers = {'Content-Type': file_msg.file.mime_type or 'video/mp4', 'Accept-Ranges': 'bytes', 
               'Content-Length': str(end - start + 1), 'Content-Disposition': f'inline; filename="{file_msg.file.name}"'}
    if range_header: headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'
    return Response(file_generator(file_msg, start, end), status=206 if range_header else 200, headers=headers)

# --- Bot Events ---
@client.on(events.NewMessage(incoming=True, func=lambda e: e.media))
async def handle_media(event):
    existing = await links_col.find_one({"file_id": event.file.id})
    if existing: return await event.respond(f"✅ **කලින් සකස් කළ Link එක:**\n\n🔗 {existing['web_link']}", link_preview=False)
    
    msg = await event.respond("⚡ **Processing...**")
    forwarded = await client.forward_messages(BIN_CHANNEL, event.message)
    web_link = f"{STREAM_URL}/view/{forwarded.id}"
    await links_col.insert_one({"file_id": event.file.id, "file_name": event.file.name, "web_link": web_link})
    await msg.edit(f"✅ **Link Ready!**\n\n📂 `{event.file.name}`\n🔗 {web_link}", link_preview=False)

@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    await event.respond(f"👋 **Enusha Stream Bot**\n\nFile එකක් එවන්න, මම ලින්ක් එකක් දෙන්නම්.", file=LOGO_URL)

async def main():
    await client.start(bot_token=BOT_TOKEN)
    from hypercorn.asyncio import serve
    from hypercorn.config import Config
    config = Config()
    config.bind = [f"0.0.0.0:{os.environ.get('PORT', 8080)}"]
    await serve(app, config)

if __name__ == '__main__':
    asyncio.run(main())
