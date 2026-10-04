import { useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Button } from "@/components/ui/button";

const S = {
  en: { listen: "▶️ Listen", pause: "❚❚ Pause", aria: "Listen to a plain-language summary of this rule", pauseAria: "Pause the plain-language summary", err: "Audio unavailable", note: "AI-generated voice reading the summary above. Not legal advice.", left: "remaining" },
  es: { listen: "▶️ Escuchar", pause: "❚❚ Pausar", aria: "Escuchar un resumen en lenguaje sencillo de esta regla", pauseAria: "Pausar el resumen en lenguaje sencillo", err: "Audio no disponible", note: "Voz generada con IA que lee el resumen de arriba. No es asesoría legal.", left: "restante" },
};

let current: HTMLAudioElement | null = null;
const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export function AudioPlayer({ url, showNote }: { url: string; showNote: boolean }) {
  const { lang } = useI18n();
  const s = S[lang];
  const ref = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState(false);
  const [time, setTime] = useState(0);
  const [dur, setDur] = useState(0);
  const src = API_BASE + url;

  useEffect(() => { setError(false); setPlaying(false); setTime(0); setDur(0); }, [src]);
  useEffect(() => () => { if (current === ref.current) current = null; }, []);

  const toggle = async () => {
    const a = ref.current;
    if (!a) return;
    if (playing) { a.pause(); return; }
    if (current && current !== a) current.pause();
    current = a;
    try { setError(false); await a.play(); } catch { setError(true); }
  };

  const pct = dur ? (time / dur) * 100 : 0;
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" variant="outline" size="sm" onClick={toggle} aria-label={playing ? s.pauseAria : s.aria} aria-pressed={playing}>
          {playing ? s.pause : s.listen}
        </Button>
        {(playing || time > 0) && !error && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <div className="h-1 w-32 rounded bg-muted" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
              <div className="h-1 rounded bg-primary" style={{ width: `${pct}%` }} />
            </div>
            {dur > 0 && <span>{fmt(Math.max(dur - time, 0))} {s.left}</span>}
          </div>
        )}
        {error && <span role="alert" className="text-sm text-destructive">{s.err}</span>}
      </div>
      <audio ref={ref} src={src} preload="none"
        onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
        onEnded={() => { setPlaying(false); setTime(0); }}
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => setDur(e.currentTarget.duration)}
        onDurationChange={(e) => { const d = e.currentTarget.duration; if (isFinite(d)) setDur(d); }}
        onError={() => { setError(true); setPlaying(false); }} />
      {showNote && <p className="text-xs text-muted-foreground">{s.note}</p>}
    </div>
  );
}
