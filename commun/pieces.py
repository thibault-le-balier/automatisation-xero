"""Lecture et contrôle des justificatifs, communs aux deux sociétés.

- amount_variants / amounts : les façons d'écrire un montant dans un document (1 234,50 / 1,234.50 / 32.4…)
- dates_in : les dates présentes dans un texte (15/03/2026, 2026-03-15, 15 mars 2026, March 15, 2026…)
- check : None si le fichier est sain (PDF complet, image lisible), sinon la raison
- pdf_text : texte d'un PDF (pdftotext)
"""
import base64
import re
import subprocess
from datetime import date

MONTHS = {m: i + 1 for i, ms in enumerate([
    ("jan", "janv", "january", "janvier"), ("feb", "fév", "fev", "févr", "fevr", "february", "février", "fevrier"),
    ("mar", "march", "mars"), ("apr", "avr", "april", "avril"), ("may", "mai"), ("jun", "june", "juin"),
    ("jul", "july", "juillet", "juil"), ("aug", "august", "août", "aout"), ("sep", "sept", "september", "septembre"),
    ("oct", "october", "octobre"), ("nov", "november", "novembre"), ("dec", "déc", "december", "décembre"),
]) for m in ms}


def pdf_text(path):
    r = subprocess.run(["pdftotext", "-layout", "-q", str(path), "-"], capture_output=True, text=True, timeout=60)
    return r.stdout


def amount_variants(x):
    """Formats possibles d'un montant dans un document : 1234.5 -> 1234.50, 1,234.50, 1 234,50, 1234,50…"""
    v = f"{x:.2f}"
    ent, dec = v.split(".")
    grouped = f"{int(ent):,}"
    out = {v, f"{ent},{dec}", f"{grouped}.{dec}", f"{grouped.replace(',', ' ')},{dec}",
           f"{grouped.replace(',', ' ')}.{dec}", f"{grouped.replace(',', '.')},{dec}",
           f"{grouped.replace(',', chr(8239))},{dec}", f"{grouped.replace(',', chr(160))},{dec}"}
    if dec == "00":
        out |= {ent, grouped}
    return {o for o in out if len(o) >= 3}


def dates_in(text):
    found = set()
    for d, m, y in re.findall(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b", text):
        found.add((int(y), int(m), int(d)))
    for y, m, d in re.findall(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text):
        found.add((int(y), int(m), int(d)))
    for d, mon, y in re.findall(r"\b(\d{1,2})(?:er)?\s+([A-Za-zéûè]{3,9})\.?,?\s+(20\d{2})\b", text):
        if mon.lower() in MONTHS:
            found.add((int(y), MONTHS[mon.lower()], int(d)))
    for y, mon, d in re.findall(r"\b(20\d{2})\s+([A-Za-z]{3,9})\s+(\d{1,2})\b", text):  # « 2026 February 09 »
        if mon.lower() in MONTHS:
            found.add((int(y), MONTHS[mon.lower()], int(d)))
    for mon, d, y in re.findall(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(20\d{2})\b", text):
        if mon.lower() in MONTHS:
            found.add((int(y), MONTHS[mon.lower()], int(d)))
    out = []
    for y, m, d in found:
        try:
            out.append(date(y, m, d))
        except ValueError:
            pass
    return out


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def safe(name):
    return re.sub(r"[^\w.\- #]", "_", name).strip() or "piece"


def b64decode(text, urlsafe=False):
    text = re.sub(r"\s+", "", text)
    text += "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text) if urlsafe else base64.b64decode(text)


def pdf_streams_problem(data):
    """Décompresse chaque flux FlateDecode (après ASCII85 si présent) : une erreur = fichier abîmé."""
    import zlib
    for m in re.finditer(rb"<<(.{0,400}?)>>\s*stream\r?\n", data, re.S):
        head = m.group(1)
        if b"FlateDecode" not in head:
            continue
        end = data.find(b"endstream", m.end())
        raw = data[m.end():end]
        try:
            if b"ASCII85Decode" in head:
                raw = base64.a85decode(raw.strip().removeprefix(b"<~").removesuffix(b"~>"), adobe=False, ignorechars=b" \t\r\n")
            o = zlib.decompressobj()
            o.decompress(raw)
            if not o.eof:
                return "PDF tronqué (flux incomplet)"
        except (zlib.error, ValueError):
            return "PDF corrompu (flux illisible)"
    return None


def check(path):
    """Renvoie None si le fichier est sain, sinon la raison."""
    data = path.read_bytes()
    if not data:
        return "fichier vide"
    if path.suffix.lower() == ".pdf" or data[:5] == b"%PDF-":
        if data[:5] != b"%PDF-" or b"%%EOF" not in data[-2048:]:
            return "PDF tronqué"
        m = re.findall(rb"startxref\s+(\d+)", data[-2048:])
        if m:
            off = int(m[-1])
            if not (data[off:off + 4] == b"xref" or re.match(rb"\d+\s+\d+\s+obj", data[off:off + 20])):
                return "PDF corrompu (table xref)"
        return pdf_streams_problem(data)
    if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".heic"):
        r = subprocess.run(["sips", "-g", "pixelWidth", str(path)], capture_output=True, text=True)
        return None if "pixelWidth" in r.stdout else "image illisible"
    return None


def amounts(x):
    """Variantes d'écriture du montant, y compris sans zéro final (« 32.4 euros »)."""
    out = amount_variants(x)
    if f"{x:.2f}".endswith("0"):
        out |= {f"{x:.1f}", f"{x:.1f}".replace(".", ",")}
    return out
