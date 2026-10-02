/**
 * Shared look-and-feel and camera helpers for every GoCab map, so a pickup
 * pin, the route line and the driver marker read the same on the booking,
 * rider-ride and driver-ride screens.
 */
import { openExternal } from "./openExternal";

export interface LatLng {
  lat: number;
  lng: number;
}

export const BRAND_GREEN = "#1be451";
export const ROUTE_COLOR = BRAND_GREEN;

const EARTH_RADIUS_M = 6371000;
const toRad = (d: number) => (d * Math.PI) / 180;

export function distanceMeters(a: LatLng, b: LatLng): number {
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(h));
}

/** Compass heading in degrees (0 = north) travelling from a to b. */
export function bearingDeg(a: LatLng, b: LatLng): number {
  const y = Math.sin(toRad(b.lng - a.lng)) * Math.cos(toRad(b.lat));
  const x =
    Math.cos(toRad(a.lat)) * Math.sin(toRad(b.lat)) -
    Math.sin(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.cos(toRad(b.lng - a.lng));
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
}

// ── Marker icons ──────────────────────────────────────────────────────────────

export function pickupIcon(): google.maps.Symbol {
  return {
    path: google.maps.SymbolPath.CIRCLE,
    scale: 9,
    fillColor: BRAND_GREEN,
    fillOpacity: 1,
    strokeColor: "#ffffff",
    strokeWeight: 3,
  };
}

export function destinationIcon(): google.maps.Symbol {
  return {
    path: "M -7,-7 L 7,-7 L 7,7 L -7,7 z",
    scale: 1,
    fillColor: "#ffffff",
    fillOpacity: 1,
    strokeColor: "#181c17",
    strokeWeight: 4,
  };
}

/** Arrow that points the way the vehicle is heading. */
export function vehicleIcon(rotation: number): google.maps.Symbol {
  return {
    path: google.maps.SymbolPath.FORWARD_CLOSED_ARROW,
    scale: 6,
    fillColor: BRAND_GREEN,
    fillOpacity: 1,
    strokeColor: "#ffffff",
    strokeWeight: 2,
    rotation,
    anchor: new google.maps.Point(0, 2.5),
  };
}

export function personIcon(): google.maps.Symbol {
  return {
    path: google.maps.SymbolPath.CIRCLE,
    scale: 8,
    fillColor: "#38bdf8",
    fillOpacity: 1,
    strokeColor: "#ffffff",
    strokeWeight: 3,
  };
}

// ── "Pickup" / "Drop-off" pills ───────────────────────────────────────────────

export interface Pill {
  setPosition(pos: LatLng): void;
  remove(): void;
}

/** A small text pill floating above a point on the map. Built lazily because
 * OverlayView only exists once the Maps script has loaded. */
export function createPill(map: google.maps.Map, position: LatLng, text: string): Pill {
  class PillOverlay extends google.maps.OverlayView {
    el: HTMLDivElement;
    pos: LatLng;
    constructor(pos: LatLng, label: string) {
      super();
      this.pos = pos;
      this.el = document.createElement("div");
      this.el.textContent = label;
      Object.assign(this.el.style, {
        position: "absolute",
        transform: "translate(-50%, calc(-100% - 16px))",
        background: "#ffffff",
        color: "#181c17",
        font: "700 12px/1 system-ui, sans-serif",
        padding: "6px 10px",
        borderRadius: "999px",
        boxShadow: "0 2px 8px rgba(0,0,0,.35)",
        whiteSpace: "nowrap",
        pointerEvents: "none",
      });
    }
    onAdd() {
      this.getPanes()?.floatPane.appendChild(this.el);
    }
    draw() {
      const point = this.getProjection()?.fromLatLngToDivPixel(new google.maps.LatLng(this.pos));
      if (!point) return;
      this.el.style.left = `${point.x}px`;
      this.el.style.top = `${point.y}px`;
    }
    onRemove() {
      this.el.remove();
    }
  }
  const overlay = new PillOverlay(position, text);
  overlay.setMap(map);
  return {
    setPosition(pos) {
      overlay.pos = pos;
      overlay.draw();
    },
    remove() {
      overlay.setMap(null);
    },
  };
}

// ── Camera ────────────────────────────────────────────────────────────────────

/** Frames the given points inside the part of the map NOT covered by the
 * bottom sheet, so pins and the route are never hidden underneath it. */
export function frameInVisibleArea(
  map: google.maps.Map,
  points: (LatLng | google.maps.LatLngBounds)[],
  bottomInset: number,
): void {
  if (points.length === 0) return;
  const bounds = new google.maps.LatLngBounds();
  points.forEach((p) => {
    if (p instanceof google.maps.LatLngBounds) bounds.union(p);
    else bounds.extend(p);
  });

  if (bounds.getNorthEast().equals(bounds.getSouthWest())) {
    map.setCenter(bounds.getCenter());
    map.setZoom(17);
    // The camera centre is the middle of the whole map; shift it so the point
    // sits in the middle of the uncovered part instead.
    if (bottomInset > 0) map.panBy(0, bottomInset / 2);
    return;
  }

  map.fitBounds(bounds, { top: 88, left: 48, right: 48, bottom: bottomInset + 56 });
  // fitBounds tends to leave real margin on a phone screen — nudge in a
  // touch closer once it settles, capped so two very close points still
  // don't zoom in to unusable street-corner level.
  google.maps.event.addListenerOnce(map, "idle", () => {
    const z = map.getZoom() ?? 0;
    if (z > 18) map.setZoom(18);
    else if (z < 15) map.setZoom(z + 1);
  });
}

// ── Smooth marker movement ────────────────────────────────────────────────────

const glideFrames = new WeakMap<google.maps.Marker, number>();

/** Slides a marker to its new position instead of teleporting it — location
 * pings only arrive every ~15s, so without this the driver appears to jump. */
export function glideMarker(marker: google.maps.Marker, to: LatLng, durationMs = 1200): void {
  const prev = glideFrames.get(marker);
  if (prev) cancelAnimationFrame(prev);
  const from = marker.getPosition();
  if (!from) {
    marker.setPosition(to);
    return;
  }
  const fromLat = from.lat();
  const fromLng = from.lng();
  const start = performance.now();
  const step = (now: number) => {
    const t = Math.min(1, (now - start) / durationMs);
    const eased = 1 - (1 - t) * (1 - t);
    marker.setPosition({
      lat: fromLat + (to.lat - fromLat) * eased,
      lng: fromLng + (to.lng - fromLng) * eased,
    });
    if (t < 1) glideFrames.set(marker, requestAnimationFrame(step));
    else glideFrames.delete(marker);
  };
  glideFrames.set(marker, requestAnimationFrame(step));
}

// ── Turn-by-turn hand-off ─────────────────────────────────────────────────────

/** Opens Google Maps directions to a point. */
export async function openNavigation(to: LatLng): Promise<void> {
  await openExternal(
    `https://www.google.com/maps/dir/?api=1&destination=${to.lat},${to.lng}&travelmode=driving`,
  );
}
