# SPDX-License-Identifier: AGPL-3.0-only
"""Forge Neo Large Collection Helper — LoRA card pagination and directory index.

This module is loaded by Forge's normal extension script loader. It changes no core files.
It is intentionally restricted to the built-in LoRA Extra Networks page.
"""

from __future__ import annotations

import html
import os
import random
import re
import threading
import weakref
from pathlib import Path
from typing import Any

import gradio as gr
from fastapi import HTTPException

from modules import script_callbacks, shared, ui_extra_networks

OPT_BATCH = "lch_lora_batch_size"
OPT_DELAY = "lch_search_debounce_ms"
OPT_DIR_HEIGHT = "lch_mobile_dirs_height_px"
OPT_CARD_HEIGHT = "lch_mobile_cards_height_dvh"

_ORIGINAL_CREATE_HTML = ui_extra_networks.ExtraNetworksPage.create_html
_ORIGINAL_CARD_VIEW = ui_extra_networks.ExtraNetworksPage.create_card_view_html
_ORIGINAL_DIRS_VIEW = ui_extra_networks.ExtraNetworksPage.create_dirs_view_html
_ORIGINAL_TREE_VIEW = ui_extra_networks.ExtraNetworksPage.create_tree_view_html
_PATCHED = False


def _option_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        v = int(str(getattr(shared.opts, name, default)).strip())
        return v if minimum <= v <= maximum else default
    except (ValueError, TypeError):
        return default


def batch_size() -> int:
    """Any positive integer or -1; invalid values fall back to 150."""
    try:
        value = int(str(getattr(shared.opts, OPT_BATCH, "150")).strip())
        return value if value == -1 or value > 0 else 150
    except (TypeError, ValueError):
        return 150


def _is_lora(page: Any) -> bool:
    return getattr(page, "extra_networks_tabname", "").casefold() in {"lora", "loras"}


def _norm_folder(folder: str) -> str:
    return str(folder or "").replace("\\", "/").strip("/ ").casefold()


def _relative_file(filename: str, roots: tuple[str, ...]) -> str:
    if not filename:
        return ""
    path = os.path.abspath(filename)
    # Prefer the longest root so nested roots are resolved unambiguously.
    for root in sorted(roots, key=len, reverse=True):
        try:
            if os.path.commonpath([path, root]) == root:
                return os.path.relpath(path, root).replace("\\", "/")
        except (ValueError, OSError):
            pass
    return Path(path).name


class Entry:
    """An indexed LoRA. Plain classes are required for Forge's script loader.

    Forge executes extension modules without adding them to sys.modules first.
    Python 3.13's dataclasses may fail in that situation when annotations are
    postponed. A small slotted class also keeps the index compact.
    """

    __slots__ = ("item", "name", "folder", "searchable", "hidden", "sd_version", "sort_keys")

    def __init__(self, item: dict, name: str, folder: str, searchable: str,
                 hidden: bool, sd_version: str, sort_keys: dict):
        self.item = item
        self.name = name
        self.folder = folder
        self.searchable = searchable
        self.hidden = hidden
        self.sd_version = sd_version
        self.sort_keys = sort_keys


class Snapshot:
    def __init__(self, page: Any, entries: list[Entry], revision: int, folders: list[str]):
        # WeakKeyDictionary cannot release a page if its value holds a strong
        # reference back to that page (large snapshots would leak on reload).
        self.page = weakref.proxy(page) if page is not None else None
        self.entries = entries
        self.revision = revision
        self.folders = folders
        # Only keep a handful of sorts; searching filters already sorted entries.
        self.sorts: dict[tuple[str, bool, int], list[Entry]] = {}
        self.lock = threading.RLock()

    def sorted_entries(self, key: str, descending: bool, seed: int) -> list[Entry]:
        sort_id = (key, descending, seed if key == "random" else 0)
        with self.lock:
            if sort_id in self.sorts:
                return self.sorts[sort_id]
            entries = self.entries.copy()
            if key == "random":
                random.Random(seed).shuffle(entries)
            elif key == "default":
                # The native Path button is data-sortkey="default", but Forge's
                # get_sort_keys() actually provides "path", not "default".
                # Sort the ENTIRE index before slicing pages: sorting the visible
                # batch alone can make it look as though entries were skipped.
                entries.sort(key=lambda e: (
                    str(e.sort_keys.get("path", e.item.get("filename", e.name))).casefold(),
                    e.name.casefold(),
                ))
            else:
                def sort_value(e: Entry):
                    field_name = "date_created" if key == "date_created" else "date_modified" if key == "date_modified" else "name"
                    value = e.sort_keys.get(field_name, e.name)
                    if field_name.startswith("date_"):
                        try:
                            return int(value)
                        except (ValueError, TypeError):
                            return 0
                    return str(value).casefold()
                entries.sort(key=sort_value)
            if descending:
                entries.reverse()
            # Constrain cache even when many random seeds are requested.
            if len(self.sorts) >= 8:
                self.sorts.pop(next(iter(self.sorts)))
            self.sorts[sort_id] = entries
            return entries


class Index:
    def __init__(self):
        self.lock = threading.RLock()
        self._snapshots = weakref.WeakKeyDictionary()
        self._revision = 0

    def capture(self, page: Any) -> Snapshot:
        # Called when Forge's native create_html has already done list_items,
        # created self.items and populated the per-item user metadata.
        with self.lock:
            roots = tuple(os.path.abspath(p) for p in page.allowed_directories_for_previews())
            entries = []
            folder_set = set()
            for item in page.items.values():
                filename = str(item.get("filename", ""))
                rel = _relative_file(filename, roots)
                folder = rel.rsplit("/", 1)[0] if "/" in rel else ""
                bits = folder.split("/") if folder else []
                if not getattr(shared.opts, "extra_networks_show_hidden_directories", False) and any(p.startswith(".") for p in bits):
                    # Still index the model, just omit its hidden folder buttons.
                    pass
                else:
                    for i in range(1, len(bits) + 1):
                        folder_set.add("/".join(bits[:i]))
                name = str(item.get("name", ""))
                terms = item.get("search_terms") or []
                if isinstance(terms, str):
                    terms = [terms]
                desc = (item.get("description") or "") if getattr(shared.opts, "extra_networks_card_show_desc", True) else ""
                searchable = " ".join((name, rel, " ".join(map(str, terms)), str(desc))).casefold()
                # Mirrors Forge's hidden-model search-only rule.
                is_hidden = any(segment.startswith(".") for segment in rel.replace("\\", "/").split("/")[:-1])
                is_hidden |= Path(rel).name.startswith(".")
                keys = item.get("sort_keys") or {}
                entries.append(Entry(item, name, _norm_folder(folder), searchable, is_hidden, str(item.get("sd_version_str", "SdVersion.Unknown")), keys))
            self._revision += 1
            snapshot = Snapshot(page, entries, self._revision, sorted(folder_set, key=str.casefold))
            self._snapshots[page] = snapshot
            return snapshot

    def get(self, page: Any) -> Snapshot | None:
        with self.lock:
            return self._snapshots.get(page)


INDEX = Index()


def _active_snapshot(page):
    return INDEX.get(page) or INDEX.capture(page)


def patched_html(self, tabname: str, *, empty=False):
    # Mark the pane itself. Forge's existing applySort() clears the contents of
    # the card container, so a marker *inside* the container is not reliable.
    result = _ORIGINAL_CREATE_HTML(self, tabname, empty=empty)
    if _is_lora(self) and batch_size() != -1 and not empty:
        marker = f"id='{tabname}_{self.extra_networks_tabname}_pane'"
        result = result.replace(marker, marker + ' data-lch-paged="1"', 1)
    return result


def patched_card_view(self, tabname: str, *, none_message):
    if not _is_lora(self) or batch_size() == -1 or none_message == "Loading...":
        return _ORIGINAL_CARD_VIEW(self, tabname, none_message=none_message)
    INDEX.capture(self)
    # No cards and no 50,000-node Gradio HTML payload on initial load.
    return '<div class="lch-placeholder" role="status">Loading LoRA cards…</div>'


def patched_dirs_view(self, tabname: str):
    if not _is_lora(self) or batch_size() == -1:
        return _ORIGINAL_DIRS_VIEW(self, tabname)
    snapshot = _active_snapshot(self)
    # No directory filesystem walk: folder names are already in the index.
    buttons = [("", "all")] + [(folder, folder + "/") for folder in snapshot.folders]
    return "".join(
        f'<button class="lg secondary gradio-button custom-button{(" search-all" if not folder else "")}" '
        f'data-lch-folder="{html.escape(folder, quote=True)}" '
        f'onclick="extraNetworksSearchButton(\'{tabname}\', \'{self.extra_networks_tabname}\', event)">'
        f'{html.escape(label)}</button>' for folder, label in buttons
    )


def patched_tree_view(self, tabname: str):
    if not _is_lora(self) or batch_size() == -1:
        return _ORIGINAL_TREE_VIEW(self, tabname)
    snapshot = _active_snapshot(self)
    root = {}
    for folder in snapshot.folders:
        cur = root
        for component in folder.split("/"):
            cur = cur.setdefault(component, {})

    def render_tree(tree: dict, prefix: str = "") -> str:
        content = []
        for part, children in sorted(tree.items(), key=lambda pair: pair[0].casefold()):
            path = f"{prefix}/{part}".strip("/")
            content.append(render_node(path, part, render_tree(children, path)))
        return "".join(content)

    def render_node(path: str, label: str, children: str) -> str:
        # Match Forge's existing tree controls; tree contains directories only.
        return (
            '<li class="tree-list-item tree-list-item--has-subitem" data-tree-entry-type="dir">'
            '<span data-filterable-item-text hidden></span>'
            f'<div class="tree-list-content tree-list-content-dir" type="button" '
            f'data-path="{html.escape(path, quote=True)}" data-name="{html.escape(label, quote=True)}" '
            f'onclick="extraNetworksTreeOnClick(event, \'{tabname}\', \'{self.extra_networks_tabname}\')">'
            '<span class="tree-list-item-action tree-list-item-action--leading"><i class="tree-list-item-action-chevron"></i></span>'
            '<span class="tree-list-item-visual tree-list-item-visual--leading">🗀</span>'
            f'<span class="tree-list-item-label tree-list-item-label--truncate">{html.escape(label)}</span>'
            '</div>'
            f'<ul class="tree-list tree-list--subgroup" hidden>{children}</ul>'
            '</li>'
        )

    roots = self.allowed_directories_for_previews()
    # One root per configured LoRA model location; paths are relative to each
    # root, as with folder buttons. No per-file tree leaves are constructed.
    label = (Path(roots[0]).name or "LoRAs") if len(roots) == 1 else "All LoRA directories"
    result = render_node("", label, render_tree(root))
    return f'<ul class="tree-list tree-list--tree">{result}</ul>'


def _get_page():
    for page in ui_extra_networks.extra_pages:
        if _is_lora(page):
            return page
    raise HTTPException(status_code=503, detail="LoRA page not registered yet")


def _items_for_query(snapshot: Snapshot, *, folder: str, search: str, sd: int, sort: str, desc: bool, seed: int):
    text_words = search.casefold().strip().split()
    norm_folder = _norm_folder(folder)
    hide_mode = str(getattr(shared.opts, "extra_networks_hidden_models", "When searched"))
    filter_sd = not getattr(shared.opts, "lora_filter_disabled", False) and sd in (0, 1, 2)
    allowed_sd = ("SdVersion.SD1", "SdVersion.SDXL", "SdVersion.Flux")
    for entry in snapshot.sorted_entries(sort, desc, seed):
        if norm_folder and entry.folder != norm_folder and not entry.folder.startswith(norm_folder + "/"):
            continue
        if entry.hidden and hide_mode == "Never":
            continue
        if entry.hidden and hide_mode != "Always" and len(search.strip()) < 4:
            continue
        if any(word not in entry.searchable for word in text_words):
            continue
        if filter_sd and entry.sd_version not in ("SdVersion.Unknown", allowed_sd[sd]):
            continue
        yield entry


def api_config():
    return {
        "batch_size": batch_size(),
        "search_debounce_ms": _option_int(OPT_DELAY, 200, 0, 5000),
        "mobile_dirs_height_px": _option_int(OPT_DIR_HEIGHT, 400, 30, 3000),
        "mobile_cards_height_dvh": _option_int(OPT_CARD_HEIGHT, 60, 20, 95),
    }


def api_cards(
    tabname: str = "txt2img",
    folder: str = "",
    search: str = "",
    sd: int = 3,
    sort: str = "default",
    descending: bool = False,
    seed: int = 0,
    offset: int = 0,
    revision: int = 0,
):
    if tabname not in ("txt2img", "img2img"):
        raise HTTPException(status_code=400, detail="Invalid tab")
    if sort not in ("default", "name", "date_created", "date_modified", "random"):
        raise HTTPException(status_code=400, detail="Invalid sort")
    if offset < 0 or len(search) > 2000 or len(folder) > 4000:
        raise HTTPException(status_code=400, detail="Invalid filter or offset")
    page = _get_page()
    snapshot = INDEX.get(page)
    if snapshot is None:
        raise HTTPException(status_code=503, detail="LoRA listing has not finished loading")
    if revision and revision != snapshot.revision:
        raise HTTPException(status_code=409, detail="LoRA listing was refreshed")
    size = batch_size()
    # -1 is the native (unpaginated) mode, so the endpoint is not used.
    if size == -1:
        raise HTTPException(status_code=409, detail="Pagination is disabled")
    matches = list(_items_for_query(snapshot, folder=folder, search=search, sd=sd,
                                    sort=sort, desc=descending, seed=seed))
    batch = matches[offset:offset + size]
    page = snapshot.page
    # Use Forge's original per-item HTML creation to preserve prompt insertion,
    # preview, metadata, and edit-card behavior.
    result = "".join(page.create_item_html(tabname, entry.item, page.card_tpl) for entry in batch)
    next_offset = offset + len(batch)
    return {"html": result, "total": len(matches), "offset": next_offset,
            "has_more": next_offset < len(matches), "revision": snapshot.revision}


def api_diagnostics():
    """Read-only counts to help diagnose genuine missing entries.

    This reports what Forge's own LoRA page has indexed (as opposed to a
    separate rescan of the disk), and how many are hidden by the preferences.
    """
    snapshot = INDEX.get(_get_page())
    if snapshot is None:
        raise HTTPException(status_code=503, detail="LoRA listing has not finished loading")
    return {
        "indexed_loras": len(snapshot.entries),
        "folder_count": len(snapshot.folders),
        "hidden_loras": sum(entry.hidden for entry in snapshot.entries),
        "revision": snapshot.revision,
        "batch_size": batch_size(),
    }


def before_ui():
    global _PATCHED
    if _PATCHED:
        return
    cls = ui_extra_networks.ExtraNetworksPage
    cls.create_html = patched_html
    cls.create_card_view_html = patched_card_view
    cls.create_dirs_view_html = patched_dirs_view
    cls.create_tree_view_html = patched_tree_view
    _PATCHED = True
    print("[Large Collection Helper] LoRA pagination hooks installed")


def on_settings():
    section = ("large_collection_helper", "Large Collection Helper")
    shared.opts.add_option(OPT_BATCH, shared.OptionInfo(
        "150", "LoRA cards per batch", gr.Textbox,
        {"placeholder": "150"}, section=section,
    ).info("Default: 150. Enter -1 to disable pagination (render all LoRA cards). Apply and reload UI."))
    shared.opts.add_option(OPT_DELAY, shared.OptionInfo(
        200, "LoRA search delay (milliseconds)", gr.Number, {"precision": 0}, section=section,
    ).info("Default: 200 ms. Applies to incremental LoRA search."))
    shared.opts.add_option(OPT_DIR_HEIGHT, shared.OptionInfo(
        400, "Mobile folder area maximum height (pixels)", gr.Number, {"precision": 0}, section=section,
    ).info("Default: 400 px. Folder area scrolls independently when needed."))
    shared.opts.add_option(OPT_CARD_HEIGHT, shared.OptionInfo(
        60, "Mobile LoRA card area height (% of viewport)", gr.Number, {"precision": 0}, section=section,
    ).info("Default: 60. Keeps card viewport independent of the number of folders."))


def on_app_started(_demo, app):
    app.add_api_route("/lch/api/config", api_config, methods=["GET"])
    app.add_api_route("/lch/api/cards", api_cards, methods=["GET"])
    app.add_api_route("/lch/api/diagnostics", api_diagnostics, methods=["GET"])


def on_unload():
    # Called during Forge's UI reload; prevents wrapping a patched method twice.
    global _PATCHED
    if _PATCHED:
        cls = ui_extra_networks.ExtraNetworksPage
        cls.create_html = _ORIGINAL_CREATE_HTML
        cls.create_card_view_html = _ORIGINAL_CARD_VIEW
        cls.create_dirs_view_html = _ORIGINAL_DIRS_VIEW
        cls.create_tree_view_html = _ORIGINAL_TREE_VIEW
        _PATCHED = False


script_callbacks.on_ui_settings(on_settings)
script_callbacks.on_before_ui(before_ui)
script_callbacks.on_app_started(on_app_started)
script_callbacks.on_script_unloaded(on_unload)
