import { useEffect, useRef, useState, type FormEvent } from "react";
import { estimateFare, requestRide, type FareEstimateOut, type VehicleType } from "../api/rides";
import { ApiError } from "../api/http";
import { loadGoogleMaps } from "../api/googleMaps";
import { getFeatureFlags } from "../api/flags";
import { useAutoDismiss } from "../hooks/useAutoDismiss";
import { getCurrentPosition } from "../lib/geolocation";
import NotificationBell from "./NotificationBell";
import NavDrawer from "./NavDrawer";
import RideMap from "./RideMap";
import { useElementHeight } from "../hooks/useElementHeight";

interface LatLng {
  lat: number;
  lng: number;
}

// A pedal bicycle can't carry what a motorbike can — same "What GoCab can
// carry" promise shown regardless of which vehicle a rider picked until
// now, which meant a Bicycle courier could get handed a package sized for
// a Bike. Kept separate from fare_pricing.py's VEHICLE_RATES since these
// are physical limits, not a pricing concern.
const PACKAGE_LIMITS: Record<VehicleType, { size: string; weight: string; value: string }> = {
  Bike: { size: "60×40×30cm", weight: "15kg", value: "₦50,000" },
  Bicycle: { size: "40×30×20cm", weight: "8kg", value: "₦30,000" },
};

interface BookingScreenProps {
  accessToken: string | null;
  onBooked: (rideId: number) => void;
  onNeedsAuth: (pending: { currentLocation: string; destination: string }) => void;
  onLogout: () => void;
}

export default function BookingScreen({
  accessToken,
  onBooked,
  onNeedsAuth,
  onLogout,
}: BookingScreenProps) {
  const [currentLocation, setCurrentLocation] = useState("");
  const [destination, setDestination] = useState("");
  const [recipientPhone, setRecipientPhone] = useState("");
  const [paymentMethod, setPaymentMethod] = useState<"online" | "cash">("online");
  const [vehicleType, setVehicleType] = useState<VehicleType>("Bike");
  const [confirming, setConfirming] = useState(false);
  const [pickupCoords, setPickupCoords] = useState<LatLng | null>(null);
  const [destCoords, setDestCoords] = useState<LatLng | null>(null);
  const [estimate, setEstimate] = useState<FareEstimateOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [mapsReady, setMapsReady] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [locating, setLocating] = useState(false);
  const [locateError, setLocateError] = useState<string | null>(null);
  const [cashEnabled, setCashEnabled] = useState(false);

  useAutoDismiss(error, () => setError(null));
  useAutoDismiss(locateError, () => setLocateError(null));

  useEffect(() => {
    getFeatureFlags().then((flags) => setCashEnabled(flags.cash_payments_enabled));
  }, []);

  const [pickupPredictions, setPickupPredictions] = useState<google.maps.places.AutocompletePrediction[]>([]);
  const [destPredictions, setDestPredictions] = useState<google.maps.places.AutocompletePrediction[]>([]);
  const [pickupDropdownOpen, setPickupDropdownOpen] = useState(false);
  const [destDropdownOpen, setDestDropdownOpen] = useState(false);

  const [sheetRef, sheetHeight] = useElementHeight<HTMLFormElement>();
  // Custom-rendered dropdown, not Google's auto-injected .pac-container —
  // that widget appends its suggestion list directly to <body> and, on a
  // full-screen map layout like this one, the map's own internal panes can
  // end up stacked above it. The dropdown would show but clicks landed on
  // the map underneath instead of the suggestion. Rendering the list as
  // normal React elements sidesteps that entirely: there's nothing outside
  // React's control to fight over stacking with.
  const autocompleteServiceRef = useRef<google.maps.places.AutocompleteService | null>(null);
  const placesServiceRef = useRef<google.maps.places.PlacesService | null>(null);
  const pickupDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const destDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    loadGoogleMaps().then(setMapsReady);
  }, []);

  // Places services for the custom dropdown — created once, reused for
  // every keystroke.
  useEffect(() => {
    if (!mapsReady || !window.google?.maps?.places) return;
    if (!autocompleteServiceRef.current) {
      autocompleteServiceRef.current = new window.google.maps.places.AutocompleteService();
    }
    if (!placesServiceRef.current) {
      placesServiceRef.current = new window.google.maps.places.PlacesService(document.createElement("div"));
    }
  }, [mapsReady]);

  function fetchPredictions(
    input: string,
    setPredictions: (p: google.maps.places.AutocompletePrediction[]) => void,
  ) {
    if (!autocompleteServiceRef.current || !input.trim()) {
      setPredictions([]);
      return;
    }
    autocompleteServiceRef.current.getPlacePredictions(
      // No "types" filter: restricting to "address" made shops, landmarks and
      // whole areas (Shoprite Ikeja, Oworonshoki) return nothing at all.
      { input, componentRestrictions: { country: "ng" } },
      (predictions, status) => {
        if (status === google.maps.places.PlacesServiceStatus.OK && predictions) {
          setPredictions(predictions);
        } else {
          setPredictions([]);
        }
      },
    );
  }

  function handlePickupChange(value: string) {
    setCurrentLocation(value);
    setPickupCoords(null);
    setPickupDropdownOpen(true);
    // A previous estimate no longer reflects this address — without this,
    // the "Send it — ₦X" button keeps showing the old fare/ETA, and
    // submitting would book the NEW addresses under the OLD displayed price.
    setEstimate(null);
    if (pickupDebounceRef.current) clearTimeout(pickupDebounceRef.current);
    pickupDebounceRef.current = setTimeout(() => fetchPredictions(value, setPickupPredictions), 200);
  }

  function handleDestChange(value: string) {
    setDestination(value);
    setDestCoords(null);
    setDestDropdownOpen(true);
    setEstimate(null);
    if (destDebounceRef.current) clearTimeout(destDebounceRef.current);
    destDebounceRef.current = setTimeout(() => fetchPredictions(value, setDestPredictions), 200);
  }

  function selectPrediction(prediction: google.maps.places.AutocompletePrediction, isPickup: boolean) {
    if (!placesServiceRef.current) return;
    placesServiceRef.current.getDetails(
      { placeId: prediction.place_id, fields: ["formatted_address", "geometry"] },
      (place, status) => {
        // For a shop/landmark, keep Google's "Name, street, area" description —
        // formatted_address would drop the name the rider actually picked, and
        // the driver needs it. Plain street addresses keep the canonical form.
        const isNamedPlace = prediction.types?.some(
          (t) => t === "establishment" || t === "point_of_interest",
        );
        const address =
          !isNamedPlace &&
          status === google.maps.places.PlacesServiceStatus.OK &&
          place?.formatted_address
            ? place.formatted_address
            : prediction.description;
        const loc = place?.geometry?.location;
        setEstimate(null);
        if (isPickup) {
          setCurrentLocation(address);
          if (loc) setPickupCoords({ lat: loc.lat(), lng: loc.lng() });
          setPickupPredictions([]);
          setPickupDropdownOpen(false);
        } else {
          setDestination(address);
          if (loc) setDestCoords({ lat: loc.lat(), lng: loc.lng() });
          setDestPredictions([]);
          setDestDropdownOpen(false);
        }
      },
    );
  }

  function handleUseCurrentLocation() {
    setLocating(true);
    setLocateError(null);
    getCurrentPosition(
      (position) => {
        const coords = { lat: position.latitude, lng: position.longitude };
        setPickupCoords(coords);
        setPickupPredictions([]);
        setPickupDropdownOpen(false);
        setEstimate(null);
        if (window.google?.maps) {
          new google.maps.Geocoder().geocode({ location: coords }, (results, status) => {
            setLocating(false);
            if (status === "OK" && results?.[0]) {
              setCurrentLocation(results[0].formatted_address);
            } else {
              setCurrentLocation("Current location");
            }
          });
        } else {
          setLocating(false);
          setCurrentLocation("Current location");
        }
      },
      () => {
        setLocating(false);
        setLocateError("Couldn't get your location. Check location permissions.");
      },
    );
  }

  async function handleGetEstimate(e: FormEvent) {
    e.preventDefault();
    setConfirming(false);
    setError(null);
    setEstimate(null);
    if (!currentLocation.trim() || !destination.trim()) {
      setError("Enter both a pickup point and a drop-off point.");
      return;
    }
    if (recipientPhone.length !== 11) {
      setError("Recipient phone number must be 11 digits.");
      return;
    }
    setLoading(true);
    try {
      const result = await estimateFare(currentLocation.trim(), destination.trim(), vehicleType);
      setEstimate(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not get an estimate.");
    } finally {
      setLoading(false);
    }
  }

  async function handleSendIt() {
    setError(null);
    if (recipientPhone.length !== 11) {
      setError("Recipient phone number must be 11 digits.");
      return;
    }
    if (!accessToken) {
      onNeedsAuth({ currentLocation, destination });
      return;
    }
    setLoading(true);
    try {
      const ride = await requestRide(currentLocation, destination, accessToken, {
        recipientPhoneNumber: recipientPhone,
        paymentMethod,
        fareQuote: estimate?.quote,
        vehicleType,
      });
      onBooked(ride.ride_id);
    } catch (err) {
      // 409 = the price moved since the estimate: drop the stale figure so
      // the rider re-estimates instead of confirming a number that's gone.
      if (err instanceof ApiError && err.status === 409 && !/active ride/i.test(err.message)) {
        setEstimate(null);
      }
      setError(err instanceof ApiError ? err.message : "Could not send your request.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 flex flex-col bg-[#20241f]">
      <RideMap
        fullScreen
        dark
        pickup={pickupCoords}
        destination={destCoords}
        movingMarker={null}
        routeOrigin={pickupCoords}
        routeDestination={destCoords}
        bottomInset={sheetHeight}
      />

      <button
        onClick={() => setMenuOpen(true)}
        className="absolute top-4 left-4 z-10 bg-black/40 rounded-full w-10 h-10 flex items-center justify-center text-white"
        aria-label="Menu"
      >
        <i className="fa-solid fa-bars" />
      </button>

      {accessToken && (
        <div className="absolute top-4 right-4 z-10 bg-black/40 rounded-full p-1.5 text-white">
          <NotificationBell accessToken={accessToken} />
        </div>
      )}

      <NavDrawer open={menuOpen} onClose={() => setMenuOpen(false)} role="rider" onLogout={onLogout} />

      <form
        ref={sheetRef}
        onSubmit={handleGetEstimate}
        className="relative mt-auto rounded-t-3xl bg-[#181c17] text-slate-100 flex flex-col max-h-[58dvh]"
      >
        {/* The fields scroll; the action button below has its own pinned area, so
            it can never end up "below the fold" on a short phone screen. */}
        <div className="min-h-0 overflow-y-auto overscroll-contain px-8 pt-6 pb-3 flex flex-col gap-4">
        <h2 className="text-white text-xl font-extrabold">Order details</h2>

        <div>
          <div className="flex items-center justify-between mb-2">
            <p className="text-white font-semibold">Where to pick up</p>
            <button
              type="button"
              onClick={handleUseCurrentLocation}
              disabled={locating}
              className="text-[#1be451] text-xs font-semibold flex items-center gap-1 disabled:opacity-50"
            >
              <i className="fa-solid fa-location-crosshairs" />
              {locating ? "Locating…" : "Use current location"}
            </button>
          </div>
          <input
            required
            value={currentLocation}
            onChange={(e) => handlePickupChange(e.target.value)}
            onFocus={() => setPickupDropdownOpen(pickupPredictions.length > 0)}
            onBlur={() => setTimeout(() => setPickupDropdownOpen(false), 150)}
            placeholder="Street, building"
            className="w-full rounded-full px-4 py-3 bg-white/10 border border-white/20 text-white placeholder:text-slate-400"
          />
          {locateError && <p className="text-red-400 text-xs mt-1">{locateError}</p>}
          {pickupDropdownOpen && pickupPredictions.length > 0 && (
            <div className="mt-1 rounded-2xl bg-[#20241f] border border-white/20 overflow-hidden max-h-56 overflow-y-auto">
              {pickupPredictions.map((p) => (
                <div
                  key={p.place_id}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    selectPrediction(p, true);
                  }}
                  className="px-4 py-3 text-white text-sm hover:bg-white/10 cursor-pointer border-b border-white/10 last:border-b-0"
                >
                  {p.description}
                </div>
              ))}
            </div>
          )}
        </div>

        <div>
          <p className="text-white font-semibold mb-2">Where to deliver</p>
          <input
            required
            value={destination}
            onChange={(e) => handleDestChange(e.target.value)}
            onFocus={() => setDestDropdownOpen(destPredictions.length > 0)}
            onBlur={() => setTimeout(() => setDestDropdownOpen(false), 150)}
            placeholder="Street, building"
            className="w-full rounded-full px-4 py-3 bg-white/10 border border-white/20 text-white placeholder:text-slate-400"
          />
          {destDropdownOpen && destPredictions.length > 0 && (
            <div className="mt-1 rounded-2xl bg-[#20241f] border border-white/20 overflow-hidden max-h-56 overflow-y-auto">
              {destPredictions.map((p) => (
                <div
                  key={p.place_id}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    selectPrediction(p, false);
                  }}
                  className="px-4 py-3 text-white text-sm hover:bg-white/10 cursor-pointer border-b border-white/10 last:border-b-0"
                >
                  {p.description}
                </div>
              ))}
            </div>
          )}
        </div>

        <div>
          <p className="text-white font-semibold mb-2">Recipient phone number</p>
          <div className="flex items-center rounded-full bg-white/10 border border-white/20 overflow-hidden">
            <span className="pl-4 pr-2 text-lg leading-none">🇳🇬</span>
            <input
              required
              value={recipientPhone}
              onChange={(e) => setRecipientPhone(e.target.value.replace(/\D/g, "").slice(0, 11))}
              inputMode="numeric"
              maxLength={11}
              placeholder="Who's receiving this?"
              className="flex-1 min-w-0 py-3 pr-4 bg-transparent text-white placeholder:text-slate-400 outline-none"
            />
          </div>
        </div>

        <div>
          <p className="text-white font-semibold mb-2">Vehicle type</p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => {
                setVehicleType("Bike");
                setEstimate(null);
              }}
              className={`flex-1 py-3 rounded-full font-semibold border ${
                vehicleType === "Bike"
                  ? "bg-[#1be451] text-neutral-900 border-[#1be451]"
                  : "bg-white/10 text-white border-white/20"
              }`}
            >
              <i className="fa-solid fa-motorcycle mr-2" />
              Bike
            </button>
            <button
              type="button"
              onClick={() => {
                setVehicleType("Bicycle");
                setEstimate(null);
              }}
              className={`flex-1 py-3 rounded-full font-semibold border ${
                vehicleType === "Bicycle"
                  ? "bg-[#1be451] text-neutral-900 border-[#1be451]"
                  : "bg-white/10 text-white border-white/20"
              }`}
            >
              <i className="fa-solid fa-bicycle mr-2" />
              Bicycle
            </button>
          </div>
          <p className="text-slate-400 text-xs mt-1.5">
            Bicycle costs less, but takes a bit longer for longer trips.
          </p>
        </div>

        {cashEnabled ? (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setPaymentMethod("cash")}
              className={`flex-1 py-3 rounded-full font-semibold border ${
                paymentMethod === "cash"
                  ? "bg-[#1be451] text-neutral-900 border-[#1be451]"
                  : "bg-white/10 text-white border-white/20"
              }`}
            >
              <i className="fa-solid fa-money-bill-wave mr-2" />
              Cash
            </button>
            <button
              type="button"
              onClick={() => setPaymentMethod("online")}
              className={`flex-1 py-3 rounded-full font-semibold border ${
                paymentMethod === "online"
                  ? "bg-[#1be451] text-neutral-900 border-[#1be451]"
                  : "bg-white/10 text-white border-white/20"
              }`}
            >
              <i className="fa-solid fa-credit-card mr-2" />
              Card
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-3 rounded-2xl bg-white/5 border border-white/10 px-4 py-3">
            <i className="fa-solid fa-credit-card text-[#1be451]" />
            <span className="flex-1 text-sm text-slate-200">Pay by card</span>
          </div>
        )}

        <div className="rounded-2xl bg-white/5 border border-white/10 px-4 py-3">
          <p className="text-slate-400 text-xs leading-relaxed">
            <span className="text-white font-semibold">What GoCab can carry: </span>
            anything that fits in a backpack, up to {PACKAGE_LIMITS[vehicleType].size},{" "}
            {PACKAGE_LIMITS[vehicleType].weight}, and worth up to {PACKAGE_LIMITS[vehicleType].value}.
            Have your package ready before your rider arrives. You'll get their contact once
            they accept{cashEnabled ? ", and cash payments are confirmed with a code only you can see." : "."}
          </p>
        </div>

        </div>

        <div className="shrink-0 px-8 pt-3 pb-[max(1rem,env(safe-area-inset-bottom))] border-t border-white/5 flex flex-col gap-2">
        {error && <p className="text-red-400 text-sm text-center">{error}</p>}
        {!estimate ? (
          <button
            type="submit"
            disabled={loading}
            className="w-full py-4 rounded-full bg-[#1be451] text-neutral-900 font-bold text-lg disabled:opacity-50"
          >
            {loading ? "Checking…" : "Get estimate"}
          </button>
        ) : (
          <div className="flex flex-col gap-2">
            <p className="text-slate-300 text-sm text-center">
              {estimate.distance_km}km, about {Math.round(estimate.duration_min)} min
            </p>
            {confirming ? (
              <>
                <p className="text-white text-center font-semibold">
                  Confirm booking for {estimate.currency} {estimate.total_fare.toLocaleString()}?
                </p>
                <button
                  type="button"
                  onClick={handleSendIt}
                  disabled={loading}
                  className="w-full py-4 rounded-full bg-[#1be451] text-neutral-900 font-bold text-lg disabled:opacity-50"
                >
                  {loading ? "Booking…" : "Yes, book ride"}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirming(false)}
                  disabled={loading}
                  className="w-full py-3 rounded-full border border-white/20 text-white font-semibold disabled:opacity-50"
                >
                  Not yet
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={() => setConfirming(true)}
                disabled={loading}
                className="w-full py-4 rounded-full bg-[#1be451] text-neutral-900 font-bold text-lg disabled:opacity-50"
              >
                Book ride, {estimate.currency} {estimate.total_fare.toLocaleString()}
              </button>
            )}
          </div>
        )}

        </div>
      </form>
    </div>
  );
}
