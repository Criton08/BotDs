import os
import random
import time

import discord
from discord import app_commands

from bot import (
    COOLDOWN_SECONDS,
    XP_MAX,
    XP_MIN,
    LevelBot,
    db,
    get_user,
    level_info,
    mark_dirty,
)

from roles import LEVEL_ROLES

TOKEN = os.getenv("DISCORD_TOKEN")  # il token si legge dalla variabile d'ambiente

client = LevelBot()
cooldowns = {}  # (id_server, id_utente) -> orario ultimo XP guadagnato


@client.event
async def on_ready():
    print(f"Online come {client.user}")


@client.event
async def on_message(message: discord.Message):
    """Eseguito a ogni messaggio: assegna XP e controlla il level up."""
    # Ignora i bot e i messaggi privati
    if message.author.bot or message.guild is None:
        return

    # Controllo cooldown: evita di guadagnare XP spammando
    key = (message.guild.id, message.author.id)
    now = time.time()
    if now - cooldowns.get(key, 0) < COOLDOWN_SECONDS:
        return
    cooldowns[key] = now

    # Assegna XP casuali e ricorda il livello di prima
    user = get_user(message.guild.id, message.author.id)
    level_before, _, _ = level_info(user["xp"])
    user["xp"] += random.randint(XP_MIN, XP_MAX)
    mark_dirty()

    # Se il livello è aumentato, annuncia
    level_after, _, _ = level_info(user["xp"])
    if level_after > level_before:
        await message.channel.send(
            f"🎉 {message.author.mention} è salito al **livello {level_after}**!"
        )

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
# COMANDI SLASH
# =====================================================
@client.tree.command(name="rank", description="Mostra livello e XP")
@app_commands.describe(utente="L'utente di cui vedere il livello (opzionale)")
@app_commands.guild_only()
async def rank(interaction: discord.Interaction, utente: discord.Member | None = None):
    # Se non specifichi nessuno, mostra i dati di chi ha scritto il comando
    target = utente or interaction.user
    xp = get_user(interaction.guild.id, target.id)["xp"]
    level, current, needed = level_info(xp)

    embed = discord.Embed(color=0x5865F2)
    embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)
    embed.add_field(name="Livello", value=str(level))
    embed.add_field(name="XP", value=f"{current} / {needed}")
    embed.add_field(name="XP totali", value=str(xp))
    await interaction.response.send_message(embed=embed)


@client.tree.command(name="leaderboard", description="Classifica top 10 del server")
@app_commands.guild_only()
async def leaderboard(interaction: discord.Interaction):
    # Ordina gli utenti del server per XP, dal più alto, e prende i primi 10
    users = db.get(str(interaction.guild.id), {})
    top = sorted(users.items(), key=lambda item: item[1]["xp"], reverse=True)[:10]

    righe = []
    for posizione, (user_id, data) in enumerate(top, start=1):
        level, _, _ = level_info(data["xp"])
        righe.append(f"**{posizione}.** <@{user_id}> — livello {level} ({data['xp']} XP)")

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