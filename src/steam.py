import os
import re

import aiohttp

STEAM_API_KEY = os.getenv("STEAM_API_KEY")  # la chiave si legge dalla variabile d'ambiente
URL_LIVELLO = "https://api.steampowered.com/IPlayerService/GetSteamLevel/v1/"


URL_VANITY = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/"
PROFILO_RE = re.compile(r"steamcommunity\.com/profiles/(\d{17})")
VANITY_RE = re.compile(r"steamcommunity\.com/id/([^/?#\s]+)")


async def resolve_steam_id(testo: str) -> str | None:
    """Accetta SteamID64, link al profilo (/profiles/... o /id/...) o nome del link personalizzato.
    Restituisce lo SteamID64, None se non riesce a trovarlo."""
    testo = testo.strip()
    if testo.isdigit() and len(testo) == 17:
        return testo
    if m := PROFILO_RE.search(testo):
        return m.group(1)
    vanity = m.group(1) if (m := VANITY_RE.search(testo)) else testo
    if not STEAM_API_KEY:
        return None
    params = {"key": STEAM_API_KEY, "vanityurl": vanity}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(URL_VANITY, params=params) as r:
                if r.status != 200:
                    return None
                data = await r.json()
    except aiohttp.ClientError:
        return None
    risposta = data.get("response", {})
    return risposta.get("steamid") if risposta.get("success") == 1 else None


async def steam_level(steamid: str) -> int | None:
    """Livello Steam dell'utente. None se profilo privato, ID errato o errore di rete."""
    if not STEAM_API_KEY:
        return None
    params = {"key": STEAM_API_KEY, "steamid": steamid}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(URL_LIVELLO, params=params) as r:
                if r.status != 200:
                    return None
                data = await r.json()
    except aiohttp.ClientError:
        return None
    return data.get("response", {}).get("player_level")
