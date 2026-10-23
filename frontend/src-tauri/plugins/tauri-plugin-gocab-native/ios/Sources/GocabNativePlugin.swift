import CoreLocation
import FirebaseCore
import FirebaseMessaging
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
//  - getFcmToken: real — GoogleService-Info.plist is bundled as a resource
//    on this target (see Package.swift) and loaded in
//    configureFirebaseIfPossible, which falls back to a clear "not
//    configured" rejection instead of hanging if that file is ever missing.
//    WKWebView apps can't receive the APNs device token through any normal
//    Tauri/UIKit hook, so this injects application:didRegisterForRemoteNotifications...
//    onto the Tao-generated AppDelegate class at runtime via class_addMethod
//    (confirmed working pattern, adapted from tauri-plugin-mobile-push's
//    iOS implementation — no generated file ever needs editing, which
//    matters a lot here since gen/apple is wiped and regenerated fresh on
//    every CI run with zero local way to test any of this). The device
//    token bridges to Messaging.messaging().apnsToken, which is what makes
//    Messaging.messaging().token(...) resolve to a real FCM token instead
//    of erroring — only after that bridge exists does the normal
//    FirebaseMessaging flow work, same destination as Android's token.
//  - exitApp: no-op. Only ever called from the Android hardware-back "press
//    again to exit" flow — iOS has no hardware back button, and apps can't
//    programmatically background themselves there anyway, so this path
//    should never actually be reached on iOS.
class GocabNativePlugin: Plugin, CLLocationManagerDelegate, MessagingDelegate, UNUserNotificationCenterDelegate {
  private let locationManager = CLLocationManager()
  private var baseUrl: String?
  private var authToken: String?
  private var isTracking = false
  private let urlSession = URLSession(configuration: .ephemeral)

  private var firebaseConfigured = false
  private var apnsDelegateSetUp = false
  private var pendingFcmTokenInvokes: [Invoke] = []

  override init() {
    super.init()
    locationManager.delegate = self
    locationManager.desiredAccuracy = kCLLocationAccuracyBest
    // Matches Android's foreground-service notification's purpose — without
    // this and the "location" UIBackgroundModes entry, iOS suspends updates
    // the moment the app backgrounds, same as if this were never built.
    locationManager.allowsBackgroundLocationUpdates = true
    locationManager.pausesLocationUpdatesAutomatically = false

    configureFirebaseIfPossible()
    // Must be set before launch finishes to not lose a notification tap
    // that launched the app — same reasoning as installing it this early
    // in tauri-plugin-mobile-push's reference implementation. Safe even
    // before Firebase is configured; this delegate is plain UIKit/UN*, not
    // Firebase-specific.
    UNUserNotificationCenter.current().delegate = self
  }

  // GoogleService-Info.plist ships as a bundled SPM resource on this target
  // (see Package.swift) once it exists — Bundle.module is SPM's accessor
  // for a package's own resource bundle, NOT the main app bundle, since
  // Firebase's auto-discovery only looks at Bundle.main and this plugin has
  // no way to place a file into the generated gen/apple app target (unlike
  // Info.plist, which Tauri explicitly documents merging — nothing else
  // gets that treatment). FirebaseOptions(contentsOfFile:) accepts any
  // path, so loading it explicitly from the plugin's own bundle sidesteps
  // the problem entirely instead of fighting Tauri's generated project.
  private func configureFirebaseIfPossible() {
    guard FirebaseApp.app() == nil else {
      firebaseConfigured = true
      return
    }
    guard let path = Bundle.module.path(forResource: "GoogleService-Info", ofType: "plist"),
          let options = FirebaseOptions(contentsOfFile: path) else {
      NSLog("[gocab-native] GoogleService-Info.plist not bundled yet — push notifications stay disabled until it's added")
      return
    }
    FirebaseApp.configure(options: options)
    Messaging.messaging().delegate = self
    firebaseConfigured = true
  }

  @objc public func getFcmToken(_ invoke: Invoke) throws {
    guard firebaseConfigured else {
      invoke.reject("Push notifications are not set up on iOS yet")
      return
    }
    pendingFcmTokenInvokes.append(invoke)
    DispatchQueue.main.async {
      self.setupApnsDelegateIfNeeded()
      UIApplication.shared.registerForRemoteNotifications()
    }
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

  // Runtime-injects the APNs device-token callbacks onto the Tao-generated
  // AppDelegate class — adapted directly from tauri-plugin-mobile-push's
  // iOS implementation (confirmed working technique, not guessed): neither
  // Tauri nor UIKit gives a plugin any normal hook for these, since only
  // whatever class UIApplication.shared.delegate actually is receives them
  // from the OS. class_addMethod only succeeds if the selector doesn't
  // already exist on that class, so this is safe to attempt even if some
  // future plugin/Tauri version already defines it — it just silently
  // no-ops rather than breaking anything. Lazy + idempotent: cheap to call
  // from every getFcmToken, only does real work once.
  private func setupApnsDelegateIfNeeded() {
    guard !apnsDelegateSetUp else { return }
    guard let delegate = UIApplication.shared.delegate else {
      NSLog("[gocab-native] setupApnsDelegateIfNeeded: no UIApplication.delegate yet")
      return
    }
    let cls: AnyClass = type(of: delegate)

    let didRegisterSel = sel_registerName("application:didRegisterForRemoteNotificationsWithDeviceToken:")
    let didRegisterBlock: @convention(block) (AnyObject, UIApplication, Data) -> Void = { [weak self] _, _, deviceToken in
      Messaging.messaging().apnsToken = deviceToken
      Messaging.messaging().token { token, error in
        self?.resolvePendingFcmTokenInvokes(token: token, error: error)
      }
    }
    let didRegisterImp = imp_implementationWithBlock(didRegisterBlock as Any)
    _ = class_addMethod(cls, didRegisterSel, didRegisterImp, "v@:@@")

    let didFailSel = sel_registerName("application:didFailToRegisterForRemoteNotificationsWithError:")
    let didFailBlock: @convention(block) (AnyObject, UIApplication, Error) -> Void = { [weak self] _, _, error in
      self?.resolvePendingFcmTokenInvokes(token: nil, error: error)
    }
    let didFailImp = imp_implementationWithBlock(didFailBlock as Any)
    _ = class_addMethod(cls, didFailSel, didFailImp, "v@:@@")

    apnsDelegateSetUp = true
  }

  private func resolvePendingFcmTokenInvokes(token: String?, error: Error?) {
    let invokes = pendingFcmTokenInvokes
    pendingFcmTokenInvokes.removeAll()
    for invoke in invokes {
      if let token = token {
        invoke.resolve(["token": token])
      } else {
        invoke.reject(error?.localizedDescription ?? "Failed to get FCM token")
      }
    }
  }

  // MessagingDelegate — fires whenever Firebase (re)issues the FCM token,
  // including a silent rotation well after the original getFcmToken call,
  // same event Android's GocabFcmService.onNewToken forwards so the backend
  // never sends to a dead token on either platform.
  func messaging(_ messaging: Messaging, didReceiveRegistrationToken fcmToken: String?) {
    guard let fcmToken = fcmToken else { return }
    // Plugin.trigger(_:data:) takes Tauri's own JSObject (= [String: JSValue],
    // a closed protocol a plain `Any` doesn't conform to — confirmed
    // directly against Tauri's Swift source, not assumed), so this is a
    // dictionary literal of concretely JSValue-conforming values, not the
    // more permissive JsonObject (= [String: Any?]) that Invoke.resolve
    // below accepts.
    trigger("token-refresh", data: ["token": fcmToken])
  }

  // UNUserNotificationCenterDelegate — fires only while the app is actually
  // foregrounded; backgrounded/killed states bypass this and iOS shows the
  // system banner natively from the raw APNs payload with no app code
  // involved. "ride_id" matches push_service.py's push_for_event exactly
  // (data = {"ride_id": str(ride_id)}), same key Android's GocabFcmService
  // reads, so both platforms forward an identical shape to JS.
  func userNotificationCenter(
    _ center: UNUserNotificationCenter,
    willPresent notification: UNNotification,
    withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
  ) {
    let content = notification.request.content
    var payload: JSObject = ["title": content.title, "body": content.body]
    // JSObject's value type is JSValue, not JSValue? — an Optional can't be
    // assigned directly, so the two cases are written out rather than
    // reaching for `??` (which doesn't type-check between String? and
    // NSNull either way: different, unrelated types on each side).
    if let rideId = content.userInfo["ride_id"] as? String {
      payload["rideId"] = rideId
    } else {
      payload["rideId"] = NSNull()
    }
    trigger("push-received", data: payload)
    completionHandler([.banner, .sound, .badge])
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
