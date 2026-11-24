"""Lecture des factures électroniques (Factur-X, CII, UBL) : les champs utiles au classement, sans bibliothèque.

- Fichier XML : CII (CrossIndustryInvoice, le format de Factur-X) ou UBL (Invoice, CreditNote).
- PDF Factur-X : le XML est joint dans le PDF ; il est cherché dans ses flux (compressés ou non), sans rien exécuter.

Prudence (contenu reçu d'un fournisseur) : taille plafonnée, XML avec DOCTYPE refusé (ni entité externe ni « bombe »
XML), aucun accès réseau. Importé par factures.py ; se lance aussi seul : `python facturx.py <fichier>` → JSON."""
import json
import re
import sys
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path

PDF_MAX = 20_000_000  # octets lus d'un PDF
XML_MAX = 3_000_000  # octets d'un XML (fichier ou joint)
STREAMS_MAX = 3000  # flux d'un PDF examinés au plus
TYPES = {"380": "Facture", "381": "Avoir", "384": "Facture", "386": "Facture", "389": "Facture", "751": "Facture"}
_STREAM = re.compile(rb"stream\r?\n")


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _find(node, *path):
    """Premier élément au bout du chemin de noms locaux (espaces de noms ignorés), ou None."""
    for name in path:
        node = next((c for c in node if _local(c.tag) == name), None) if node is not None else None
    return node


def _text(node, *path) -> str:
    n = _find(node, *path)
    return " ".join((n.text or "").split()) if n is not None else ""


def _date(raw) -> str:
    raw = raw.strip()
    if re.fullmatch(r"\d{8}", raw):
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
    return "-".join(m.groups()) if m else ""


def parse_xml(data: bytes) -> dict | None:
    """XML d'une facture électronique → {type, date, fournisseur, numero, objet, ht, tva, ttc, devise, format}, ou None."""
    if len(data) > XML_MAX or b"<!DOCTYPE" in data[:4096].upper() or b"<!ENTITY" in data.upper():
        return None
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    kind = _local(root.tag)
    if kind == "CrossIndustryInvoice":
        doc = _find(root, "ExchangedDocument")
        tx = _find(root, "SupplyChainTradeTransaction")
        agreement = _find(tx, "ApplicableHeaderTradeAgreement")
        settle = _find(tx, "ApplicableHeaderTradeSettlement")
        total = _find(settle, "SpecifiedTradeSettlementHeaderMonetarySummation")
        line = _find(tx, "IncludedSupplyChainTradeLineItem")
        out = {"format": "CII", "type": TYPES.get(_text(doc, "TypeCode"), "Facture"), "numero": _text(doc, "ID"),
               "date": _date(_text(doc, "IssueDateTime", "DateTimeString")),
               "fournisseur": _text(agreement, "SellerTradeParty", "Name"),
               "objet": _text(line, "SpecifiedTradeProduct", "Name"),
               "ht": _text(total, "TaxBasisTotalAmount"), "tva": _text(total, "TaxTotalAmount"),
               "ttc": _text(total, "GrandTotalAmount"), "devise": _text(settle, "InvoiceCurrencyCode")}
    elif kind in ("Invoice", "CreditNote"):
        party = _find(root, "AccountingSupplierParty", "Party")
        total = _find(root, "LegalMonetaryTotal")
        line = _find(root, "InvoiceLine")
        line = _find(root, "CreditNoteLine") if line is None else line
        code = _text(root, "InvoiceTypeCode") or _text(root, "CreditNoteTypeCode")
        out = {"format": "UBL", "type": "Avoir" if kind == "CreditNote" else TYPES.get(code, "Facture"),
               "numero": _text(root, "ID"), "date": _date(_text(root, "IssueDate")),
               "fournisseur": _text(party, "PartyName", "Name") or _text(party, "PartyLegalEntity", "RegistrationName"),
               "objet": _text(line, "Item", "Name"), "ht": _text(total, "TaxExclusiveAmount"),
               "tva": _text(root, "TaxTotal", "TaxAmount"),
               "ttc": _text(total, "TaxInclusiveAmount") or _text(total, "PayableAmount"),
               "devise": _text(root, "DocumentCurrencyCode")}
    else:
        return None
    return out if out["date"] or out["numero"] or out["ttc"] else None


def _inflate(raw: bytes) -> bytes:
    d = zlib.decompressobj()
    try:
        return d.decompress(raw, XML_MAX + 1)
    except zlib.error:
        return b""


def from_pdf(path) -> dict | None:
    """PDF Factur-X → les champs de son XML joint, ou None (PDF ordinaire, illisible ou trop gros)."""
    try:
        with open(path, "rb") as fh:
            data = fh.read(PDF_MAX + 1)
    except OSError:
        return None
    if len(data) > PDF_MAX or not data.startswith(b"%PDF"):
        return None
    pos = 0
    for _ in range(STREAMS_MAX):
        m = _STREAM.search(data, pos)
        if not m:
            break
        end = data.find(b"endstream", m.end())
        if end < 0:
            break
        head = data[max(0, m.start() - 400):m.start()]
        raw = data[m.end():end].rstrip(b"\r\n")
        body = _inflate(raw) if b"FlateDecode" in head else raw
        if b"CrossIndustryInvoice" in body or b"urn:oasis:names:specification:ubl" in body:
            got = parse_xml(body[body.find(b"<"):].strip())
            if got:
                got["format"] = "Factur-X" if got["format"] == "CII" else got["format"]
                return got
        pos = end + 9
    return None


def read(path) -> dict | None:
    """Fichier d'une facture → champs lus (XML ou PDF Factur-X), ou None."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".xml":
        try:
            if p.stat().st_size > XML_MAX:
                return None
            return parse_xml(p.read_bytes())
        except OSError:
            return None
    if ext == ".pdf":
        return from_pdf(p)
    return None


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage : python facturx.py <facture.pdf|facture.xml>\nLit une facture électronique (Factur-X, CII, UBL) "
              "et affiche ses champs en JSON ; rien si le fichier n'en contient pas.")
        sys.exit(0 if len(sys.argv) == 1 else 3)
    print(json.dumps(read(sys.argv[1]), ensure_ascii=False, indent=1))
