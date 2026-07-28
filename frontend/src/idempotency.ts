type RandomSource = {
  randomUUID?: () => string;
  getRandomValues?: (values: Uint8Array) => Uint8Array;
};

function browserRandomSource(): RandomSource | undefined {
  if (typeof window === "undefined") return undefined;
  return window.crypto;
}

export function createIdempotencyKey(
  source: RandomSource | undefined = browserRandomSource(),
  now: number = Date.now(),
  fallbackRandom: () => number = Math.random
): string {
  if (source && typeof source.randomUUID === "function") {
    return `${source.randomUUID()}-${now}`;
  }

  const bytes = new Uint8Array(16);
  if (source && typeof source.getRandomValues === "function") {
    source.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(fallbackRandom() * 256);
    }
  }

  // Keep the familiar UUID v4 shape without depending on randomUUID().
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0"));
  const uuid = [
    hex.slice(0, 4).join(""),
    hex.slice(4, 6).join(""),
    hex.slice(6, 8).join(""),
    hex.slice(8, 10).join(""),
    hex.slice(10, 16).join("")
  ].join("-");
  return `${uuid}-${now}`;
}
