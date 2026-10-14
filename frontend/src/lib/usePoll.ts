import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

/** Interroge l'API à intervalle régulier ; conserve les dernières données en cas d'erreur réseau passagère. */
export function usePoll<T>(url: string, intervalMs: number, enabled = true) {
  return useQuery<T>({
    queryKey: [url],
    queryFn: () => api.get<T>(url),
    refetchInterval: intervalMs,
    refetchIntervalInBackground: false,
    enabled,
    retry: 1,
    placeholderData: (prev) => prev,
  });
}
