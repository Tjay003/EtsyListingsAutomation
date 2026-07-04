document.addEventListener("DOMContentLoaded", () => {
    
    // Elements
    const urlInput = document.getElementById("product-url");
    const themeSelector = document.getElementById("theme-selector");
    const presetSelector = document.getElementById("preset-selector");
    const triggerKeyword = document.getElementById("trigger-keyword");
    const headedMode = document.getElementById("headed-mode");
    const btnGenerate = document.getElementById("btn-generate");
    const btnSave = document.getElementById("btn-save");
    const btnAddSlot = document.getElementById("btn-add-slot");
    const btnGenerateAllImages = document.getElementById("btn-generate-all-images");
    
    const consoleLogs = document.getElementById("console-logs");
    const workspace = document.getElementById("listing-workspace");
    
    const etsyTitle = document.getElementById("etsy-title");
    const titleCharCount = document.getElementById("title-char-count");
    const etsyPrice = document.getElementById("etsy-price");
    const tagsContainer = document.getElementById("tags-container");
    const etsyDesc = document.getElementById("etsy-desc");
    const imagesGrid = document.getElementById("images-grid");
    
    // State
    let activeListing = null;
    let activePrompts = [];
    let scrapedImages = [];
    let outputDirName = "";
    let eventSource = null;

    // Load available themes
    fetch("/api/themes")
        .then(res => res.json())
        .then(data => {
            if (data.themes) {
                themeSelector.innerHTML = "";
                data.themes.forEach(theme => {
                    const option = document.createElement("option");
                    option.value = theme;
                    option.textContent = theme.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
                    themeSelector.appendChild(option);
                });
            }
        })
        .catch(err => logConsole("error", `Failed to load themes: ${err.message}`));

    // Add log entry to custom console
    function logConsole(type, message) {
        const entry = document.createElement("div");
        entry.className = `log-entry ${type}`;
        entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
        consoleLogs.appendChild(entry);
        consoleLogs.scrollTop = consoleLogs.scrollHeight;
    }

    // Toggle forms interactive state
    function setControlsDisabled(disabled) {
        urlInput.disabled = disabled;
        themeSelector.disabled = disabled;
        presetSelector.disabled = disabled;
        triggerKeyword.disabled = disabled;
        headedMode.disabled = disabled;
        btnGenerate.disabled = disabled;
    }

    // Process event stream message
    function handleStreamMessage(event) {
        try {
            const data = JSON.parse(event.data);
            
            if (data.status === "progress") {
                logConsole("progress", data.message);
            } else if (data.status === "error") {
                logConsole("error", data.message);
                cleanupStream();
                setControlsDisabled(false);
            } else if (data.status === "done") {
                logConsole("success", data.message);
                cleanupStream();
                setControlsDisabled(false);
                
                // Set data
                activeListing = data.listing;
                activePrompts = data.prompts;
                scrapedImages = data.scraped_images || [];
                outputDirName = data.output_dir_name;
                
                populateWorkspace();
            }
        } catch (e) {
            logConsole("error", `Error parsing stream data: ${e.message}`);
        }
    }

    function cleanupStream() {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
            logConsole("system", "Event stream disconnected.");
        }
    }

    // Populate listing workspace with generated values
    function populateWorkspace() {
        if (!activeListing) return;
        
        workspace.classList.remove("disabled");
        btnSave.disabled = false;
        btnAddSlot.disabled = false;
        btnGenerateAllImages.disabled = false;
        
        // Title
        etsyTitle.value = activeListing.title || "";
        etsyTitle.removeAttribute("readonly");
        updateTitleIndicator();
        
        // Price
        etsyPrice.value = activeListing.suggested_price || "";
        etsyPrice.removeAttribute("readonly");
        
        // Description
        etsyDesc.value = activeListing.description || "";
        etsyDesc.removeAttribute("readonly");
        
        // Tags
        renderTags(activeListing.tags || []);
        
        // Render editable prompt slots
        renderPromptCards(activePrompts);
    }

    // Update Title character indicator
    function updateTitleIndicator() {
        const len = etsyTitle.value.length;
        titleCharCount.textContent = `${len} / 140`;
        if (len > 140) {
            titleCharCount.style.color = "var(--accent-red)";
            titleCharCount.style.fontWeight = "700";
        } else {
            titleCharCount.style.color = "var(--neutral-grey)";
            titleCharCount.style.fontWeight = "500";
        }
    }

    etsyTitle.addEventListener("input", updateTitleIndicator);

    // Render tag chips
    function renderTags(tags) {
        tagsContainer.innerHTML = "";
        
        // Update local object
        activeListing.tags = tags;
        
        tags.forEach((tag, idx) => {
            const chip = document.createElement("div");
            chip.className = "tag-chip";
            
            const text = document.createElement("span");
            text.textContent = tag;
            
            const removeBtn = document.createElement("span");
            removeBtn.className = "tag-remove";
            removeBtn.innerHTML = `
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <line x1="18" y1="6" x2="6" y2="18"></line>
                    <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
            `;
            
            removeBtn.addEventListener("click", () => {
                const updated = [...tags];
                updated.splice(idx, 1);
                renderTags(updated);
            });
            
            chip.appendChild(text);
            chip.appendChild(removeBtn);
            tagsContainer.appendChild(chip);
        });
    }

    // Dynamic prompt suggestions client-side
    function getPresetPromptText(theme, preset, trigger) {
        const styles = {
            "bauhaus_beige": {
                "bg": "minimalist warm cream-beige cyclorama studio, Bauhaus chrome structures, soft elegant studio lighting",
                "model_clothing": "a modern model wearing a clean white linen dress, neutral background",
                "packaging": "minimalist kraft paper box, silk ribbon, soft elegant shadow"
            },
            "cottagecore_rustic": {
                "bg": "rustic weathered wooden surface, dried wildflowers, cozy cottage morning sun filtering through window",
                "model_clothing": "a model in a floral prairie dress, vintage countryside aesthetic",
                "packaging": "vintage recycled cardboard box wrapped in twine, dried lavender"
            },
            "cyberpunk_neon": {
                "bg": "dark wet metallic panel reflecting pink and blue neon lights, moody tech-noir atmospheric haze",
                "model_clothing": "a cool model in a black techwear leather jacket, Tokyo futuristic neon street night background",
                "packaging": "futuristic matte black box with neon circuit trace accents, soft cyber-glow"
            }
        };
        const style = styles[theme] || styles["bauhaus_beige"];
        if (preset === "fashion_model") {
            return `A close-up shot of a model's hand elegantly holding the ${trigger}, ${style.bg}, clean sharp focus, 8k resolution`;
        } else {
            return `${trigger} product, professional studio product photography, centered and resting on a geometric concrete pedestal, ${style.bg}, elegant shadows, 8k resolution`;
        }
    }

    // Render list of prompt editing cards
    function renderPromptCards(prompts) {
        imagesGrid.innerHTML = "";
        
        if (!prompts || prompts.length === 0) {
            imagesGrid.innerHTML = `<div class="image-placeholder">No image slots. Click "Add Slot" to create one.</div>`;
            return;
        }
        
        prompts.forEach((item, index) => {
            createPromptCardDOM(item, index);
        });
    }

    // Create and append a prompt card DOM element
    function createPromptCardDOM(item, index) {
        const sectionName = item.name;
        const card = document.createElement("div");
        card.className = "prompt-card";
        card.dataset.index = index;
        card.dataset.section = sectionName;
        
        // Image preview wrapper
        const imgWrapper = document.createElement("div");
        imgWrapper.className = "prompt-card-img-wrapper";
        
        const imgEl = document.createElement("img");
        imgEl.style.display = "none";
        
        const emptyIcon = document.createElement("div");
        emptyIcon.className = "empty-photo-icon";
        emptyIcon.innerHTML = `
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                <circle cx="8.5" cy="8.5" r="1.5"></circle>
                <polyline points="21 15 16 10 5 21"></polyline>
            </svg>
        `;
        
        imgWrapper.appendChild(imgEl);
        imgWrapper.appendChild(emptyIcon);
        
        // Content panel
        const content = document.createElement("div");
        content.className = "prompt-card-content";
        
        const textGroup = document.createElement("div");
        textGroup.className = "input-group";
        textGroup.style.marginBottom = "0px";
        
        const labelRow = document.createElement("div");
        labelRow.className = "flex-between";
        
        const label = document.createElement("span");
        label.className = "prompt-card-label";
        label.textContent = `Slot #${index + 1} - Image Prompt`;
        
        labelRow.appendChild(label);
        textGroup.appendChild(labelRow);
        
        const textarea = document.createElement("textarea");
        textarea.className = "prompt-card-textarea";
        textarea.value = item.prompt;
        
        textGroup.appendChild(textarea);
        
        // Rows for options (Preset selection & Reference image selector)
        const row = document.createElement("div");
        row.className = "prompt-card-row";
        
        // Preset select
        const presetGroup = document.createElement("div");
        presetGroup.className = "input-group";
        presetGroup.style.marginBottom = "0px";
        
        const presetLabel = document.createElement("label");
        presetLabel.className = "field-label";
        presetLabel.textContent = "Preset Settings";
        
        const presetSelect = document.createElement("select");
        presetSelect.className = "prompt-card-select";
        presetSelect.innerHTML = `
            <option value="product_staging">Product Staging</option>
            <option value="fashion_model">AI Fashion Model</option>
        `;
        // Match current preset if custom tags exists
        if (item.prompt.includes("model") || item.prompt.includes("hand")) {
            presetSelect.value = "fashion_model";
        }
        
        presetSelect.addEventListener("change", () => {
            const currentTheme = themeSelector.value;
            const currentTrigger = triggerKeyword.value.trim() || "product";
            textarea.value = getPresetPromptText(currentTheme, presetSelect.value, currentTrigger);
        });
        
        presetGroup.appendChild(presetLabel);
        presetGroup.appendChild(presetSelect);
        
        // Reference image select
        const refGroup = document.createElement("div");
        refGroup.className = "input-group";
        refGroup.style.marginBottom = "0px";
        
        const refLabel = document.createElement("label");
        refLabel.className = "field-label";
        refLabel.textContent = "Reference Photo";
        
        const refSelect = document.createElement("select");
        refSelect.className = "prompt-card-select";
        
        // Populate options based on scrapedImages list
        if (scrapedImages.length === 0) {
            const opt = document.createElement("option");
            opt.value = "scraped_1.png";
            opt.textContent = "Photo 1 (Default)";
            refSelect.appendChild(opt);
        } else {
            scrapedImages.forEach((imgUrl, imgIdx) => {
                const opt = document.createElement("option");
                opt.value = `scraped_${imgIdx + 1}.png`;
                opt.textContent = `Scraped Photo ${imgIdx + 1}`;
                refSelect.appendChild(opt);
            });
        }
        
        refGroup.appendChild(refLabel);
        refGroup.appendChild(refSelect);
        
        row.appendChild(presetGroup);
        row.appendChild(refGroup);
        content.appendChild(row);
        
        // Actions row
        const actions = document.createElement("div");
        actions.className = "prompt-card-actions";
        
        const statusIndicator = document.createElement("span");
        statusIndicator.className = "prompt-card-label";
        statusIndicator.style.color = "var(--neutral-grey)";
        statusIndicator.textContent = "Status: Not Generated";
        
        const buttonWrapper = document.createElement("div");
        buttonWrapper.className = "button-group";
        
        const deleteBtn = document.createElement("button");
        deleteBtn.className = "secondary-btn btn-sm btn-danger";
        deleteBtn.innerHTML = `
            <span>Delete</span>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                <line x1="10" y1="11" x2="10" y2="17"></line>
                <line x1="14" y1="11" x2="14" y2="17"></line>
            </svg>
        `;
        
        deleteBtn.addEventListener("click", () => {
            card.remove();
            activePrompts.splice(index, 1);
            // Re-render to update Slot numbers
            renderPromptCards(activePrompts);
        });
        
        const runBtn = document.createElement("button");
        runBtn.className = "secondary-btn btn-sm";
        runBtn.innerHTML = `
            <span>Generate</span>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <polygon points="5 3 19 12 5 21 5 3"></polygon>
            </svg>
        `;
        
        runBtn.addEventListener("click", () => {
            generateSingleImage(textarea.value, `${sectionName}.png`, refSelect.value, imgEl, emptyIcon, runBtn, statusIndicator);
        });
        
        buttonWrapper.appendChild(deleteBtn);
        buttonWrapper.appendChild(runBtn);
        
        actions.appendChild(statusIndicator);
        actions.appendChild(buttonWrapper);
        
        content.appendChild(actions);
        
        card.appendChild(imgWrapper);
        card.appendChild(content);
        imagesGrid.appendChild(card);
    }

    // Call API to generate a single image card
    function generateSingleImage(promptText, imageName, referenceImageName, imgEl, emptyIcon, btn, statusLabel) {
        btn.disabled = true;
        const origText = btn.querySelector("span").textContent;
        btn.querySelector("span").textContent = "Generating...";
        statusLabel.textContent = "Status: Rendering...";
        statusLabel.style.color = "var(--secondary)";
        
        logConsole("progress", `Sending image generation request for '${imageName}' using ref '${referenceImageName}' to Fal.ai...`);
        
        const payload = {
            prompt: promptText,
            output_dir_name: outputDirName,
            image_name: imageName,
            reference_image: referenceImageName
        };
        
        return fetch("/api/generate-image", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        })
        .then(res => {
            if (!res.ok) throw new Error(`Server returned error status ${res.status}`);
            return res.json();
        })
        .then(data => {
            if (data.status === "success") {
                logConsole("success", `Successfully generated lifestyle photo: '${imageName}'!`);
                statusLabel.textContent = "Status: Ready";
                statusLabel.style.color = "#34A853";
                
                // Show loaded image
                imgEl.src = `${data.image_url}?t=${new Date().getTime()}`;
                imgEl.style.display = "block";
                emptyIcon.style.display = "none";
                
                btn.querySelector("span").textContent = "Regenerate";
            } else {
                throw new Error("API reported failure");
            }
            btn.disabled = false;
        })
        .catch(err => {
            logConsole("error", `Failed to generate photo '${imageName}': ${err.message}`);
            statusLabel.textContent = "Status: Failed";
            statusLabel.style.color = "var(--accent-red)";
            btn.querySelector("span").textContent = "Retry";
            btn.disabled = false;
        });
    }

    // Add new image slot
    btnAddSlot.addEventListener("click", () => {
        if (!activeListing) return;
        
        // Remove empty placeholders if any
        const placeholder = imagesGrid.querySelector(".image-placeholder");
        if (placeholder) placeholder.remove();
        
        const newSlotIndex = activePrompts.length;
        const sectionId = `custom_slot_${newSlotIndex + 1}`;
        
        const currentTheme = themeSelector.value;
        const currentTrigger = triggerKeyword.value.trim() || "product";
        const initialPrompt = getPresetPromptText(currentTheme, "product_staging", currentTrigger);
        
        const newItem = {
            name: sectionId,
            prompt: initialPrompt
        };
        
        activePrompts.push(newItem);
        createPromptCardDOM(newItem, newSlotIndex);
        
        logConsole("system", `Created new custom photo slot: Slot #${newSlotIndex + 1}`);
    });

    // Trigger pipeline execution
    btnGenerate.addEventListener("click", () => {
        const url = urlInput.value.trim();
        if (!url) {
            logConsole("error", "Error: AliExpress URL is required.");
            alert("Please enter a valid AliExpress URL.");
            return;
        }
        
        // Reset states
        workspace.classList.add("disabled");
        btnSave.disabled = true;
        btnAddSlot.disabled = true;
        btnGenerateAllImages.disabled = true;
        consoleLogs.innerHTML = "";
        
        logConsole("system", "Connecting to pipeline status stream...");
        
        // Open SSE status connection
        eventSource = new EventSource("/api/status-stream");
        eventSource.onmessage = handleStreamMessage;
        eventSource.onerror = (err) => {
            logConsole("error", "Disconnected from server status stream.");
            cleanupStream();
            setControlsDisabled(false);
        };
        
        // Disable controls
        setControlsDisabled(true);
        
        const theme = themeSelector.value;
        const trigger = triggerKeyword.value.trim() || "product";
        const headed = headedMode.checked;
        const preset = presetSelector.value;
        
        // Call FastAPI generate endpoint
        const apiPath = `/api/scrape-and-generate?url=${encodeURIComponent(url)}&theme=${encodeURIComponent(theme)}&product_trigger=${encodeURIComponent(trigger)}&headed=${headed}&preset=${encodeURIComponent(preset)}`;
        
        fetch(apiPath, { method: "POST" })
            .then(res => res.json())
            .then(resData => {
                logConsole("system", `Job successfully queued: ${resData.message}`);
            })
            .catch(err => {
                logConsole("error", `Failed to initiate job: ${err.message}`);
                cleanupStream();
                setControlsDisabled(false);
            });
    });

    // Generate all images sequentially
    btnGenerateAllImages.addEventListener("click", async () => {
        btnGenerateAllImages.disabled = true;
        logConsole("system", "Starting batch Fal.ai image generations for all slots...");
        
        const cards = document.querySelectorAll(".prompt-card");
        for (const card of cards) {
            const sectionName = card.dataset.section;
            const textarea = card.querySelector(".prompt-card-textarea");
            const imgEl = card.querySelector(".prompt-card-img-wrapper img");
            const emptyIcon = card.querySelector(".empty-photo-icon");
            const btn = card.querySelector(".button-group button:last-child");
            const statusLabel = card.querySelector(".prompt-card-actions span");
            const refSelect = card.querySelector(".prompt-card-select:last-of-type");
            
            // Execute and wait for completion sequentially
            await generateSingleImage(textarea.value, `${sectionName}.png`, refSelect.value, imgEl, emptyIcon, btn, statusLabel);
        }
        
        logConsole("success", "All image generation slots finished processing.");
        btnGenerateAllImages.disabled = false;
    });

    // Save changes
    btnSave.addEventListener("click", () => {
        if (!activeListing || !outputDirName) return;
        
        logConsole("system", "Saving listing updates back to disk...");
        btnSave.disabled = true;
        
        const payload = {
            title: etsyTitle.value,
            suggested_price: etsyPrice.value,
            description: etsyDesc.value,
            tags: activeListing.tags,
            output_dir_name: outputDirName
        };
        
        fetch("/api/save-listing", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        })
        .then(res => res.json())
        .then(data => {
            if (data.status === "success") {
                logConsole("success", "Listing successfully saved!");
                alert("Listing successfully saved to disk!");
            } else {
                logConsole("error", `Failed to save: ${data.detail || "Unknown error"}`);
            }
            btnSave.disabled = false;
        })
        .catch(err => {
            logConsole("error", `Failed to save: ${err.message}`);
            btnSave.disabled = false;
        });
    });

});
