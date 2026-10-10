import { useEffect, useRef } from "react";
import { geoOrthographic, geoPath, geoGraticule10, geoDistance } from "d3-geo";
import { feature } from "topojson-client";
import landTopo from "world-atlas/land-110m.json";

const land = feature(landTopo, landTopo.objects.land);

// Hub nodes (audit / monitoring centres) and the vendor nodes linked to them
const HUBS = [
  { ll: [-122.4, 37.8], peers: [[-118.2, 34.0], [-112.0, 33.4], [-123.1, 49.3]] },
  { ll: [-46.6, -23.5], peers: [[-58.4, -34.6], [-43.2, -22.9], [-38.5, -12.9], [-60.0, -3.1]] },
  { ll: [-0.1, 51.5], peers: [[2.3, 48.9], [13.4, 52.5], [-3.7, 40.4]] },
  { ll: [77.2, 28.6], peers: [[75.8, 22.7], [72.8, 19.0], [80.3, 13.1]] },
  { ll: [139.7, 35.7], peers: [[126.9, 37.5], [121.5, 31.2]] },
  { ll: [-74.0, 40.7], peers: [[-87.6, 41.9], [-71.0, 42.4]] },
  { ll: [18.4, -33.9], peers: [[28.0, -26.2], [36.8, -1.3]] },
];
// Hub-to-hub backbone links
const BACKBONE = [[0, 5], [5, 2], [2, 3], [3, 4], [1, 5], [2, 6], [0, 4]];

export default function NetworkGlobe() {
  const wrapRef = useRef(null);
  const canvasRef = useRef(null);

  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    const proj = geoOrthographic().clipAngle(90).precision(0.5);
    const path = geoPath(proj, ctx);
    const graticule = geoGraticule10();

    let size = 0, rot = 60, tilt = -20, raf, t = 0;
    let dragging = false, lastX = 0, lastY = 0;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      size = Math.min(wrap.clientWidth, wrap.clientHeight);
      canvas.width = size * dpr;
      canvas.height = size * dpr;
      canvas.style.width = size + "px";
      canvas.style.height = size + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);

    const visible = (ll) => geoDistance(ll, [-rot, -tilt]) < Math.PI / 2 - 0.05;

    const orbit = (cx, cy, rx, ry, angle, alpha) => {
      ctx.beginPath();
      ctx.ellipse(cx, cy, rx, ry, angle, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(255,255,255,${alpha})`;
      ctx.lineWidth = 1;
      ctx.stroke();
    };

    const draw = () => {
      t += 0.016;
      if (!dragging) rot += 0.15;
      const r = size * 0.36;
      const c = size / 2;
      proj.scale(r).translate([c, c]).rotate([rot, tilt, 0]);
      ctx.clearRect(0, 0, size, size);

      // orbit rings
      orbit(c, c * 0.45, r * 0.55, r * 0.14, -0.2, 0.25);
      orbit(c * 0.5, c * 1.55, r * 0.6, r * 0.14, 0.35, 0.25);

      // sphere body
      ctx.beginPath(); path({ type: "Sphere" });
      ctx.fillStyle = "#000"; ctx.fill();
      ctx.strokeStyle = "rgba(255,255,255,0.9)"; ctx.lineWidth = 1.2; ctx.stroke();

      // graticule
      ctx.beginPath(); path(graticule);
      ctx.strokeStyle = "rgba(255,255,255,0.28)"; ctx.lineWidth = 0.7; ctx.stroke();

      // land
      ctx.beginPath(); path(land);
      ctx.fillStyle = "rgba(255,255,255,0.07)"; ctx.fill();
      ctx.strokeStyle = "rgba(255,255,255,0.85)"; ctx.lineWidth = 0.9; ctx.stroke();

      // links (dotted great-circle arcs)
      ctx.setLineDash([2, 4]);
      ctx.lineWidth = 1;
      ctx.strokeStyle = "rgba(255,255,255,0.55)";
      BACKBONE.forEach(([a, b]) => {
        ctx.beginPath();
        path({ type: "LineString", coordinates: [HUBS[a].ll, HUBS[b].ll] });
        ctx.stroke();
      });
      ctx.strokeStyle = "rgba(255,230,80,0.6)";
      HUBS.forEach((h) =>
        h.peers.forEach((p) => {
          ctx.beginPath();
          path({ type: "LineString", coordinates: [h.ll, p] });
          ctx.stroke();
        })
      );
      ctx.setLineDash([]);

      // peer nodes (yellow)
      HUBS.forEach((h) =>
        h.peers.forEach((p) => {
          if (!visible(p)) return;
          const [x, y] = proj(p);
          ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2);
          ctx.fillStyle = "#ffe14d";
          ctx.shadowColor = "#ffe14d"; ctx.shadowBlur = 8;
          ctx.fill(); ctx.shadowBlur = 0;
        })
      );

      // hub nodes (ringed, pulsing)
      HUBS.forEach((h, i) => {
        if (!visible(h.ll)) return;
        const [x, y] = proj(h.ll);
        const pulse = (t * 0.8 + i * 0.3) % 1;
        ctx.beginPath(); ctx.arc(x, y, 8 + pulse * 14, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(255,255,255,${0.5 * (1 - pulse)})`;
        ctx.lineWidth = 1; ctx.stroke();
        ctx.beginPath(); ctx.arc(x, y, 8, 0, Math.PI * 2);
        ctx.fillStyle = "#000"; ctx.fill();
        ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5; ctx.stroke();
        ctx.beginPath(); ctx.moveTo(x - 3, y); ctx.lineTo(x + 3, y);
        ctx.stroke();
      });

      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);

    const down = (e) => { dragging = true; lastX = e.clientX; lastY = e.clientY; canvas.setPointerCapture(e.pointerId); };
    const move = (e) => {
      if (!dragging) return;
      rot += (e.clientX - lastX) * 0.4;
      tilt = Math.max(-60, Math.min(60, tilt - (e.clientY - lastY) * 0.3));
      lastX = e.clientX; lastY = e.clientY;
    };
    const up = () => { dragging = false; };
    canvas.addEventListener("pointerdown", down);
    canvas.addEventListener("pointermove", move);
    canvas.addEventListener("pointerup", up);
    canvas.addEventListener("pointercancel", up);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      canvas.removeEventListener("pointerdown", down);
      canvas.removeEventListener("pointermove", move);
      canvas.removeEventListener("pointerup", up);
      canvas.removeEventListener("pointercancel", up);
    };
  }, []);

  return (
    <div ref={wrapRef} className="w-full h-full flex items-center justify-center">
      <canvas ref={canvasRef} style={{ cursor: "grab", touchAction: "none" }} />
    </div>
  );
}