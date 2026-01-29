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

# --- Final UI Upgrade ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CineCloud - Streaming</title>
    <link rel="stylesheet" href="https://cdn.plyr.io/3.7.8/plyr.css" />
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;800&display=swap" rel="stylesheet">
    <style>
        :root { --primary-red: #e50914; --deep-dark: #050505; }
        body { 
            font-family: 'Poppins', sans-serif; background-color: var(--deep-dark); 
            background-image: radial-gradient(circle at top right, #2a0202, transparent);
            color: #fff; margin: 0; padding: 20px; display: flex; flex-direction: column; align-items: center; min-height: 100vh;
        }
        .logo { width: 85px; height: 85px; border-radius: 50%; margin-bottom: 20px; border: 2px solid var(--primary-red); box-shadow: 0 0 20px rgba(229, 9, 20, 0.5); }
        
        /* Search Bar - Hidden on Home */
        .search-box { width: 100%; max-width: 500px; margin-bottom: 25px; display: {{ 'block' if show_search else 'none' }}; }
        .search-box input { 
            width: 100%; padding: 12px 20px; border-radius: 50px; border: 1px solid rgba(255,255,255,0.1);
            background: rgba(255,255,255,0.08); color: #fff; outline: none; backdrop-filter: blur(10px); text-align: center;
        }

        .container { 
            background: rgba(255, 255, 255, 0.06); backdrop-filter: blur(15px); -webkit-backdrop-filter: blur(15px);
            padding: 30px; border-radius: 30px; width: 100%; max-width: 650px; border: 1px solid rgba(255, 255, 255, 0.1); text-align: center;
        }

        /* Glowing Home Message */
        .home-msg { 
            font-weight: 800; font-size: 26px; color: #fff; text-transform: uppercase; letter-spacing: 3px;
            text-shadow: 0 0 10px var(--primary-red), 0 0 25px var(--primary-red), 0 0 40px var(--primary-red);
            margin: 60px 0;
        }

        .player-wrapper { margin: 20px 0; border-radius: 18px; overflow: hidden; background: #000; border: 1px solid rgba(255, 255, 255, 0.05); }
        .btn-group { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 20px; }
        .btn { padding: 13px; border-radius: 50px; text-decoration: none; font-weight: 600; font-size: 13px; transition: 0.3s; cursor: pointer; border: none; color: #fff; backdrop-filter: blur(5px); }
        .btn-dl { background: rgba(229, 9, 20, 0.65); border: 1px solid rgba(255, 255, 255, 0.1); }
        .btn-cp { background: rgba(255, 255, 255, 0.12); border: 1px solid rgba(255, 255, 255, 0.05); }
        .btn-vlc { background: rgba(255, 136, 0, 0.35); grid-column: span 2; border: 1px solid rgba(255, 136, 0, 0.1); }
        .btn:hover { transform: translateY(-3px); box-shadow: 0 5px 15px rgba(229, 9, 20, 0.4); background: var(--primary-red); }
        
        .results-list { text-align: left; list-style: none; padding: 0; margin-top: 15px; }
        .results-list li { padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.05); transition: 0.2s; }
        .results-list a { color: #ddd; text-decoration: none; font-size: 14px; display: block; }
    </style>
</head>
<body>
    <img src="{{ logo }}" class="logo">
    
    <div class="search-box">
        <form action="/search" method="get">
            <input type="text" name="q" placeholder="Search Movies & Files..." autocomplete="off">
        </form>
    </div>

    <div class="container">
        {% if is_search %}
            <h3 style="color:var(--primary-red)">🔍 Search Results</h3>
            <ul class="results-list">
                {% for r in results %}
                <li><a href="{{ r.web_link }}">🎬 {{ r.file_name }}</a></li>
                {% else %}
                <p>No results found.</p>
                {% endfor %}
            </ul>
            <br><a href="/" class="btn btn-cp" style="display:inline-block; padding: 10px 30px;">Back Home</a>
        {% elif name %}
            <h3 style="margin-bottom:5px;">{{ name }}</h3>
            <div style="font-size:11px; color:#aaa; margin-bottom:15px;">{{ size }} MB • {{ mime }}</div>
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
            <div class="home-msg">CINECLOUD IS ONLINE</div>
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

# --- Streaming Engine ---
async def file_generator(file_msg, start, end):
    chunk_size = 1024 * 1024
    async for chunk in client.iter_download(file_msg.media, offset=start, limit=(end - start + 1), request_size=chunk_size):
        yield chunk

# --- Web Routes ---
@app.route('/')
async def index():
    # Home එකේ සර්ච් එක පෙන්නන්නේ නැහැ
    return await render_template_string(HTML_TEMPLATE, is_search=False, name=None, show_search=False, logo=LOGO_URL)

@app.route('/search')
async def search_route():
    query = request.args.get('q', '')
    results = []
    if query:
        results = await links_col.find({"file_name": {"$regex": query, "$options": "i"}}).limit(20).to_list(20)
    # සර්ච් එකේදී සර්ච් බාර් එක පෙන්නනවා
    return await render_template_string(HTML_TEMPLATE, is_search=True, results=results, show_search=True, logo=LOGO_URL)

@app.route('/view/<int:msg_id>')
async def view_page(msg_id):
    try:
        file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        name = file_msg.file.name or "Unknown File"
        size = round(file_msg.file.size / (1024*1024), 2)
        mime = file_msg.file.mime_type or 'video/mp4'
        # වීඩියෝ පේජ් එකේදී සර්ච් බාර් එක පෙන්නනවා
        return await render_template_string(HTML_TEMPLATE, is_search=False, name=name, size=size, mime=mime, show_search=True,
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
    file_id = event.file.id
    file_name = event.file.name or "Unknown"
    existing = await links_col.find_one({"file_id": file_id})
    if existing: return await event.respond(f"✅ **Link:** {existing['web_link']}", link_preview=False)
    
    msg = await event.respond("🔄 Generating Link...")
    forwarded = await client.forward_messages(BIN_CHANNEL, event.message)
    web_link = f"{STREAM_URL}/view/{forwarded.id}"
    await links_col.insert_one({"file_id": file_id, "file_name": file_name, "web_link": web_link})
    await msg.edit(f"✅ **Done:** {web_link}", link_preview=False)

@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    await event.respond("CineCloud Is Ready!", file=LOGO_URL)

async def main():
    await client.start(bot_token=BOT_TOKEN)
    from hypercorn.asyncio import serve
    from hypercorn.config import Config
    config = Config()
    config.bind = [f"0.0.0.0:{os.environ.get('PORT', 8080)}"]
    await serve(app, config)

if __name__ == '__main__':
    asyncio.run(main())
