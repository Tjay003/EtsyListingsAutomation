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

    // Filter pills
    const filterPills = document.querySelectorAll(".filter-pill");
    let activeFilter = "active"; // "active" | "completed"

    // Workspace Elements
    const wsProductTitle = document.getElementById("ws-product-title");
    const wsProductSlug = document.getElementById("ws-product-slug");
    const wsPipelineMode = document.getElementById("ws-pipeline-mode");
    const imageGenConfigContainer = document.getElementById("image-gen-config-container");
    const imageModelSelect = document.getElementById("image-model-select");
    const imageThinkingSelect = document.getElementById("image-thinking-select");
    const referencePickerContainer = document.getElementById("reference-picker-container");
    const referenceStatus = document.getElementById("reference-status");
    const referenceImageGrid = document.getElementById("reference-image-grid");
    const imageTasksList = document.getElementById("image-tasks-list");
    const btnAddTask = document.getElementById("btn-add-task");
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

    const modal = document.getElementById("app-modal");
    const modalTitle = document.getElementById("modal-title");
    const modalMessage = document.getElementById("modal-message");
    const modalInputWrap = document.getElementById("modal-input-wrap");
    const modalInputLabel = document.getElementById("modal-input-label");
    const modalInput = document.getElementById("modal-input");
    const modalClose = document.getElementById("modal-close");
    const modalCancel = document.getElementById("modal-cancel");
    const modalConfirm = document.getElementById("modal-confirm");

    function openModal({ title, message, confirmText = "Confirm", cancelText = "Cancel", danger = false, input = null, hideCancel = false }) {
        return new Promise(resolve => {
            let resolved = false;

            const cleanup = (value) => {
                if (resolved) return;
                resolved = true;
                modal.hidden = true;
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
            const onCancel = () => cleanup(input ? null : false);
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
            modalCancel.hidden = hideCancel;

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

    // --- INITIALIZATION ---
    loadSettings();
    loadPresets();
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
            presetCustomPromptRules.value = "You are an expert e-commerce copywriter and Etsy SEO strategist specializing in premium boutique branding. Your task is to transform raw, clunky supplier specifications from AliExpress/manufacturers into a high-end, high-converting Etsy listing asset.\n--- CRITICAL COMPLIANCE RULES ---\n1. ABSOLUTE PROHIBITIONS: Never mention \"China\", \"AliExpress\", \"mass production\", \"factory\", \"bulk\", \"wholesale\", or \"shipping tracking variations\". Reframe everything around a \"curated, small-batch, premium boutique model\".\n2. TITLE RESTRICTIONS: Do not keyword-stuff titles. Use clean, natural keyphrases separated by pipes (|). Put primary structural/material identifiers in the first 40 characters. Remove subjective words like \"perfect\", \"beautiful\", or \"unbelievable\".\n3. DESCRIPTION FORMATTING: Optimize for readability and scanning. Avoid large text walls. For all bulleted lists or technical attribute breakdowns, you must strictly use a literal hyphen (-) instead of bullet dots (•, *, or circle symbols). ABSOLUTELY NO MARKDOWN FORMATTING: Do not use asterisks (**) or underscores (_) to bold or italicize text, as Etsy does not support markdown. Use ALL CAPS for section headers instead. Ensure key traits like color, exact size, and materials appear clearly in the first two sentences.\n4. TITLE-TAG MATCH: Ensure the 2 or 3 most important keyword phrases in the Title exactly match 2 or 3 of the Tags.\n5. META DESCRIPTION: Make the first paragraph of the description exactly 1-2 sentences (under 160 characters), naturally weaving in the primary keywords for Google SEO.\n6. OCCASION TARGETING: If applicable, weave in 1 or 2 tags targeting gift intent (e.g., \"Gifts for Her\", \"Anniversary Gift\").";
        });
    }

    if (btnResetRules) {
        btnResetRules.addEventListener("click", () => {
            presetCustomPromptRules.value = presetCustomPromptRules.value.replace(
                "2. TITLE RESTRICTIONS: Do not keyword-stuff titles. Use clean, natural keyphrases separated by pipes (|). Put primary structural/material identifiers in the first 40 characters. Remove subjective words like \"perfect\", \"beautiful\", or \"unbelievable\".",
                "2. TITLE RESTRICTIONS: Do not keyword-stuff titles or use pipe-separated keyword chains. Write one clear, natural buyer-friendly title under 140 characters and preferably under 15 words. Put the product noun and primary structural/material identifiers in the first 50-60 characters. Remove subjective words like \"perfect\", \"beautiful\", or \"unbelievable\"."
            );
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
        return fetch("/api/image-generation-options")
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
        return fetch("/api/image-prompt-presets")
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
        fetch("/api/generation-presets")
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
            
            fetch("/api/generation-presets", {
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
            
            fetch("/api/generation-presets/delete", {
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
    }

    function isImagePipelineMode() {
        return wsPipelineMode.value === "listing_with_images" || wsPipelineMode.value === "images_only";
    }

    wsPipelineMode.addEventListener("change", syncPipelineModeUI);
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
        return fetch("/api/queue")
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
            fetch("/api/delete-queue-item", {
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
        const cacheParam = bustCache ? `?t=${Date.now()}` : "";
        return `/api/product-image/${slug}/${encodeURIComponent(imagePath)}${cacheParam}`;
    }

    function getImagePath(imageEntry) {
        if (!imageEntry) return "";
        if (typeof imageEntry === "object") {
            return imageEntry.local_path || imageEntry.path || imageEntry.filename || "";
        }
        return imageEntry;
    }

    function renderPreviewGeneratedImages(container, images, slug) {
        container.innerHTML = "";

        const generatedImages = (Array.isArray(images) ? images : [])
            .map(getImagePath)
            .filter(Boolean);

        if (generatedImages.length === 0) {
            container.innerHTML = `<div class="preview-generated-empty">No generated images yet.</div>`;
            return;
        }

        generatedImages.forEach((imagePath, index) => {
            const src = getProductImageSrc(slug, imagePath, true);
            const link = document.createElement("a");
            link.className = "preview-generated-tile";
            link.href = src;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.title = `Open generated image ${index + 1}`;

            const img = document.createElement("img");
            img.src = src;
            img.alt = `Generated image ${index + 1}`;
            img.loading = "lazy";

            const badge = document.createElement("span");
            badge.className = "preview-generated-badge";
            badge.textContent = `${index + 1}`;

            link.appendChild(img);
            link.appendChild(badge);
            container.appendChild(link);
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
            const res = await fetch("/api/set-reference-image", {
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

    function getSeoCopyText(listing, copyType) {
        const altText = asTextList(listing.image_alt_text);
        const notes = asTextList(listing.seo_qa_notes);
        if (copyType === "google-title") return listing.google_meta_title || "";
        if (copyType === "google-desc") return listing.google_meta_description || "";
        if (copyType === "pinterest-title") return listing.pinterest_title || "";
        if (copyType === "pinterest-desc") return listing.pinterest_description || "";
        if (copyType === "alt-text") return altText.join("\n");
        if (copyType === "seo-notes") return notes.join("\n");
        return "";
    }

    function buildSeoPreviewHtml(listing) {
        const altText = asTextList(listing.image_alt_text);
        const notes = asTextList(listing.seo_qa_notes);
        const score = Number.isFinite(Number(listing.seo_quality_score))
            ? Number(listing.seo_quality_score)
            : null;

        const fields = [
            { label: "Google Title", copyType: "google-title", value: listing.google_meta_title || "" },
            { label: "Google Description", copyType: "google-desc", value: listing.google_meta_description || "" },
            { label: "Pinterest Title", copyType: "pinterest-title", value: listing.pinterest_title || "" },
            { label: "Pinterest Description", copyType: "pinterest-desc", value: listing.pinterest_description || "" },
            { label: "Image Alt Text", copyType: "alt-text", value: altText.join("\n") }
        ].filter(field => field.value);

        if (!fields.length && score === null && !notes.length) {
            return "";
        }

        const scoreHtml = score === null
            ? ""
            : `<span class="seo-score-pill">SEO ${score}/100</span>`;

        const cardsHtml = fields.map(field => `
            <div class="preview-seo-card">
                <div class="preview-field-header">
                    <span class="preview-label">${escapeHtml(field.label)}</span>
                    <button class="copy-btn" data-copy-type="${field.copyType}">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                        <span>Copy</span>
                    </button>
                </div>
                <div class="preview-seo-value">${escapeHtml(field.value)}</div>
            </div>
        `).join("");

        const notesHtml = notes.length
            ? `<div class="preview-seo-notes">
                <div class="preview-field-header">
                    <span class="preview-label">SEO QA Notes</span>
                    <button class="copy-btn" data-copy-type="seo-notes">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                        <span>Copy</span>
                    </button>
                </div>
                <ul class="preview-seo-list">${notes.map(note => `<li>${escapeHtml(note)}</li>`).join("")}</ul>
            </div>`
            : "";

        return `
            <div class="preview-field preview-seo-field">
                <div class="preview-field-header">
                    <span class="preview-label">Cross-Platform SEO</span>
                    ${scoreHtml}
                </div>
                <div class="preview-seo-grid">
                    ${cardsHtml}
                    ${notesHtml}
                </div>
            </div>
        `;
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

        const seoHtml = buildSeoPreviewHtml(listing);

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
            ${seoHtml}
        `;

        renderPreviewGeneratedImages(
            panel.querySelector("[data-generated-images]"),
            generatedImages,
            item.slug
        );

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
                } else {
                    textToCopy = getSeoCopyText(listing, copyType);
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
        }).catch(async err => {
            await showInfoModal("Export Failed", err.message);
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
                        mode: wsPipelineMode.value,
                        image_tasks: isImagePipelineMode() ? getImageTasks() : [],
                        image_settings: getImageSettings()
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
            etsyTitle.value = "";
            etsyPrice.value = "";
            etsyDesc.value = "";
            tagsContainer.innerHTML = "";
            btnSave.disabled = true;
            variationsSpecsWrapper.style.display = "none";
            variationsSpecsList.innerHTML = "";
            renderGeneratedImages(item.generated_images, item.slug);
        } else {
            // Reset workspace
            activeListing = null;
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
                image_tasks: isImagePipelineMode() ? getImageTasks() : [],
                image_settings: getImageSettings()
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
                if (data.generated_images) {
                    renderGeneratedImages(data.generated_images, data.output_dir_name);
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

    function renderGeneratedImages(images, slug) {
        imagesGrid.innerHTML = "";
        if (!images || images.length === 0) {
            imagesGrid.innerHTML = `<div class="image-placeholder">No images generated.</div>`;
            return;
        }

        images.forEach((imgFile) => {
            const imagePath = getImagePath(imgFile);
            if (!imagePath) return;

            const card = document.createElement("div");
            card.className = "prompt-card";

            const imgWrap = document.createElement("div");
            imgWrap.className = "prompt-card-img-wrapper";
            const img = document.createElement("img");
            img.src = getProductImageSrc(slug, imagePath, true);
            img.style.display = "block";
            
            imgWrap.appendChild(img);
            card.appendChild(imgWrap);
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
        }).then(r => r.json()).then(async res => {
            btnSave.textContent = "Save Updates";
            btnSave.disabled = false;
            if (res.status === "success") {
                await showInfoModal("Listing Saved", "Saved updates to metadata.json.");
                if (selectedQueueItem) {
                    selectedQueueItem.variation_images = updatedVars;
                }
                loadQueue();
            }
        });
    });

});
