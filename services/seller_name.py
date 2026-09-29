"""Имя продавца из JSON парсера — правила для валидации email."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Слова короче 4 букв не участвуют в first.last.
# Имя для first.last / генерации: ≥5 букв (не Jan/Hans как first).
# NL/DE/HU: ник с цифрой ≥5 букв; одно слово без цифр ≥8 (mariasto), частые имена — нет.
# HR (Njuškalo): то же ≥5; ник с цифрами считает буквы+цифры (Anaama_08, Ana_08);
#   Имя Фамилия → first.last, каждое слово ≥5 букв.
# CH (Ricardo): ≥4 буквы, одиночное имя (Irene/Hans) — валидируем.
MIN_NAME_TOKEN_LEN = 4
MIN_FIRST_NAME_LEN = 5
MIN_SELLER_LETTERS = 5
MIN_SELLER_LETTERS_CH = 4
MIN_SINGLE_LOCAL_NO_DIGIT = 8


def seller_name_min_letters(country: str | None = None) -> int:
    if (country or "").strip().lower() == "ch":
        return MIN_SELLER_LETTERS_CH
    return MIN_SELLER_LETTERS


def allow_single_first_name(country: str | None = None) -> bool:
    """Одиночное имя/ник тоже валидируем (Hans, Irene, брендовый ник)."""
    _ = country
    return True


def is_ch_name_policy(country: str | None = None) -> bool:
    return (country or "").strip().lower() == "ch"


def is_hr_name_policy(country: str | None = None) -> bool:
    return (country or "").strip().lower() == "hr"


def ch_local_part_variants(name: str) -> list[str]:
    """
    CH/Ricardo: ник/имя → local как есть (jul_2f57, jessica13).
    Единственный отсев — меньше 4 букв во всём имени.
    """
    if seller_name_too_short(name, min_letters=MIN_SELLER_LETTERS_CH):
        return []

    out: list[str] = []
    seen: set[str] = set()

    def _add(local: str) -> None:
        local = re.sub(r"[^a-z0-9._+\-_]", "", (local or "").lower())
        local = local.replace("-", ".")
        local = re.sub(r"\.+", ".", local).strip("._")
        if not local or local in seen:
            return
        if sum(1 for c in local if c.isalpha()) < MIN_SELLER_LETTERS_CH:
            return
        if len(local) > 64:
            return
        seen.add(local)
        out.append(local)

    for raw in seller_name_ascii_forms(name):
        if not raw:
            continue
        # hyphen/пробел → точка: Kenwoodcarhifi-Marine, Allgae - TOM
        _add(re.sub(r"[\s\-]+", ".", raw))
        compact = re.sub(r"[\s\-]+", "", raw)
        cleaned = re.sub(r"[^A-Za-z0-9._]", "", compact)
        _add(cleaned)
        _add(re.sub(r"[^A-Za-z0-9._]", "", re.sub(r"[\s\-]+", "_", raw)))
        if "_" in cleaned:
            _add(cleaned.replace("_", "."))

        parts = [p for p in re.split(r"[\s\-_]+", raw) if p.strip()]
        alpha_parts = []
        for p in parts:
            core = re.sub(r"[^A-Za-z0-9]", "", p)
            if core and sum(1 for c in core if c.isalpha()) >= 2:
                alpha_parts.append(core.lower())
        if len(alpha_parts) >= 2:
            first, last = alpha_parts[0], alpha_parts[-1]
            _add(f"{first}.{last}")
            _add(f"{first}{last}")
            _add(f"{first}_{last}")
        elif len(alpha_parts) == 1:
            _add(alpha_parts[0])

    return out

# Однословные local-part: бренды, города NL, бизнес-слова — не пробиваем.
_BLOCKED_SINGLE_LOCALS = frozenset(
    {
        # бренды / авто / магазин
        "auto",
        "audi",
        "bmw",
        "ford",
        "toyota",
        "volvo",
        "opel",
        "garage",
        "shop",
        "store",
        "markt",
        "marktplaats",
        "motors",
        "motor",
        "automotive",
        "autobedrijf",
        "autogroep",
        "autocentrum",
        "dealer",
        "dealers",
        "parts",
        "mobility",
        "vintage",
        "antique",
        "boutique",
        "service",
        "services",
        "company",
        "handel",
        "handelsonderneming",
        "onderneming",
        "verkoop",
        "verhuur",
        "online",
        "official",
        "info",
        "contact",
        "admin",
        "sales",
        "support",
        "noreply",
        "mail",
        "email",
        "test",
        "tester",
        "private",
        "prive",
        "particulier",
        "hobby",
        "hobbyist",
        # бизнес / роль / «магазинное» слово как ник
        "specialist",
        "juweliers",
        "juwelier",
        "boekhandel",
        "kantoor",
        "products",
        "product",
        "used",
        "groep",
        "group",
        "centrum",
        "bedrijf",
        "design",
        "meubilair",
        "transport",
        "cars",
        "car",
        "exclusive",
        "xclusive",
        "speelgoed",
        "kinderspeelgoed",
        "tweewielers",
        "boomkwekerij",
        "kwekerij",
        "mangrove",
        "schuurtje",
        "tropisch",
        "ruimt",
        "lifestyle",
        "benelux",
        "alarmering",
        "personenalarmering",
        "designmeubilair",
        "waalwijk",
        "hoofddorp",
        "katwijk",
        "leudal",
        "brabant",
        "zuithof",
        "biemans",
        "digo",
        # частые города NL (как ник на MP)
        "amsterdam",
        "rotterdam",
        "utrecht",
        "eindhoven",
        "tilburg",
        "groningen",
        "breda",
        "nijmegen",
        "haarlem",
        "arnhem",
        "amersfoort",
        "apeldoorn",
        "zaandam",
        "leiden",
        "dordrecht",
        "zwolle",
        "maastricht",
        "delft",
        "alkmaar",
        "hilversum",
        "leeuwarden",
        "denhaag",
        "haag",
        "almere",
        "haarlemmer",
        "enschede",
        "venlo",
        "heerlen",
        "helmond",
        "oss",
        "emmen",
        "deventer",
        "borne",
        # HU / Jófogás юрлица
        "kft",
        "zrt",
        "nyrt",
        "bt",
        "kftzrt",
    }
)

# Частые имена: как единственный local на gmail/hotmail SMTP почти всегда врёт.
_COMMON_FIRST_NAME_LOCALS = frozenset(
    {
        "jan",
        "henk",
        "hans",
        "piet",
        "kees",
        "jos",
        "rob",
        "tim",
        "tom",
        "bas",
        "rick",
        "mark",
        "paul",
        "peter",
        "john",
        "mike",
        "anna",
        "anne",
        "emma",
        "lisa",
        "sara",
        "sarah",
        "maria",
        "marie",
        "laura",
        "linda",
        "susan",
        "sandra",
        "monique",
        "ingrid",
        "anita",
        "carla",
        "diana",
        "ellen",
        "irene",
        "joyce",
        "karen",
        "nancy",
        "patricia",
        "angela",
        "amanda",
        "andrea",
        "albert",
        "alexander",
        "alex",
        "andrew",
        "anthony",
        "antonio",
        "arthur",
        "astrid",
        "barbara",
        "benjamin",
        "bernard",
        "bert",
        "brian",
        "bruce",
        "bryan",
        "carl",
        "carlos",
        "carol",
        "caroline",
        "catherine",
        "charles",
        "chris",
        "christian",
        "christina",
        "christine",
        "christopher",
        "claire",
        "clara",
        "claude",
        "claus",
        "colin",
        "daniel",
        "danny",
        "david",
        "dennis",
        "derek",
        "diane",
        "dirk",
        "donald",
        "douglas",
        "edward",
        "edwin",
        "eric",
        "erik",
        "ernest",
        "eugene",
        "eva",
        "eve",
        "felix",
        "fernando",
        "francis",
        "frank",
        "franz",
        "fred",
        "frederick",
        "frederik",
        "frederih",
        "friedrich",
        "fritz",
        "gabriel",
        "gerhard",
        "gertrud",
        "gisela",
        "heinrich",
        "heinz",
        "helga",
        "herbert",
        "hildegard",
        "horst",
        "ingeborg",
        "johann",
        "josef",
        "klaus",
        "manfred",
        "matthias",
        "norbert",
        "renate",
        "sabine",
        "ursula",
        "werner",
        "wolfgang",
        "gary",
        "george",
        "gerald",
        "giovanni",
        "glenn",
        "gordon",
        "gregory",
        "harold",
        "harry",
        "harvey",
        "helen",
        "helmut",
        "henry",
        "herman",
        "howard",
        "hugo",
        "ian",
        "ivan",
        "jack",
        "jacob",
        "jacques",
        "james",
        "jason",
        "jeffrey",
        "jennifer",
        "jeremy",
        "jerry",
        "jesse",
        "jessica",
        "jim",
        "jimmy",
        "joe",
        "joel",
        "johan",
        "johannes",
        "john",
        "johnny",
        "jonathan",
        "jordan",
        "jose",
        "joseph",
        "josh",
        "joshua",
        "juan",
        "judith",
        "julia",
        "julian",
        "julie",
        "justin",
        "karl",
        "kate",
        "katherine",
        "kathleen",
        "keith",
        "kelly",
        "kenneth",
        "kevin",
        "kim",
        "kyle",
        "larry",
        "lawrence",
        "lee",
        "leo",
        "leon",
        "leonard",
        "leroy",
        "leslie",
        "lewis",
        "louis",
        "lucas",
        "luis",
        "luke",
        "manuel",
        "marc",
        "marcel",
        "marco",
        "marcus",
        "margaret",
        "maria",
        "marianne",
        "marie",
        "mario",
        "marion",
        "mark",
        "martin",
        "martina",
        "marvin",
        "mary",
        "matthew",
        "maureen",
        "maurice",
        "max",
        "megan",
        "melissa",
        "michael",
        "michelle",
        "miguel",
        "mike",
        "mohamed",
        "mohammed",
        "monica",
        "nathan",
        "neil",
        "nicholas",
        "nick",
        "nicole",
        "nina",
        "norman",
        "oliver",
        "olivia",
        "oscar",
        "patrick",
        "paul",
        "paula",
        "pedro",
        "peter",
        "philip",
        "philippe",
        "phillip",
        "pierre",
        "ralph",
        "ramon",
        "randy",
        "raymond",
        "rebecca",
        "rene",
        "ricardo",
        "richard",
        "rick",
        "robert",
        "robin",
        "roger",
        "roland",
        "ronald",
        "roy",
        "ruben",
        "russell",
        "ruth",
        "ryan",
        "samuel",
        "sandra",
        "santiago",
        "scott",
        "sean",
        "sebastian",
        "sergio",
        "sharon",
        "shirley",
        "simon",
        "sophia",
        "stefan",
        "stephanie",
        "stephen",
        "steve",
        "steven",
        "stuart",
        "susan",
        "suzanne",
        "thomas",
        "timothy",
        "tina",
        "todd",
        "tony",
        "travis",
        "tyler",
        "victor",
        "victoria",
        "vincent",
        "virginia",
        "walter",
        "wayne",
        "wendy",
        "william",
        "willie",
        "willy",
        "wilson",
        "wim",
        "wolfgang",
        "zachary",
        # NL частые
        "anneke",
        "annelot",
        "anneloes",
        "angeline",
        "anine",
        "arnoud",
        "aidan",
        "joost",
        "jeroen",
        "marieke",
        "ingrid",
        "maarten",
        "sander",
        "bram",
        "thijs",
        "daan",
        "sem",
        "lucas",
        "finn",
        "noah",
        "liam",
        "milan",
        "luuk",
        "jesse",
        "ruben",
        "stijn",
        "niels",
        "koen",
        "bart",
        "dirk",
        "gerrit",
        "hendrik",
        "willem",
        "cornelis",
        "johannes",
        "pieter",
        "franciscus",
        "antonius",
        "marinus",
        "adrianus",
        "wilhelmus",
        "petronella",
        "johanna",
        "maria",
        "anna",
        "cornelia",
        "wilhelmina",
        "hendrika",
        "catharina",
        "geertruida",
        "elizabeth",
        "alida",
        "joanna",
        "christina",
        "margaretha",
        "andrea",
        "albert",
        "arthur",
        "astrid",
        "berry",
        "bruno",
        "eddy",
        "ella",
        "gast",
        "inge",
        "joana",
        "jutte",
        "nena",
        "nikki",
        "reiss",
        "roos",
        "tamara",
        "toine",
        "vic",
        "wies",
        "frans",
        "karin",
        "diana",
        "hans",
        "henk",
        "jan",
        "mar",
    }
)


def is_business_token(token: str) -> bool:
    s = re.sub(r"[^a-z0-9]", "", (token or "").lower())
    return bool(s) and (s in _BLOCKED_SINGLE_LOCALS or is_blocked_single_local(s))


def is_common_first_name_local(local: str) -> bool:
    s = re.sub(r"[^a-z]", "", (local or "").lower())
    return s in _COMMON_FIRST_NAME_LOCALS


def is_blocked_single_local(local: str) -> bool:
    s = re.sub(r"[^a-z0-9]", "", (local or "").lower())
    if not s:
        return True
    if s in _BLOCKED_SINGLE_LOCALS:
        return True
    # denhaag / den-haag уже в списке; "denhaag123" тоже режем по префиксу города
    for city in (
        "amsterdam",
        "rotterdam",
        "amersfoort",
        "apeldoorn",
        "eindhoven",
        "utrecht",
        "groningen",
        "haarlem",
        "arnhem",
    ):
        if s.startswith(city) and len(s) <= len(city) + 3:
            return True
    return False


def is_usable_single_local(
    local: str,
    *,
    min_letters: int = MIN_SELLER_LETTERS,
    allow_common_first: bool = False,
    count_digits: bool = False,
) -> bool:
    """
    Одно слово как email-local.
    С цифрой (ник): ≥ min_letters букв; HR — буквы+цифры вместе.
    Без цифр (strict): ≥8, не бренд/город/частое имя.
    CH (allow_common_first): ≥ min_letters (обычно 4), частые имена ок, бренды/города — нет.
    """
    raw = (local or "").strip().lower()
    if not raw or "." in raw or "+" in raw:
        return False
    s = re.sub(r"[^a-z0-9_]", "", raw)
    if not s:
        return False
    letters = sum(1 for c in s if c.isalpha())
    digits = sum(1 for c in s if c.isdigit())
    has_digit = digits > 0
    if is_blocked_single_local(s):
        return False
    if has_digit:
        weight = letters + digits if count_digits else letters
        return weight >= int(min_letters)
    floor = int(min_letters) if allow_common_first else MIN_SINGLE_LOCAL_NO_DIGIT
    if letters < floor:
        return False
    if not allow_common_first and is_common_first_name_local(s):
        return False
    return True


_PARSER_PLACEHOLDER_NAMES = frozenset(
    {
        "частное лицо",
        "частное",
        "maganszemely",
        "magánszemély",
        "magan szemely",
        "private person",
        "private",
        "particulier",
        "anonim",
        "anonymous",
        "unknown",
        "privatna osoba",
        "privatnaosoba",
        "fizicka osoba",
        "fizička osoba",
        "fizickaosoba",
        "n/a",
        "na",
        "-",
        ".",
    }
)

_COMPANY_NAME_RE = re.compile(
    r"(?i)(?:\b(?:kft|zrt|nyrt|bt|gmbh|ltd|llc|srl|sro|doo)\b|d\.?\s*o\.?\s*o\.?|s\.?\s*r\.?\s*o\.?|www\.|https?://)",
)


def is_parser_placeholder_name(raw: str) -> bool:
    s = " ".join(str(raw or "").strip().lower().split())
    if not s:
        return True
    folded = normalize_seller_name(s).strip().lower()
    compact = re.sub(r"[^a-zа-яё]+", "", folded or s, flags=re.IGNORECASE)
    if s in _PARSER_PLACEHOLDER_NAMES or folded in _PARSER_PLACEHOLDER_NAMES:
        return True
    if compact in {
        "частноелицо",
        "maganszemely",
        "privateperson",
        "privatnaosoba",
        "fizickaosoba",
    }:
        return True
    return False


def is_company_seller_name(raw: str) -> bool:
    s = str(raw or "").strip()
    if not s:
        return False
    if _COMPANY_NAME_RE.search(s):
        return True
    folded = normalize_seller_name(s)
    return bool(folded and _COMPANY_NAME_RE.search(folded))


def person_tokens_for_email(name: str) -> list[str]:
    """Токены похожие на имя/фамилию (без shop/city/business)."""
    out: list[str] = []
    for t in pick_name_tokens_for_email(name):
        if is_business_token(t) or is_blocked_single_local(t):
            continue
        out.append(t)
    return out


def first_name_long_enough(tokens: list[str], *, country: str | None = None) -> bool:
    """First token for first.last: CH ≥4, иначе ≥5 букв.

    HR: два слова (Имя Фамилия) — всегда first.last, даже если имя короче 5 (Ivan Horvat).
    """
    if not tokens:
        return False
    if is_hr_name_policy(country) and len(tokens) >= 2:
        return True
    need = MIN_SELLER_LETTERS_CH if is_ch_name_policy(country) else MIN_FIRST_NAME_LEN
    first = re.sub(r"[^a-z]", "", (tokens[0] or "").lower())
    return len(first) >= need


_MARKT_PROFILE_RENAME_RE = re.compile(
    r"(?:Neu)?Das Mitglied hat vor kurzem den Profilnamen geändert\.?\s*$",
    re.IGNORECASE,
)


def clean_parser_seller_name(raw: str) -> str:
    """Убрать хвост markt.ch и заглушки парсера («Частное лицо»)."""
    s = (raw or "").strip()
    if not s:
        return ""
    s = _MARKT_PROFILE_RENAME_RE.sub("", s).strip()
    if is_parser_placeholder_name(s):
        return ""
    return s


def seller_name_from_item(item: dict[str, Any]) -> str:
    if not isinstance(item, dict):
        return ""
    for key in (
        "item_person_name",
        "seller_name",
        "person_name",
        "seller",
        "name",
    ):
        v = clean_parser_seller_name(str(item.get(key) or ""))
        if v:
            return v
    return ""


def _strip_accents(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


# ö → oe, ä → ae, ü → ue; плюс короткие o/a/u в seller_name_ascii_forms
_LATIN_FOLD = str.maketrans(
    {
        "ö": "oe",
        "Ö": "Oe",
        "ä": "ae",
        "Ä": "Ae",
        "ü": "ue",
        "Ü": "Ue",
        "ë": "e",
        "Ë": "E",
        "é": "e",
        "è": "e",
        "ê": "e",
        "á": "a",
        "à": "a",
        "â": "a",
        "í": "i",
        "ì": "i",
        "î": "i",
        "ó": "o",
        "ò": "o",
        "ô": "o",
        "ú": "u",
        "ù": "u",
        "û": "u",
        "ñ": "n",
        "ç": "c",
        "ø": "o",
        "Ø": "O",
        "å": "a",
        "Å": "A",
        "æ": "ae",
        "Æ": "AE",
        "œ": "oe",
        "Œ": "OE",
        "ß": "ss",
        "ẞ": "SS",
        # RO / AT / DE: ș ţ ă → ascii (на случай если NFD не сработал)
        "ș": "s",
        "Ș": "S",
        "ş": "s",
        "Ş": "S",
        "ț": "t",
        "Ț": "T",
        "ţ": "t",
        "Ţ": "T",
        "ă": "a",
        "Ă": "A",
        "ő": "o",
        "Ő": "O",
        "ű": "u",
        "Ű": "U",
        "đ": "d",
        "Đ": "D",
        "č": "c",
        "Č": "C",
        "ć": "c",
        "Ć": "C",
        "š": "s",
        "Š": "S",
        "ž": "z",
        "Ž": "Z",
    }
)

# Dr. / Prof. / Mag. — не first token для email (иначе Dr. Michael X → dr.x)
_NAME_HONORIFIC_TOKENS = frozenset(
    {
        "dr",
        "drs",
        "prof",
        "professor",
        "mag",
        "magister",
        "ing",
        "ingenieur",
        "dipl",
        "dipling",
        "phd",
        "mba",
        "ba",
        "ma",
        "msc",
        "bsc",
        "mr",
        "mrs",
        "ms",
        "miss",
        "mister",
        "herr",
        "frau",
        "fr",
        "sr",
        "jr",
        "med",
        "dent",
        "vet",
        "hc",
        "rer",
        "nat",
        "phil",
        "llc",
        "gmbh",
        "og",
        "kg",
    }
)


def is_name_honorific_token(token: str) -> bool:
    s = re.sub(r"[^a-z]", "", (token or "").lower())
    return bool(s) and s in _NAME_HONORIFIC_TOKENS


def strip_name_honorifics(raw: str) -> str:
    """Убрать Dr./Prof./Mag. из начала (и одиночные титулы в середине)."""
    s = " ".join(str(raw or "").strip().split())
    if not s:
        return ""
    parts = re.split(r"[\s]+", s)
    kept: list[str] = []
    for p in parts:
        core = re.sub(r"[^A-Za-zÀ-ÿ]", "", p)
        if is_name_honorific_token(core):
            continue
        kept.append(p)
    return " ".join(kept).strip() or s


_LATIN_FOLD_SHORT = str.maketrans(
    {
        "ö": "o",
        "Ö": "O",
        "ä": "a",
        "Ä": "A",
        "ü": "u",
        "Ü": "U",
        "ë": "e",
        "Ë": "E",
        "é": "e",
        "è": "e",
        "ê": "e",
        "á": "a",
        "à": "a",
        "â": "a",
        "í": "i",
        "ì": "i",
        "î": "i",
        "ó": "o",
        "ò": "o",
        "ô": "o",
        "ú": "u",
        "ù": "u",
        "û": "u",
        "ñ": "n",
        "ç": "c",
        "ø": "o",
        "Ø": "O",
        "å": "a",
        "Å": "A",
        "æ": "ae",
        "Æ": "AE",
        "œ": "oe",
        "Œ": "OE",
        "ß": "ss",
        "ẞ": "SS",
        "ș": "s",
        "Ș": "S",
        "ş": "s",
        "Ş": "S",
        "ț": "t",
        "Ț": "T",
        "ţ": "t",
        "Ţ": "T",
        "ă": "a",
        "Ă": "A",
        "ő": "o",
        "Ő": "O",
        "ű": "u",
        "Ű": "U",
        "đ": "d",
        "Đ": "D",
        "č": "c",
        "Č": "C",
        "ć": "c",
        "Ć": "C",
        "š": "s",
        "Š": "S",
        "ž": "z",
        "Ž": "Z",
    }
)


def _ascii_fold_name(raw: str, table: dict | str) -> str:
    s = " ".join(str(raw or "").strip().split())
    if not s:
        return ""
    s = s.translate(table)
    s = _strip_accents(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s.replace("'", "'").replace("`", "'")


def seller_name_ascii_forms(raw: str) -> list[str]:
    """ascii-формы имени: Allgäu → Allgae и Allgau."""
    base = strip_name_honorifics(raw)
    out: list[str] = []
    seen: set[str] = set()
    for table in (_LATIN_FOLD, _LATIN_FOLD_SHORT):
        s = _ascii_fold_name(base, table)
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def normalize_seller_name(raw: str) -> str:
    forms = seller_name_ascii_forms(raw)
    return forms[0] if forms else ""


def pick_name_tokens_for_email(name: str) -> list[str]:
    """
    Токены для local-part: пара слов предпочтительнее (Jan Vries → jan + vries),
    даже если имя короче 4 букв; одиночное длинное слово — как есть.
    """
    long_t = pick_name_tokens(name, min_len=MIN_NAME_TOKEN_LEN)
    if len(long_t) >= 2:
        return long_t
    short_t = pick_name_tokens(name, min_len=2)
    if len(short_t) >= 2:
        return short_t
    if long_t:
        return long_t
    return short_t


def pick_name_tokens(name: str, *, min_len: int = MIN_NAME_TOKEN_LEN) -> list[str]:
    """Буквенные части имени (каждая >= min_len символов, только буквы)."""
    s = normalize_seller_name(strip_name_honorifics(name))
    if not s:
        return []

    s2 = re.sub(r"[^A-Za-z0-9.\s'\-]", " ", s)
    parts = re.split(r"[\s\-']+", s2.strip())

    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        p = p.strip(".")
        if is_name_honorific_token(p):
            continue
        if len(p) >= min_len and p.isalpha():
            pl = p.lower()
            if pl not in seen:
                seen.add(pl)
                out.append(pl)
    return out


def seller_name_letter_count(name: str) -> int:
    return sum(1 for c in normalize_seller_name(name) if c.isalpha())


def seller_name_digit_count(name: str) -> int:
    return sum(1 for c in normalize_seller_name(name) if c.isdigit())


def seller_name_weight(name: str, *, count_digits: bool = False) -> int:
    letters = seller_name_letter_count(name)
    if count_digits:
        return letters + seller_name_digit_count(name)
    return letters


def seller_name_too_short(
    name: str,
    *,
    min_letters: int = MIN_SELLER_LETTERS,
    count_digits: bool = False,
) -> bool:
    """Меньше min_letters букв (HR-ник: буквы+цифры) — не валидируем."""
    if not (name or "").strip():
        return True
    return seller_name_weight(name, count_digits=count_digits) < int(min_letters)


def _is_handle_token(
    h: str,
    *,
    min_letters: int = MIN_SELLER_LETTERS,
    count_digits: bool = False,
) -> bool:
    """Ник: Bird19, mar_l5z6, Anaama_08 — буквы/цифры/_, ≥min_letters."""
    if len(h) < min_letters or len(h) > 64:
        return False
    if not re.fullmatch(r"[A-Za-z0-9_]+", h):
        return False
    if seller_name_too_short(h, min_letters=min_letters, count_digits=count_digits):
        return False
    if is_blocked_single_local(h):
        return False
    return any(c.isalpha() for c in h)


def pick_handle_locals(
    name: str,
    *,
    min_letters: int = MIN_SELLER_LETTERS,
    allow_common_first: bool = False,
    count_digits: bool = False,
) -> list[str]:
    """
    Никнеймы как в JSON: Bird19, mar_l5z6, Anaama_08 — local-part как есть (lower).
    Имя «Имя Фамилия» сюда не попадает (только first.last).
    """
    s = normalize_seller_name(name)
    if not s or seller_name_too_short(
        s, min_letters=min_letters, count_digits=count_digits
    ):
        return []

    parts = [p for p in re.split(r"[\s\-']+", s) if p.strip()]
    out: list[str] = []
    seen: set[str] = set()
    single_part = len(parts) <= 1

    for p in parts:
        h = re.sub(r"[^A-Za-z0-9_]", "", p)
        if not _is_handle_token(h, min_letters=min_letters, count_digits=count_digits):
            continue
        looks_like_nick = single_part or any(c.isdigit() for c in h) or "_" in h
        if not looks_like_nick:
            continue
        hl = h.lower()
        if not is_usable_single_local(
            hl,
            min_letters=min_letters,
            allow_common_first=allow_common_first,
            count_digits=count_digits,
        ):
            continue
        if hl not in seen:
            seen.add(hl)
            out.append(hl)
    return out


def seller_name_eligible_for_validation(
    name: str,
    *,
    min_token_len: int = MIN_NAME_TOKEN_LEN,
    country: str | None = None,
) -> bool:
    """Имя подходит: CH — ≥4 букв; иначе ник/имя по strict-политике или пара person-токенов."""
    if is_ch_name_policy(country):
        return not seller_name_too_short(name, min_letters=MIN_SELLER_LETTERS_CH)

    if is_parser_placeholder_name(name) or is_company_seller_name(name):
        return False
    min_letters = seller_name_min_letters(country)
    allow_cf = allow_single_first_name(country)
    count_digits = is_hr_name_policy(country)
    if seller_name_too_short(
        name, min_letters=min_letters, count_digits=count_digits
    ):
        return False
    if pick_handle_locals(
        name,
        min_letters=min_letters,
        allow_common_first=allow_cf,
        count_digits=count_digits,
    ):
        return True
    person = person_tokens_for_email(name)
    if len(person) >= 2:
        return first_name_long_enough(person, country=country)
    if len(person) == 1 and is_usable_single_local(
        person[0],
        min_letters=min_letters,
        allow_common_first=allow_cf,
        count_digits=count_digits,
    ):
        return True
    return False
