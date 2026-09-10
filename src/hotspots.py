"""
Busca sugestões de rolê ("Onde marcar") via OpenStreetMap (Nominatim para
geocodificar + Overpass API para achar lugares num raio de 5km do escritório).
100% gratuito — sem API key, sem conta, sem faturamento.

Roda todo mês dentro do pipeline (run_api), antes de renderizar o artefato.
Se a geocodificação ou a busca falharem, retorna None e o chamador mantém o
hotspots.json existente (a feature não derruba o pipeline).

Faz só 2 requisições de rede (1 geocode + 1 Overpass): o servidor público do
Overpass é compartilhado e enfileira/derruba requisições em sequência rápida
vindas do mesmo cliente, então todas as categorias vão numa única query
(múltiplos blocos `(...);out N;` na mesma consulta), em vez de uma chamada
por categoria.

O Overpass `around:5000,lat,lon` filtra corretamente por raio, mas **não**
devolve os resultados ordenados por distância — a ordem é a ordem interna do
banco dele. Por isso pedimos um pool bem maior que o necessário por
categoria (`_POOL_N`) e ordenamos localmente por distância real (haversine),
senão os 3-6 primeiros que sobrevivem ao corte do Overpass podem estar bem
na borda do círculo de 5km em vez de serem os mais pertinho. Também
recalculamos e re-filtramos a distância aqui (defensivo: a distância do
Overpass usa o centro geométrico de ways/relations, que pode ficar um pouco
fora do raio mesmo com parte do polígono dentro).

Como o OSM não tem nota/avaliação, usamos como proxy de "lugar estabelecido"
(não um cadastro vazio/abandonado no mapa) a presença de tags de contato
(`website`, `phone`, `opening_hours`, ...) — ver `_QUALITY_TAGS`. Lugares com
pelo menos um desses sinais entram primeiro (ordenados por distância entre
si); só usamos os sem nenhum sinal para completar a cota se faltar opção.
"""
from __future__ import annotations
from math import radians, sin, cos, sqrt, atan2
import urllib.parse
import requests

RADIUS_M = 5000
_POOL_N = {"restaurant": 40, "bar_pub": 25, "arts": 25}
_QUALITY_TAGS = ("website", "contact:website", "phone", "contact:phone", "opening_hours")
USER_AGENT = "small-gatherings-enter/1.0 (People team, getenter.ai)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_TIMEOUT_S = 50


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlambda / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


def _coords(el: dict) -> tuple[float, float] | None:
    """Nós têm lat/lon direto; ways/relations vêm com `center` (pedido via
    `out center`)."""
    if "lat" in el and "lon" in el:
        return el["lat"], el["lon"]
    center = el.get("center")
    if center:
        return center["lat"], center["lon"]
    return None


def _quality_score(tags: dict) -> int:
    return sum(1 for k in _QUALITY_TAGS if tags.get(k))


def _geocode(address: str) -> tuple[float, float] | None:
    r = requests.get(NOMINATIM_URL, params={"q": address, "format": "jsonv2", "limit": 1},
                     headers={"User-Agent": USER_AGENT}, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"])


def _build_query(lat: float, lon: float) -> str:
    around = f"around:{RADIUS_M},{lat},{lon}"
    # cada filtro busca por uma tag indexada (rápido). Um regex livre em
    # `name` obriga o Overpass a varrer o texto de TODO mundo na área (lento
    # e costuma dar timeout no servidor público) — por isso "Aulas" usa as
    # tags de artesanato/arte do OSM em vez de busca por nome.
    # Pedimos um pool bem maior que o exibido (`_POOL_N`) porque o Overpass
    # não ordena por distância — cortamos localmente pelos mais próximos.
    blocks = [
        (f'nwr["amenity"="restaurant"]({around});', _POOL_N["restaurant"]),
        (f'nwr["amenity"~"^(bar|pub)$"]({around});', _POOL_N["bar_pub"]),
        (
            f'nwr["amenity"="arts_centre"]({around});'
            f'nwr["craft"~"^(pottery|sculptor|scupture)$"]({around});'
            f'nwr["shop"="art"]({around});',
            _POOL_N["arts"],
        ),
    ]
    parts = [f"({stmt});out center tags {n};" for stmt, n in blocks]
    return f"[out:json][timeout:{OVERPASS_TIMEOUT_S - 10}];" + "".join(parts)


def _overpass(lat: float, lon: float) -> list[dict]:
    ql = _build_query(lat, lon)
    r = requests.post(OVERPASS_URL, data={"data": ql}, headers={"User-Agent": USER_AGENT},
                      timeout=OVERPASS_TIMEOUT_S)
    r.raise_for_status()
    data = r.json()
    return data.get("elements", [])


def _address_from_tags(tags: dict) -> str:
    street = " ".join(p for p in (tags.get("addr:street"), tags.get("addr:housenumber")) if p)
    suburb = tags.get("addr:suburb") or tags.get("addr:neighbourhood") or ""
    return ", ".join(p for p in (street, suburb) if p)


def _maps_url(name: str, area: str) -> str:
    q = urllib.parse.quote(f"{name} {area}".strip())
    return f"https://www.google.com/maps/search/?api=1&query={q}"


def _distance_label(distance_m: float) -> str:
    km = distance_m / 1000
    return f"a {km:.1f} km do escritório" if km >= 1 else f"a {int(distance_m)} m do escritório"


def _item(cat: str, el: dict) -> dict:
    tags = el.get("tags") or {}
    name = tags["name"]
    area = _address_from_tags(tags)
    note = _distance_label(el["_distance_m"])
    return {"cat": cat, "name": name, "area": area, "note": note, "maps_url": _maps_url(name, area)}


def _categorize(elements: list[dict], lat: float, lon: float) -> tuple[list, list, list]:
    """Separa os elementos vindos da query combinada em (restaurantes, bares,
    aulas), deduplicando por (type, id). Restaurantes/bares vêm da tag
    `amenity`; "aulas" vem de `amenity=arts_centre` / `craft` de
    cerâmica-escultura / `shop=art` (ateliês e centros de arte).

    Cada lugar recebe a distância real até o escritório (`_distance_m`) e um
    score de "estabelecido" (`_quality_score`, via tags de contato/horário).
    Cada categoria é ordenada com os lugares "estabelecidos" primeiro
    (mais próximos entre si primeiro) e só depois os sem nenhum sinal de
    contato — sempre dentro do raio real de `RADIUS_M`, o que o Overpass já
    filtra pelo centro, mas conferimos de novo aqui por segurança."""
    seen: set[tuple] = set()
    restaurants, bars, classes = [], [], []
    for el in elements:
        key = (el.get("type"), el.get("id"))
        tags = el.get("tags") or {}
        name = tags.get("name")
        if not name or key in seen:
            continue
        coords = _coords(el)
        if not coords:
            continue
        distance_m = _haversine_m(lat, lon, *coords)
        if distance_m > RADIUS_M:
            continue
        seen.add(key)
        el["_distance_m"] = distance_m
        el["_quality"] = _quality_score(tags)
        amenity = tags.get("amenity", "")
        if amenity == "restaurant":
            restaurants.append(el)
        elif amenity in ("bar", "pub"):
            bars.append(el)
        elif amenity == "arts_centre" or tags.get("shop") == "art" \
                or tags.get("craft") in ("pottery", "sculptor", "scupture"):
            classes.append(el)
    rank = lambda el: (0 if el["_quality"] > 0 else 1, el["_distance_m"])
    restaurants.sort(key=rank)
    bars.sort(key=rank)
    classes.sort(key=rank)
    return restaurants, bars, classes


def fetch_hotspots(office_address: str, month_label: str = "") -> dict | None:
    """Busca sugestões reais no OpenStreetMap num raio de 5km do escritório
    (almoço, jantar, barzinhos, aulas). Retorna None se a geocodificação ou a
    busca falharem (rede, timeout, servidor indisponível) ou nenhum resultado
    vier — nesses casos o chamador mantém o hotspots.json existente."""
    try:
        loc = _geocode(office_address)
        if not loc:
            return None
        elements = _overpass(*loc)
        restaurants, bars, classes = _categorize(elements, *loc)
        items = (
            [_item("Almoço", el) for el in restaurants[:3]]
            + [_item("Jantar", el) for el in restaurants[3:6]]
            + [_item("Barzinhos", el) for el in bars[:3]]
            + [_item("Aulas", el) for el in classes[:3]]
        )
    except (requests.RequestException, ValueError, KeyError):
        return None
    if not items:
        return None
    return {"month": month_label, "office_ref": office_address, "items": items}
