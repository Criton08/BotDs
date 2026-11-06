# Bot leveling with message

Bot Discord con sistema di livelli e XP. Ogni messaggio dà XP, salendo di livello si ottengono ruoli.

## Comandi

| Comando | Descrizione |
|---|---|
| `/rank [utente]` | Mostra posizione in classifica, livello, XP nel livello attuale e XP totali. Senza argomento mostra i propri dati. |
| `/leaderboard [quanti]` | Classifica del server per XP: `quanti` utenti (1-25), default 10. |
| `/setlevelchannel [canale]` | Solo admin. Imposta il canale dei messaggi di level up. Senza argomento torna al canale dove scrive l'utente. |
| `/steam <profilo>` | Collega il tuo account Steam (incolla il link al profilo) e aggiunge il livello Steam al nickname (`Nome [Steam 42]`). |

I comandi funzionano solo dentro un server, non in privato.

## Livello Steam nel nickname

- `/steam` accetta il link al profilo (`.../profiles/<numero>` o `.../id/<nome>`), il nome del link o direttamente lo SteamID64.
- Salva il collegamento utente Discord -> SteamID64 nella tabella `utenti` del database (valido per tutti i server).
- Ogni ora il bot riallinea il livello nei nickname degli utenti collegati.
- Il profilo Steam deve essere **pubblico**.
- Il proprietario del server non può essere rinominato (limite di Discord).
- Servono la variabile `STEAM_API_KEY` (chiave da https://steamcommunity.com/dev/apikey) e, per il bot, il permesso **Gestisci nickname** con ruolo sopra quello degli utenti.

## Come si guadagna XP

- Ogni messaggio dà da **15 a 25 XP** (media 20) al livello 0.
- Bonus del **+5% per ogni livello** (`XP_BONUS_PER_LEVEL` in `src/bot.py`): al livello 10 gli XP sono x1.5, al livello 20 x2.
- Cooldown di **30 secondi** per utente: i messaggi entro i 30 secondi non contano.
- Quindi al massimo ~40 XP al minuto, ~2400 XP all'ora di chat continua.
- I messaggi dei bot e i messaggi privati sono ignorati.
- All'avvio il bot recupera i messaggi arrivati mentre era spento (senza annunciare i level up).

## Database

SQLite, file `levels.db` creato all'avvio nella cartella da cui lanci il bot (lancialo dalla radice del progetto). Il codice sta in `src/database.py`. Il salvataggio avviene ogni 10 secondi. Tabelle:

| Tabella | Contenuto |
|---|---|
| `utenti` | `id_utente`, `steam`: dati globali dell'utente |
| `server` | `id_server`, `canale_levelup` |
| `meta` | `chiave`, `valore` (`ultimo_salvataggio`: orario per recuperare i messaggi persi) |
| `xp` | `id_server`, `id_utente`, `xp`: XP dell'utente in quel server |
| `classifica` (view) | `id_server`, `id_utente`, `xp`, `posizione`: `RANK()` per server, usata da `/rank` e `/leaderboard` |

`levels.db` è nel `.gitignore`: contiene dati degli utenti, non va committato.

## XP per livello

Per passare dal livello `L` al successivo servono `5·L² + 50·L + 100` XP.

## Livelli con ruolo

XP totali necessari per raggiungere i livelli che sbloccano un ruolo. "Minuti" è il tempo minimo stimato scrivendo un messaggio al minuto (media 20 XP al livello 0, con il bonus per livello).

| Livello | XP totali | Minuti circa |
|---:|---:|---:|
| 5 | 1.150 | 51 |
| 10 | 4.675 | 180 |
| 15 | 11.825 | 403 |
| 20 | 23.850 | 726 |
| 25 | 42.000 | 1.157 |
| 30 | 67.525 | 1.700 |
| 40 | 145.700 | 3.127 |
| 50 | 268.375 | 5.023 |
| 75 | 835.375 | 11.861 |
| 100 | 1.899.250 | 21.744 |

I ruoli sono definiti in `src/roles.py` (`LEVEL_ROLES`). I ruoli vecchi non vengono tolti: si accumulano.

