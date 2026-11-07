"""Comandi slash. index.py li aggiunge al bot con registra()."""
import discord
from discord import app_commands

from bot import MINI_INATTIVITA_GIORNI, MINI_RESET_ORE, level_info, total_xp_for_level
from database import (
    add_mini,
    get_levelup_channel,
    get_mini,
    get_posizione,
    get_ruoli,
    get_ruolo_mini,
    get_xp,
    remove_ruolo,
    set_levelup_channel,
    set_ruolo,
    set_ruolo_mini,
    set_steam_id,
    top_xp,
)
from mini import elimina_mini, nome_mini, permessi_mini
from steam import aggiorna_nick, resolve_steam_id, steam_level


@app_commands.command(name="steam", description="Collega il tuo account Steam e mostra il livello nel nickname")
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



@app_commands.command(name="rank", description="Mostra livello e XP")
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


@app_commands.command(name="helprank", description="Mostra livello e XP necessari per ogni ruolo")
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


@app_commands.command(name="setlevelchannel", description="Imposta il canale dei level up (solo admin)")
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


@app_commands.command(name="setrole", description="Registra un ruolo di livello (solo admin)")
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


@app_commands.command(name="removerole", description="Toglie un ruolo di livello (solo admin)")
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


@app_commands.command(name="setminiruolo", description="Imposta il ruolo che può creare un mini server (solo admin)")
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


@app_commands.command(name="minicrea", description="Crea il tuo mini server (chat e vocale privati)")
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


@app_commands.command(name="miniinvita", description="Invita un utente nel tuo mini server")
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


@app_commands.command(name="minirimuovi", description="Toglie l'accesso al tuo mini server a un utente")
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


@app_commands.command(name="minielimina", description="Elimina il tuo mini server")
@app_commands.guild_only()
async def minielimina(interaction: discord.Interaction):
    riga = get_mini(interaction.guild.id, interaction.user.id)
    if riga is None:
        await interaction.response.send_message("Non hai un mini server.", ephemeral=True)
        return
    # Si risponde prima: il comando può essere stato scritto nella chat che stiamo per eliminare
    await interaction.response.send_message("Mini server eliminato.", ephemeral=True)
    await elimina_mini(interaction.guild, riga)


@app_commands.command(name="leaderboard", description="Classifica del server (default top 10)")
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



def registra(tree: app_commands.CommandTree):
    """Aggiunge tutti i comandi all'albero dei comandi del bot."""
    for comando in (
    steam,
    rank,
    helprank,
    setlevelchannel,
    setrole,
    removerole,
    setminiruolo,
    minicrea,
    miniinvita,
    minirimuovi,
    minielimina,
    leaderboard,
    ):
        tree.add_command(comando)
