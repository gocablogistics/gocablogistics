package com.gocab.app

import android.os.Bundle
import android.view.View
import androidx.activity.enableEdgeToEdge
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat

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
}
