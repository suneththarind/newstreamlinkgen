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
client = TelegramClient('bot', API_ID, API_HASH)

# HTML UI - තව ටිකක් ලස්සන කළා
HTML_UI = """
<!DOCTYPE html>
<html lang="si">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Download Center</title>
    <style>
        body { font-family: 'Segoe UI', sans-serif; background: #0b0e11; color: white; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .card { background: #151921; padding: 30px; border-radius: 20px; text-align: center; width: 90%; max-width: 400px; border: 1px solid #2d343f; }
        .btn { display: block; padding: 15px; margin: 10px 0; border-radius: 10px; text-decoration: none; font-weight: bold; transition: 0.3s; }
        .btn-dl { background: #0088cc; color: white; }
        .btn-st { background: #e50914; color: white; }
        .btn:hover { opacity: 0.8; transform: scale(1.02); }
    </style>
</head>
<body>
    <div class="card">
        <h2>📂 File Details</h2>
        <p><strong>Name:</strong> {{ name }}<br><strong>Size:</strong> {{ size }} MB</p>
        <hr style="border: 0.5px solid #2d343f;">
        <a href="{{ dl_link }}" class="btn btn-dl">📥 Direct Download</a>
        <a href="{{ st_link }}" class="btn btn-st">🎬 Online Stream</a>
    </div>
</body>
</html>
"""

async def file_generator(file_msg, start, end):
    CHUNK_SIZE = 1024 * 1024
    async for chunk in client.iter_download(file_msg.media, offset=start, limit=(end - start + 1), request_size=CHUNK_SIZE):
        yield chunk

@app.route('/view/<int:msg_id>')
async def view_page(msg_id):
    try:
        file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        if not file_msg or not file_msg.file: return "File Not Found", 404
        file_name = file_msg.file.name or "Unknown File"
        file_size = round(file_msg.file.size / (1024*1024), 2)
        clean_name = urllib.parse.quote(file_name)
        dl_link = f"{STREAM_URL}/download/{msg_id}?name={clean_name}"
        st_link = f"{STREAM_URL}/watch/{msg_id}?name={clean_name}"
        return await render_template_string(HTML_UI, name=file_name, size=file_size, dl_link=dl_link, st_link=st_link)
    except Exception as e: return str(e), 500

@app.route('/download/<int:msg_id>')
@app.route('/watch/<int:msg_id>')
async def stream_handler(msg_id):
    try:
        file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        file_size = file_msg.file.size
        mime_type = file_msg.file.mime_type or 'application/octet-stream'
        disposition = 'inline' if 'watch' in request.path else 'attachment'
        headers = {
            'Content-Type': mime_type,
            'Accept-Ranges': 'bytes',
            'Content-Length': str(file_size),
            'Content-Disposition': f'{disposition}; filename="{file_msg.file.name}"',
        }
        return Response(file_generator(file_msg, 0, file_size-1), headers=headers)
    except Exception as e: return str(e), 500

@client.on(events.NewMessage(incoming=True, func=lambda e: e.media))
async def handle_media(event):
    file_id = event.file.id
    existing = await links_col.find_one({"file_id": file_id})
    
    # පරණ දත්ත තිබුණත් Error නොවී වැඩ කිරීමට fix එක මෙන්න:
    if existing:
        link = existing.get('web_link') or existing.get('text') or "Link not found"
        return await event.respond(f"✅ **කලින් සකස් කළ Link එක:**\n\n🔗 {link}", link_preview=False)

    prog = await event.respond("🔄 Processing...")
    try:
        forwarded = await client.forward_messages(BIN_CHANNEL, event.message)
        web_link = f"{STREAM_URL}/view/{forwarded.id}"
        await links_col.insert_one({"file_id": file_id, "web_link": web_link})
        await prog.edit(f"✅ **Link Ready!**\n\n🔗 {web_link}", link_preview=False)
    except Exception as e:
        logger.error(f"Error: {e}")
        await prog.edit("Error processing file.")

@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    await event.respond("බොට් වැඩ! ඕනෑම File එකක් එවන්න. 🚀")

async def main():
    await client.start(bot_token=BOT_TOKEN)
    from hypercorn.asyncio import serve
    from hypercorn.config import Config
    config = Config()
    config.bind = [f"0.0.0.0:{os.environ.get('PORT', 8080)}"]
    await serve(app, config)

if __name__ == '__main__':
    asyncio.run(main())
