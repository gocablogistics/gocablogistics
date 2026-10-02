use tauri::{command, AppHandle, Runtime};

use crate::models::*;
use crate::GocabNativeExt;
use crate::Result;

#[command]
pub(crate) async fn get_fcm_token<R: Runtime>(app: AppHandle<R>) -> Result<FcmTokenResponse> {
    app.gocab_native().get_fcm_token()
}

#[command]
pub(crate) async fn request_notification_permission<R: Runtime>(
    app: AppHandle<R>,
) -> Result<PermissionResponse> {
    app.gocab_native().request_notification_permission()
}

#[command]
pub(crate) async fn start_location_tracking<R: Runtime>(
    app: AppHandle<R>,
    payload: StartLocationTrackingRequest,
) -> Result<()> {
    app.gocab_native().start_location_tracking(payload)
}

#[command]
pub(crate) async fn stop_location_tracking<R: Runtime>(app: AppHandle<R>) -> Result<()> {
    app.gocab_native().stop_location_tracking()
}

#[command]
pub(crate) async fn update_location_token<R: Runtime>(
    app: AppHandle<R>,
    payload: UpdateLocationTokenRequest,
) -> Result<()> {
    app.gocab_native().update_location_token(payload)
}
