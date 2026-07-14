document.addEventListener("DOMContentLoaded", () => {

    // UI Elements
    const navBtns = document.querySelectorAll(".nav-btn");
    const panels = document.querySelectorAll(".main-panel");
    const btnRefreshQueue = document.getElementById("btn-refresh-queue");
    const btnExportSelected = document.getElementById("btn-export-selected");
    const btnRunSelected = document.getElementById("btn-run-selected");
    const queueList = document.getElementById("queue-list");
    const filterCount = document.getElementById("filter-count");
    const chkQueueSelectAll = document.getElementById("chk-queue-select-all");

    // Console Sidebar
    const consoleSidebar = document.getElementById("console-sidebar");
    const btnToggleConsole = document.getElementById("btn-toggle-console");
    const btnClearConsole = document.getElementById("btn-clear-console");
    const consoleActivityDot = document.getElementById("console-activity-dot");
    const appMain = document.getElementById("app-main");
    const notificationStack = document.getElementById("notification-stack");

    // Filter pills
    const filterPills = document.querySelectorAll(".filter-pill");
    let activeFilter = "active"; // "active" | "completed"

    // Workspace Elements
    const wsProductTitle = document.getElementById("ws-product-title");
    const wsProductSlug = document.getElementById("ws-product-slug");
    const wsPipelineMode = document.getElementById("ws-pipeline-mode");
    const copywritingDepthSelect = document.getElementById("copywriting-depth-select");
    const copywritingDepthHint = document.getElementById("copywriting-depth-hint");
    const imageGenConfigContainer = document.getElementById("image-gen-config-container");
    const imageModelSelect = document.getElementById("image-model-select");
    const imageThinkingSelect = document.getElementById("image-thinking-select");
    const referencePickerContainer = document.getElementById("reference-picker-container");
    const referenceStatus = document.getElementById("reference-status");
    const referenceImageGrid = document.getElementById("reference-image-grid");
    const imageTasksList = document.getElementById("image-tasks-list");
    const btnAddTask = document.getElementById("btn-add-task");
    const btnGenerate = document.getElementById("btn-generate");
    const btnCancelPipeline = document.getElementById("btn-cancel-pipeline");

    const consoleLogs = document.getElementById("console-logs");
    const workspace = document.getElementById("listing-workspace");
    const btnTweakCopy = document.getElementById("btn-tweak-copy");
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
    const defaultCopywritingRules = [
        "You are an expert e-commerce copywriter and Etsy SEO strategist specializing in premium boutique branding. Transform raw supplier/manufacturer details into a polished, readable, high-converting Etsy listing while staying factually conservative.",
        "--- COPYWRITING AND COMPLIANCE RULES ---",
        "1. ABSOLUTE PROHIBITIONS: Never mention \"China\", \"AliExpress\", \"mass production\", \"factory\", \"wholesale\", \"dropshipping\", \"shipping tracking variations\", \"bulk order\", \"bulk pricing\", or \"bulk sale\". Do not claim small-batch, handmade, luxury, designer, eco-friendly, or premium materials unless directly supported by the source facts. Use a curated boutique tone without inventing business-model claims.",
        "2. TITLE RESTRICTIONS: Do not keyword-stuff titles or use pipe-separated keyword chains. Write one clear Etsy-ready buyer-friendly title under 140 characters, ideally 80-125 characters when enough supported details exist. Put the product noun and strongest objective identifiers in the first 50-60 characters.",
        "3. DESCRIPTION FORMATTING: Optimize for readability and scanning. Avoid large text walls. Use plain Etsy-safe text only: no markdown bold/italic, no asterisks for emphasis, and no underscores. For list items or attribute breakdowns, use a literal hyphen (-). Section headers may use ALL CAPS or clear title case, but keep them consistent.",
        "4. FACT SAFETY: Mention color, exact size, materials, capacity, closures, pockets, compatibility, gift audience, and care details only when supported by source text, image facts, or variation specs. If a detail is unknown, leave it out instead of guessing.",
        "5. TITLE-TAG MATCH: Ensure the 2 or 3 most important keyword phrases in the title exactly match 2 or 3 of the tags when possible, while keeping tags under 20 characters.",
        "6. OCCASION TARGETING: If clearly applicable, include 1 or 2 gift/use-intent tags such as \"gift for her\" or \"travel bag\", but do not force audience or occasion claims onto unrelated products."
    ].join("\n");
    const workspaceTokenValue = document.getElementById("workspace-token-value");
    const btnSwitchWorkspace = document.getElementById("btn-switch-workspace");

    // State
    let queueData = [];
    let selectedQueueItem = null;
    let eventSource = null;
    let activeListing = null;
    let isBulkRunning = false;
    let pipelineRunning = false;
    let bulkCancelRequested = false;
    let currentPipelineSlug = "";
    let userToken = localStorage.getItem("userToken") || "";
    let browserNotificationRequested = false;
    let activeTweakPreset = "fix_title";
    let imageTweakState = {
        item: null,
        imageEntry: null,
        imagePath: "",
        referencePath: "",
        previewContainer: null
    };
    const imageTweakingKeys = new Set();

    const modal = document.getElementById("app-modal");
    const modalTitle = document.getElementById("modal-title");
    const modalMessage = document.getElementById("modal-message");
    const modalInputWrap = document.getElementById("modal-input-wrap");
    const modalInputLabel = document.getElementById("modal-input-label");
    const modalInput = document.getElementById("modal-input");
    const modalClose = document.getElementById("modal-close");
    const modalCancel = document.getElementById("modal-cancel");
    const modalConfirm = document.getElementById("modal-confirm");

    const tweakModal = document.getElementById("tweak-modal");
    const tweakModalClose = document.getElementById("tweak-modal-close");
    const tweakModalCancel = document.getElementById("tweak-modal-cancel");
    const tweakModalRun = document.getElementById("tweak-modal-run");
    const tweakPresetGrid = document.getElementById("tweak-preset-grid");
    const tweakInstruction = document.getElementById("tweak-instruction");
    const tweakFieldInputs = document.querySelectorAll(".tweak-field");

    const imageTweakModal = document.getElementById("image-tweak-modal");
    const imageTweakModalClose = document.getElementById("image-tweak-modal-close");
    const imageTweakModalCancel = document.getElementById("image-tweak-modal-cancel");
    const imageTweakModalRun = document.getElementById("image-tweak-modal-run");
    const imageTweakPreviewImg = document.getElementById("image-tweak-preview-img");
    const imageTweakModelSelect = document.getElementById("image-tweak-model-select");
    const imageTweakThinkingSelect = document.getElementById("image-tweak-thinking-select");
    const imageTweakPromptMode = document.getElementById("image-tweak-prompt-mode");
    const imageTweakPresetGroup = document.getElementById("image-tweak-preset-group");
    const imageTweakPresetSelect = document.getElementById("image-tweak-preset-select");
    const imageTweakPresetHint = document.getElementById("image-tweak-preset-hint");
    const imageTweakCustomGroup = document.getElementById("image-tweak-custom-group");
    const imageTweakInstruction = document.getElementById("image-tweak-instruction");
    const imageTweakReferenceGrid = document.getElementById("image-tweak-reference-grid");
    const imageTweakReferenceHint = document.getElementById("image-tweak-reference-hint");

    function openModal({ title, message, confirmText = "Confirm", cancelText = "Cancel", danger = false, input = null, hideCancel = false, blocking = false }) {
        return new Promise(resolve => {
            let resolved = false;

            const cleanup = (value) => {
                if (resolved) return;
                resolved = true;
                modal.hidden = true;
                modalClose.hidden = false;
                modalConfirm.classList.remove("danger-btn");
                modalConfirm.classList.add("primary-btn");
                modalConfirm.removeEventListener("click", onConfirm);
                modalCancel.removeEventListener("click", onCancel);
                modalClose.removeEventListener("click", onCancel);
                modal.removeEventListener("click", onOverlayClick);
                document.removeEventListener("keydown", onKeydown);
                resolve(value);
            };

            const onConfirm = () => {
                if (input) {
                    const value = modalInput.value.trim();
                    if (!value) {
                        modalInput.focus();
                        return;
                    }
                    cleanup(value);
                    return;
                }
                cleanup(true);
            };
            const onCancel = () => {
                if (blocking) return;
                cleanup(input ? null : false);
            };
            const onOverlayClick = (event) => {
                if (event.target === modal) onCancel();
            };
            const onKeydown = (event) => {
                if (event.key === "Escape") onCancel();
                if (event.key === "Enter" && input && document.activeElement === modalInput) onConfirm();
            };

            modalTitle.textContent = title;
            modalMessage.textContent = message || "";
            modalConfirm.textContent = confirmText;
            modalCancel.textContent = cancelText;
            modalCancel.hidden = hideCancel || blocking;
            modalClose.hidden = blocking;

            if (danger) {
                modalConfirm.classList.remove("primary-btn");
                modalConfirm.classList.add("danger-btn");
            }

            if (input) {
                modalInputWrap.hidden = false;
                modalInputLabel.textContent = input.label || "Name";
                modalInput.value = input.value || "";
                modalInput.placeholder = input.placeholder || "";
            } else {
                modalInputWrap.hidden = true;
                modalInput.value = "";
            }

            modal.hidden = false;
            modalConfirm.addEventListener("click", onConfirm);
            modalCancel.addEventListener("click", onCancel);
            modalClose.addEventListener("click", onCancel);
            modal.addEventListener("click", onOverlayClick);
            document.addEventListener("keydown", onKeydown);

            setTimeout(() => {
                if (input) {
                    modalInput.focus();
                    modalInput.select();
                } else {
                    modalConfirm.focus();
                }
            }, 0);
        });
    }

    function showInfoModal(title, message) {
        return openModal({
            title,
            message,
            confirmText: "OK",
            hideCancel: true
        });
    }

    function showAppNotification({ title, message, type = "info", timeout = 7000 }) {
        if (!notificationStack) return;

        const item = document.createElement("div");
        item.className = `app-notification notification-${type}`;
        item.setAttribute("role", type === "error" ? "alert" : "status");

        const content = document.createElement("div");
        content.className = "notification-content";

        const titleEl = document.createElement("strong");
        titleEl.className = "notification-title";
        titleEl.textContent = title || "Notification";

        const messageEl = document.createElement("p");
        messageEl.className = "notification-message";
        messageEl.textContent = message || "";

        const closeBtn = document.createElement("button");
        closeBtn.type = "button";
        closeBtn.className = "notification-close";
        closeBtn.setAttribute("aria-label", "Dismiss notification");
        closeBtn.textContent = "X";

        const dismiss = () => {
            item.classList.add("leaving");
            setTimeout(() => item.remove(), 180);
        };

        closeBtn.addEventListener("click", dismiss);
        content.appendChild(titleEl);
        content.appendChild(messageEl);
        item.appendChild(content);
        item.appendChild(closeBtn);
        notificationStack.appendChild(item);

        if (timeout > 0) {
            setTimeout(dismiss, timeout);
        }
    }

    async function requestBrowserNotificationPermission() {
        if (!("Notification" in window) || browserNotificationRequested) return;
        browserNotificationRequested = true;
        if (Notification.permission === "default") {
            try {
                await Notification.requestPermission();
            } catch (_) {}
        }
    }

    function showBrowserNotification(title, message, type = "info") {
        if (!("Notification" in window) || Notification.permission !== "granted") return;
        try {
            new Notification(title || "Pipeline update", {
                body: message || "",
                tag: `etsy-pipeline-${type}-${Date.now()}`,
                silent: false
            });
        } catch (_) {}
    }

    function notifyPipeline({ title, message, type = "info", browser = true }) {
        showAppNotification({ title, message, type });
        if (browser) {
            showBrowserNotification(title, message, type);
        }
    }

    function sanitizeWorkspaceToken(value) {
        return String(value || "").replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 64);
    }

    function updateWorkspaceTokenUI() {
        if (workspaceTokenValue) {
            workspaceTokenValue.textContent = userToken || "Not set";
            workspaceTokenValue.title = userToken || "";
        }
    }

    function apiFetch(url, options = {}) {
        const headers = new Headers(options.headers || {});
        if (userToken) {
            headers.set("X-User-Token", userToken);
        }
        return fetch(url, { ...options, headers });
    }

    function withTokenQuery(url) {
        const finalUrl = new URL(url, window.location.origin);
        if (userToken) {
            finalUrl.searchParams.set("token", userToken);
        }
        return `${finalUrl.pathname}${finalUrl.search}${finalUrl.hash}`;
    }

    function setTweakFields(fields) {
        const selected = new Set(fields || []);
        tweakFieldInputs.forEach(input => {
            input.checked = selected.has(input.value);
        });
    }

    function getSelectedTweakFields() {
        return Array.from(tweakFieldInputs)
            .filter(input => input.checked)
            .map(input => input.value);
    }

    function selectTweakPreset(button) {
        if (!button) return;
        activeTweakPreset = button.dataset.presetKey || "custom";
        tweakPresetGrid.querySelectorAll(".tweak-preset-btn").forEach(btn => {
            btn.classList.toggle("selected", btn === button);
        });
        const fields = (button.dataset.fields || "")
            .split(",")
            .map(field => field.trim())
            .filter(Boolean);
        setTweakFields(fields.length ? fields : ["title", "category", "description", "tags"]);
        if (activeTweakPreset === "custom" && tweakInstruction) {
            setTimeout(() => tweakInstruction.focus(), 0);
        }
    }

    function getEditorListingSnapshot() {
        const currentTags = activeListing && Array.isArray(activeListing.tags) ? activeListing.tags : [];
        return {
            ...(activeListing || {}),
            title: etsyTitle.value || "",
            category: etsyCategory ? etsyCategory.value || "" : "",
            suggested_price: etsyPrice.value || "",
            description: etsyDesc.value || "",
            tags: currentTags
        };
    }

    function applyTweakedListingToEditor(listing) {
        if (!listing || !activeListing) return;
        activeListing = {
            ...activeListing,
            ...listing,
            slug: activeListing.slug
        };
        populateWorkspace();
        workspace.classList.add("has-unsaved-tweak");
        btnSave.textContent = "Save Tweaked Copy";
        btnSave.disabled = false;
        logConsole("success", "AI copy tweak generated. Review it, then click Save Updates when ready.");
        notifyPipeline({
            title: "Copy Tweak Ready",
            message: "The editor has been updated, but the listing is not saved yet.",
            type: "success",
            browser: false
        });
    }

    function openTweakCopyModal() {
        if (!activeListing || !activeListing.slug) {
            showInfoModal("No Listing Selected", "Select a completed listing before tweaking copy.");
            return;
        }
        tweakModal.hidden = false;
        const selectedButton = tweakPresetGrid.querySelector(".tweak-preset-btn.selected") || tweakPresetGrid.querySelector(".tweak-preset-btn");
        selectTweakPreset(selectedButton);
        setTimeout(() => tweakModalRun.focus(), 0);
    }

    function closeTweakCopyModal() {
        tweakModal.hidden = true;
    }

    async function runCopyTweak() {
        if (!activeListing || !activeListing.slug) return;
        const fields = getSelectedTweakFields();
        if (fields.length === 0) {
            await showInfoModal("Choose Fields", "Select at least one field to update.");
            return;
        }

        const previousText = tweakModalRun.textContent;
        tweakModalRun.disabled = true;
        tweakModalRun.textContent = "Generating...";

        try {
            const res = await apiFetch("/api/tweak-listing", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    output_dir_name: activeListing.slug,
                    preset_key: activeTweakPreset,
                    instruction: tweakInstruction.value.trim(),
                    fields,
                    context_mode: "existing_output",
                    current_listing: getEditorListingSnapshot()
                })
            });
            const payload = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(payload.detail || payload.message || "Copy tweak failed");
            }
            applyTweakedListingToEditor(payload.listing);
            closeTweakCopyModal();
        } catch (err) {
            logConsole("error", err.message);
            await showInfoModal("Copy Tweak Failed", err.message);
        } finally {
            tweakModalRun.disabled = false;
            tweakModalRun.textContent = previousText;
        }
    }

    if (tweakPresetGrid) {
        tweakPresetGrid.addEventListener("click", (event) => {
            const button = event.target.closest(".tweak-preset-btn");
            if (button) selectTweakPreset(button);
        });
    }

    if (btnTweakCopy) {
        btnTweakCopy.addEventListener("click", openTweakCopyModal);
    }

    if (tweakModalClose) tweakModalClose.addEventListener("click", closeTweakCopyModal);
    if (tweakModalCancel) tweakModalCancel.addEventListener("click", closeTweakCopyModal);
    if (tweakModalRun) tweakModalRun.addEventListener("click", runCopyTweak);
    if (tweakModal) {
        tweakModal.addEventListener("click", (event) => {
            if (event.target === tweakModal) closeTweakCopyModal();
        });
        document.addEventListener("keydown", (event) => {
            if (!tweakModal.hidden && event.key === "Escape") closeTweakCopyModal();
        });
    }

    async function promptForWorkspaceToken(initialValue = "", forcePrompt = false) {
        let nextToken = forcePrompt ? "" : sanitizeWorkspaceToken(initialValue || userToken);
        while (!nextToken) {
            const entered = await openModal({
                title: "Enter Your Workspace Token",
                message: "Your token keeps your queued products, images, and exports separate from other users.",
                confirmText: "Continue",
                input: {
                    label: "User Token",
                    placeholder: "e.g. tyrone-abc123",
                    value: initialValue || ""
                },
                hideCancel: true,
                blocking: true
            });
            nextToken = sanitizeWorkspaceToken(entered);
        }

        userToken = nextToken;
        localStorage.setItem("userToken", userToken);
        updateWorkspaceTokenUI();
        return userToken;
    }

    function resetWorkspaceState() {
        queueData = [];
        selectedQueueItem = null;
        activeListing = null;
        queueList.innerHTML = "";
        wsProductTitle.value = "";
        wsProductSlug.value = "";
        btnGenerate.disabled = true;
        if (btnTweakCopy) btnTweakCopy.disabled = true;
        btnSave.textContent = "Save Updates";
        workspace.classList.add("disabled");
        workspace.classList.remove("has-unsaved-tweak");
        etsyTitle.value = "";
        if (etsyCategory) etsyCategory.value = "";
        etsyPrice.value = "";
        etsyDesc.value = "";
        tagsContainer.innerHTML = "";
        imagesGrid.innerHTML = `<div class="image-placeholder">Run pipeline to generate images.</div>`;
        variationsSpecsWrapper.style.display = "none";
        variationsSpecsList.innerHTML = "";
        renderReferencePicker(null);
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
        setActivityDot(false);
    }

    async function switchWorkspace() {
        const previousToken = userToken;
        localStorage.removeItem("userToken");
        userToken = "";
        updateWorkspaceTokenUI();
        await promptForWorkspaceToken(previousToken, true);
        resetWorkspaceState();
        loadQueue();
        connectStatusStream();
    }

    if (btnSwitchWorkspace) {
        btnSwitchWorkspace.addEventListener("click", switchWorkspace);
    }

    // --- INITIALIZATION ---
    async function initializeApp() {
        updateWorkspaceTokenUI();
        await promptForWorkspaceToken(userToken);
        loadSettings();
        loadPresets();
        loadQueue();
        connectStatusStream();
    }

    initializeApp();

    // --- CONSOLE SIDEBAR ---
    btnToggleConsole.addEventListener("click", () => {
        const isOpen = consoleSidebar.classList.toggle("open");
        btnToggleConsole.classList.toggle("active", isOpen);
        appMain.classList.toggle("console-open", isOpen);
    });

    btnClearConsole.addEventListener("click", () => {
        consoleLogs.innerHTML = "";
    });

    function setActivityDot(running, slug = "") {
        pipelineRunning = running;
        if (running) {
            currentPipelineSlug = slug || currentPipelineSlug || wsProductSlug.value || "";
        } else {
            currentPipelineSlug = "";
            bulkCancelRequested = false;
        }
        consoleActivityDot.classList.toggle("running", running);
        if (btnCancelPipeline) {
            btnCancelPipeline.hidden = !running;
            btnCancelPipeline.disabled = !running || !currentPipelineSlug;
            if (!running) {
                btnCancelPipeline.textContent = "Stop Pipeline";
            }
        }
        if (btnGenerate) {
            btnGenerate.disabled = running || !wsProductSlug.value;
        }
    }

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

    // --- SELECT ALL ---
    if (chkQueueSelectAll) {
        chkQueueSelectAll.addEventListener("change", (e) => {
            const isChecked = e.target.checked;
            document.querySelectorAll(".queue-chk").forEach(chk => {
                chk.checked = isChecked;
            });
            updateActionBtnState();
        });
    }

    // --- SETTINGS ---
    function loadSettings() {
        apiFetch("/api/settings")
            .then(r => r.json())
            .then(data => {
                settingOutputDir.value = data.output_dir || "";
                settingOutputDir.disabled = Boolean(data.hosted_mode);
                btnSaveSettings.disabled = Boolean(data.hosted_mode);
                if (data.hosted_mode) {
                    settingsStatus.textContent = "Output directory is locked in hosted mode.";
                    settingsStatus.style.display = "block";
                } else {
                    settingsStatus.style.display = "none";
                }
            });
    }

    btnSaveSettings.addEventListener("click", () => {
        const payload = { output_dir: settingOutputDir.value.trim() };
        apiFetch("/api/settings", {
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
        apiFetch("/api/listing-presets")
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
            presetCustomPromptRules.value = defaultCopywritingRules;
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
        apiFetch("/api/listing-presets", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        }).then(r => r.json()).then(() => {
            presetsStatus.style.display = "block";
            setTimeout(() => presetsStatus.style.display = "none", 3000);
        });
    });

    // --- IMAGE GENERATION TASKS & PRESETS ---
    const presetSelector = document.getElementById("preset-selector");
    const btnSavePreset = document.getElementById("btn-save-preset");
    const btnDeletePreset = document.getElementById("btn-delete-preset");
    const btnAddBatchTask = document.getElementById("btn-add-batch-task");
    const btnAddIndividualTask = document.getElementById("btn-add-individual-task");
    const defaultImageSettings = {
        model_key: "flux-kontext-pro",
        thinking_level: "off"
    };
    const defaultPromptPreset = "auto_product_staging";
    let imageModelOptions = [
        {
            key: "flux-kontext-pro",
            label: "Flux Kontext Pro",
            supports_thinking: false,
            recommended_for: "Variation batches and reliable day-to-day listing images."
        }
    ];
    let imageThinkingLevels = [
        { key: "off", label: "Off", description: "Do not send a thinking parameter." },
        { key: "minimal", label: "Minimal", description: "Light reasoning for smarter edits." },
        { key: "high", label: "High", description: "Best for hero/showcase edits." }
    ];
    let imagePromptPresets = [
        {
            key: "auto_product_staging",
            label: "Adaptive Product Staging",
            description: "Creates a polished marketplace-ready product scene with tasteful context."
        },
        {
            key: "auto_lifestyle_model",
            label: "Modeled By Someone",
            description: "Show the product worn, held, carried, or used by an appropriate person."
        },
        {
            key: "auto_in_use",
            label: "In Use",
            description: "Show the product actively being used in the most likely real-world context."
        },
        {
            key: "clean_catalog",
            label: "Clean Catalog Hero",
            description: "A simple ecommerce hero shot with better lighting and a clean background."
        },
        {
            key: "detail_closeup",
            label: "Detail Close-up",
            description: "A closer product detail shot focused on texture, material, finish, or craftsmanship."
        },
        {
            key: "gift_unboxing",
            label: "Gift / Unboxing",
            description: "Show the product in a giftable unboxing or premium packaging scene."
        },
        {
            key: "luxury_editorial_plinth",
            label: "Luxury Editorial Plinth",
            description: "A high-end editorial product shot on a minimalist geometric plinth."
        }
    ];

    function getImageSettings() {
        const modelKey = imageModelSelect ? imageModelSelect.value : defaultImageSettings.model_key;
        const thinkingLevel = imageThinkingSelect ? imageThinkingSelect.value : defaultImageSettings.thinking_level;
        return {
            model_key: modelKey,
            thinking_level: supportsModelThinking(modelKey) ? thinkingLevel : "off"
        };
    }

    function getCopywritingOptions() {
        return {
            depth: copywritingDepthSelect ? copywritingDepthSelect.value : "quality"
        };
    }

    function setImageSettings(settings = {}) {
        const next = {
            model_key: settings.model_key || defaultImageSettings.model_key,
            thinking_level: settings.thinking_level || defaultImageSettings.thinking_level
        };

        if (imageModelSelect) {
            const option = imageModelSelect.querySelector(`option[value="${next.model_key}"]`);
            imageModelSelect.value = option ? next.model_key : defaultImageSettings.model_key;
        }
        if (imageThinkingSelect) {
            const option = imageThinkingSelect.querySelector(`option[value="${next.thinking_level}"]`);
            imageThinkingSelect.value = option ? next.thinking_level : defaultImageSettings.thinking_level;
        }
        syncGlobalThinkingUI();
    }

    function loadImageGenerationOptions() {
        if (!imageModelSelect) return Promise.resolve();

        const current = getImageSettings();
        return apiFetch("/api/image-generation-options")
            .then(r => r.json())
            .then(data => {
                defaultImageSettings.model_key = data.default_model_key || defaultImageSettings.model_key;
                imageModelOptions = data.models && data.models.length ? data.models : imageModelOptions;
                imageThinkingLevels = data.thinking_levels && data.thinking_levels.length ? data.thinking_levels : imageThinkingLevels;

                imageModelSelect.innerHTML = "";
                imageModelOptions.forEach(model => {
                    const option = document.createElement("option");
                    option.value = model.key;
                    option.textContent = model.key === data.default_model_key ? `${model.label} (Default)` : model.label;
                    imageModelSelect.appendChild(option);
                });
                if (imageThinkingSelect) {
                    imageThinkingSelect.innerHTML = buildThinkingLevelOptions(current.thinking_level || defaultImageSettings.thinking_level);
                }

                setImageSettings({
                    model_key: current.model_key || defaultImageSettings.model_key,
                    thinking_level: current.thinking_level || defaultImageSettings.thinking_level
                });
            })
            .catch(() => setImageSettings(defaultImageSettings));
    }

    function getImageModelOption(key) {
        return imageModelOptions.find(model => model.key === key);
    }

    function supportsModelThinking(key) {
        return Boolean(getImageModelOption(key)?.supports_thinking);
    }

    function supportsMultipleReferenceImages(key) {
        return Boolean(getImageModelOption(key)?.input_image_list);
    }

    function buildModelOptions(selectedKey = "", includeInherit = false) {
        const options = [];
        if (includeInherit) {
            options.push(`<option value=""${selectedKey ? "" : " selected"}>Use global model</option>`);
        }
        imageModelOptions.forEach(model => {
            const selected = model.key === selectedKey ? " selected" : "";
            options.push(`<option value="${model.key}"${selected}>${model.label}</option>`);
        });
        return options.join("");
    }

    function buildThinkingLevelOptions(selectedKey = "off", includeInherit = false) {
        const options = [];
        if (includeInherit) {
            options.push(`<option value="inherit"${!selectedKey || selectedKey === "inherit" ? " selected" : ""}>Use global/default</option>`);
        }
        imageThinkingLevels.forEach(level => {
            const selected = level.key === selectedKey ? " selected" : "";
            options.push(`<option value="${level.key}"${selected}>${level.label}</option>`);
        });
        return options.join("");
    }

    function syncGlobalThinkingUI() {
        if (!imageThinkingSelect || !imageModelSelect) return;
        const supportsThinking = supportsModelThinking(imageModelSelect.value);
        imageThinkingSelect.disabled = !supportsThinking;
        imageThinkingSelect.closest(".input-group")?.classList.toggle("is-muted", !supportsThinking);
        if (!supportsThinking) {
            imageThinkingSelect.value = "off";
        }
        syncAllTaskModelUI();
    }

    if (imageModelSelect) {
        imageModelSelect.addEventListener("change", syncGlobalThinkingUI);
    }

    if (imageThinkingSelect) {
        imageThinkingSelect.addEventListener("change", syncAllTaskModelUI);
    }

    function loadImagePromptPresets() {
        return apiFetch("/api/image-prompt-presets")
            .then(r => r.json())
            .then(data => {
                if (Array.isArray(data.presets) && data.presets.length > 0) {
                    imagePromptPresets = data.presets;
                }
            })
            .catch(() => {});
    }

    function buildPromptPresetOptions(selectedKey = defaultPromptPreset) {
        return imagePromptPresets.map(preset => {
            const selected = preset.key === selectedKey ? " selected" : "";
            return `<option value="${preset.key}"${selected}>${preset.label}</option>`;
        }).join("");
    }

    function getPromptPresetDescription(key) {
        return imagePromptPresets.find(preset => preset.key === key)?.description || "";
    }

    function syncImageTweakPromptUI() {
        if (!imageTweakPromptMode || !imageTweakPresetGroup || !imageTweakCustomGroup) return;
        const isPreset = imageTweakPromptMode.value === "preset";
        imageTweakPresetGroup.hidden = !isPreset;
        imageTweakCustomGroup.hidden = isPreset;
        if (imageTweakPresetHint && imageTweakPresetSelect) {
            imageTweakPresetHint.textContent = getPromptPresetDescription(imageTweakPresetSelect.value);
        }
    }

    function syncImageTweakModelUI() {
        if (!imageTweakModelSelect || !imageTweakThinkingSelect || !imageTweakReferenceHint) return;
        const modelKey = imageTweakModelSelect.value || defaultImageSettings.model_key;
        const supportsThinking = supportsModelThinking(modelKey);
        const supportsMultiRef = supportsMultipleReferenceImages(modelKey);
        imageTweakThinkingSelect.disabled = !supportsThinking;
        imageTweakThinkingSelect.closest(".input-group")?.classList.toggle("is-muted", !supportsThinking);
        if (!supportsThinking) {
            imageTweakThinkingSelect.value = "off";
        }

        if (imageTweakState.referencePath && !supportsMultiRef) {
            imageTweakReferenceHint.textContent = "This model only accepts one image, so the extra product reference will be ignored. Use Nano Banana 2 Edit to send both.";
        } else if (imageTweakState.referencePath && supportsMultiRef) {
            imageTweakReferenceHint.textContent = "The selected generated image and this product reference will both be sent to the model.";
        } else {
            imageTweakReferenceHint.textContent = "Choose an original product image if you want extra product-accuracy guidance.";
        }
    }

    function populateImageTweakControls() {
        if (imageTweakModelSelect) {
            imageTweakModelSelect.innerHTML = buildModelOptions(defaultImageSettings.model_key, false);
            imageTweakModelSelect.value = defaultImageSettings.model_key;
        }
        if (imageTweakThinkingSelect) {
            imageTweakThinkingSelect.innerHTML = buildThinkingLevelOptions(defaultImageSettings.thinking_level, false);
            imageTweakThinkingSelect.value = defaultImageSettings.thinking_level;
        }
        if (imageTweakPresetSelect) {
            imageTweakPresetSelect.innerHTML = buildPromptPresetOptions(defaultPromptPreset);
            imageTweakPresetSelect.value = defaultPromptPreset;
        }
        if (imageTweakPromptMode) {
            imageTweakPromptMode.value = "preset";
        }
        if (imageTweakInstruction) {
            imageTweakInstruction.value = "";
        }
        syncImageTweakPromptUI();
        syncImageTweakModelUI();
    }

    function renderImageTweakReferenceGrid(item) {
        if (!imageTweakReferenceGrid) return;
        imageTweakReferenceGrid.innerHTML = "";

        const noneButton = document.createElement("button");
        noneButton.type = "button";
        noneButton.className = `reference-image-card ${!imageTweakState.referencePath ? "selected" : ""}`;
        noneButton.innerHTML = `
            <div class="image-tweak-no-reference">No extra reference</div>
            <span class="reference-selected-badge">Selected</span>
        `;
        noneButton.addEventListener("click", () => {
            imageTweakState.referencePath = "";
            renderImageTweakReferenceGrid(item);
            syncImageTweakModelUI();
        });
        imageTweakReferenceGrid.appendChild(noneButton);

        const candidates = collectReferenceCandidates(item);
        candidates.forEach(candidate => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = `reference-image-card ${imageTweakState.referencePath === candidate.local_path ? "selected" : ""}`;

            const sourcePill = document.createElement("span");
            sourcePill.className = "reference-source-pill";
            sourcePill.textContent = `${candidate.source_label} ${candidate.index}`;

            const img = document.createElement("img");
            img.src = getProductImageSrc(item.slug, candidate.local_path);
            img.alt = candidate.label;
            img.loading = "lazy";

            const label = document.createElement("span");
            label.className = "reference-card-label";
            label.textContent = candidate.label;

            const selectedBadge = document.createElement("span");
            selectedBadge.className = "reference-selected-badge";
            selectedBadge.textContent = "Selected";

            button.appendChild(sourcePill);
            button.appendChild(img);
            button.appendChild(label);
            button.appendChild(selectedBadge);
            button.addEventListener("click", () => {
                imageTweakState.referencePath = candidate.local_path;
                renderImageTweakReferenceGrid(item);
                syncImageTweakModelUI();
            });
            imageTweakReferenceGrid.appendChild(button);
        });
    }

    function openGeneratedImageTweakModal(item, imageEntry, previewContainer = null) {
        const imagePath = getImagePath(imageEntry);
        if (!item?.slug || !imagePath) {
            showInfoModal("No Image Selected", "Choose a generated image before tweaking.");
            return;
        }

        imageTweakState = {
            item,
            imageEntry,
            imagePath,
            referencePath: "",
            previewContainer
        };
        populateImageTweakControls();
        if (imageTweakPreviewImg) {
            imageTweakPreviewImg.src = getProductImageSrc(item.slug, imagePath, true);
        }
        renderImageTweakReferenceGrid(item);
        imageTweakModal.hidden = false;
        setTimeout(() => imageTweakModalRun?.focus(), 0);
    }

    function closeGeneratedImageTweakModal() {
        if (imageTweakModal) imageTweakModal.hidden = true;
    }

    function applyGeneratedImageTweakResult(slug, generatedImages) {
        const product = queueData.find(item => item.slug === slug) || imageTweakState.item;
        if (product) {
            product.generated_images = generatedImages;
        }
        if (selectedQueueItem?.slug === slug) {
            selectedQueueItem.generated_images = generatedImages;
            renderGeneratedImages(generatedImages, slug);
        }
        if (imageTweakState.item?.slug === slug) {
            imageTweakState.item.generated_images = generatedImages;
        }
        if (imageTweakState.previewContainer && imageTweakState.item) {
            renderPreviewGeneratedImages(imageTweakState.previewContainer, generatedImages, slug, imageTweakState.item);
        }
    }

    function getImageTweakKey(slug, imagePath) {
        return `${slug || ""}::${imagePath || ""}`;
    }

    function isImageTweaking(slug, imagePath) {
        return imageTweakingKeys.has(getImageTweakKey(slug, imagePath));
    }

    function refreshGeneratedImageDisplays(slug) {
        const product = queueData.find(item => item.slug === slug) || imageTweakState.item;
        const generatedImages = product?.generated_images || imageTweakState.item?.generated_images || [];
        if (selectedQueueItem?.slug === slug) {
            renderGeneratedImages(generatedImages, slug);
        }
        if (imageTweakState.previewContainer && imageTweakState.item?.slug === slug) {
            renderPreviewGeneratedImages(imageTweakState.previewContainer, generatedImages, slug, imageTweakState.item);
        }
    }

    async function runGeneratedImageTweak() {
        const item = imageTweakState.item;
        if (!item?.slug || !imageTweakState.imagePath) return;

        const promptMode = imageTweakPromptMode ? imageTweakPromptMode.value : "preset";
        const customPrompt = imageTweakInstruction ? imageTweakInstruction.value.trim() : "";
        if (promptMode === "custom" && !customPrompt) {
            await showInfoModal("Custom Prompt Needed", "Write a custom instruction or switch back to Preset.");
            return;
        }

        const previousText = imageTweakModalRun.textContent;
        const tweakKey = getImageTweakKey(item.slug, imageTweakState.imagePath);
        const modelLabel = getImageModelOption(imageTweakModelSelect ? imageTweakModelSelect.value : defaultImageSettings.model_key)?.label || "selected model";
        imageTweakingKeys.add(tweakKey);
        refreshGeneratedImageDisplays(item.slug);
        logConsole("progress", `Tweaking generated image ${imageTweakState.imagePath} for ${item.slug} with ${modelLabel}...`);
        imageTweakModalRun.disabled = true;
        imageTweakModalRun.textContent = "Generating...";

        try {
            const res = await apiFetch("/api/tweak-generated-image", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    product_slug: item.slug,
                    generated_image: imageTweakState.imagePath,
                    reference_image: imageTweakState.referencePath,
                    prompt_mode: promptMode,
                    prompt_preset: imageTweakPresetSelect ? imageTweakPresetSelect.value : defaultPromptPreset,
                    prompt: customPrompt,
                    model_key: imageTweakModelSelect ? imageTweakModelSelect.value : defaultImageSettings.model_key,
                    thinking_level: imageTweakThinkingSelect ? imageTweakThinkingSelect.value : "off"
                })
            });
            const payload = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(payload.detail || payload.message || "Image tweak failed");
            }

            applyGeneratedImageTweakResult(item.slug, payload.generated_images || []);
            closeGeneratedImageTweakModal();
            logConsole("success", `Image tweak finished for ${item.slug}. Added ${payload.generated_image?.local_path || "new generated image"}.`);
            notifyPipeline({
                title: "Image Tweak Finished",
                message: payload.reference_image_ignored
                    ? "Created a new tweaked image. Extra product reference was ignored by this model."
                    : "Created a new tweaked image and added it to this listing.",
                type: "success",
                browser: false
            });
        } catch (err) {
            logConsole("error", err.message);
            await showInfoModal("Image Tweak Failed", err.message);
        } finally {
            imageTweakingKeys.delete(tweakKey);
            refreshGeneratedImageDisplays(item.slug);
            imageTweakModalRun.disabled = false;
            imageTweakModalRun.textContent = previousText;
        }
    }

    if (imageTweakPromptMode) imageTweakPromptMode.addEventListener("change", syncImageTweakPromptUI);
    if (imageTweakPresetSelect) imageTweakPresetSelect.addEventListener("change", syncImageTweakPromptUI);
    if (imageTweakModelSelect) imageTweakModelSelect.addEventListener("change", syncImageTweakModelUI);
    if (imageTweakModalClose) imageTweakModalClose.addEventListener("click", closeGeneratedImageTweakModal);
    if (imageTweakModalCancel) imageTweakModalCancel.addEventListener("click", closeGeneratedImageTweakModal);
    if (imageTweakModalRun) imageTweakModalRun.addEventListener("click", runGeneratedImageTweak);
    if (imageTweakModal) {
        imageTweakModal.addEventListener("click", (event) => {
            if (event.target === imageTweakModal) closeGeneratedImageTweakModal();
        });
        document.addEventListener("keydown", (event) => {
            if (!imageTweakModal.hidden && event.key === "Escape") closeGeneratedImageTweakModal();
        });
    }

    function applyGenerationPreset(presetName) {
        if (!presetName || !window.generationPresets || !window.generationPresets[presetName]) return false;
        const preset = window.generationPresets[presetName];

        wsPipelineMode.value = preset.mode || "listing_only";
        wsPipelineMode.dispatchEvent(new Event("change"));
        setImageSettings(preset.image_settings);

        if (imageTasksList) {
            imageTasksList.innerHTML = "";
            if (preset.image_tasks) {
                preset.image_tasks.forEach(task => {
                    imageTasksList.appendChild(createTaskRow(task.task_type || "batch", task.target, task));
                });
            }
        }

        return true;
    }
    
    function loadGenerationPresets() {
        if (!presetSelector) return;
        apiFetch("/api/generation-presets")
            .then(r => r.json())
            .then(data => {
                window.generationPresets = data;
                const currentVal = presetSelector.value;
                presetSelector.innerHTML = '<option value="">-- Load a Preset --</option>';
                for (const name in data) {
                    const opt = document.createElement("option");
                    opt.value = name;
                    opt.textContent = name;
                    presetSelector.appendChild(opt);
                }
                if (data[currentVal]) {
                    presetSelector.value = currentVal;
                } else if (data.default && imageTasksList && imageTasksList.children.length === 0) {
                    presetSelector.value = "default";
                    applyGenerationPreset("default");
                }
            })
            .catch(console.error);
    }
    
    if (presetSelector) {
        Promise.all([loadImageGenerationOptions(), loadImagePromptPresets()]).then(loadGenerationPresets);
        
        presetSelector.addEventListener("change", () => {
            const presetName = presetSelector.value;
            applyGenerationPreset(presetName);
        });
        
        btnSavePreset.addEventListener("click", async (e) => {
            e.preventDefault();
            const name = await openModal({
                title: "Save Pipeline Preset",
                message: "Name this pipeline setup so you can reuse the same image generation tasks later.",
                confirmText: "Save Preset",
                input: {
                    label: "Preset Name",
                    placeholder: "e.g. Hero + variation refresh",
                    value: presetSelector.value || ""
                }
            });
            if (!name) return;
            
            const payload = {
                name: name,
                mode: wsPipelineMode.value,
                image_tasks: getImageTasks(),
                image_settings: getImageSettings()
            };
            
            apiFetch("/api/generation-presets", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            }).then(() => {
                loadGenerationPresets();
                presetSelector.value = name;
            });
        });
        
        btnDeletePreset.addEventListener("click", async (e) => {
            e.preventDefault();
            const name = presetSelector.value;
            if (!name) {
                await showInfoModal("No Preset Selected", "Choose a pipeline preset before deleting.");
                return;
            }
            const confirmed = await openModal({
                title: "Delete Pipeline Preset",
                message: `Delete "${name}"? This removes the saved preset only; it will not delete products or generated listings.`,
                confirmText: "Delete Preset",
                danger: true
            });
            if (!confirmed) return;
            
            apiFetch("/api/generation-presets/delete", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: name })
            }).then(() => {
                presetSelector.value = "";
                loadGenerationPresets();
            });
        });
    }

    function syncPipelineModeUI() {
        if (imageGenConfigContainer) {
            imageGenConfigContainer.classList.toggle("is-visible", isImagePipelineMode());
        }
        if (copywritingDepthSelect) {
            copywritingDepthSelect.disabled = wsPipelineMode.value === "images_only";
        }
        syncCopywritingDepthHint();
    }

    function syncCopywritingDepthHint() {
        if (!copywritingDepthHint || !copywritingDepthSelect) return;
        const hints = {
            fast: "Fast Batch is text-first and uses the fewest image/spec scans. Best for rough bulk drafts.",
            balanced: "Balanced keeps quality high while capping expensive variation scans.",
            quality: "Quality Review uses modest scans plus stricter QA. It allows natural storytelling but avoids unsupported product details.",
            deep: "Deep Scan is slowest and uses the richest visual/variation analysis for important listings."
        };
        copywritingDepthHint.textContent = hints[copywritingDepthSelect.value] || hints.quality;
    }

    function isImagePipelineMode() {
        return wsPipelineMode.value === "listing_with_images" || wsPipelineMode.value === "images_only";
    }

    wsPipelineMode.addEventListener("change", syncPipelineModeUI);
    if (copywritingDepthSelect) {
        copywritingDepthSelect.addEventListener("change", syncCopywritingDepthHint);
    }
    syncPipelineModeUI();

    function syncTaskPromptModeUI(row) {
        const modeSelect = row.querySelector(".task-prompt-mode");
        const presetGroup = row.querySelector(".task-preset-group");
        const customGroup = row.querySelector(".task-custom-prompt-group");
        const hint = row.querySelector(".task-preset-hint");
        const isPreset = modeSelect.value === "preset";

        presetGroup.hidden = !isPreset;
        customGroup.hidden = isPreset;
        if (hint) {
            hint.textContent = getPromptPresetDescription(row.querySelector(".task-prompt-preset").value);
        }
    }

    function syncTaskModelUI(row) {
        const modelSelect = row.querySelector(".task-model-key");
        const thinkingSelect = row.querySelector(".task-thinking-level");
        const hint = row.querySelector(".task-model-hint");
        if (!modelSelect || !thinkingSelect) return;

        const inheritedSettings = getImageSettings();
        const resolvedModelKey = modelSelect.value || inheritedSettings.model_key;
        const model = getImageModelOption(resolvedModelKey);
        const supportsThinking = supportsModelThinking(resolvedModelKey);

        thinkingSelect.disabled = !supportsThinking;
        thinkingSelect.closest(".input-group")?.classList.toggle("is-muted", !supportsThinking);

        if (supportsThinking && !thinkingSelect.value) {
            thinkingSelect.value = "inherit";
        }

        if (hint && model) {
            const source = modelSelect.value ? model.label : `Global: ${model.label}`;
            const thinkingNote = supportsThinking ? "Thinking available." : "No thinking mode.";
            hint.textContent = `${source}. ${model.recommended_for || model.description || ""} ${thinkingNote}`.trim();
        }
    }

    function syncAllTaskModelUI() {
        if (!imageTasksList) return;
        imageTasksList.querySelectorAll(".task-row").forEach(syncTaskModelUI);
    }

    function createTaskRow(type = "batch", targetVal = "", taskConfig = {}) {
        const row = document.createElement("div");
        row.className = "task-row";
        row.dataset.taskType = type;
        const titleText = type === "individual" ? "Individual Task" : "Batch Task";
        const config = typeof taskConfig === "string" ? { prompt: taskConfig } : (taskConfig || {});
        const promptVal = config.prompt || "";
        const promptMode = config.prompt_mode || (promptVal ? "custom" : "preset");
        const promptPreset = config.prompt_preset || defaultPromptPreset;
        const taskModelKey = config.model_key || "";
        const taskThinkingLevel = config.thinking_level || "inherit";
        
        let targetOptions = "";
        if (type === "individual") {
            targetOptions = `
                <option value="selected_reference">Selected Reference Image</option>
                <option value="first_variation">1st Variation Image</option>
                <option value="first_main">1st Main Image</option>
                <option value="first_description">1st Description Image</option>
            `;
        } else {
            targetOptions = `
                <option value="variation_images">Variations</option>
                <option value="main_images">Main Images</option>
                <option value="description_images">Description Images</option>
            `;
        }
        
        row.innerHTML = `
            <div class="task-row-header">
                <span class="task-type-badge">${titleText}</span>
                <button type="button" class="remove-task-btn" title="Remove Task" aria-label="Remove task">Remove</button>
            </div>
            <div class="input-group">
                <label class="field-label">${type === "individual" ? "Target Reference" : "Target Folder"}</label>
                <select class="select-input task-target">
                    ${targetOptions}
                </select>
            </div>
            <div class="input-group">
                <label class="field-label">Prompt Type</label>
                <select class="select-input task-prompt-mode">
                    <option value="preset">Preset</option>
                    <option value="custom">Custom</option>
                </select>
            </div>
            <div class="task-model-grid">
                <div class="input-group">
                    <label class="field-label">Task Model</label>
                    <select class="select-input task-model-key">
                        ${buildModelOptions(taskModelKey, true)}
                    </select>
                </div>
                <div class="input-group">
                    <label class="field-label">Thinking</label>
                    <select class="select-input task-thinking-level">
                        ${buildThinkingLevelOptions(taskThinkingLevel, true)}
                    </select>
                </div>
                <small class="task-model-hint"></small>
            </div>
            <div class="input-group task-preset-group">
                <label class="field-label">Image Preset</label>
                <select class="select-input task-prompt-preset">
                    ${buildPromptPresetOptions(promptPreset)}
                </select>
                <small class="task-preset-hint"></small>
            </div>
            <div class="input-group">
                <label class="field-label task-custom-prompt-group-label">Custom Prompt</label>
                <textarea class="text-input task-prompt" rows="3" placeholder="Describe the edit, staging, model, scene, lighting, or background..."></textarea>
            </div>
        `;
        const customGroup = row.querySelector(".task-prompt").closest(".input-group");
        customGroup.classList.add("task-custom-prompt-group");
        row.querySelector(".task-prompt").value = promptVal || "";
        row.querySelector(".task-prompt-mode").value = promptMode === "preset" ? "preset" : "custom";
        row.querySelector(".task-model-key").value = taskModelKey;
        row.querySelector(".task-thinking-level").value = taskThinkingLevel;
        
        if (targetVal) {
            const select = row.querySelector(".task-target");
            const opt = select.querySelector(`option[value="${targetVal}"]`);
            if (opt) select.value = targetVal;
        }

        row.querySelector(".task-prompt-mode").addEventListener("change", () => {
            syncTaskPromptModeUI(row);
        });
        row.querySelector(".task-prompt-preset").addEventListener("change", () => {
            syncTaskPromptModeUI(row);
        });
        row.querySelector(".task-model-key").addEventListener("change", () => {
            syncTaskModelUI(row);
        });
        
        row.querySelector(".remove-task-btn").addEventListener("click", (e) => {
            e.preventDefault();
            row.remove();
        });

        syncTaskPromptModeUI(row);
        syncTaskModelUI(row);
        
        return row;
    }

    if (btnAddBatchTask) {
        btnAddBatchTask.addEventListener("click", (e) => {
            e.preventDefault();
            if (imageTasksList) imageTasksList.appendChild(createTaskRow("batch"));
        });
    }
    if (btnAddIndividualTask) {
        btnAddIndividualTask.addEventListener("click", (e) => {
            e.preventDefault();
            if (imageTasksList) imageTasksList.appendChild(createTaskRow("individual"));
        });
    }

    function getImageTasks() {
        if (!imageTasksList) return [];
        const tasks = [];
        imageTasksList.querySelectorAll(".task-row").forEach(row => {
            const promptMode = row.querySelector(".task-prompt-mode").value;
            const promptPreset = row.querySelector(".task-prompt-preset").value;
            const prompt = row.querySelector(".task-prompt").value.trim();
            if (promptMode === "preset" || prompt) {
                tasks.push({
                    task_type: row.dataset.taskType,
                    target: row.querySelector(".task-target").value,
                    prompt_mode: promptMode,
                    prompt_preset: promptPreset,
                    prompt: prompt,
                    model_key: row.querySelector(".task-model-key")?.value || "",
                    thinking_level: row.querySelector(".task-thinking-level")?.value || "inherit"
                });
            }
        });
        return tasks;
    }

    // --- QUEUE MANAGEMENT ---
    btnRefreshQueue.addEventListener("click", loadQueue);

    function loadQueue() {
        return apiFetch("/api/queue")
            .then(r => r.json())
            .then(data => {
                queueData = data.queue || [];
                if (selectedQueueItem) {
                    const updatedSelected = queueData.find(item => item.slug === selectedQueueItem.slug);
                    if (updatedSelected) {
                        selectedQueueItem = updatedSelected;
                        renderReferencePicker(selectedQueueItem);
                    }
                }
                renderQueue();
            });
    }

    function renderQueue() {
        queueList.innerHTML = "";
        
        if (chkQueueSelectAll) chkQueueSelectAll.checked = false;

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

            // Wrapper for inline reference/listing panels
            const wrapper = document.createElement("div");
            wrapper.className = `queue-item-wrapper ${isDone ? "completed" : "active"}`;

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
                thumb.src = withTokenQuery(item.thumbnail_path);
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
            if (getPrimaryReferencePath(item)) {
                addQueueReferenceBadge(meta);
            }

            info.appendChild(title);
            info.appendChild(meta);

            // Actions
            const actions = document.createElement("div");
            actions.className = "queue-actions";
            const referencePanel = buildQueueReferencePanel(item, (updatedItem) => {
                item.primary_reference_image = updatedItem.primary_reference_image;
                addQueueReferenceBadge(meta);
                if (!referencePanel.classList.contains("open")) {
                    btnReference.textContent = "Change Ref";
                }
            });
            const btnReference = document.createElement("button");
            btnReference.className = "secondary-btn";
            btnReference.textContent = getPrimaryReferencePath(item) ? "Change Ref" : "Set Ref";
            btnReference.addEventListener("click", () => {
                const isOpen = referencePanel.classList.contains("open");
                referencePanel.classList.toggle("open", !isOpen);
                btnReference.textContent = isOpen
                    ? (getPrimaryReferencePath(item) ? "Change Ref" : "Set Ref")
                    : "Close Ref";
            });

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
                actions.appendChild(btnReference);

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
                wrapper.appendChild(referencePanel);
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

                actions.appendChild(btnReference);
                actions.appendChild(btnOpen);
                actions.appendChild(btnDelete);

                row.appendChild(chk);
                row.appendChild(thumb);
                row.appendChild(info);
                row.appendChild(actions);

                wrapper.appendChild(row);
                wrapper.appendChild(referencePanel);
                queueList.appendChild(wrapper);
            }
        });

        updateActionBtnState();
    }

    function buildDeleteButton(item) {
        const btnDelete = document.createElement("button");
        btnDelete.className = "danger-btn";
        btnDelete.textContent = "Delete";
        btnDelete.addEventListener("click", async () => {
            const confirmed = await openModal({
                title: "Delete Queue Item",
                message: `Delete "${item.title}" and its downloaded assets from the queue? This cannot be undone.`,
                confirmText: "Delete Item",
                danger: true
            });
            if (!confirmed) return;

            btnDelete.disabled = true;
            btnDelete.textContent = "Deleting...";
            apiFetch("/api/delete-queue-item", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ slug: item.slug })
            })
            .then(r => r.json())
            .then(async res => {
                if (res.status === "success") {
                    loadQueue();
                } else {
                    await showInfoModal("Delete Failed", res.detail || "Failed to delete item.");
                    btnDelete.disabled = false;
                    btnDelete.textContent = "Delete";
                }
            })
            .catch(async err => {
                await showInfoModal("Delete Failed", err.message);
                btnDelete.disabled = false;
                btnDelete.textContent = "Delete";
            });
        });
        return btnDelete;
    }

    function getProductImageSrc(slug, imagePath, bustCache = false) {
        const imageUrl = withTokenQuery(`/api/product-image/${encodeURIComponent(slug)}/${encodeURIComponent(imagePath)}`);
        if (!bustCache) return imageUrl;
        const separator = imageUrl.includes("?") ? "&" : "?";
        return `${imageUrl}${separator}t=${Date.now()}`;
    }

    function getImagePath(imageEntry) {
        if (!imageEntry) return "";
        if (typeof imageEntry === "object") {
            return imageEntry.local_path || imageEntry.path || imageEntry.filename || "";
        }
        return imageEntry;
    }

    function getGeneratedSourceLabel(imageEntry) {
        if (!imageEntry || typeof imageEntry !== "object") return "";
        const sourceLabel = imageEntry.source_label || "";
        const sourceFolder = imageEntry.source_folder || "";
        const sourceIndex = Number.isFinite(Number(imageEntry.source_index))
            ? Number(imageEntry.source_index) + 1
            : "";
        if (sourceLabel) return `From ${sourceLabel}`;
        if (sourceFolder && sourceIndex) return `From ${sourceFolder.replace("_", " ")} ${sourceIndex}`;
        if (imageEntry.source_image) return `From ${imageEntry.source_image}`;
        return "";
    }

    function renderPreviewGeneratedImages(container, images, slug, item = null) {
        container.innerHTML = "";

        const generatedEntries = (Array.isArray(images) ? images : [])
            .map(entry => ({ entry, imagePath: getImagePath(entry) }))
            .filter(item => item.imagePath);

        if (generatedEntries.length === 0) {
            container.innerHTML = `<div class="preview-generated-empty">No generated images yet.</div>`;
            return;
        }

        generatedEntries.forEach(({ entry, imagePath }, index) => {
            const sourceLabel = getGeneratedSourceLabel(entry);
            const src = getProductImageSrc(slug, imagePath, true);
            const busy = isImageTweaking(slug, imagePath);
            const tile = document.createElement("div");
            tile.className = `preview-generated-tile ${busy ? "is-tweaking" : ""}`;
            tile.title = `Generated image ${index + 1}`;

            const img = document.createElement("img");
            img.src = src;
            img.alt = `Generated image ${index + 1}`;
            img.loading = "lazy";
            img.addEventListener("click", () => {
                window.open(src, "_blank", "noopener,noreferrer");
            });

            const badge = document.createElement("span");
            badge.className = "preview-generated-badge";
            badge.textContent = `${index + 1}`;

            const tweakBtn = document.createElement("button");
            tweakBtn.type = "button";
            tweakBtn.className = "generated-tweak-btn";
            tweakBtn.textContent = busy ? "Tweaking..." : "Tweak";
            tweakBtn.disabled = busy;
            tweakBtn.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                if (busy) return;
                const product = item || queueData.find(q => q.slug === slug);
                openGeneratedImageTweakModal(product, entry, container);
            });

            tile.appendChild(img);
            tile.appendChild(badge);
            tile.appendChild(tweakBtn);
            if (busy) {
                const status = document.createElement("span");
                status.className = "generated-tweak-status";
                status.textContent = "Tweaking image...";
                tile.appendChild(status);
            }
            if (sourceLabel) {
                const source = document.createElement("span");
                source.className = "preview-generated-source";
                source.textContent = sourceLabel;
                tile.appendChild(source);
            }
            container.appendChild(tile);
        });
    }

    function getPrimaryReferencePath(item) {
        return getImagePath(item?.primary_reference_image);
    }

    function collectReferenceCandidates(item) {
        if (!item) return [];

        const candidates = [];
        const addImages = (images, source, sourceLabel) => {
            (images || []).forEach((entry, index) => {
                const localPath = getImagePath(entry);
                if (!localPath) return;
                const entryLabel = typeof entry === "object"
                    ? (entry.alt || entry.title || `${sourceLabel} ${index + 1}`)
                    : `${sourceLabel} ${index + 1}`;
                candidates.push({
                    local_path: localPath,
                    source,
                    source_label: sourceLabel,
                    label: entryLabel,
                    index: index + 1,
                });
            });
        };

        addImages(item.main_images, "main_images", "Main");
        addImages(item.variation_images, "variation_images", "Variation");
        addImages(item.description_images, "description_images", "Description");
        return candidates;
    }

    function renderReferenceImageGrid({ item, grid, status, emptyText = "No product selected.", noImagesText = "No downloaded product images found.", onSaved = null }) {
        if (!grid || !status) return;

        grid.innerHTML = "";
        if (!item) {
            status.textContent = "Select a product to choose the source image for AI edits.";
            grid.innerHTML = `<div class="reference-empty">${emptyText}</div>`;
            return;
        }

        const candidates = collectReferenceCandidates(item);
        const selectedPath = getPrimaryReferencePath(item);

        if (selectedPath) {
            status.textContent = "Manual reference selected. Image generation can use this as the source.";
        } else {
            status.textContent = "Choose the clearest product image before running AI image edits.";
        }

        if (candidates.length === 0) {
            grid.innerHTML = `<div class="reference-empty">${noImagesText}</div>`;
            return;
        }

        candidates.forEach(candidate => {
            const isSelected = candidate.local_path === selectedPath;
            const button = document.createElement("button");
            button.type = "button";
            button.className = `reference-image-card${isSelected ? " selected" : ""}`;
            button.title = `Use ${candidate.label} as the AI reference`;

            const sourcePill = document.createElement("span");
            sourcePill.className = "reference-source-pill";
            sourcePill.textContent = `${candidate.source_label} ${candidate.index}`;

            const img = document.createElement("img");
            img.src = getProductImageSrc(item.slug, candidate.local_path);
            img.alt = candidate.label;
            img.loading = "lazy";

            const label = document.createElement("span");
            label.className = "reference-card-label";
            label.textContent = candidate.label;

            const selectedBadge = document.createElement("span");
            selectedBadge.className = "reference-selected-badge";
            selectedBadge.textContent = "Selected";

            button.appendChild(sourcePill);
            button.appendChild(img);
            button.appendChild(label);
            button.appendChild(selectedBadge);

            button.addEventListener("click", () => saveReferenceImage(item, candidate, button, {
                statusElement: status,
                onSaved,
            }));
            grid.appendChild(button);
        });
    }

    function renderReferencePicker(item) {
        renderReferenceImageGrid({
            item,
            grid: referenceImageGrid,
            status: referenceStatus,
            emptyText: "No product selected.",
            noImagesText: "No downloaded product images found.",
        });
    }

    async function saveReferenceImage(item, candidate, button, options = {}) {
        if (!item?.slug || !candidate?.local_path) return;

        const statusElement = options.statusElement || referenceStatus;
        const previousText = statusElement ? statusElement.textContent : "";
        if (statusElement) {
            statusElement.textContent = "Saving selected reference image...";
        }
        if (button) button.disabled = true;

        try {
            const res = await apiFetch("/api/set-reference-image", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    product_slug: item.slug,
                    local_path: candidate.local_path,
                    source: candidate.source,
                }),
            });

            const data = await res.json();
            if (!res.ok) {
                throw new Error(data.detail || "Failed to save reference image.");
            }

            item.primary_reference_image = data.primary_reference_image;
            const queueItem = queueData.find(q => q.slug === item.slug);
            if (queueItem) {
                queueItem.primary_reference_image = data.primary_reference_image;
            }
            if (selectedQueueItem?.slug === item.slug) {
                selectedQueueItem = queueItem || item;
                renderReferencePicker(selectedQueueItem);
            }
            if (typeof options.onSaved === "function") {
                options.onSaved(queueItem || item);
            }
            logConsole("success", `Reference image selected for ${item.slug}.`);
        } catch (err) {
            if (statusElement) {
                statusElement.textContent = previousText;
            }
            await showInfoModal("Reference Save Failed", err.message);
        } finally {
            if (button) button.disabled = false;
        }
    }

    function addQueueReferenceBadge(meta) {
        if (!meta || meta.querySelector(".queue-reference-badge")) return;
        const referenceLabel = document.createElement("span");
        referenceLabel.className = "queue-reference-badge";
        referenceLabel.textContent = "reference set";
        meta.appendChild(referenceLabel);
    }

    function buildQueueReferencePanel(item, onSaved = null) {
        const panel = document.createElement("div");
        panel.className = "queue-reference-panel";

        const header = document.createElement("div");
        header.className = "queue-reference-header";

        const titleWrap = document.createElement("div");
        const title = document.createElement("div");
        title.className = "preview-label";
        title.textContent = "Reference Image";

        const status = document.createElement("p");
        status.className = "reference-status";

        titleWrap.appendChild(title);
        titleWrap.appendChild(status);
        header.appendChild(titleWrap);

        const grid = document.createElement("div");
        grid.className = "reference-image-grid queue-reference-grid";

        panel.appendChild(header);
        panel.appendChild(grid);

        const renderPanelGrid = (nextItem = item) => {
            renderReferenceImageGrid({
                item: nextItem,
                grid,
                status,
                emptyText: "No product selected.",
                noImagesText: "Images are still downloading or unavailable.",
                onSaved: (updatedItem) => {
                    renderPanelGrid(updatedItem);
                    if (typeof onSaved === "function") {
                        onSaved(updatedItem);
                    }
                },
            });
        };

        renderPanelGrid(item);
        return panel;
    }

    function asTextList(value) {
        if (Array.isArray(value)) {
            return value.map(item => String(item || "").trim()).filter(Boolean);
        }
        if (typeof value === "string") {
            return value.split(/\n|,/).map(item => item.trim()).filter(Boolean);
        }
        return [];
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function buildListingPreviewPanel(item) {
        const listing = item.etsy_listing || {};
        const panel = document.createElement("div");
        panel.className = "listing-preview-panel";
        const generatedImages = Array.isArray(item.generated_images) ? item.generated_images : [];
        const generatedCount = generatedImages.map(getImagePath).filter(Boolean).length;

        const tags = listing.tags || [];
        const tagsHtml = tags.length > 0
            ? `<div class="preview-tags">${tags.map(t => `<span class="preview-tag">${t}</span>`).join("")}</div>`
            : `<span class="preview-value" style="color:var(--neutral-grey)">—</span>`;

        panel.innerHTML = `
            <div class="preview-action-row">
                <button type="button" class="secondary-btn preview-tweak-btn" data-action="tweak-copy">Tweak Copy</button>
            </div>
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

            <div class="preview-field preview-generated-field">
                <div class="preview-field-header">
                    <span class="preview-label">Generated Images</span>
                    <span class="preview-image-count">${generatedCount} image${generatedCount === 1 ? "" : "s"}</span>
                </div>
                <div class="preview-generated-images" data-generated-images></div>
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

        renderPreviewGeneratedImages(
            panel.querySelector("[data-generated-images]"),
            generatedImages,
            item.slug,
            item
        );

        const tweakBtn = panel.querySelector("[data-action='tweak-copy']");
        if (tweakBtn) {
            tweakBtn.addEventListener("click", (event) => {
                event.stopPropagation();
                selectForWorkspace(item);
                openTweakCopyModal();
            });
        }

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
        const allChks = document.querySelectorAll(".queue-chk");
        const checked = document.querySelectorAll(".queue-chk:checked");
        
        if (chkQueueSelectAll && allChks.length > 0) {
            chkQueueSelectAll.checked = (allChks.length === checked.length);
        }

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

        apiFetch("/api/export-zip", {
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
        }).catch(async err => {
            await showInfoModal("Export Failed", err.message);
            btnExportSelected.textContent = "Export ZIP";
            btnExportSelected.disabled = false;
        });
    });

    async function requestPipelineCancel(slug) {
        if (!slug) return;
        if (isBulkRunning) {
            bulkCancelRequested = true;
        }
        if (btnCancelPipeline) {
            btnCancelPipeline.disabled = true;
            btnCancelPipeline.textContent = "Stopping...";
        }

        const res = await apiFetch("/api/cancel-pipeline", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ product_slug: slug })
        });
        const payload = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(payload.detail || payload.message || "Cancel request failed");
        }
        logConsole("system", payload.message || `Cancel requested for ${slug}.`);
        notifyPipeline({
            title: payload.status === "idle" ? "No Active Pipeline" : "Stopping Pipeline",
            message: payload.message || "Waiting for the current API call to finish safely.",
            type: payload.status === "idle" ? "info" : "info"
        });
    }

    if (btnCancelPipeline) {
        btnCancelPipeline.addEventListener("click", async () => {
            const slug = currentPipelineSlug || wsProductSlug.value;
            if (!slug) return;
            const confirmed = await openModal({
                title: "Stop Pipeline",
                message: "Stop this pipeline after the current API call finishes? Partial outputs that already saved will stay in the product folder.",
                confirmText: "Stop Pipeline",
                danger: true
            });
            if (!confirmed) return;
            try {
                await requestPipelineCancel(slug);
            } catch (err) {
                logConsole("error", err.message);
                notifyPipeline({
                    title: "Cancel Failed",
                    message: err.message,
                    type: "error"
                });
                if (btnCancelPipeline && pipelineRunning) {
                    btnCancelPipeline.disabled = false;
                    btnCancelPipeline.textContent = "Stop Pipeline";
                }
            }
        });
    }

    // --- BULK RUN LISTINGS ---
    btnRunSelected.addEventListener("click", async () => {
        const checked = Array.from(document.querySelectorAll(".queue-chk:checked"))
            .filter(c => c.dataset.status === "queued" || c.dataset.status === "done");

        if (checked.length === 0) return;
        requestBrowserNotificationPermission();

        isBulkRunning = true;
        bulkCancelRequested = false;
        let processedCount = 0;
        btnRunSelected.disabled = true;
        btnRunSelected.textContent = `Running 0/${checked.length}...`;

        // Switch to Workspace tab so the user can see console progress
        navBtns[1].click();

        for (let i = 0; i < checked.length; i++) {
            if (bulkCancelRequested) break;
            const slug = checked[i].dataset.slug;
            currentPipelineSlug = slug;
            setActivityDot(true, slug);
            btnRunSelected.textContent = `Running ${i + 1}/${checked.length}...`;
            logConsole("system", `Bulk run: Starting ${slug} (${i + 1}/${checked.length})`);

            try {
                await apiFetch("/api/run-pipeline", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        product_slug: slug,
                        mode: wsPipelineMode.value,
                        image_tasks: isImagePipelineMode() ? getImageTasks() : [],
                        image_settings: getImageSettings(),
                        copywriting_options: getCopywritingOptions()
                    })
                });
                // Wait for the SSE "done" or "error" event for this slug before continuing
                await waitForPipelineCompletion(slug);
                processedCount++;
            } catch (err) {
                logConsole("error", `Bulk run error on ${slug}: ${err.message}`);
                notifyPipeline({
                    title: err.cancelled ? "Bulk Run Stopped" : "Bulk Run Paused",
                    message: err.message,
                    type: err.cancelled ? "info" : "error"
                });
                break;
            }
        }

        const stopped = bulkCancelRequested;
        logConsole(stopped ? "system" : "success", `${stopped ? "Bulk run stopped" : "Bulk run complete"}. Processed ${processedCount}/${checked.length} listing(s).`);
        notifyPipeline({
            title: stopped ? "Bulk Run Stopped" : "Bulk Run Finished",
            message: `Processed ${processedCount}/${checked.length} listing(s).`,
            type: stopped ? "info" : "success"
        });
        isBulkRunning = false;
        bulkCancelRequested = false;
        setActivityDot(false);
        btnRunSelected.textContent = "Run Listings";
        loadQueue();
    });

    /**
     * Returns a Promise that resolves when the SSE stream emits a "done" or "error"
     * event. Uses polling so bulk runs stay strictly sequential.
     * Rejects after max 45 minutes per item as a safety net instead of starting overlap.
     */
    function waitForPipelineCompletion(slug) {
        return new Promise((resolve, reject) => {
            const TIMEOUT_MS = 45 * 60 * 1000;
            let resolved = false;

            const timer = setTimeout(() => {
                if (!resolved) {
                    resolved = true;
                    clearInterval(poll);
                    reject(new Error(`Timed out waiting for ${slug} after 45 minutes.`));
                }
            }, TIMEOUT_MS);

            // Poll metadata until status changes from "processing"
            const poll = setInterval(async () => {
                try {
                    const res = await apiFetch("/api/queue");
                    const data = await res.json();
                    const item = (data.queue || []).find(q => q.slug === slug);
                    if (item && !["processing", "queued", "cancelling"].includes(item.status)) {
                        clearInterval(poll);
                        clearTimeout(timer);
                        if (!resolved) {
                            resolved = true;
                            if (item.status === "failed") {
                                reject(new Error(item.error || `${slug} failed.`));
                            } else if (item.status === "cancelled") {
                                const err = new Error(`${slug} was cancelled.`);
                                err.cancelled = true;
                                reject(err);
                            } else {
                                resolve();
                            }
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
        renderReferencePicker(item);

        // Switch tab to Workspace
        navBtns[1].click();

        // Load data if already processed
        if (item.status === "done" && item.etsy_listing) {
            activeListing = item.etsy_listing;
            activeListing.slug = item.slug;
            populateWorkspace();
            populateVariationSpecs(item);

            if (item.generated_images) {
                renderGeneratedImages(item.generated_images, item.slug);
            }
        } else if (item.status === "done" && item.generated_images) {
            activeListing = null;
            workspace.classList.add("disabled");
            workspace.classList.remove("has-unsaved-tweak");
            etsyTitle.value = "";
            etsyPrice.value = "";
            etsyDesc.value = "";
            tagsContainer.innerHTML = "";
            btnSave.disabled = true;
            btnSave.textContent = "Save Updates";
            if (btnTweakCopy) btnTweakCopy.disabled = true;
            variationsSpecsWrapper.style.display = "none";
            variationsSpecsList.innerHTML = "";
            renderGeneratedImages(item.generated_images, item.slug);
        } else {
            // Reset workspace
            activeListing = null;
            workspace.classList.add("disabled");
            workspace.classList.remove("has-unsaved-tweak");
            etsyTitle.value = "";
            etsyPrice.value = "";
            etsyDesc.value = "";
            tagsContainer.innerHTML = "";
            imagesGrid.innerHTML = `<div class="image-placeholder">Run pipeline to generate images.</div>`;
            btnSave.disabled = true;
            btnSave.textContent = "Save Updates";
            if (btnTweakCopy) btnTweakCopy.disabled = true;
            variationsSpecsWrapper.style.display = "none";
            variationsSpecsList.innerHTML = "";
        }
    }

    btnGenerate.addEventListener("click", () => {
        const slug = wsProductSlug.value;
        if (!slug) return;
        requestBrowserNotificationPermission();

        logConsole("system", `Triggering pipeline for ${slug}...`);
        btnGenerate.disabled = true;
        currentPipelineSlug = slug;
        setActivityDot(true, slug);

        apiFetch("/api/run-pipeline", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                product_slug: slug,
                mode: wsPipelineMode.value,
                image_tasks: isImagePipelineMode() ? getImageTasks() : [],
                image_settings: getImageSettings(),
                copywriting_options: getCopywritingOptions()
            })
        }).then(async res => {
            if (!res.ok) {
                const payload = await res.json().catch(() => ({}));
                throw new Error(payload.detail || payload.message || "Pipeline start failed");
            }
        }).catch(err => {
            logConsole("error", err.message);
            notifyPipeline({
                title: "Pipeline Start Failed",
                message: err.message,
                type: "error"
            });
            setActivityDot(false);
        });
    });

    // --- EVENT STREAM ---
    function connectStatusStream() {
        if (eventSource) return;
        eventSource = new EventSource(withTokenQuery("/api/status-stream"));

        eventSource.onopen = () => logConsole("system", "Connected to pipeline events.");

        eventSource.onmessage = (e) => {
            const data = JSON.parse(e.data);
            if (data.status === "progress") {
                logConsole("progress", data.message);
                setActivityDot(true, data.slug || data.output_dir_name || currentPipelineSlug);
            } else if (data.status === "error") {
                logConsole("error", data.message);
                notifyPipeline({
                    title: data.title || "Pipeline Failed",
                    message: data.message || "A pipeline task failed.",
                    type: "error"
                });
                btnGenerate.disabled = false;
                setActivityDot(false);
            } else if (data.status === "cancelled") {
                logConsole("system", data.message || "Pipeline cancelled.");
                notifyPipeline({
                    title: data.title || "Pipeline Cancelled",
                    message: data.message || "The pipeline was stopped.",
                    type: "info"
                });
                btnGenerate.disabled = false;
                setActivityDot(false);
                loadQueue();
            } else if (data.status === "done") {
                logConsole("success", data.message);
                notifyPipeline({
                    title: data.title || "Pipeline Finished",
                    message: data.message || "A pipeline task finished.",
                    type: "success"
                });
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
                if (data.generated_images) {
                    renderGeneratedImages(data.generated_images, data.output_dir_name);
                }
            } else if (data.status === "notification") {
                notifyPipeline({
                    title: data.title || "Pipeline Update",
                    message: data.message || "",
                    type: data.level || "info",
                    browser: data.browser !== false
                });
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
        workspace.classList.remove("has-unsaved-tweak");
        btnSave.disabled = false;
        btnSave.textContent = "Save Updates";
        if (btnTweakCopy) btnTweakCopy.disabled = false;

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
            
            const imgSrc = getProductImageSrc(item.slug, localPath);
            
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

    function renderGeneratedImages(images, slug) {
        imagesGrid.innerHTML = "";
        if (!images || images.length === 0) {
            imagesGrid.innerHTML = `<div class="image-placeholder">No images generated.</div>`;
            return;
        }

        images.forEach((imgFile) => {
            const imagePath = getImagePath(imgFile);
            if (!imagePath) return;
            const sourceLabel = getGeneratedSourceLabel(imgFile);
            const busy = isImageTweaking(slug, imagePath);
            const item = selectedQueueItem?.slug === slug
                ? selectedQueueItem
                : (queueData.find(q => q.slug === slug) || {
                    slug,
                    generated_images: images,
                    main_images: [],
                    variation_images: [],
                    description_images: []
                });

            const card = document.createElement("div");
            card.className = `prompt-card ${busy ? "is-tweaking" : ""}`;

            const imgWrap = document.createElement("div");
            imgWrap.className = "prompt-card-img-wrapper";
            const img = document.createElement("img");
            img.src = getProductImageSrc(slug, imagePath, true);
            img.style.display = "block";
            
            imgWrap.appendChild(img);
            const tweakBtn = document.createElement("button");
            tweakBtn.type = "button";
            tweakBtn.className = "generated-tweak-btn prompt-card-tweak-btn";
            tweakBtn.textContent = busy ? "Tweaking..." : "Tweak";
            tweakBtn.disabled = busy;
            tweakBtn.addEventListener("click", () => {
                if (busy) return;
                openGeneratedImageTweakModal(item, imgFile);
            });
            imgWrap.appendChild(tweakBtn);
            if (busy) {
                const status = document.createElement("span");
                status.className = "generated-tweak-status";
                status.textContent = "Tweaking image...";
                imgWrap.appendChild(status);
            }
            card.appendChild(imgWrap);

            if (sourceLabel) {
                const content = document.createElement("div");
                content.className = "prompt-card-content";
                const label = document.createElement("div");
                label.className = "generated-source-label";
                label.textContent = sourceLabel;
                content.appendChild(label);
                card.appendChild(content);
            }
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

        apiFetch("/api/save-listing", {
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
        }).then(r => r.json()).then(async res => {
            btnSave.textContent = "Save Updates";
            btnSave.disabled = false;
            if (res.status === "success") {
                workspace.classList.remove("has-unsaved-tweak");
                btnSave.textContent = "Save Updates";
                await showInfoModal("Listing Saved", "Saved updates to metadata.json.");
                if (selectedQueueItem) {
                    selectedQueueItem.etsy_listing = {
                        ...(selectedQueueItem.etsy_listing || {}),
                        ...activeListing,
                        title: etsyTitle.value,
                        category: etsyCategory ? etsyCategory.value : "",
                        suggested_price: etsyPrice.value,
                        description: etsyDesc.value
                    };
                    selectedQueueItem.variation_images = updatedVars;
                }
                loadQueue();
            }
        });
    });

});
