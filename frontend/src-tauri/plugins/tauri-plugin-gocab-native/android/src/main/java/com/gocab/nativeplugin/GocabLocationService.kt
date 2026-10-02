package com.gocab.nativeplugin

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.IBinder
import android.os.Looper
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.google.android.gms.location.FusedLocationProviderClient
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

private const val CHANNEL_ID = "gocab_location"
private const val CHANNEL_NAME = "GoCab location sharing"
private const val NOTIFICATION_ID = 42001
private const val UPDATE_INTERVAL_MS = 15000L

/**
 * A real Android foreground service — keeps posting the driver's location to
 * the backend independent of the WebView/JS thread, which Android
 * aggressively suspends once the app is backgrounded. Started/stopped by
 * GocabNativePlugin, driven from DriverHome's online toggle. The persistent
 * notification this posts is what lets a *foreground* service hold location
 * access without needing the separate (Play-Store-sensitive)
 * ACCESS_BACKGROUND_LOCATION permission.
 */
class GocabLocationService : Service() {

    private lateinit var fusedLocationClient: FusedLocationProviderClient
    private val httpExecutor = Executors.newSingleThreadExecutor()

    @Volatile private var baseUrl: String? = null
    @Volatile private var authToken: String? = null

    private val locationCallback = object : LocationCallback() {
        override fun onLocationResult(result: LocationResult) {
            val location = result.lastLocation ?: return
            postLocation(location.latitude, location.longitude)
        }
    }

    override fun onCreate() {
        super.onCreate()
        fusedLocationClient = LocationServices.getFusedLocationProviderClient(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                baseUrl = intent.getStringExtra(EXTRA_BASE_URL)
                authToken = intent.getStringExtra(EXTRA_TOKEN)
                ensureChannel()
                startForeground(NOTIFICATION_ID, buildNotification())
                beginLocationUpdates()
            }
            ACTION_UPDATE_TOKEN -> {
                authToken = intent.getStringExtra(EXTRA_TOKEN)
            }
            ACTION_STOP -> {
                fusedLocationClient.removeLocationUpdates(locationCallback)
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        super.onDestroy()
        fusedLocationClient.removeLocationUpdates(locationCallback)
        httpExecutor.shutdown()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    @SuppressLint("MissingPermission") // checked in GocabNativePlugin before this service is ever started
    private fun beginLocationUpdates() {
        val hasFine = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val hasCoarse = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
        if (!hasFine && !hasCoarse) {
            stopSelf()
            return
        }
        val request = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, UPDATE_INTERVAL_MS)
            .setMinUpdateIntervalMillis(UPDATE_INTERVAL_MS)
            .build()
        fusedLocationClient.requestLocationUpdates(request, locationCallback, Looper.getMainLooper())
    }

    private fun postLocation(latitude: Double, longitude: Double) {
        val url = baseUrl ?: return
        val token = authToken ?: return
        httpExecutor.execute {
            var connection: HttpURLConnection? = null
            try {
                connection = URL("$url/rides/location").openConnection() as HttpURLConnection
                connection.requestMethod = "POST"
                connection.setRequestProperty("Content-Type", "application/json")
                connection.setRequestProperty("Authorization", "Bearer $token")
                connection.doOutput = true
                connection.connectTimeout = 10000
                connection.readTimeout = 10000
                OutputStreamWriter(connection.outputStream).use {
                    it.write("""{"latitude":$latitude,"longitude":$longitude}""")
                }
                connection.responseCode // triggers the request
            } catch (e: Exception) {
                android.util.Log.w("GocabLocationService", "Failed to post location", e)
            } finally {
                connection?.disconnect()
            }
        }
    }

    private fun buildNotification(): Notification {
        val launchIntent = packageManager.getLaunchIntentForPackage(packageName)
            ?.setFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        val pendingIntent = PendingIntent.getActivity(
            this, 0, launchIntent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("GoCab")
            .setContentText("Sharing your location while you're online")
            .setSmallIcon(applicationInfo.icon)
            .setOngoing(true)
            .setContentIntent(pendingIntent)
            .build()
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID, CHANNEL_NAME, NotificationManager.IMPORTANCE_LOW,
            )
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    companion object {
        const val ACTION_START = "com.gocab.nativeplugin.action.START_LOCATION"
        const val ACTION_STOP = "com.gocab.nativeplugin.action.STOP_LOCATION"
        const val ACTION_UPDATE_TOKEN = "com.gocab.nativeplugin.action.UPDATE_TOKEN"
        const val EXTRA_BASE_URL = "baseUrl"
        const val EXTRA_TOKEN = "token"
    }
}
