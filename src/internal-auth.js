const encoder = new TextEncoder();

async function sha256(value) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(value)));
}

export async function constantTimeSecretEqual(left, right) {
  if (!left || !right) return false;
  const [leftHash, rightHash] = await Promise.all([sha256(String(left)), sha256(String(right))]);
  let difference = 0;
  for (let index = 0; index < leftHash.length; index += 1) {
    difference |= leftHash[index] ^ rightHash[index];
  }
  return difference === 0;
}

export async function authorizeInternalRefresh(request, configuredSecret) {
  if (request.method !== "POST" || !configuredSecret) return false;
  return constantTimeSecretEqual(
    request.headers.get("x-twss-refresh-token") || "",
    configuredSecret,
  );
}
