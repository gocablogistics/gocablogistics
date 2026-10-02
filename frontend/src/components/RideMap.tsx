import { useCallback, useEffect, useRef, useState } from "react";
import { DARK_MAP_STYLE, loadGoogleMaps } from "../api/googleMaps";
import {
  ROUTE_COLOR,
  bearingDeg,
  createPill,
  destinationIcon,
  distanceMeters,
  frameInVisibleArea,
  glideMarker,
  personIcon,
  pickupIcon,
  vehicleIcon,
  type LatLng,
  type Pill,
} from "../lib/mapVisuals";

interface RideMapProps {
  pickup: LatLng | null;
  destination: LatLng | null;
  /** The live position of whoever is moving — the driver's arrow on the
   * rider's map, or the driver's own arrow on the driver's map. */
  movingMarker: LatLng | null;
  /** "vehicle" is a heading-aware arrow; "person" is a plain dot. */
  movingMarkerKind?: "vehicle" | "person";
  /** Matches the app's dark theme instead of the default light map. */
  dark?: boolean;
  /** Fills its container instead of the fixed 280px card height. */
  fullScreen?: boolean;
  /** Draws the live driving route from routeOrigin to routeDestination. It is
   * only re-requested once the origin has moved a meaningful distance, so a
   * moving driver doesn't cost a paid Directions call on every ping. */
  routeOrigin?: LatLng | null;
  routeDestination?: LatLng | null;
  /** Height in px of the sheet covering the bottom of the map. Pins and the
   * route are framed inside the remaining visible area. */
  bottomInset?: number;
  /** Other open ride requests to show as pins (the driver's home map). */
  requestPins?: LatLng[];
}

const LAGOS_FALLBACK: LatLng = { lat: 6.5244, lng: 3.3792 };
// The route is only re-requested after the origin moves this far.
const REROUTE_METERS = 50;

export default function RideMap({
  pickup,
  destination,
  movingMarker,
  movingMarkerKind = "vehicle",
  dark = false,
  fullScreen = false,
  routeOrigin = null,
  routeDestination = null,
  bottomInset = 0,
  requestPins,
}: RideMapProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstance = useRef<google.maps.Map | null>(null);
  const pickupMarker = useRef<google.maps.Marker | null>(null);
  const destMarker = useRef<google.maps.Marker | null>(null);
  const pickupPill = useRef<Pill | null>(null);
  const destPill = useRef<Pill | null>(null);
  const movingMarkerRef = useRef<google.maps.Marker | null>(null);
  const requestMarkers = useRef<google.maps.Marker[]>([]);
  const lastMovingPos = useRef<LatLng | null>(null);
  const headingRef = useRef(0);
  const directionsRendererRef = useRef<google.maps.DirectionsRenderer | null>(null);
  const fallbackLine = useRef<google.maps.Polyline | null>(null);
  const lastRoute = useRef<{ origin: LatLng; dest: LatLng } | null>(null);
  const routeRequestId = useRef(0);
  const routeBounds = useRef<google.maps.LatLngBounds | null>(null);
  // Once the user pans/zooms themselves the camera stops chasing the driver
  // until they tap the recenter button.
  const userMovedRef = useRef(false);
  const [userMoved, setUserMoved] = useState(false);
  const [status, setStatus] = useState<"loading" | "ready" | "failed">("loading");
  const ready = status === "ready";

  const latest = useRef({ pickup, destination, movingMarker, bottomInset, requestPins });
  useEffect(() => {
    latest.current = { pickup, destination, movingMarker, bottomInset, requestPins };
  });
  const requestPinsKey = (requestPins ?? []).map((p) => `${p.lat},${p.lng}`).join("|");

  const load = useCallback(() => {
    setStatus("loading");
    loadGoogleMaps().then((ok) => setStatus(ok ? "ready" : "failed"));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const fit = useCallback(() => {
    const map = mapInstance.current;
    if (!map) return;
    const { pickup: p, destination: d, movingMarker: m, bottomInset: inset, requestPins: pins } = latest.current;
    const targets: (LatLng | google.maps.LatLngBounds)[] = [p, d, m, ...(pins ?? [])].filter(Boolean) as LatLng[];
    if (routeBounds.current) targets.push(routeBounds.current);
    frameInVisibleArea(map, targets, inset);
  }, []);

  const markUserMoved = useCallback(() => {
    userMovedRef.current = true;
    setUserMoved(true);
  }, []);

  // Create the map once, sized to the div's actual mount.
  useEffect(() => {
    if (!ready || !mapRef.current || mapInstance.current) return;
    const el = mapRef.current;
    const map = new google.maps.Map(el, {
      center: pickup || destination || movingMarker || LAGOS_FALLBACK,
      // Street-level, not city-level — 13 read as too zoomed-out on a real
      // phone screen; a rider/driver cares about their immediate area, not
      // the whole city.
      zoom: 16,
      styles: dark ? DARK_MAP_STYLE : undefined,
      disableDefaultUI: true,
      // One finger pans, two pinch — no "use two fingers" page-scroll fight.
      gestureHandling: "greedy",
      // Tapping a shop/landmark otherwise pops Google's own info window.
      clickableIcons: false,
      keyboardShortcuts: false,
    });
    mapInstance.current = map;
    directionsRendererRef.current = new google.maps.DirectionsRenderer({
      map,
      suppressMarkers: true,
      // We frame the camera ourselves (inside the visible area, above the sheet).
      preserveViewport: true,
      polylineOptions: { strokeColor: ROUTE_COLOR, strokeWeight: 5, strokeOpacity: 0.95 },
    });
    map.addListener("dragstart", markUserMoved);
    const onTouch = (e: TouchEvent) => {
      if (e.touches.length > 1) markUserMoved();
    };
    el.addEventListener("touchstart", onTouch, { passive: true });
    el.addEventListener("wheel", markUserMoved, { passive: true });
    return () => {
      el.removeEventListener("touchstart", onTouch);
      el.removeEventListener("wheel", markUserMoved);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  useEffect(
    () => () => {
      pickupPill.current?.remove();
      destPill.current?.remove();
      requestMarkers.current.forEach((m) => m.setMap(null));
    },
    [],
  );

  // New pickup/destination means a new trip framing — hand the camera back.
  useEffect(() => {
    userMovedRef.current = false;
    setUserMoved(false);
  }, [pickup?.lat, pickup?.lng, destination?.lat, destination?.lng]);

  useEffect(() => {
    const map = mapInstance.current;
    if (!map) return;
    if (!pickup) {
      pickupMarker.current?.setMap(null);
      pickupMarker.current = null;
      pickupPill.current?.remove();
      pickupPill.current = null;
      return;
    }
    if (!pickupMarker.current) {
      pickupMarker.current = new google.maps.Marker({
        position: pickup, map, icon: pickupIcon(), title: "Pickup", zIndex: 2, clickable: false,
      });
      pickupPill.current = createPill(map, pickup, "Pickup");
    } else {
      pickupMarker.current.setPosition(pickup);
      pickupPill.current?.setPosition(pickup);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, pickup?.lat, pickup?.lng]);

  useEffect(() => {
    const map = mapInstance.current;
    if (!map) return;
    if (!destination) {
      destMarker.current?.setMap(null);
      destMarker.current = null;
      destPill.current?.remove();
      destPill.current = null;
      return;
    }
    if (!destMarker.current) {
      destMarker.current = new google.maps.Marker({
        position: destination, map, icon: destinationIcon(), title: "Drop-off", zIndex: 2, clickable: false,
      });
      destPill.current = createPill(map, destination, "Drop-off");
    } else {
      destMarker.current.setPosition(destination);
      destPill.current?.setPosition(destination);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, destination?.lat, destination?.lng]);

  useEffect(() => {
    const map = mapInstance.current;
    if (!map) return;
    if (!movingMarker) {
      movingMarkerRef.current?.setMap(null);
      movingMarkerRef.current = null;
      lastMovingPos.current = null;
      return;
    }
    // Point the arrow along the direction of travel; hold the last heading
    // when the driver is (nearly) stationary so it doesn't spin from GPS noise.
    const prev = lastMovingPos.current;
    if (prev && distanceMeters(prev, movingMarker) > 5) {
      headingRef.current = bearingDeg(prev, movingMarker);
    }
    lastMovingPos.current = movingMarker;
    const icon = movingMarkerKind === "vehicle" ? vehicleIcon(headingRef.current) : personIcon();
    if (!movingMarkerRef.current) {
      movingMarkerRef.current = new google.maps.Marker({
        position: movingMarker, map, icon, zIndex: 3, clickable: false,
      });
    } else {
      movingMarkerRef.current.setIcon(icon);
      glideMarker(movingMarkerRef.current, movingMarker);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, movingMarker?.lat, movingMarker?.lng, movingMarkerKind]);

  // Open requests around the driver.
  useEffect(() => {
    const map = mapInstance.current;
    if (!map) return;
    requestMarkers.current.forEach((m) => m.setMap(null));
    requestMarkers.current = (latest.current.requestPins ?? []).map(
      (position) =>
        new google.maps.Marker({
          position,
          map,
          zIndex: 1,
          clickable: false,
          icon: {
            path: google.maps.SymbolPath.CIRCLE,
            scale: 8,
            fillColor: "#fbbf24",
            fillOpacity: 1,
            strokeColor: "#ffffff",
            strokeWeight: 3,
          },
        }),
    );
  }, [ready, requestPinsKey]);

  // Live route. Throttled: a fresh Directions request only when the
  // destination changed or the origin moved REROUTE_METERS.
  useEffect(() => {
    const renderer = directionsRendererRef.current;
    const map = mapInstance.current;
    if (!renderer || !map) return;

    if (!routeOrigin || !routeDestination) {
      routeRequestId.current++;
      lastRoute.current = null;
      routeBounds.current = null;
      fallbackLine.current?.setMap(null);
      renderer.setDirections({ routes: [] } as unknown as google.maps.DirectionsResult);
      return;
    }

    const last = lastRoute.current;
    if (
      last &&
      distanceMeters(last.dest, routeDestination) < 1 &&
      distanceMeters(last.origin, routeOrigin) < REROUTE_METERS
    ) {
      return;
    }
    lastRoute.current = { origin: routeOrigin, dest: routeDestination };
    const requestId = ++routeRequestId.current;

    new google.maps.DirectionsService().route(
      { origin: routeOrigin, destination: routeDestination, travelMode: google.maps.TravelMode.DRIVING },
      (result, dirStatus) => {
        if (requestId !== routeRequestId.current) return; // superseded
        if (dirStatus === "OK" && result) {
          fallbackLine.current?.setMap(null);
          renderer.setDirections(result);
          routeBounds.current = result.routes[0]?.bounds ?? null;
        } else {
          // No road route (quota, no road link…): still show where to go
          // with a straight line, and try again on the next move.
          renderer.setDirections({ routes: [] } as unknown as google.maps.DirectionsResult);
          routeBounds.current = null;
          lastRoute.current = null;
          fallbackLine.current?.setMap(null);
          fallbackLine.current = new google.maps.Polyline({
            map,
            path: [routeOrigin, routeDestination],
            strokeColor: ROUTE_COLOR,
            strokeOpacity: 0.6,
            strokeWeight: 4,
          });
        }
        if (!userMovedRef.current) fit();
      },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, routeOrigin?.lat, routeOrigin?.lng, routeDestination?.lat, routeDestination?.lng]);

  // Frame everything inside the visible area — again when the sheet grows or
  // shrinks — unless the user has taken over the camera.
  useEffect(() => {
    if (!ready || userMovedRef.current) return;
    fit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, pickup?.lat, pickup?.lng, destination?.lat, destination?.lng, movingMarker?.lat, movingMarker?.lng, bottomInset, requestPinsKey]);

  return (
    <div
      style={
        fullScreen
          ? { position: "absolute", inset: 0, background: dark ? "#20241f" : "#eee" }
          : { position: "relative", width: "100%", height: 280, borderRadius: 8, marginBottom: 12, background: "#eee", overflow: "hidden" }
      }
    >
      <div ref={mapRef} style={{ position: "absolute", inset: 0 }} />

      {status === "failed" && (
        <div className="absolute inset-x-0 top-24 z-[5] flex justify-center px-6">
          <div className="rounded-2xl bg-[#181c17]/95 border border-white/10 px-4 py-3 text-center">
            <p className="text-white text-sm font-semibold">Map couldn't load</p>
            <p className="text-slate-400 text-xs mt-0.5">Check your connection. Your trip still works.</p>
            <button onClick={load} className="mt-2 text-[#1be451] text-sm font-bold">
              Try again
            </button>
          </div>
        </div>
      )}

      {userMoved && (
        <button
          onClick={() => {
            userMovedRef.current = false;
            setUserMoved(false);
            fit();
          }}
          aria-label="Recenter map"
          className="absolute right-4 z-[5] w-11 h-11 rounded-full bg-[#181c17] border border-white/15 text-[#1be451] shadow-lg flex items-center justify-center"
          style={{ bottom: bottomInset + 16 }}
        >
          <i className="fa-solid fa-location-crosshairs" />
        </button>
      )}
    </div>
  );
}
