import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.gov.pl"
NEWS_URL = "https://www.gov.pl/web/energia/aktualnosci"
DATA_FILE = Path("prices.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CPNMonitorBot/1.0)"}

MONTHS_PL = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4,
    "maja": 5, "czerwca": 6, "lipca": 7, "sierpnia": 8,
    "września": 9, "października": 10, "listopada": 11, "grudnia": 12,
}


def extract_price(text: str, patterns: list[str]) -> float | None:
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE | re.DOTALL)
        if m:
            val = float(m.group(1).replace(",", "."))
            if 4.0 <= val <= 12.0:
                return round(val, 2)
    return None


def extract_dates(text: str) -> tuple[str, str] | None:
    # Wzorzec typu: "od 21 do 23 listopada 2026" lub "21-23 listopada 2026"
    m_range = re.search(
        r"(\d{1,2})\s*(?:do|[-–])\s*(\d{1,2})\s+(" + "|".join(MONTHS_PL) + r")\s+(\d{4})",
        text, flags=re.IGNORECASE
    )
    if m_range:
        d1, d2, month_name, year = int(m_range.group(1)), int(m_range.group(2)), m_range.group(3).lower(), int(m_range.group(4))
        month = MONTHS_PL[month_name]
        return f"{year:04d}-{month:02d}-{d1:02d}", f"{year:04d}-{month:02d}-{d2:02d}"

    # Wzorzec pojedynczego dnia: "20 listopada 2026"
    m_single = re.search(
        r"(\d{1,2})\s+(" + "|".join(MONTHS_PL) + r")\s+(\d{4})",
        text, flags=re.IGNORECASE
    )
    if m_single:
        d1, month_name, year = int(m_single.group(1)), m_single.group(2).lower(), int(m_single.group(3))
        month = MONTHS_PL[month_name]
        iso = f"{year:04d}-{month:02d}-{d1:02d}"
        return iso, iso

    # Wzorzec DD.MM.YYYY - DD.MM.YYYY
    m_dot = re.findall(r"(\d{2})\.(\d{2})\.(\d{4})", text)
    if len(m_dot) >= 2:
        d1, m1, y1 = m_dot[0]
        d2, m2, y2 = m_dot[1]
        return f"{y1}-{m1}-{d1}", f"{y2}-{m2}-{d2}"
    if len(m_dot) == 1:
        d1, m1, y1 = m_dot[0]
        iso = f"{y1}-{m1}-{d1}"
        return iso, iso
    return None


def fetch_latest_entries() -> list[dict]:
    resp = requests.get(NEWS_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    found = []
    for a in soup.select("a[href]"):
        title = a.get_text(" ", strip=True).lower()
        if any(k in title for k in ("maksymaln", "cen paliw", "cenach paliw", "obwieszczeni")):
            href = a["href"]
            url = href if href.startswith("http") else BASE_URL + href
            article = requests.get(url, headers=HEADERS, timeout=20)
            if article.status_code != 200:
                continue
            text = BeautifulSoup(article.text, "html.parser").get_text(" ", strip=True)

            pb95 = extract_price(text, [r"(?:Pb\s*95|benzyna\s*(?:silnikowa\s*)?95|E10)[^\d]{0,40}(\d[,\.]\d{2})"])
            pb98 = extract_price(text, [r"(?:Pb\s*98|benzyna\s*(?:silnikowa\s*)?98|E5)[^\d]{0,40}(\d[,\.]\d{2})"])
            on = extract_price(text, [r"(?:olej\s*napędow\w*|ON|diesel|B7)[^\d]{0,40}(\d[,\.]\d{2})"])
            dates = extract_dates(text)

            if pb95 and pb98 and on and dates:
                found.append({
                    "from": dates[0],
                    "to": dates[1],
                    "pb95": pb95,
                    "pb98": pb98,
                    "on": on,
                })
            if len(found) >= 5:
                break
    return found


def main():
    data = json.loads(DATA_FILE.read_text(encoding="utf-8")) if DATA_FILE.exists() else {"periods": []}
    by_key = {(p["from"], p["to"]): p for p in data.get("periods", [])}

    for entry in fetch_latest_entries():
        by_key[(entry["from"], entry["to"])] = entry

    sorted_periods = sorted(by_key.values(), key=lambda x: x["from"])[-30:]
    cet = timezone(timedelta(hours=1))
    output = {
        "updated_at": datetime.now(cet).strftime("%Y-%m-%d %H:%M"),
        "periods": sorted_periods,
    }
    DATA_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()