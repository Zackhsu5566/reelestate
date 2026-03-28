import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { useEffect, useRef, useState } from "react";
import {
  continueRender,
  delayRender,
  Easing,
  interpolate,
  useCurrentFrame,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/NotoSansTC";
import type { POI } from "../types";

const { fontFamily } = loadFont("normal", {
  weights: ["400", "700"],
});

const MAPBOX_STYLE_ID = "beingzackhsu/cmmrh4sis008501rndfa72u92";

// Exported for MapScene timing
export const FLY_DURATION_FRAMES = 0; // no zoom animation — start at final position
export const POI_START_FRAME = 15; // POIs appear after brief settle (~0.5s)

const POI_STAGGER = 60; // 2s between each POI
const LINE_DRAW_FRAMES = 20; // ~0.67s connector line animation
const DOT_ANIM_FRAMES = 8; // ~0.27s pin dot pop-in

// Left-side label layout
const LABEL_LEFT = 40;
const LABEL_TOP = 280;
const LABEL_GAP = 110;
const LABEL_CARD_WIDTH = 260;
const LABEL_CARD_HEIGHT = 72;

const CATEGORY_COLORS: Record<POI["category"], string> = {
  mrt: "#00B4D8",
  supermarket: "#FFD700",
  park: "#4CAF50",
  school: "#FF9800",
  hospital: "#E91E63",
  other: "#9E9E9E",
};

type ScreenPOI = POI & { x: number; y: number };

type Props = {
  lat: number;
  lng: number;
  token: string;
  pois?: POI[];
};

const CAMERA = { zoom: 13, pitch: 30, bearing: 0 };

function cameraAtFrame(_frame: number) {
  return CAMERA;
}

export const MapboxFlyIn: React.FC<Props> = ({
  lat,
  lng,
  token,
  pois = [],
}) => {
  const frame = useCurrentFrame();
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [screenPois, setScreenPois] = useState<ScreenPOI[]>([]);

  const [initHandle] = useState(() => delayRender("Mapbox init"));

  useEffect(() => {
    if (!containerRef.current) return;

    mapboxgl.accessToken = token;

    const originalError = console.error;
    console.error = (...args: unknown[]) => {
      if (String(args[0] ?? "").includes("Could not load models")) return;
      originalError.apply(console, args);
    };

    const initial = cameraAtFrame(0);
    const styleUrl = `https://api.mapbox.com/styles/v1/${MAPBOX_STYLE_ID}?access_token=${token}&fresh=true`;

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: styleUrl,
      center: [lng, lat],
      zoom: initial.zoom,
      pitch: initial.pitch,
      bearing: initial.bearing,
      interactive: false,
      attributionControl: false,
      fadeDuration: 0,
    });

    map.once("idle", () => {
      const style = map.getStyle();
      if (style?.layers) {
        for (const layer of style.layers) {
          if (layer.type === ("model" as unknown as mapboxgl.Layer["type"])) {
            try {
              map.removeLayer(layer.id);
            } catch {}
          }
        }
      }
      // Pin marker — house emoji
      const el = document.createElement("div");
      el.style.cssText = `
        font-size: 36px; line-height: 1;
        filter: drop-shadow(0 2px 6px rgba(0,0,0,0.6));
      `;
      el.textContent = "🏠";
      new mapboxgl.Marker({ element: el }).setLngLat([lng, lat]).addTo(map);

      mapRef.current = map;
      setMapReady(true);
      continueRender(initHandle);
    });

    return () => {
      console.error = originalError;
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    const handle = delayRender("Mapbox frame idle");

    const { zoom, pitch, bearing } = cameraAtFrame(frame);

    map.jumpTo({ center: [lng, lat], zoom, pitch, bearing });

    // Project POIs to screen coordinates after camera settles
    if (pois.length > 0 && frame >= FLY_DURATION_FRAMES) {
      const projected: ScreenPOI[] = [];
      for (const poi of pois) {
        if (poi.lat == null || poi.lng == null) continue;
        const pt = map.project([poi.lng, poi.lat]);
        projected.push({ ...poi, x: pt.x, y: pt.y });
      }
      setScreenPois(projected);
    }

    map.once("idle", () => continueRender(handle));

    return () => continueRender(handle);
  }, [frame, mapReady]);

  // All labels fade in together at POI_START_FRAME
  const labelsOpacity = pois.length > 0
    ? interpolate(frame, [POI_START_FRAME, POI_START_FRAME + 15], [0, 1], {
        extrapolateLeft: "clamp", extrapolateRight: "clamp",
      })
    : 0;

  // Build a lookup: POI index → screen coordinates
  const screenByIndex = new Map<number, ScreenPOI>();
  for (const sp of screenPois) {
    const idx = pois.findIndex((p) => p.name === sp.name && p.category === sp.category);
    if (idx >= 0) screenByIndex.set(idx, sp);
  }

  return (
    <>
      <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />

      {/* Left-side POI label cards */}
      {pois.map((poi, i) => {
        const color = CATEGORY_COLORS[poi.category] || CATEGORY_COLORS.other;
        const delay = POI_START_FRAME + i * POI_STAGGER;
        const isActive = frame >= delay;

        // Dim initially, brighten when connector starts
        const brightness = isActive
          ? interpolate(frame, [delay, delay + 10], [0.5, 1], {
              extrapolateLeft: "clamp", extrapolateRight: "clamp",
            })
          : 0.5;

        return (
          <div
            key={`label-${i}`}
            style={{
              position: "absolute",
              left: LABEL_LEFT,
              top: LABEL_TOP + i * LABEL_GAP,
              width: LABEL_CARD_WIDTH,
              height: LABEL_CARD_HEIGHT,
              opacity: labelsOpacity * brightness,
              background: "rgba(0,0,0,0.75)",
              backdropFilter: "blur(6px)",
              borderRadius: 12,
              padding: "10px 16px",
              display: "flex",
              alignItems: "center",
              gap: 12,
              border: `2px solid ${isActive ? color : "rgba(255,255,255,0.2)"}`,
              pointerEvents: "none" as const,
              fontFamily,
            }}
          >
            {/* Color dot */}
            <div
              style={{
                width: 14,
                height: 14,
                borderRadius: "50%",
                background: color,
                flexShrink: 0,
              }}
            />
            <div>
              <div style={{ color: "#fff", fontSize: 22, fontWeight: 700, whiteSpace: "nowrap" }}>
                {poi.name}
              </div>
              <div style={{ color: "rgba(255,255,255,0.6)", fontSize: 16, fontWeight: 400 }}>
                {poi.distance}
              </div>
            </div>
          </div>
        );
      })}

      {/* SVG connector lines + pin dots */}
      <svg
        style={{ position: "absolute", inset: 0, pointerEvents: "none" }}
        width={1080}
        height={1920}
        viewBox="0 0 1080 1920"
      >
        {pois.map((poi, i) => {
          const sp = screenByIndex.get(i);
          if (!sp) return null;

          const color = CATEGORY_COLORS[poi.category] || CATEGORY_COLORS.other;
          const delay = POI_START_FRAME + i * POI_STAGGER;

          // Connector line: from right edge of label card → map coordinate
          const fromX = LABEL_LEFT + LABEL_CARD_WIDTH;
          const fromY = LABEL_TOP + i * LABEL_GAP + LABEL_CARD_HEIGHT / 2;
          const toX = sp.x;
          const toY = sp.y;

          const dx = toX - fromX;
          const dy = toY - fromY;
          const length = Math.sqrt(dx * dx + dy * dy);

          const lineProgress = interpolate(
            frame,
            [delay, delay + LINE_DRAW_FRAMES],
            [0, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) },
          );

          // Pin dot pops in after line finishes
          const dotDelay = delay + LINE_DRAW_FRAMES;
          const dotScale = interpolate(
            frame,
            [dotDelay, dotDelay + DOT_ANIM_FRAMES],
            [0, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) },
          );

          return (
            <g key={`connector-${i}`}>
              {lineProgress > 0 && (
                <line
                  x1={fromX}
                  y1={fromY}
                  x2={toX}
                  y2={toY}
                  stroke={color}
                  strokeWidth={2}
                  strokeDasharray={length}
                  strokeDashoffset={length * (1 - lineProgress)}
                  opacity={0.8}
                />
              )}
              {dotScale > 0 && (
                <>
                  <circle cx={toX} cy={toY} r={12 * dotScale} fill={color} opacity={0.3} />
                  <circle cx={toX} cy={toY} r={8 * dotScale} fill={color} stroke="#fff" strokeWidth={2} />
                </>
              )}
            </g>
          );
        })}
      </svg>
    </>
  );
};
