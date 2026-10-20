"""Listings organised in chat groups (Signal, WhatsApp, Telegram, Discord): group links, and announcements cleaned.

His rulings (2026-10-21): a group's invite link goes only to signed-in members, and only with the
depositor's tick that the organiser shares it openly; reviewers check a chat-only listing against the pasted
announcement, kept with phone numbers, @handles, emails and senders' names taken out. A link to one person (a
number or a profile) is never kept.
"""
import re

PLATFORMS = {"signal": "Signal", "whatsapp": "WhatsApp", "telegram": "Telegram", "discord": "Discord", "other": "another app"}

GROUP = [  # invite links to a group, by platform
    ("signal", r"https://signal\.group/#\S+"),
    ("whatsapp", r"https://chat\.whatsapp\.com/(invite/)?[A-Za-z0-9]{10,}"),
    ("whatsapp", r"https://(www\.)?whatsapp\.com/channel/[A-Za-z0-9]{10,}"),
    ("telegram", r"https://(t|telegram)\.me/(\+|joinchat/)[A-Za-z0-9_-]{8,}"),
    ("discord", r"https://(discord\.gg|discord\.com/invite|discordapp\.com/invite)/[A-Za-z0-9-]{2,}"),
]
PERSON = [  # links to one person: a number or a profile
    ("whatsapp", r"https://(wa\.me|api\.whatsapp\.com/send)\S*"),
    ("signal", r"https://signal\.me/\S*"),
    ("telegram", r"https://(t|telegram)\.me/(?![+]|joinchat/)[A-Za-z0-9_]{3,}\S*"),  # a public name: a person or a channel, unknowable
    ("discord", r"https://(discord|discordapp)\.com/users/\S*"),
]
LINKS_HELP = "A group link starts signal.group/, chat.whatsapp.com/, t.me/+ or discord.gg/."
PERSON_TEXT = ("That's a link to one person, and The Wheel keeps links to groups only. "
               "For a Telegram group, ask its admin for an invite link (t.me/+…).")


def classify(url: str):
    """-> ("group", platform), ("person", platform), or None for any other link."""
    u = (url or "").strip()
    u = "https://" + u[len("http://"):] if u.startswith("http://") else u
    for kind, rules in (("group", GROUP), ("person", PERSON)):
        for platform, rx in rules:
            if re.fullmatch(rx + r"/?", u):
                return kind, platform
    return None


ANY_LINK = r"(https?://)?(signal\.group|signal\.me|chat\.whatsapp\.com|(www\.)?whatsapp\.com/channel|wa\.me|api\.whatsapp\.com|t\.me|telegram\.me|discord\.gg|discord(app)?\.com/(invite|users))/\S*"
STAMP = (  # a copied message's header: who sent it and when
    r"^\s*\[\d{1,2}[:./]\d{2}(\s?[ap]\.?m\.?)?,\s*\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\]\s*[^:\n]{1,60}:\s*",  # WhatsApp: [9:14 am, 21/10/2026] Name:
    r"^\s*\[\d{1,2}[/.]\d{1,2}[/.]\d{2,4},?\s*\d{1,2}[:.]\d{2}(:\d{2})?(\s?[ap]\.?m\.?)?\]\s*[^:\n]{1,60}:\s*",  # [21/10/2026, 9:14 am] Name:
    r"^\s*\d{1,2}[/.]\d{1,2}[/.]\d{2,4},?\s*\d{1,2}[:.]\d{2}(\s?[ap]\.?m\.?)?\s*-\s*[^:\n]{1,60}:\s*",  # 21/10/2026, 9:14 am - Name: (exports)
    r"^\s*[^\n,\[]{1,60},\s*\[\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\s+\d{1,2}[:.]\d{2}\]\s*$",  # Telegram: Name, [21.10.26 09:14]
)
PHONE = r"(?<![\w/:.-])(\+\d{1,3}[\s.-]?\(?\d{1,4}\)?|\(?0\d{1,4}\)?)([\s.-]?\d{2,4}){2,4}(?![\w/])"
EMAIL = r"[\w.+-]+@[\w-]+(\.[\w-]+)+"
HANDLE = r"(?<![\w.@\[])@[\w.+-]{2,}"  # "[@name]" stays as it is: cleaning twice changes nothing


def is_chat(text: str) -> bool:
    """Whether pasted text looks copied from a chat: a group link in it, or a message header."""
    t = text or ""
    return bool(re.search(ANY_LINK, t) or any(re.search(rx, t, re.M) for rx in STAMP))


def group_links(text: str) -> list[tuple[str, str]]:
    """The group invite links in a text, as (platform, link)."""
    out = []
    for m in re.finditer(r"(https?://)?(signal\.group|chat\.whatsapp\.com|(www\.)?whatsapp\.com/channel|t\.me|telegram\.me|discord\.gg|discord(app)?\.com/invite)/\S*", text or ""):
        link = m.group(0).rstrip(".,;:!?)]'\"")
        link = link if link.startswith("http") else "https://" + link
        c = classify(link)
        if c and c[0] == "group":
            out.append((c[1], link))
    return out


def scrub(text: str) -> str:
    """The announcement as reviewers see it: senders, numbers, emails, @handles and chat links taken out."""
    t = text or ""
    for rx in STAMP:
        t = re.sub(rx, "", t, flags=re.M | re.I)
    t = re.sub(ANY_LINK, "[chat link]", t)
    t = re.sub(EMAIL, "[email]", t)
    t = re.sub(HANDLE, "[@name]", t)
    t = re.sub(PHONE, lambda m: "[number]" if len(re.sub(r"\D", "", m.group(0))) >= 7 else m.group(0), t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def sort_links(rec: dict) -> dict:
    """After the reader: a group link it put under the organiser's page or tickets moves to the chat fields; a link to
    one person is taken out. The depositor then ticks, or removes, the group link before sending."""
    for f in ("website", "tickets_url"):
        c = classify(rec.get(f) or "")
        if not c:
            continue
        link = rec.pop(f)
        if c[0] == "group" and not rec.get("chat_link"):
            rec["chat_link"], rec["chat_platform"] = link, c[1]
        elif c[0] == "person":
            rec.setdefault("chat_platform", c[1])
    return rec
