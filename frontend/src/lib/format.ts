export const bytes = (n: number): string => {
  if (!isFinite(n) || n <= 0) return "0 o";
  const u = ["o", "Ko", "Mo", "Go", "To"];
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  const v = n / 1024 ** i;
  return `${v >= 100 || i === 0 ? v.toFixed(0) : v.toFixed(1)} ${u[i]}`;
};

export const uptime = (s: number): string => {
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d} j ${h} h` : h ? `${h} h ${m} min` : `${m} min`;
};

/** « il y a 3 min » à partir d'un timestamp serveur (secondes). */
export const ago = (t: number | undefined, now = Date.now() / 1000): string => {
  if (!t) return "—";
  const s = Math.max(0, now - t);
  if (s < 10) return "à l'instant";
  if (s < 60) return `il y a ${Math.floor(s)} s`;
  if (s < 3600) return `il y a ${Math.floor(s / 60)} min`;
  if (s < 86400) return `il y a ${Math.floor(s / 3600)} h`;
  return `il y a ${Math.floor(s / 86400)} j`;
};

export const dateTime = (t: number | undefined): string =>
  t ? new Date(t * 1000).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";

export const pct = (v: number, digits = 0) => `${v.toFixed(digits)} %`;

export type Level = "ok" | "warn" | "crit";
export const level = (p: number): Level => (p >= 90 ? "crit" : p >= 75 ? "warn" : "ok");

export const ipNum = (ip: string) => ip.split(".").reduce((x, y) => x * 256 + +y, 0);
