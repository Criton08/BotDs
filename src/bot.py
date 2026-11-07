import discord
from discord import app_commands

from database import save_loop

# =====================================================
# CONFIGURAZIONE
# =====================================================
COOLDOWN_SECONDS = 30             # ogni utente guadagna XP al massimo ogni 5 secondi
XP_MIN = 15                         # XP minimi per messaggio
XP_MAX = 25                         # XP massimi per messaggio
XP_BONUS_PER_LEVEL = 0.05           # +5% XP per messaggio per ogni livello (livello 10 = x1.5)
MINI_RESET_ORE = 24                 # ogni quante ore la chat di un mini server viene azzerata
MINI_INATTIVITA_GIORNI = 30         # senza messaggi per tanti giorni il mini server viene eliminato

# =====================================================
# FORMULA DEI LIVELLI (stile MEE6)
# =====================================================
def xp_for_level(level: int) -> int:
    """XP necessari per passare da 'level' a 'level + 1'."""
    return 5 * level**2 + 50 * level + 100


def total_xp_for_level(level: int) -> int:
    """XP totali necessari per raggiungere 'level' partendo da 0."""
    return sum(xp_for_level(l) for l in range(level))


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
