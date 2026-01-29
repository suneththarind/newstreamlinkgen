import os
import time
import logging
import urllib.parse
from telethon import TelegramClient, events
from quart import Quart, Response, request, render_template_string
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# Logging
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

# Database
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client['telegram_bot']
links_col = db['file_links']

app = Quart(__name__)
client = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# --- Web Page UI (HTML) ---
HTML_UI = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Download Center</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #0b0e11; color: #e9ecef; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .container { background: #151921; padding: 30px; border-radius: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); text-align: center; width: 90%; max-width: 400px; border: 1px solid #2d343f; }
        h2 { color: #0088cc; margin-bottom: 10px; font-size: 1.5rem; word-wrap: break-word; }
        .file-info { background: #1c212b; padding: 15px; border-radius: 10px; margin-bottom: 25px; font-size: 0.9rem; color: #adb5bd; }
        .btn { display: block; width: 100%; padding: 12px; margin: 10px 0; border-radius: 10px; text-decoration: none; font-weight: 600; transition: 0.3s; box-sizing: border-box; }
        .btn-download { background: #0088cc; color: white; border: none; }
        .btn-download:hover { background: #0072ad; transform: translateY(-2px); }
        .btn-stream { background: #e50914; color: white; }
        .btn-stream:hover { background: #b20710; transform: translateY(-2px); }
        .copy-box { margin-top: 15px; font-size: 0.8rem; color: #6c757d; cursor: pointer; text-decoration: underline; }
    </style>
</head>
<body>
    <div class="container">
        <h2>📂 File Details</h2>
        <div class="file-info">
            <strong>Name:</strong> {{ name }}<br>
            <strong>Size:</strong> {{ size }} MB<br>
            <strong>Type:</strong> {{ mime }}
        </div>
        <a href="{{ dl_link }}" class="btn btn-download">📥 Download Now</a>
        <a href="{{ st_link }}" class="btn btn-stream">🎬 Stream Online</a>
        <div class="copy-box" onclick="navigator.clipboard.writeText('{{ dl_link }}'); alert('Link Copied!');">
            Copy Direct Link to Clipboard
        </div>
    </div>
</body>
</html>
"""

async def file_generator(file_msg, start, end):
    CHUNK_SIZE = 1024 * 1024 # 1MB for speed
    async for chunk in client.iter_download(file_msg.media, offset=start, limit=(end - start + 1), request_size=CHUNK_SIZE):
        yield chunk

@app.route('/view/<int:msg_id>')
async def view_page(msg_id):
    file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
    if not file_msg or not file_msg.file: return "File Not Found", 404
    
    file_name = file_msg.file.name or f"file_{msg_id}"
    file_size = round(file_msg.file.size / (1024*1024), 2)
    mime_type = file_msg.file.mime_type or 'application/octet-stream'
    clean_name = urllib.parse.quote(file_name)
    
    dl_link = f"{STREAM_URL}/download/{msg_id}?name={clean_name}"
    st_link = f"{STREAM_URL}/watch/{msg_id}?name={clean_name}"
    
    return await render_template_string(HTML_UI, name=file_name, size=file_size, mime=mime_type, dl_link=dl_link, st_link=st_link)

@app.route('/download/<int:msg_id>')
@app.route('/watch/<int:msg_id>')
async def stream_handler(msg_id):
    try:
        file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        if not file_msg or not file_msg.file: return "Error: File missing", 404

        file_size = file_msg.file.size
        mime_type = file_msg.file.mime_type or 'application/octet-stream'
        
        range_header = request.headers.get('Range', None)
        start, end = 0, file_size - 1

        if range_header:
            parts = range_header.replace('bytes=', '').split('-')
            start = int(parts[0])
            if len(parts) > 1 and parts[1]: end = int(parts[1])

        disposition = 'inline' if 'watch' in request.path else 'attachment'
        headers = {
            'Content-Type': mime_type,
            'Accept-Ranges': 'bytes',
            'Content-Length': str(end - start + 1),
            'Content-Disposition': f'{disposition}; filename="{file_msg.file.name}"',
            'Access-Control-Allow-Origin': '*',
        }

        status = 206 if range_header else 200
        if range_header: headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'

        return Response(file_generator(file_msg, start, end), status=status, headers=headers)
    except Exception as e:
        logger.error(f"Stream Error: {e}")
        return "Internal Server Error", 500

@client.on(events.NewMessage(incoming=True, func=lambda e: e.media))
async def handle_media(event):
    file_id = event.file.id
    existing = await links_col.find_one({"file_id": file_id})
    
    if existing:
        return await event.respond(f"✅ **කලින් සකස් කළ Link එක:**\n\n🔗 {existing['web_link']}", link_preview=False)

    prog = await event.respond("🔄 Processing Your File...")
    try:
        forwarded = await client.forward_messages(BIN_CHANNEL, event.message)
        web_link = f"{STREAM_URL}/view/{forwarded.id}"
        
        res_text = (
            f"✅ **Link Ready!**\n\n"
            f"📂 **File:** `{event.file.name}`\n"
            f"🔗 **Web Link:** {web_link}\n\n"
            f"පහත ලින්ක් එකෙන් ගොස් බාගත කරගන්න."
        )
        await links_col.insert_one({"file_id": file_id, "web_link": web_link})
        await prog.edit(res_text, link_preview=False)
    except Exception as e:
        logger.error(f"Bot Error: {e}")
        await prog.edit("වැරැද්දක් සිදුවිය.")

# Ping Command
@client.on(events.NewMessage(pattern='/ping'))
async def ping(event):
    await event.respond(f"🚀 **Bot is Online!**\nLatency: Testing...")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    client.loop.create_task(app.run_task(host='0.0.0.0', port=port))
    client.run_until_disconnected()
