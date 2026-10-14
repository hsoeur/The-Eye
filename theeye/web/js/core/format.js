export function bytes(n) {
  n = +n || 0;
  const u = ["o", "Ko", "Mo", "Go", "To"];
  let i = 0;
  while (n >= 1024 && i < 4) { n /= 1024; i++; }
  return `${n.toFixed(i > 1 ? 1 : 0)} ${u[i]}`;
}

export function uptime(s) {
  s = +s || 0;
  const d = Math.floor(s / 86400), hr = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return `${d ? d + " j " : ""}${hr} h ${m} min`;
}

export function ago(t, now = Date.now() / 1000) {
  const s = Math.max(0, now - t);
  if (s < 60) return "à l'instant";
  if (s < 3600) return `il y a ${Math.round(s / 60)} min`;
  if (s < 86400) return `il y a ${Math.round(s / 3600)} h`;
  return `il y a ${Math.round(s / 86400)} j`;
}

export const dateTime = (t) => new Date(t * 1000).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "medium" });

// Niveau d'une jauge en pourcentage
export const level = (p) => (p > 90 ? "critical" : p > 75 ? "warning" : "ok");
