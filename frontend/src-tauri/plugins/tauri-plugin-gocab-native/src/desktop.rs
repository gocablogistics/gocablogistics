use serde::de::DeserializeOwned;
use tauri::{plugin::PluginApi, AppHandle, Runtime};

use crate::models::*;

pub fn init<R: Runtime, C: DeserializeOwned>(
  app: &AppHandle<R>,
  _api: PluginApi<R, C>,
) -> crate::Result<GocabNative<R>> {
  Ok(GocabNative(app.clone()))
}

/// Access to the gocab-native APIs. Desktop has no FCM/background-location
/// story in this phase — every command is a documented no-op rather than an
/// error, so shared call sites don't need platform branches.
pub struct GocabNative<R: Runtime>(AppHandle<R>);

impl<R: Runtime> GocabNative<R> {
  pub fn get_fcm_token(&self) -> crate::Result<FcmTokenResponse> {
    Ok(FcmTokenResponse { token: None })
  }

  pub fn request_notification_permission(&self) -> crate::Result<PermissionResponse> {
    Ok(PermissionResponse { granted: true })
  }

  pub fn start_location_tracking(&self, _payload: StartLocationTrackingRequest) -> crate::Result<()> {
    Ok(())
  }

  pub fn stop_location_tracking(&self) -> crate::Result<()> {
    Ok(())
  }

  pub fn update_location_token(&self, _payload: UpdateLocationTokenRequest) -> crate::Result<()> {
    Ok(())
  }
}
