import { Background, BackgroundVariant, Controls, Handle, Panel, Position, ReactFlow, type Edge, type Node, type NodeChange, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { memo, useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { TYPES, inNet, nameOf, typeInfo, type Device } from "./devices";

type DeviceData = { device: Device; selected: boolean };
type HubData = { label: string; count: number };
type GroupData = { type: string; count: number; online: number };
type Pos = { x: number; y: number };

const hidden = { opacity: 0, width: 1, height: 1, border: 0, minWidth: 0 } as const;
const CELL_W = 196, CELL_H = 62, GAP = 14, MAX_ROW = 1250, MODE = "eye-map-mode";
type Mode = "type" | "network";

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

const HubNode = memo(({ data }: NodeProps<Node<HubData>>) => (
  <div className="rounded-full border-2 border-accent/60 bg-accent/10 px-4 py-2 text-center">
    <Handle type="source" position={Position.Bottom} style={hidden} />
    <div className="font-mono text-[12px] font-semibold">{data.label}</div>
    <div className="text-[10.5px] text-muted">{data.count} équipement{data.count > 1 ? "s" : ""}</div>
  </div>
));

const nodeTypes = { device: DeviceNode, group: GroupNode, hub: HubNode };
const groupOf = (d: Device) => (d.type in TYPES ? d.type : "unknown");

type Header = { id: string; kind: "group" | "hub"; type: string; label: string; x: number; y: number; count: number; online: number };

/** Disposition radiale : un cluster par sous-réseau, passerelle au plus près du centre. */
function layoutNetwork(devices: Device[], subnets: string[]) {
  const pos = new Map<string, Pos>();
  const headers: Header[] = [];
  const netOf = (d: Device) => subnets.find((c) => inNet(d.ip, c)) ?? "autre";
  const groups = new Map<string, Device[]>();
  for (const d of devices) groups.set(netOf(d), [...(groups.get(netOf(d)) ?? []), d]);
  let cursor = 0;
  for (const [net, list] of [...groups.entries()].sort(([a], [b]) => a.localeCompare(b))) {
    list.sort((a, b) => Number(!!b.is_gateway) - Number(!!a.is_gateway) || a.ip.localeCompare(b.ip, undefined, { numeric: true }));
    const rings: Device[][] = [];
    let radius = 230, i = 0;
    while (i < list.length) {
      const cap = Math.max(5, Math.floor((2 * Math.PI * radius) / 200));
      rings.push(list.slice(i, i + cap));
      i += cap; radius += 130;
    }
    const extent = radius - 130 + 120;
    const cx = cursor + extent, cy = extent;
    headers.push({ id: `net:${net}`, kind: "hub", type: "", label: net, x: cx - 60, y: cy - 24, count: list.length, online: 0 });
    rings.forEach((ring, r) => ring.forEach((d, k) => {
      const a = (2 * Math.PI * k) / ring.length - Math.PI / 2 + (r % 2 ? Math.PI / ring.length : 0);
      const rad = 230 + r * 130;
      pos.set(d.ip, { x: cx + rad * Math.cos(a) - 90, y: cy + rad * Math.sin(a) - 24 });
    }));
    cursor += extent * 2 + 60;
  }
  return { pos, headers, hubOf: (d: Device) => `net:${netOf(d)}` };
}

/** Regroupement par type : un bloc par type, équipements en grille sous un en-tête. */
function layoutType(devices: Device[]) {
  const order = Object.keys(TYPES);
  const groups = new Map<string, Device[]>();
  for (const d of devices) groups.set(groupOf(d), [...(groups.get(groupOf(d)) ?? []), d]);
  const sorted = [...groups.entries()].sort(([a], [b]) => order.indexOf(a) - order.indexOf(b));

  const pos = new Map<string, Pos>();
  const headers: Header[] = [];
  let x = 0, y = 0, rowH = 0;
  for (const [type, list] of sorted) {
    list.sort((a, b) => Number(!!b.is_gateway) - Number(!!a.is_gateway) || a.ip.localeCompare(b.ip, undefined, { numeric: true }));
    const cols = Math.min(4, Math.max(1, Math.ceil(Math.sqrt(list.length))));
    const rows = Math.ceil(list.length / cols);
    const w = cols * CELL_W, h = 34 + rows * CELL_H;
    if (x > 0 && x + w > MAX_ROW) { x = 0; y += rowH + 50; rowH = 0; }
    headers.push({ id: `grp:${type}`, kind: "group", type, label: "", x, y, count: list.length, online: list.filter((d) => d.online).length });
    list.forEach((d, i) => pos.set(d.ip, { x: x + (i % cols) * CELL_W, y: y + 34 + Math.floor(i / cols) * CELL_H }));
    x += w + GAP * 3; rowH = Math.max(rowH, h);
  }
  return { pos, headers, hubOf: (d: Device) => `grp:${groupOf(d)}` };
}

export function NetworkMap({ devices, subnets, selected, onSelect }: { devices: Device[]; subnets: string[]; selected?: string; onSelect: (ip: string | null) => void }) {
  const [mode, setMode] = useState<Mode>(() => (localStorage.getItem(MODE) === "network" ? "network" : "type"));
  const structure = mode + devices.map((d) => d.ip + d.type).join() + (mode === "network" ? subnets.join() : "");
  const { pos, headers, hubOf } = useMemo(() => (mode === "type" ? layoutType(devices) : layoutNetwork(devices, subnets)), [structure]); // eslint-disable-line react-hooks/exhaustive-deps
  const edges: Edge[] = useMemo(() => devices.map((d) => ({
    id: `e:${d.ip}`, source: hubOf(d), target: d.ip,
    style: { strokeWidth: d.is_gateway ? 2 : 1, strokeDasharray: mode === "type" ? "3 4" : undefined, opacity: 0.5 },
  })), [structure]); // eslint-disable-line react-hooks/exhaustive-deps

  const nodes: Node[] = useMemo(() => [
    ...headers.map((h) => ({ id: h.id, type: h.kind, position: { x: h.x, y: h.y }, selectable: false,
      data: h.kind === "hub" ? { label: h.label, count: h.count } : { type: h.type, count: h.count, online: h.online } })),
    ...devices.map((d) => ({ id: d.ip, type: "device", position: pos.get(d.ip) ?? { x: 0, y: 0 }, data: { device: d, selected: d.ip === selected } })),
  ], [devices, selected, pos, headers]);

  const pick = (m: Mode) => { localStorage.setItem(MODE, m); setMode(m); };

  return (
    <ReactFlow key={structure} nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.12 }} minZoom={0.15} maxZoom={1.8}
      nodesDraggable={false} nodesConnectable={false} elementsSelectable proOptions={{ hideAttribution: true }}
      onNodeClick={(_, n) => n.type === "device" && onSelect(n.id)} onPaneClick={() => onSelect(null)}>
      <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="var(--border)" />
      <Panel position="top-left">
        <div role="group" aria-label="Disposition" className="flex rounded-md border bg-surface p-0.5 shadow-sm">
          {([["type", "Par type"], ["network", "Par sous-réseau"]] as const).map(([id, label]) => (
            <button key={id} onClick={() => pick(id)} aria-pressed={mode === id} className={cn("h-6 rounded px-2 text-xs font-medium text-muted", mode === id && "bg-raised text-fg")}>{label}</button>
          ))}
        </div>
      </Panel>
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

