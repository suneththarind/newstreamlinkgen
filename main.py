import os
import asyncio
import logging
import urllib.parse
from telethon import TelegramClient, events
from quart import Quart, Response, request, render_template_string
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# --- Configurations ---
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
BIN_CHANNEL = int(os.getenv('BIN_CHANNEL'))
STREAM_URL = os.getenv('STREAM_URL').rstrip('/')
MONGO_URI = os.getenv('MONGO_URI')
LOGO_URL = "https://image2url.com/r2/default/images/1769709206740-5b40868a-02c0-4c63-9db9-c5e68c0733b0.jpg"

db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client['telegram_bot']
links_col = db['file_links']

app = Quart(__name__)
client = TelegramClient('bot', API_ID, API_HASH)

# --- Optimized HTML with Player & Search ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ name }} - Enusha Streaming</title>
    <link rel="stylesheet" href="https://cdn.plyr.io/3.7.8/plyr.css" />
    <style>
        body { font-family: 'Poppins', sans-serif; background: #080a0d; color: #fff; margin: 0; padding: 20px; display: flex; flex-direction: column; align-items: center; }
        .logo { width: 120px; border-radius: 50%; margin-bottom: 20px; border: 2px solid #0088cc; }
        .search-container { margin-bottom: 30px; width: 100%; max-width: 500px; }
        .search-input { width: 100%; padding: 12px; border-radius: 25px; border: none; background: #1a1e26; color: #fff; outline: none; text-align: center; border: 1px solid #333; }
        .container { background: #12161f; padding: 25px; border-radius: 15px; width: 100%; max-width: 700px; border: 1px solid #1e2530; text-align: center; }
        .player-wrapper { margin: 20px 0; border-radius: 10px; overflow: hidden; background: #000; }
        .btn-group { display: flex; gap: 10px; justify-content: center; margin-top: 20px; flex-wrap: wrap; }
        .btn { padding: 12px 25px; border-radius: 8px; text-decoration: none; font-weight: bold; font-size: 14px; transition: 0.3s; cursor: pointer; border: none; }
        .btn-dl { background: #0088cc; color: #fff; }
        .btn-cp { background: #333; color: #ccc; }
        h3 { margin-bottom: 5px; color: #0088cc; font-size: 18px; }
        p { font-size: 13px; color: #888; }
    </style>
</head>
<body>
    <img src="{{ logo }}" class="logo">
    
    <div class="search-container">
        <form action="/search" method="get">
            <input type="text" name="q" class="search-input" placeholder="Search previously hosted files...">
        </form>
    </div>

    <div class="container">
        <h3>📂 {{ name }}</h3>
        <p>Size: {{ size }} MB | Type: {{ mime }}</p>

        {% if is_video %}
        <div class="player-wrapper">
            <video id="player" playsinline controls data-poster="{{ logo }}">
                <source src="{{ stream_link }}" type="{{ mime }}" />
            </video>
        </div>
        {% endif %}

        <div class="btn-group">
            <a href="{{ dl_link }}" class="btn btn-dl">📥 Download Now</a>
            <button onclick="copyToClipboard('{{ dl_link }}')" class="btn btn-cp">📋 Copy Link</button>
        </div>
    </div>

    <script src="https://cdn.plyr.io/3.7.8/plyr.js"></script>
    <script>
        const player = new Plyr('#player');
        function copyToClipboard(text) {
            navigator.clipboard.writeText(text);
            alert("Download link copied to clipboard!");
        }
    </script>
</body>
</html>
"""

# --- Speed Optimized Generator ---
async def file_generator(file_msg, start, end):
    # Chunk size set to 1MB for parallel requests and faster seeking
    chunk_size = 1024 * 1024 
    async for chunk in client.iter_download(
        file_msg.media, 
        offset=start, 
        limit=(end - start + 1), 
        request_size=chunk_size
    ):
        yield chunk

@app.route('/view/<int:msg_id>')
async def view_page(msg_id):
    file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
    if not file_msg or not file_msg.file: return "File Not Found", 404
    
    name = file_msg.file.name or "Unknown File"
    size = round(file_msg.file.size / (1024*1024), 2)
    mime = file_msg.file.mime_type or 'application/octet-stream'
    is_video = 'video' in mime or 'mp4' in name.lower() or 'mkv' in name.lower()
    
    dl_link = f"{STREAM_URL}/download/{msg_id}"
    stream_link = f"{STREAM_URL}/watch/{msg_id}"
    
    return await render_template_string(HTML_TEMPLATE, name=name, size=size, mime=mime, is_video=is_video, dl_link=dl_link, stream_link=stream_link, logo=LOGO_URL)

@app.route('/search')
async def search_files():
    query = request.args.get('q', '')
    if not query: return "Please enter a search term"
    results = await links_col.find({"file_name": {"$regex": query, "$options": "i"}}).limit(10).to_list(10)
    
    res_html = "<h2>Search Results</h2><ul>"
    for r in results:
        res_html += f"<li><a href='{r['web_link']}' style='color:#0088cc;'>{r['file_name']}</a></li>"
    res_html += "</ul><br><a href='/' style='color:#fff;'>Back</a>"
    return res_html

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
        'Content-Type': file_msg.file.mime_type or 'application/octet-stream',
        'Accept-Ranges': 'bytes',
        'Content-Length': str(end - start + 1),
        'Content-Disposition': f'inline; filename="{file_msg.file.name}"',
        'Access-Control-Allow-Origin': '*',
    }

    status = 206 if range_header else 200
    if range_header: headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'

    return Response(file_generator(file_msg, start, end), status=status, headers=headers)

# --- Bot Handler ---
@client.on(events.NewMessage(incoming=True, func=lambda e: e.media))
async def handle_media(event):
    file_id = event.file.id
    file_name = event.file.name or "Unknown"
    
    existing = await links_col.find_one({"file_id": file_id})
    if existing:
        return await event.respond(f"✅ **කලින් සකස් කළ Link එක:**\n\n🔗 {existing.get('web_link')}", link_preview=False)

    prog = await event.respond("⚡ **Processing at High Speed...**")
    forwarded = await client.forward_messages(BIN_CHANNEL, event.message)
    web_link = f"{STREAM_URL}/view/{forwarded.id}"
    
    # Save file name for search feature
    await links_col.insert_one({"file_id": file_id, "file_name": file_name, "web_link": web_link})
    
    await prog.delete()
    await event.respond(
        f"✅ **Link Generated!**\n\n📂 **Name:** `{file_name}`\n🔗 **Web Link:** {web_link}\n\n🎬 වීඩියෝව නැරඹීමට හෝ බාගත කිරීමට ඉහත ලින්ක් එක භාවිතා කරන්න.",
        thumb=LOGO_URL
    )

@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    await event.respond(f"👋 **Enusha Stream Bot** වෙත සාදරයෙන් පිළිගනිමු!\n\nඕනෑම ගොනුවක් එවන්න, මම ඔබට High-Speed Web Player එකක් සමඟ Link එකක් ලබා දෙන්නම්.", file=LOGO_URL)

async def main():
    await client.start(bot_token=BOT_TOKEN)
    from hypercorn.asyncio import serve
    from hypercorn.config import Config
    config = Config()
    config.bind = [f"0.0.0.0:{os.environ.get('PORT', 8080)}"]
    await serve(app, config)

if __name__ == '__main__':
    asyncio.run(main())
