"""Личный ЧС имён продавцов (на пользователя).

- SellerBlacklist: после успешного подбора email — имя больше не гоняем через API.
- При активной рассылке дополнительно person_name из Offer (доп. рассылка без повторной валидации).
- В одном VOID-файле: только первый лот с данным именем продавца идёт в API; email копируется на все его лоты при сохранении.
"""

from __future__ import annotations

from sqlalchemy import delete as sa_delete, func, select as sa_select

from models import Offer, OfferEmail, SellerBlacklist
from services.seller_name import normalize_seller_name, seller_name_from_item


def seller_name_key(raw: str) -> str:
    """Ключ для сравнения: Maria Johansen → maria johansen."""
    return normalize_seller_name(raw).strip().lower()


def seller_name_key_from_item(item: dict) -> str:
    return seller_name_key(seller_name_from_item(item))


async def load_seller_name_keys(
    session,
    user_id: int,
    *,
    include_offer_names: bool = True,
) -> set[str]:
    """Имена продавцов, которых уже не валидируем: ЧС в БД + опционально person_name из офферов."""
    keys: set[str] = set()
    rows = (
        await session.execute(
            sa_select(SellerBlacklist.seller_name_key).where(SellerBlacklist.user_id == int(user_id))
        )
    ).all()
    for (k,) in rows:
        if k:
            keys.add(str(k).strip().lower())

    if not include_offer_names:
        return keys

    off_names = (
        await session.execute(
            sa_select(Offer.person_name)
            .where(Offer.user_id == int(user_id))
            .where(Offer.person_name.is_not(None))
            .distinct()
        )
    ).all()
    for (nm,) in off_names:
        key = seller_name_key(str(nm or ""))
        if key:
            keys.add(key)
    return keys


async def is_seller_name_blacklisted(session, user_id: int, seller_name: str) -> bool:
    key = seller_name_key(seller_name)
    if not key:
        return False
    row = (
        await session.execute(
            sa_select(SellerBlacklist.id)
            .where(SellerBlacklist.user_id == int(user_id))
            .where(func.lower(SellerBlacklist.seller_name_key) == key)
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def add_seller_name_blacklist(
    session,
    user_id: int,
    seller_name: str,
) -> bool:
    key = seller_name_key(seller_name)
    if not key:
        return False
    if await is_seller_name_blacklisted(session, user_id, seller_name):
        return False
    display = normalize_seller_name(seller_name).strip() or key
    session.add(
        SellerBlacklist(
            user_id=int(user_id),
            seller_name_key=key,
            seller_name_display=display,
        )
    )
    await session.flush()
    return True


async def load_seller_keys_with_validated_email(session, user_id: int) -> set[str]:
    """Имена продавцов с почтой: OfferEmail или validated_emails в raw_json.

    После /reset очередь OfferEmail пустая, но лот в offers остаётся — имя
    нельзя считать «пустым» и нельзя вечно держать только в ЧС без записи.
    """
    from services.offer_storage import offer_raw_has_validated_email, parse_offer_raw

    keys: set[str] = set()
    emailed_ids: set[int] = set()
    email_rows = (
        await session.execute(
            sa_select(OfferEmail.offer_id)
            .join(Offer, Offer.id == OfferEmail.offer_id)
            .where(Offer.user_id == int(user_id))
        )
    ).all()
    for (oid,) in email_rows:
        try:
            emailed_ids.add(int(oid))
        except (TypeError, ValueError):
            pass

    rows = (
        await session.execute(
            sa_select(Offer.id, Offer.person_name, Offer.raw_json).where(
                Offer.user_id == int(user_id)
            )
        )
    ).all()
    for oid, pname, raw_json in rows:
        has_mail = False
        try:
            has_mail = int(oid) in emailed_ids
        except (TypeError, ValueError):
            has_mail = False
        if not has_mail and not offer_raw_has_validated_email(raw_json):
            continue
        key = seller_name_key(str(pname or ""))
        if not key and raw_json:
            raw = parse_offer_raw(raw_json)
            key = seller_name_key_from_item(raw if isinstance(raw, dict) else {})
        if key:
            keys.add(key)
    return keys


async def prune_seller_blacklist_without_email(
    session,
    user_id: int,
    *,
    keep_keys: set[str],
) -> int:
    """ЧС без живой почты — после wipe/reset такие имена снова идут в API."""
    keep = {str(k or "").strip().lower() for k in (keep_keys or set()) if str(k or "").strip()}
    rows = (
        await session.execute(
            sa_select(SellerBlacklist.seller_name_key).where(
                SellerBlacklist.user_id == int(user_id)
            )
        )
    ).all()
    stale = [
        str(k).strip().lower()
        for (k,) in rows
        if k and str(k).strip().lower() not in keep
    ]
    if not stale:
        return 0
    await session.execute(
        sa_delete(SellerBlacklist).where(
            SellerBlacklist.user_id == int(user_id),
            func.lower(SellerBlacklist.seller_name_key).in_(stale),
        )
    )
    await session.flush()
    return len(stale)


async def add_seller_name_blacklist_bulk(
    session,
    user_id: int,
    name_keys: set[str] | list[str],
) -> int:
    """Один SELECT + bulk insert имён (без N запросов на каждое имя)."""
    keys = {str(k or "").strip().lower() for k in (name_keys or []) if str(k or "").strip()}
    if not keys:
        return 0
    rows = (
        await session.execute(
            sa_select(SellerBlacklist.seller_name_key).where(
                SellerBlacklist.user_id == int(user_id)
            )
        )
    ).all()
    existing = {str(r[0]).strip().lower() for r in rows if r[0]}
    added = 0
    for key in sorted(keys):
        if key in existing:
            continue
        session.add(
            SellerBlacklist(
                user_id=int(user_id),
                seller_name_key=key,
                seller_name_display=key,
            )
        )
        added += 1
    if added:
        await session.flush()
    return added
