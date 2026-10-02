package com.gocab.nativeplugin

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

private const val CHANNEL_ID = "gocab_default"
private const val CHANNEL_NAME = "GoCab notifications"

/**
 * Registered via this module's own AndroidManifest.xml (merged into the app
 * manifest at build time — see ../../AndroidManifest.xml). Android
 * instantiates this directly, outside Tauri's plugin lifecycle, so it talks
 * back to the JS side through GocabNativePlugin's static bridge rather than
 * holding a Plugin reference of its own.
 */
class GocabFcmService : FirebaseMessagingService() {

    override fun onNewToken(token: String) {
        super.onNewToken(token)
        GocabNativePlugin.notifyTokenRefresh(token)
    }

    override fun onMessageReceived(message: RemoteMessage) {
        super.onMessageReceived(message)

        val title = message.notification?.title ?: message.data["title"] ?: "GoCab"
        val body = message.notification?.body ?: message.data["body"] ?: ""
        val rideId = message.data["ride_id"]

        GocabNativePlugin.notifyPushReceived(rideId, title, body)
        showNotification(title, body, rideId)
    }

    private fun showNotification(title: String, body: String, rideId: String?) {
        ensureChannel()

        val launchIntent = packageManager.getLaunchIntentForPackage(packageName)
            ?.setFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        if (rideId != null) launchIntent?.putExtra("ride_id", rideId)

        val pendingIntent = PendingIntent.getActivity(
            this,
            rideId?.hashCode() ?: 0,
            launchIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            // No custom drawable exists for this plugin module yet — the
            // app's own launcher icon always resolves regardless of which
            // module posts the notification.
            .setSmallIcon(applicationInfo.icon)
            .setContentTitle(title)
            .setContentText(body)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .build()

        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            ContextCompat.checkSelfPermission(this, android.Manifest.permission.POST_NOTIFICATIONS)
            == android.content.pm.PackageManager.PERMISSION_GRANTED
        ) {
            NotificationManagerCompat.from(this)
                .notify(rideId?.hashCode() ?: System.currentTimeMillis().toInt(), notification)
        }
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID, CHANNEL_NAME, NotificationManager.IMPORTANCE_HIGH,
            )
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }
}
