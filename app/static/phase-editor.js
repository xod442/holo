(() => {
  const dialog = document.getElementById("pill-dialog");
  if (!dialog || typeof dialog.showModal !== "function") return;

  const content = document.getElementById("pill-dialog-content");
  let activePill;
  let placeholder;
  let opener;

  document.querySelectorAll(".expand-pill").forEach((button) => {
    button.hidden = false;
    button.addEventListener("click", () => {
      opener = button;
      activePill = button.closest(".phase");
      placeholder = document.createComment("Expanded pill");
      activePill.before(placeholder);
      content.append(activePill);
      button.hidden = true;
      dialog.setAttribute("aria-labelledby", activePill.querySelector(".phase-name").id);
      document.body.classList.add("pill-dialog-open");
      dialog.showModal();
      activePill.querySelector('textarea[name="notes"]').focus();
    });
  });

  document.getElementById("close-pill-dialog").addEventListener("click", () => dialog.close());
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      dialog.close();
    }
  });
  dialog.addEventListener("close", () => {
    placeholder.replaceWith(activePill);
    opener.hidden = false;
    document.body.classList.remove("pill-dialog-open");
    opener.focus();
  });
})();
