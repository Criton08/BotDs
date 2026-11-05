# Bot leveling with message

Bot Discord con sistema di livelli e XP. Ogni messaggio dà XP, salendo di livello si ottengono ruoli.

## Comandi

| Comando | Descrizione |
|---|---|
| `/rank [utente]` | Mostra livello, XP nel livello attuale e XP totali. Senza argomento mostra i propri dati. |
| `/leaderboard` | Classifica top 10 del server per XP. |
| `/setlevelchannel [canale]` | Solo admin. Imposta il canale dei messaggi di level up. Senza argomento torna al canale dove scrive l'utente. |
| `/steam <profilo>` | Collega il tuo account Steam (incolla il link al profilo) e aggiunge il livello Steam al nickname (`Nome [Steam 42]`). |

I comandi funzionano solo dentro un server, non in privato.

## Livello Steam nel nickname

- `/steam` accetta il link al profilo (`.../profiles/<numero>` o `.../id/<nome>`), il nome del link o direttamente lo SteamID64.
- Salva il collegamento utente Discord -> SteamID64 in `levels.json` (chiave `_steam`, valida per tutti i server).
- Ogni ora il bot riallinea il livello nei nickname degli utenti collegati.
- Il profilo Steam deve essere **pubblico**.
- Il proprietario del server non può essere rinominato (limite di Discord).
- Servono la variabile `STEAM_API_KEY` (chiave da https://steamcommunity.com/dev/apikey) e, per il bot, il permesso **Gestisci nickname** con ruolo sopra quello degli utenti.

## Come si guadagna XP

- Ogni messaggio dà da **15 a 25 XP** (media 20).
- Cooldown di **30 secondi** per utente: i messaggi entro i 30 secondi non contano.
- Quindi al massimo ~40 XP al minuto, ~2400 XP all'ora di chat continua.
- I messaggi dei bot e i messaggi privati sono ignorati.
- All'avvio il bot recupera i messaggi arrivati mentre era spento (senza annunciare i level up).

## XP per livello

Per passare dal livello `L` al successivo servono `5·L² + 50·L + 100` XP.

## Livelli con ruolo

XP totali necessari per raggiungere i livelli che sbloccano un ruolo. "Minuti" è il tempo minimo stimato scrivendo un messaggio al minuto (media 20 XP).

| Livello | XP totali | Minuti circa |
|---:|---:|---:|
| 5 | 1.150 | 58 |
| 10 | 4.675 | 234 |
| 15 | 11.825 | 591 |
| 20 | 23.850 | 1.192 |
| 25 | 42.000 | 2.100 |
| 30 | 67.525 | 3.376 |
| 40 | 145.700 | 7.285 |
| 50 | 268.375 | 13.419 |
| 75 | 835.375 | 41.769 |
| 100 | 1.899.250 | 94.962 |

I ruoli sono definiti in `src/roles.py` (`LEVEL_ROLES`). I ruoli vecchi non vengono tolti: si accumulano.

