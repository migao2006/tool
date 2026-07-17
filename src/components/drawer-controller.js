function setDrawerOpen(drawer, isOpen) {
  drawer.hidden = !isOpen;
  drawer.setAttribute("aria-hidden", String(!isOpen));
  document.body.classList.toggle("has-open-drawer", isOpen);
  if (isOpen) drawer.querySelector("[data-close-drawer]")?.focus();
}

export function initializeDrawers() {
  document.addEventListener("click", (event) => {
    const openButton = event.target.closest("[data-open-drawer]");
    if (openButton) {
      const drawer = document.querySelector(`[data-drawer="${openButton.dataset.openDrawer}"]`);
      if (drawer) setDrawerOpen(drawer, true);
      return;
    }

    const closeButton = event.target.closest("[data-close-drawer]");
    if (closeButton) {
      const drawer = closeButton.closest("[data-drawer]");
      if (drawer) setDrawerOpen(drawer, false);
      return;
    }

    const backdrop = event.target.closest("[data-drawer-backdrop]");
    if (backdrop && event.target === backdrop) setDrawerOpen(backdrop, false);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const drawer = document.querySelector("[data-drawer]:not([hidden])");
    if (drawer) setDrawerOpen(drawer, false);
  });
}
