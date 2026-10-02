use serde::de::DeserializeOwned;
use tauri::{
  plugin::{PluginApi, PluginHandle},
  AppHandle, Runtime,
};

use crate::models::*;

// Binds the Swift `init_plugin_gocab_native` (ios/Sources/GocabNativePlugin.swift).
#[cfg(target_os = "ios")]
tauri::ios_plugin_binding!(init_plugin_gocab_native);

// Registers the native half: the Kotlin plugin class on Android, the Swift
// plugin on iOS. `mobile` is exactly those two targets, so one of the two
// `let handle` lines always exists.
pub fn init<R: Runtime, C: DeserializeOwned>(
  _app: &AppHandle<R>,
  api: PluginApi<R, C>,
) -> crate::Result<GocabNative<R>> {
  #[cfg(target_os = "android")]
  let handle = api.register_android_plugin("com.gocab.nativeplugin", "GocabNativePlugin")?;
  #[cfg(target_os = "ios")]
  let handle = api.register_ios_plugin(init_plugin_gocab_native)?;
  Ok(GocabNative(handle))
}

/// Access to the gocab-native APIs.
pub struct GocabNative<R: Runtime>(PluginHandle<R>);

impl<R: Runtime> GocabNative<R> {
  pub fn get_fcm_token(&self) -> crate::Result<FcmTokenResponse> {
    self.0.run_mobile_plugin("getFcmToken", ()).map_err(Into::into)
  }

  pub fn request_notification_permission(&self) -> crate::Result<PermissionResponse> {
    self.0
      .run_mobile_plugin("requestNotificationPermission", ())
      .map_err(Into::into)
  }

  pub fn start_location_tracking(&self, payload: StartLocationTrackingRequest) -> crate::Result<()> {
    self.0
      .run_mobile_plugin("startLocationTracking", payload)
      .map_err(Into::into)
  }

  pub fn stop_location_tracking(&self) -> crate::Result<()> {
    self.0
      .run_mobile_plugin("stopLocationTracking", ())
      .map_err(Into::into)
  }

  pub fn update_location_token(&self, payload: UpdateLocationTokenRequest) -> crate::Result<()> {
    self.0
      .run_mobile_plugin("updateLocationToken", payload)
      .map_err(Into::into)
  }
}
