use crate::state::{Health, Runtime, Snapshot};
use serde::Serialize;
use std::sync::atomic::Ordering;
use tauri::{image::Image, Emitter, Manager};

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
            // `PKC_TRAY_PIN=1` keeps the panel up through focus changes: a review hand for
            // screenshots taken while the reviewer is typing elsewhere; never set by users.
            let pinned = std::env::var_os("PKC_TRAY_PIN").is_some();
            if shown > 0 && age > 400 && !pinned {
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
    if let Some(tab) = tab {
        *runtime.wanted_tab.lock().unwrap() = Some(tab.to_owned());
    }
    let tab = runtime.wanted_tab.lock().unwrap().clone();
    let tab = tab.as_deref();
    if runtime.ready.load(Ordering::Relaxed) {
        *runtime.wanted_tab.lock().unwrap() = None;
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
    // The panel belongs on the display the Owner is looking at: the one under the mouse at
    // the moment of the click (a tray icon exists on every menu bar, and Tauri's window
    // position API does not move a converted NSPanel). AppKit directly: NSEvent's mouse
    // location, NSScreen's visible frame, the panel's own setFrameOrigin — points, y up.
    #[cfg(target_os = "macos")]
    {
        use tauri_nspanel::cocoa::base::{id, nil};
        use tauri_nspanel::cocoa::foundation::{NSPoint, NSRect};
        use tauri_nspanel::objc::{class, msg_send, sel, sel_impl};
        use tauri_nspanel::ManagerExt;
        let panel = app.get_webview_panel("panel").map_err(|_| "Panel unavailable")?;
        unsafe {
            let mouse: NSPoint = msg_send![class!(NSEvent), mouseLocation];
            let screens: id = msg_send![class!(NSScreen), screens];
            let count: usize = msg_send![screens, count];
            let mut target: id = nil;
            for i in 0..count {
                let screen: id = msg_send![screens, objectAtIndex: i];
                let frame: NSRect = msg_send![screen, frame];
                if mouse.x >= frame.origin.x && mouse.x < frame.origin.x + frame.size.width
                    && mouse.y >= frame.origin.y && mouse.y < frame.origin.y + frame.size.height
                {
                    target = screen;
                    break;
                }
            }
            if target == nil {
                target = msg_send![class!(NSScreen), mainScreen];
            }
            if target != nil {
                let visible: NSRect = msg_send![target, visibleFrame];
                eprintln!("[panel] screen visible frame origin ({:.0}, {:.0})", visible.origin.x, visible.origin.y);
                let frame: NSRect = msg_send![&*panel, frame];
                let margin = 8.0;
                let x = (mouse.x - frame.size.width / 2.0)
                    .max(visible.origin.x + margin)
                    .min(visible.origin.x + visible.size.width - frame.size.width - margin);
                let y = visible.origin.y + visible.size.height - frame.size.height - margin;
                eprintln!("[panel] mouse ({:.0}, {:.0}) → origin ({x:.0}, {y:.0}) on a {:.0}x{:.0} screen", mouse.x, mouse.y, visible.size.width, visible.size.height);
                let _: () = msg_send![&*panel, setFrameOrigin: NSPoint::new(x, y)];
            }
        }
    }
    #[cfg(not(target_os = "macos"))]
    {
        let size = window.outer_size().map_err(|e| e.to_string())?;
        if let Ok(Some(monitor)) = app.primary_monitor() {
            let scale = monitor.scale_factor();
            let margin = (8.0 * scale) as i32;
            let x = monitor.position().x + monitor.size().width as i32 - size.width as i32 - margin;
            let y = monitor.position().y + (30.0 * scale) as i32;
            window.set_position(tauri::PhysicalPosition::new(x, y)).map_err(|e| e.to_string())?;
        }
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
    eprintln!("[panel] shown");
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

/// The panel takes the height of its content: a paper card does not stretch. Called by the
/// frontend after layout with the document's height in points; clamped, and the top edge
/// stays where it is (AppKit grows a window downward from its bottom-left origin otherwise).
#[tauri::command]
pub fn fit_panel(app: tauri::AppHandle, height: f64) -> Result<(), String> {
    eprintln!("[panel] fit requested for content {height:.0}");
    let height = height.clamp(280.0, 720.0);
    #[cfg(target_os = "macos")]
    {
        use tauri_nspanel::cocoa::foundation::{NSPoint, NSRect};
        use tauri_nspanel::objc::{msg_send, sel, sel_impl};
        use tauri_nspanel::ManagerExt;
        let panel = app.get_webview_panel("panel").map_err(|_| "Panel unavailable")?;
        unsafe {
            let frame: NSRect = msg_send![&*panel, frame];
            if (frame.size.height - height).abs() < 1.0 {
                return Ok(());
            }
            let top_left = NSPoint::new(frame.origin.x, frame.origin.y + frame.size.height);
            panel.set_content_size(frame.size.width, height);
            let _: () = msg_send![&*panel, setFrameTopLeftPoint: top_left];
            let after: NSRect = msg_send![&*panel, frame];
            eprintln!("[panel] fit {:.0}x{:.0}@({:.0},{:.0}) -> {:.0}x{:.0}@({:.0},{:.0}) for content {height:.0}",
                frame.size.width, frame.size.height, frame.origin.x, frame.origin.y,
                after.size.width, after.size.height, after.origin.x, after.origin.y);
        }
    }
    #[cfg(not(target_os = "macos"))]
    {
        if let Some(window) = app.get_webview_window("panel") {
            let width = window.outer_size().map(|s| s.width as f64 / window.scale_factor().unwrap_or(1.0)).unwrap_or(380.0);
            window.set_size(tauri::LogicalSize::new(width, height)).map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}

