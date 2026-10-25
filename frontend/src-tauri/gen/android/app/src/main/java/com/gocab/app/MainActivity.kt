package com.gocab.app

import android.os.Bundle
import android.view.View
import android.webkit.WebView
import androidx.activity.addCallback
import androidx.activity.enableEdgeToEdge
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.gocab.nativeplugin.GocabNativePlugin

// Hand-edited: gen/android is Tauri-generated, but this file is only written by
// `tauri android init` and is not touched by builds.
class MainActivity : TauriActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    // Must come before super.onCreate() — this reads the activity's current
    // theme (Theme.gocab.Starting, set in AndroidManifest.xml) and keeps
    // that splash on screen until the WebView below is actually ready,
    // instead of a blank window while Tauri/Rust initializes.
    installSplashScreen()
    enableEdgeToEdge()
    super.onCreate(savedInstanceState)

    // TauriActivity overrides handleBackNavigation to false, so WryActivity
    // never registers its own back-press callback — without this, a back
    // press anywhere just falls through to the system default and exits the
    // app instantly, from any screen. This callback stays deliberately dumb:
    // it never decides to exit or navigate on its own, only forwards the
    // event to JS, which is the only layer that knows about open overlays
    // (chat/drawer/receipt) and route state. Registered unconditionally, not
    // tied to the WebView, so it's always active even in a cold-start race
    // before JS has attached its own listener — worst case then is back does
    // nothing once, never that the app closes.
    onBackPressedDispatcher.addCallback(this) {
      GocabNativePlugin.notifyBackPressed()
    }

    // enableEdgeToEdge() draws the app behind the status bar and the navigation
    // bar. Pad the content area by those bars (and by the on-screen keyboard) so
    // nothing — the menu button, the action button — ends up underneath them.
    val content = findViewById<View>(android.R.id.content)
    ViewCompat.setOnApplyWindowInsetsListener(content) { view, insets ->
      val bars = insets.getInsets(
        WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout()
      )
      val ime = insets.getInsets(WindowInsetsCompat.Type.ime())
      view.setPadding(bars.left, bars.top, bars.right, maxOf(bars.bottom, ime.bottom))
      WindowInsetsCompat.CONSUMED
    }
  }

  // Native WebViews show a blue/gray "glow" past scroll bounds by default —
  // reads as a browser, not an app. CSS overscroll-behavior (already set in
  // index.css) stops pull-to-refresh/scroll-chaining but can't touch this;
  // it's purely a View-level setting.
  override fun onWebViewCreate(webView: WebView) {
    webView.overScrollMode = View.OVER_SCROLL_NEVER
  }
}
