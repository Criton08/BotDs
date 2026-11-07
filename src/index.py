import asyncio
import os
import random
import re
import time
from datetime import datetime, timezone

import discord
from discord import app_commands
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
    total_xp_for_level,
)
import database
from database import (
    add_mini,
    all_steam_ids,
    get_last_save,
    get_levelup_channel,
    get_mini,
    get_posizione,
    get_ruoli,
    get_ruolo_mini,
    get_xp,
    mark_dirty,
    mini_da_resettare,
    mini_inattivi,
    remove_mini,
    remove_mini_categoria,
    remove_ruolo,
    segna_messaggio_mini,
    set_levelup_channel,
    set_mini_testo,
    set_ruolo,
    set_ruolo_mini,
    set_steam_id,
    set_xp,
    top_xp,
)

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
# MINI SERVER (categoria + chat + vocale privati)
# =====================================================
def nome_mini(nome: str) -> str:
    """Nome adatto ai canali Discord: minuscolo, solo lettere, numeri e trattini."""
    return re.sub(r"[^a-z0-9]+", "-", nome.lower()).strip("-")[:40]


def permessi_mini(guild: discord.Guild, proprietario: discord.Member) -> dict:
    """Vedono solo il proprietario, il bot e gli admin (che hanno già tutto)."""
    uso = dict(view_channel=True, read_message_history=True, send_messages=True, connect=True, speak=True)
    return {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        proprietario: discord.PermissionOverwrite(**uso),
        guild.me: discord.PermissionOverwrite(manage_channels=True, manage_messages=True, **uso),
    }


async def elimina_mini(guild: discord.Guild, riga: tuple):
    """Toglie il mini server dal database ed elimina chat, vocale e categoria."""
    _, id_utente, _, id_categoria, id_testo, id_vocale = riga
    remove_mini(guild.id, id_utente)
    for id_canale in (id_testo, id_vocale, id_categoria):
        canale = guild.get_channel(id_canale)
        if canale:
            try:
                await canale.delete(reason="Mini server eliminato")
            except (discord.Forbidden, discord.HTTPException):
                print(f"Impossibile eliminare il canale {id_canale}")


async def resetta_chat(guild: discord.Guild, riga: tuple):
    """Azzera la chat clonando il canale (stessi permessi e inviti) ed eliminando il vecchio."""
    _, id_utente, nome, id_categoria, id_testo, _ = riga
    vecchio = guild.get_channel(id_testo)
    try:
        if vecchio:
            nuovo = await vecchio.clone(reason="Reset giornaliero della chat")
            await vecchio.delete(reason="Reset giornaliero della chat")
        else:  # chat eliminata a mano: la ricrea
            categoria = guild.get_channel(id_categoria)
            if categoria is None:
                remove_mini(guild.id, id_utente)
                return
            nuovo = await guild.create_text_channel(f"{nome}_chat", category=categoria,
                                                    overwrites=categoria.overwrites)
    except (discord.Forbidden, discord.HTTPException):
        print(f"Permessi mancanti: reset della chat di {nome} non riuscito")
        return
    set_mini_testo(guild.id, id_utente, nuovo.id)


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
    posizione = get_posizione(interaction.guild.id, target.id)
    embed.add_field(name="Posizione", value=f"#{posizione}" if posizione else "—")
    embed.add_field(name="Livello", value=str(level))
    embed.add_field(name="XP", value=f"{current} / {needed}")
    embed.add_field(name="XP totali", value=str(xp))
    # Ruolo di livello più alto raggiunto (non il top_role del server)
    raggiunti = [r for l, r in get_ruoli(interaction.guild.id) if l <= level]
    ruolo = interaction.guild.get_role(raggiunti[-1]) if raggiunti else None
    embed.add_field(name="Ruolo", value=ruolo.mention if ruolo else "—", inline=False)
    await interaction.response.send_message(embed=embed)


@client.tree.command(name="helprank", description="Mostra livello e XP necessari per ogni ruolo")
@app_commands.guild_only()
async def helprank(interaction: discord.Interaction):
    righe = []
    for livello, role_id in get_ruoli(interaction.guild.id):
        ruolo = interaction.guild.get_role(role_id)
        nome = ruolo.mention if ruolo else "(ruolo eliminato)"
        righe.append(f"{nome} — livello **{livello}** ({total_xp_for_level(livello):,} XP)".replace(",", "."))
    embed = discord.Embed(
        title="Ruoli e requisiti",
        description="\n".join(righe) or "Nessun ruolo configurato.",
        color=0x5865F2,
    )
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


@client.tree.command(name="setrole", description="Registra un ruolo di livello (solo admin)")
@app_commands.describe(
    ruolo="Il ruolo da assegnare",
    livello="Livello da raggiungere; vuoto = ultimo livello + 5",
)
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
async def setrole(
    interaction: discord.Interaction,
    ruolo: discord.Role,
    livello: app_commands.Range[int, 0] | None = None,
):
    try:
        usato = set_ruolo(interaction.guild.id, ruolo.id, livello)
    except ValueError:
        await interaction.response.send_message(
            f"Il livello {livello} ha già un altro ruolo.", ephemeral=True
        )
        return
    await interaction.response.send_message(
        f"{ruolo.mention} sarà assegnato al livello {usato}.", ephemeral=True
    )


@client.tree.command(name="removerole", description="Toglie un ruolo di livello (solo admin)")
@app_commands.describe(ruolo="Il ruolo da togliere dall'elenco")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
async def removerole(interaction: discord.Interaction, ruolo: discord.Role):
    if remove_ruolo(interaction.guild.id, ruolo.id):
        msg = f"{ruolo.mention} tolto dai ruoli di livello."
    else:
        msg = f"{ruolo.mention} non era registrato."
    await interaction.response.send_message(msg, ephemeral=True)


@setrole.error
@removerole.error
async def ruoli_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "Solo gli amministratori possono usarlo.", ephemeral=True
        )
    else:
        raise error


@client.tree.command(name="setminiruolo", description="Imposta il ruolo che può creare un mini server (solo admin)")
@app_commands.describe(ruolo="Ruolo autorizzato; vuoto = disattiva i mini server")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
async def setminiruolo(interaction: discord.Interaction, ruolo: discord.Role | None = None):
    set_ruolo_mini(interaction.guild.id, ruolo.id if ruolo else None)
    if ruolo:
        msg = f"Chi ha {ruolo.mention} può creare un mini server con /minicrea."
    else:
        msg = "Mini server disattivati: nessuno può crearne di nuovi."
    await interaction.response.send_message(msg, ephemeral=True)


@setminiruolo.error
async def setminiruolo_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "Solo gli amministratori possono usarlo.", ephemeral=True
        )
    else:
        raise error


@client.tree.command(name="minicrea", description="Crea il tuo mini server (chat e vocale privati)")
@app_commands.describe(nome="Nome del mini server")
@app_commands.guild_only()
async def minicrea(interaction: discord.Interaction, nome: app_commands.Range[str, 1, 40]):
    guild = interaction.guild
    ruolo_id = get_ruolo_mini(guild.id)
    if ruolo_id is None:
        await interaction.response.send_message(
            "I mini server non sono attivi: un admin deve usare /setminiruolo.", ephemeral=True
        )
        return
    autorizzato = interaction.user.guild_permissions.administrator or any(
        r.id == ruolo_id for r in interaction.user.roles
    )
    if not autorizzato:
        await interaction.response.send_message(
            f"Per creare un mini server ti serve il ruolo <@&{ruolo_id}>.", ephemeral=True
        )
        return
    if get_mini(guild.id, interaction.user.id):
        await interaction.response.send_message(
            "Hai già un mini server: eliminalo con /minielimina per crearne un altro.", ephemeral=True
        )
        return
    pulito = nome_mini(nome)
    if not pulito:
        await interaction.response.send_message(
            "Nome non valido: usa almeno una lettera o un numero.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)
    permessi = permessi_mini(guild, interaction.user)
    creati = []
    try:
        categoria = await guild.create_category(pulito, overwrites=permessi)
        creati.append(categoria)
        testo = await guild.create_text_channel(f"{pulito}_chat", category=categoria, overwrites=permessi)
        creati.append(testo)
        vocale = await guild.create_voice_channel(f"{pulito}_vocale", category=categoria, overwrites=permessi)
    except (discord.Forbidden, discord.HTTPException):
        for canale in creati:
            await canale.delete()
        await interaction.followup.send(
            "Non riesco a creare i canali: al bot serve il permesso 'Gestisci canali'.", ephemeral=True
        )
        return
    add_mini(guild.id, interaction.user.id, pulito, categoria.id, testo.id, vocale.id)
    await interaction.followup.send(
        f"Mini server creato: {testo.mention} e {vocale.mention}. "
        f"La chat si azzera ogni {MINI_RESET_ORE} ore; senza messaggi per "
        f"{MINI_INATTIVITA_GIORNI} giorni viene eliminato. Invita gli amici con /miniinvita.",
        ephemeral=True,
    )


@client.tree.command(name="miniinvita", description="Invita un utente nel tuo mini server")
@app_commands.describe(utente="L'utente che potrà vedere chat e vocale")
@app_commands.guild_only()
async def miniinvita(interaction: discord.Interaction, utente: discord.Member):
    riga = get_mini(interaction.guild.id, interaction.user.id)
    if riga is None:
        await interaction.response.send_message("Non hai un mini server.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    permesso = discord.PermissionOverwrite(
        view_channel=True, read_message_history=True, send_messages=True, connect=True, speak=True
    )
    try:
        # Le modifiche alla categoria non passano ai canali: si impostano su tutti e tre
        for id_canale in (riga[3], riga[4], riga[5]):
            canale = interaction.guild.get_channel(id_canale)
            if canale:
                await canale.set_permissions(utente, overwrite=permesso)
    except (discord.Forbidden, discord.HTTPException):
        await interaction.followup.send("Non riesco a modificare i permessi dei canali.", ephemeral=True)
        return
    await interaction.followup.send(f"{utente.mention} ora vede il tuo mini server.", ephemeral=True)


@client.tree.command(name="minirimuovi", description="Toglie l'accesso al tuo mini server a un utente")
@app_commands.describe(utente="L'utente a cui togliere l'accesso")
@app_commands.guild_only()
async def minirimuovi(interaction: discord.Interaction, utente: discord.Member):
    riga = get_mini(interaction.guild.id, interaction.user.id)
    if riga is None:
        await interaction.response.send_message("Non hai un mini server.", ephemeral=True)
        return
    if utente.id == interaction.user.id:
        await interaction.response.send_message(
            "Non puoi rimuovere te stesso: usa /minielimina.", ephemeral=True
        )
        return
    await interaction.response.defer(ephemeral=True)
    try:
        for id_canale in (riga[3], riga[4], riga[5]):
            canale = interaction.guild.get_channel(id_canale)
            if canale:
                await canale.set_permissions(utente, overwrite=None)  # None toglie il permesso dedicato
    except (discord.Forbidden, discord.HTTPException):
        await interaction.followup.send("Non riesco a modificare i permessi dei canali.", ephemeral=True)
        return
    await interaction.followup.send(f"{utente.mention} non vede più il tuo mini server.", ephemeral=True)


@client.tree.command(name="minielimina", description="Elimina il tuo mini server")
@app_commands.guild_only()
async def minielimina(interaction: discord.Interaction):
    riga = get_mini(interaction.guild.id, interaction.user.id)
    if riga is None:
        await interaction.response.send_message("Non hai un mini server.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    await elimina_mini(interaction.guild, riga)
    await interaction.followup.send("Mini server eliminato.", ephemeral=True)


@client.tree.command(name="leaderboard", description="Classifica del server (default top 10)")
@app_commands.describe(quanti="Quanti utenti mostrare (1-25, default 10)")
@app_commands.guild_only()
async def leaderboard(
    interaction: discord.Interaction, quanti: app_commands.Range[int, 1, 25] = 10
):
    # Dalla view 'classifica': primi N utenti del server per XP
    top = top_xp(interaction.guild.id, quanti)

    righe = []
    for posizione, user_id, xp in top:
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