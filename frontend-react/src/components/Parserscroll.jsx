import { useCallback, useEffect, useRef, useState } from "react";
import {
  AnimatePresence,
  motion,
  useMotionValueEvent,
  useScroll,
  useTransform,
} from "framer-motion";

/* ───────── CONFIG: edit these ───────── */
const FRAME_COUNT = 120; // number of photos in /public/photo/parser
const frameSrc = (i) =>
  `/photo/parser/ezgif-frame-${String(i).padStart(3, "0")}.jpg`; // frame-001.jpg ...
const SCROLL_HEIGHT = "500vh"; // longer = slower playback

const LAYERS = [
  {
    id: "01",
    title: "INGESTION LAYER",
    text: "Collects vendor reports, logs, certificates and API feeds from every connected source into one normalized stream.",
  },
  {
    id: "02",
    title: "EXTRACTION LAYER",
    text: "Breaks raw documents into structured fields: controls, evidence, dates, owners and scope.",
  },
  {
    id: "03",
    title: "MAPPING LAYER",
    text: "Maps each extracted control to frameworks such as ISO 27001, SOC 2 and GDPR so vendors can be compared fairly.",
  },
  {
    id: "04",
    title: "EVALUATION LAYER",
    text: "Scores compliance, flags gaps and raises live alerts when a vendor drifts out of policy.",
  },
];
/* ─────────────────────────────────────── */

export default function ParserScroll() {
  const sectionRef = useRef(null);
  const wrapRef = useRef(null);
  const canvasRef = useRef(null);
  const imagesRef = useRef([]);
  const currentRef = useRef(0);
  const [loaded, setLoaded] = useState(false);
  const [active, setActive] = useState(0);

  const { scrollYProgress } = useScroll({
    target: sectionRef,
    offset: ["start start", "end end"],
  });
  // frames play across the first 90% of the scroll, then hold the last frame
  const frameIndex = useTransform(scrollYProgress, [0, 0.9], [0, FRAME_COUNT - 1]);
  const barWidth = useTransform(scrollYProgress, [0, 1], ["0%", "100%"]);

  // preload photos
  useEffect(() => {
    let done = 0;
    let cancelled = false;
    const imgs = [];
    for (let i = 1; i <= FRAME_COUNT; i++) {
      const img = new Image();
      img.src = frameSrc(i);
      const finish = () => {
        done++;
        if (!cancelled && done === FRAME_COUNT) setLoaded(true);
      };
      img.onload = finish;
      img.onerror = finish; // a missing frame must not block the section
      imgs.push(img);
    }
    imagesRef.current = imgs;
    return () => {
      cancelled = true;
    };
  }, []);

  const render = useCallback((index) => {
    const canvas = canvasRef.current;
    const img = imagesRef.current[index];
    if (!canvas || !img || !img.complete || !img.naturalWidth) return;
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.width / dpr;
    const h = canvas.height / dpr;
    const ratio = img.naturalWidth / img.naturalHeight;
    // "contain" so the whole photo is always visible
    let dw = w, dh = w / ratio;
    if (dh > h) { dh = h; dw = h * ratio; }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.drawImage(img, (w - dw) / 2, (h - dh) / 2, dw, dh);
  }, []);

  // keep canvas sharp and sized to its container
  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.round(wrap.clientWidth * dpr);
      canvas.height = Math.round(wrap.clientHeight * dpr);
      canvas.style.width = wrap.clientWidth + "px";
      canvas.style.height = wrap.clientHeight + "px";
      render(currentRef.current);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);
    return () => ro.disconnect();
  }, [render]);

  useEffect(() => {
    if (loaded) render(0);
  }, [loaded, render]);

  useMotionValueEvent(frameIndex, "change", (v) => {
    const i = Math.min(FRAME_COUNT - 1, Math.max(0, Math.round(v)));
    currentRef.current = i;
    if (loaded) requestAnimationFrame(() => render(i));
  });

  useMotionValueEvent(scrollYProgress, "change", (p) => {
    setActive(Math.min(LAYERS.length - 1, Math.floor(p * LAYERS.length)));
  });

  const layer = LAYERS[active];

  return (
    <section
      ref={sectionRef}
      className="relative w-full bg-black text-white font-mono"
      style={{ height: SCROLL_HEIGHT }}
    >
      <div className="sticky top-0 h-screen w-full overflow-hidden flex flex-col lg:flex-row">
        {/* LEFT: photo sequence */}
        <div className="relative w-full lg:w-1/2 h-1/2 lg:h-full border-b lg:border-b-0 lg:border-r border-gray-800">
          <div ref={wrapRef} className="absolute inset-0">
            <canvas
              ref={canvasRef}
              className={`transition-opacity duration-700 ${loaded ? "opacity-100" : "opacity-0"}`}
            />
          </div>
          {!loaded && (
            <div className="absolute inset-0 flex items-center justify-center text-[10px] tracking-[0.4em] text-gray-500">
              LOADING FRAMES...
            </div>
          )}
          <span className="absolute top-5 left-6 text-[10px] tracking-[0.3em] text-gray-500">
            // lib/photo/parser
          </span>
        </div>

        {/* RIGHT: description */}
        <div className="relative w-full lg:w-1/2 h-1/2 lg:h-full flex flex-col justify-center px-8 lg:px-20">
          <span className="text-[10px] tracking-[0.4em] text-gray-500 mb-4">
            4-LAYER PARSER — WORKING LAYER
          </span>

          <AnimatePresence mode="wait">
            <motion.div
              key={layer.id}
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -24 }}
              transition={{ duration: 0.35 }}
            >
              <span className="text-gray-600 text-lg block mb-2">{layer.id}</span>
              <h2 className="text-xl lg:text-2xl font-bold tracking-wide mb-4">
                {layer.title}
              </h2>
              <p className="text-gray-400 text-xs leading-relaxed">
                {layer.text}
              </p>
            </motion.div>
          </AnimatePresence>

          {/* layer index */}
          <div className="mt-10 flex flex-col gap-3">
            {LAYERS.map((l, i) => (
              <div key={l.id} className="flex items-center gap-3 text-xs">
                <span
                  className={`h-px transition-all duration-300 ${
                    i === active ? "w-10 bg-white" : "w-4 bg-gray-700"
                  }`}
                />
                <span className={i === active ? "text-white" : "text-gray-700"}>
                  {l.id}
                </span>
                <span
                  className={`hidden sm:inline tracking-widest ${
                    i === active ? "text-gray-300" : "text-gray-700"
                  }`}
                >
                  {l.title}
                </span>
              </div>
            ))}
          </div>

          {/* scroll progress */}
          <div className="absolute bottom-0 left-0 w-full h-px bg-gray-800">
            <motion.div className="h-full bg-white" style={{ width: barWidth }} />
          </div>
        </div>
      </div>
    </section>
  );
}