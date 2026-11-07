"""Funzioni di supporto dei mini server: nomi, permessi, eliminazione e reset della chat.
Non importa index.py né comandi.py."""
import re

import discord

from database import remove_mini, set_mini_testo


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
