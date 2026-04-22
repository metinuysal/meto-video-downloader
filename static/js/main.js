function escapeHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function formatDuration(seconds) {
    if (!seconds) return "0:00";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    return `${m}:${String(s).padStart(2, "0")}`;
}

function formatFileSize(bytes) {
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0;
    while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++; }
    return `${bytes.toFixed(1)} ${units[i]}`;
}

// Mobile nav toggle
const navToggle = document.getElementById("nav-toggle");
const mobileMenu = document.getElementById("mobile-menu");
if (navToggle && mobileMenu) {
    navToggle.addEventListener("click", () => {
        mobileMenu.classList.toggle("open");
    });
}

// Project selector navigation
document.querySelectorAll(".project-select, .project-select-mobile").forEach(sel => {
    sel.addEventListener("change", () => {
        const pid = sel.value;
        const path = window.location.pathname;
        if (path === "/library") {
            window.location.href = `/library?project=${pid}`;
        } else if (path === "/settings") {
            window.location.href = `/settings?project=${pid}`;
        } else {
            window.location.href = `/?project=${pid}`;
        }
    });
});
