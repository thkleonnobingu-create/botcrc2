import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import aiohttp
import io
import re
from datetime import timedelta
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# --- 1. WEB SERVER (KEEP ALIVE) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot Leaderboard & Security System Online!"

def run_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_server)
    t.daemon = True
    t.start()

# --- 2. CONFIGURATION ---
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

DATA_FILE = "topplayers_data.json"
AUTH_FILE = "authorized_users.json"
BLACKLIST_FILE = "blacklist_data.json"
BOT_OWNER_ID = 626404653139099648 
SCP_LOGO_URL = "https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/SCP_Foundation_logo.svg/1200px-SCP_Foundation_logo.svg.png"
DECORATION_GIF = "https://cdn.discordapp.com/attachments/1327188364885102594/1443075988580995203/fixedbulletlines.gif"

# Tên các Role trong Discord phải trùng khớp chính xác với các tên này
RANK_ROLES = {
    "god": "GOD",
    "mythic": "Mythic",
    "legend": "Legend",
    "semi": "Semi Legendary"
}

# --- 3. JSON HELPERS ---
def load_json(filename):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            try: 
                data = json.load(f)
                if filename == DATA_FILE:
                    updated = False
                    for key in list(data.keys()):
                        if isinstance(data[key], list):
                            data[key] = {"players": data[key], "img_msg_id": None}
                            updated = True
                    if updated: save_json(filename, data)
                return data
            except: return {}
    return {}

def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def is_authorized(interaction: discord.Interaction):
    if interaction.user.id == BOT_OWNER_ID: return True
    auth = load_json(AUTH_FILE)
    gid = str(interaction.guild_id)
    if gid in auth:
        if interaction.user.id in auth[gid].get("users", []): return True
        u_roles = [r.id for r in interaction.user.roles]
        for rid in auth[gid].get("roles", []):
            if rid in u_roles: return True
    return False

def is_blacklisted(user_id):
    blacklist = load_json(BLACKLIST_FILE)
    return str(user_id) in blacklist

# --- 4. DATA SYNCING (Hàm quan trọng: Tự động hồi phục dữ liệu) ---
async def ensure_data_sync(interaction: discord.Interaction, data, cid):
    """
    Kiểm tra nếu dữ liệu trống thì tự động quét kênh để lấy lại.
    Trả về True nếu đã sync, False nếu không tìm thấy gì.
    """
    if cid not in data or not data[cid].get("players"):
        if cid not in data: data[cid] = {"players": [], "img_msg_id": None}
        
        scanned_players = []
        # Quét 50 tin nhắn gần nhất
        async for message in interaction.channel.history(limit=50):
            if message.author == bot.user and message.embeds:
                emb = message.embeds[0]
                if emb.title and "Rank" in emb.title:
                    try:
                        rank_match = re.search(r"Rank (\d+)", emb.title)
                        if not rank_match: continue
                        
                        rank = rank_match.group(1)
                        dname = emb.title.split(" - ")[1].strip()
                        uname = emb.description.replace("`⋆. 𐙚˚࿔ ", "").replace(" 𝜗𝜚˚⋆`", "").strip()
                        
                        # Regex an toàn hơn cho các trường
                        m_id_match = re.search(r"<@(\d+)>", emb.fields[0].value)
                        ctry_match = re.search(r"Country: (.+)", emb.fields[0].value)
                        
                        m_id = int(m_id_match.group(1)) if m_id_match else 0
                        ctry = ctry_match.group(1).split('\n')[0].strip() if ctry_match else "Unknown"

                        # Lấy metadata ẩn
                        rid = "0"
                        stg = "legend"
                        if emb.footer.text:
                            rid_match = re.search(r"RID:(\d+)", emb.footer.text)
                            stg_match = re.search(r"STG:(\w+)", emb.footer.text)
                            if rid_match: rid = rid_match.group(1)
                            if stg_match: stg = stg_match.group(1)

                        scanned_players.append({
                            "top": rank, "username": uname, "mention_id": m_id,
                            "displayname": dname, "stage": stg, "roblox_id": rid,
                            "country": ctry, "avatar_url": emb.thumbnail.url,
                            "msg_id": message.id
                        })
                    except: continue
        
        if scanned_players:
            data[cid]["players"] = scanned_players
            save_json(DATA_FILE, data)
            return True
    return False

# --- 5. ROLE MANAGEMENT ---
async def manage_roles(guild, member_id, new_stage):
    """Xóa role rank cũ và thêm role rank mới"""
    if not guild: return
    member = guild.get_member(member_id)
    if not member: return

    # Tìm các role rank trong server
    target_role_name = RANK_ROLES.get(new_stage)
    roles_to_remove = []
    role_to_add = None

    for role in guild.roles:
        if role.name == target_role_name:
            role_to_add = role
        elif role.name in RANK_ROLES.values():
            roles_to_remove.append(role)
    
    try:
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason="Leaderboard Rank Update")
        if role_to_add:
            await member.add_roles(role_to_add, reason="Leaderboard Rank Update")
    except:
        print(f"⚠️ Không thể cập nhật Role cho {member.display_name}. Kiểm tra quyền Bot.")

# --- 6. IMAGE GENERATION ---
async def create_top_player_image(players):
    canvas_w, canvas_h = 1100, 750
    bg = Image.new('RGB', (canvas_w, canvas_h), (0, 0, 0))
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(SCP_LOGO_URL) as resp:
                if resp.status == 200:
                    logo = Image.open(io.BytesIO(await resp.read())).convert("RGBA").resize((500, 500))
                    alpha = logo.getchannel('A').point(lambda i: i * 0.15)
                    logo.putalpha(alpha)
                    bg.paste(logo, (canvas_w//2 - 250, canvas_h//2 - 220), logo)
        except: pass

        draw = ImageDraw.Draw(bg)
        try: font = ImageFont.truetype("arial.ttf", 45)
        except: font = ImageFont.load_default()
        
        draw.text((canvas_w//2 - 250, 40), "TOP PLAYER SUMMARY", fill=(255, 255, 255), font=font)
        
        for i, p in enumerate(players[:10]):
            row, col = i // 5, i % 5
            x, y = 80 + (col * 200), 150 + (row * 280)
            try:
                async with session.get(p['avatar_url']) as resp:
                    if resp.status == 200:
                        avatar = Image.open(io.BytesIO(await resp.read())).convert("RGBA").resize((150, 150))
                        draw.rectangle([x-5, y-5, x+155, y+155], outline=(255, 255, 255), width=3)
                        bg.paste(avatar, (x, y), avatar)
                        draw.text((x + 30, y + 160), f"RANK {p['top']}", fill=(255, 255, 255))
            except: continue

    img_bin = io.BytesIO()
    bg.save(img_bin, format='PNG')
    img_bin.seek(0)
    return discord.File(fp=img_bin, filename="top_summary.png")

# --- 7. EMBED & BOARD LOGIC ---
def get_embed(p):
    # Emojis
    emojis = {
        "god": "<:GOD:1468846398677061714>",
        "mythic": "<:00:1465285228812701796><:10:1465285247649185944><:20:1465285263667363850><:30:1465285281404944577>",
        "legend": "<:Legend1:1465293078859612253><:Legend2:1465293093686345883><:Legend3:1465293108529856726><:Legend4:1465293122912125114>",
        "semi": "<:Semi:1468846825623523370>"
    }
    
    stg_type = p.get('stage', 'legend').lower()
    stg_icon = emojis.get(stg_type, emojis['legend'])
    
    embed = discord.Embed(title=f"Rank {p['top']} - {p['displayname']}", color=0x000000)
    embed.description = f"`⋆. 𐙚˚࿔ {p['username']} 𝜗𝜚˚⋆`"
    embed.add_field(name="════════ Information ════════", value=f"༒︎ Country: {p['country']}\n༒︎ Stage: {stg_icon}\n༒︎ Mention: <@{p['mention_id']}>", inline=False)
    embed.set_thumbnail(url=p['avatar_url'])
    embed.set_image(url=DECORATION_GIF)
    embed.set_footer(text=f"RID:{p['roblox_id']} | STG:{stg_type}")
    return embed

async def update_board(channel, cid, data, edit_mode=False):
    players = data[cid]["players"]
    players.sort(key=lambda x: int(x['top']))
    
    if edit_mode:
        for p in players:
            if "msg_id" in p:
                try:
                    msg = await channel.fetch_message(p["msg_id"])
                    await msg.edit(embed=get_embed(p))
                except: pass
        if "img_msg_id" in data[cid] and data[cid]["img_msg_id"]:
            try:
                old_img = await channel.fetch_message(data[cid]["img_msg_id"])
                await old_img.delete()
            except: pass
        if players:
            new_file = await create_top_player_image(players)
            img_msg = await channel.send(file=new_file)
            data[cid]["img_msg_id"] = img_msg.id
        save_json(DATA_FILE, data)
        return

    try: await channel.purge(limit=100, check=lambda m: not m.pinned and m.author == channel.guild.me)
    except: pass
    
    for p in players:
        msg = await channel.send(embed=get_embed(p))
        p["msg_id"] = msg.id
        
    if players:
        img_file = await create_top_player_image(players)
        img_msg = await channel.send(file=img_file)
        data[cid]["img_msg_id"] = img_msg.id
        
    save_json(DATA_FILE, data)

# --- 8. BOT COMMANDS ---
class TopBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())
    async def setup_hook(self):
        await self.tree.sync()
        print(f"✅ Bot Online: {self.user}")

bot = TopBot()

# --- STANDALONE MOD COMMANDS ---
@bot.tree.command(name="blacklist", description="Ban/Unban user")
@app_commands.describe(action="Add/Remove/Check", user="Target", reason="Reason")
@app_commands.choices(action=[app_commands.Choice(name="Add", value="add"), app_commands.Choice(name="Remove", value="remove"), app_commands.Choice(name="Check", value="check")])
async def blacklist(interaction: discord.Interaction, action: app_commands.Choice[str], user: discord.Member, reason: str = "No reason"):
    if not is_authorized(interaction): return await interaction.response.send_message("❌ Owner/Admin Only.", ephemeral=True)
    blacklist_data = load_json(BLACKLIST_FILE)
    embed = discord.Embed(color=0x000000)
    
    if action.value == "add":
        blacklist_data[str(user.id)] = {"reason": reason, "by": interaction.user.name}
        save_json(BLACKLIST_FILE, blacklist_data)
        embed.title = "🚫 Blacklisted"; embed.description = f"{user.mention} banned."
    elif action.value == "remove":
        if str(user.id) in blacklist_data: del blacklist_data[str(user.id)]
        save_json(BLACKLIST_FILE, blacklist_data)
        embed.title = "✅ Unblacklisted"; embed.description = f"{user.mention} unbanned."
    elif action.value == "check":
        status = "BANNED" if str(user.id) in blacklist_data else "CLEAN"
        embed.title = f"Status: {status}"; embed.description = f"Check for {user.mention}"
        
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="mute", description="Timeout user")
async def mute(interaction: discord.Interaction, user: discord.Member, minutes: int, reason: str = "Violation"):
    if not is_authorized(interaction): return await interaction.response.send_message("❌ Access Denied.", ephemeral=True)
    embed = discord.Embed(color=0x000000)
    try:
        await user.timeout(timedelta(minutes=minutes), reason=reason)
        embed.title = "🔇 Muted"; embed.description = f"{user.mention} for {minutes}m."
        await interaction.response.send_message(embed=embed)
    except: await interaction.response.send_message("❌ Failed.", ephemeral=True)

@bot.tree.command(name="kick", description="Kick user")
async def kick(interaction: discord.Interaction, user: discord.Member, reason: str = "Violation"):
    if not is_authorized(interaction): return await interaction.response.send_message("❌ Access Denied.", ephemeral=True)
    embed = discord.Embed(color=0x000000)
    try:
        await user.kick(reason=reason)
        embed.title = "👢 Kicked"; embed.description = f"{user.mention} kicked."
        await interaction.response.send_message(embed=embed)
    except: await interaction.response.send_message("❌ Failed.", ephemeral=True)

# --- LEADERBOARD COMMANDS ---
group = app_commands.Group(name="topplayer", description="Ranking System")

@group.command(name="added", description="Add player (Auto Syncs if empty)")
@app_commands.choices(stage=[
    app_commands.Choice(name="GOD", value="god"),
    app_commands.Choice(name="Mythic", value="mythic"),
    app_commands.Choice(name="Legend", value="legend"),
    app_commands.Choice(name="Semi Legendary", value="semi")
])
async def added(interaction: discord.Interaction, top: int, mention: discord.Member, displayname: str, stage: app_commands.Choice[str], roblox_id: str, country: str):
    if is_blacklisted(interaction.user.id): return await interaction.response.send_message("🚫 Blacklisted.", ephemeral=True)
    if not is_authorized(interaction): return await interaction.response.send_message("❌ Denied.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    
    data = load_json(DATA_FILE); cid = str(interaction.channel_id)
    # TỰ ĐỘNG SYNC DỮ LIỆU CŨ NẾU FILE TRỐNG
    await ensure_data_sync(interaction, data, cid)
    
    url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={roblox_id}&size=150x150&format=Png"
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            av = (await r.json())['data'][0]['imageUrl'] if r.status == 200 else ""
            
    entry = {"top": str(top), "username": mention.name, "mention_id": mention.id, "displayname": displayname, "stage": stage.value, "roblox_id": roblox_id, "country": country, "avatar_url": av}
    data[cid]["players"] = [p for p in data[cid]["players"] if p['top'] != str(top)]
    data[cid]["players"].append(entry)
    
    # Cập nhật Role
    await manage_roles(interaction.guild, mention.id, stage.value)
    
    await update_board(interaction.channel, cid, data)
    await interaction.followup.send("✅ Added & Synced.")

@group.command(name="edit", description="Edit Rank")
@app_commands.choices(stage=[
    app_commands.Choice(name="GOD", value="god"),
    app_commands.Choice(name="Mythic", value="mythic"),
    app_commands.Choice(name="Legend", value="legend"),
    app_commands.Choice(name="Semi Legendary", value="semi")
])
async def edit(interaction: discord.Interaction, top: int, mention: discord.Member = None, displayname: str = None, stage: app_commands.Choice[str] = None, roblox_id: str = None, country: str = None):
    if is_blacklisted(interaction.user.id): return await interaction.response.send_message("🚫 Blacklisted.", ephemeral=True)
    if not is_authorized(interaction): return await interaction.response.send_message("❌ Denied.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    
    data = load_json(DATA_FILE); cid = str(interaction.channel_id)
    await ensure_data_sync(interaction, data, cid) # Auto Sync
    
    p = next((x for x in data.get(cid, {}).get("players", []) if x['top'] == str(top)), None)
    if not p: return await interaction.followup.send("❌ Rank not found.")
    
    if mention: p["username"], p["mention_id"] = mention.name, mention.id
    if displayname: p["displayname"] = displayname
    if country: p["country"] = country
    if stage: 
        p["stage"] = stage.value
        # Cập nhật Role nếu đổi Stage
        target_uid = mention.id if mention else p["mention_id"]
        await manage_roles(interaction.guild, target_uid, stage.value)
        
    if roblox_id:
        p["roblox_id"] = roblox_id
        url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={roblox_id}&size=150x150&format=Png"
        async with aiohttp.ClientSession() as s:
            async with s.get(url) as r:
                if r.status == 200: p["avatar_url"] = (await r.json())['data'][0]['imageUrl']
                
    save_json(DATA_FILE, data)
    await update_board(interaction.channel, cid, data, edit_mode=True)
    await interaction.followup.send(f"✅ Updated Rank {top}.")

@group.command(name="move", description="Move Rank")
async def move(interaction: discord.Interaction, current_top: int, new_top: int):
    if is_blacklisted(interaction.user.id): return await interaction.response.send_message("🚫 Blacklisted.", ephemeral=True)
    if not is_authorized(interaction): return await interaction.response.send_message("❌ Denied.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    
    data = load_json(DATA_FILE); cid = str(interaction.channel_id)
    await ensure_data_sync(interaction, data, cid) # Auto Sync
    
    players = data.get(cid, {}).get("players", [])
    players.sort(key=lambda x: int(x['top']))
    src = next((i for i, p in enumerate(players) if p['top'] == str(current_top)), None)
    dst = next((i for i, p in enumerate(players) if p['top'] == str(new_top)), None)
    
    if src is not None and dst is not None:
        src_data = {k: v for k, v in players[src].items() if k not in ["top", "msg_id"]}
        if src > dst:
            for i in range(src, dst, -1):
                for k, v in {k:v for k,v in players[i-1].items() if k not in ["top","msg_id"]}.items(): players[i][k] = v
        else:
            for i in range(src, dst):
                for k, v in {k:v for k,v in players[i+1].items() if k not in ["top","msg_id"]}.items(): players[i][k] = v
        for k, v in src_data.items(): players[dst][k] = v
        save_json(DATA_FILE, data)
        await update_board(interaction.channel, cid, data, edit_mode=True)
        await interaction.followup.send(f"⏩ Moved.")
    else: await interaction.followup.send("❌ Error.")

@group.command(name="exchange", description="Swap Ranks")
async def exchange(interaction: discord.Interaction, rank1: int, rank2: int):
    if not is_authorized(interaction): return await interaction.response.send_message("❌ Denied.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    data = load_json(DATA_FILE); cid = str(interaction.channel_id)
    await ensure_data_sync(interaction, data, cid)
    
    players = data.get(cid, {}).get("players", [])
    p1 = next((p for p in players if str(p['top']) == str(rank1)), None)
    p2 = next((p for p in players if str(p['top']) == str(rank2)), None)
    if p1 and p2:
        keys = ["username", "mention_id", "displayname", "stage", "roblox_id", "country", "avatar_url"]
        for k in keys: p1[k], p2[k] = p2[k], p1[k]
        save_json(DATA_FILE, data)
        await update_board(interaction.channel, cid, data, edit_mode=True)
        await interaction.followup.send(f"🔄 Swapped.")
    else: await interaction.followup.send("❌ Not found.")

@group.command(name="remove", description="Remove Rank")
async def remove(interaction: discord.Interaction, top: int):
    if is_blacklisted(interaction.user.id): return await interaction.response.send_message("🚫 Blacklisted.", ephemeral=True)
    if not is_authorized(interaction): return await interaction.response.send_message("❌ Denied.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    data = load_json(DATA_FILE); cid = str(interaction.channel_id)
    await ensure_data_sync(interaction, data, cid) # Auto Sync
    
    if cid in data:
        data[cid]["players"] = [p for p in data[cid]["players"] if p['top'] != str(top)]
        await update_board(interaction.channel, cid, data)
        await interaction.followup.send(f"🗑️ Removed.")

@group.command(name="run", description="Manual Sync & Refresh")
async def run_cmd(interaction: discord.Interaction):
    if not is_authorized(interaction): return await interaction.response.send_message("❌ Denied.")
    await interaction.response.defer(ephemeral=True)
    data = load_json(DATA_FILE); cid = str(interaction.channel_id)
    await ensure_data_sync(interaction, data, cid) # Gọi hàm Sync
    await update_board(interaction.channel, cid, data)
    await interaction.followup.send("✅ Synced & Refreshed.")

@group.command(name="permissions", description="Grant Access")
async def permissions(interaction: discord.Interaction, role: discord.Role = None, user: discord.Member = None):
    if interaction.user.id != BOT_OWNER_ID: return await interaction.response.send_message("⚠️ Owner Only.")
    auth = load_json(AUTH_FILE); gid = str(interaction.guild_id)
    if gid not in auth: auth[gid] = {"roles": [], "users": []}
    if role: auth[gid]["roles"].append(role.id)
    if user: auth[gid]["users"].append(user.id)
    save_json(AUTH_FILE, auth)
    await interaction.response.send_message("✅ Granted.")

@group.command(name="removeperm", description="Revoke Access")
async def removeperm(interaction: discord.Interaction, role: discord.Role = None, user: discord.Member = None):
    if interaction.user.id != BOT_OWNER_ID: return await interaction.response.send_message("⚠️ Owner Only.")
    auth = load_json(AUTH_FILE); gid = str(interaction.guild_id)
    if gid in auth:
        if role and role.id in auth[gid].get("roles", []): auth[gid]["roles"].remove(role.id)
        if user and user.id in auth[gid].get("users", []): auth[gid]["users"].remove(user.id)
        save_json(AUTH_FILE, auth)
    await interaction.response.send_message("🗑️ Revoked.")

bot.tree.add_command(group)

if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)
