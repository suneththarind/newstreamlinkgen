import os
import asyncio
import logging
import time
import psutil
from datetime import datetime
from telethon import TelegramClient, events
from quart import Quart, Response, request, render_template_string, redirect, url_for, session
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
ADMIN_PASSWORD = "Menushabaduwa" # ඔයා දීපු පාස්වර්ඩ් එක
START_TIME = time.time()

# --- Database ---
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client['telegram_bot']
links_col = db['file_links']

app = Quart(__name__)
app.secret_key = "cinecloud_secret_key_123" # Session ආරක්ෂා කිරීමට
client = TelegramClient('bot', API_ID, API_HASH)

# --- Full UI Template ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} - CineCloud</title>
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
        .search-box { width: 100%; max-width: 500px; margin-bottom: 25px; display: {{ 'block' if show_search else 'none' }}; }
        .search-box input, .login-input { 
            width: 100%; padding: 12px 20px; border-radius: 50px; border: 1px solid rgba(255,255,255,0.1);
            background: rgba(255,255,255,0.08); color: #fff; outline: none; backdrop-filter: blur(10px); text-align: center; margin-bottom: 10px;
        }
        .container { 
            background: rgba(255, 255, 255, 0.06); backdrop-filter: blur(15px); -webkit-backdrop-filter: blur(15px);
            padding: 30px; border-radius: 30px; width: 100%; max-width: 650px; border: 1px solid rgba(255, 255, 255, 0.1); text-align: center;
        }
        .home-msg { font-weight: 800; font-size: 26px; text-shadow: 0 0 20px var(--primary-red); margin: 60px 0; }
        .admin-card { display: flex; justify-content: space-around; flex-wrap: wrap; gap: 15px; margin-top: 20px; }
        .stat-box { background: rgba(255,255,255,0.05); padding: 20px; border-radius: 20px; border: 1px solid rgba(229, 9, 20, 0.2); min-width: 130px; }
        .stat-box h2 { color: var(--primary-red); margin: 0; font-size: 22px; }
        .btn { padding: 13px 30px; border-radius: 50px; text-decoration: none; font-weight: 600; font-size: 13px; transition: 0.3s; cursor: pointer; border: none; color: #fff; background: var(--primary-red); display: inline-block; }
    </style>
</head>
<body>
    <img src="{{ logo }}" class="logo">
    <div class="search-box">
        <form action="/search" method="get"><input type="text" name="q" placeholder="Search Movies..." autocomplete="off"></form>
    </div>
    <div class="container">
        {% if is_login %}
            <h2 style="color:var(--primary-red)">🔐 Admin Login</h2>
            <form method="post">
                <input type="password" name="password" class="login-input" placeholder="Enter Admin Password" required>
                <button type="submit" class="btn">Login</button>
            </form>
            {% if error %}<p style="color: red; font-size: 12px; margin-top: 10px;">{{ error }}</p>{% endif %}
        {% elif is_admin %}
            <h2 style="color:var(--primary-red)">🚀 Admin Dashboard</h2>
            <div class="admin-card">
                <div class="stat-box"><h2>{{ total_files }}</h2><p>Files</p></div>
                <div class="stat-box"><h2>{{ ping }}ms</h2><p>Ping</p></div>
                <div class="stat-box"><h2>{{ cpu }}%</h2><p>CPU</p></div>
                <div class="stat-box"><h2>{{ ram }}%</h2><p>RAM</p></div>
            </div>
            <p style="font-size:12px; margin-top:20px;">Uptime: {{ uptime }}</p>
            <br><a href="/logout" style="color:#888; text-decoration:none; font-size:12px;">Logout</a>
        {% elif is_search %}
            <h3 style="color:var(--primary-red)">🔍 Results</h3>
            {% for r in results %}
                <div style="padding: 10px; border-bottom: 1px solid rgba(255,255,255,0.05); text-align: left;">
                    <a href="{{ r.web_link }}" style="color:#ddd; text-decoration:none;">🎬 {{ r.file_name }}</a>
                </div>
            {% else %}<p>No results.</p>{% endfor %}
            <br><a href="/" class="btn" style="background:rgba(255,255,255,0.1)">Home</a>
        {% elif name %}
            <h3>{{ name }}</h3>
            <div style="margin:20px 0; border-radius:18px; overflow:hidden; background:#000;">
                <video id="player" playsinline controls><source src="{{ stream_link }}" type="video/mp4"></video>
            </div>
            <a href="{{ dl_link }}" class="btn">Download Now</a>
        {% else %}
            <div class="home-msg">CINECLOUD IS ONLINE</div>
        {% endif %}
    </div>
    <script src="https://cdn.plyr.io/3.7.8/plyr.js"></script><script>const player = new Plyr('#player');</script>
</body>
</html>
"""

# --- Admin Routes ---
@app.route('/admin', methods=['GET', 'POST'])
async def admin_panel():
    error = None
    if request.method == 'POST':
        form = await request.form
        if form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin_panel'))
        error = "❌ Wrong Password!"

    if not session.get('logged_in'):
        return await render_template_string(HTML_TEMPLATE, title="Login", is_login=True, error=error, show_search=False, logo=LOGO_URL)

    total_files = await links_col.count_documents({})
    start_ping = time.time()
    await links_col.find_one()
    ping = round((time.time() - start_ping) * 1000)
    uptime = str(datetime.now() - datetime.fromtimestamp(START_TIME)).split('.')[0]
    
    return await render_template_string(HTML_TEMPLATE, title="Admin", is_admin=True, total_files=total_files, ping=ping, cpu=psutil.cpu_percent(), ram=psutil.virtual_memory().percent, uptime=uptime, show_search=False, logo=LOGO_URL)

@app.route('/logout')
async def logout():
    session.pop('logged_in', None)
    return redirect(url_for('index'))

# --- Existing Routes ---
@app.route('/')
async def index():
    return await render_template_string(HTML_TEMPLATE, title="Home", show_search=False, name=None, logo=LOGO_URL)

@app.route('/search')
async def search_route():
    query = request.args.get('q', '')
    results = await links_col.find({"file_name": {"$regex": query, "$options": "i"}}).limit(20).to_list(20) if query else []
    return await render_template_string(HTML_TEMPLATE, title="Search", is_search=True, results=results, show_search=True, logo=LOGO_URL)

@app.route('/view/<int:msg_id>')
async def view_page(msg_id):
    file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
    name = file_msg.file.name or "Unknown File"
    return await render_template_string(HTML_TEMPLATE, title=name, name=name, show_search=True,
                                        dl_link=f"{STREAM_URL}/download/{msg_id}", stream_link=f"{STREAM_URL}/watch/{msg_id}", logo=LOGO_URL)

# --- Streaming Engine ---
@app.route('/download/<int:msg_id>')
@app.route('/watch/<int:msg_id>')
async def stream_handler(msg_id):
    file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
    headers = {'Content-Type': 'video/mp4', 'Accept-Ranges': 'bytes', 'Content-Length': str(file_msg.file.size), 'Content-Disposition': f'inline; filename="{file_msg.file.name}"'}
    async def file_generator():
        async for chunk in client.iter_download(file_msg.media, chunk_size=1024*1024): yield chunk
    return Response(file_generator(), headers=headers)

# --- Bot Handlers ---
@client.on(events.NewMessage(incoming=True, func=lambda e: e.media))
async def handle_media(event):
    forwarded = await client.forward_messages(BIN_CHANNEL, event.message)
    web_link = f"{STREAM_URL}/view/{forwarded.id}"
    await links_col.insert_one({"file_name": event.file.name, "web_link": web_link})
    await event.respond(f"✅ Link: {web_link}", link_preview=False)

async def main():
    await client.start(bot_token=BOT_TOKEN)
    from hypercorn.asyncio import serve
    from hypercorn.config import Config
    config = Config()
    config.bind = [f"0.0.0.0:{os.environ.get('PORT', 8080)}"]
    await serve(app, config)

if __name__ == '__main__':
    asyncio.run(main())
