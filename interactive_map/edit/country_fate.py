"""Record active/inactive country tag transitions on edit results."""

from __future__ import annotations

from collections.abc import Iterable


def note_country_destroyed(payload: dict, tag: str) -> None:
    tag = str(tag)
    if not tag:
        return
    tags = list(payload.get("countries_destroyed") or [])
    if tag not in tags:
        tags.append(tag)
        payload["countries_destroyed"] = sorted(tags)


def note_country_restored(payload: dict, tag: str) -> None:
    tag = str(tag)
    if not tag:
        return
    tags = list(payload.get("countries_restored") or [])
    if tag not in tags:
        tags.append(tag)
        payload["countries_restored"] = sorted(tags)


def note_annexed_tags(payload: dict, tags: Iterable[str]) -> None:
    for tag in tags:
        note_country_destroyed(payload, str(tag))


def country_fate(payload: dict) -> tuple[list[str], list[str]]:
    destroyed = sorted(payload.get("countries_destroyed") or [])
    restored = sorted(payload.get("countries_restored") or [])
    return destroyed, restored


def has_country_fate(payload: dict) -> bool:
    destroyed, restored = country_fate(payload)
    return bool(destroyed or restored)
