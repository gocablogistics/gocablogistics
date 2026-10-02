package com.gocab.nativeplugin

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.webkit.WebView
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import com.google.firebase.messaging.FirebaseMessaging
import java.lang.ref.WeakReference

@InvokeArg
class StartLocationTrackingArgs {
    var baseUrl: String? = null
    var token: String? = null
}

@InvokeArg
class UpdateLocationTokenArgs {
    var token: String? = null
}

@TauriPlugin
class GocabNativePlugin(private val activity: Activity) : Plugin(activity) {

    override fun load(webView: WebView) {
        super.load(webView)
        // GocabFcmService is instantiated directly by Android outside Tauri's
        // plugin lifecycle, so it can't call this.trigger(...) itself — it
        // reaches the live plugin instance (when there is one) through here.
        activeInstance = WeakReference(this)
    }

    @Command
    fun getFcmToken(invoke: Invoke) {
        FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
            if (task.isSuccessful) {
                val ret = JSObject()
                ret.put("token", task.result)
                invoke.resolve(ret)
            } else {
                invoke.reject("Failed to get FCM token: ${task.exception?.message}")
            }
        }
    }

    // Android 13+ shows no notification at all until the app has asked for
    // this permission at runtime — declaring it in the manifest isn't enough.
    // Resolves immediately with the current state; the system dialog is
    // answered by the user afterwards.
    @Command
    fun requestNotificationPermission(invoke: Invoke) {
        val granted = Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            ContextCompat.checkSelfPermission(activity, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        if (!granted) {
            activity.runOnUiThread {
                ActivityCompat.requestPermissions(activity, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 4242)
            }
        }
        val ret = JSObject()
        ret.put("granted", granted)
        invoke.resolve(ret)
    }

    @Command
    fun startLocationTracking(invoke: Invoke) {
        val hasFine = ContextCompat.checkSelfPermission(activity, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val hasCoarse = ContextCompat.checkSelfPermission(activity, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
        if (!hasFine && !hasCoarse) {
            invoke.reject("Location permission not granted")
            return
        }

        val args = invoke.parseArgs(StartLocationTrackingArgs::class.java)
        val baseUrl = args.baseUrl
        val token = args.token
        if (baseUrl.isNullOrEmpty() || token.isNullOrEmpty()) {
            invoke.reject("baseUrl and token are required")
            return
        }

        val intent = Intent(activity, GocabLocationService::class.java).apply {
            action = GocabLocationService.ACTION_START
            putExtra(GocabLocationService.EXTRA_BASE_URL, baseUrl)
            putExtra(GocabLocationService.EXTRA_TOKEN, token)
        }
        ContextCompat.startForegroundService(activity, intent)
        invoke.resolve()
    }

    @Command
    fun stopLocationTracking(invoke: Invoke) {
        val intent = Intent(activity, GocabLocationService::class.java).apply {
            action = GocabLocationService.ACTION_STOP
        }
        activity.startService(intent)
        invoke.resolve()
    }

    @Command
    fun updateLocationToken(invoke: Invoke) {
        val args = invoke.parseArgs(UpdateLocationTokenArgs::class.java)
        val token = args.token
        if (token.isNullOrEmpty()) {
            invoke.reject("token is required")
            return
        }
        val intent = Intent(activity, GocabLocationService::class.java).apply {
            action = GocabLocationService.ACTION_UPDATE_TOKEN
            putExtra(GocabLocationService.EXTRA_TOKEN, token)
        }
        activity.startService(intent)
        invoke.resolve()
    }

    companion object {
        private var activeInstance: WeakReference<GocabNativePlugin>? = null

        /** Forwards a refreshed FCM token to JS as `plugin:gocab-native://token-refresh`. */
        fun notifyTokenRefresh(token: String) {
            val data = JSObject()
            data.put("token", token)
            activeInstance?.get()?.trigger("token-refresh", data)
        }

        /** Forwards a push received while the webview is alive as `plugin:gocab-native://push-received`. */
        fun notifyPushReceived(rideId: String?, title: String?, body: String?) {
            val data = JSObject()
            data.put("rideId", rideId)
            data.put("title", title)
            data.put("body", body)
            activeInstance?.get()?.trigger("push-received", data)
        }
    }
}
