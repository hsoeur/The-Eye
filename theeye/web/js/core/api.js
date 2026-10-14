async function request(method, path, body) {
  let res;
  try {
    res = await fetch(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new Error("Serveur injoignable");
  }
  let data = null;
  try { data = await res.json(); } catch { /* corps vide */ }
  if (!res.ok) throw new Error((data && (data.error || data.out)) || `Erreur ${res.status}`);
  return data;
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body = {}) => request("POST", path, body),
  del: (path) => request("DELETE", path),
};
