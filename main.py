import os
import asyncio
import logging
import urllib.parse
from telethon import TelegramClient, events
from quart import Quart, Response, request, render_template_string
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# --- Configs (Environment Variables) ---
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
BIN_CHANNEL = int(os.getenv('BIN_CHANNEL'))
STREAM_URL = os.getenv('STREAM_URL', '').rstrip('/')
MONGO_URI = os.getenv('MONGO_URI')
LOGO_URL = "https://image2url.com/r2/default/images/1769709206740-5b40868a-02c0-4c63-9db9-c5e68c0733b0.jpg"

# --- Database Setup ---
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client['telegram_bot']
links_col = db['file_links']

app = Quart(__name__)
client = TelegramClient('bot', API_ID, API_HASH)

# --- Deep Dark & Red Glassy UI with Search ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ name if name else "Search" }} - Enusha Streaming</title>
    <link rel="stylesheet" href="https://cdn.plyr.io/3.7.8/plyr.css" />
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600&display=swap" rel="stylesheet">
    <style>
        :root { --primary-red: #e50914; --deep-dark: #050505; }
        body { 
            font-family: 'Poppins', sans-serif; background-color: var(--deep-dark); 
            background-image: radial-gradient(circle at top right, #2a0202, transparent);
            color: #fff; margin: 0; padding: 20px; display: flex; flex-direction: column; align-items: center; min-height: 100vh;
        }
        .logo { width: 80px; height: 80px; border-radius: 50%; margin-bottom: 15px; border: 2px solid var(--primary-red); box-shadow: 0 0 15px rgba(229, 9, 20, 0.4); }
        
        /* Search Bar */
        .search-box { width: 100%; max-width: 500px; margin-bottom: 25px; }
        .search-box input { 
            width: 100%; padding: 12px 20px; border-radius: 50px; border: 1px solid rgba(255,255,255,0.1);
            background: rgba(255,255,255,0.08); color: #fff; outline: none; backdrop-filter: blur(10px); text-align: center;
        }
        .search-box input:focus { border-color: var(--primary-red); }

        .container { 
            background: rgba(255, 255, 255, 0.06); backdrop-filter: blur(15px); -webkit-backdrop-filter: blur(15px);
            padding: 25px; border-radius: 28px; width: 100%; max-width: 650px; border: 1px solid rgba(255, 255, 255, 0.1); text-align: center;
        }
        .player-wrapper { margin: 20px 0; border-radius: 18px; overflow: hidden; background: #000; border: 1px solid rgba(255, 255, 255, 0.05); }
        .plyr--full-ui.plyr--video { --plyr-color-main: var(--primary-red); }
        
        .btn-group { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 20px; }
        .btn { 
            padding: 13px; border-radius: 50px; text-decoration: none; font-weight: 600; font-size: 13px; 
            transition: 0.3s; cursor: pointer; border: none; color: #fff; backdrop-filter: blur(5px);
        }
        .btn-dl { background: rgba(229, 9, 20, 0.6); border: 1px solid rgba(255, 255, 255, 0.1); }
        .btn-cp { background: rgba(255, 255, 255, 0.12); border: 1px solid rgba(255, 255, 255, 0.05); }
        .btn-vlc { background: rgba(255, 136, 0, 0.3); grid-column: span 2; border: 1px solid rgba(255, 136, 0, 0.1); }
        .btn:hover { transform: translateY(-3px); box-shadow: 0 5px 15px rgba(229, 9, 20, 0.4); background: var(--primary-red); }
        
        h3 { margin-bottom: 5px; font-size: 17px; word-wrap: break-word; font-weight: 600; }
        .info { font-size: 11px; color: #aaa; margin-bottom: 10px; }
        
        .results-list { text-align: left; list-style: none; padding: 0; margin-top: 15px; }
        .results-list li { padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.05); transition: 0.2s; }
        .results-list li:hover { background: rgba(255,255,255,0.03); }
        .results-list a { color: #ddd; text-decoration: none; font-size: 14px; display: block; }
    </style>
</head>
<body>
    <img src="{{ logo }}" class="logo">
    
    <div class="search-box">
        <form action="/search" method="get">
            <input type="text" name="q" placeholder="Search movies or files..." autocomplete="off">
        </form>
    </div>

    <div class="container">
        {% if is_search %}
            <h3>🔍 Search Results</h3>
            <ul class="results-list">
                {% for r in results %}
                <li><a href="{{ r.web_link }}">🎬 {{ r.file_name }}</a></li>
                {% else %}
                <p style="padding: 20px;">No files found in database.</p>
                {% endfor %}
            </ul>
            <br><a href="/" class="btn btn-cp" style="display:inline-block; padding: 8px 25px;">Back to Home</a>
        {% elif name %}
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
                <button onclick="copyLink('{{ stream_link }}', this)" class="btn btn-cp">🔗 Stream Link</button>
                <a href="intent:{{ stream_link }}#Intent;package=org.videolan.vlc;end" class="btn btn-vlc">🧡 Play in VLC Player</a>
            </div>
        {% else %}
            <h3>Welcome to cinevibes.lk Stream</h3>
            <p class="info">Send a file to the bot to generate a high-speed link.</p>
        {% endif %}
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

# --- File Streaming Engine ---
async def file_generator(file_msg, start, end):
    chunk_size = 1024 * 1024 # 1MB chunks
    async for chunk in client.iter_download(file_msg.media, offset=start, limit=(end - start + 1), request_size=chunk_size):
        yield chunk

# --- Web Routes ---
@app.route('/')
async def index():
    return await render_template_string(HTML_TEMPLATE, is_search=False, name=None, logo=LOGO_URL)

@app.route('/search')
async def search_route():
    query = request.args.get('q', '')
    results = []
    if query:
        results = await links_col.find({"file_name": {"$regex": query, "$options": "i"}}).limit(20).to_list(20)
    return await render_template_string(HTML_TEMPLATE, is_search=True, results=results, logo=LOGO_URL)

@app.route('/view/<int:msg_id>')
async def view_page(msg_id):
    try:
        file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        if not file_msg or not file_msg.file: return "File Not Found", 404
        name = file_msg.file.name or "Unknown File"
        size = round(file_msg.file.size / (1024*1024), 2)
        mime = file_msg.file.mime_type or 'video/mp4'
        return await render_template_string(HTML_TEMPLATE, is_search=False, name=name, size=size, mime=mime,
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
    headers = {
        'Content-Type': file_msg.file.mime_type or 'video/mp4',
        'Accept-Ranges': 'bytes',
        'Content-Length': str(end - start + 1),
        'Content-Disposition': f'inline; filename="{file_msg.file.name}"'
    }
    if range_header: headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'
    return Response(file_generator(file_msg, start, end), status=206 if range_header else 200, headers=headers)

# --- Telegram Bot Events ---
@client.on(events.NewMessage(incoming=True, func=lambda e: e.media))
async def handle_media(event):
    file_id = event.file.id
    file_name = event.file.name or "Unknown"
    
    existing = await links_col.find_one({"file_id": file_id})
    if existing:
        return await event.respond(f"✅ **කලින් සකස් කළ Link එක:**\n\n🔗 {existing['web_link']}", link_preview=False)

    prog = await event.respond("🔄 **පොඩ්ඩක් ඉන්න, ලින්ක් එක හදනවා...**")
    try:
        forwarded = await client.forward_messages(BIN_CHANNEL, event.message)
        web_link = f"{STREAM_URL}/view/{forwarded.id}"
        
        # Save to DB for Search
        await links_col.insert_one({
            "file_id": file_id, 
            "file_name": file_name, 
            "web_link": web_link
        })
        
        await prog.edit(f"✅ **සූදානම්!**\n\n📂 `{file_name}`\n🔗 {web_link}", link_preview=False)
    except Exception as e:
        await prog.edit(f"❌ දෝෂයක් සිදු වුණා: {str(e)}")

@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    await event.respond(f"👋 **CINEVIBES.LK Stream Bot වෙත සාදරයෙන් පිළිගනිමු!**\n\nඕනෑම File එකක් එවන්න, මම ඔබට High-Speed Link එකක් ලබා දෙන්නම්.", file=LOGO_URL)

# --- Execution ---
async def main():
    await client.start(bot_token=BOT_TOKEN)
    logger.info("Bot & Web Server Starting...")
    from hypercorn.asyncio import serve
    from hypercorn.config import Config
    config = Config()
    config.bind = [f"0.0.0.0:{os.environ.get('PORT', 8080)}"]
    await serve(app, config)

if __name__ == '__main__':
    asyncio.run(main())
