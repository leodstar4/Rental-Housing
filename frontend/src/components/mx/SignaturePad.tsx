/**
 * SignaturePad — accessible simple-electronic-signature capture (docs/MX_UX.md).
 *
 * Two tabs, both producing exactly ONE of the two fields the backend accepts (mx/models.py
 * SignRequest + mx/signatures.py):
 *   • "Dibujar": a <canvas> drawn with Pointer Events → PNG. We rasterize to a bounded size and
 *     check the client-side limits (PNG_MAX_BYTES, PNG_MAX_W/H) that mirror validate_png before
 *     handing the base64 up; the server re-validates.
 *   • "Escribir": a typed name → typed_signature (method "tecleada"). Recommended for keyboard /
 *     screen-reader users.
 *
 * Accessibility:
 *   • The two tabs are a real radiogroup; the canvas has an aria-label and written instructions,
 *     with the typed field offered as an always-available alternative.
 *   • Clear / undo are plain buttons; status is announced via role="status".
 *   • Respects prefers-reduced-motion implicitly (no animation here).
 *
 * This component owns NO consent and NO submit: the parent decides when to send. It only reports a
 * value through onChange: `{ kind: "trazo", png } | { kind: "tecleada", typed } | null`.
 */
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Eraser, PenLine, Type, Undo2 } from "lucide-react";

import { useMx } from "@/components/mx/MxShared";
import { base64ByteLength, PNG_MAX_BYTES, PNG_MAX_H, PNG_MAX_W } from "@/lib/mx-sign";

export type SignatureValue =
  | { kind: "trazo"; png: string }
  | { kind: "tecleada"; typed: string }
  | null;

/** Canvas backing-store size: well inside the server's 1200×600 px / 150 KB bounds. */
const CANVAS_W = 600;
const CANVAS_H = 220;

type Stroke = Array<{ x: number; y: number }>;

export function SignaturePad({
  onChange,
  disabled,
}: {
  onChange: (value: SignatureValue) => void;
  disabled?: boolean;
}) {
  const { mx } = useMx();
  const s = mx.sign;
  const [tab, setTab] = useState<"trazo" | "tecleada">("trazo");
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const strokesRef = useRef<Stroke[]>([]);
  const drawingRef = useRef(false);
  const [hasInk, setHasInk] = useState(false);

  const tabId = useId();

  // Redraw the whole canvas from the stored strokes (device-pixel aware, crisp lines).
  const redraw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "#1f2937";
    ctx.lineWidth = 2.2;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    for (const stroke of strokesRef.current) {
      if (stroke.length < 2) continue;
      ctx.beginPath();
      ctx.moveTo(stroke[0].x, stroke[0].y);
      for (let i = 1; i < stroke.length; i++) ctx.lineTo(stroke[i].x, stroke[i].y);
      ctx.stroke();
    }
  }, []);

  useEffect(() => {
    redraw();
  }, [redraw]);

  // Map a pointer event to canvas backing-store coordinates.
  const point = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    return {
      x: ((e.clientX - rect.left) / rect.width) * canvas.width,
      y: ((e.clientY - rect.top) / rect.height) * canvas.height,
    };
  };

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (disabled) return;
    e.preventDefault();
    canvasRef.current?.setPointerCapture(e.pointerId);
    drawingRef.current = true;
    strokesRef.current.push([point(e)]);
  };

  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawingRef.current) return;
    e.preventDefault();
    strokesRef.current[strokesRef.current.length - 1].push(point(e));
    redraw();
  };

  const commitDrawing = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ink = strokesRef.current.some((st) => st.length >= 2);
    setHasInk(ink);
    if (!ink) {
      setError(null);
      onChange(null);
      return;
    }
    const dataUrl = canvas.toDataURL("image/png");
    const b64 = dataUrl.slice(dataUrl.indexOf(",") + 1);
    // Client-side mirror of validate_png: byte size + dimensions. (Header/magic is guaranteed by
    // the canvas; the server re-validates everything authoritatively.)
    if (base64ByteLength(b64) > PNG_MAX_BYTES) {
      setError(s.errTooLarge);
      onChange(null);
      return;
    }
    if (canvas.width > PNG_MAX_W || canvas.height > PNG_MAX_H) {
      setError(s.errTooLarge);
      onChange(null);
      return;
    }
    setError(null);
    onChange({ kind: "trazo", png: b64 });
  }, [onChange, s.errTooLarge]);

  const onPointerUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawingRef.current) return;
    drawingRef.current = false;
    canvasRef.current?.releasePointerCapture?.(e.pointerId);
    commitDrawing();
  };

  const clearDrawing = () => {
    strokesRef.current = [];
    drawingRef.current = false;
    setHasInk(false);
    setError(null);
    redraw();
    onChange(null);
  };

  const undoStroke = () => {
    strokesRef.current.pop();
    redraw();
    commitDrawing();
  };

  const selectTab = (next: "trazo" | "tecleada") => {
    setTab(next);
    setError(null);
    // Switching tabs invalidates the other tab's value: report the active tab's current value.
    if (next === "tecleada") onChange(typed.trim() ? { kind: "tecleada", typed: typed.trim() } : null);
    else commitDrawing();
  };

  const onTypedChange = (value: string) => {
    setTyped(value);
    onChange(value.trim() ? { kind: "tecleada", typed: value.trim() } : null);
  };

  const tabBtn = (active: boolean) =>
    `flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
      active ? "bg-primary text-primary-foreground" : "border border-input bg-background hover:bg-accent"
    }`;

  return (
    <div className="space-y-3">
      <div role="radiogroup" aria-label={s.methodLegend} className="flex flex-wrap gap-2">
        <button
          type="button"
          role="radio"
          aria-checked={tab === "trazo"}
          id={`${tabId}-draw`}
          disabled={disabled}
          onClick={() => selectTab("trazo")}
          className={tabBtn(tab === "trazo")}
        >
          <PenLine className="h-4 w-4" aria-hidden /> {s.methodDraw}
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={tab === "tecleada"}
          id={`${tabId}-type`}
          disabled={disabled}
          onClick={() => selectTab("tecleada")}
          className={tabBtn(tab === "tecleada")}
        >
          <Type className="h-4 w-4" aria-hidden /> {s.methodType}
        </button>
      </div>

      {tab === "trazo" ? (
        <div className="space-y-2">
          <p id={`${tabId}-draw-help`} className="text-xs text-muted-foreground">
            {s.canvasInstructions}
          </p>
          <canvas
            ref={canvasRef}
            width={CANVAS_W}
            height={CANVAS_H}
            role="img"
            aria-label={s.canvasLabel}
            aria-describedby={`${tabId}-draw-help`}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerLeave={onPointerUp}
            onPointerCancel={onPointerUp}
            className="h-40 w-full touch-none rounded-md border-2 border-dashed border-input bg-background"
            style={{ touchAction: "none" }}
          />
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={undoStroke}
              disabled={disabled || !hasInk}
              className="inline-flex items-center gap-1.5 rounded-md border border-input px-2.5 py-1 text-sm hover:bg-accent disabled:opacity-50"
            >
              <Undo2 className="h-3.5 w-3.5" aria-hidden /> {s.undo}
            </button>
            <button
              type="button"
              onClick={clearDrawing}
              disabled={disabled || !hasInk}
              className="inline-flex items-center gap-1.5 rounded-md border border-input px-2.5 py-1 text-sm hover:bg-accent disabled:opacity-50"
            >
              <Eraser className="h-3.5 w-3.5" aria-hidden /> {s.clear}
            </button>
          </div>
        </div>
      ) : (
        <label className="flex flex-col gap-1">
          <span className="sr-only">{s.typedLabel}</span>
          <input
            value={typed}
            onChange={(e) => onTypedChange(e.target.value)}
            disabled={disabled}
            placeholder={s.typedLabel}
            className="rounded-md border border-input bg-background px-3 py-2 font-serif text-lg italic"
          />
          {typed.trim() && (
            <>
              <span className="text-xs text-muted-foreground">{s.typedPreview}</span>
              <span className="rounded-md border border-dashed border-border px-3 py-2 font-serif text-2xl italic">
                {typed.trim()}
              </span>
            </>
          )}
        </label>
      )}

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
