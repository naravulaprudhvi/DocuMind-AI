// ==========================================================================
// Theme Management (System Preferred, Dark, Light)
// ==========================================================================
function updateThemeUI(effectiveTheme, preference) {
  const icon = document.getElementById("theme-btn-icon");
  const label = document.getElementById("theme-btn-label");
  if (icon) {
    if (preference === "system") {
      icon.className = "bi bi-circle-half";
      if (label) label.textContent = "Auto";
    } else if (preference === "dark") {
      icon.className = "bi bi-moon-stars-fill text-info";
      if (label) label.textContent = "Dark";
    } else {
      icon.className = "bi bi-sun-fill text-warning";
      if (label) label.textContent = "Light";
    }
  }

  document.querySelectorAll("[data-theme-value]").forEach((btn) => {
    const val = btn.getAttribute("data-theme-value");
    if (val === preference) {
      btn.classList.add("active", "fw-bold");
    } else {
      btn.classList.remove("active", "fw-bold");
    }
  });
}

function setDocuMindTheme(preference) {
  let effectiveTheme = preference;
  if (preference === "system") {
    effectiveTheme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  document.documentElement.setAttribute("data-bs-theme", effectiveTheme);
  document.documentElement.setAttribute("data-theme", effectiveTheme);
  localStorage.setItem("documind_theme", preference);
  updateThemeUI(effectiveTheme, preference);
}

// Live listener for OS system theme changes
try {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
    const currentPref = localStorage.getItem("documind_theme") || "system";
    if (currentPref === "system") {
      const newEffective = e.matches ? "dark" : "light";
      document.documentElement.setAttribute("data-bs-theme", newEffective);
      document.documentElement.setAttribute("data-theme", newEffective);
      updateThemeUI(newEffective, "system");
    }
  });
} catch (e) {}

// DocuMind AI - Client Interactions & Micro-Animations
document.addEventListener("DOMContentLoaded", () => {
  // 1. Initialize Theme Manager
  const currentPref = localStorage.getItem("documind_theme") || "system";
  setDocuMindTheme(currentPref);

  document.querySelectorAll("[data-theme-value]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      const val = btn.getAttribute("data-theme-value");
      setDocuMindTheme(val);
    });
  });

  // 2. Auto-dismiss alerts after 5 seconds
  const alerts = document.querySelectorAll(".alert");
  alerts.forEach((alert) => {
    setTimeout(() => {
      try {
        const bsAlert = new bootstrap.Alert(alert);
        bsAlert.close();
      } catch (e) {
        alert.remove();
      }
    }, 5000);
  });

  // 3. Initialize Bootstrap tooltips if any
  const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
  tooltipTriggerList.map((tooltipTriggerEl) => new bootstrap.Tooltip(tooltipTriggerEl));

  // 4. Global copy-to-clipboard helper for code snippets & citations
  document.querySelectorAll(".copy-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const targetSelector = btn.getAttribute("data-target");
      const targetEl = targetSelector ? document.querySelector(targetSelector) : btn.previousElementSibling;
      if (targetEl) {
        const textToCopy = targetEl.innerText || targetEl.textContent;
        try {
          await navigator.clipboard.writeText(textToCopy);
          const origHtml = btn.innerHTML;
          btn.innerHTML = '<i class="bi bi-check2 text-success"></i> Copied!';
          setTimeout(() => {
            btn.innerHTML = origHtml;
          }, 2000);
        } catch (err) {
          console.error("Clipboard copy failed", err);
        }
      }
    });
  });
});
