# Il bestemmiatore — bot Discord livelli/XP

## Stack e versione
- Python 3.11.5
- discord.py 2.7.1 (`discord.Client` + `app_commands`, non `commands.Bot`)
- Database: file JSON locale (`levels.json`), nessuna libreria extra

## Struttura cartelle
- `index.py`: entry point. Crea `client`, eventi (`on_ready`, `on_message`), comandi slash (`/rank`, `/leaderboard`), avvio.
- `bot.py`: classe `LevelBot`, config (XP, cooldown, `DB_FILE`), DB (`db`, `get_user`, `mark_dirty`, `save_loop`), formula livelli (`xp_for_level`, `level_info`).
- `roles.py`: `LEVEL_ROLES`, dizionario livello -> ID ruolo Discord.
- `levels.json`: creato a runtime, relativo alla cartella di lancio. Non versionare.

## Come si avvia
```
set DISCORD_TOKEN=<token>      # PowerShell: $env:DISCORD_TOKEN="<token>"
python index.py
```
Lanciare da questa cartella, altrimenti `levels.json` finisce altrove.
Nel portale developer serve attiva l'opzione **Message Content Intent**.

## Convenzioni
- Commenti e testi utente in italiano.
- Chiavi JSON sempre stringhe: converti gli ID con `str()` (vedi `get_user`).
- Stato condiviso (`dirty`) si modifica solo tramite `mark_dirty()`, mai da `index.py` direttamente.
- Ruoli assegnati con `>=` sul livello, così si recuperano ruoli saltati. I vecchi ruoli non si tolgono.
- Nuovi comandi slash: `@client.tree.command` in `index.py`, con `@app_commands.guild_only()`.

## Cosa non bisogna fare
- Non scrivere il token nel codice né committarlo: solo variabile d'ambiente `DISCORD_TOKEN`.
- Non committare `levels.json` (dati utenti).
- Non scrivere su `levels.json` a ogni messaggio: il salvataggio passa da `save_loop` ogni 10 s.
- Non fare import circolari: `bot.py` e `roles.py` non importano `index.py`.
- Il ruolo del bot deve stare sopra i ruoli di `LEVEL_ROLES` e avere **Gestisci ruoli**, altrimenti `Forbidden`.
