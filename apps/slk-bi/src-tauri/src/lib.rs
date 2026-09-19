pub mod commands;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            commands::projects,
            commands::runs,
            commands::run,
            commands::graph,
            commands::roles,
            commands::plans,
            commands::events,
            commands::evidence
        ])
        .run(tauri::generate_context!())
        .expect("SLK BI failed to start");
}
