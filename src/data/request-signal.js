export function createRequestSignal(externalSignal, timeoutMs) {
	const controller = new AbortController();
	let timedOut = false;
	const forwardAbort = () => controller.abort(externalSignal?.reason);

	if (externalSignal?.aborted) forwardAbort();
	else externalSignal?.addEventListener("abort", forwardAbort, { once: true });

	const timer = globalThis.setTimeout(() => {
		timedOut = true;
		controller.abort();
	}, timeoutMs);

	return Object.freeze({
		signal: controller.signal,
		timedOut: () => timedOut,
		cleanup: () => {
			globalThis.clearTimeout(timer);
			externalSignal?.removeEventListener("abort", forwardAbort);
		},
	});
}
