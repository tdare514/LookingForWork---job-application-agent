import { SESSION_SECONDS } from "./config.js";

const encoder = new TextEncoder();
const decoder = new TextDecoder();

function encode(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function decode(value: string): Uint8Array {
  const padded = value.replaceAll("-", "+").replaceAll("_", "/") + "===".slice((value.length + 3) % 4);
  return Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
}

// AES-GCM takes a raw key of exactly 16, 24 or 32 bytes, and SESSION_SECRET is
// only required to be at least 32 characters. Hash it to a fixed 32 bytes so a
// 44-character base64 secret works instead of failing every login.
async function key(secret: string): Promise<CryptoKey> {
  const material = await crypto.subtle.digest("SHA-256", encoder.encode(secret));
  return crypto.subtle.importKey("raw", material, "AES-GCM", false, ["encrypt", "decrypt"]);
}

export async function seal(value: string, secret: string): Promise<string> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = new Uint8Array(
    await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await key(secret), encoder.encode(value)),
  );
  return `${encode(iv)}.${encode(ciphertext)}`;
}

export async function open(sealed: string, secret: string): Promise<string | null> {
  const [ivValue, ciphertextValue] = sealed.split(".");
  if (!ivValue || !ciphertextValue) return null;
  try {
    const plaintext = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: decode(ivValue) },
      await key(secret),
      decode(ciphertextValue),
    );
    return decoder.decode(plaintext);
  } catch {
    return null;
  }
}

export function randomToken(bytes = 32): string {
  return encode(crypto.getRandomValues(new Uint8Array(bytes)));
}

export function parseCookies(header: string | null): Map<string, string> {
  const cookies = new Map<string, string>();
  for (const part of header?.split(";") ?? []) {
    const separator = part.indexOf("=");
    if (separator > 0) cookies.set(part.slice(0, separator).trim(), part.slice(separator + 1).trim());
  }
  return cookies;
}

export function cookie(name: string, value: string, maxAge: number): string {
  return `${name}=${value}; Max-Age=${maxAge}; Path=/; HttpOnly; Secure; SameSite=Lax`;
}

export function csrfCookie(value: string): string {
  return `jobagent_csrf=${value}; Max-Age=${SESSION_SECONDS}; Path=/; Secure; SameSite=Lax`;
}

export const denied = (): Response =>
  Response.json({ error: "access denied" }, { status: 403, headers: { "cache-control": "no-store" } });

// Compare digests rather than the strings, so the time taken says nothing about
// how much of a guess was right.
export async function sameSecret(given: string, expected: string): Promise<boolean> {
  const [a, b] = await Promise.all(
    [given, expected].map(async (value) => new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(value)))),
  );
  let difference = 0;
  for (let index = 0; index < a!.length; index += 1) difference |= a![index]! ^ b![index]!;
  return difference === 0;
}
