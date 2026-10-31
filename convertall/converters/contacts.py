"""Contacts (vCard .vcf) and calendars (iCalendar .ics) to tables (CSV, JSON) and back.

Both are "content lines": NAME;PARAM=value:value, long lines folded onto the next line with a
leading space, and , ; \\ and newlines escaped. One record per contact or event; columns use plain
names ("Mobile", "Start") and the common Google/Outlook export headers are understood on the way back.
"""

import datetime as dt
import quopri
import re
import uuid
from pathlib import Path

from ..errors import ConversionError
from ..registry import converter
from ..textfile import read_text

# ---- content lines


def _unfold(text: str) -> list[str]:
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for raw in text.split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif lines and lines[-1].endswith("=") and "QUOTED-PRINTABLE" in lines[-1].split(":", 1)[0].upper():
            lines[-1] = lines[-1][:-1] + raw  # vCard 2.1 soft line break
        elif raw.strip():
            lines.append(raw)
    return lines


def _split(value: str, sep: str) -> list[str]:
    """Split on sep, but not on an escaped one."""
    return [p.replace("\\" + sep, sep) for p in re.split(rf"(?<!\\){re.escape(sep)}", value)]


def _unescape(v: str) -> str:
    return re.sub(r"\\([nN,;\\:])", lambda m: "\n" if m[1] in "nN" else m[1], v)


def _escape(v: str) -> str:
    return (str(v).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\n").replace("\n", "\\n"))


def _parse_line(line: str) -> tuple[str, dict[str, str], str]:
    """'item1.TEL;TYPE=CELL,VOICE:+1 555' -> ('TEL', {'TYPE': 'CELL,VOICE'}, '+1 555')."""
    m = re.match(r'((?:[^:"]|"[^"]*")*):(.*)', line)
    if not m:
        return "", {}, ""
    head, value = m[1], m[2]
    name, *params = head.split(";")
    name = name.rsplit(".", 1)[-1].upper()
    found: dict[str, str] = {}
    for p in params:
        k, eq, v = p.partition("=")
        if eq:
            found[k.upper()] = (found.get(k.upper(), "") + "," + v.strip('"')).lstrip(",")
        else:  # vCard 2.1: bare "CELL" means TYPE=CELL, bare "QUOTED-PRINTABLE" an encoding
            key = "ENCODING" if k.upper() in ("QUOTED-PRINTABLE", "BASE64", "B") else "TYPE"
            found[key] = (found.get(key, "") + "," + k).lstrip(",")
    if found.get("ENCODING", "").upper() == "QUOTED-PRINTABLE":
        value = quopri.decodestring(value.encode("latin-1", "replace")).decode(found.get("CHARSET", "utf-8"), "replace")
        value = value.replace("\r\n", "\\n").replace("\n", "\\n")  # line breaks escaped, as in vCard 3 and 4
    return name, found, value


def _fold(line: str) -> str:
    """Lines longer than 75 bytes continue on the next line after a space (RFC 5545 / 6350)."""
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode()) > 75:
            out.append(cur)
            cur = " "
        cur += ch
    out.append(cur)
    return "\r\n".join(out)


def _components(text: str, kind: str) -> list[list[tuple[str, dict, str]]]:
    """Every BEGIN:kind ... END:kind block, its lines parsed (nested blocks like VALARM skipped)."""
    found, cur, depth = [], None, 0
    for line in _unfold(text):
        name, params, value = _parse_line(line)
        if name == "BEGIN":
            if value.upper() == kind and cur is None:
                cur, depth = [], 0
            elif cur is not None:
                depth += 1
        elif name == "END":
            if cur is not None and depth == 0 and value.upper() == kind:
                found.append(cur)
                cur = None
            elif cur is not None:
                depth -= 1
        elif cur is not None and depth == 0:
            cur.append((name, params, value))
    return found


# ---- tables in and out

def _records_in(src: Path, fmt: str) -> list[dict]:
    from .data import _records, load
    return [{k: v for k, v in r.items() if v not in (None, "")} for r in _records(load(src, fmt))]


def _records_out(records: list[dict], dst: Path, fmt: str) -> None:
    from .data import dump
    dump(records, dst, fmt)


def _norm(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(header).lower()).strip()


# ---- vCard

_TEL = {"cell": "Mobile", "mobile": "Mobile", "iphone": "Mobile", "work": "Work phone", "home": "Home phone",
        "fax": "Fax"}
_ADR = {"work": "Work address", "home": "Home address"}


def _types(params: dict) -> list[str]:
    return [t.strip().lower() for t in params.get("TYPE", "").split(",") if t.strip()]


def _add(rec: dict, key: str, value: str) -> None:
    if not value:
        return
    n, k = 1, key
    while k in rec:
        n += 1
        k = f"{key} {n}"
    rec[k] = value


def read_vcards(text: str) -> list[dict]:
    cards = []
    for lines in _components(text, "VCARD"):
        rec: dict = {}
        for name, params, value in lines:
            if params.get("ENCODING", "").upper() in ("B", "BASE64"):
                continue  # photos and keys
            if name == "FN":
                rec["Name"] = _unescape(value)
            elif name == "N":
                parts = [_unescape(p) for p in _split(value, ";")] + [""] * 5
                for key, v in zip(("Last name", "First name", "Middle name", "Prefix", "Suffix"), parts):
                    if v:
                        rec[key] = v
            elif name in ("NICKNAME", "TITLE", "BDAY", "NOTE", "CATEGORIES"):
                key = {"NICKNAME": "Nickname", "TITLE": "Title", "BDAY": "Birthday", "NOTE": "Note",
                       "CATEGORIES": "Categories"}[name]
                _add(rec, key, _unescape(value))
            elif name == "ORG":
                parts = [_unescape(p) for p in _split(value, ";")]
                _add(rec, "Organization", parts[0])
                if len(parts) > 1:
                    _add(rec, "Department", parts[1])
            elif name == "EMAIL":
                _add(rec, "Email", _unescape(value))
            elif name == "TEL":
                kinds = _types(params)
                label = next((_TEL[t] for t in kinds if t in _TEL), "Phone")
                _add(rec, label, _unescape(value).removeprefix("tel:"))
            elif name == "ADR":
                parts = [_unescape(p) for p in _split(value, ";")]
                label = next((_ADR[t] for t in _types(params) if t in _ADR), "Address")
                _add(rec, label, ", ".join(p.strip().replace("\n", ", ") for p in parts if p.strip()))
            elif name == "URL":
                _add(rec, "Website", _unescape(value))
        if "Name" not in rec:
            full = " ".join(rec.get(k, "") for k in ("First name", "Last name")).strip()
            if full or rec.get("Organization"):
                rec = {"Name": full or rec["Organization"], **rec}
        if rec:
            cards.append(rec)
    return cards


# header (normalized) -> our column; numbered Google/Outlook columns are matched by prefix below
_CONTACT_HEADERS = {
    "name": "Name", "full name": "Name", "display name": "Name", "first name": "First name",
    "given name": "First name", "last name": "Last name", "family name": "Last name", "surname": "Last name",
    "middle name": "Middle name", "additional name": "Middle name", "prefix": "Prefix", "name prefix": "Prefix",
    "suffix": "Suffix", "name suffix": "Suffix", "nickname": "Nickname", "organization": "Organization",
    "organisation": "Organization", "company": "Organization", "organization 1 name": "Organization",
    "department": "Department", "organization 1 department": "Department", "title": "Title",
    "job title": "Title", "organization 1 title": "Title", "email": "Email", "e mail": "Email",
    "email address": "Email", "e mail address": "Email", "mobile": "Mobile", "mobile phone": "Mobile",
    "cell": "Mobile", "cell phone": "Mobile", "phone": "Phone", "telephone": "Phone", "primary phone": "Phone",
    "work phone": "Work phone", "business phone": "Work phone", "home phone": "Home phone", "fax": "Fax",
    "business fax": "Fax", "address": "Address", "home address": "Home address", "work address": "Work address",
    "business address": "Work address", "birthday": "Birthday", "website": "Website", "web page": "Website",
    "url": "Website", "note": "Note", "notes": "Note", "categories": "Categories", "group membership": "Categories",
}


def _contact_column(header: str) -> str | None:
    h = _norm(header)
    h = re.sub(r"^(e mail|email) (\d+) (address|value)$", r"email \2", h)  # "E-mail 2 Address"
    m = re.match(r"^(email|phone) (\d+)(?: value)?$", h)  # Google: "E-mail 1 - Value", "Phone 2 - Value"
    if m:
        return {"email": "Email", "phone": "Phone"}[m[1]] + ("" if m[2] == "1" else f" {m[2]}")
    base = re.sub(r" (\d+)$", "", h)
    if base in _CONTACT_HEADERS:
        n = h[len(base):].strip()
        return _CONTACT_HEADERS[base] + (f" {n}" if n and n != "1" else "")
    return None


def write_vcards(records: list[dict]) -> str:
    out = []
    for rec in records:
        card: dict[str, str] = {}
        extra = []
        for k, v in rec.items():
            col = _contact_column(k)
            if col:
                card[col] = str(v)
            elif str(v).strip():
                extra.append(f"{k}: {v}")
        if extra:
            card["Note"] = "\n".join(filter(None, [card.get("Note", "")] + extra))
        full = card.get("Name") or " ".join(card.get(k, "") for k in ("First name", "Last name")).strip()
        full = full or card.get("Organization") or card.get("Email") or card.get("Phone") or card.get("Mobile")
        if not full:
            continue
        lines = ["BEGIN:VCARD", "VERSION:3.0", f"FN:{_escape(full)}"]
        n = [card.get(k, "") for k in ("Last name", "First name", "Middle name", "Prefix", "Suffix")]
        if not any(n) and "Name" in card and " " in card["Name"]:
            first, _, last = card["Name"].rpartition(" ")
            n = [last, first, "", "", ""]
        lines.append("N:" + ";".join(_escape(x) for x in n))
        for col, v in card.items():
            base = re.sub(r" \d+$", "", col)
            v = _escape(v)
            if base == "Email":
                lines.append(f"EMAIL;TYPE=INTERNET:{v}")
            elif base in ("Mobile", "Phone", "Work phone", "Home phone", "Fax"):
                kind = {"Mobile": "CELL", "Work phone": "WORK", "Home phone": "HOME", "Fax": "FAX"}.get(base, "VOICE")
                lines.append(f"TEL;TYPE={kind}:{v}")
            elif base in ("Address", "Home address", "Work address"):
                kind = {"Home address": ";TYPE=HOME", "Work address": ";TYPE=WORK"}.get(base, "")
                lines.append(f"ADR{kind}:;;{v};;;;")
            elif base == "Organization":
                dept = _escape(card.get("Department", ""))
                lines.append(f"ORG:{v}" + (f";{dept}" if dept else ""))
            elif base in ("Nickname", "Title", "Birthday", "Note", "Categories", "Website"):
                prop = {"Nickname": "NICKNAME", "Title": "TITLE", "Birthday": "BDAY", "Note": "NOTE",
                        "Categories": "CATEGORIES", "Website": "URL"}[base]
                lines.append(f"{prop}:{v.replace(chr(92) + ',', ',') if prop == 'CATEGORIES' else v}")
        lines.append("END:VCARD")
        out.append("\r\n".join(_fold(line) for line in lines))
    if not out:
        raise ConversionError("No contacts found: the table needs a name, email or phone column")
    return "\r\n".join(out) + "\r\n"


# ---- iCalendar

def _ics_when(value: str, params: dict) -> tuple[str, bool]:
    """('2026-10-25T14:00:00Z', all_day=False) from DTSTART/DTEND."""
    v = value.strip()
    if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", v):
        return f"{v[:4]}-{v[4:6]}-{v[6:8]}", True
    m = re.fullmatch(r"(\d{4})(\d\d)(\d\d)T(\d\d)(\d\d)(\d\d)(Z?)", v)
    if not m:
        return v, False
    return f"{m[1]}-{m[2]}-{m[3]}T{m[4]}:{m[5]}:{m[6]}{m[7]}", False


def _duration(text: str) -> dt.timedelta | None:
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", text.strip())
    if not m:
        return None
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    delta = dt.timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)
    return -delta if m[1] == "-" else delta


def _shift(when: str, delta: dt.timedelta) -> str:
    z = when.endswith("Z")
    try:
        t = dt.datetime.fromisoformat(when.rstrip("Z"))
    except ValueError:
        return ""
    if len(when) == 10:
        return (t + delta).date().isoformat()
    return (t + delta).isoformat() + ("Z" if z else "")


def read_events(text: str) -> list[dict]:
    events = []
    for lines in _components(text, "VEVENT"):
        rec: dict = {}
        props = {}
        for name, params, value in lines:
            props.setdefault(name, (params, value))
            if name == "ATTENDEE":
                who = params.get("CN") or value.removeprefix("mailto:").removeprefix("MAILTO:")
                rec["Attendees"] = "; ".join(filter(None, [rec.get("Attendees", ""), who]))
        if "SUMMARY" in props:
            rec["Subject"] = _unescape(props["SUMMARY"][1])
        all_day = False
        if "DTSTART" in props:
            params, value = props["DTSTART"]
            rec["Start"], all_day = _ics_when(value, params)
            if params.get("TZID"):
                rec["Time zone"] = params["TZID"]
        if "DTEND" in props:
            end, _ = _ics_when(props["DTEND"][1], props["DTEND"][0])
        elif "DURATION" in props and "Start" in rec and _duration(props["DURATION"][1]):
            end = _shift(rec["Start"], _duration(props["DURATION"][1]))
        else:
            end = ""
        if end and all_day:  # iCalendar's all-day end is the day after; people write the last day
            end = _shift(end, dt.timedelta(days=-1))
        if end:
            rec["End"] = end
        rec["All day"] = "yes" if all_day else ""
        for prop, col in (("LOCATION", "Location"), ("DESCRIPTION", "Description"), ("STATUS", "Status"),
                          ("RRULE", "Repeat"), ("UID", "UID")):
            if prop in props:
                rec[col] = _unescape(props[prop][1]) if prop not in ("RRULE",) else props[prop][1]
        if "ORGANIZER" in props:
            params, value = props["ORGANIZER"]
            rec["Organizer"] = params.get("CN") or value.removeprefix("mailto:").removeprefix("MAILTO:")
        events.append({k: v for k, v in rec.items() if v != ""} | {"All day": rec["All day"]})
    return events


_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d.%m.%Y", "%Y/%m/%d", "%d %b %Y", "%b %d, %Y")
_TIME_FORMATS = ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p", "%I:%M%p")


def _parse_when(date: str, time: str = "") -> tuple[dt.datetime | dt.date | None, bool]:
    """(value, is_utc) from a table's date (+ time) cells."""
    date, time = str(date).strip(), str(time).strip()
    if not date:
        return None, False
    utc = date.endswith(("Z", "+00:00"))
    try:
        t = dt.datetime.fromisoformat(date)
        if t.tzinfo is not None:
            t = t.astimezone(dt.UTC).replace(tzinfo=None)
            utc = True
        if len(date) == 10 and not time:
            return t.date(), False
        day = t
    except ValueError:
        day = next((dt.datetime.strptime(date, f) for f in _DATE_FORMATS if _try(date, f)), None)  # noqa: DTZ007 - floating time
        if day is None:
            return None, False
        if not time:
            return day.date(), False
    if time:
        clock = next((dt.datetime.strptime(time.upper(), f)  # noqa: DTZ007 - floating time
                      for f in _TIME_FORMATS if _try(time.upper(), f)), None)
        if clock:
            day = day.replace(hour=clock.hour, minute=clock.minute, second=clock.second)
    return day, utc


def _try(text: str, fmt: str) -> bool:
    try:
        dt.datetime.strptime(text, fmt)  # noqa: DTZ007 - only checks the format
        return True
    except ValueError:
        return False


def _ics_value(v, utc: bool) -> tuple[str, str]:
    """(params, value) for DTSTART/DTEND."""
    if isinstance(v, dt.datetime):
        return "", v.strftime("%Y%m%dT%H%M%S") + ("Z" if utc else "")
    return ";VALUE=DATE", v.strftime("%Y%m%d")


def write_events(records: list[dict]) -> str:
    now = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Pure Tech//ConvertAll//EN", "CALSCALE:GREGORIAN"]
    count = 0
    for rec in records:
        cell = {_norm(k): str(v) for k, v in rec.items()}

        def pick(*names: str, cell: dict = cell) -> str:
            return next((cell[n] for n in names if cell.get(n)), "")
        start, utc = _parse_when(pick("start", "start date", "begin", "date", "dtstart"), pick("start time"))
        if start is None:
            continue
        end, end_utc = _parse_when(pick("end", "end date", "dtend"), pick("end time"))
        all_day = pick("all day", "all day event").lower() in ("yes", "true", "1", "y", "x")
        if all_day or not isinstance(start, dt.datetime):
            start = start.date() if isinstance(start, dt.datetime) else start
            last = (end.date() if isinstance(end, dt.datetime) else end) or start
            end = last + dt.timedelta(days=1)  # back to iCalendar's exclusive end
        tz = pick("time zone", "timezone", "tzid")
        lines += ["BEGIN:VEVENT", f"UID:{pick('uid') or f'{uuid.uuid4()}@convertall'}", f"DTSTAMP:{now}"]
        for prop, value, is_utc in (("DTSTART", start, utc), ("DTEND", end, end_utc)):
            if value is None:
                continue
            params, text = _ics_value(value, is_utc)
            if tz and not params and not is_utc:
                params = f";TZID={tz}"
            lines.append(f"{prop}{params}:{text}")
        for col, prop in (("subject", "SUMMARY"), ("location", "LOCATION"), ("description", "DESCRIPTION"),
                          ("status", "STATUS")):
            value = pick(col, *(("title", "summary", "name") if col == "subject" else ()))
            if value:
                lines.append(f"{prop}:{_escape(value)}")
        repeat = pick("repeat", "rrule")
        if repeat.upper().startswith("FREQ="):
            lines.append(f"RRULE:{repeat}")
        lines.append("END:VEVENT")
        count += 1
    if not count:
        raise ConversionError("No events found: the table needs a Start (or Start Date) column")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


@converter(inputs={"vcf", "ics"}, outputs={"csv", "json"})
def to_table(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    text = read_text(src)
    records = read_vcards(text) if src_fmt == "vcf" else read_events(text)
    if not records:
        raise ConversionError("No contacts found in this file" if src_fmt == "vcf" else "No events found in this file")
    _records_out(records, dst, dst_fmt)


@converter(inputs={"csv", "json"}, outputs={"vcf", "ics"}, cost=2)
def from_table(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    records = _records_in(src, src_fmt)
    text = write_vcards(records) if dst_fmt == "vcf" else write_events(records)
    dst.write_bytes(text.encode("utf-8"))

