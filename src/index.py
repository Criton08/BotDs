import asyncio
import os
import random
import re
import time

import discord
from discord import app_commands
from discord.ext import tasks

from bot import (
    COOLDOWN_SECONDS,
    XP_MAX,
    XP_BONUS_PER_LEVEL,
    XP_MIN,
    LevelBot,
    level_info,
)
from database import (
    all_steam_ids,
    get_last_seen,
    get_levelup_channel,
    get_steam_id,
    get_xp,
    set_last_seen,
    set_levelup_channel,
    set_steam_id,
    set_xp,
    top_xp,
)

from roles import LEVEL_ROLES
from steam import resolve_steam_id, steam_level

TOKEN = os.getenv("DISCORD_TOKEN")  # il token si legge dalla variabile d'ambiente

client = LevelBot()
cooldowns = {}  # (id_server, id_utente) -> orario ultimo XP guadagnato


recuperati = False  # on_ready può scattare più volte (riconnessioni)


@client.event
async def on_ready():
    global recuperati
    print(f"Online come {client.user}")
    if recuperati:
        return
    recuperati = True

    if not aggiorna_steam.is_running():
        aggiorna_steam.start()

    # Recupera i messaggi arrivati mentre il bot era spento
    for guild in client.guilds:
        for channel in guild.text_channels:
            last = get_last_seen(channel.id)
            if last is None:
                # Canale mai visto: parte da adesso, non legge lo storico
                if channel.last_message_id:
                    set_last_seen(guild.id, channel.id, channel.last_message_id)
                continue
            try:
                async for msg in channel.history(
                    limit=None, after=discord.Object(id=last), oldest_first=True
                ):
                    set_last_seen(guild.id, channel.id, msg.id)
                    await assegna_xp(msg, msg.created_at.timestamp(), annuncia=False)
            except discord.Forbidden:
                pass  # manca "Leggi cronologia messaggi" in questo canale
    print("Recupero messaggi completato")


@client.event
async def on_message(message: discord.Message):
    """Eseguito a ogni messaggio in diretta."""
    if message.guild is not None:
        set_last_seen(message.guild.id, message.channel.id, message.id)
    await assegna_xp(message, time.time())


async def assegna_xp(message: discord.Message, now: float, annuncia: bool = True):
    """Assegna XP e controlla il level up. 'now' è l'orario del messaggio."""
    # Ignora i bot e i messaggi privati
    if message.author.bot or message.guild is None:
        return

    # Controllo cooldown: evita di guadagnare XP spammando
    key = (message.guild.id, message.author.id)
    if now - cooldowns.get(key, 0) < COOLDOWN_SECONDS:
        return
    cooldowns[key] = now

    # Assegna XP casuali e ricorda il livello di prima
    xp = get_xp(message.guild.id, message.author.id)
    level_before, _, _ = level_info(xp)
    # Più sali di livello, più XP guadagni per messaggio
    moltiplicatore = 1 + XP_BONUS_PER_LEVEL * level_before
    xp += round(random.randint(XP_MIN, XP_MAX) * moltiplicatore)
    set_xp(message.guild.id, message.author.id, xp)

    # Se il livello è aumentato, annuncia
    level_after, _, _ = level_info(xp)
    if annuncia and level_after > level_before:
        # Usa il canale scelto dall'admin; se manca o è stato cancellato, quello del messaggio
        canale = message.channel
        scelto = get_levelup_channel(message.guild.id)
        if scelto:
            canale = message.guild.get_channel(scelto) or message.channel
        try:
            await canale.send(
                f"🎉 {message.author.mention} è salito al **livello {level_after}**!"
            )
        except discord.Forbidden:
            print(f"Permessi mancanti per scrivere in #{canale.name}")

    # Aggiunge i ruoli sbloccati (livello 0 incluso) senza togliere quelli vecchi.
    # Controllo a ogni XP guadagnato: il ruolo base arriva al primo messaggio.
    nuovi = []
    for lvl, role_id in LEVEL_ROLES.items():
        if level_after >= lvl:
            ruolo = message.guild.get_role(role_id)
            if ruolo and ruolo not in message.author.roles:
                nuovi.append(ruolo)
    if nuovi:
        try:
            await message.author.add_roles(*nuovi)
        except discord.Forbidden:
            print("Permessi mancanti: serve 'Gestisci ruoli' e ruolo bot più in alto")


# =====================================================
# LIVELLO STEAM NEL NICKNAME
# =====================================================
SUFFISSO_RE = re.compile(r"\s*\[Steam \d+\]$")  # riconosce un suffisso già messo da noi


async def aggiorna_nick(member: discord.Member, livello: int) -> bool:
    """Imposta 'Nome [Steam N]' (max 32 caratteri). False se mancano i permessi."""
    suffisso = f" [Steam {livello}]"
    base = SUFFISSO_RE.sub("", member.display_name)[: 32 - len(suffisso)]
    nuovo = base + suffisso
    if member.nick == nuovo:
        return True
    try:
        await member.edit(nick=nuovo)
        return True
    except discord.Forbidden:
        # Il proprietario del server non è modificabile; per gli altri serve
        # 'Gestisci nickname' e il ruolo del bot sopra quello dell'utente
        return False


@tasks.loop(hours=1)
async def aggiorna_steam():
    """Ogni ora riallinea il livello Steam nei nickname degli utenti collegati."""
    for user_id, steam_id in all_steam_ids().items():
        livello = await steam_level(steam_id)
        if livello is None:
            continue
        for guild in client.guilds:
            try:
                member = await guild.fetch_member(int(user_id))
            except (discord.NotFound, discord.HTTPException):
                continue  # utente non in questo server
            await aggiorna_nick(member, livello)
            await asyncio.sleep(1)  # evita il rate limit


# =====================================================
# COMANDI SLASH
# =====================================================
@client.tree.command(name="steam", description="Collega il tuo account Steam e mostra il livello nel nickname")
@app_commands.describe(profilo="Link al tuo profilo Steam (o il nome del link); il profilo deve essere pubblico")
@app_commands.guild_only()
async def steam(interaction: discord.Interaction, profilo: str):
    await interaction.response.defer(ephemeral=True)  # le chiamate a Steam possono essere lente
    steamid = await resolve_steam_id(profilo)
    if steamid is None:
        await interaction.followup.send(
            "Profilo non trovato: incolla il link del tuo profilo Steam.", ephemeral=True
        )
        return

    livello = await steam_level(steamid)
    if livello is None:
        await interaction.followup.send(
            "Non riesco a leggere il livello: controlla l'ID e che il profilo sia pubblico.",
            ephemeral=True,
        )
        return

    set_steam_id(interaction.user.id, steamid)
    if await aggiorna_nick(interaction.user, livello):
        await interaction.followup.send(f"Collegato! Livello Steam: {livello}.", ephemeral=True)
    else:
        await interaction.followup.send(
            f"Collegato (livello {livello}), ma non posso cambiare il tuo nickname: "
            "mancano i permessi o sei il proprietario del server.",
            ephemeral=True,
        )



@client.tree.command(name="rank", description="Mostra livello e XP")
@app_commands.describe(utente="L'utente di cui vedere il livello (opzionale)")
@app_commands.guild_only()
async def rank(interaction: discord.Interaction, utente: discord.Member | None = None):
    # Se non specifichi nessuno, mostra i dati di chi ha scritto il comando
    target = utente or interaction.user
    xp = get_xp(interaction.guild.id, target.id)
    level, current, needed = level_info(xp)

    embed = discord.Embed(color=0x5865F2)
    embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)
    embed.add_field(name="Livello", value=str(level))
    embed.add_field(name="XP", value=f"{current} / {needed}")
    embed.add_field(name="XP totali", value=str(xp))
    await interaction.response.send_message(embed=embed)


@client.tree.command(name="setlevelchannel", description="Imposta il canale dei level up (solo admin)")
@app_commands.describe(canale="Canale dove scrivere i level up; vuoto = quello del messaggio")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
async def setlevelchannel(
    interaction: discord.Interaction, canale: discord.TextChannel | None = None
):
    set_levelup_channel(interaction.guild.id, canale.id if canale else None)
    if canale:
        await interaction.response.send_message(
            f"Level up in {canale.mention}.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "Canale rimosso: i level up escono dove scrive l'utente.", ephemeral=True
        )


@setlevelchannel.error
async def setlevelchannel_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "Solo gli amministratori possono usarlo.", ephemeral=True
        )
    else:
        raise error


@client.tree.command(name="leaderboard", description="Classifica top 10 del server")
@app_commands.guild_only()
async def leaderboard(interaction: discord.Interaction):
    # Ordina gli utenti del server per XP, dal più alto, e prende i primi 10
    top = top_xp(interaction.guild.id, 10)

    righe = []
    for posizione, (user_id, xp) in enumerate(top, start=1):
        level, _, _ = level_info(xp)
        righe.append(f"**{posizione}.** <@{user_id}> — livello {level} ({xp} XP)")

    embed = discord.Embed(
        title="🏆 Classifica",
        description="\n".join(righe) or "Ancora nessun dato.",
        color=0x5865F2,
    )
    await interaction.response.send_message(embed=embed)


# =====================================================
# AVVIO
# =====================================================
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN non impostato in questa sessione.")
    client.run(TOKEN.strip())