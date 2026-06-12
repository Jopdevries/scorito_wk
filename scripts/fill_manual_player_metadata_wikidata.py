from __future__ import annotations

import asyncio
import csv
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote_plus
from typing import Any, cast

from scorito_wk_odds_optimizer.cloak_browser import browser_session

INPUT_PATH = Path("input/manual_player_metadata.csv")
SOURCE_PATH = Path("output/topscorer_recommendations.csv")

PREFERRED_DESC = (
    "footballer",
    "association football player",
    "football player",
)

POSITION_MAP = {
    "goalkeeper": "GK",
    "keeper": "GK",
    "defender": "DEF",
    "centre-back": "DEF",
    "centre back": "DEF",
    "full-back": "DEF",
    "full back": "DEF",
    "left-back": "DEF",
    "right-back": "DEF",
    "wing-back": "DEF",
    "wing back": "DEF",
    "midfielder": "MID",
    "defensive midfielder": "MID",
    "central midfielder": "MID",
    "attacking midfielder": "MID",
    "wing half": "MID",
    "winger": "FWD",
    "forward": "FWD",
    "centre-forward": "FWD",
    "centre forward": "FWD",
    "striker": "FWD",
    "second striker": "FWD",
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip().casefold()


def aliases(name: str) -> list[str]:
    options = [name]
    for replacement in (
        name.replace("Jnr", "Junior").replace("Jr", "Junior"),
        name.replace("Jnr", "Júnior").replace("Jr", "Junior"),
    ):
        replacement = re.sub(r"\s+", " ", replacement).strip()
        if replacement not in options:
            options.append(replacement)
    parts = name.split()
    if len(parts) >= 2:
        short = " ".join(parts[-2:])
        if short not in options:
            options.append(short)
    no_prefix = re.sub(r"^(de|da|do|del|van|von)\s+", "", name, flags=re.IGNORECASE)
    no_prefix = re.sub(r"\s+", " ", no_prefix).strip()
    if no_prefix and no_prefix not in options:
        options.append(no_prefix)
    return options


def choose_search_hit(hits: list[dict[str, object]], query: str) -> dict[str, object] | None:
    query_key = normalize(query)
    footballish = [
        hit
        for hit in hits
        if any(marker in normalize(str(hit.get("description", ""))) for marker in PREFERRED_DESC)
    ]
    if footballish:
        for hit in footballish:
            if normalize(str(hit.get("label", ""))) == query_key:
                return hit
        return footballish[0]
    for hit in hits:
        if normalize(str(hit.get("label", ""))) == query_key:
            return hit
    return hits[0] if hits else None


def map_positions(labels: list[str]) -> str:
    ranked: list[str] = []
    for label in labels:
        text = normalize(label)
        for marker, position in POSITION_MAP.items():
            if marker in text:
                ranked.append(position)
                break
    if "GK" in ranked:
        return "GK"
    if "DEF" in ranked:
        return "DEF"
    if "FWD" in ranked:
        return "FWD"
    if "MID" in ranked:
        return "MID"
    return "UNKNOWN"


async def fetch_json(page, url: str) -> dict[str, Any] | None:
    try:
        payload = await page.evaluate(
            """async (u) => {
                const controller = new AbortController();
                const timeout = setTimeout(() => controller.abort(), 10000);
                try {
                    const response = await fetch(u, {signal: controller.signal});
                    return {
                        ok: response.ok,
                        status: response.status,
                        text: await response.text(),
                    };
                } finally {
                    clearTimeout(timeout);
                }
            }""",
            url,
        )
    except Exception:
        return None
    if not payload or not payload.get("ok"):
        return None
    try:
        return cast(dict[str, Any], json.loads(str(payload["text"])))
    except json.JSONDecodeError:
        return None


async def fetch_text(page, url: str) -> str | None:
    try:
        payload = await page.evaluate(
            """async (u) => {
                const controller = new AbortController();
                const timeout = setTimeout(() => controller.abort(), 10000);
                try {
                    const response = await fetch(u, {signal: controller.signal});
                    return { ok: response.ok, status: response.status, text: await response.text() };
                } finally {
                    clearTimeout(timeout);
                }
            }""",
            url,
        )
    except Exception:
        return None
    if not payload or not payload.get("ok"):
        return None
    return str(payload["text"])


async def fetch_label(page, qid: str, label_cache: dict[str, str]) -> str | None:
    if qid in label_cache:
        return label_cache[qid]
    data = await fetch_json(page, f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")
    if not data:
        return None
    label = data.get("entities", {}).get(qid, {}).get("labels", {}).get("en", {}).get("value")
    if isinstance(label, str):
        label_cache[qid] = label
        return label
    return None


async def resolve_player(
    page,
    name: str,
    label_cache: dict[str, str],
) -> dict[str, object]:
    for query in aliases(name):
        search = await fetch_json(
            page,
            "https://www.wikidata.org/w/api.php?"
            + f"action=wbsearchentities&search={quote_plus(query)}&language=en&format=json&limit=50",
        )
        if not search:
            continue
        hits = list(search.get("search", []))
        chosen = choose_search_hit(hits, query)
        if not chosen:
            continue
        # Try to infer position from the short description (e.g. "Spanish footballer who plays as a midfielder")
        desc = str(chosen.get("description", ""))
        if desc:
            inferred = map_positions([desc])
            if inferred != "UNKNOWN":
                # still fetch country and return early with inferred position
                qid = str(chosen.get("id", ""))
                country = None
                if qid:
                    entity = await fetch_json(page, f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")
                    if entity:
                        entity_data = entity.get("entities", {}).get(qid, {})
                        claims = entity_data.get("claims", {})
                        for claim in claims.get("P27", [])[:1]:
                            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
                            if isinstance(value, dict) and value.get("id"):
                                country = await fetch_label(page, str(value["id"]), label_cache)
                                break
                return {
                    "player": name,
                    "country": country,
                    "position": inferred,
                    "source": chosen.get("label"),
                    "description": chosen.get("description"),
                    "query": query,
                }
        qid = str(chosen.get("id", ""))
        if not qid:
            continue
        entity = await fetch_json(page, f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")
        if not entity:
            continue
        entity_data = entity.get("entities", {}).get(qid, {})
        claims = entity_data.get("claims", {})
        position_qids: list[str] = []
        for claim in claims.get("P413", [])[:5]:
            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            if isinstance(value, dict) and value.get("id"):
                position_qids.append(str(value["id"]))
        position_labels: list[str] = []
        for position_qid in position_qids:
            label = await fetch_label(page, position_qid, label_cache)
            if label:
                position_labels.append(label)
        position = map_positions(position_labels)

        country = None
        for claim in claims.get("P27", [])[:1]:
            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            if isinstance(value, dict) and value.get("id"):
                country = await fetch_label(page, str(value["id"]), label_cache)
                break

        return {
            "player": name,
            "country": country,
            "position": position,
            "source": chosen.get("label"),
            "description": chosen.get("description"),
            "query": query,
        }

        # If we couldn't determine a position from Wikidata P413, try English Wikipedia infobox
        if position == "UNKNOWN":
            sitelinks = entity_data.get("sitelinks", {})
            enwiki = sitelinks.get("enwiki", {})
            title = enwiki.get("title") if isinstance(enwiki, dict) else None
            if title:
                wiki_url = "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")
                html = await fetch_text(page, wiki_url)
                if html:
                    m = re.search(r"<th[^>]*>\s*(?:Position|Positions)\s*</th>\s*<td[^>]*>(.*?)</td>", html, flags=re.IGNORECASE | re.DOTALL)
                    if m:
                        raw = m.group(1)
                        # normalize HTML: replace <br> with commas and strip tags
                        raw = re.sub(r"<br\s*/?>", ",", raw, flags=re.IGNORECASE)
                        raw = re.sub(r"<.*?>", "", raw)
                        parts = [p.strip() for p in re.split(r",|/|;", raw) if p.strip()]
                        wiki_positions = []
                        for p in parts:
                            wiki_positions.append(p)
                        wiki_mapped = map_positions(wiki_positions)
                        if wiki_mapped != "UNKNOWN":
                            position = wiki_mapped

            return {
                "player": name,
                "country": country,
                "position": position,
                "source": chosen.get("label"),
                "description": chosen.get("description"),
                "query": query,
            }

    return {
        "player": name,
        "country": None,
        "position": "UNKNOWN",
        "source": None,
        "description": None,
        "query": None,
    }


async def main() -> None:
    rows = list(cast(list[dict[str, str]], csv.DictReader(SOURCE_PATH.open(encoding="utf-8-sig"))))

    WORKER_COUNT = 4
    async with browser_session() as browser:
        pages = [await browser.new_page() for _ in range(WORKER_COUNT)]
        for page in pages:
            await page.goto(
                "https://www.wikidata.org/wiki/Special:Search?search=Lamine+Yamal&ns0=1&ns120=1",
                wait_until="domcontentloaded",
            )

        async def process_chunk(chunk: list[dict[str, str]], chunk_index: int) -> dict[str, dict[str, object]]:
            page = pages[chunk_index]
            label_cache: dict[str, str] = {}
            output: dict[str, dict[str, object]] = {}
            for index, row in enumerate(chunk, start=1):
                player = row["player"]
                output[player.casefold()] = await resolve_player(page, player, label_cache)
                if index % 25 == 0:
                    print(
                        f"Chunk {chunk_index + 1}: resolved {index}/{len(chunk)} players"
                    )
            return output

        # Split rows into contiguous chunks for each worker to avoid round-robin
        import math

        chunk_size = math.ceil(len(rows) / len(pages)) if rows else 0
        chunks = [rows[i * chunk_size : (i + 1) * chunk_size] for i in range(len(pages))]
        chunk_results = await asyncio.gather(
            *(process_chunk(chunk, index) for index, chunk in enumerate(chunks))
        )

        resolved: dict[str, dict[str, object]] = {}
        for chunk_result in chunk_results:
            resolved.update(chunk_result)

    output_rows: list[dict[str, str]] = []
    unknown_positions = 0
    for row in rows:
        player_key = row["player"].casefold()
        info = resolved.get(player_key, {})
        position = str(info.get("position") or row.get("position") or "UNKNOWN")
        country = str(info.get("country") or row.get("country") or "")
        if position == "UNKNOWN":
            unknown_positions += 1
        output_rows.append(
            {
                "player": row["player"],
                "country": country,
                "position": position,
                "starter_prob": row.get("starter_prob", "0.9"),
                "penalty_taker": row.get("penalty_taker", "0"),
                "set_piece_taker": row.get("set_piece_taker", "0"),
                "minutes_risk": row.get("minutes_risk", "MEDIUM"),
            }
        )

    with INPUT_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "player",
                "country",
                "position",
                "starter_prob",
                "penalty_taker",
                "set_piece_taker",
                "minutes_risk",
            ],
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Wrote {len(output_rows)} rows to {INPUT_PATH}")
    print(f"Rows still with UNKNOWN position: {unknown_positions}")


if __name__ == "__main__":
    asyncio.run(main())
