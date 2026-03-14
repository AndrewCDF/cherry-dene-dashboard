# Cherry Dene Mobile

This folder contains a native iOS SwiftUI app scaffold for the Cherry Dene
dashboard system.

Current scope:

- Native iPhone/iPad app shell
- Tabs for:
  - Office dashboard
  - Shed controller
  - Bore hole controller
  - Farm health
  - Settings
- Embedded `WKWebView` views for the existing Flask dashboards
- Local app settings for controller/dashboard URLs
- Notification permission plumbing ready for future alarm notifications

What this is not yet:

- A complete native rewrite of every dashboard screen
- Real APNs push notification delivery

Recommended setup:

1. Open `CherryDeneMobile.xcodeproj` in Xcode.
2. Set your bundle identifier and Apple team in Signing.
3. If you want to change deployment target or app icons, do it there.

Suggested first-run local URLs:

- Office: `http://127.0.0.1:8090`
- Shed: `http://127.0.0.1:8091`
- Bore hole: `http://127.0.0.1:8092`

For real device use on your farm network, change them to the office/shed Pi IPs.

Push notifications later:

- The app already includes a notification permission manager.
- Real alarm push needs backend support and APNs integration on the server side.

Native alarm support included now:

- The app has a native `Alarms` tab.
- It reads the office dashboard `/api/overview` endpoint.
- It shows active shed and bore hole alarms with sync status.
