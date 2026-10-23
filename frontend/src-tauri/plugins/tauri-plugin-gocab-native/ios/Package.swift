// swift-tools-version:6.1
// Bumped from 5.3 — Firebase 12.x (added below for push notifications)
// requires swift-tools-version 6.1 at minimum (confirmed directly against
// its own Package.swift). The newer Firebase 13.x line needs 6.2.1/Xcode
// 26.2, a tighter requirement than necessary here, so this pins to the
// 12.x line specifically to stay on the oldest toolchain that still works.

import PackageDescription

let package = Package(
    name: "tauri-plugin-gocab-native",
    platforms: [
        .macOS(.v10_13),
        // Bumped from .v13 — Firebase 12.x's own minimum is iOS 15, which
        // already matches this app's real deployment target
        // (tauri.conf.json's bundle.iOS.minimumSystemVersion), so this is
        // just the plugin's declared minimum catching up to reality rather
        // than a new constraint on the app itself.
        .iOS(.v15),
    ],
    products: [
        // Products define the executables and libraries a package produces, and make them visible to other packages.
        .library(
            name: "tauri-plugin-gocab-native",
            type: .static,
            targets: ["tauri-plugin-gocab-native"]),
    ],
    dependencies: [
        .package(name: "Tauri", path: "../.tauri/tauri-api"),
        // Pinned to an exact version, not a range — this plugin's iOS build
        // only ever runs in CI with zero local way to test a surprise minor
        // bump, so an exact pin is worth the (manual) upgrade cost later.
        .package(url: "https://github.com/firebase/firebase-ios-sdk", exact: "12.16.0"),
    ],
    targets: [
        // Targets are the basic building blocks of a package. A target can depend on other targets in this package, and on products in packages this package depends on.
        .target(
            name: "tauri-plugin-gocab-native",
            dependencies: [
                .byName(name: "Tauri"),
                .product(name: "FirebaseMessaging", package: "firebase-ios-sdk"),
            ],
            path: "Sources")
            // GoogleService-Info.plist is NOT declared as a resource yet —
            // the file doesn't exist in this repo yet (needs to come from
            // Firebase Console, see GocabNativePlugin.swift's
            // configureFirebaseIfPossible). Declaring a resource that
            // doesn't exist fails the whole package's resolution, not just
            // the push feature, so this stays unset until the real file
            // lands alongside it.
    ]
)
