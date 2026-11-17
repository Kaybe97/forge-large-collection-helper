# SPDX-License-Identifier: AGPL-3.0-only
"""Offline tests using a small Forge-shaped stub (not an integration test)."""

import importlib.util
import sys
import types
from pathlib import Path

from fastapi import HTTPException

PATH = Path(__file__).parents[1] / "scripts" / "large_collection_helper.py"


def load_module(*, register_in_sys_modules=False):
    callbacks = types.SimpleNamespace(
        on_ui_settings=lambda fn: None,
        on_before_ui=lambda fn: None,
        on_app_started=lambda fn: None,
        on_script_unloaded=lambda fn: None,
    )
    shared = types.SimpleNamespace(opts=types.SimpleNamespace(
        lch_lora_batch_size="150", lch_search_debounce_ms=200,
        lch_mobile_dirs_height_px=400, lch_mobile_cards_height_dvh=60,
        extra_networks_show_hidden_directories=False,
        extra_networks_card_show_desc=True,
        extra_networks_hidden_models="When searched",
        lora_filter_disabled=False,
    ))
    class BasePage:
        extra_networks_tabname = "lora"
        card_tpl = "CARD"

        def create_html(self, tabname, *, empty=False):
            cards = self.create_card_view_html(tabname, none_message="Loading..." if empty else None)
            return f"<div id='{tabname}_lora_pane'><div id='{tabname}_lora_cards'>{cards}</div></div>"

        def create_card_view_html(self, tabname, *, none_message):
            return "ORIGINAL"

        def create_tree_view_html(self, tabname):
            return "ORIGINAL-TREE"

        def create_dirs_view_html(self, tabname):
            return "ORIGINAL-DIRS"

        def create_item_html(self, tabname, item, template):
            return f'<div class="card" data-tab="{tabname}" data-name="{item["name"]}"></div>'

        def allowed_directories_for_previews(self):
            return ["/models/Lora"]

    networks = types.SimpleNamespace(ExtraNetworksPage=BasePage, extra_pages=[])
    mods = types.ModuleType("modules")
    mods.script_callbacks = callbacks
    mods.shared = shared
    mods.ui_extra_networks = networks
    sys.modules["modules"] = mods
    sys.modules["modules.script_callbacks"] = callbacks
    sys.modules["modules.shared"] = shared
    sys.modules["modules.ui_extra_networks"] = networks
    spec = importlib.util.spec_from_file_location("lch_backend", PATH)
    module = importlib.util.module_from_spec(spec)
    # Forge's modules/script_loading.py intentionally does NOT register the
    # extension in sys.modules before executing it. Mirror that by default.
    sys.modules.pop(spec.name, None)
    if register_in_sys_modules:
        sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, networks, shared


def make_items(n=800):
    return {
        f"test{i:05}": {
            "name": f"test{i:05}",
            "filename": f"/models/Lora/{'Characters' if i % 2 else 'Styles'}/test{i:05}.safetensors",
            "description": f"description {i % 11}",
            "search_terms": ["lora", f"test{i:05}"],
            "sort_keys": {"name": f"test{i:05}", "path": f"/models/Lora/test{i:05}",
                          "date_created": i, "date_modified": 800 - i},
            "sd_version_str": "SdVersion.SDXL" if i % 3 == 0 else "SdVersion.Unknown",
        } for i in range(n)
    }


def test_paginate_search_filter_and_random():
    mod, net, shared = load_module()
    page = net.ExtraNetworksPage()
    net.extra_pages.append(page)
    page.items = make_items()
    mod.before_ui()
    assert "lch-placeholder" in page.create_card_view_html("txt2img", none_message=None)
    assert 'data-lch-paged="1"' in page.create_html("txt2img")
    assert 'data-lch-paged="1"' not in page.create_html("txt2img", empty=True)
    assert "data-lch-folder=" in page.create_dirs_view_html("txt2img")
    assert "tree-list-content-dir" in page.create_tree_view_html("txt2img")
    one = mod.api_cards(folder="Characters", sort="name", offset=0)
    two = mod.api_cards(folder="Characters", sort="name", offset=one["offset"], revision=one["revision"])
    assert one["total"] == 400
    assert one["offset"] == 150
    assert two["offset"] == 300
    assert 'test00001' in one["html"]
    assert 'test00000' not in one["html"]
    assert mod.api_cards(folder="Styles", search="test00000")["total"] == 1
    assert mod.api_cards(folder="Characters", search="test00000")["total"] == 0
    a = mod.api_cards(folder="Characters", sort="random", seed=12345)
    b = mod.api_cards(folder="Characters", sort="random", seed=12345)
    c = mod.api_cards(folder="Characters", sort="random", seed=12346)
    assert a["html"] == b["html"]
    assert a["html"] != c["html"]
    assert a["offset"] == 150
    assert mod.api_cards(sd=1)["total"] == 800 * 1  # Unknown passes model filters
    shared.opts.lch_lora_batch_size = "-1"
    assert page.create_card_view_html("txt2img", none_message=None) == "ORIGINAL"
    assert mod.api_config()["batch_size"] == -1
    shared.opts.lch_lora_batch_size = "0"
    assert mod.batch_size() == 150
    shared.opts.lch_lora_batch_size = "150"
    page.items = make_items(10)
    page.create_card_view_html("txt2img", none_message=None)
    try:
        mod.api_cards(revision=one["revision"])
        assert False, "stale revision must fail"
    except HTTPException as e:
        assert e.status_code == 409


def test_large_index_does_not_render_all_cards():
    mod, net, _shared = load_module()
    page = net.ExtraNetworksPage()
    net.extra_pages.append(page)
    page.items = make_items(50_000)
    mod.before_ui()
    view = page.create_card_view_html("txt2img", none_message=None)
    assert len(view) < 500
    assert len(mod.INDEX.get(page).entries) == 50_000
    result = mod.api_cards(search="test49999")
    assert result["total"] == 1
    assert "test49999" in result["html"]
    assert mod.api_cards(sort="random", seed=123)["offset"] == 150


def test_import_when_forge_does_not_register_module():
    mod, _net, _shared = load_module(register_in_sys_modules=False)
    assert mod.Entry({}, "name", "", "", False, "", {}).name == "name"
    assert mod.Snapshot(None, [], 1, []).revision == 1
    assert "lch_backend" not in sys.modules


def test_all_entries_are_reachable_without_duplicates_for_each_sort():
    """Simulate scrolling through an entire library, not just the first batch."""
    import re
    mod, net, shared = load_module()
    page = net.ExtraNetworksPage()
    net.extra_pages.append(page)
    page.items = make_items(3601)
    shared.opts.lch_lora_batch_size = "137"  # arbitrary user-entered page size
    mod.before_ui()
    page.create_card_view_html("txt2img", none_message=None)
    for sort, descending in (("default", False), ("name", False),
                             ("name", True), ("random", False),
                             ("date_created", False)):
        offset = 0
        seen = []
        revision = 0
        while True:
            result = mod.api_cards(sort=sort, descending=descending, seed=42,
                                   offset=offset, revision=revision)
            seen.extend(re.findall('data-name="(test\\d+)"', result["html"]))
            assert len(seen) == result["offset"]
            assert result["offset"] > offset
            offset, revision = result["offset"], result["revision"]
            if not result["has_more"]:
                break
        assert len(seen) == 3601
        assert len(set(seen)) == 3601
        assert set(seen) == {f"test{i:05}" for i in range(3601)}
    assert mod.api_diagnostics()["indexed_loras"] == 3601
    assert mod.api_config()["mobile_dirs_height_px"] == 400


def test_path_sort_uses_actual_path_key_and_filters_subfolders():
    mod, net, shared = load_module()
    page = net.ExtraNetworksPage()
    net.extra_pages.append(page)
    page.items = {
        "a": {"name": "a", "filename": "/models/Lora/Zoo/a.safetensors",
              "sort_keys": {"path": "/models/Lora/Zoo/a.safetensors"}},
        "b": {"name": "b", "filename": "/models/Lora/Characters/Anime/b.safetensors",
              "sort_keys": {"path": "/models/Lora/Characters/Anime/b.safetensors"}},
        "c": {"name": "c", "filename": "/models/Lora/Characters/Games/c.safetensors",
              "sort_keys": {"path": "/models/Lora/Characters/Games/c.safetensors"}},
    }
    mod.before_ui()
    page.create_card_view_html("txt2img", none_message=None)
    all_entries = [e.name for e in mod._items_for_query(mod.INDEX.get(page), folder="", search="",
                      sd=3, sort="default", desc=False, seed=0)]
    assert all_entries == ["b", "c", "a"]
    folder_entries = [e.name for e in mod._items_for_query(mod.INDEX.get(page), folder="Characters", search="",
                      sd=3, sort="default", desc=False, seed=0)]
    assert folder_entries == ["b", "c"]


def test_old_page_does_not_leak_across_ui_reload():
    import gc
    import weakref
    mod, net, _shared = load_module()
    page = net.ExtraNetworksPage()
    page.items = make_items(50)
    mod.INDEX.capture(page)
    reference = weakref.ref(page)
    del page
    gc.collect()
    assert reference() is None
    assert len(mod.INDEX._snapshots) == 0
