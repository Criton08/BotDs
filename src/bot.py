import json

import discord
from discord import app_commands
from discord.ext import tasks

# =====================================================
# CONFIGURAZIONE
# =====================================================
DB_FILE = "levels.json"             # file dove vengono salvati gli XP
COOLDOWN_SECONDS = 30             # ogni utente guadagna XP al massimo ogni 5 secondi
XP_MIN = 15                         # XP minimi per messaggio
XP_MAX = 25                         # XP massimi per messaggio

# =====================================================
# DATABASE (semplice file JSON)
# Struttura: db[id_server][id_utente] = {"xp": numero}
# =====================================================
try:
    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    db = {}

dirty = False  # diventa True quando ci sono dati da salvare


def mark_dirty():
    """Segnala che ci sono dati da salvare al prossimo giro di save_loop."""
    global dirty
    dirty = True


def get_user(guild_id: int, user_id: int) -> dict:
    """Restituisce i dati dell'utente, creandoli se non esistono.
    Le chiavi JSON devono essere stringhe, quindi converto gli ID."""
    guild = db.setdefault(str(guild_id), {})
    return guild.setdefault(str(user_id), {"xp": 0}) #viene restituito un dizionario


def get_last_seen(channel_id: int) -> int | None:
    """ID dell'ultimo messaggio letto in un canale (None se mai visto).
    Salvato sotto la chiave riservata "_last_seen", separata dai server."""
    return db.get("_last_seen", {}).get(str(channel_id))


def set_last_seen(channel_id: int, message_id: int):
    """Ricorda l'ultimo messaggio letto; il file lo scrive save_loop."""
    db.setdefault("_last_seen", {})[str(channel_id)] = message_id
    mark_dirty()


def get_levelup_channel(guild_id: int) -> int | None:
    """ID del canale scelto per i level up (None = canale del messaggio).
    Chiave riservata "_levelup_channel", separata dai server."""
    return db.get("_levelup_channel", {}).get(str(guild_id))


def set_levelup_channel(guild_id: int, channel_id: int | None):
    """Imposta (o con None rimuove) il canale dei level up."""
    cfg = db.setdefault("_levelup_channel", {})
    if channel_id is None:
        cfg.pop(str(guild_id), None)
    else:
        cfg[str(guild_id)] = channel_id
    mark_dirty()


def get_steam_id(user_id: int) -> str | None:
    """SteamID64 collegato all'utente Discord (None se non collegato).
    Chiave riservata "_steam", valida per tutti i server."""
    return db.get("_steam", {}).get(str(user_id))


def set_steam_id(user_id: int, steam_id: str):
    """Collega un SteamID64 all'utente Discord."""
    db.setdefault("_steam", {})[str(user_id)] = steam_id
    mark_dirty()


def all_steam_ids() -> dict:
    """Copia di tutti i collegamenti {id_utente: steamid}."""
    return dict(db.get("_steam", {}))


@tasks.loop(seconds=10)
async def save_loop():
    """Ogni 10 secondi salva su file, ma solo se qualcosa è cambiato."""
    global dirty
    if dirty:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f)
        dirty = False


# =====================================================
# FORMULA DEI LIVELLI (stile MEE6)
# =====================================================
def xp_for_level(level: int) -> int:
    """XP necessari per passare da 'level' a 'level + 1'."""
    return 5 * level**2 + 50 * level + 100


def level_info(total_xp: int):
    """Dagli XP totali calcola (livello, xp nel livello attuale, xp necessari al prossimo)."""
    level = 0
    remaining = total_xp
    while remaining >= xp_for_level(level):
        remaining -= xp_for_level(level)
        level += 1
    return level, remaining, xp_for_level(level)


# =====================================================
# BOT
# =====================================================
class LevelBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # serve anche l'opzione attiva nel portale developer
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)  # contenitore dei comandi slash

    async def setup_hook(self):
        """Eseguito una volta all'avvio: registra i comandi e avvia il salvataggio."""
        await self.tree.sync()  # i comandi globali possono impiegare qualche minuto ad apparire
        save_loop.start()
