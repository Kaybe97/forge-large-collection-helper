/* SPDX-License-Identifier: AGPL-3.0-only
 * Forge Neo Large Collection Helper.
 * Restricts all behavior to the built-in txt2img/img2img LoRA panes.
 * Keeps searching and sorting on the server, not in 50,000 DOM cards.
 */
(() => {
    "use strict";

    const PANE_IDS = ["txt2img_lora", "img2img_lora", "txt2img_loras", "img2img_loras"];
    const states = new Map();
    let config = null;
    let scanTimer = null;
    let scanObserver = null;
    let pageScrollListenerInstalled = false;

    function appRoot() {
        return typeof gradioApp === "function" ? gradioApp() : document;
    }
    function url(path, params = {}) {
        const target = new URL(`./lch/api/${path}`, window.location.href);
        Object.entries(params).forEach(([key, value]) => target.searchParams.set(key, String(value)));
        return target.toString();
    }
    async function readConfig() {
        if (config) return config;
        try {
            const response = await fetch(url("config"), { credentials: "same-origin" });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            config = await response.json();
        } catch (error) {
            console.warn("[Large Collection Helper] Configuration unavailable:", error);
            return null;
        }
        return config;
    }
    function randomSeed() {
        if (window.crypto && window.crypto.getRandomValues) {
            return crypto.getRandomValues(new Uint32Array(1))[0];
        }
        return Math.floor(Math.random() * 0xFFFFFFFF);
    }
    function findSort(state) {
        const active = state.controls.querySelector(".extra-network-control--sort.extra-network-control--enabled");
        return active ? active.dataset.sortkey || "default" : "default";
    }
    function sortDescending(state) {
        const dir = state.controls.querySelector(".extra-network-control--sort-dir");
        return Boolean(dir && dir.dataset.sortdir === "Descending");
    }
    function activePreset() {
        const ui = appRoot().querySelector("#forge_ui_preset");
        if (!ui || (typeof opts !== "undefined" && opts.lora_filter_disabled)) return 3;
        const buttons = Array.from(ui.querySelectorAll("input"));
        const index = buttons.findIndex(input => input.checked);
        return index >= 0 && index <= 3 ? index : 3;
    }
    function updateCount(state) {
        if (!state.footer) return;
        if (state.total === null) {
            state.footer.hidden = true;
            state.footer.textContent = "";
            return;
        }
        // Keep the count outside the scrollable card container. It remains
        // visible below the cards, without taking up toolbar space or growing
        // the card DOM with every paginated request.
        state.footer.textContent = `${state.offset.toLocaleString()} / ${state.total.toLocaleString()} LoRAs loaded`;
        state.footer.hidden = false;
    }
    function setStatus(state, message, retry = false) {
        if (!state.status) return;
        state.status.textContent = message || "";
        state.status.hidden = !message;
        state.status.dataset.lchError = retry ? "true" : "false";
    }
    function setFolder(state, folder) {
        state.folder = (folder || "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
        const dirs = state.pane.querySelector(".extra-network-dirs");
        if (dirs) {
            dirs.querySelectorAll("button").forEach(btn => {
                btn.classList.toggle("lch-selected-folder", (btn.dataset.lchFolder || "") === state.folder);
            });
        }
        const tree = state.pane.querySelector(".extra-network-tree");
        if (tree) {
            tree.querySelectorAll(".tree-list-content-dir").forEach(btn => {
                if (btn.dataset.path === state.folder) btn.dataset.selected = "";
                else delete btn.dataset.selected;
            });
        }
        if (state.folderReset) {
            state.folderReset.hidden = !state.folder;
            state.folderReset.title = state.folder ? `Clear folder: ${state.folder}` : "No folder selected";
            state.folderReset.textContent = state.folder ? `📁 ${state.folder} ×` : "";
        }
        reset(state);
    }
    function setupFolderControls(state) {
        const folderReset = document.createElement("button");
        folderReset.type = "button";
        folderReset.className = "lch-folder-label";
        folderReset.hidden = true;
        folderReset.addEventListener("click", () => setFolder(state, ""));
        // Keep the potentially long folder path out of the toolbar, especially
        // on mobile where the native tabs and sort controls already compete.
        const body = state.pane.querySelector(".extra-network-pane-content-dirs, .extra-network-pane-content-tree");
        if (body) state.pane.insertBefore(folderReset, body);
        else state.pane.prepend(folderReset);
        state.folderReset = folderReset;

        // Capture before Forge's inline onclick changes the search field.
        // This allows a directory filter and a free-text query to coexist.
        state.pane.addEventListener("click", event => {
            const directoryButton = event.target.closest(".extra-network-dirs button[data-lch-folder]");
            if (directoryButton && state.pane.contains(directoryButton)) {
                event.preventDefault();
                event.stopImmediatePropagation();
                setFolder(state, directoryButton.dataset.lchFolder || "");
                return;
            }
            const treeDir = event.target.closest(".extra-network-tree .tree-list-content-dir");
            if (!treeDir || !state.pane.contains(treeDir)) return;
            event.preventDefault();
            event.stopImmediatePropagation();
            const subgroup = treeDir.nextElementSibling;
            const onChevron = !!event.target.closest(".tree-list-item-action--leading, .tree-list-item-action-chevron");
            if (onChevron) {
                if (subgroup) {
                    const expand = subgroup.hasAttribute("hidden");
                    subgroup.toggleAttribute("hidden", !expand);
                    if (expand) treeDir.dataset.expanded = "";
                    else delete treeDir.dataset.expanded;
                }
                return;
            }
            const targetFolder = treeDir.dataset.path || "";
            if (state.folder === targetFolder && targetFolder) {
                setFolder(state, "");
            } else {
                if (subgroup && subgroup.hasAttribute("hidden")) {
                    subgroup.removeAttribute("hidden");
                    treeDir.dataset.expanded = "";
                }
                setFolder(state, targetFolder);
            }
        }, true);
    }
    function setupSort(state) {
        // This class is also used by Forge's existing sort-selection UI.
        const sortButton = document.createElement("button");
        sortButton.type = "button";
        sortButton.className = "extra-network-control--sort lch-random-sort";
        sortButton.dataset.sortkey = "random";
        sortButton.textContent = "🎲";
        sortButton.title = "Random order (click again to reshuffle)";
        sortButton.setAttribute("aria-label", sortButton.title);
        const dirButton = state.controls.querySelector(".extra-network-control--sort-dir");
        // Forge places an empty <small> separator BEFORE the direction icon.
        // Insert before that separator to keep Random with the sort icons.
        const spacer = dirButton && dirButton.previousElementSibling;
        const anchor = spacer && spacer.tagName === "SMALL" ? spacer : dirButton;
        if (anchor) state.controls.insertBefore(sortButton, anchor);
        else state.controls.appendChild(sortButton);
        sortButton.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();
            state.controls.querySelectorAll(".extra-network-control--sort").forEach(btn => {
                btn.classList.remove("extra-network-control--enabled");
            });
            sortButton.classList.add("extra-network-control--enabled");
            state.seed = randomSeed();
            reset(state);
        });
        // Forge invokes applyExtraNetworkSort asynchronously after clicks on
        // its original sort controls. Our replacement callback handles them.
    }
    function insertCards(state, htmlText) {
        const template = document.createElement("template");
        template.innerHTML = htmlText;
        // Insert before the sentinel. Card click handlers are native Forge HTML.
        state.cards.insertBefore(template.content, state.status);
    }
    function scrollNearBottom(state) {
        // Only fetch when the LoRA pane is visible. Previously, empty/hidden
        // containers could report scrollHeight == clientHeight == 0, causing
        // endless background loads and effectively defeating pagination.
        if (!state.cards.isConnected || !state.cards.getClientRects().length) return false;
        const box = state.cards.getBoundingClientRect();
        if (box.width < 1 || box.height < 1) return false;
        if (state.cards.scrollHeight > state.cards.clientHeight + 2) {
            return state.cards.scrollTop + state.cards.clientHeight >= state.cards.scrollHeight - 400;
        }
        // Some layouts scroll the document instead of the card container.
        // Use the sentinel's actual viewport position in that case.
        const sentinelBox = state.sentinel.getBoundingClientRect();
        return sentinelBox.top <= window.innerHeight + 400 && sentinelBox.bottom >= -400;
    }
    async function loadNext(state) {
        if (state.busy || !state.hasMore || !state.cards.isConnected) return;
        state.busy = true;
        const epoch = state.epoch;
        // Loading state stays out of the toolbar; no permanent result counter.
        setStatus(state, "");
        try {
            const params = {
                tabname: state.tabname,
                search: state.search.value,
                folder: state.folder,
                sort: findSort(state),
                descending: sortDescending(state),
                sd: activePreset(),
                seed: state.seed,
                offset: state.offset,
                revision: state.revision || 0,
            };
            const response = await fetch(url("cards", params), { credentials: "same-origin" });
            if (epoch !== state.epoch) return;
            if (response.status === 409) {
                // An in-flight request crossed a Gradio LoRA refresh.
                reset(state);
                return;
            }
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            if (epoch !== state.epoch) return;
            if (state.revision && data.revision !== state.revision) {
                reset(state);
                return;
            }
            state.revision = data.revision;
            state.offset = data.offset;
            state.total = data.total;
            state.hasMore = data.has_more;
            insertCards(state, data.html);
            updateCount(state);
            if (!data.total) setStatus(state, "No matching LoRAs");
            else setStatus(state, "");
        } catch (error) {
            if (epoch !== state.epoch) return;
            state.hasMore = false;
            setStatus(state, `LoRA loading failed (${error.message}). Tap to retry.`, true);
            console.error("[Large Collection Helper]", error);
        } finally {
            if (epoch === state.epoch) {
                state.busy = false;
                // If the first batch doesn't fill the available viewport, load
                // another. Schedule to prevent deep recursion on tiny batches.
                if (state.hasMore && scrollNearBottom(state)) {
                    setTimeout(() => loadNext(state), 40);
                }
            }
        }
    }
    function reset(state) {
        state.epoch += 1;
        state.busy = false;
        state.offset = 0;
        state.total = null;
        state.revision = 0;
        state.hasMore = true;
        state.cards.replaceChildren(state.status, state.sentinel);
        state.cards.scrollTop = 0;
        updateCount(state);
        setStatus(state, "");
        loadNext(state);
    }
    function initState(pane, settings) {
        const id = pane.id.replace(/_pane$/, "");
        const controls = appRoot().querySelector(`#${id}_controls`);
        const searchOriginal = appRoot().querySelector(`#${id}_extra_search`);
        const cards = pane.querySelector(`#${id}_cards`);
        if (!controls || !searchOriginal || !cards) return;
        // Run after Forge's setupExtraNetworksForTab attached its listeners.
        if (typeof extraNetworksApplyFilter === "undefined" || !extraNetworksApplyFilter[id]) return;
        const existing = states.get(id);
        if (existing && existing.cards === cards && existing.search.isConnected) return;
        if (existing && existing.observer) existing.observer.disconnect();
        // The native input listener is an expensive per-keystroke full DOM scan.
        // Replacing the input removes it without modifying Forge's source.
        const search = searchOriginal.cloneNode(true);
        searchOriginal.replaceWith(search);
        const status = document.createElement("button");
        status.type = "button";
        status.className = "lch-browser-message";
        status.hidden = true;
        status.title = "Tap to retry if LoRA loading fails";
        const footer = document.createElement("div");
        footer.className = "lch-count-footer";
        footer.hidden = true;
        footer.setAttribute("aria-live", "off");
        // The footer is a sibling of the folder/card body, rather than a card
        // child, so it stays at the bottom when the cards scroll independently.
        const content = pane.querySelector(".extra-network-pane-content-dirs, .extra-network-pane-content-tree");
        if (content) content.insertAdjacentElement("afterend", footer);
        else pane.appendChild(footer);
        const sentinel = document.createElement("div");
        sentinel.className = "lch-scroll-sentinel";
        sentinel.setAttribute("aria-hidden", "true");
        const state = {
            id, pane, controls, search, cards, sentinel, status, footer,
            tabname: id.startsWith("img2img") ? "img2img" : "txt2img",
            folder: "", seed: randomSeed(), epoch: 0, revision: 0,
            offset: 0, total: null, busy: false, hasMore: true, observer: null,
        };
        states.set(id, state);
        pane.classList.add("lch-managed");
        controls.classList.add("lch-managed-controls");
        const nav = controls.closest(".tab-nav");
        if (nav) nav.classList.add("lch-tab-nav");
        pane.style.setProperty("--lch-dirs-max-height", `${settings.mobile_dirs_height_px}px`);
        pane.style.setProperty("--lch-cards-height", `${settings.mobile_cards_height_dvh}dvh`);
        setupFolderControls(state);
        setupSort(state);
        search.addEventListener("input", () => {
            clearTimeout(state.searchTimer);
            state.searchTimer = setTimeout(() => reset(state), settings.search_debounce_ms);
        });
        status.addEventListener("click", () => {
            if (status.dataset.lchError === "true") reset(state);
        });
        // The original global functions are also used by tab-switch callbacks,
        // sort buttons and other Forge extensions; redirect them to our index.
        extraNetworksApplyFilter[id] = () => reset(state);
        extraNetworksApplySort[id] = () => reset(state);
        if ("IntersectionObserver" in window) {
            state.observer = new IntersectionObserver(entries => {
                if (entries.some(entry => entry.isIntersecting) && scrollNearBottom(state)) loadNext(state);
            }, { root: null, rootMargin: "0px 0px 400px 0px" });
            state.observer.observe(sentinel);
        }
        cards.addEventListener("scroll", () => {
            // Fallback and support for different scroll containers.
            if (scrollNearBottom(state)) loadNext(state);
        }, { passive: true });
        // When Forge's layout allows document scrolling instead of an inner
        // scroller, use a single shared listener across Gradio UI reloads.
        if (!pageScrollListenerInstalled) {
            window.addEventListener("scroll", () => {
                states.forEach(current => {
                    if (current.cards.isConnected && scrollNearBottom(current)) loadNext(current);
                });
            }, { passive: true });
            pageScrollListenerInstalled = true;
        }
        reset(state);
    }
    function applyMobileSizing(pane, settings) {
        pane.classList.add("lch-mobile-layout");
        pane.style.setProperty("--lch-dirs-max-height", `${settings.mobile_dirs_height_px}px`);
        pane.style.setProperty("--lch-cards-height", `${settings.mobile_cards_height_dvh}dvh`);
    }
    function initNative(pane, settings) {
        const id = pane.id.replace(/_pane$/, "");
        const controls = appRoot().querySelector(`#${id}_controls`);
        const cards = pane.querySelector(`#${id}_cards`);
        if (!controls || !cards) return;
        applyMobileSizing(pane, settings);
        controls.classList.add("lch-managed-controls");
        const nav = controls.closest(".tab-nav");
        if (nav) nav.classList.add("lch-tab-nav");
        if (controls.querySelector(".lch-random-sort")) return;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "extra-network-control--sort lch-random-sort";
        button.dataset.sortkey = "random";
        button.textContent = "🎲";
        button.title = "Random order (click again to reshuffle)";
        button.setAttribute("aria-label", button.title);
        const sortDir = controls.querySelector(".extra-network-control--sort-dir");
        const spacer = sortDir && sortDir.previousElementSibling;
        const anchor = spacer && spacer.tagName === "SMALL" ? spacer : sortDir;
        if (anchor) controls.insertBefore(button, anchor);
        else controls.appendChild(button);
        let seed = randomSeed();
        let timer;
        const hash = text => {
            let h = (seed ^ 2166136261) >>> 0;
            for (let i = 0; i < text.length; i++) {
                h = Math.imul(h ^ text.charCodeAt(i), 16777619) >>> 0;
            }
            return h;
        };
        const reorder = () => {
            if (!button.classList.contains("extra-network-control--enabled")) return;
            // Warning: -1 intentionally returns to Forge's expensive full DOM.
            const all = Array.from(cards.querySelectorAll(":scope > .card"));
            all.sort((a, b) => hash(a.dataset.name || "") - hash(b.dataset.name || ""));
            const fragment = document.createDocumentFragment();
            all.forEach(card => fragment.appendChild(card));
            cards.appendChild(fragment);
        };
        button.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();
            controls.querySelectorAll(".extra-network-control--sort").forEach(control => {
                control.classList.remove("extra-network-control--enabled");
            });
            button.classList.add("extra-network-control--enabled");
            seed = randomSeed();
            reorder();
        });
        // Native search still runs first, then restore the stable random order.
        // It will be slower with -1; this is an opt-out from pagination.
        const search = appRoot().querySelector(`#${id}_extra_search`);
        if (search) search.addEventListener("input", () => {
            clearTimeout(timer);
            timer = setTimeout(reorder, 250);
        });
    }
    async function scan() {
        const settings = await readConfig();
        if (!settings) return;
        const app = appRoot();
        for (const id of PANE_IDS) {
            const pane = app.querySelector(`#${id}_pane`);
            if (!pane) continue;
            if (settings.batch_size === -1) {
                initNative(pane, settings);
            } else if (pane.dataset.lchPaged === "1") {
                // Only take over if backend explicitly enabled pagination.
                initState(pane, settings);
            }
        }
    }
    function scheduleScan() {
        if (scanTimer) return;
        scanTimer = setTimeout(() => {
            scanTimer = null;
            scan().catch(error => console.error("[Large Collection Helper]", error));
        }, 60);
    }
    function start() {
        const root = appRoot();
        scanObserver = new MutationObserver(scheduleScan);
        scanObserver.observe(root, { childList: true, subtree: true });
        document.addEventListener("change", event => {
            if (!event.target.closest || !event.target.closest("#forge_ui_preset")) return;
            states.forEach(state => {
                if (state.cards.isConnected) reset(state);
            });
        });
        scheduleScan();
    }
    if (typeof onUiLoaded === "function") onUiLoaded(start);
    else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
    else start();
})();
