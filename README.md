# Bot leveling with message

Bot Discord con sistema di livelli e XP. Ogni messaggio dà XP, salendo di livello si ottengono ruoli.

## Comandi

| Comando | Descrizione |
|---|---|
| `/rank [utente]` | Mostra livello, XP nel livello attuale e XP totali. Senza argomento mostra i propri dati. |
| `/leaderboard` | Classifica top 10 del server per XP. |

I comandi funzionano solo dentro un server, non in privato.

## Come si guadagna XP

- Ogni messaggio dà da **15 a 25 XP** (media 20).
- Cooldown di **60 secondi** per utente: i messaggi entro il minuto non contano.
- Quindi al massimo ~20 XP al minuto, ~1200 XP all'ora di chat continua.
- I messaggi dei bot e i messaggi privati sono ignorati.

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

I ruoli sono definiti in `roles.py` (`LEVEL_ROLES`). I ruoli vecchi non vengono tolti: si accumulano.

