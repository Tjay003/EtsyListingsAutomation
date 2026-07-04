document.addEventListener("DOMContentLoaded", () => {
    
    // Elements
    const urlInput = document.getElementById("product-url");
    const themeSelector = document.getElementById("theme-selector");
    const triggerKeyword = document.getElementById("trigger-keyword");
    const headedMode = document.getElementById("headed-mode");
    const btnGenerate = document.getElementById("btn-generate");
    const btnSave = document.getElementById("btn-save");
    
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
    let activeImages = [];
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
        .catch(err => logConsole("error", `Failed to load themes config: ${err.message}`));

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
                activeImages = data.images;
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
        
        // Images
        renderImages(activeImages);
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

    // Render lifestyle images grid
    function renderImages(images) {
        imagesGrid.innerHTML = "";
        
        if (!images || images.length === 0) {
            imagesGrid.innerHTML = `<div class="image-placeholder">No images generated. Check pipeline logs.</div>`;
            return;
        }
        
        const labels = ["Showcase", "Worn/Used", "Close-up", "Detail/Extra"];
        
        images.forEach((imgSrc, idx) => {
            const card = document.createElement("div");
            card.className = "image-card";
            
            const img = document.createElement("img");
            // Add cachebuster to load fresh images if overwritten
            img.src = `${imgSrc}?t=${new Date().getTime()}`;
            img.alt = labels[idx] || "Product Photo";
            
            const label = document.createElement("span");
            label.className = "image-label";
            label.textContent = labels[idx] || `Photo ${idx + 1}`;
            
            card.appendChild(img);
            card.appendChild(label);
            imagesGrid.appendChild(card);
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
        
        // Call FastAPI generate endpoint
        const apiPath = `/api/scrape-and-generate?url=${encodeURIComponent(url)}&theme=${encodeURIComponent(theme)}&product_trigger=${encodeURIComponent(trigger)}&headed=${headed}`;
        
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
