function bytesToBase64(bytes: Uint8Array) {
  let value = "";
  for (const byte of bytes) value += String.fromCharCode(byte);
  return btoa(value);
}

function base64ToBytes(value: string) {
  const decoded = atob(value);
  return Uint8Array.from(decoded, (char) => char.charCodeAt(0));
}

async function encryptionKey() {
  const encoded = process.env.META_TOKEN_ENCRYPTION_KEY;
  if (!encoded) throw new Error("META_TOKEN_ENCRYPTION_KEY non configurata");
  const raw = base64ToBytes(encoded);
  if (raw.byteLength !== 32) throw new Error("META_TOKEN_ENCRYPTION_KEY deve contenere 32 byte in Base64");
  return crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["encrypt", "decrypt"]);
}

export async function encryptMetaToken(token: string) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const encrypted = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    await encryptionKey(),
    new TextEncoder().encode(token),
  );
  return {
    ciphertext: bytesToBase64(new Uint8Array(encrypted)),
    iv: bytesToBase64(iv),
  };
}
