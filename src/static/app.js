document.addEventListener("DOMContentLoaded", () => {

    // UI Elements
    const navBtns = document.querySelectorAll(".nav-btn");
    const panels = document.querySelectorAll(".main-panel");
    const btnRefreshQueue = document.getElementById("btn-refresh-queue");
    const btnExportSelected = document.getElementById("btn-export-selected");
    const btnRunSelected = document.getElementById("btn-run-selected");
    const queueList = document.getElementById("queue-list");
    const filterCount = document.getElementById("filter-count");

    // Console Sidebar
    const consoleSidebar = document.getElementById("console-sidebar");
    const btnToggleConsole = document.getElementById("btn-toggle-console");
    const btnClearConsole = document.getElementById("btn-clear-console");
    const consoleActivityDot = document.getElementById("console-activity-dot");
    const appMain = document.getElementById("app-main");

    // Filter pills
    const filterPills = document.querySelectorAll(".filter-pill");
    let activeFilter = "active"; // "active" | "completed"

    // Presets accordion
    const btnTogglePresets = document.getElementById("btn-toggle-presets");
    const presetsBody = document.getElementById("presets-body");
    const presetsChevron = document.getElementById("presets-chevron");

    // Workspace Elements
    const wsProductTitle = document.getElementById("ws-product-title");
    const wsProductSlug = document.getElementById("ws-product-slug");
    const wsPipelineMode = document.getElementById("ws-pipeline-mode");
    const themeSelector = document.getElementById("theme-selector");
    const presetSelector = document.getElementById("preset-selector");
    const btnGenerate = document.getElementById("btn-generate");

    const consoleLogs = document.getElementById("console-logs");
    const workspace = document.getElementById("listing-workspace");
    const btnSave = document.getElementById("btn-save");

    const etsyTitle = document.getElementById("etsy-title");
    const etsyCategory = document.getElementById("etsy-category");
    const etsyPrice = document.getElementById("etsy-price");
    const tagsContainer = document.getElementById("tags-container");
    const etsyDesc = document.getElementById("etsy-desc");
    const imagesGrid = document.getElementById("images-grid");

    const variationsSpecsWrapper = document.getElementById("variations-specs-wrapper");
    const variationsSpecsList = document.getElementById("variations-specs-list");

    // Settings Elements
    const settingOutputDir = document.getElementById("setting-output-dir");
    const btnSaveSettings = document.getElementById("btn-save-settings");
    const settingsStatus = document.getElementById("settings-status");

    // Presets Elements
    const presetShopIntro = document.getElementById("preset-shop-intro");
    const presetShippingNote = document.getElementById("preset-shipping-note");
    const presetMaterialsDisclaimer = document.getElementById("preset-materials-disclaimer");
    const presetCustomPolicy = document.getElementById("preset-custom-policy");
    const presetCustomPromptRules = document.getElementById("preset-custom-prompt-rules");
    const btnResetRules = document.getElementById("btn-reset-rules");
    const btnSavePresets = document.getElementById("btn-save-presets");
    const presetsStatus = document.getElementById("presets-status");

    // State
    let queueData = [];
    let selectedQueueItem = null;
    let eventSource = null;
    let activeListing = null;
    let isBulkRunning = false;
    let pipelineRunning = false;

    // --- INITIALIZATION ---
    loadSettings();
    loadPresets();
    loadThemes();
    loadQueue();
    connectStatusStream();

    // --- CONSOLE SIDEBAR ---
    btnToggleConsole.addEventListener("click", () => {
        const isOpen = consoleSidebar.classList.toggle("open");
        btnToggleConsole.classList.toggle("active", isOpen);
        appMain.classList.toggle("console-open", isOpen);
    });

    btnClearConsole.addEventListener("click", () => {
        consoleLogs.innerHTML = "";
    });

    function setActivityDot(running) {
        pipelineRunning = running;
        consoleActivityDot.classList.toggle("running", running);
    }

    // --- PRESETS ACCORDION ---
    btnTogglePresets.addEventListener("click", () => {
        const isOpen = presetsBody.style.display !== "none";
        presetsBody.style.display = isOpen ? "none" : "block";
        presetsChevron.classList.toggle("rotated", !isOpen);
    });

    // --- NAVIGATION ---
    navBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            navBtns.forEach(b => b.classList.remove("active"));
            panels.forEach(p => p.classList.remove("active"));
            btn.classList.add("active");
            document.getElementById(btn.dataset.target).classList.add("active");
        });
    });

    // --- FILTER PILLS ---
    filterPills.forEach(pill => {
        pill.addEventListener("click", () => {
            filterPills.forEach(p => p.classList.remove("active"));
            pill.classList.add("active");
            activeFilter = pill.dataset.filter;
            renderQueue();
        });
    });

    // --- SETTINGS ---
    function loadSettings() {
        fetch("/api/settings")
            .then(r => r.json())
            .then(data => {
                settingOutputDir.value = data.output_dir || "";
            });
    }

    btnSaveSettings.addEventListener("click", () => {
        const payload = { output_dir: settingOutputDir.value.trim() };
        fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        }).then(r => r.json()).then(() => {
            settingsStatus.style.display = "block";
            setTimeout(() => settingsStatus.style.display = "none", 3000);
            loadQueue();
        });
    });

    // --- LISTING PRESETS ---
    function loadPresets() {
        fetch("/api/listing-presets")
            .then(r => r.json())
            .then(data => {
                presetShopIntro.value = data.shop_intro || "";
                presetShippingNote.value = data.shipping_note || "";
                presetMaterialsDisclaimer.value = data.materials_disclaimer || "";
                presetCustomPolicy.value = data.custom_policy || "";
                if (data.custom_prompt_rules !== undefined) {
                    presetCustomPromptRules.value = data.custom_prompt_rules;
                }
            })
            .catch(() => {}); // Silently fail if endpoint not yet available
    }
    
    if (btnResetRules) {
        btnResetRules.addEventListener("click", () => {
            presetCustomPromptRules.value = "You are an expert e-commerce copywriter and Etsy SEO strategist specializing in premium boutique branding. Your task is to transform raw, clunky supplier specifications from AliExpress/manufacturers into a high-end, high-converting Etsy listing asset.\n--- CRITICAL COMPLIANCE RULES ---\n1. ABSOLUTE PROHIBITIONS: Never mention \"China\", \"AliExpress\", \"mass production\", \"factory\", \"bulk\", \"wholesale\", or \"shipping tracking variations\". Reframe everything around a \"curated, small-batch, premium boutique model\".\n2. TITLE RESTRICTIONS: Do not keyword-stuff titles. Use clean, natural keyphrases separated by pipes (|). Put primary structural/material identifiers in the first 40 characters. Remove subjective words like \"perfect\", \"beautiful\", or \"unbelievable\".\n3. DESCRIPTION FORMATTING: Optimize for readability and scanning. Avoid large text walls. For all bulleted lists or technical attribute breakdowns, you must strictly use a literal hyphen (-) instead of bullet dots (•, *, or circle symbols). Ensure key traits like color, exact size, and materials appear clearly in the first two sentences.\n4. TITLE-TAG MATCH: Ensure the 2 or 3 most important keyword phrases in the Title exactly match 2 or 3 of the Tags.\n5. META DESCRIPTION: Make the first paragraph of the description exactly 1-2 sentences (under 160 characters), naturally weaving in the primary keywords for Google SEO.\n6. OCCASION TARGETING: If applicable, weave in 1 or 2 tags targeting gift intent (e.g., \"Gifts for Her\", \"Anniversary Gift\").";
        });
    }

    btnSavePresets.addEventListener("click", () => {
        const payload = {
            shop_intro: presetShopIntro.value.trim(),
            shipping_note: presetShippingNote.value.trim(),
            materials_disclaimer: presetMaterialsDisclaimer.value.trim(),
            custom_policy: presetCustomPolicy.value.trim(),
            custom_prompt_rules: presetCustomPromptRules.value.trim()
        };
        fetch("/api/listing-presets", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        }).then(r => r.json()).then(() => {
            presetsStatus.style.display = "block";
            setTimeout(() => presetsStatus.style.display = "none", 3000);
        });
    });

    function loadThemes() {
        fetch("/api/themes").then(r => r.json()).then(data => {
            if (data.themes) {
                themeSelector.innerHTML = "";
                data.themes.forEach(theme => {
                    const option = document.createElement("option");
                    option.value = theme;
                    option.textContent = theme.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
                    themeSelector.appendChild(option);
                });
            }
        });
    }

    // --- QUEUE MANAGEMENT ---
    btnRefreshQueue.addEventListener("click", loadQueue);

    function loadQueue() {
        return fetch("/api/queue")
            .then(r => r.json())
            .then(data => {
                queueData = data.queue || [];
                renderQueue();
            });
    }

    function renderQueue() {
        queueList.innerHTML = "";

        const activeItems = queueData.filter(i => i.status !== "done");
        const completedItems = queueData.filter(i => i.status === "done");
        const displayItems = activeFilter === "active" ? activeItems : completedItems;

        // Update count pill
        filterCount.textContent = `${displayItems.length} item${displayItems.length !== 1 ? "s" : ""}`;

        if (displayItems.length === 0) {
            const msg = activeFilter === "active"
                ? "No active items. Use the Chrome Extension to add products."
                : "No completed listings yet. Run the pipeline on queued products.";
            queueList.innerHTML = `<div style="padding: 24px; color: var(--neutral-grey); text-align: center;">${msg}</div>`;
            updateActionBtnState();
            return;
        }

        displayItems.forEach(item => {
            const isDone = item.status === "done";

            // Wrapper (needed for inline preview on completed items)
            const wrapper = document.createElement("div");
            wrapper.className = isDone ? "queue-item-wrapper" : "";

            // Row
            const row = document.createElement("div");
            row.className = "queue-item";

            // Checkbox
            const chk = document.createElement("input");
            chk.type = "checkbox";
            chk.className = "queue-chk";
            chk.dataset.slug = item.slug;
            chk.dataset.status = item.status;
            chk.addEventListener("change", updateActionBtnState);

            // Thumbnail
            const thumb = document.createElement("img");
            thumb.className = "queue-thumb";
            if (item.thumbnail_path) {
                thumb.src = item.thumbnail_path;
            }

            // Info
            const info = document.createElement("div");
            info.className = "queue-info";

            const title = document.createElement("div");
            title.className = "queue-title";
            title.textContent = item.title;

            const meta = document.createElement("div");
            meta.className = "queue-meta";

            const statusBadge = document.createElement("span");
            const status = item.status || "queued";
            statusBadge.className = `queue-status status-${status}`;
            if (status === "downloading" && item.download_progress) {
                statusBadge.textContent = `downloading (${item.download_progress})`;
            } else {
                statusBadge.textContent = status;
            }

            const imgCount = (item.main_images?.length || 0) + (item.variation_images?.length || 0) + (item.description_images?.length || 0);
            const countLabel = document.createElement("span");
            countLabel.textContent = `${imgCount} Images`;

            meta.appendChild(statusBadge);
            meta.appendChild(countLabel);

            info.appendChild(title);
            info.appendChild(meta);

            // Actions
            const actions = document.createElement("div");
            actions.className = "queue-actions";

            if (isDone) {
                // "View Listing" toggles the inline preview panel
                const btnView = document.createElement("button");
                btnView.className = "secondary-btn";
                btnView.textContent = "View Listing";

                const previewPanel = buildListingPreviewPanel(item);
                btnView.addEventListener("click", () => {
                    const isOpen = previewPanel.classList.contains("open");
                    previewPanel.classList.toggle("open", !isOpen);
                    btnView.textContent = isOpen ? "View Listing" : "Close";
                });

                actions.appendChild(btnView);

                // Also allow opening in workspace
                const btnOpen = document.createElement("button");
                btnOpen.className = "secondary-btn";
                btnOpen.textContent = "Edit";
                btnOpen.addEventListener("click", () => selectForWorkspace(item));
                actions.appendChild(btnOpen);

                // Assemble wrapper with preview panel
                row.appendChild(chk);
                row.appendChild(thumb);
                row.appendChild(info);
                row.appendChild(actions);

                const btnDelete = buildDeleteButton(item);
                actions.appendChild(btnDelete);

                wrapper.appendChild(row);
                wrapper.appendChild(previewPanel);
                queueList.appendChild(wrapper);

            } else {
                // Active item — standard layout
                const btnOpen = document.createElement("button");
                btnOpen.className = "secondary-btn";
                if (status === "downloading") {
                    btnOpen.textContent = "Downloading...";
                    btnOpen.disabled = true;
                } else {
                    btnOpen.textContent = "Open in Workspace";
                    btnOpen.addEventListener("click", () => selectForWorkspace(item));
                }

                const btnDelete = buildDeleteButton(item);
                btnDelete.disabled = status === "downloading";

                actions.appendChild(btnOpen);
                actions.appendChild(btnDelete);

                row.appendChild(chk);
                row.appendChild(thumb);
                row.appendChild(info);
                row.appendChild(actions);

                queueList.appendChild(row);
            }
        });

        updateActionBtnState();
    }

    function buildDeleteButton(item) {
        const btnDelete = document.createElement("button");
        btnDelete.className = "danger-btn";
        btnDelete.textContent = "Delete";
        btnDelete.addEventListener("click", () => {
            if (confirm(`Are you sure you want to delete "${item.title}"?`)) {
                btnDelete.disabled = true;
                btnDelete.textContent = "Deleting...";
                fetch("/api/delete-queue-item", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ slug: item.slug })
                })
                .then(r => r.json())
                .then(res => {
                    if (res.status === "success") {
                        loadQueue();
                    } else {
                        alert(res.detail || "Failed to delete item.");
                        btnDelete.disabled = false;
                        btnDelete.textContent = "Delete";
                    }
                })
                .catch(err => {
                    alert("Error: " + err.message);
                    btnDelete.disabled = false;
                    btnDelete.textContent = "Delete";
                });
            }
        });
        return btnDelete;
    }

    function buildListingPreviewPanel(item) {
        const listing = item.etsy_listing || {};
        const panel = document.createElement("div");
        panel.className = "listing-preview-panel";

        const tags = listing.tags || [];
        const tagsHtml = tags.length > 0
            ? `<div class="preview-tags">${tags.map(t => `<span class="preview-tag">${t}</span>`).join("")}</div>`
            : `<span class="preview-value" style="color:var(--neutral-grey)">—</span>`;

        panel.innerHTML = `
            <div class="preview-grid-top">
                <div class="preview-left-col">
                    <div class="preview-field">
                        <div class="preview-field-header">
                            <span class="preview-label">Etsy Title</span>
                            <button class="copy-btn" data-copy-type="title">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                                <span>Copy</span>
                            </button>
                        </div>
                        <div class="preview-value-box">${listing.title || "—"}</div>
                    </div>
                    <div class="preview-field" style="margin-top: 16px;">
                        <div class="preview-field-header">
                            <span class="preview-label">Category</span>
                            <button class="copy-btn" data-copy-type="category">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                                <span>Copy</span>
                            </button>
                        </div>
                        <div class="preview-value-box">${listing.category || "Not categorized"}</div>
                    </div>

                    <div class="preview-field" style="margin-top: 16px;">
                        <div class="preview-field-header">
                            <span class="preview-label">Tags</span>
                            <button class="copy-btn" data-copy-type="tags">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                                <span>Copy</span>
                            </button>
                        </div>
                        <div class="preview-value-box" style="padding: 10px 14px;">${tagsHtml}</div>
                    </div>
                </div>
                
                <div class="preview-right-col">
                    <div class="preview-field">
                        <div class="preview-field-header">
                            <span class="preview-label">Price</span>
                            <button class="copy-btn" data-copy-type="price">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                                <span>Copy</span>
                            </button>
                        </div>
                        <div class="preview-value-box">${listing.suggested_price || "—"}</div>
                    </div>
                </div>
            </div>
            
            <div class="preview-field" style="margin-top: 16px;">
                <div class="preview-field-header">
                    <span class="preview-label">Description</span>
                    <button class="copy-btn" data-copy-type="desc">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                        <span>Copy</span>
                    </button>
                </div>
                <textarea class="preview-desc" readonly>${listing.description || "—"}</textarea>
            </div>
        `;

        // Wire up copy event listeners
        panel.querySelectorAll(".copy-btn").forEach(btn => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation(); // Avoid triggering any toggle actions from parent rows
                
                let textToCopy = "";
                const copyType = btn.dataset.copyType;
                
                if (copyType === "title") {
                    textToCopy = listing.title || "";
                } else if (copyType === "category") {
                    textToCopy = listing.category || "";
                } else if (copyType === "price") {
                    textToCopy = listing.suggested_price || "";
                } else if (copyType === "tags") {
                    textToCopy = (listing.tags || []).join(", ");
                } else if (copyType === "desc") {
                    textToCopy = listing.description || "";
                }
                
                navigator.clipboard.writeText(textToCopy).then(() => {
                    const origHtml = btn.innerHTML;
                    btn.classList.add("copied");
                    btn.innerHTML = `
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                            <polyline points="20 6 9 17 4 12"></polyline>
                        </svg>
                        <span>Copied!</span>
                    `;
                    setTimeout(() => {
                        btn.classList.remove("copied");
                        btn.innerHTML = origHtml;
                    }, 2000);
                }).catch(err => {
                    console.error("Clipboard copy failed:", err);
                });
            });
        });

        return panel;
    }

    function updateActionBtnState() {
        const checked = document.querySelectorAll(".queue-chk:checked");
        const hasChecked = checked.length > 0;
        btnExportSelected.disabled = !hasChecked;

        // Run Listings: active when at least one checked item is in "queued" or "done" status and not bulk running
        const hasQueueable = Array.from(checked).some(c => c.dataset.status === "queued" || c.dataset.status === "done");
        btnRunSelected.disabled = !hasQueueable || isBulkRunning;
    }

    // --- EXPORT ZIP ---
    btnExportSelected.addEventListener("click", () => {
        const checked = document.querySelectorAll(".queue-chk:checked");
        const slugs = Array.from(checked).map(c => c.dataset.slug);

        btnExportSelected.textContent = "Zipping...";
        btnExportSelected.disabled = true;

        fetch("/api/export-zip", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ product_slugs: slugs })
        }).then(res => {
            if (!res.ok) throw new Error("Export failed");
            return res.blob();
        }).then(blob => {
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = slugs.length === 1 ? `${slugs[0]}.zip` : "AliExpress_Batch_Export.zip";
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);

            btnExportSelected.textContent = "Export ZIP";
            btnExportSelected.disabled = false;
        }).catch(err => {
            alert(err.message);
            btnExportSelected.textContent = "Export ZIP";
            btnExportSelected.disabled = false;
        });
    });

    // --- BULK RUN LISTINGS ---
    btnRunSelected.addEventListener("click", async () => {
        const checked = Array.from(document.querySelectorAll(".queue-chk:checked"))
            .filter(c => c.dataset.status === "queued" || c.dataset.status === "done");

        if (checked.length === 0) return;

        isBulkRunning = true;
        btnRunSelected.disabled = true;
        btnRunSelected.textContent = `Running 0/${checked.length}...`;

        // Switch to Workspace tab so the user can see console progress
        navBtns[1].click();

        for (let i = 0; i < checked.length; i++) {
            const slug = checked[i].dataset.slug;
            btnRunSelected.textContent = `Running ${i + 1}/${checked.length}...`;
            logConsole("system", `Bulk run: Starting ${slug} (${i + 1}/${checked.length})`);

            try {
                await fetch("/api/run-pipeline", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        product_slug: slug,
                        mode: "listing_only",
                        theme: themeSelector.value || "bauhaus_beige",
                        preset: presetSelector.value || "product_staging"
                    })
                });
                // Wait for the SSE "done" or "error" event for this slug before continuing
                await waitForPipelineCompletion(slug);
            } catch (err) {
                logConsole("error", `Bulk run error on ${slug}: ${err.message}`);
            }
        }

        logConsole("success", `Bulk run complete. Processed ${checked.length} listing(s).`);
        isBulkRunning = false;
        btnRunSelected.textContent = "Run Listings";
        loadQueue();
    });

    /**
     * Returns a Promise that resolves when the SSE stream emits a "done" or "error"
     * event. Uses a poll + timeout approach to avoid blocking the SSE listener.
     * Resolves after max 5 minutes per item (safety net).
     */
    function waitForPipelineCompletion(slug) {
        return new Promise(resolve => {
            const TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes max
            let resolved = false;

            const timer = setTimeout(() => {
                if (!resolved) {
                    resolved = true;
                    resolve();
                }
            }, TIMEOUT_MS);

            // Poll metadata until status changes from "processing"
            const poll = setInterval(async () => {
                try {
                    const res = await fetch("/api/queue");
                    const data = await res.json();
                    const item = (data.queue || []).find(q => q.slug === slug);
                    if (item && item.status !== "processing" && item.status !== "queued") {
                        clearInterval(poll);
                        clearTimeout(timer);
                        if (!resolved) {
                            resolved = true;
                            resolve();
                        }
                    }
                } catch (_) {}
            }, 2000);
        });
    }

    // --- WORKSPACE & PIPELINE ---
    function selectForWorkspace(item) {
        selectedQueueItem = item;
        wsProductTitle.value = item.title;
        wsProductSlug.value = item.slug;
        btnGenerate.disabled = false;

        // Switch tab to Workspace
        navBtns[1].click();

        // Load data if already processed
        if (item.status === "done" && item.etsy_listing) {
            activeListing = item.etsy_listing;
            activeListing.slug = item.slug;
            populateWorkspace();
            populateVariationSpecs(item);

            if (item.prompts) {
                const varImgs = (item.variation_images || []).map(v => typeof v === 'object' ? v.local_path : v);
                renderPromptCards(item.prompts, item.slug, [...(item.main_images || []), ...varImgs, ...(item.description_images || [])]);
            }
        } else {
            // Reset workspace
            workspace.classList.add("disabled");
            etsyTitle.value = "";
            etsyPrice.value = "";
            etsyDesc.value = "";
            tagsContainer.innerHTML = "";
            imagesGrid.innerHTML = `<div class="image-placeholder">Run pipeline to generate images.</div>`;
            btnSave.disabled = true;
            variationsSpecsWrapper.style.display = "none";
            variationsSpecsList.innerHTML = "";
        }
    }

    btnGenerate.addEventListener("click", () => {
        const slug = wsProductSlug.value;
        if (!slug) return;

        logConsole("system", `Triggering pipeline for ${slug}...`);
        btnGenerate.disabled = true;

        fetch("/api/run-pipeline", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                product_slug: slug,
                mode: wsPipelineMode.value,
                theme: themeSelector.value,
                preset: presetSelector.value
            })
        });
    });

    // --- EVENT STREAM ---
    function connectStatusStream() {
        if (eventSource) return;
        eventSource = new EventSource("/api/status-stream");

        eventSource.onopen = () => logConsole("system", "Connected to pipeline events.");

        eventSource.onmessage = (e) => {
            const data = JSON.parse(e.data);
            if (data.status === "progress") {
                logConsole("progress", data.message);
                setActivityDot(true);
            } else if (data.status === "error") {
                logConsole("error", data.message);
                btnGenerate.disabled = false;
                setActivityDot(false);
            } else if (data.status === "done") {
                logConsole("success", data.message);
                btnGenerate.disabled = false;
                setActivityDot(false);

                if (data.listing) {
                    activeListing = data.listing;
                    activeListing.slug = data.output_dir_name;
                    populateWorkspace();
                    
                    loadQueue().then(() => {
                        const updatedItem = queueData.find(q => q.slug === activeListing.slug);
                        if (updatedItem) {
                            selectedQueueItem = updatedItem;
                            populateVariationSpecs(updatedItem);
                        }
                    });
                }
                if (data.prompts) {
                    let refImgs = [];
                    if (selectedQueueItem) {
                        const varImgs = (selectedQueueItem.variation_images || []).map(v => typeof v === 'object' ? v.local_path : v);
                        refImgs = [...(selectedQueueItem.main_images||[]), ...varImgs];
                    }
                    renderPromptCards(data.prompts, data.output_dir_name, refImgs);
                }
            } else if (data.status === "queue_updated") {
                loadQueue();
            }
        };

        eventSource.onerror = () => {
            if (eventSource) { eventSource.close(); eventSource = null; }
            setTimeout(connectStatusStream, 3000);
        };
    }

    function logConsole(type, msg) {
        const div = document.createElement("div");
        div.className = `log-entry ${type}`;
        div.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
        consoleLogs.appendChild(div);
        consoleLogs.scrollTop = consoleLogs.scrollHeight;
    }

    // --- EDITOR ---
    function populateWorkspace() {
        if (!activeListing) return;
        workspace.classList.remove("disabled");
        btnSave.disabled = false;

        etsyTitle.value = activeListing.title || "";
        if (etsyCategory) {
            etsyCategory.value = activeListing.category || "";
        }
        etsyPrice.value = activeListing.suggested_price || "";
        etsyDesc.value = activeListing.description || "";

        renderTags(activeListing.tags || []);
    }

    function populateVariationSpecs(item) {
        variationsSpecsList.innerHTML = "";
        const varImages = item.variation_images || [];
        if (varImages.length === 0) {
            variationsSpecsWrapper.style.display = "none";
            return;
        }
        
        variationsSpecsWrapper.style.display = "block";
        varImages.forEach((imgObj, idx) => {
            const isObj = typeof imgObj === "object" && imgObj !== null;
            const localPath = isObj ? imgObj.local_path : imgObj;
            const alt = isObj ? (imgObj.alt || imgObj.title || `Var ${idx+1}`) : `Var ${idx+1}`;
            const detected = isObj ? (imgObj.detected_specs || {}) : {};
            
            const sizeVal = detected.size || "";
            const dimVal = detected.dimensions || "";
            
            const itemRow = document.createElement("div");
            itemRow.className = "variation-spec-item";
            itemRow.dataset.index = idx;
            
            const imgSrc = `/api/product-image/${item.slug}/${encodeURIComponent(localPath)}`;
            
            itemRow.innerHTML = `
                <img class="variation-spec-thumb" src="${imgSrc}" alt="${alt}">
                <div class="variation-spec-info">
                    <span class="variation-spec-name">${alt}</span>
                </div>
                <div class="variation-spec-inputs">
                    <div class="variation-spec-input-group">
                        <label>Detected Size</label>
                        <input type="text" class="variation-spec-input var-size-input" value="${sizeVal}" placeholder="e.g. S, M, L">
                    </div>
                    <div class="variation-spec-input-group">
                        <label>Dimensions</label>
                        <input type="text" class="variation-spec-input var-dims-input" value="${dimVal}" placeholder="e.g. 30x40cm">
                    </div>
                </div>
            `;
            variationsSpecsList.appendChild(itemRow);
        });
    }

    function renderTags(tags) {
        tagsContainer.innerHTML = "";
        activeListing.tags = tags;
        tags.forEach((t, i) => {
            const chip = document.createElement("div");
            chip.className = "tag-chip";
            chip.innerHTML = `<span>${t}</span><span class="tag-remove" style="cursor:pointer; margin-left:4px;">&times;</span>`;
            chip.querySelector(".tag-remove").addEventListener("click", () => {
                const arr = [...tags];
                arr.splice(i, 1);
                renderTags(arr);
            });
            tagsContainer.appendChild(chip);
        });
    }

    function renderPromptCards(prompts, slug, refImages) {
        imagesGrid.innerHTML = "";
        if (!prompts || prompts.length === 0) {
            imagesGrid.innerHTML = `<div class="image-placeholder">No images generated.</div>`;
            return;
        }

        prompts.forEach((item) => {
            const card = document.createElement("div");
            card.className = "prompt-card";

            const imgWrap = document.createElement("div");
            imgWrap.className = "prompt-card-img-wrapper";
            const img = document.createElement("img");
            img.style.display = "none";
            imgWrap.appendChild(img);

            const content = document.createElement("div");
            content.className = "prompt-card-content";

            const p = document.createElement("textarea");
            p.className = "prompt-card-textarea";
            p.value = item.prompt;

            const btn = document.createElement("button");
            btn.className = "primary-btn btn-sm";
            btn.textContent = "Generate (Fal.ai)";

            btn.addEventListener("click", () => {
                btn.textContent = "Generating...";
                btn.disabled = true;

                const ref = refImages && refImages.length > 0 ? refImages[0].split("/").pop() : "scraped_1.png";

                fetch("/api/generate-image", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        prompt: p.value,
                        output_dir_name: slug,
                        image_name: `${item.name}.png`,
                        reference_image: ref
                    })
                }).then(r => r.json()).then(res => {
                    if (res.status === "success") {
                        img.src = res.image_url + "?t=" + Date.now();
                        img.style.display = "block";
                        btn.textContent = "Regenerate";
                    } else {
                        throw new Error("Failed");
                    }
                    btn.disabled = false;
                }).catch(() => {
                    alert("Generation failed");
                    btn.textContent = "Retry";
                    btn.disabled = false;
                });
            });

            content.appendChild(p);
            content.appendChild(btn);
            card.appendChild(imgWrap);
            card.appendChild(content);
            imagesGrid.appendChild(card);
        });
    }

    // Save metadata
    btnSave.addEventListener("click", () => {
        if (!activeListing) return;
        btnSave.disabled = true;
        btnSave.textContent = "Saving...";

        const updatedVars = [];
        const varRows = variationsSpecsList.querySelectorAll(".variation-spec-item");
        const originalVars = selectedQueueItem ? (selectedQueueItem.variation_images || []) : [];
        
        varRows.forEach((row) => {
            const idx = parseInt(row.dataset.index);
            const orig = originalVars[idx];
            const sizeInput = row.querySelector(".var-size-input").value.trim();
            const dimsInput = row.querySelector(".var-dims-input").value.trim();
            
            if (typeof orig === "object" && orig !== null) {
                updatedVars.push({
                    ...orig,
                    detected_specs: {
                        name: orig.alt || orig.title || `Var ${idx+1}`,
                        size: sizeInput,
                        dimensions: dimsInput,
                        other_details: orig.detected_specs?.other_details || ""
                    }
                });
            } else {
                updatedVars.push({
                    local_path: orig,
                    url: "",
                    alt: `Var ${idx+1}`,
                    title: `Var ${idx+1}`,
                    detected_specs: {
                        name: `Var ${idx+1}`,
                        size: sizeInput,
                        dimensions: dimsInput,
                        other_details: ""
                    }
                });
            }
        });

        fetch("/api/save-listing", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                title: etsyTitle.value,
                category: etsyCategory ? etsyCategory.value : "",
                suggested_price: etsyPrice.value,
                description: etsyDesc.value,
                tags: activeListing.tags,
                output_dir_name: activeListing.slug,
                variation_images: updatedVars.length > 0 ? updatedVars : null
            })
        }).then(r => r.json()).then(res => {
            btnSave.textContent = "Save Updates";
            btnSave.disabled = false;
            if (res.status === "success") {
                alert("Saved to metadata.json!");
                if (selectedQueueItem) {
                    selectedQueueItem.variation_images = updatedVars;
                }
                loadQueue();
            }
        });
    });

});
