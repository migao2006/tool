const SECURITY_EVIDENCE_CATEGORIES = new Set([
	"TRADABILITY",
	"POSITION_LIMITS",
]);

function retargetGate(gate, { symbol, asOfDate, decisionAt }) {
	if (!gate.evidence) {
		return { ...gate, source_date: asOfDate };
	}
	const evidence = {
		...gate.evidence,
		effective_date: asOfDate,
		available_at: decisionAt,
	};
	if (SECURITY_EVIDENCE_CATEGORIES.has(evidence.category)) {
		evidence.symbol = symbol;
		evidence.publication_id = `${evidence.category.toLowerCase()}-${symbol}-${asOfDate}`;
	}
	return {
		...gate,
		source_date: asOfDate,
		evidence,
	};
}

export function retargetPredictionEvidence(
	prediction,
	{
		symbol = prediction.symbol,
		asOfDate = prediction.as_of_date,
		decisionAt = prediction.decision_at,
	} = {},
) {
	return {
		...prediction,
		symbol,
		as_of_date: asOfDate,
		decision_at: decisionAt,
		gates: prediction.gates.map((gate) =>
			retargetGate(gate, { symbol, asOfDate, decisionAt }),
		),
	};
}

export function retimeSnapshotEvidence(payload, { asOfDate, decisionAt }) {
	for (const collection of [
		payload.predictions,
		payload.watchlist,
		payload.excluded,
	]) {
		if (!Array.isArray(collection)) continue;
		for (const prediction of collection) {
			if (!Array.isArray(prediction.gates)) continue;
			prediction.gates = prediction.gates.map((gate) =>
				retargetGate(gate, {
					symbol: prediction.symbol,
					asOfDate,
					decisionAt,
				}),
			);
		}
	}
}
