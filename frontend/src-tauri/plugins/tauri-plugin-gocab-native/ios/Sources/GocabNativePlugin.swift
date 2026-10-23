import CoreLocation
import SwiftRs
import Tauri
import UIKit
import UserNotifications
import WebKit

// iOS half of the gocab-native plugin. Mirrors the Kotlin GocabNativePlugin
// command for command, so the JS bridge (src/lib/nativePush.ts,
// src/lib/nativeLocation.ts) needs no iOS special-casing.
//
// What's real today vs. stubbed:
//  - requestNotificationPermission: real (UNUserNotificationCenter).
//  - startLocationTracking / stopLocationTracking / updateLocationToken:
//    real — CLLocationManager with allowsBackgroundLocationUpdates, POSTing
//    to {baseUrl}/rides/location on every fix, same endpoint/JSON shape/
//    Bearer-token pattern as Android's GocabLocationService (a foreground
//    service there; here, background location updates + the "location"
//    UIBackgroundModes entry is iOS's equivalent of "keep running while
//    backgrounded"). Needs NSLocationAlwaysAndWhenInUseUsageDescription and
//    the location background mode in Info.plist.
//  - getFcmToken: rejects with a clear message — needs the Firebase iOS SDK
//    plus APNs key (Apple Developer account) wiring, not done yet. Every JS
//    caller already catches a rejection, so the app simply behaves as
//    "no native push" on iOS until that's built.
//  - exitApp: no-op. Only ever called from the Android hardware-back "press
//    again to exit" flow — iOS has no hardware back button, and apps can't
//    programmatically background themselves there anyway, so this path
//    should never actually be reached on iOS.
class GocabNativePlugin: Plugin, CLLocationManagerDelegate {
  private let locationManager = CLLocationManager()
  private var baseUrl: String?
  private var authToken: String?
  private var isTracking = false
  private let urlSession = URLSession(configuration: .ephemeral)

  override init() {
    super.init()
    locationManager.delegate = self
    locationManager.desiredAccuracy = kCLLocationAccuracyBest
    // Matches Android's foreground-service notification's purpose — without
    // this and the "location" UIBackgroundModes entry, iOS suspends updates
    // the moment the app backgrounds, same as if this were never built.
    locationManager.allowsBackgroundLocationUpdates = true
    locationManager.pausesLocationUpdatesAutomatically = false
  }

  @objc public func getFcmToken(_ invoke: Invoke) throws {
    invoke.reject("Push notifications are not set up on iOS yet")
  }

  @objc public func requestNotificationPermission(_ invoke: Invoke) throws {
    UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound]) { granted, _ in
      invoke.resolve(["granted": granted])
    }
  }

  @objc public func startLocationTracking(_ invoke: Invoke) throws {
    let args = try invoke.parseArgs(StartLocationTrackingArgs.self)
    baseUrl = args.baseUrl
    authToken = args.token

    // Static call, not the newer instance property — Package.swift declares
    // iOS 13 as this plugin's minimum, and the instance property needs 14+.
    // Deprecated since 14.0 but still fully functional; Tauri's own
    // official geolocation plugin uses the exact same call for the same
    // reason (confirmed directly in its source).
    let status = CLLocationManager.authorizationStatus()
    switch status {
    case .denied, .restricted:
      invoke.reject("Location permission not granted")
      return
    case .authorizedAlways:
      beginUpdating()
    case .authorizedWhenInUse, .notDetermined:
      // Background delivery specifically needs "Always", not just
      // "WhenInUse" (already granted/requested elsewhere for one-shot
      // pickup/booking lookups via the official geolocation plugin) — this
      // is the first point the app actually needs it, matching Apple's
      // guidance to ask only once the feature that needs it is used.
      // didChangeAuthorization below starts updating once it resolves.
      locationManager.requestAlwaysAuthorization()
    @unknown default:
      locationManager.requestAlwaysAuthorization()
    }
    invoke.resolve()
  }

  @objc public func stopLocationTracking(_ invoke: Invoke) throws {
    locationManager.stopUpdatingLocation()
    isTracking = false
    baseUrl = nil
    authToken = nil
    invoke.resolve()
  }

  @objc public func updateLocationToken(_ invoke: Invoke) throws {
    let args = try invoke.parseArgs(UpdateLocationTokenArgs.self)
    authToken = args.token
    invoke.resolve()
  }

  @objc public func exitApp(_ invoke: Invoke) throws {
    invoke.resolve()
  }

  private func beginUpdating() {
    guard !isTracking else { return }
    isTracking = true
    locationManager.startUpdatingLocation()
  }

  public func locationManager(_ manager: CLLocationManager, didChangeAuthorization status: CLAuthorizationStatus) {
    guard baseUrl != nil, authToken != nil else { return }
    if status == .authorizedAlways {
      beginUpdating()
    }
  }

  public func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
    guard let location = locations.last else { return }
    postLocation(latitude: location.coordinate.latitude, longitude: location.coordinate.longitude)
  }

  // Best-effort, same as Android's version — a dropped ping isn't worth
  // surfacing to JS (nothing there is listening for it either way), the
  // next fix a few seconds later supersedes it regardless.
  private func postLocation(latitude: Double, longitude: Double) {
    guard let baseUrl = baseUrl, let token = authToken,
          let url = URL(string: "\(baseUrl)/rides/location") else { return }

    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    request.timeoutInterval = 10
    request.httpBody = try? JSONSerialization.data(withJSONObject: [
      "latitude": latitude,
      "longitude": longitude,
    ])

    urlSession.dataTask(with: request).resume()
  }
}

private class StartLocationTrackingArgs: Decodable {
  let baseUrl: String
  let token: String
}

private class UpdateLocationTokenArgs: Decodable {
  let token: String
}

@_cdecl("init_plugin_gocab_native")
func initPlugin() -> Plugin {
  return GocabNativePlugin()
}
