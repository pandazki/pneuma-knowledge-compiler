use crate::state::{Health, Runtime, Snapshot};
use serde::Serialize;
use std::sync::atomic::Ordering;
use tauri::{image::Image, Emitter, Manager};
use tauri_plugin_positioner::{Position, WindowExt};

pub fn init(app: &tauri::AppHandle) -> tauri::Result<()> {
    let window = app.get_webview_window("panel").expect("configured panel");
    #[cfg(target_os = "macos")]
    {
        use tauri_nspanel::WebviewWindowExt;
        let panel = window.to_panel()?;
        panel.set_level(25);
        panel.set_style_mask(1 << 7); // NSWindowStyleMaskNonactivatingPanel
        panel.set_floating_panel(true);
        // NOT hidesOnDeactivate: an accessory app is never "active" when a non-activating
        // panel is ordered front, and AppKit hides such a panel at once — it never appeared
        // on a real screen. The panel hides on its own focus loss (below) instead.
        panel.set_hides_on_deactivate(false);
        panel.set_becomes_key_only_if_needed(false);
        panel.set_has_shadow(true);
        panel.set_released_when_closed(false);
        panel.set_collection_behaviour(
            tauri_nspanel::cocoa::appkit::NSWindowCollectionBehavior::NSWindowCollectionBehaviorCanJoinAllSpaces
                | tauri_nspanel::cocoa::appkit::NSWindowCollectionBehavior::NSWindowCollectionBehaviorFullScreenAuxiliary,
        );
    }
    let handle = app.clone();
    window.on_window_event(move |event| match event {
        tauri::WindowEvent::Focused(false) => {
            // A non-activating panel reports a focus change while it is still being
            // ordered on screen; only a loss after it has settled is the Owner clicking away.
            let shown = handle.state::<Runtime>().shown_at_ms.load(Ordering::Relaxed);
            let age = crate::poller::now_ms().saturating_sub(shown);
            eprintln!("[panel] focus lost {age}ms after show");
            if shown > 0 && age > 400 {
                hide(&handle);
            }
        }
        tauri::WindowEvent::CloseRequested { api, .. } => {
            api.prevent_close();
            hide(&handle);
        }
        _ => {}
    });
    Ok(())
}
#[derive(Clone, Serialize)]
struct Opening {
    state: Snapshot,
    tab: Option<String>,
}
pub fn request_open(app: &tauri::AppHandle, tab: Option<&str>) {
    let runtime = app.state::<Runtime>();
    runtime.wants_open.store(true, Ordering::Relaxed);
    if runtime.ready.load(Ordering::Relaxed) {
        // The hidden webview commits this cached snapshot before asking to become visible.
        let _ = app.emit_to(
            "panel",
            "panel-open",
            Opening {
                state: runtime.cache.read().unwrap().clone(),
                tab: tab.map(str::to_owned),
            },
        );
    }
}
#[tauri::command]
pub fn frontend_ready(app: tauri::AppHandle) {
    let runtime = app.state::<Runtime>();
    runtime.ready.store(true, Ordering::Relaxed);
    if runtime.wants_open.load(Ordering::Relaxed) {
        request_open(&app, None);
    }
}
#[tauri::command]
pub fn reveal_panel(app: tauri::AppHandle) -> Result<(), String> {
    let runtime = app.state::<Runtime>();
    if !runtime.wants_open.load(Ordering::Relaxed) {
        return Ok(());
    }
    let window = app.get_webview_window("panel").ok_or("Panel unavailable")?;
    // Tray events seed positioner. Menu actions can open before a click, so seed from
    // rect on platforms that expose it; TopRight is a safe fallback on Linux.
    let tray_rect = app
        .tray_by_id("pkc")
        .and_then(|tray| tray.rect().ok().flatten());
    if let Some(rect) = tray_rect {
        tauri_plugin_positioner::on_tray_event(
            &app,
            &tauri::tray::TrayIconEvent::Move {
                id: "pkc".into(),
                position: rect.position.to_physical(1.0),
                rect,
            },
        );
        window
            .as_ref()
            .window()
            .move_window(Position::TrayCenter)
            .map_err(|e| e.to_string())?;
    } else {
        window
            .as_ref()
            .window()
            .move_window(Position::TopRight)
            .map_err(|e| e.to_string())?;
    }
    #[cfg(target_os = "macos")]
    {
        use tauri_nspanel::ManagerExt;
        app.get_webview_panel("panel")
            .map_err(|e| {
                eprintln!("[panel] reveal: no NSPanel for the panel window: {e:?}");
                "Panel unavailable"
            })?
            .show();
    }
    if let Ok(pos) = window.outer_position() {
        let size = window.outer_size().ok();
        let scale = window.scale_factor().unwrap_or(1.0);
        eprintln!("[panel] shown at {:?} size {:?} scale {scale}", pos, size);
    } else {
        eprintln!("[panel] shown");
    }
    runtime.shown_at_ms.store(crate::poller::now_ms(), Ordering::Relaxed);
    #[cfg(not(target_os = "macos"))]
    {
        window.show().map_err(|e| e.to_string())?;
        window.set_focus().map_err(|e| e.to_string())?;
    }
    runtime.panel_open.store(true, Ordering::Relaxed);
    runtime.wake.notify_one();
    Ok(())
}
pub fn hide(app: &tauri::AppHandle) {
    let runtime = app.state::<Runtime>();
    runtime.wants_open.store(false, Ordering::Relaxed);
    runtime.panel_open.store(false, Ordering::Relaxed);
    #[cfg(target_os = "macos")]
    {
        use tauri_nspanel::ManagerExt;
        if let Ok(panel) = app.get_webview_panel("panel") {
            panel.order_out(None);
        }
    }
    #[cfg(not(target_os = "macos"))]
    if let Some(window) = app.get_webview_window("panel") {
        let _ = window.hide();
    }
    let _ = app.emit_to("panel", "panel-hidden", ());
    runtime.wake.notify_one();
}
#[tauri::command]
pub fn hide_panel(app: tauri::AppHandle) {
    hide(&app);
}

fn rgb(health: Health) -> [u8; 3] {
    match health {
        Health::Green => [44, 166, 90],
        Health::Amber => [221, 156, 34],
        Health::Red => [215, 70, 68],
        Health::Grey => [145, 148, 150],
    }
}
pub fn icon(health: Health) -> Image<'static> {
    // A 2x template book/spine. macOS tints this glyph itself; its dot is separate.
    let mut pixels = vec![0u8; 36 * 36 * 4];
    for y in 0..36_usize {
        for x in 0..36_usize {
            let border = (6..=27).contains(&x)
                && (4..=31).contains(&y)
                && (!(9..=24).contains(&x) || !(7..=28).contains(&y));
            let spine = (12..=14).contains(&x) && (6..=29).contains(&y);
            if border || spine {
                pixels[(y * 36 + x) * 4 + 3] = 255;
            }
            if !cfg!(target_os = "macos") && (x as i32 - 28).pow(2) + (y as i32 - 28).pow(2) <= 36 {
                let start = (y * 36 + x) * 4;
                pixels[start..start + 3].copy_from_slice(&rgb(health));
                pixels[start + 3] = 255;
            }
        }
    }
    Image::new_owned(pixels, 36, 36)
}
#[cfg(target_os = "macos")]
fn set_native_dot(tray: &tauri::tray::TrayIcon, health: Health) {
    // NSImage's template flag applies to the entire bitmap. An attributed status-button
    // title keeps the glyph native in either appearance without bleaching the status dot.
    let color = rgb(health);
    let _ = tray.with_inner_tray_icon(move |inner| {
        use objc::{class, msg_send, sel, sel_impl, runtime::Object};
        if let Some(item) = inner.ns_status_item() {
            unsafe {
                let item = &*item as *const _ as *mut Object;
                let button: *mut Object = msg_send![item, button];
                let string: *mut Object = msg_send![class!(NSString), stringWithUTF8String: c"●".as_ptr()];
                let key: *mut Object = msg_send![class!(NSString), stringWithUTF8String: c"NSColor".as_ptr()];
                let color: *mut Object = msg_send![class!(NSColor), colorWithSRGBRed: color[0] as f64 / 255.0
                    green: color[1] as f64 / 255.0 blue: color[2] as f64 / 255.0 alpha: 1.0_f64];
                let attrs: *mut Object = msg_send![class!(NSDictionary), dictionaryWithObject: color forKey: key];
                let title: *mut Object = msg_send![class!(NSAttributedString), alloc];
                let title: *mut Object = msg_send![title, initWithString: string attributes: attrs];
                let _: () = msg_send![button, setAttributedTitle: title];
                let _: () = msg_send![title, release];
            }
        }
    });
}
pub fn update_icon(app: &tauri::AppHandle, health: Health) {
    if let Some(tray) = app.tray_by_id("pkc") {
        #[cfg(target_os = "macos")]
        set_native_dot(&tray, health);
        #[cfg(not(target_os = "macos"))]
        let _ = tray.set_icon(Some(icon(health)));
        let label = match health {
            Health::Grey => "Set up your home",
            Health::Green => "All engines ready",
            Health::Amber => "Some services need attention",
            Health::Red => "Docker is unreachable",
        };
        let _ = tray.set_tooltip(Some(format!("PKC · {label}")));
    }
}
