document.addEventListener("DOMContentLoaded", () => {
    
    // UI Elements
    const navBtns = document.querySelectorAll(".nav-btn");
    const panels = document.querySelectorAll(".main-panel");
    const btnRefreshQueue = document.getElementById("btn-refresh-queue");
    const btnExportSelected = document.getElementById("btn-export-selected");
    const queueList = document.getElementById("queue-list");
    
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
    const etsyPrice = document.getElementById("etsy-price");
    const tagsContainer = document.getElementById("tags-container");
    const etsyDesc = document.getElementById("etsy-desc");
    const imagesGrid = document.getElementById("images-grid");
    
    // Settings Elements
    const settingOutputDir = document.getElementById("setting-output-dir");
    const btnSaveSettings = document.getElementById("btn-save-settings");
    const settingsStatus = document.getElementById("settings-status");

    // State
    let queueData = [];
    let selectedQueueItem = null;
    let eventSource = null;
    let activeListing = null;

    // --- INITIALIZATION ---
    loadSettings();
    loadThemes();
    loadQueue();
    connectStatusStream();

    // --- NAVIGATION ---
    navBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            navBtns.forEach(b => b.classList.remove("active"));
            panels.forEach(p => p.classList.remove("active"));
            btn.classList.add("active");
            document.getElementById(btn.dataset.target).classList.add("active");
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
        }).then(r => r.json()).then(res => {
            settingsStatus.style.display = "block";
            setTimeout(() => settingsStatus.style.display = "none", 3000);
            loadQueue(); // Reload queue in case dir changed
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
        fetch("/api/queue")
            .then(r => r.json())
            .then(data => {
                queueData = data.queue || [];
                renderQueue();
            });
    }

    function renderQueue() {
        queueList.innerHTML = "";
        
        if (queueData.length === 0) {
            queueList.innerHTML = `<div style="padding: 24px; color: var(--neutral-grey); text-align: center;">Queue is empty. Use the Chrome Extension to add products.</div>`;
            return;
        }

        queueData.forEach((item, idx) => {
            const row = document.createElement("div");
            row.className = "queue-item";
            
            // Checkbox for selection
            const chk = document.createElement("input");
            chk.type = "checkbox";
            chk.className = "queue-chk";
            chk.dataset.slug = item.slug;
            chk.addEventListener("change", updateExportBtnState);
            
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
            
            const btnOpen = document.createElement("button");
            btnOpen.className = "secondary-btn";
            if (status === "downloading") {
                btnOpen.textContent = "Downloading...";
                btnOpen.disabled = true;
            } else {
                btnOpen.textContent = "Open in Workspace";
                btnOpen.disabled = false;
                btnOpen.addEventListener("click", () => {
                    selectForWorkspace(item);
                });
            }
            
            const btnDelete = document.createElement("button");
            btnDelete.className = "danger-btn";
            btnDelete.textContent = "Delete";
            if (status === "downloading") {
                btnDelete.disabled = true;
            } else {
                btnDelete.disabled = false;
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
            }
            
            actions.appendChild(btnOpen);
            actions.appendChild(btnDelete);



            row.appendChild(chk);
            row.appendChild(thumb);
            row.appendChild(info);
            row.appendChild(actions);
            
            queueList.appendChild(row);
        });
    }

    function updateExportBtnState() {
        const checked = document.querySelectorAll(".queue-chk:checked");
        btnExportSelected.disabled = checked.length === 0;
    }

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
            
            // Re-render images if they exist
            if (item.prompts) {
                renderPromptCards(item.prompts, item.slug, [...item.main_images, ...item.variation_images, ...item.description_images]);
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
            } else if (data.status === "error") {
                logConsole("error", data.message);
                btnGenerate.disabled = false;
            } else if (data.status === "done") {
                logConsole("success", data.message);
                btnGenerate.disabled = false;
                
                if (data.listing) {
                    activeListing = data.listing;
                    activeListing.slug = data.output_dir_name;
                    populateWorkspace();
                }
                if (data.prompts) {
                    // Need images for reference dropdowns
                    let refImgs = [];
                    if (selectedQueueItem) {
                        refImgs = [...(selectedQueueItem.main_images||[]), ...(selectedQueueItem.variation_images||[])];
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
        etsyPrice.value = activeListing.suggested_price || "";
        etsyDesc.value = activeListing.description || "";
        
        renderTags(activeListing.tags || []);
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

        prompts.forEach((item, idx) => {
            const card = document.createElement("div");
            card.className = "prompt-card";
            
            // Img
            const imgWrap = document.createElement("div");
            imgWrap.className = "prompt-card-img-wrapper";
            const img = document.createElement("img");
            img.style.display = "none";
            imgWrap.appendChild(img);

            // If we already generated it previously, try to load it
            // For now, let's assume it's just the prompt UI. Users have to generate.
            
            // Content
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
                
                // Select first ref image
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
                }).catch(e => {
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
        
        fetch("/api/save-listing", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                title: etsyTitle.value,
                suggested_price: etsyPrice.value,
                description: etsyDesc.value,
                tags: activeListing.tags,
                output_dir_name: activeListing.slug
            })
        }).then(r => r.json()).then(res => {
            btnSave.textContent = "Save Updates";
            btnSave.disabled = false;
            if (res.status === "success") {
                alert("Saved to metadata.json!");
            }
        });
    });

});
