/**
 * The Steward's composer: one control, not three things near each other.
 *
 * The frame IS the input surface — thumbnails along its top, the text in the middle, and on
 * one bottom row the attach button, the keyboard hint as quiet text, and the send button in
 * the corner. Focus lands on the frame as a whole (the app's 2px accent ring, DESIGN.md §4.1),
 * because what the Owner is aiming at is the message, not the textarea element.
 *
 * Images are attached by paste, by drop, or by the attach button, and all three roads go
 * through the same two steps: `admitImages` decides on the file descriptor alone (type, size,
 * how many are already held) and only then are the accepted bytes read. A refusal is said in
 * words, in place, naming the file — never a silent drop.
 *
 * The queue note is the one piece of state the Owner needs while a turn runs, and it appears
 * only when it is true: there is something typed AND a turn is in flight. It is the warning
 * whose receipt is the `queued` marker on the sent message.
 */

import { useCallback, useLayoutEffect, useRef, useState, type ClipboardEvent, type DragEvent } from "react";
import { ImagePlus, Send, X } from "lucide-react";
import {
  MAX_IMAGES,
  MAX_IMAGE_BYTES,
  admitImages,
  type ImageRefusal,
  type ImageRejection,
  type StewardImage,
} from "@/lib/steward";
import type { MessageKey } from "@/lib/i18n";
import { useT } from "@/lib/useT";
import { Button } from "@/ui/Button";
import { IconButton } from "@/ui/IconButton";
import { cn } from "@/ui/cn";

/** A refusal is a reason key here and a sentence only in the dictionary (DESIGN.md §4.4). */
const REFUSAL_KEYS: Record<ImageRefusal, MessageKey> = {
  type: "steward.compose.refused.type",
  size: "steward.compose.refused.size",
  count: "steward.compose.refused.count",
};

const MIN_ROWS = 2;
const MAX_ROWS = 8;

export interface StewardComposerProps {
  draft: string;
  onDraftChange: (text: string) => void;
  images: StewardImage[];
  onImagesChange: (images: StewardImage[]) => void;
  onSend: () => void;
  disabled: boolean;
  /** A turn is in flight and something is typed: what is sent now waits for it to end. */
  queueing: boolean;
  working: boolean;
}

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export function StewardComposer({
  draft,
  onDraftChange,
  images,
  onImagesChange,
  onSend,
  disabled,
  queueing,
  working,
}: StewardComposerProps) {
  const t = useT();
  const areaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [rejected, setRejected] = useState<ImageRejection[]>([]);
  const [dropping, setDropping] = useState(false);

  // Grow with the content, between two and eight rows: a chat turn is a sentence, and a
  // pasted paragraph should not take the transcript's place.
  useLayoutEffect(() => {
    const el = areaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const line = parseFloat(getComputedStyle(el).lineHeight) || 21;
    el.style.height = `${Math.min(Math.max(el.scrollHeight, MIN_ROWS * line), MAX_ROWS * line)}px`;
  }, [draft, images.length]);

  const attach = useCallback(
    async (files: readonly File[]) => {
      if (files.length === 0) return;
      const admission = admitImages(
        images.length,
        files.map((f) => ({ name: f.name, mime: f.type, size: f.size })),
      );
      setRejected(admission.rejected);
      if (admission.accepted.length === 0) return;
      const read = await Promise.all(
        admission.accepted.map(async (index) => {
          const file = files[index];
          return {
            name: file.name || t("steward.compose.pastedImage"),
            mime: file.type,
            dataUrl: await readAsDataUrl(file),
          } satisfies StewardImage;
        }),
      );
      onImagesChange([...images, ...read.filter((image) => image.dataUrl !== "")]);
    },
    [images, onImagesChange, t],
  );

  const onPaste = useCallback(
    (event: ClipboardEvent<HTMLTextAreaElement>) => {
      const files = Array.from(event.clipboardData?.files ?? []);
      const pictures = files.filter((f) => f.type.startsWith("image/"));
      if (pictures.length === 0) return;
      // The pasted bytes are the message's, not the textarea's: never also paste a file path.
      event.preventDefault();
      void attach(pictures);
    },
    [attach],
  );

  const onDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setDropping(false);
      if (disabled) return;
      void attach(Array.from(event.dataTransfer?.files ?? []));
    },
    [attach, disabled],
  );

  const remove = useCallback(
    (index: number) => {
      onImagesChange(images.filter((_, i) => i !== index));
      setRejected([]);
    },
    [images, onImagesChange],
  );

  const empty = draft.trim() === "" && images.length === 0;

  return (
    <div
      onDragOver={(e) => {
        if (disabled) return;
        e.preventDefault();
        setDropping(true);
      }}
      onDragLeave={(e) => {
        if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
        setDropping(false);
      }}
      onDrop={onDrop}
      className={cn(
        "rounded-2 border bg-surface transition-colors duration-120 ease-out",
        "field-surface",
        dropping ? "border-accent-line bg-accent-soft" : "border-line-2",
        disabled && "opacity-45",
      )}
    >
      {images.length > 0 && (
        <ul className="flex flex-wrap gap-2 px-2 pt-2.5">
          {images.map((image, index) => (
            <li key={`${image.name}:${index}`} className="group relative">
              <img
                src={image.dataUrl}
                alt={image.name}
                title={image.name}
                className="size-14 rounded-2 border border-line object-cover"
              />
              <IconButton
                size="sm"
                aria-label={t("steward.compose.removeImage", { name: image.name })}
                className="absolute top-0.5 right-0.5 size-5 border border-line bg-raised text-ink-2"
                onClick={() => remove(index)}
              >
                <X size={11} aria-hidden />
              </IconButton>
            </li>
          ))}
        </ul>
      )}

      <textarea
        ref={areaRef}
        rows={MIN_ROWS}
        value={draft}
        disabled={disabled}
        placeholder={t("steward.compose.placeholder")}
        aria-label={t("steward.compose.label")}
        onChange={(e) => onDraftChange(e.target.value)}
        onPaste={onPaste}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            onSend();
          }
        }}
        className="block w-full resize-none overflow-y-auto bg-transparent px-3 pt-2.5 pb-1 text-14 leading-[1.75] text-ink placeholder:text-ink-3"
      />

      {rejected.length > 0 && (
        <ul className="px-3 pb-1">
          {rejected.map((refusal, index) => (
            <li key={`${refusal.name}:${index}`} className="text-12 text-danger">
              {t(REFUSAL_KEYS[refusal.reason], {
                name: refusal.name || t("steward.compose.pastedImage"),
                max: String(MAX_IMAGES),
                size: String(Math.round(MAX_IMAGE_BYTES / (1024 * 1024))),
              })}
            </li>
          ))}
        </ul>
      )}

      <div className="flex items-center gap-2 px-2 pb-2">
        <IconButton
          size="sm"
          aria-label={t("steward.compose.attach")}
          title={t("steward.compose.attach")}
          disabled={disabled || images.length >= MAX_IMAGES}
          onClick={() => fileRef.current?.click()}
        >
          <ImagePlus size={15} aria-hidden />
        </IconButton>
        {/* Quiet, and gone rather than cut in half on a narrow screen (DESIGN.md hard rule 8). */}
        <span className="hidden min-w-0 truncate text-12 text-ink-3 sm:block">
          {t("steward.compose.hint")}
        </span>
        <span className="flex-1" />
        {queueing && (
          <span className="min-w-0 truncate text-12 text-ink-2">
            {t("steward.compose.queueing")}
          </span>
        )}
        <Button
          size="sm"
          variant="primary"
          disabled={disabled || empty}
          onClick={onSend}
          aria-busy={working || undefined}
        >
          <Send size={13} aria-hidden />
          {t("steward.compose.send")}
        </Button>
      </div>

      {/* The native picker stays as the file-selection backing only (DESIGN.md hard rule 2). */}
      <input
        ref={fileRef}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif"
        multiple
        className="sr-only"
        tabIndex={-1}
        onChange={(e) => {
          void attach(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />
    </div>
  );
}
