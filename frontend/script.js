const API_BASE_URL = "http://127.0.0.1:8000/api";
const FASTAPI_URL = "http://127.0.0.1:8001/api";
// DOM Elements
const uploadForm = document.getElementById("uploadForm");
const deviceRowsContainer = document.getElementById("deviceRowsContainer");
const addDeviceBtn = document.getElementById("addDeviceBtn");
const submitBtn = document.getElementById("submitBtn");
const statusMessage = document.getElementById("statusMessage");
const resultsSection = document.getElementById("resultsSection");
const reportsContainer = document.getElementById("reportsContainer");
const downloadPdfBtn = document.getElementById("downloadPdfBtn");
const humanInterventionSection = document.getElementById("humanInterventionSection");

const translateForm = document.getElementById("translateForm");
const translateFile = document.getElementById("translateFile");
const translateFileText = document.getElementById("translateFileText");
const translateSubmitBtn = document.getElementById("translateSubmitBtn");
const translateStatusMessage = document.getElementById(
  "translateStatusMessage",
);
let currentUploadIds = [];

const demoMappingSuggestions = {
  "secure-remote-access version-two": "management.ssh_version = 2",
};

const VENDOR_LABELS = {
  cisco: "Cisco IOS",
  juniper: "Juniper Junos",
  junos: "Juniper Junos",
};

// Keep the two dropdowns meaningful: picking a source auto-selects the other
// vendor as the target. Same vendor on both sides means "no conversion", which
// the API handles as an explicit passthrough.
function syncTranslateVendors(changedId) {
  const sourceSelect = document.getElementById("sourceVendor");
  const targetSelect = document.getElementById("targetVendor");
  const hint = document.getElementById("translateHint");
  if (!sourceSelect || !targetSelect) return;

  const source = sourceSelect.value;
  const preferredTarget = source === "cisco" ? "junos" : "cisco";

  if (changedId === "sourceVendor" || targetSelect.value === source) {
    targetSelect.value = preferredTarget;
  }

  const target = targetSelect.value;
  if (hint) {
    hint.textContent =
      source === target
        ? `${VENDOR_LABELS[source]} → ${VENDOR_LABELS[target]} (no conversion — passthrough)`
        : `${VENDOR_LABELS[source]} → ${VENDOR_LABELS[target]}`;
  }
}

// File name display listener
if (translateFile) {
  translateFile.addEventListener("change", (e) => {
    const fileName = e.target.files[0]?.name || "Choose file...";
    translateFileText.textContent = fileName;
  });
}

["sourceVendor", "targetVendor"].forEach((id) => {
  const el = document.getElementById(id);
  if (el) el.addEventListener("change", () => syncTranslateVendors(id));
});

// Handle form submission to FastAPI backend
if (translateForm) {
  translateForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const sourceVendor = document.getElementById("sourceVendor").value;
    const targetVendor = document.getElementById("targetVendor").value;
    const file = translateFile.files[0];

    if (!file) {
      showTranslateStatus("Please select a configuration file.", "error");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    formData.append("source_vendor", sourceVendor);
    formData.append("target_vendor", targetVendor);

    setTranslateLoading(true);
    showTranslateStatus("Translating configuration and running compliance checks...", "loading");

    try {
      // Calls the FastAPI route which handles translation and hands off to Django
      const response = await fetch(
        `${FASTAPI_URL}/translate/upload?source_vendor=${sourceVendor}&target_vendor=${targetVendor}`,
        {
          method: "POST",
          body: formData,
        },
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Translation failed");
      }

      renderTranslation(data, targetVendor);

      const handoff = data.ai_engine_handoff || {};
      if (handoff.success && handoff.compliance_report) {
        showTranslateStatus(
          "Translation and compliance audit completed successfully!",
          "success",
        );
      } else if (handoff.success) {
        showTranslateStatus(
          "Translation completed. The compliance audit needs a second pass — use Analyze Configurations to view it.",
          "success",
        );
      } else {
        showTranslateStatus(
          `Translation completed, but the compliance hand-off failed: ${
            handoff.error || "Django API unavailable on port 8000"
          }`,
          "error",
        );
      }

      // Render results using your existing display function or custom UI handler
      displayMultipleResults([
        {
          id: handoff.upload_id || "N/A",
          status: handoff.status || "done",
          vendor: targetVendor,
          compliance_report: handoff.compliance_report,
          baseline_json: handoff.baseline_json,
        },
      ]);

      if (data.download_source_stem) {
        downloadTranslatedFile(data.download_source_stem, data.download_target_vendor);
      }
      setTranslateLoading(false);
    } catch (error) {
      console.error("Translation Error:", error);
      showTranslateStatus(`Error: ${error.message}`, "error");
      setTranslateLoading(false);
    }
  });
}

// Show the translated configuration itself, not only the downstream report.
function renderTranslation(data, targetVendor) {
  let panel = document.getElementById("translationResult");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "translationResult";
    panel.className = "form-card";
    panel.style.marginTop = "20px";
    translateForm.closest(".form-card").appendChild(panel);
  }

  const commands = data.set_commands || [];
  const unresolved = data.unresolved || [];

  const meta = [
    `Direction: ${VENDOR_LABELS[data.source_vendor] || data.source_vendor} → ${
      VENDOR_LABELS[data.target_vendor] || targetVendor
    }`,
    `Confidence: ${
      data.overall_confidence != null ? Math.round(data.overall_confidence * 100) : 0
    }%`,
    `Status: ${data.status || "done"}`,
  ];
  if (unresolved.length) meta.push(`${unresolved.length} line(s) need human review`);

  panel.innerHTML = `
    <h3>${escapeHtml(VENDOR_LABELS[data.target_vendor] || targetVendor)} output</h3>
    <p style="font-size:13px;color:var(--text-secondary)">${escapeHtml(meta.join("  |  "))}</p>
    <pre style="background:#0f172a;color:#e2e8f0;padding:12px;border-radius:8px;overflow:auto;max-height:420px;font-size:12.5px">${escapeHtml(
      commands.join("\n") || "(no commands produced)",
    )}</pre>
    ${
      unresolved.length
        ? `<details style="margin-top:10px"><summary style="cursor:pointer">Lines needing human review (${unresolved.length})</summary>
           <ul style="font-size:13px">${unresolved
             .map((u) => `<li>${escapeHtml(u)}</li>`)
             .join("")}</ul></details>`
        : ""
    }`;
}

function showTranslateStatus(message, type) {
  translateStatusMessage.textContent = message;
  translateStatusMessage.className = `status-message ${type}`;
}

// async function downloadTranslatedFile(sourceStem, targetVendor) {
//     try {
//         const response = await fetch(
//             `${FASTAPI_URL}/translate/download?target_vendor=${targetVendor}&source_stem=${sourceStem}`
//         );
//         if (!response.ok) throw new Error('Download failed');

//         const blob = await response.blob();
//         const url = window.URL.createObjectURL(blob);
//         const a = document.createElement('a');
//         a.href = url;
//         a.download = `${sourceStem}_${targetVendor}.txt`;
//         document.body.appendChild(a);
//         a.click();
//         document.body.removeChild(a);
//         window.URL.revokeObjectURL(url);
//     } catch (err) {
//         console.error('Translated file download failed:', err);
//     }
// }

function downloadTranslatedFile(sourceStem, targetVendor) {
    const url = `${FASTAPI_URL}/translate/download?target_vendor=${targetVendor}&source_stem=${sourceStem}`;
    const a = document.createElement('a');
    a.href = url;
    a.download = `${sourceStem}_${targetVendor}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

function setTranslateLoading(isLoading) {
  translateSubmitBtn.disabled = isLoading;
  const btnText = translateSubmitBtn.querySelector(".btn-text");
  const btnLoader = translateSubmitBtn.querySelector(".btn-loader");

  if (isLoading) {
    btnText.style.display = "none";
    btnLoader.style.display = "inline";
  } else {
    btnText.style.display = "inline";
    btnLoader.style.display = "none";
  }
}

// Initialize with one default upload row
document.addEventListener("DOMContentLoaded", () => {
  addDeviceRow();
  syncTranslateVendors();
});

// Add new device row
addDeviceBtn.addEventListener("click", () => {
  addDeviceRow();
});

function addDeviceRow() {
  const rowIndex = deviceRowsContainer.children.length;
  // Generate a unique ID for the file input so the label click works
  const fileInputId = `configFile_${Date.now()}_${rowIndex}`;

  const row = document.createElement("div");
  row.className = "device-row";
  row.style.cssText =
    "position: relative; border-bottom: 1px solid #ccc; padding-bottom: 15px; margin-bottom: 15px;";

  row.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <span style="font-weight: bold;">Device ${rowIndex + 1}</span>
            ${rowIndex > 0 ? `<button type="button" class="remove-row-btn" style="background:none; border:none; color:red; cursor:pointer; font-weight:bold;">&times; Remove</button>` : ""}
        </div>
        
        <div class="form-group" style="margin-top: 10px;">
            <label>Device Vendor</label>
            <select class="vendor-select" required>
                <option value="">Select vendor...</option>
                <option value="cisco">Cisco</option>
                <option value="juniper">Juniper</option>
            </select>
        </div>

        <div class="form-group">
            <label for="${fileInputId}">Configuration File</label>
            <div class="file-input-wrapper">
                <!-- Added ID here -->
                <input type="file" id="${fileInputId}" class="config-file-input" accept=".txt,.conf,.cfg" required>
                <!-- Linked label using "for" attribute -->
                <label for="${fileInputId}" class="file-input-label">
                    <span class="file-input-text">Choose file...</span>
                    <span class="file-input-button">Browse</span>
                </label>
            </div>
            <span class="file-name"></span>
        </div>
    `;

  // File input event listener for this row
  const fileInput = row.querySelector(".config-file-input");
  const fileText = row.querySelector(".file-input-text");
  const fileNameSpan = row.querySelector(".file-name");

  fileInput.addEventListener("change", (e) => {
    const fileName = e.target.files[0]?.name || "";
    fileNameSpan.textContent = fileName;
    fileText.textContent = fileName || "Choose file...";
  });

  // Remove row event listener
  const removeBtn = row.querySelector(".remove-row-btn");
  if (removeBtn) {
    removeBtn.addEventListener("click", () => {
      row.remove();
      updateRowLabels();
    });
  }

  deviceRowsContainer.appendChild(row);
}

function updateRowLabels() {
  Array.from(deviceRowsContainer.children).forEach((row, index) => {
    const label = row.querySelector("span");
    if (label) label.textContent = `Device ${index + 1}`;
  });
}

// Form submission
uploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();

  const rows = deviceRowsContainer.querySelectorAll(".device-row");
  const formData = new FormData();
  let isValid = true;

  rows.forEach((row) => {
    const vendor = row.querySelector(".vendor-select").value;
    const file = row.querySelector(".config-file-input").files[0];

    if (!vendor || !file) {
      isValid = false;
    } else {
      formData.append("config", file);
      formData.append("vendor", vendor);
    }
  });

  if (!isValid) {
    showStatus("Please select a vendor and file for each device.", "error");
    return;
  }

  setLoading(true);
  showStatus("Analyzing configurations...", "loading");
  resultsSection.style.display = "none";

  try {
    const response = await fetch(`${API_BASE_URL}/uploads/`, {
      method: "POST",
      body: formData,
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Upload failed");
    }

    const results = data.results || [data];
    currentUploadIds = results.filter((r) => r.id).map((r) => r.id);

    showStatus(`Analysis complete for ${results.length} device(s)!`, "success");

    displayMultipleResults(results);
    setLoading(false);

    setTimeout(() => {
      resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 300);
  } catch (error) {
    console.error("Error:", error);
    showStatus(`Error: ${error.message}`, "error");
    setLoading(false);
  }
});

// Download PDF (Multiple IDs)
downloadPdfBtn.addEventListener("click", async () => {
  if (!currentUploadIds.length) return;

  try {
    showStatus("Generating PDF report...", "loading");

    const idsQuery = currentUploadIds.join(",");
    const response = await fetch(
      `${API_BASE_URL}/uploads/report/pdf/?ids=${idsQuery}`,
    );

    if (!response.ok) {
      throw new Error("PDF generation failed");
    }

    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `combined-compliance-report.pdf`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);

    showStatus("PDF downloaded successfully!", "success");
    setTimeout(() => hideStatus(), 3000);
  } catch (error) {
    console.error("Error:", error);
    showStatus(`PDF download failed: ${error.message}`, "error");
  }
});

// // Render multiple device result cards
// function displayMultipleResults(results) {
//   resultsSection.style.display = "block";
//   reportsContainer.innerHTML = "";

//   results.forEach((data, index) => {
//     const card = document.createElement("div");
//     card.className = "report-card";
//     card.style.marginBottom = "30px";

//     if (data.status === "failed") {
//       card.innerHTML = `<h3>Device ${index + 1} (${data.vendor?.toUpperCase()})</h3><p style="color:red;">Error: ${data.error}</p>`;
//       reportsContainer.appendChild(card);
//       return;
//     }

//     const report = data.compliance_report;
//     const summary = report?.summary || {};

//     card.innerHTML = `
//             <div class="report-meta">
//                 <div class="meta-item">
//                     <span class="meta-label">Upload ID</span>
//                     <span class="meta-value">${data.id}</span>
//                 </div>
//                 <div class="meta-item">
//                     <span class="meta-label">Vendor</span>
//                     <span class="meta-value">${data.vendor ? data.vendor.toUpperCase() : "UNKNOWN"}</span>
//                 </div>
//                 <div class="meta-item">
//                     <span class="meta-label">Status</span>
//                     <span class="meta-value status-badge ${data.status}">${data.status}</span>
//                 </div>
//             </div>

//             <div class="summary-grid">
//                 <div class="summary-card total"><div class="label">Total Rules</div><div class="value">${summary.total || 0}</div></div>
//                 <div class="summary-card passed"><div class="label">Passed</div><div class="value">${summary.passed || 0}</div></div>
//                 <div class="summary-card failed"><div class="label">Failed</div><div class="value">${summary.failed || 0}</div></div>
//                 <div class="summary-card critical"><div class="label">Critical/High</div><div class="value">${summary.critical_high || 0}</div></div>
//             </div>

//             <div class="baseline-section">
//                 <h3>Baseline Configuration</h3>
//                 <div class="baseline-data">${renderBaseline(data.baseline_json)}</div>
//             </div>

//             <div class="rules-section">
//                 <h3>Compliance Rules</h3>
//                 <!-- <div class="rules-data">${renderRules(report?.results)}</div> -->
//                 <div class="rules-data">${renderRules(report?.results, data.id)}</div>
//             </div>
//         `;

//     reportsContainer.appendChild(card);
//   });
//   function displayMultipleResults(results) {
//     resultsSection.style.display = 'block';
//     reportsContainer.innerHTML = '';

//     results.forEach((data, index) => {
//         // ...existing code unchanged...
//         reportsContainer.appendChild(card);
//     });

//     // ADD THIS — wire up any "Fix with AI" buttons just rendered
//     reportsContainer.querySelectorAll('.fix-btn').forEach(btn => {
//         btn.addEventListener('click', () => {
//             fixWithAI(btn.dataset.uploadId, btn.dataset.ruleId);
//         });
//     });
//  }
// }


function downloadCorrectedConfig(uploadId) {
    const url = `${API_BASE_URL}/uploads/${uploadId}/corrected-config/`;
    const a = document.createElement('a');
    a.href = url;
    a.download = `corrected_config_${uploadId}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}
// Render multiple device result cards
function displayMultipleResults(results) {
  resultsSection.style.display = "block";
  reportsContainer.innerHTML = "";
  humanInterventionSection.hidden = true;
  const allReviews = [];

  results.forEach((data, index) => {
    const card = document.createElement("div");
    card.className = "report-card";
    card.style.marginBottom = "30px";

    if (data.status === "failed") {
      card.innerHTML = `<h3>Device ${index + 1} (${data.vendor?.toUpperCase()})</h3><p style="color:red;">Error: ${data.error}</p>`;
      reportsContainer.appendChild(card);
      return;
    }

    const report = data.compliance_report;
    const summary = report?.summary || {};

    const reviews = Array.isArray(data.normalization_review) ? data.normalization_review : [];
    allReviews.push(...reviews);
    card.innerHTML = `
            <div class="report-meta">
                <div class="meta-item">
                    <span class="meta-label">Upload ID</span>
                    <span class="meta-value">${data.id}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Vendor</span>
                    <span class="meta-value">${data.vendor ? data.vendor.toUpperCase() : "UNKNOWN"}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Status</span>
                    <span class="meta-value status-badge ${data.status}">${data.status}</span>
                </div>
            </div>

            <div class="summary-grid">
                <div class="summary-card total"><div class="label">Total Rules</div><div class="value">${summary.total || 0}</div></div>
                <div class="summary-card passed"><div class="label">Passed</div><div class="value">${summary.passed || 0}</div></div>
                <div class="summary-card failed"><div class="label">Failed</div><div class="value">${summary.failed || 0}</div></div>
                <div class="summary-card critical"><div class="label">Critical/High</div><div class="value">${summary.critical_high || 0}</div></div>
            </div>

            <div class="baseline-section">
                <h3>Baseline Configuration</h3>
                <div class="baseline-data">${renderBaseline(data.baseline_json)}</div>
            </div>

            <div class="rules-section">
                <h3>Compliance Rules</h3>
                <div class="rules-data">${renderRules(report?.results, data.id)}</div>
            </div>

            <button onclick="downloadCorrectedConfig('${data.id}')" class="btn-secondary" style="margin-top: 15px;">
                Download Corrected Config
            </button>
        `;

    reportsContainer.appendChild(card);
  });

  // Wire up the "Fix with AI" buttons after all cards are rendered
  reportsContainer.querySelectorAll('.fix-btn').forEach(btn => {
      btn.addEventListener('click', () => {
          fixWithAI(btn.dataset.uploadId, btn.dataset.ruleId);
      });
  });
  renderGlobalHumanIntervention(allReviews);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  }[char]));
}

function suggestionFor(command) {
  const match = Object.entries(demoMappingSuggestions)
    .find(([fragment]) => command.includes(fragment));
  return match ? match[1] : "";
}

function renderGlobalHumanIntervention(reviews) {
  if (!reviews.length) return;
  humanInterventionSection.hidden = false;
  humanInterventionSection.innerHTML = `
    <h3>Human intervention required</h3>
    <p>${reviews.length} uncertain command${reviews.length === 1 ? "" : "s"} must be approved before the learned result can be used.</p>
    <button class="btn-primary human-review-btn">Review and store embeddings</button>
    <div class="human-review-panel" hidden></div>`;
  humanInterventionSection.querySelector('.human-review-btn').addEventListener('click', () => openHumanReview(reviews));
}

function openHumanReview(reviews) {
  const panel = humanInterventionSection.querySelector('.human-review-panel');
  panel.hidden = false;
  panel.innerHTML = `
    <p class="review-help">Write the human normalization command in the form <code>canonical.path = JSON value</code>. This command and the original command embedding are stored together. For the supplied demo, values are pre-filled.</p>
    ${reviews.map((review, index) => {
      const humanCommand = suggestionFor(review.command || "");
      return `<article class="review-item" data-memory-id="${review.memory_id}">
        <div><strong>Command:</strong> <code>${escapeHtml(review.command)}</code></div>
        <div><strong>AI proposal:</strong> ${escapeHtml(review.proposed_meaning || "No proposal")}</div>
        <div><strong>AI confidence:</strong> ${Math.round((Number(review.confidence) || 0) * 100)}%</div>
        <label>Human normalization command <input class="review-command" value="${escapeHtml(humanCommand)}" placeholder="management.ssh_version = 2"></label>
      </article>`;
    }).join("")}
    <button class="btn-primary save-human-review">Approve and store embeddings</button>
    <p class="review-save-status" aria-live="polite"></p>`;
  panel.querySelector('.save-human-review').addEventListener('click', () => saveHumanReviews(panel));
}

async function saveHumanReviews(panel) {
  const button = panel.querySelector('.save-human-review');
  const status = panel.querySelector('.review-save-status');
  const rows = [...panel.querySelectorAll('.review-item')];
  const payloads = [];
  try {
    for (const row of rows) {
      const humanCommand = row.querySelector('.review-command').value.trim();
      if (!/^([A-Za-z_]\w*(?:\.\w+)*)\s*=\s*(.+)$/.test(humanCommand)) {
        throw new Error('Every entry must be in the form canonical.path = JSON value.');
      }
      const rawValue = humanCommand.slice(humanCommand.indexOf('=') + 1).trim();
      JSON.parse(rawValue);
      payloads.push({ id: row.dataset.memoryId, humanCommand });
    }
  } catch (error) {
    status.textContent = `Value error: ${error.message}. Use valid JSON (for example false, 2, or ["radius"]).`;
    status.className = 'review-save-status error';
    return;
  }

  button.disabled = true;
  status.textContent = 'Saving approved mappings and embeddings...';
  status.className = 'review-save-status';
  try {
    await Promise.all(payloads.map(async item => {
      const response = await fetch(`${API_BASE_URL}/normalization-reviews/${item.id}/`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision: 'approve', human_command: item.humanCommand }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `Could not save review ${item.id}`);
    }));
    status.textContent = 'Approved mappings and embeddings stored. Upload the same file again to run the learned compliance result.';
    status.className = 'review-save-status success';
    button.remove();
  } catch (error) {
    status.textContent = `Save failed: ${error.message}`;
    status.className = 'review-save-status error';
    button.disabled = false;
  }
}
function renderBaseline(baseline) {
  if (!baseline) return "<p>No baseline available.</p>";
  const displayFields = [
    { key: "vendor", label: "Vendor" },
    { key: "hostname", label: "Hostname" },
    { key: "os_version", label: "OS Version" },
    { key: "management.ssh_version", label: "SSH Version" },
    { key: "management.telnet_enabled", label: "Telnet Enabled" },
    { key: "management.http_enabled", label: "HTTP Enabled" },
    { key: "authentication.aaa_methods", label: "AAA Methods" },
    { key: "authentication.password_encryption", label: "Password Encryption" },
  ];

  return displayFields
    .map((field) => {
      const value = getNestedValue(baseline, field.key);
      if (value === null || value === undefined) return "";
      return `
            <div class="baseline-item">
                <div class="key">${field.label}</div>
                <div class="value">${formatValue(value)}</div>
            </div>`;
    })
    .join("");
}

// function renderRules(rules) {
//     if (!rules || !rules.length) return '<p>No rules processed.</p>';
//     return rules.map(rule => {
//         const statusEmoji = rule.status === 'Pass' ? '✅' : rule.status === 'Fail' ? '❌' : '⚠️';
//         return `
//             <div class="rule-item ${rule.status.toLowerCase()}">
//                 <div class="rule-header">
//                     <span class="rule-status">${statusEmoji}</span>
//                     <div class="rule-title">
//                         <div class="rule-id">[${rule.rule_id}]</div>
//                         <div class="rule-name">${rule.name}</div>
//                     </div>
//                 </div>
//                 <div class="rule-details">
//                     <div class="rule-detail"><span class="label">Field</span><span class="value">${rule.field}</span></div>
//                     <div class="rule-detail"><span class="label">Expected</span><span class="value">${formatValue(rule.expected)}</span></div>
//                     <div class="rule-detail"><span class="label">Actual</span><span class="value">${formatValue(rule.actual)}</span></div>
//                 </div>
//                 ${rule.reason ? `<div style="margin-top: 12px; font-size: 14px; color: var(--text-secondary); font-style: italic;">${rule.reason}</div>` : ''}
//             </div>`;
//     }).join('');
// }
function renderRules(rules, uploadId) {
    if (!rules || !rules.length) return '<p>No rules processed.</p>';
    return rules.map(rule => {
        const statusEmoji = rule.status === 'Pass' ? '✅' : rule.status === 'Fail' ? '❌' : '⚠️';
        return `
            <div class="rule-item ${rule.status.toLowerCase()}">
                <div class="rule-header">
                    <span class="rule-status">${statusEmoji}</span>
                    <div class="rule-title">
                        <div class="rule-id">[${rule.rule_id}]</div>
                        <div class="rule-name">${rule.name}</div>
                    </div>
                </div>
                <div class="rule-details">
                    <div class="rule-detail"><span class="label">Field</span><span class="value">${rule.field}</span></div>
                    <div class="rule-detail"><span class="label">Expected</span><span class="value">${formatValue(rule.expected)}</span></div>
                    <div class="rule-detail"><span class="label">Actual</span><span class="value">${formatValue(rule.actual)}</span></div>
                </div>
                ${rule.reason ? `<div style="margin-top: 12px; font-size: 14px; color: var(--text-secondary); font-style: italic;">${rule.reason}</div>` : ''}
                ${rule.status === 'Fail' ? `
                    <button class="fix-btn" data-upload-id="${uploadId}" data-rule-id="${rule.rule_id}">
                        Fix with AI
                    </button>
                    <div class="fix-suggestion" id="fix-${uploadId}-${rule.rule_id}"></div>
                ` : ''}
            </div>`;
    }).join('');
}

async function fixWithAI(uploadId, ruleId) {
    const container = document.getElementById(`fix-${uploadId}-${ruleId}`);
    container.innerHTML = 'Asking AI for a fix...';

    try {
        const response = await fetch(
            `${API_BASE_URL}/uploads/${uploadId}/remediation/propose/${ruleId}/`,
            { method: 'POST' }
        );
        const data = await response.json();

        if (response.ok && data.proposal && data.proposal.commands) {
            container.innerHTML = `
                <strong>Suggested fix:</strong>
                <pre>${data.proposal.commands.join('\n')}</pre>
            `;
        } else {
            container.innerHTML = `<span style="color:red;">${data.error || 'No suggestion returned.'}</span>`;
        }
    } catch (err) {
        container.innerHTML = `<span style="color:red;">Error: ${err.message}</span>`;
    }
}
// Helpers
function getNestedValue(obj, path) {
  return path.split(".").reduce((current, prop) => current?.[prop], obj);
}

function formatValue(value) {
  if (value === null || value === undefined) return "N/A";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.join(", ") || "Empty";
  if (typeof value === "object") return JSON.stringify(value);
  return value.toString();
}

function showStatus(message, type) {
  statusMessage.textContent = message;
  statusMessage.className = `status-message ${type}`;
}

function hideStatus() {
  statusMessage.className = "status-message";
}

function setLoading(isLoading) {
  submitBtn.disabled = isLoading;
  const btnText = submitBtn.querySelector(".btn-text");
  const btnLoader = submitBtn.querySelector(".btn-loader");

  if (isLoading) {
    btnText.style.display = "none";
    btnLoader.style.display = "inline";
  } else {
    btnText.style.display = "inline";
    btnLoader.style.display = "none";
  }
}
