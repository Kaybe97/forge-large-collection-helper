# Forge Large Collection Helper

An extension for [Forge Neo](https://github.com/Haoming02/sd-webui-forge-classic/tree/neo) that makes very large LoRA libraries easier to browse. It loads LoRA cards in batches, searches and sorts the full collection without requiring every card to be rendered in the browser, and improves the mobile LoRA layout.

## Installation

### Recommended: Install from URL

1. In Forge Neo, open **Extensions → Install from URL**.
2. On this GitHub repository page, use **Code → HTTPS** to copy the repository URL. Paste it into **URL for extension's git repository** in Forge Neo, then click **Install**.
3. Once the installation completes, **fully stop and relaunch Forge Neo** to load the extension's Python hooks. Refresh the browser afterward.

### Alternative: Manual installation

Download the release ZIP from GitHub or CivitAI and extract the `forge-large-collection-helper` folder into:

```text
<Forge Neo>/extensions/forge-large-collection-helper/
```

Fully restart Forge Neo, then refresh the browser. To update a manual installation, replace the extension files and restart. To disable the extension, use Forge Neo's **Extensions → Installed** tab and restart; remove the extension directory to uninstall.

## Features

- **Incremental LoRA loading:** Starts with a configurable number of cards and loads more as you scroll. Search and sorting apply to the full indexed collection, including cards not yet displayed.
- **Responsive search:** Uses a backend search index and a short delay after typing, avoiding repeated filtering of thousands of browser elements.
- **Random sort:** The dice button shuffles the matching LoRAs. Click it again to reshuffle. The order stays consistent as more cards load, and respects both the selected folder and search terms.
- **Folder navigation:** Folder selection and text search can be used together. The directory tree shows folders without expanding into a list of every file.
- **Mobile layout:** Folder controls scroll within a height limit, leaving a consistent-height area for LoRA cards. The search and sort controls wrap to fit narrower screens.
- **Load counter:** A small counter beneath the cards shows how many of the matching LoRAs have loaded.

The extension affects the built-in **LoRA** Extra Networks tabs in txt2img and img2img. It reuses Forge Neo's card rendering and does not modify Forge Neo's core files.

## Settings

In **Settings → Large Collection Helper**:

| Setting | Default | Description |
| --- | --- | --- |
| LoRA cards per batch | `150` | Any positive whole number. Enter `-1` to disable pagination and use Forge's original all-at-once card display. |
| LoRA search delay | `200 ms` | Wait after typing before updating results. |
| Mobile folder area maximum height | `400 px` | Maximum height of the scrollable folder section. |
| Mobile LoRA card area height | `60` | Height of the card area as a percentage of the mobile viewport. |

Apply settings and reload the UI when changing them. The page size is a text field; invalid values fall back to 150.

## Notes

Forge Neo still scans LoRA files and metadata when building its listing. This extension reduces the HTML sent to the browser and the amount of card-related work done there; it does not replace Forge Neo's filesystem scan with a persistent cache. Cards from previous batches remain loaded as you scroll, rather than being removed through virtualization.

Changes to LoRA descriptions or model files may require refreshing the LoRA listing. Forge Neo's own handling of duplicate model names and metadata continues to apply. Setting the batch size to `-1` restores the original, potentially slower full-card rendering behavior.

Because the extension hooks Forge Neo's Extra Networks internals, changes to those internals may require an extension update. Other extensions that override the same interface functions may also interfere.

## Credits and license

Newly written code for this extension was generated using OpenAI ChatGPT; code adapted from other sources is excluded from that statement. See [NOTICE.md](NOTICE.md) for upstream acknowledgments.

Licensed under the [GNU Affero General Public License v3.0](LICENSE) (`AGPL-3.0-only`).
