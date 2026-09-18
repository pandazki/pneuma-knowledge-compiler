//! The desktop's one AppKit panel. Tauri owns the window and its webview throughout;
//! this module changes its native behavior without a second owner or plugin store.

use cocoa::base::{BOOL, YES};
use objc::{
    class,
    declare::ClassDecl,
    msg_send,
    runtime::{Class, Object, Sel},
    sel, sel_impl,
};
use std::sync::OnceLock;
use tauri::Manager;

unsafe extern "C" {
    fn object_setClass(object: *mut Object, class: *const Class) -> *const Class;
}

fn main_thread() -> Result<(), String> {
    let is_main: BOOL = unsafe { msg_send![class!(NSThread), isMainThread] };
    if is_main == YES {
        Ok(())
    } else {
        Err("AppKit panel access requires the main thread".into())
    }
}

extern "C" fn accepts_keyboard(_: &Object, _: Sel) -> BOOL {
    YES
}

pub fn configure(window: &tauri::WebviewWindow) -> Result<(), Box<dyn std::error::Error>> {
    main_thread()?;
    static PANEL_CLASS: OnceLock<&'static Class> = OnceLock::new();
    let panel_class = PANEL_CLASS.get_or_init(|| {
        let mut declaration = ClassDecl::new("PKCKnowledgePanel", class!(NSPanel))
            .expect("the application registers its panel class once");
        unsafe {
            declaration.add_method(
                sel!(canBecomeKeyWindow),
                accepts_keyboard as extern "C" fn(&Object, Sel) -> BOOL,
            );
        }
        declaration.register()
    });
    let panel = window.ns_window()? as *mut Object;
    unsafe {
        // No ivars or ownership changes: the existing Tauri window remains the owner.
        object_setClass(panel, *panel_class);
        let _: () = msg_send![panel, setStyleMask: 1_usize << 7];
        let _: () = msg_send![panel, setLevel: 25_isize];
        let _: () = msg_send![panel, setFloatingPanel: YES];
        let _: () = msg_send![panel, setHidesOnDeactivate: 0_i8];
        let _: () = msg_send![panel, setBecomesKeyOnlyIfNeeded: 0_i8];
        let _: () = msg_send![panel, setHasShadow: YES];
        let _: () = msg_send![panel, setReleasedWhenClosed: 0_i8];
        // Join all spaces and remain available alongside fullscreen applications.
        let _: () = msg_send![panel, setCollectionBehavior: (1_usize << 0) | (1_usize << 8)];
        let content: *mut Object = msg_send![panel, contentView];
        let children: *mut Object = msg_send![content, subviews];
        let count: usize = msg_send![children, count];
        for index in 0..count {
            let child: *mut Object = msg_send![children, objectAtIndex: index];
            let _: () = msg_send![child, setAutoresizingMask: (1_usize << 1) | (1_usize << 4)];
        }
    }
    Ok(())
}

/// A borrowed native pointer, used immediately by the synchronous UI commands only.
/// The app's window manager retains the window; this module never retains/releases it.
pub fn pointer(app: &tauri::AppHandle) -> Result<*mut Object, String> {
    main_thread()?;
    app.get_webview_window("panel")
        .ok_or("Panel unavailable")?
        .ns_window()
        .map(|window| window as *mut Object)
        .map_err(|error| error.to_string())
}

pub fn show(app: &tauri::AppHandle) -> Result<(), String> {
    let panel = pointer(app)?;
    unsafe {
        let content: *mut Object = msg_send![panel, contentView];
        let _: BOOL = msg_send![panel, makeFirstResponder: content];
        let _: () = msg_send![panel, orderFrontRegardless];
        let _: () = msg_send![panel, makeKeyWindow];
    }
    Ok(())
}

pub fn hide(app: &tauri::AppHandle) {
    if let Ok(panel) = pointer(app) {
        unsafe {
            let _: () = msg_send![panel, orderOut: std::ptr::null_mut::<Object>()];
        }
    }
}
