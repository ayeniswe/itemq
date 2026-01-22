const toggleBtn = document.getElementById("inventory-add-toggle");
const overlay = document.getElementById("inventory-add-overlay");
const card = document.getElementById("inventory-add-card");

toggleBtn.addEventListener("click", () => {
    overlay.classList.remove("is-hidden");
});

overlay.addEventListener("click", (e) => {
    if (!card.contains(e.target)) {
        overlay.classList.add("is-hidden");
    }
});