import asyncio
import os
import random
import time
from datetime import datetime, timezone

import discord
from discord.ext import tasks

from bot import (
    COOLDOWN_SECONDS,
    MINI_INATTIVITA_GIORNI,
    MINI_RESET_ORE,
    XP_MAX,
    XP_BONUS_PER_LEVEL,
    XP_MIN,
    LevelBot,
    level_info,
)
from comandi import registra
import database
from database import (
    all_steam_ids,
    get_last_save,
    get_levelup_channel,
    get_ruoli,
    get_xp,
    mark_dirty,
    mini_da_resettare,
    mini_inattivi,
    remove_mini_categoria,
    remove_ruolo,
    segna_messaggio_mini,
    set_xp,
)
from mini import elimina_mini, resetta_chat
from steam import aggiorna_nick, steam_level


TOKEN = os.getenv("DISCORD_TOKEN")  # il token si legge dalla variabile d'ambiente

client = LevelBot()
registra(client.tree)
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
    if not gestisci_mini.is_running():
        gestisci_mini.start()

    # Recupera i messaggi arrivati dopo l'ultimo salvataggio
    ultimo = get_last_save()
    if ultimo is not None:
        da = datetime.fromtimestamp(ultimo, tz=timezone.utc)
        for guild in client.guilds:
            for channel in guild.text_channels:
                try:
                    async for msg in channel.history(limit=None, after=da, oldest_first=True):
                        await assegna_xp(msg, msg.created_at.timestamp(), annuncia=False)
                except discord.Forbidden:
                    pass  # manca "Leggi cronologia messaggi" in questo canale
    database.recupero_in_corso = False  # da ora save() può far avanzare l'orario
    mark_dirty()  # forza un commit con il nuovo orario
    print("Recupero messaggi completato")


@client.event
async def on_message(message: discord.Message):
    """Eseguito a ogni messaggio in diretta."""
    if message.guild and not message.author.bot:
        segna_messaggio_mini(message.channel.id)  # attività per l'eliminazione dopo 30 giorni
    await assegna_xp(message, time.time())


@client.event
async def on_guild_role_delete(role: discord.Role):
    """Un ruolo eliminato su Discord sparisce anche dall'elenco dei ruoli di livello."""
    remove_ruolo(role.guild.id, role.id)


@client.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    """Una categoria di mini server eliminata a mano su Discord sparisce anche dal database."""
    remove_mini_categoria(channel.id)


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

    # Chi ha lasciato il server è un 'User' senza ruoli: nel recupero dei messaggi vecchi succede
    if not isinstance(message.author, discord.Member):
        return

    # Aggiunge i ruoli sbloccati (livello 0 incluso) senza togliere quelli vecchi.
    # Controllo a ogni XP guadagnato: il ruolo base arriva al primo messaggio.
    nuovi = []
    for lvl, role_id in get_ruoli(message.guild.id):
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
# MINI SERVER (categoria + chat + vocale privati)
# =====================================================
@tasks.loop(minutes=10)
async def gestisci_mini():
    """Elimina i mini server inattivi e azzera le chat più vecchie di MINI_RESET_ORE."""
    adesso = time.time()
    for riga in mini_inattivi(adesso - MINI_INATTIVITA_GIORNI * 86400):
        guild = client.get_guild(riga[0])
        if guild:
            await elimina_mini(guild, riga)
            await asyncio.sleep(1)  # evita il rate limit
    for riga in mini_da_resettare(adesso - MINI_RESET_ORE * 3600):
        guild = client.get_guild(riga[0])
        if guild:
            await resetta_chat(guild, riga)
            await asyncio.sleep(1)


# =====================================================
# AVVIO
# =====================================================
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN non impostato in questa sessione.")
    client.run(TOKEN.strip())