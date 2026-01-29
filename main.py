import os
import time
import logging
import urllib.parse
from telethon import TelegramClient, events
from quart import Quart, Response, request, render_template_string
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Config
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
BIN_CHANNEL = int(os.getenv('BIN_CHANNEL'))
STREAM_URL = os.getenv('STREAM_URL').rstrip('/')
MONGO_URI = os.getenv('MONGO_URI')

db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client['telegram_bot']
links_col = db['file_links']

app = Quart(__name__)
client = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# HTML Template (Landing Page)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Download File</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: sans-serif; background: #0f0f0f; color: white; text-align: center; padding: 50px; }
        .card { background: #1e1e1e; padding: 20px; border-radius: 15px; display: inline-block; max-width: 90%; }
        .btn { display: block; padding: 15px 25px; margin: 10px; border-radius: 8px; text-decoration: none; font-weight: bold; cursor: pointer; }
        .dl { background: #0088cc; color: white; }
        .st { background: #e50914; color: white; }
        .cp { background: #333; color: #bbb; font-size: 12px; }
    </style>
</head>
<body>
    <div class="card">
        <h3>📂 {{ file_name }}</h3>
        <p>Size: {{ file_size }} MB</p>
        <hr>
        <a href="{{ dl_link }}" class="btn dl">📥 Direct Download</a>
        <a href="{{ watch_link }}" class="btn st">🎬 Stream Online</a>
        <button onclick="copyToClipboard('{{ dl_link }}')" class="btn cp">📋 Copy Download Link</button>
    </div>
    <script>
        function copyToClipboard(text) {
            navigator.clipboard.writeText(text);
            alert("Link Copied!");
        }
    </script>
</body>
</html>
"""

# --- Optimized Generator ---
async def file_generator(file_msg, start, end):
    CHUNK_SIZE = 1024 * 1024 
    async for chunk in client.iter_download(file_msg.media, offset=start, limit=(end - start + 1), request_size=CHUNK_SIZE):
        yield chunk

# Web View Route
@app.route('/view/<int:msg_id>')
async def view_page(msg_id):
    file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
    if not file_msg or not file_msg.file: return "File Not Found", 404
    
    file_name = file_msg.file.name or "Unknown File"
    file_size = round(file_msg.file.size / (1024*1024), 2)
    clean_name = urllib.parse.quote(file_name)
    
    dl_link = f"{STREAM_URL}/download/{msg_id}?name={clean_name}"
    watch_link = f"{STREAM_URL}/watch/{msg_id}?name={clean_name}"
    
    return await render_template_string(HTML_TEMPLATE, file_name=file_name, file_size=file_size, dl_link=dl_link, watch_link=watch_link)

@app.route('/download/<int:msg_id>')
@app.route('/watch/<int:msg_id>')
async def stream_handler(msg_id):
    try:
        file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        if not file_msg or not file_msg.file: return "Not Found", 404

        file_size = file_msg.file.size
        mime_type = file_msg.file.mime_type or 'application/octet-stream'
        
        range_header = request.headers.get('Range', None)
        start_byte, end_byte = 0, file_size - 1

        if range_header:
            range_parts = range_header.replace('bytes=', '').split('-')
            start_byte = int(range_parts[0])
            if len(range_parts) > 1 and range_parts[1]: end_byte = int(range_parts[1])

        disposition = 'inline' if 'watch' in request.path else 'attachment'
        headers = {
            'Content-Type': mime_type,
            'Accept-Ranges': 'bytes',
            'Content-Length': str(end_byte - start_byte + 1),
            'Content-Disposition': f'{disposition}; filename="{file_msg.file.name}"',
        }

        status = 206 if range_header else 200
        if range_header: headers['Content-Range'] = f'bytes {start_byte}-{end_byte}/{file_size}'

        return Response(file_generator(file_msg, start_byte, end_byte), status=status, headers=headers)
    except Exception as e:
        return str(e), 500

# --- Bot Events ---
@client.on(events.NewMessage(incoming=True, func=lambda e: e.media))
async def handle_media(event):
    file_id = event.file.id
    existing = await links_col.find_one({"file_id": file_id})
    
    if existing:
        return await event.respond(f"✅ **කලින් සකස් කළ Link එක:**\n\n🔗 {existing['web_link']}", link_preview=False)

    prog = await event.respond("🔄 Processing...")
    try:
        forwarded = await client.forward_messages(BIN_CHANNEL, event.message)
        web_link = f"{STREAM_URL}/view/{forwarded.id}"
        
        res_text = f"📂 **File:** `{event.file.name}`\n\n🔗 **Web Link:** {web_link}"
        await links_col.insert_one({"file_id": file_id, "web_link": web_link})
        await prog.edit(res_text, link_preview=False)
    except Exception as e:
        await prog.edit(f"Error: {e}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
