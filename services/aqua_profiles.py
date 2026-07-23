"""Локальная модель профиля пользователя (имя и адрес для API Narkologia)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AquaProfile:
    profile_id: str
    title: str
    full_name: str
    address: str

    def button_label(self, max_len: int = 48) -> str:
        parts = [p for p in (self.title, self.full_name) if p]
        label = " · ".join(parts) if parts else self.profile_id
        if len(label) > max_len:
            return label[: max_len - 1] + "…"
        return label

    def display_short(self) -> str:
        if self.title:
            return f"{self.title} ({self.profile_id})"
        return self.profile_id
