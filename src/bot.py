import atexit
import sqlite3

import discord
from discord import app_commands
from discord.ext import tasks

# =====================================================
# CONFIGURAZIONE
# =====================================================
DB_FILE = "levels.db"               # database SQLite con gli XP
COOLDOWN_SECONDS = 30             # ogni utente guadagna XP al massimo ogni 5 secondi
XP_MIN = 15                         # XP minimi per messaggio
XP_MAX = 25                         # XP massimi per messaggio
XP_BONUS_PER_LEVEL = 0.05           # +5% XP per messaggio per ogni livello (livello 10 = x1.5)

# =====================================================
# DATABASE (SQLite, schema normalizzato con chiavi esterne)
#   utenti(id_utente PK, steam)                  un utente, una riga (dati globali)
#   server(id_server PK, canale_levelup)         un server, una riga
#   canali(id_canale PK, id_server FK, ultimo_messaggio)
#   xp(id_server FK, id_utente FK, xp)           PK (id_server, id_utente)
# Le scritture restano in una transazione; save_loop fa il commit ogni 10 s.
# =====================================================
conn = sqlite3.connect(DB_FILE)
conn.execute("PRAGMA foreign_keys = ON")  # in SQLite le chiavi esterne vanno attivate
conn.executescript("""
CREATE TABLE IF NOT EXISTS utenti (
    id_utente INTEGER PRIMARY KEY,
    steam     TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS server (
    id_server      INTEGER PRIMARY KEY,
    canale_levelup INTEGER
);
CREATE TABLE IF NOT EXISTS canali (
    id_canale        INTEGER PRIMARY KEY,
    id_server        INTEGER NOT NULL REFERENCES server(id_server) ON DELETE CASCADE,
    ultimo_messaggio INTEGER
);
CREATE TABLE IF NOT EXISTS xp (
    id_server INTEGER NOT NULL REFERENCES server(id_server) ON DELETE CASCADE,
    id_utente INTEGER NOT NULL REFERENCES utenti(id_utente) ON DELETE CASCADE,
    xp        INTEGER NOT NULL DEFAULT 0 CHECK (xp >= 0),
    PRIMARY KEY (id_server, id_utente)
);
CREATE INDEX IF NOT EXISTS idx_xp_classifica ON xp (id_server, xp DESC);
""")

dirty = False  # diventa True quando ci sono dati da salvare


def mark_dirty():
    """Segnala che ci sono dati da salvare al prossimo giro di save_loop."""
    global dirty
    dirty = True


def _assicura(guild_id: int, user_id: int | None = None):
    """Crea le righe padre (server, utente) se mancano, così le chiavi esterne reggono."""
    conn.execute("INSERT OR IGNORE INTO server (id_server) VALUES (?)", (guild_id,))
    if user_id is not None:
        conn.execute("INSERT OR IGNORE INTO utenti (id_utente) VALUES (?)", (user_id,))


def get_xp(guild_id: int, user_id: int) -> int:
    """XP dell'utente in questo server (0 se mai visto)."""
    riga = conn.execute("SELECT xp FROM xp WHERE id_server = ? AND id_utente = ?",
                        (guild_id, user_id)).fetchone()
    return riga[0] if riga else 0


def set_xp(guild_id: int, user_id: int, xp: int):
    """Imposta gli XP; il commit lo fa save_loop."""
    _assicura(guild_id, user_id)
    conn.execute("INSERT INTO xp (id_server, id_utente, xp) VALUES (?, ?, ?) "
                 "ON CONFLICT (id_server, id_utente) DO UPDATE SET xp = excluded.xp",
                 (guild_id, user_id, xp))
    mark_dirty()


def top_xp(guild_id: int, limite: int = 10) -> list[tuple[int, int]]:
    """I primi utenti del server per XP: [(id_utente, xp), ...]."""
    return conn.execute("SELECT id_utente, xp FROM xp WHERE id_server = ? "
                        "ORDER BY xp DESC LIMIT ?", (guild_id, limite)).fetchall()


def get_last_seen(channel_id: int) -> int | None:
    """ID dell'ultimo messaggio letto in un canale (None se mai visto)."""
    riga = conn.execute("SELECT ultimo_messaggio FROM canali WHERE id_canale = ?",
                        (channel_id,)).fetchone()
    return riga[0] if riga else None


def set_last_seen(guild_id: int, channel_id: int, message_id: int):
    """Ricorda l'ultimo messaggio letto in un canale del server."""
    _assicura(guild_id)
    conn.execute("INSERT INTO canali (id_canale, id_server, ultimo_messaggio) VALUES (?, ?, ?) "
                 "ON CONFLICT (id_canale) DO UPDATE SET ultimo_messaggio = excluded.ultimo_messaggio",
                 (channel_id, guild_id, message_id))
    mark_dirty()


def get_levelup_channel(guild_id: int) -> int | None:
    """ID del canale scelto per i level up (None = canale del messaggio)."""
    riga = conn.execute("SELECT canale_levelup FROM server WHERE id_server = ?",
                        (guild_id,)).fetchone()
    return riga[0] if riga else None


def set_levelup_channel(guild_id: int, channel_id: int | None):
    """Imposta (o con None rimuove) il canale dei level up."""
    _assicura(guild_id)
    conn.execute("UPDATE server SET canale_levelup = ? WHERE id_server = ?", (channel_id, guild_id))
    mark_dirty()


def get_steam_id(user_id: int) -> str | None:
    """SteamID64 collegato all'utente Discord (None se non collegato)."""
    riga = conn.execute("SELECT steam FROM utenti WHERE id_utente = ?", (user_id,)).fetchone()
    return riga[0] if riga else None


def set_steam_id(user_id: int, steam_id: str):
    """Collega un SteamID64 all'utente Discord."""
    conn.execute("INSERT INTO utenti (id_utente, steam) VALUES (?, ?) "
                 "ON CONFLICT (id_utente) DO UPDATE SET steam = excluded.steam",
                 (user_id, steam_id))
    mark_dirty()


def all_steam_ids() -> dict:
    """Tutti i collegamenti {id_utente: steamid}."""
    righe = conn.execute("SELECT id_utente, steam FROM utenti WHERE steam IS NOT NULL").fetchall()
    return dict(righe)


@tasks.loop(seconds=10)
async def save_loop():
    """Ogni 10 secondi fa il commit, ma solo se qualcosa è cambiato."""
    global dirty
    if dirty:
        conn.commit()
        dirty = False


atexit.register(conn.commit)  # alla chiusura salva quello che resta


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
