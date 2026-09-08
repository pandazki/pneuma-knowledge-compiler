mod panel;
mod pkchome;
mod poller;
mod state;

use state::{Runtime, Snapshot};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    RwLock,
};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager,
};

#[tauri::command]
fn get_state(runtime: tauri::State<'_, Runtime>) -> Snapshot {
    runtime.cache.read().unwrap().clone()
}
#[tauri::command]
fn quit(app: tauri::AppHandle) {
    app.exit(0);
}

pub fn run() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(
            tauri_plugin_autostart::Builder::new()
                .app_name("PKC")
                .build(),
        )
        .plugin(tauri_plugin_positioner::init());
    #[cfg(target_os = "macos")]
    let builder = builder.plugin(tauri_nspanel::init());
    builder
        .invoke_handler(tauri::generate_handler![
            get_state,
            pkchome::run_action,
            pkchome::search,
            panel::frontend_ready,
            panel::reveal_panel,
            panel::hide_panel,
            quit
        ])
        .setup(|app| {
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);
            let home = poller::home_path();
            let (login_path, initial) = tauri::async_runtime::block_on(async {
                let path = pkchome::login_path().await;
                let initial = poller::shallow(&home, &path).await;
                (path, initial)
            });
            let health = initial.health();
            app.manage(Runtime {
                home,
                login_path,
                client: reqwest::Client::builder()
                    .no_proxy()
                    .redirect(reqwest::redirect::Policy::none())
                    .timeout(std::time::Duration::from_secs(5))
                    .build()?,
                cache: RwLock::new(Snapshot {
                    shallow: initial,
                    fetched_at: poller::now_ms(),
                    ..Default::default()
                }),
                panel_open: AtomicBool::new(false),
                shown_at_ms: std::sync::atomic::AtomicU64::new(0),
                wants_open: AtomicBool::new(false),
                ready: AtomicBool::new(false),
                wake: tokio::sync::Notify::new(),
                action_lock: tokio::sync::Mutex::new(()),
            });
            panel::init(app.handle())?;
            let open = MenuItem::with_id(app, "open", "Open PKC", true, None::<&str>)?;
            let search = MenuItem::with_id(app, "search", "Search", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit PKC", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &search, &quit])?;
            let tray = TrayIconBuilder::with_id("pkc")
                .icon(panel::icon(health))
                .icon_as_template(cfg!(target_os = "macos"))
                .tooltip("PKC")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open" => panel::request_open(app, None),
                    "search" => panel::request_open(app, Some("search")),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    tauri_plugin_positioner::on_tray_event(tray.app_handle(), &event);
                    if matches!(
                        event,
                        TrayIconEvent::Click {
                            button: MouseButton::Left,
                            button_state: MouseButtonState::Up,
                            ..
                        }
                    ) {
                        let runtime = tray.app_handle().state::<Runtime>();
                        if runtime.panel_open.load(Ordering::Relaxed) {
                            panel::hide(tray.app_handle());
                        } else {
                            panel::request_open(tray.app_handle(), None);
                        }
                    }
                })
                .build(app)?;
            #[cfg(target_os = "macos")]
            tray.set_title(Some("●"))?;
            #[cfg(not(target_os = "macos"))]
            let _ = tray;
            panel::update_icon(app.handle(), health);
            tauri::async_runtime::spawn(poller::run(app.handle().clone()));
            // A diagnostic hand: `PKC_TRAY_OPEN=1` opens the panel right after launch, so a
            // terminal can exercise the open path without a click on the menu bar.
            if std::env::var_os("PKC_TRAY_OPEN").is_some() {
                panel::request_open(app.handle(), None);
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("could not run PKC desktop");
}
