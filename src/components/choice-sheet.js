export function createChoiceSheet() {
	return `
    <div class="choice-sheet" data-choice-sheet role="dialog" aria-modal="true" aria-labelledby="candidate-choice-title" aria-hidden="true" hidden>
      <section class="choice-sheet-panel" data-choice-sheet-backdrop>
        <header class="choice-sheet-header">
          <h3 id="candidate-choice-title" data-choice-sheet-title>選擇條件</h3>
          <button class="text-button" type="button" data-close-choice-sheet>取消</button>
        </header>
        <div class="choice-sheet-options" data-choice-sheet-options></div>
      </section>
    </div>`;
}

function selectForTrigger(root, trigger) {
	return (
		[...root.querySelectorAll("[data-choice-select]")].find(
			(select) => select.name === trigger.dataset.choiceFor,
		) ?? null
	);
}

function selectedOption(select) {
	return (
		[...select.options].find((option) => option.value === select.value) ??
		select.options[0] ??
		null
	);
}

export function initializeChoiceSheet(root) {
	const sheet = root.querySelector("[data-choice-sheet]");
	const title = sheet?.querySelector("[data-choice-sheet-title]");
	const optionsRoot = sheet?.querySelector("[data-choice-sheet-options]");
	let activeTrigger = null;
	let activeSelect = null;

	const syncTrigger = (trigger) => {
		const select = selectForTrigger(root, trigger);
		if (!select) return;
		const valueLabel = trigger.querySelector("[data-choice-value]");
		if (valueLabel)
			valueLabel.textContent = selectedOption(select)?.textContent ?? "—";
		trigger.disabled = select.disabled;
	};

	const syncAll = () => {
		root.querySelectorAll("[data-choice-trigger]").forEach(syncTrigger);
	};

	const close = ({ restoreFocus = true } = {}) => {
		if (!sheet || sheet.hidden) return;
		sheet.hidden = true;
		sheet.setAttribute("aria-hidden", "true");
		activeTrigger?.setAttribute("aria-expanded", "false");
		document.body.classList.remove("has-open-choice-sheet");
		const trigger = activeTrigger;
		activeTrigger = null;
		activeSelect = null;
		if (restoreFocus) trigger?.focus();
	};

	const renderOptions = () => {
		if (!optionsRoot || !activeSelect) return;
		optionsRoot.replaceChildren();
		[...activeSelect.options].forEach((option) => {
			const button = document.createElement("button");
			const isSelected = option.value === activeSelect.value;
			button.type = "button";
			button.className = `choice-sheet-option${isSelected ? " is-selected" : ""}`;
			button.dataset.choiceOption = option.value;
			button.setAttribute("aria-pressed", String(isSelected));
			const label = document.createElement("span");
			label.textContent = option.textContent;
			const checkmark = document.createElement("span");
			checkmark.className = "choice-sheet-check";
			checkmark.setAttribute("aria-hidden", "true");
			checkmark.textContent = "✓";
			button.append(label, checkmark);
			optionsRoot.append(button);
		});
	};

	const open = (trigger) => {
		if (!sheet || trigger.disabled) return;
		const select = selectForTrigger(root, trigger);
		if (!select || select.disabled) return;
		activeTrigger = trigger;
		activeSelect = select;
		if (title)
			title.textContent = `選擇${trigger.dataset.choiceLabel ?? "條件"}`;
		renderOptions();
		sheet.hidden = false;
		sheet.setAttribute("aria-hidden", "false");
		trigger.setAttribute("aria-expanded", "true");
		document.body.classList.add("has-open-choice-sheet");
		optionsRoot?.querySelector(".is-selected")?.focus();
	};

	root.addEventListener("click", (event) => {
		const trigger = event.target.closest("[data-choice-trigger]");
		if (trigger) {
			open(trigger);
			return;
		}

		const option = event.target.closest("[data-choice-option]");
		if (option && activeSelect) {
			activeSelect.value = option.dataset.choiceOption ?? "";
			syncTrigger(activeTrigger);
			activeSelect.dispatchEvent(new Event("change", { bubbles: true }));
			close();
			return;
		}

		if (
			event.target.closest("[data-close-choice-sheet]") ||
			event.target === sheet
		)
			close();
	});

	document.addEventListener("keydown", (event) => {
		if (event.key !== "Escape" || !sheet || sheet.hidden) return;
		event.preventDefault();
		event.stopImmediatePropagation();
		close();
	});

	syncAll();
	return Object.freeze({ close, syncAll });
}
