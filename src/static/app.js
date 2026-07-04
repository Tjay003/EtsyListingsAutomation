document.addEventListener("DOMContentLoaded", () => {
    
    // Elements
    const urlInput = document.getElementById("product-url");
    const themeSelector = document.getElementById("theme-selector");
    const presetSelector = document.getElementById("preset-selector");
    const triggerKeyword = document.getElementById("trigger-keyword");
    const headedMode = document.getElementById("headed-mode");
    const btnGenerate = document.getElementById("btn-generate");
    const btnSave = document.getElementById("btn-save");
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

    // Render list of prompt editing cards
    function renderPromptCards(prompts) {
        imagesGrid.innerHTML = "";
        
        const labels = {
            "1_showcase": "Showcase Photo",
            "2_worn_or_used": "Worn / Lifestyle Photo",
            "3_detail_close_up": "Close-up Detail Photo",
            "4_packaging_or_extra": "Packaging Photo"
        };
        
        prompts.forEach((item) => {
            const sectionName = item.name;
            const card = document.createElement("div");
            card.className = "prompt-card";
            card.dataset.section = sectionName;
            
            // Image preview wrapper
            const imgWrapper = document.createElement("div");
            imgWrapper.className = "prompt-card-img-wrapper";
            
            // Render blank visual state or loaded image
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
            
            const label = document.createElement("span");
            label.className = "prompt-card-label";
            label.textContent = labels[sectionName] || sectionName;
            
            const textarea = document.createElement("textarea");
            textarea.className = "prompt-card-textarea";
            textarea.value = item.prompt;
            
            textGroup.appendChild(label);
            textGroup.appendChild(textarea);
            
            const actions = document.createElement("div");
            actions.className = "prompt-card-actions";
            
            const statusIndicator = document.createElement("span");
            statusIndicator.className = "prompt-card-label";
            statusIndicator.style.color = "var(--neutral-grey)";
            statusIndicator.textContent = "Status: Not Generated";
            
            const runBtn = document.createElement("button");
            runBtn.className = "secondary-btn btn-sm";
            runBtn.innerHTML = `
                <span>Generate Photo</span>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <polygon points="5 3 19 12 5 21 5 3"></polygon>
                </svg>
            `;
            
            runBtn.addEventListener("click", () => {
                generateSingleImage(textarea.value, `${sectionName}.png`, imgEl, emptyIcon, runBtn, statusIndicator);
            });
            
            actions.appendChild(statusIndicator);
            actions.appendChild(runBtn);
            
            content.appendChild(textGroup);
            content.appendChild(actions);
            
            card.appendChild(imgWrapper);
            card.appendChild(content);
            imagesGrid.appendChild(card);
        });
    }

    // Call API to generate a single image card
    function generateSingleImage(promptText, imageName, imgEl, emptyIcon, btn, statusLabel) {
        btn.disabled = true;
        const origText = btn.querySelector("span").textContent;
        btn.querySelector("span").textContent = "Generating...";
        statusLabel.textContent = "Status: Querying Fal.ai...";
        statusLabel.style.color = "var(--secondary)";
        
        logConsole("progress", `Sending image request for '${imageName}' to Fal.ai...`);
        
        const payload = {
            prompt: promptText,
            output_dir_name: outputDirName,
            image_name: imageName
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
                logConsole("success", `Successfully generated '${imageName}'!`);
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
            logConsole("error", `Failed to generate '${imageName}': ${err.message}`);
            statusLabel.textContent = "Status: Failed";
            statusLabel.style.color = "var(--accent-red)";
            btn.querySelector("span").textContent = "Retry";
            btn.disabled = false;
        });
    }

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
            const btn = card.querySelector("button");
            const statusLabel = card.querySelector(".prompt-card-actions span");
            
            // Execute and wait for completion sequentially
            await generateSingleImage(textarea.value, `${sectionName}.png`, imgEl, emptyIcon, btn, statusLabel);
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
