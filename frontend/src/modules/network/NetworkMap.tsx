import { Background, BackgroundVariant, Controls, ControlButton, Handle, Position, ReactFlow, type Edge, type Node, type NodeChange, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { LayoutGrid } from "lucide-react";
import { memo, useCallback, useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { TYPES, nameOf, typeInfo, type Device } from "./devices";

type DeviceData = { device: Device; selected: boolean };
type GroupData = { type: string; count: number; online: number };
type Pos = { x: number; y: number };

const hidden = { opacity: 0, width: 1, height: 1, border: 0, minWidth: 0 } as const;
const CELL_W = 196, CELL_H = 62, GAP = 14, MAX_ROW = 1250, STORE = "eye-map-positions";

const DeviceNode = memo(({ data }: NodeProps<Node<DeviceData>>) => {
  const { device: d, selected } = data;
  const Icon = typeInfo(d.type).icon;
  return (
    <div className={cn("flex w-[180px] cursor-grab items-center gap-2.5 rounded-lg border bg-surface px-2.5 py-2 shadow-sm transition-colors active:cursor-grabbing",
      selected ? "border-accent ring-2 ring-accent/30" : "hover:border-faint", !d.online && "opacity-55", d.new && "border-warn")}>
      <Handle type="target" position={Position.Top} style={hidden} />
      <div className={cn("relative flex size-8 shrink-0 items-center justify-center rounded-md bg-raised", d.is_gateway && "bg-accent/15 text-accent")}>
        <Icon className="size-4" />
        <span className={cn("absolute -right-0.5 -top-0.5 size-2.5 rounded-full border-2 border-surface", d.online ? "bg-ok" : "bg-faint")} />
      </div>
      <div className="min-w-0">
        <div className="truncate text-[12px] font-medium leading-tight">{nameOf(d)}</div>
        <div className="truncate font-mono text-[10.5px] leading-tight text-muted">{d.ip}</div>
      </div>
    </div>
  );
});

const GroupNode = memo(({ data }: NodeProps<Node<GroupData>>) => {
  const Icon = typeInfo(data.type).icon;
  return (
    <div className="flex w-[180px] items-center gap-2 px-1 text-[11px] font-medium uppercase tracking-wide text-muted">
      <Handle type="source" position={Position.Bottom} style={hidden} />
      <Icon className="size-3.5" />
      <span>{typeInfo(data.type).label}</span>
      <span className="ml-auto font-mono normal-case text-faint">{data.online}/{data.count}</span>
    </div>
  );
});

const nodeTypes = { device: DeviceNode, group: GroupNode };
const groupOf = (d: Device) => (d.type in TYPES ? d.type : "unknown");

const load = (): Record<string, Pos> => { try { return JSON.parse(localStorage.getItem(STORE) ?? "{}"); } catch { return {}; } };

/** Regroupement par type : un bloc par type, équipements en grille sous un en-tête. */
function layout(devices: Device[]) {
  const order = Object.keys(TYPES);
  const groups = new Map<string, Device[]>();
  for (const d of devices) groups.set(groupOf(d), [...(groups.get(groupOf(d)) ?? []), d]);
  const sorted = [...groups.entries()].sort(([a], [b]) => order.indexOf(a) - order.indexOf(b));

  const pos = new Map<string, Pos>();
  const headers: { id: string; type: string; x: number; y: number; count: number; online: number }[] = [];
  let x = 0, y = 0, rowH = 0;
  for (const [type, list] of sorted) {
    list.sort((a, b) => Number(!!b.is_gateway) - Number(!!a.is_gateway) || a.ip.localeCompare(b.ip, undefined, { numeric: true }));
    const cols = Math.min(4, Math.max(1, Math.ceil(Math.sqrt(list.length))));
    const rows = Math.ceil(list.length / cols);
    const w = cols * CELL_W, h = 34 + rows * CELL_H;
    if (x > 0 && x + w > MAX_ROW) { x = 0; y += rowH + 50; rowH = 0; }
    headers.push({ id: `grp:${type}`, type, x, y, count: list.length, online: list.filter((d) => d.online).length });
    list.forEach((d, i) => pos.set(d.ip, { x: x + (i % cols) * CELL_W, y: y + 34 + Math.floor(i / cols) * CELL_H }));
    x += w + GAP * 3; rowH = Math.max(rowH, h);
  }
  return { pos, headers };
}

export function NetworkMap({ devices, selected, onSelect }: { devices: Device[]; selected?: string; onSelect: (ip: string | null) => void }) {
  const structure = devices.map((d) => d.ip + d.type).join();
  const { pos, headers } = useMemo(() => layout(devices), [structure]); // eslint-disable-line react-hooks/exhaustive-deps
  const [moved, setMoved] = useState<Record<string, Pos>>(load);
  const [epoch, setEpoch] = useState(0);

  const edges: Edge[] = useMemo(() => devices.map((d) => ({
    id: `e:${d.ip}`, source: `grp:${groupOf(d)}`, target: d.ip,
    style: { strokeWidth: 1, strokeDasharray: "3 4", opacity: 0.5 },
  })), [structure]); // eslint-disable-line react-hooks/exhaustive-deps

  const nodes: Node[] = useMemo(() => [
    ...headers.map((h) => ({ id: h.id, type: "group", position: moved[h.id] ?? { x: h.x, y: h.y }, data: { type: h.type, count: h.count, online: h.online }, selectable: false })),
    ...devices.map((d) => ({ id: d.ip, type: "device", position: moved[d.ip] ?? pos.get(d.ip) ?? { x: 0, y: 0 }, data: { device: d, selected: d.ip === selected } })),
  ], [devices, selected, pos, headers, moved]);

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setMoved((m) => {
      let next = m;
      for (const c of changes) if (c.type === "position" && c.position) next = { ...next, [c.id]: c.position };
      return next;
    });
  }, []);

  const persist = useCallback(() => { setMoved((m) => { localStorage.setItem(STORE, JSON.stringify(m)); return m; }); }, []);
  const reset = () => { localStorage.removeItem(STORE); setMoved({}); setEpoch((e) => e + 1); };

  return (
    <ReactFlow key={structure + epoch} nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.12 }} minZoom={0.15} maxZoom={1.8}
      nodesDraggable nodesConnectable={false} elementsSelectable proOptions={{ hideAttribution: true }}
      onNodesChange={onNodesChange} onNodeDragStop={persist}
      onNodeClick={(_, n) => n.type === "device" && onSelect(n.id)} onPaneClick={() => onSelect(null)}>
      <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="var(--border)" />
      <Controls showInteractive={false}>
        <ControlButton onClick={reset} title="Réorganiser par type" aria-label="Réorganiser par type"><LayoutGrid /></ControlButton>
      </Controls>
    </ReactFlow>
  );
}
