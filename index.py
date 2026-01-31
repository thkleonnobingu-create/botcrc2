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

# --- CẤU HÌNH WEB SERVER (GIỮ BOT CHẠY 24/7 TRÊN RENDER) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot Security & Leaderboard Online!"

def run_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_server)
    t.daemon = True
    t.start()

# --- INITIALIZATION ---
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# --- CONFIGURATION ---
DATA_FILE = "topplayers_data.json"
AUTH_FILE = "authorized_users.json"
BLACKLIST_FILE = "blacklist_data.json"
BLACKLIST_PERMS_FILE = "blacklist_perms.json" # File mới để lưu quyền blacklist
BOT_OWNER_ID = 626404653139099648 
SCP_LOGO_URL = "https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/SCP_Foundation_logo.svg/1200px-SCP_Foundation_logo.svg.png"
DECORATION_GIF = "https://cdn.discordapp.com/attachments/1327188364885102594/1443075988580995203/fixedbulletlines.gif"

# --- JSON MANAGER ---
def load_json(filename):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            try: return json.load(f)
            except: return {}
    return {}

def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

# --- PERMISSION CHECKS ---

# Check quyền cho Top Player (như cũ)
def is_topplayer_authorized(interaction: discord.Interaction):
    if interaction.user.id == BOT_OWNER_ID: return True
    auth = load_json(AUTH_FILE)
    gid = str(interaction.guild_id)
    if gid in auth:
        if interaction.user.id in auth[gid].get("users", []): return True
        u_roles = [r.id for r in interaction.user.roles]
        for rid in auth[gid].get("roles", []):
            if rid in u_roles: return True
    return False

# Check quyền cho Blacklist (MỚI)
def is_blacklist_authorized(interaction: discord.Interaction):
    if interaction.user.id == BOT_OWNER_ID: return True
    perms = load_json(BLACKLIST_PERMS_FILE)
    gid = str(interaction.guild_id)
    if gid in perms:
        if interaction.user.id in perms[gid].get("users", []): return True
        u_roles = [r.id for r in interaction.user.roles]
        for rid in perms[gid].get("roles", []):
            if rid in u_roles: return True
    return False

def is_blacklisted(user_id):
    blacklist = load_json(BLACKLIST_FILE)
    return str(user_id) in blacklist

# --- IMAGE GENERATION ---
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

# --- EMBED BUILDER ---
def get_embed(p):
    mythic = "<:00:1465285228812701796><:10:1465285247649185944><:20:1465285263667363850><:30:1465285281404944577>"
    legend = "<:Legend1:1465293078859612253><:Legend2:1465293093686345883><:Legend3:1465293108529856726><:Legend4:1465293122912125114>"
    stg_type = p.get('stage', 'legend')
    stg_icon = mythic if stg_type == 'mythic' else legend
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

# --- BOT SETUP ---
class TopBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())
    async def setup_hook(self):
        await self.tree.sync()

bot = TopBot()

# --- BLACKLIST GROUP ---
blacklist_group = app_commands.Group(name="blacklist", description="Blacklist System & Permissions")

@blacklist_group.command(name="add", description="Add user to blacklist")
@app_commands.describe(user="Target User", reason="Reason")
async def blacklist_add(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason"):
    if not is_blacklist_authorized(interaction): return await interaction.response.send_message("❌ Access Denied.", ephemeral=True)
    
    blacklist_data = load_json(BLACKLIST_FILE)
    embed = discord.Embed(color=0x000000)
    
    if str(user.id) in blacklist_data:
        embed.title = "⚠️ Already Blacklisted"
        embed.description = f"{user.mention} is already in the blacklist."
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    
    blacklist_data[str(user.id)] = {"reason": reason, "by": interaction.user.name}
    save_json(BLACKLIST_FILE, blacklist_data)
    
    embed.title = "🚫 User Blacklisted"
    embed.description = f"**User:** {user.mention}\n**Reason:** {reason}\n**By:** {interaction.user.mention}"
    await interaction.response.send_message(embed=embed, ephemeral=True)

@blacklist_group.command(name="remove", description="Remove user from blacklist (ID Support)")
@app_commands.describe(user_id="Target User ID or Mention")
async def blacklist_remove(interaction: discord.Interaction, user_id: str):
    if not is_blacklist_authorized(interaction): return await interaction.response.send_message("❌ Access Denied.", ephemeral=True)
    
    blacklist_data = load_json(BLACKLIST_FILE)
    embed = discord.Embed(color=0x000000)
    
    # Lọc lấy số từ input (hỗ trợ cả dạng <@ID> và ID thuần)
    target_id = re.sub(r"\D", "", user_id)
    
    if not target_id:
        return await interaction.response.send_message("❌ Invalid ID.", ephemeral=True)

    if target_id not in blacklist_data:
        embed.title = "⚠️ Not Blacklisted"
        embed.description = f"<@{target_id}> is not in the blacklist."
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    
    del blacklist_data[target_id]
    save_json(BLACKLIST_FILE, blacklist_data)
    
    embed.title = "✅ User Unblacklisted"
    embed.description = f"**User:** <@{target_id}>\n**Action:** Removed from blacklist."
    await interaction.response.send_message(embed=embed, ephemeral=True)

@blacklist_group.command(name="check", description="Check blacklist status")
@app_commands.describe(user="Target User")
async def blacklist_check(interaction: discord.Interaction, user: discord.Member):
    if not is_blacklist_authorized(interaction): return await interaction.response.send_message("❌ Access Denied.", ephemeral=True)

    blacklist_data = load_json(BLACKLIST_FILE)
    embed = discord.Embed(color=0x000000)
    
    if str(user.id) in blacklist_data:
        info = blacklist_data[str(user.id)]
        embed.title = "🚫 Blacklist Status: BANNED"
        embed.description = f"**User:** {user.mention}\n**Reason:** {info['reason']}\n**By:** {info['by']}"
    else:
        embed.title = "✅ Blacklist Status: CLEAN"
        embed.description = f"{user.mention} is allowed to use the bot."
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- BLACKLIST PERMISSION COMMANDS ---
@blacklist_group.command(name="permadded", description="Grant Blacklist Access (Owner Only)")
@app_commands.describe(role="Role to authorize", user="User to authorize")
async def blacklist_permadded(interaction: discord.Interaction, role: discord.Role = None, user: discord.Member = None):
    if interaction.user.id != BOT_OWNER_ID: return await interaction.response.send_message("⚠️ Owner Only.", ephemeral=True)
    
    perms = load_json(BLACKLIST_PERMS_FILE)
    gid = str(interaction.guild_id)
    if gid not in perms: perms[gid] = {"roles": [], "users": []}
    
    text = ""
    if role: 
        if role.id not in perms[gid]["roles"]:
            perms[gid]["roles"].append(role.id)
            text += f"Granted to Role: {role.mention}\n"
        else:
            text += f"Role {role.mention} already has access.\n"
            
    if user: 
        if user.id not in perms[gid]["users"]:
            perms[gid]["users"].append(user.id)
            text += f"Granted to User: {user.mention}\n"
        else:
            text += f"User {user.mention} already has access.\n"
            
    if not text: text = "Please specify a user or role."
    
    save_json(BLACKLIST_PERMS_FILE, perms)
    await interaction.response.send_message(f"✅ **Blacklist Permissions Updated:**\n{text}", ephemeral=True)

@blacklist_group.command(name="permremove", description="Revoke Blacklist Access (Owner Only)")
@app_commands.describe(role="Role to revoke", user="User to revoke")
async def blacklist_permremove(interaction: discord.Interaction, role: discord.Role = None, user: discord.Member = None):
    if interaction.user.id != BOT_OWNER_ID: return await interaction.response.send_message("⚠️ Owner Only.", ephemeral=True)
    
    perms = load_json(BLACKLIST_PERMS_FILE)
    gid = str(interaction.guild_id)
    
    if gid not in perms: return await interaction.response.send_message("❌ No permissions set for this server.", ephemeral=True)
    
    text = ""
    if role and role.id in perms[gid]["roles"]: 
        perms[gid]["roles"].remove(role.id)
        text += f"Revoked Role: {role.mention}\n"
        
    if user and user.id in perms[gid]["users"]: 
        perms[gid]["users"].remove(user.id)
        text += f"Revoked User: {user.mention}\n"
        
    if not text: text = "Nothing changed (User/Role not found in permission list)."
    
    save_json(BLACKLIST_PERMS_FILE, perms)
    await interaction.response.send_message(f"🗑️ **Blacklist Permissions Updated:**\n{text}", ephemeral=True)

bot.tree.add_command(blacklist_group)

# --- MODERATION COMMANDS ---

@bot.tree.command(name="mute", description="Timeout a user")
@app_commands.describe(user="Target User", duration="Time amount", unit="Time unit", reason="Reason")
@app_commands.choices(unit=[
    app_commands.Choice(name="Seconds", value="seconds"),
    app_commands.Choice(name="Minutes", value="minutes"),
    app_commands.Choice(name="Hours", value="hours"),
    app_commands.Choice(name="Days", value="days"),
    app_commands.Choice(name="Years", value="years")
])
async def mute(interaction: discord.Interaction, user: discord.Member, duration: int, unit: app_commands.Choice[str], reason: str = "Violation"):
    if not is_topplayer_authorized(interaction): return await interaction.response.send_message("❌ Access Denied.", ephemeral=True)
    if user.top_role >= interaction.guild.me.top_role: return await interaction.response.send_message("❌ Role too high.", ephemeral=True)

    embed = discord.Embed(color=0x000000)
    try:
        # Calculate timedelta
        unit_value = unit.value
        dt = timedelta()
        
        if unit_value == "seconds": dt = timedelta(seconds=duration)
        elif unit_value == "minutes": dt = timedelta(minutes=duration)
        elif unit_value == "hours": dt = timedelta(hours=duration)
        elif unit_value == "days": dt = timedelta(days=duration)
        elif unit_value == "years": dt = timedelta(days=duration * 365)
        
        # Discord API limit check (28 days)
        max_duration = timedelta(days=28)
        if dt > max_duration:
            dt = max_duration
            duration_str = "28 Days (Max Limit)"
        else:
            duration_str = f"{duration} {unit.name}"

        await user.timeout(dt, reason=reason)
        embed.title = "🔇 User Muted"
        embed.description = f"**User:** {user.mention}\n**Duration:** {duration_str}\n**Reason:** {reason}"
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

@bot.tree.command(name="unmute", description="Remove timeout from user")
@app_commands.describe(user="Target User", reason="Reason")
async def unmute(interaction: discord.Interaction, user: discord.Member, reason: str = "Amnesty"):
    if not is_topplayer_authorized(interaction): return await interaction.response.send_message("❌ Access Denied.", ephemeral=True)
    if user.top_role >= interaction.guild.me.top_role: return await interaction.response.send_message("❌ Role too high.", ephemeral=True)

    embed = discord.Embed(color=0x000000)
    try:
        await user.timeout(None, reason=reason)
        embed.title = "🔊 User Unmuted"
        embed.description = f"**User:** {user.mention}\n**Reason:** {reason}"
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

@bot.tree.command(name="kick", description="Kick a user")
@app_commands.describe(user="Target User", reason="Reason")
async def kick(interaction: discord.Interaction, user: discord.Member, reason: str = "Violation"):
    if not is_topplayer_authorized(interaction): return await interaction.response.send_message("❌ Access Denied.", ephemeral=True)
    if user.top_role >= interaction.guild.me.top_role: return await interaction.response.send_message("❌ Role too high.", ephemeral=True)

    embed = discord.Embed(color=0x000000)
    try:
        await user.kick(reason=reason)
        embed.title = "👢 User Kicked"
        embed.description = f"**User:** {user.mention}\n**Reason:** {reason}"
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

# --- LEADERBOARD GROUP COMMANDS ---
group = app_commands.Group(name="topplayer", description="Leaderboard System")

@group.command(name="added", description="Add player")
@app_commands.choices(stage=[app_commands.Choice(name="Legend", value="legend"), app_commands.Choice(name="Mythic", value="mythic")])
async def added(interaction: discord.Interaction, top: int, mention: discord.Member, displayname: str, stage: app_commands.Choice[str], roblox_id: str, country: str):
    if is_blacklisted(interaction.user.id): return await interaction.response.send_message("🚫 You are blacklisted.", ephemeral=True)
    if not is_topplayer_authorized(interaction): return await interaction.response.send_message("❌ Access Denied.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    data = load_json(DATA_FILE); cid = str(interaction.channel_id)
    if cid not in data: data[cid] = {"players": [], "img_msg_id": None}
    url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={roblox_id}&size=150x150&format=Png"
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            av = (await r.json())['data'][0]['imageUrl'] if r.status == 200 else ""
    entry = {"top": str(top), "username": mention.name, "mention_id": mention.id, "displayname": displayname, "stage": stage.value, "roblox_id": roblox_id, "country": country, "avatar_url": av}
    data[cid]["players"] = [p for p in data[cid]["players"] if p['top'] != str(top)]
    data[cid]["players"].append(entry)
    await update_board(interaction.channel, cid, data)
    await interaction.followup.send("✅ Player added.")

@group.command(name="run", description="Sync & Refresh")
async def run_cmd(interaction: discord.Interaction):
    if is_blacklisted(interaction.user.id): return await interaction.response.send_message("🚫 Blacklisted.", ephemeral=True)
    if not is_topplayer_authorized(interaction): return await interaction.response.send_message("❌ Access Denied.")
    await interaction.response.defer(ephemeral=True)
    cid = str(interaction.channel_id); data = load_json(DATA_FILE)
    if cid not in data: data[cid] = {"players": [], "img_msg_id": None}
    scanned = []
    async for msg in interaction.channel.history(limit=50):
        if msg.author == bot.user and msg.embeds:
            emb = msg.embeds[0]
            if emb.title and "Rank" in emb.title:
                try:
                    rank = re.search(r"Rank (\d+)", emb.title).group(1)
                    dname = emb.title.split(" - ")[1].strip()
                    uname = emb.description.replace("`⋆. 𐙚˚࿔ ", "").replace(" 𝜗𝜚˚⋆`", "").strip()
                    m_id = re.search(r"<@(\d+)>", emb.fields[0].value).group(1)
                    ctry = re.search(r"Country: (.+)", emb.fields[0].value).group(1).split('\n')[0].strip()
                    rid = re.search(r"RID:(.+) \|", emb.footer.text).group(1).strip()
                    stg = re.search(r"STG:(.+)", emb.footer.text).group(1).strip()
                    scanned.append({"top": rank, "username": uname, "mention_id": int(m_id), "displayname": dname, "stage": stg, "roblox_id": rid, "country": ctry, "avatar_url": emb.thumbnail.url, "msg_id": msg.id})
                except: continue
    if scanned: data[cid]["players"] = scanned
    players = data[cid]["players"]
    user_ids = [p["roblox_id"] for p in players if p.get("roblox_id")]
    if user_ids:
        ids_str = ",".join(user_ids)
        url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={ids_str}&size=150x150&format=Png"
        async with aiohttp.ClientSession() as s:
            async with s.get(url) as r:
                if r.status == 200:
                    results = (await r.json())['data']
                    for res in results:
                        for p in players:
                            if str(p["roblox_id"]) == str(res["targetId"]): p["avatar_url"] = res["imageUrl"]
    save_json(DATA_FILE, data)
    await update_board(interaction.channel, cid, data) 
    await interaction.followup.send("✅ Synced & Refreshed.")

@group.command(name="edit", description="Edit info")
@app_commands.choices(stage=[app_commands.Choice(name="Legend", value="legend"), app_commands.Choice(name="Mythic", value="mythic")])
async def edit(interaction: discord.Interaction, top: int, mention: discord.Member = None, displayname: str = None, stage: app_commands.Choice[str] = None, roblox_id: str = None, country: str = None):
    if is_blacklisted(interaction.user.id): return await interaction.response.send_message("🚫 Blacklisted.", ephemeral=True)
    if not is_topplayer_authorized(interaction): return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    data = load_json(DATA_FILE); cid = str(interaction.channel_id)
    p = next((x for x in data.get(cid, {}).get("players", []) if x['top'] == str(top)), None)
    if not p: return await interaction.followup.send("❌ Rank not found.")
    if mention: p["username"], p["mention_id"] = mention.name, mention.id
    if displayname: p["displayname"] = displayname
    if stage: p["stage"] = stage.value
    if country: p["country"] = country
    if roblox_id:
        p["roblox_id"] = roblox_id
        url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={roblox_id}&size=150x150&format=Png"
        async with aiohttp.ClientSession() as s:
            async with s.get(url) as r:
                if r.status == 200: p["avatar_url"] = (await r.json())['data'][0]['imageUrl']
    save_json(DATA_FILE, data)
    await update_board(interaction.channel, cid, data, edit_mode=True)
    await interaction.followup.send(f"✅ Updated Rank {top}.")

@group.command(name="exchange", description="Swap ranks")
async def exchange(interaction: discord.Interaction, rank1: int, rank2: int):
    if is_blacklisted(interaction.user.id): return await interaction.response.send_message("🚫 Blacklisted.", ephemeral=True)
    if not is_topplayer_authorized(interaction): return await interaction.response.send_message("❌ Denied.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    data = load_json(DATA_FILE); cid = str(interaction.channel_id)
    players = data.get(cid, {}).get("players", [])
    p1 = next((p for p in players if str(p['top']) == str(rank1)), None)
    p2 = next((p for p in players if str(p['top']) == str(rank2)), None)
    if p1 and p2:
        keys = ["username", "mention_id", "displayname", "stage", "roblox_id", "country", "avatar_url"]
        for k in keys: p1[k], p2[k] = p2[k], p1[k]
        save_json(DATA_FILE, data)
        await update_board(interaction.channel, cid, data, edit_mode=True)
        await interaction.followup.send(f"🔄 Swapped {rank1} & {rank2}.")
    else: await interaction.followup.send("❌ Not found.")

@group.command(name="move", description="Move rank")
async def move(interaction: discord.Interaction, current_top: int, new_top: int):
    if is_blacklisted(interaction.user.id): return await interaction.response.send_message("🚫 Blacklisted.", ephemeral=True)
    if not is_topplayer_authorized(interaction): return await interaction.response.send_message("❌ Denied.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    data = load_json(DATA_FILE); cid = str(interaction.channel_id)
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
        await interaction.followup.send(f"⏩ Moved {current_top} to {new_top}.")
    else: await interaction.followup.send("❌ Error.")

@group.command(name="remove", description="Remove rank")
async def remove(interaction: discord.Interaction, top: int):
    if is_blacklisted(interaction.user.id): return await interaction.response.send_message("🚫 Blacklisted.", ephemeral=True)
    if not is_topplayer_authorized(interaction): return await interaction.response.send_message("❌ Denied.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    data = load_json(DATA_FILE); cid = str(interaction.channel_id)
    if cid in data:
        data[cid]["players"] = [p for p in data[cid]["players"] if p['top'] != str(top)]
        await update_board(interaction.channel, cid, data)
        await interaction.followup.send(f"🗑️ Removed Rank {top}.")

@group.command(name="permissions", description="Grant Access (Top Player)")
async def permissions(interaction: discord.Interaction, role: discord.Role = None, user: discord.Member = None):
    if interaction.user.id != BOT_OWNER_ID: return await interaction.response.send_message("⚠️ Owner Only.")
    auth = load_json(AUTH_FILE); gid = str(interaction.guild_id)
    if gid not in auth: auth[gid] = {"roles": [], "users": []}
    if role: auth[gid]["roles"].append(role.id)
    if user: auth[gid]["users"].append(user.id)
    save_json(AUTH_FILE, auth)
    await interaction.response.send_message("✅ Access Granted (Top Player).")

@group.command(name="removeperm", description="Revoke Access (Top Player)")
async def removeperm(interaction: discord.Interaction, role: discord.Role = None, user: discord.Member = None):
    if interaction.user.id != BOT_OWNER_ID: return await interaction.response.send_message("⚠️ Owner Only.")
    auth = load_json(AUTH_FILE); gid = str(interaction.guild_id)
    if gid in auth:
        if role and role.id in auth[gid]["roles"]: auth[gid]["roles"].remove(role.id)
        if user and user.id in auth[gid]["users"]: auth[gid]["users"].remove(user.id)
        save_json(AUTH_FILE, auth)
    await interaction.response.send_message("🗑️ Access Revoked (Top Player).")

bot.tree.add_command(group)

if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)