const COMMANDS: &[&str] = &[
  "get_fcm_token",
  "request_notification_permission",
  "start_location_tracking",
  "stop_location_tracking",
  "update_location_token",
];

fn main() {
  tauri_plugin::Builder::new(COMMANDS)
    .android_path("android")
    .ios_path("ios")
    .build();
}
