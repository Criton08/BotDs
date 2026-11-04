import json

import discord
from discord import app_commands
from discord.ext import tasks

# =====================================================
# CONFIGURAZIONE
# =====================================================
DB_FILE = "levels.json"             # file dove vengono salvati gli XP
COOLDOWN_SECONDS = 60               # ogni utente guadagna XP al massimo 1 volta al minuto
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
