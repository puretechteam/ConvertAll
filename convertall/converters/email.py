"""Email and saved web pages, with the standard library's MIME parser: .eml and Outlook .msg (read
with olefile) become a readable HTML page or plain text, and .mht web archives one self-contained
HTML file (pictures inlined). PDF comes from the HTML (pdf.py)."""

import base64
import datetime as dt
import email
import email.utils
import html
import re
import struct
from dataclasses import dataclass, field
from email import policy
from pathlib import Path

from ..errors import ConversionError
from ..registry import converter
from ..textfile import decode
from .markup import page


@dataclass
class Attachment:
    name: str
    data: bytes
    mime: str = "application/octet-stream"
    cid: str = ""


@dataclass
class Mail:
    headers: dict[str, str] = field(default_factory=dict)  # From, To, Cc, Date, Subject
    html: str = ""
    text: str = ""
    attachments: list[Attachment] = field(default_factory=list)


# ---- reading

def _read_eml(src: Path) -> Mail:
    with src.open("rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)
    if not msg.keys():
        raise ConversionError("No email headers found in this file")
    mail = Mail({k: str(msg[k]) for k in ("From", "To", "Cc", "Date", "Subject") if msg[k]})
    for kind in ("html", "plain"):
        body = msg.get_body(preferencelist=(kind,))
        if body is not None:
            setattr(mail, "html" if kind == "html" else "text", body.get_content())
    for part in msg.walk():
        if part.is_multipart() or part.get_content_maintype() == "text" and not part.get_filename():
            continue
        data = part.get_payload(decode=True) or b""
        mail.attachments.append(Attachment(part.get_filename() or "", data, part.get_content_type(),
                                           (part["Content-ID"] or "").strip("<> ")))
    return mail


# Outlook .msg: an OLE compound file with one stream per MAPI property
_MSG_PROPS = {"Subject": "0037", "From": "0C1A", "To": "0E04", "Cc": "0E03"}


def _msg_prop(ole, pid: str, prefix: str = ""):
    for typ in ("001F", "001E", "0102"):
        name = f"{prefix}__substg1.0_{pid}{typ}"
        if ole.exists(name):
            data = ole.openstream(name).read()
            if typ == "001F":
                return data.decode("utf-16-le", "replace").rstrip("\x00")
            if typ == "001E":
                return data.decode("cp1252", "replace").rstrip("\x00")
            return data
    return None


def _msg_date(ole) -> str:
    """Sent (or else received) time from the fixed-size property table."""
    if not ole.exists("__properties_version1.0"):
        return ""
    data = ole.openstream("__properties_version1.0").read()
    found = {}
    for off in range(32, len(data) - 15, 16):
        tag, = struct.unpack_from("<I", data, off)
        if tag & 0xFFFF == 0x0040:  # PT_SYSTIME
            found[tag >> 16] = struct.unpack_from("<Q", data, off + 8)[0]
    ticks = found.get(0x0039) or found.get(0x0E06)
    if not ticks:
        return ""
    when = dt.datetime(1601, 1, 1, tzinfo=dt.UTC) + dt.timedelta(microseconds=ticks // 10)
    return email.utils.format_datetime(when.astimezone())


def _read_msg(src: Path) -> Mail:
    import olefile
    if not olefile.isOleFile(str(src)):
        raise ConversionError("Not an Outlook message")
    with olefile.OleFileIO(str(src)) as ole:
        mail = Mail()
        for key, pid in _MSG_PROPS.items():
            value = _msg_prop(ole, pid)
            if isinstance(value, str) and value:
                mail.headers[key] = value
        sender = _msg_prop(ole, "5D01") or _msg_prop(ole, "0C1F")  # SMTP address
        if isinstance(sender, str) and sender and sender not in mail.headers.get("From", ""):
            mail.headers["From"] = f"{mail.headers.get('From', '')} <{sender}>".strip()
        date = _msg_date(ole)
        if date:
            mail.headers["Date"] = date
        body = _msg_prop(ole, "1000")
        mail.text = body if isinstance(body, str) else ""
        raw_html = _msg_prop(ole, "1013")
        if isinstance(raw_html, bytes):
            mail.html = decode(raw_html)
        elif isinstance(raw_html, str):
            mail.html = raw_html
        for storage in sorted({e[0] for e in ole.listdir() if e[0].startswith("__attach_version1.0_#")}):
            prefix = f"{storage}/"
            data = _msg_prop(ole, "3701", prefix)
            if not isinstance(data, bytes):
                continue  # an attached Outlook item, not a file
            name = next((n for n in (_msg_prop(ole, p, prefix) for p in ("3707", "3704", "3001"))
                         if isinstance(n, str) and n), "attachment")
            mime = _msg_prop(ole, "370E", prefix)
            cid = _msg_prop(ole, "3712", prefix)
            mail.attachments.append(Attachment(name, data, mime if isinstance(mime, str) and mime else
                                               "application/octet-stream", cid if isinstance(cid, str) else ""))
    if not (mail.headers or mail.text or mail.html):
        raise ConversionError("This Outlook file holds no message")
    return mail


def _read(src: Path, fmt: str) -> Mail:
    return _read_msg(src) if fmt == "msg" else _read_eml(src)


# ---- writing

def _data_uri(mime: str, data: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _body_html(raw: str) -> tuple[str, str]:
    """(styles, body) from a full HTML document: scripts dropped, its own <style> kept."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "iframe", "object", "embed"]):
        tag.decompose()
    styles = "".join(str(s) for s in soup("style"))
    body = soup.body or soup
    return styles, "".join(str(c) for c in body.contents)


def _size(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def mail_html(mail: Mail, title: str) -> str:
    rows = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>"
                   for k, v in mail.headers.items() if k != "Subject")
    subject = html.escape(mail.headers.get("Subject", "")) or "(no subject)"
    if mail.html:
        styles, body = _body_html(mail.html)
        for att in mail.attachments:  # pictures shown in the message itself
            if att.cid:
                body = body.replace(f"cid:{att.cid}", _data_uri(att.mime, att.data))
    else:
        styles, body = "", f"<pre style='white-space: pre-wrap'>{html.escape(mail.text)}</pre>"
    files = [a for a in mail.attachments if a.name and not (a.cid and f"cid:{a.cid}" in mail.html)]
    listed = ""
    if files:
        items = "".join(f"<li>{html.escape(a.name)} ({_size(len(a.data))})</li>" for a in files)
        listed = f"<hr><p><b>Attachments</b></p><ul>{items}</ul>"
    head = (f"<h2>{subject}</h2><table class='mail-head'>{rows}</table><hr>"
            "<style>.mail-head th{text-align:left;padding-right:1em;color:#555;vertical-align:top}"
            ".mail-head td,.mail-head th{border:none}</style>")
    return page(title, styles + head + body + listed)


def mail_text(mail: Mail) -> str:
    head = "\n".join(f"{k}: {v}" for k, v in mail.headers.items())
    text = mail.text.replace("\r\n", "\n")
    if not text and mail.html:
        from bs4 import BeautifulSoup
        text = BeautifulSoup(mail.html, "html.parser").get_text("\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
    files = [a.name for a in mail.attachments if a.name]
    tail = ("\n\nAttachments:\n" + "\n".join(f"  {n}" for n in files)) if files else ""
    return f"{head}\n\n{text.strip()}{tail}\n"


@converter(inputs={"eml", "msg"}, outputs={"html"})
@converter(inputs={"eml", "msg"}, outputs={"txt"}, terminal=True)  # PDFs come from the formatted HTML
def mail_convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    mail = _read(src, src_fmt)
    if dst_fmt == "html":
        dst.write_text(mail_html(mail, mail.headers.get("Subject", src.stem)), encoding="utf-8")
    else:
        dst.write_text(mail_text(mail), encoding="utf-8")


# ---- MHT / MHTML: a web page and everything it loads, as one MIME message

@converter(inputs={"mht"}, outputs={"html"})
def mht_to_html(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    with src.open("rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)
    parts = [p for p in msg.walk() if not p.is_multipart()]
    root = next((p for p in parts if p.get_content_type() == "text/html"), None)
    if root is None:
        raise ConversionError("No web page found in this archive")
    page_html = root.get_content()
    for part in parts:
        if part is root:
            continue
        data = part.get_payload(decode=True) or b""
        if part.get_content_type() == "text/css":  # stylesheets inline as text, pictures as data URIs
            uri = _data_uri("text/css", data)
        else:
            uri = _data_uri(part.get_content_type(), data)
        for ref in (part["Content-Location"], part["Content-ID"] and "cid:" + part["Content-ID"].strip("<> ")):
            if ref:
                page_html = page_html.replace(str(ref), uri)
    # written as UTF-8 now, whatever the page said before
    page_html = re.sub(r"""(<meta[^>]*charset=["']?)[\w-]+""", r"\1utf-8", page_html, flags=re.IGNORECASE)
    dst.write_text(page_html, encoding="utf-8")
