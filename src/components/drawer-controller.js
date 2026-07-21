const drawerTriggers = new WeakMap();

function setDrawerOpen(drawer, isOpen, trigger = null) {
  if (isOpen && trigger) drawerTriggers.set(drawer, trigger);
  drawer.hidden = !isOpen;
  drawer.setAttribute("aria-hidden", String(!isOpen));
  document.body.classList.toggle(
    "has-open-drawer",
    Boolean(document.querySelector("[data-drawer]:not([hidden])")),
  );
  if (isOpen) {
    drawer.querySelector("[data-close-drawer]")?.focus();
  } else {
    drawerTriggers.get(drawer)?.focus();
    drawerTriggers.delete(drawer);
  }
}

export function initializeDrawers() {
  document.addEventListener("click", (event) => {
    const openButton = event.target.closest("[data-open-drawer]");
    if (openButton) {
      const drawer = document.querySelector(`[data-drawer="${openButton.dataset.openDrawer}"]`);
      if (drawer) setDrawerOpen(drawer, true, openButton);
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
