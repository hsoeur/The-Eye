export interface Usage { host_id: string; machine: string; poste: string; usage: string }
export interface Account {
  id: string; label: string; username: string; kind: string; notes: string; usages: Usage[];
  created_at: number; updated_at: number; rotated_at: number;
}
export interface VaultState {
  available: boolean; error: string; initialized: boolean; unlocked: boolean; auto_lock_s: number;
  min_passphrase: number; kinds: string[]; count: number; retry_in_s: number; accounts: Account[]; stale_days: number;
}
export interface AuditEntry { t: number; action: string; client: string; account_id: string | null; label: string }
export interface AccountForm { label: string; username: string; kind: string; secret: string; notes: string; usages: Usage[] }
