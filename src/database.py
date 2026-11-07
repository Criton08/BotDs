"""Gestione del database SQLite: schema e funzioni di lettura/scrittura.
Non importa index.py né bot.py."""
import atexit
import sqlite3
import time

from discord.ext import tasks

DB_FILE = "levels.db"  # database SQLite con gli XP

'''
Tabella utente abbiamo le info di ds e steam,
Tabella server abbiamo le info del serverDs e quale è il canale levelup,
Tabella meta abbiamo l'ultimo salvataggio svolto,
Tabella xp abbiamo gli xp di ogni utente in ogni server, con chiavi esterne verso le altre due tabelle,
Tabella ruoli abbiamo i ruoli di livello di ogni server (1 server -> n ruoli), con il livello da raggiungere,
Tabella config_mini abbiamo il ruolo che può creare un mini server (1 per server, scelto dall'admin),
Tabella mini_server abbiamo i mini server (categoria + chat + vocale), al massimo uno per utente e per server.
'''

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
CREATE TABLE IF NOT EXISTS meta (
    chiave TEXT PRIMARY KEY,
    valore REAL
);
CREATE TABLE IF NOT EXISTS xp (
    id_server INTEGER NOT NULL REFERENCES server(id_server) ON DELETE CASCADE,
    id_utente INTEGER NOT NULL REFERENCES utenti(id_utente) ON DELETE CASCADE,
    xp        INTEGER NOT NULL DEFAULT 0 CHECK (xp >= 0),
    PRIMARY KEY (id_server, id_utente)
);
CREATE TABLE IF NOT EXISTS ruoli (
    id_ruolo  INTEGER PRIMARY KEY,
    id_server INTEGER NOT NULL REFERENCES server(id_server) ON DELETE CASCADE,
    livello   INTEGER NOT NULL CHECK (livello >= 0),
    UNIQUE (id_server, livello)
);
CREATE TABLE IF NOT EXISTS config_mini (
    id_server INTEGER PRIMARY KEY REFERENCES server(id_server) ON DELETE CASCADE,
    id_ruolo  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS mini_server (
    id_server        INTEGER NOT NULL REFERENCES server(id_server) ON DELETE CASCADE,
    id_utente        INTEGER NOT NULL REFERENCES utenti(id_utente) ON DELETE CASCADE,
    nome             TEXT NOT NULL,
    id_categoria     INTEGER NOT NULL,
    id_testo         INTEGER NOT NULL,
    id_vocale        INTEGER NOT NULL,
    ultimo_reset     REAL NOT NULL,  -- ultima volta che la chat è stata azzerata
    ultimo_messaggio REAL NOT NULL,  -- ultimo messaggio scritto nella chat
    PRIMARY KEY (id_server, id_utente)
);
CREATE INDEX IF NOT EXISTS idx_mini_testo ON mini_server (id_testo);
CREATE INDEX IF NOT EXISTS idx_xp_classifica ON xp (id_server, xp DESC);
CREATE VIEW IF NOT EXISTS classifica AS
SELECT id_server, id_utente, xp,
       RANK() OVER (PARTITION BY id_server ORDER BY xp DESC) AS posizione
FROM xp;
""")

dirty = False  # diventa True quando ci sono dati da salvare
recupero_in_corso = True  # True finché on_ready non ha finito di recuperare i messaggi


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


def top_xp(guild_id: int, limite: int = 10) -> list[tuple[int, int, int]]:
    """I primi utenti del server per XP: [(posizione, id_utente, xp), ...]."""
    return conn.execute("SELECT posizione, id_utente, xp FROM classifica WHERE id_server = ? "
                        "ORDER BY posizione, id_utente LIMIT ?", (guild_id, limite)).fetchall()


def get_posizione(guild_id: int, user_id: int) -> int | None:
    """Posizione in classifica dell'utente nel server (None se non ha XP)."""
    riga = conn.execute("SELECT posizione FROM classifica WHERE id_server = ? AND id_utente = ?",
                        (guild_id, user_id)).fetchone()
    return riga[0] if riga else None


def get_last_save() -> float | None:
    """Orario (epoch) dell'ultimo salvataggio (None se mai salvato)."""
    riga = conn.execute("SELECT valore FROM meta WHERE chiave = 'ultimo_salvataggio'").fetchone()
    return riga[0] if riga else None


def save():
    """Scrive l'orario del salvataggio e fa il commit, nella stessa transazione degli XP.
    Durante il recupero messaggi l'orario non avanza: un crash non fa perdere messaggi."""
    if not recupero_in_corso:
        conn.execute("INSERT INTO meta (chiave, valore) VALUES ('ultimo_salvataggio', ?) "
                     "ON CONFLICT (chiave) DO UPDATE SET valore = excluded.valore", (time.time(),))
    conn.commit()


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


def get_ruoli(guild_id: int) -> list[tuple[int, int]]:
    """Ruoli di livello del server: [(livello, id_ruolo), ...] dal livello più basso."""
    return conn.execute("SELECT livello, id_ruolo FROM ruoli WHERE id_server = ? ORDER BY livello",
                        (guild_id,)).fetchall()


def set_ruolo(guild_id: int, role_id: int, livello: int | None = None) -> int:
    """Registra il ruolo al livello dato; senza livello: ultimo livello del server + 5
    (0 se non ci sono ruoli). Se il ruolo esiste già, ne cambia il livello.
    Ritorna il livello usato. ValueError se quel livello ha già un altro ruolo."""
    _assicura(guild_id)
    if livello is None:
        riga = conn.execute("SELECT MAX(livello) FROM ruoli WHERE id_server = ? AND id_ruolo != ?",
                            (guild_id, role_id)).fetchone()
        livello = 0 if riga[0] is None else riga[0] + 5
    occupato = conn.execute("SELECT 1 FROM ruoli WHERE id_server = ? AND livello = ? AND id_ruolo != ?",
                            (guild_id, livello, role_id)).fetchone()
    if occupato:
        raise ValueError(livello)
    conn.execute("INSERT INTO ruoli (id_ruolo, id_server, livello) VALUES (?, ?, ?) "
                 "ON CONFLICT (id_ruolo) DO UPDATE SET livello = excluded.livello",
                 (role_id, guild_id, livello))
    mark_dirty()
    return livello


def remove_ruolo(guild_id: int, role_id: int) -> bool:
    """Toglie il ruolo dall'elenco. False se non era registrato."""
    cur = conn.execute("DELETE FROM ruoli WHERE id_server = ? AND id_ruolo = ?", (guild_id, role_id))
    mark_dirty()
    return cur.rowcount > 0


_COLONNE_MINI = "id_server, id_utente, nome, id_categoria, id_testo, id_vocale"


def get_ruolo_mini(guild_id: int) -> int | None:
    """Ruolo che può creare un mini server (None = non configurato)."""
    riga = conn.execute("SELECT id_ruolo FROM config_mini WHERE id_server = ?", (guild_id,)).fetchone()
    return riga[0] if riga else None


def set_ruolo_mini(guild_id: int, role_id: int | None):
    """Imposta (o con None rimuove) il ruolo che può creare un mini server."""
    if role_id is None:
        conn.execute("DELETE FROM config_mini WHERE id_server = ?", (guild_id,))
    else:
        _assicura(guild_id)
        conn.execute("INSERT INTO config_mini (id_server, id_ruolo) VALUES (?, ?) "
                     "ON CONFLICT (id_server) DO UPDATE SET id_ruolo = excluded.id_ruolo",
                     (guild_id, role_id))
    mark_dirty()


def get_mini(guild_id: int, user_id: int) -> tuple | None:
    """Mini server dell'utente: (id_server, id_utente, nome, id_categoria, id_testo, id_vocale)."""
    return conn.execute(f"SELECT {_COLONNE_MINI} FROM mini_server WHERE id_server = ? AND id_utente = ?",
                        (guild_id, user_id)).fetchone()


def add_mini(guild_id: int, user_id: int, nome: str, id_categoria: int, id_testo: int, id_vocale: int):
    """Registra un mini server appena creato."""
    _assicura(guild_id, user_id)
    adesso = time.time()
    conn.execute("INSERT INTO mini_server (id_server, id_utente, nome, id_categoria, id_testo, id_vocale, "
                 "ultimo_reset, ultimo_messaggio) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (guild_id, user_id, nome, id_categoria, id_testo, id_vocale, adesso, adesso))
    mark_dirty()


def remove_mini(guild_id: int, user_id: int):
    """Toglie il mini server dall'elenco (i canali si eliminano su Discord)."""
    conn.execute("DELETE FROM mini_server WHERE id_server = ? AND id_utente = ?", (guild_id, user_id))
    mark_dirty()


def remove_mini_categoria(id_categoria: int):
    """Toglie il mini server la cui categoria è stata eliminata su Discord."""
    cur = conn.execute("DELETE FROM mini_server WHERE id_categoria = ?", (id_categoria,))
    if cur.rowcount:
        mark_dirty()


def set_mini_testo(guild_id: int, user_id: int, id_testo: int):
    """Dopo il reset: nuovo canale chat e orario del reset."""
    conn.execute("UPDATE mini_server SET id_testo = ?, ultimo_reset = ? WHERE id_server = ? AND id_utente = ?",
                 (id_testo, time.time(), guild_id, user_id))
    mark_dirty()


def segna_messaggio_mini(id_testo: int):
    """Se il canale è la chat di un mini server, aggiorna l'ultimo messaggio."""
    cur = conn.execute("UPDATE mini_server SET ultimo_messaggio = ? WHERE id_testo = ?",
                       (time.time(), id_testo))
    if cur.rowcount:
        mark_dirty()


def mini_da_resettare(prima_di: float) -> list[tuple]:
    """Mini server con l'ultimo reset precedente a 'prima_di' (epoch)."""
    return conn.execute(f"SELECT {_COLONNE_MINI} FROM mini_server WHERE ultimo_reset < ?",
                        (prima_di,)).fetchall()


def mini_inattivi(prima_di: float) -> list[tuple]:
    """Mini server senza messaggi dopo 'prima_di' (epoch)."""
    return conn.execute(f"SELECT {_COLONNE_MINI} FROM mini_server WHERE ultimo_messaggio < ?",
                        (prima_di,)).fetchall()


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
        save()
        dirty = False


atexit.register(save)  # alla chiusura salva quello che resta
