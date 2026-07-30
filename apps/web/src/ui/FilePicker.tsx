import { useRef, useState, type DragEvent, type ReactNode } from "react";
import * as VisuallyHidden from "@radix-ui/react-visually-hidden";
import { FileUp, X } from "lucide-react";
import { useT } from "@/lib/useT";
import { cn } from "./cn";

export interface FilePickerProps {
  file: File | null;
  onFile: (file: File | null) => void;
  accept?: string;
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  disabled?: boolean;
  wrapperClassName?: string;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * File chooser: a visually-hidden native input + a hand-drawn click / drop zone. Once a file
 * is chosen it shows the name + size in mono, and can be removed.
 */
export function FilePicker({
  file,
  onFile,
  accept,
  label,
  hint,
  error,
  disabled,
  wrapperClassName,
}: FilePickerProps) {
  const t = useT();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (disabled) return;
    const f = e.dataTransfer.files?.[0];
    if (f) onFile(f);
  };

  return (
    <div className={cn("flex flex-col gap-1.5", wrapperClassName)}>
      {label != null && <span className="text-13 font-medium text-ink-2">{label}</span>}
      <VisuallyHidden.Root asChild>
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          disabled={disabled}
          onChange={(e) => {
            const f = e.target.files?.[0] ?? null;
            onFile(f);
            e.target.value = "";
          }}
        />
      </VisuallyHidden.Root>
      {file ? (
        <div
          className={cn(
            "flex h-12 items-center justify-between gap-3 rounded-2 border bg-surface px-3",
            error ? "border-danger" : "border-line-2",
          )}
        >
          <div className="flex min-w-0 items-baseline gap-2">
            <span className="truncate text-14 text-ink">{file.name}</span>
            <span className="shrink-0 font-mono text-12 text-ink-3 tabular-nums">
              {formatSize(file.size)}
            </span>
          </div>
          <button
            type="button"
            aria-label={t("common.removeFile")}
            disabled={disabled}
            onClick={() => onFile(null)}
            className="inline-flex size-6 shrink-0 items-center justify-center rounded-1 text-ink-3 hover:bg-hover hover:text-ink"
          >
            <X size={14} aria-hidden />
          </button>
        </div>
      ) : (
        <button
          type="button"
          disabled={disabled}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            if (!disabled) setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          className={cn(
            "flex min-h-20 w-full flex-col items-center justify-center gap-1 rounded-2 border border-dashed px-4 py-4",
            "transition-colors duration-120 ease-out",
            dragOver ? "border-accent bg-accent-soft" : error ? "border-danger" : "border-line-2",
            "hover:not-disabled:border-ink-3",
            "disabled:cursor-not-allowed disabled:opacity-45",
          )}
        >
          <FileUp size={16} aria-hidden className="text-ink-3" />
          <span className="text-13 text-ink-2">
            {dragOver ? t("common.filePicker.drop") : t("common.filePicker.idle")}
          </span>
        </button>
      )}
      {(error || hint) && (
        <p className={cn("text-12", error ? "text-danger" : "text-ink-3")}>{error ?? hint}</p>
      )}
    </div>
  );
}
