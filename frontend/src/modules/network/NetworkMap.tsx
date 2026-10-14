import { Background, BackgroundVariant, Controls, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { memo, useMemo } from "react";
import { cn } from "@/lib/utils";
import { inNet, nameOf, typeInfo, type Device } from "./devices";

type DeviceData = { device: Device; selected: boolean };
type HubData = { label: string; count: number };

const hidden = { opacity: 0, width: 1, height: 1, border: 0, minWidth: 0 } as const;

const DeviceNode = memo(({ data }: NodeProps<Node<DeviceData>>) => {
  const { device: d, selected } = data;
  const Icon = typeInfo(d.type).icon;
  return (
    <div className={cn("flex w-[168px] items-center gap-2.5 rounded-lg border bg-surface px-2.5 py-2 shadow-sm transition-colors",
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

const HubNode = memo(({ data }: NodeProps<Node<HubData>>) => (
  <div className="rounded-full border-2 border-accent/60 bg-accent/10 px-4 py-2 text-center">
    <Handle type="source" position={Position.Bottom} style={hidden} />
    <div className="font-mono text-[12px] font-semibold">{data.label}</div>
    <div className="text-[10.5px] text-muted">{data.count} équipement{data.count > 1 ? "s" : ""}</div>
  </div>
));

const nodeTypes = { device: DeviceNode, hub: HubNode };

/** Placement radial déterministe : un cluster par sous-réseau, passerelle au plus près du centre. */
function layout(devices: Device[], subnets: string[]) {
  const pos = new Map<string, { x: number; y: number }>();
  const hubs: { id: string; label: string; x: number; y: number; count: number }[] = [];
  const edges: Edge[] = [];
  const groups = new Map<string, Device[]>();
  for (const d of devices) {
    const net = subnets.find((c) => inNet(d.ip, c)) ?? "autre";
    groups.set(net, [...(groups.get(net) ?? []), d]);
  }
  let cursor = 0;
  for (const [net, list] of [...groups.entries()].sort(([a], [b]) => a.localeCompare(b))) {
    list.sort((a, b) => Number(!!b.is_gateway) - Number(!!a.is_gateway) || a.ip.localeCompare(b.ip, undefined, { numeric: true }));
    const rings: Device[][] = [];
    let radius = 230, i = 0;
    while (i < list.length) {
      const cap = Math.max(5, Math.floor((2 * Math.PI * radius) / 190));
      rings.push(list.slice(i, i + cap));
      i += cap; radius += 130;
    }
    const extent = radius - 130 + 110;
    const cx = cursor + extent, cy = extent;
    hubs.push({ id: `net:${net}`, label: net, x: cx, y: cy, count: list.length });
    rings.forEach((ring, r) => {
      const rad = 230 + r * 130;
      ring.forEach((d, k) => {
        const a = (2 * Math.PI * k) / ring.length - Math.PI / 2 + (r % 2 ? Math.PI / ring.length : 0);
        pos.set(d.ip, { x: cx + rad * Math.cos(a), y: cy + rad * Math.sin(a) });
        edges.push({ id: `e:${d.ip}`, source: `net:${net}`, target: d.ip, type: "straight", animated: false, style: { strokeWidth: d.is_gateway ? 2 : 1 } });
      });
    });
    cursor += extent * 2 + 60;
  }
  return { pos, hubs, edges };
}

export function NetworkMap({ devices, subnets, selected, onSelect }: {
  devices: Device[]; subnets: string[]; selected?: string; onSelect: (ip: string | null) => void;
}) {
  const structure = devices.map((d) => d.ip).join() + "|" + subnets.join();
  const { pos, hubs, edges } = useMemo(() => layout(devices, subnets), [structure]); // eslint-disable-line react-hooks/exhaustive-deps

  const nodes: Node[] = useMemo(() => [
    ...hubs.map((h) => ({ id: h.id, type: "hub", position: { x: h.x - 60, y: h.y - 24 }, data: { label: h.label, count: h.count }, draggable: false, selectable: false })),
    ...devices.map((d) => ({ id: d.ip, type: "device", position: { x: (pos.get(d.ip)?.x ?? 0) - 84, y: (pos.get(d.ip)?.y ?? 0) - 24 },
      data: { device: d, selected: d.ip === selected }, draggable: false })),
  ], [devices, selected, pos, hubs]);

  return (
    <ReactFlow key={structure} nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.15 }} minZoom={0.15} maxZoom={1.8}
      nodesConnectable={false} elementsSelectable proOptions={{ hideAttribution: true }}
      onNodeClick={(_, n) => n.type === "device" && onSelect(n.id)} onPaneClick={() => onSelect(null)}>
      <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="var(--border)" />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}
