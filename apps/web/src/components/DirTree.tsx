import { useState } from "react";
import { ChevronDown, ChevronRight, FileText, Folder } from "lucide-react";
import type { DirNode } from "@/lib/model";
import { cn } from "@/lib/cn";

export function DirTree({
  root,
  selectedPath,
  onSelect,
}: {
  root: DirNode;
  selectedPath: string | null;
  onSelect: (path: string) => void;
}) {
  return (
    <ul className="py-1">
      {root.children.map((child) => (
        <TreeItem
          key={child.path}
          node={child}
          depth={0}
          selectedPath={selectedPath}
          onSelect={onSelect}
        />
      ))}
    </ul>
  );
}

function TreeItem({
  node,
  depth,
  selectedPath,
  onSelect,
}: {
  node: DirNode;
  depth: number;
  selectedPath: string | null;
  onSelect: (path: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const pad = 8 + depth * 14;

  if (node.isDir) {
    return (
      <li>
        <button
          onClick={() => setOpen((o) => !o)}
          className="w-full flex items-center gap-1.5 py-1 pr-2 text-[length:var(--text-sm)] text-muted-foreground hover:text-foreground hover:bg-accent outline-none focus-visible:ring-2 focus-visible:ring-ring"
          style={{ paddingLeft: pad }}
        >
          {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          <Folder size={13} className="flex-none" />
          <span className="truncate">{node.name}</span>
        </button>
        {open && (
          <ul>
            {node.children.map((c) => (
              <TreeItem
                key={c.path}
                node={c}
                depth={depth + 1}
                selectedPath={selectedPath}
                onSelect={onSelect}
              />
            ))}
          </ul>
        )}
      </li>
    );
  }

  const active = node.path === selectedPath;
  return (
    <li>
      <button
        onClick={() => onSelect(node.path)}
        className={cn(
          "w-full flex items-center gap-1.5 py-1 pr-2 text-[length:var(--text-sm)] outline-none focus-visible:ring-2 focus-visible:ring-ring relative",
          active
            ? "text-foreground font-medium bg-accent"
            : "text-muted-foreground hover:text-foreground hover:bg-accent",
        )}
        style={{ paddingLeft: pad + 15 }}
      >
        {active && (
          <span
            className="absolute left-0 top-0 bottom-0"
            style={{ width: 3, background: "var(--color-accent)" }}
          />
        )}
        <FileText size={13} className="flex-none" />
        <span className="truncate">{node.doc?.title || node.name}</span>
      </button>
    </li>
  );
}
