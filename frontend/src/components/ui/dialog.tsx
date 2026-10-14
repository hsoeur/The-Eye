import * as D from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { Button } from "./button";
import { cn } from "@/lib/utils";

export function Modal({ open, onOpenChange, title, description, children, footer, wide }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: string; description?: string;
  children: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fade-in fixed inset-0 z-50 bg-black/50 backdrop-blur-[2px]" />
        <D.Content
          className={cn("fade-in fixed left-1/2 top-[12vh] z-50 flex max-h-[76vh] w-[calc(100vw-2rem)] -translate-x-1/2 flex-col rounded-xl border bg-surface shadow-2xl",
            wide ? "max-w-4xl" : "max-w-md")}
        >
          <div className="flex items-start justify-between gap-4 border-b px-5 py-4">
            <div>
              <D.Title className="text-[15px] font-semibold">{title}</D.Title>
              {description ? <D.Description className="mt-0.5 text-[13px] text-muted">{description}</D.Description>
                : <D.Description className="sr-only">{title}</D.Description>}
            </div>
            <D.Close asChild><Button variant="ghost" size="icon" aria-label="Fermer" className="-m-1.5"><X className="size-4" /></Button></D.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-auto px-5 py-4">{children}</div>
          {footer && <div className="flex justify-end gap-2 border-t px-5 py-3">{footer}</div>}
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}

type ConfirmOpts = { title: string; description?: string; confirmLabel?: string; danger?: boolean };
const ConfirmCtx = createContext<(o: ConfirmOpts) => Promise<boolean>>(async () => false);
export const useConfirm = () => useContext(ConfirmCtx);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [opts, setOpts] = useState<ConfirmOpts | null>(null);
  const resolver = useRef<(v: boolean) => void>(() => {});
  const confirm = useCallback((o: ConfirmOpts) => new Promise<boolean>((res) => { resolver.current = res; setOpts(o); }), []);
  const close = (v: boolean) => { resolver.current(v); setOpts(null); };
  return (
    <ConfirmCtx.Provider value={confirm}>
      {children}
      <Modal open={!!opts} onOpenChange={(o) => !o && close(false)} title={opts?.title ?? ""} description={opts?.description}
        footer={<>
          <Button onClick={() => close(false)}>Annuler</Button>
          <Button variant={opts?.danger ? "danger" : "primary"} onClick={() => close(true)}>{opts?.confirmLabel ?? "Confirmer"}</Button>
        </>}>
        <span className="sr-only">Confirmation</span>
      </Modal>
    </ConfirmCtx.Provider>
  );
}
