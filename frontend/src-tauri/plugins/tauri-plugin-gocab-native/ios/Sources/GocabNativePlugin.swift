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
//  - getFcmToken / startLocationTracking: reject with a clear message. They
//    need an Apple Developer account (APNs key + push entitlement) and, for
//    background location, the "location" background mode, neither of which
//    exist yet. Every JS caller already catches a rejection, so the app
//    simply behaves as "no native push / foreground-only location" on iOS.
//  - stopLocationTracking / updateLocationToken: no-ops, since nothing is
//    ever started.
class GocabNativePlugin: Plugin {
  @objc public func getFcmToken(_ invoke: Invoke) throws {
    invoke.reject("Push notifications are not set up on iOS yet")
  }

  @objc public func requestNotificationPermission(_ invoke: Invoke) throws {
    UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound]) { granted, _ in
      invoke.resolve(["granted": granted])
    }
  }

  @objc public func startLocationTracking(_ invoke: Invoke) throws {
    invoke.reject("Background location tracking is not available on iOS yet")
  }

  @objc public func stopLocationTracking(_ invoke: Invoke) throws {
    invoke.resolve()
  }

  @objc public func updateLocationToken(_ invoke: Invoke) throws {
    invoke.resolve()
  }
}

@_cdecl("init_plugin_gocab_native")
func initPlugin() -> Plugin {
  return GocabNativePlugin()
}
