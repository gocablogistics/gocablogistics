use tauri::{
  plugin::{Builder, TauriPlugin},
  Manager, Runtime,
};

pub use models::*;

#[cfg(desktop)]
mod desktop;
#[cfg(mobile)]
mod mobile;

mod commands;
mod error;
mod models;

pub use error::{Error, Result};

#[cfg(desktop)]
use desktop::GocabNative;
#[cfg(mobile)]
use mobile::GocabNative;

/// Extensions to [`tauri::App`], [`tauri::AppHandle`] and [`tauri::Window`] to access the gocab-native APIs.
pub trait GocabNativeExt<R: Runtime> {
  fn gocab_native(&self) -> &GocabNative<R>;
}

impl<R: Runtime, T: Manager<R>> crate::GocabNativeExt<R> for T {
  fn gocab_native(&self) -> &GocabNative<R> {
    self.state::<GocabNative<R>>().inner()
  }
}

/// Initializes the plugin.
pub fn init<R: Runtime>() -> TauriPlugin<R> {
  Builder::new("gocab-native")
    .invoke_handler(tauri::generate_handler![
      commands::get_fcm_token,
      commands::request_notification_permission,
      commands::start_location_tracking,
      commands::stop_location_tracking,
      commands::update_location_token,
    ])
    .setup(|app, api| {
      #[cfg(mobile)]
      let gocab_native = mobile::init(app, api)?;
      #[cfg(desktop)]
      let gocab_native = desktop::init(app, api)?;
      app.manage(gocab_native);
      Ok(())
    })
    .build()
}
